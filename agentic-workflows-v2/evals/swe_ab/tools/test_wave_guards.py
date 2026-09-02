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
