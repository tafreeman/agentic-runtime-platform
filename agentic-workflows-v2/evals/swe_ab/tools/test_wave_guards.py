"""Guards that keep a wave from repeating or overwriting graded evidence.

Run from the kit: ``uv run python -m pytest tools -q``. Lives next to the
scripts rather than under a ``tests/`` package so pytest's rootdir insertion
puts ``tools/`` on ``sys.path`` (the scripts import each other the same way
when run directly) and the module name cannot collide with the runtime
package's own ``tests``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import run_wave
from drawn_instances import previously_drawn_instance_ids


def _write_manifest(path: Path, ids: list[str]) -> None:
    rows = [
        {"sample_id": i, "input": {}, "reference": None, "metadata": {"instance_id": i}}
        for i in ids
    ]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _write_report(path: Path, ids: list[str]) -> None:
    samples = [
        {
            "sample": {"sample_id": i, "metadata": {"instance_id": i}},
            "execution": {"sample_id": i, "status": "completed"},
            "grade": {"status": "pass"},
        }
        for i in ids
    ]
    path.write_text(json.dumps({"samples": samples, "summary": {}}), encoding="utf-8")


class TestPreviouslyDrawn:
    """The exclusion set must come from tracked evidence, not only the case tree."""

    def test_unions_manifests_and_reports(self, tmp_path: Path) -> None:
        (tmp_path / "dataset").mkdir()
        (tmp_path / "reports").mkdir()
        _write_manifest(
            tmp_path / "dataset" / "cases.swebench.wave1.jsonl", ["django__django-1"]
        )
        _write_manifest(
            tmp_path / "dataset" / "cases.swebench.jsonl", ["django__django-2"]
        )
        _write_report(
            tmp_path / "reports" / "arm-a-direct-wave2.json", ["astropy__astropy-3"]
        )

        assert previously_drawn_instance_ids(tmp_path) == {
            "django__django-1",
            "django__django-2",
            "astropy__astropy-3",
        }

    def test_mutation_manifests_are_not_swebench(self, tmp_path: Path) -> None:
        (tmp_path / "dataset").mkdir()
        _write_manifest(tmp_path / "dataset" / "cases.jsonl", ["ARP-MUT-001"])
        _write_manifest(tmp_path / "dataset" / "cases.memoryctl.jsonl", ["MC-001"])

        assert previously_drawn_instance_ids(tmp_path) == set()

    def test_empty_kit_yields_empty_set(self, tmp_path: Path) -> None:
        assert previously_drawn_instance_ids(tmp_path) == set()

    def test_malformed_manifest_is_not_swallowed(self, tmp_path: Path) -> None:
        (tmp_path / "dataset").mkdir()
        (tmp_path / "dataset" / "cases.swebench.wave9.jsonl").write_text(
            "{not json", encoding="utf-8"
        )

        with pytest.raises(json.JSONDecodeError):
            previously_drawn_instance_ids(tmp_path)


class TestRebuildGuard:
    """A graded wave's number is spent; --rebuild-cases must not reuse it."""

    def test_existing_wave_reports_match_only_that_wave(self, tmp_path: Path) -> None:
        reports = tmp_path / "reports"
        reports.mkdir()
        for name in (
            "arm-a-direct-wave1.json",
            "arm-b-review-loop-wave1.json",
            "arm-a-direct-wave11.json",
        ):
            (reports / name).write_text("{}", encoding="utf-8")

        assert [p.name for p in run_wave.existing_wave_reports(tmp_path, 1)] == [
            "arm-a-direct-wave1.json",
            "arm-b-review-loop-wave1.json",
        ]
        assert [p.name for p in run_wave.existing_wave_reports(tmp_path, 11)] == [
            "arm-a-direct-wave11.json"
        ]
        assert run_wave.existing_wave_reports(tmp_path, 12) == []
        assert run_wave.existing_wave_reports(tmp_path / "missing", 1) == []

    def test_main_refuses_rebuild_of_a_graded_wave(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (tmp_path / "dataset").mkdir()
        (tmp_path / "reports").mkdir()
        (tmp_path / "reports" / "arm-a-direct-wave11.json").write_text(
            "{}", encoding="utf-8"
        )
        monkeypatch.setattr(run_wave, "KIT_ROOT", tmp_path)
        monkeypatch.setattr(
            sys,
            "argv",
            ["run_wave.py", "--wave", "11", "--size", "16", "--rebuild-cases"],
        )

        assert run_wave.main() == 1

        err = capsys.readouterr().err
        assert "refusing --rebuild-cases" in err
        assert "arm-a-direct-wave11.json" in err


class TestMix:
    """Bonus slices drain and drop; core slices still pin the population."""

    def test_scale_keeps_every_slice_and_its_kind(self) -> None:
        mix = [("a/a", "d", 24, run_wave.CORE), ("b/b", "d", 1, run_wave.BONUS)]

        scaled = run_wave.scale_mix(mix, 5)

        assert [kind for *_, kind in scaled] == [run_wave.CORE, run_wave.BONUS]
        assert all(count >= 1 for _, _, count, _ in scaled)
        assert scaled[0][2] == 5

    def test_only_a_core_shortfall_is_fatal(self) -> None:
        assert run_wave.shortfall_is_fatal(run_wave.CORE) is True
        assert run_wave.shortfall_is_fatal(run_wave.BONUS) is False

    def test_wave_mix_declares_a_kind_and_keeps_a_core(self) -> None:
        kinds = {kind for *_, kind in run_wave.WAVE_MIX}

        assert kinds <= {run_wave.CORE, run_wave.BONUS}
        assert run_wave.CORE in kinds


def _rows(ids: list[str]) -> list[str]:
    return [json.dumps({"sample_id": i, "input": {}}) for i in ids]


class TestRerunPreservesGradedArms:
    """A plain rerun keeps complete reports and runs only the missing arm."""

    def test_report_is_complete_only_for_the_manifest_sample_set(
        self, tmp_path: Path
    ) -> None:
        rows = _rows(["django__django-1", "django__django-2"])
        full = tmp_path / "full.json"
        _write_report(full, ["django__django-1", "django__django-2"])
        partial = tmp_path / "partial.json"
        _write_report(partial, ["django__django-1"])
        other = tmp_path / "other.json"
        _write_report(other, ["django__django-1", "django__django-9"])
        broken = tmp_path / "broken.json"
        broken.write_text("{not json", encoding="utf-8")

        assert run_wave.report_is_complete(full, rows) is True
        assert run_wave.report_is_complete(partial, rows) is False
        assert run_wave.report_is_complete(other, rows) is False
        assert run_wave.report_is_complete(broken, rows) is False
        assert run_wave.report_is_complete(tmp_path / "absent.json", rows) is False

    def test_plan_runs_only_missing_arms(self, tmp_path: Path) -> None:
        (tmp_path / "reports").mkdir()
        rows = _rows(["django__django-1"])

        assert run_wave.plan_arms(tmp_path, 7, rows) == (["a", "b"], [], [])

        _write_report(run_wave.arm_report_path(tmp_path, 7, "a"), ["django__django-1"])
        to_run, preserved, blocking = run_wave.plan_arms(tmp_path, 7, rows)
        assert to_run == ["b"]
        assert [p.name for p in preserved] == ["arm-a-direct-wave7.json"]
        assert blocking == []

        _write_report(run_wave.arm_report_path(tmp_path, 7, "b"), ["django__django-1"])
        assert run_wave.plan_arms(tmp_path, 7, rows)[0] == []

    def test_plan_blocks_on_a_report_that_does_not_cover_the_manifest(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "reports").mkdir()
        rows = _rows(["django__django-1", "django__django-2"])
        _write_report(run_wave.arm_report_path(tmp_path, 7, "b"), ["django__django-1"])

        to_run, preserved, blocking = run_wave.plan_arms(tmp_path, 7, rows)

        assert to_run == ["a"]
        assert preserved == []
        assert [p.name for p in blocking] == ["arm-b-review-loop-wave7.json"]

    def _kit_with_manifest(self, tmp_path: Path, wave: int, ids: list[str]) -> None:
        (tmp_path / "dataset").mkdir()
        (tmp_path / "reports").mkdir()
        _write_manifest(tmp_path / "dataset" / f"cases.swebench.wave{wave}.jsonl", ids)

    def test_main_reruns_only_the_arm_without_a_report(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._kit_with_manifest(tmp_path, 7, ["django__django-1"])
        _write_report(run_wave.arm_report_path(tmp_path, 7, "a"), ["django__django-1"])
        calls: list[list[str]] = []
        monkeypatch.setattr(run_wave, "run", lambda argv, **_: calls.append(argv) or 0)
        monkeypatch.setattr(run_wave, "KIT_ROOT", tmp_path)
        monkeypatch.setattr(sys, "argv", ["run_wave.py", "--wave", "7", "--size", "16"])

        assert run_wave.main() == 0

        arms = [argv[argv.index("--arm") + 1] for argv in calls]
        assert arms == ["b"]

    def test_main_refuses_a_fully_graded_wave(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._kit_with_manifest(tmp_path, 7, ["django__django-1"])
        for arm in ("a", "b"):
            _write_report(
                run_wave.arm_report_path(tmp_path, 7, arm), ["django__django-1"]
            )
        calls: list[list[str]] = []
        monkeypatch.setattr(run_wave, "run", lambda argv, **_: calls.append(argv) or 0)
        monkeypatch.setattr(run_wave, "KIT_ROOT", tmp_path)
        monkeypatch.setattr(sys, "argv", ["run_wave.py", "--wave", "7", "--size", "16"])

        assert run_wave.main() == 1
        assert calls == []
        assert "both arms are already graded" in capsys.readouterr().err

    def test_main_refuses_mining_when_reports_exist_without_a_manifest(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (tmp_path / "dataset").mkdir()
        (tmp_path / "reports").mkdir()
        _write_report(run_wave.arm_report_path(tmp_path, 7, "a"), ["django__django-1"])
        calls: list[list[str]] = []
        monkeypatch.setattr(run_wave, "run", lambda argv, **_: calls.append(argv) or 0)
        monkeypatch.setattr(run_wave, "KIT_ROOT", tmp_path)
        monkeypatch.setattr(sys, "argv", ["run_wave.py", "--wave", "7", "--size", "16"])

        assert run_wave.main() == 1
        assert calls == []
        assert "refusing to mine cases" in capsys.readouterr().err
