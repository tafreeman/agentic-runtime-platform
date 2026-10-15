"""Tests for the SWE-rebench case builder.

Run from the kit: ``uv run python -m pytest tools -q``. Docker and the
``datasets`` loader are replaced with fakes, so nothing here pulls an image or
touches the network.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import build_rebench_cases as brc
import pytest

ONE_FILE_PATCH = (
    "diff --git a/pkg/core.py b/pkg/core.py\n"
    "--- a/pkg/core.py\n"
    "+++ b/pkg/core.py\n"
    "@@ -1 +1 @@\n"
    "-old\n"
    "+new\n"
)
TWO_FILE_PATCH = ONE_FILE_PATCH + ONE_FILE_PATCH.replace("core.py", "util.py")


def _args(**overrides: Any) -> argparse.Namespace:
    base = {
        "after": None,
        "before": None,
        "require_test_patch": True,
        "lite_only": False,
        "max_source_files": 1,
        "max_patch_lines": 60,
        "min_difficulty": None,
        "max_difficulty": None,
        "model_cutoff": "2025-12-31",
        "max_changed_lines": 120,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _row(instance_id: str = "org__repo-1", **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "instance_id": instance_id,
        "repo": "org/repo",
        "created_at": "2026-02-01T00:00:00Z",
        "patch": ONE_FILE_PATCH,
        "test_patch": "diff --git a/tests/test_core.py b/tests/test_core.py\n",
        "FAIL_TO_PASS": ["tests/test_core.py::test_new"],
        "PASS_TO_PASS": ["tests/test_core.py::test_old"],
        "problem_statement": "core returns the old value",
        "docker_image": "example/image:1",
        "meta": {"has_test_patch": True, "llm_score": {"difficulty_score": 2}},
    }
    row.update(overrides)
    return row


class FakeDocker:
    """Records docker calls; `cat` succeeds only under `found_root`."""

    def __init__(self, *, pull_ok: bool = True, found_root: str | None = "/testbed"):
        self.calls: list[list[str]] = []
        self.pull_ok = pull_ok
        self.found_root = found_root

    def __call__(self, args: list[str], timeout: int = 1800) -> tuple[int, str]:
        self.calls.append(args)
        if args[0] == "pull":
            return (0, "pulled") if self.pull_ok else (1, "error: manifest unknown\n")
        path = args[-1]
        if self.found_root and path.startswith(self.found_root + "/"):
            return 0, "def core():\n    return 'old'\n"
        return 1, ""


# --- pure helpers -------------------------------------------------------------


def test_patched_files_keeps_source_files_only() -> None:
    patch = (
        ONE_FILE_PATCH
        + "diff --git a/pkg/tests/test_x.py b/pkg/tests/test_x.py\n"
        + "diff --git a/README.md b/README.md\n"
    )
    assert brc.patched_files(patch) == ["pkg/core.py"]
    assert brc.source_file_count(TWO_FILE_PATCH) == 2


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, []),
        (["a", 1], ["a", "1"]),
        ('["a", "b"]', ["a", "b"]),
        ("not json", ["not json"]),
        ("", []),
        ('{"a": 1}', []),
        (42, []),
    ],
)
def test_as_list_accepts_both_dataset_shapes(value: Any, expected: list[str]) -> None:
    assert brc.as_list(value) == expected


@pytest.mark.parametrize(
    ("created_at", "expected"),
    [
        ("2026-03-01T10:00:00Z", "low"),
        ("2025-06-01", "high"),
        ("2025-12-31", "high"),
        ("", "unknown"),
        ("March 2026", "unknown"),
    ],
)
def test_contamination_risk_never_defaults_to_low(
    created_at: str, expected: str
) -> None:
    assert brc.contamination_risk(created_at, "2025-12-31") == expected


def test_difficulty_of_reads_llm_score() -> None:
    assert brc.difficulty_of({}) == (None, "unknown")
    assert brc.difficulty_of(None) == (None, "unknown")  # type: ignore[arg-type]
    assert brc.difficulty_of({"llm_score": {"difficulty_score": 3}}) == (3, "hard")
    assert brc.difficulty_of({"llm_score": {"difficulty_score": 7}}) == (7, "score-7")


def test_size_band_uses_inclusive_thresholds() -> None:
    for threshold, label in brc.SIZE_BANDS:
        assert brc.size_band("\n" * threshold) == label
    largest = brc.SIZE_BANDS[-1][0]
    assert brc.size_band("\n" * (largest + 1)) == brc.SIZE_BAND_MAX
    assert brc.size_band(None) == brc.SIZE_BANDS[0][1]  # type: ignore[arg-type]


def test_docker_wraps_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen["cmd"] = cmd
        seen["timeout"] = kwargs["timeout"]
        return subprocess.CompletedProcess(cmd, 3, stdout="out", stderr="err")

    monkeypatch.setattr(brc.subprocess, "run", fake_run)
    assert brc.docker(["ps"], timeout=5) == (3, "outerr")
    assert seen == {"cmd": ["docker", "ps"], "timeout": 5}


def test_locate_source_probes_candidate_roots(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeDocker(found_root="/workspace")
    monkeypatch.setattr(brc, "docker", fake)
    found = brc.locate_source("img", "pkg/core.py")
    assert found is not None and found[0] == "/workspace"
    assert [c[-1] for c in fake.calls] == [
        "/testbed/pkg/core.py",
        "/workspace/pkg/core.py",
    ]

    monkeypatch.setattr(brc, "docker", FakeDocker(found_root=None))
    assert brc.locate_source("img", "pkg/core.py") is None


# --- filtering ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("row_overrides", "arg_overrides", "reason"),
    [
        ({}, {"after": "2026-03-01"}, "created before --after"),
        ({}, {"before": "2026-01-01"}, "created after --before"),
        ({"meta": {"has_test_patch": False}}, {}, "no test patch"),
        ({}, {"lite_only": True}, "not in lite subset"),
        ({"FAIL_TO_PASS": []}, {}, "empty FAIL_TO_PASS"),
        (
            {"patch": "diff --git a/README.md b/README.md\n"},
            {},
            "gold patch touches no .py source file",
        ),
        ({"patch": TWO_FILE_PATCH}, {}, "touches 2 source files"),
        ({}, {"max_patch_lines": 2}, "patch too long"),
        ({}, {"min_difficulty": 3}, "below --min-difficulty"),
        ({"meta": {}}, {"min_difficulty": 0}, "below --min-difficulty"),
        ({}, {"max_difficulty": 1}, "above --max-difficulty"),
    ],
)
def test_passes_filters_reports_each_rejection(
    row_overrides: dict[str, Any], arg_overrides: dict[str, Any], reason: str
) -> None:
    assert brc.passes_filters(_row(**row_overrides), _args(**arg_overrides)) == reason


def test_passes_filters_accepts_a_good_row() -> None:
    assert brc.passes_filters(_row(), _args(min_difficulty=1, max_difficulty=3)) is None


# --- case building --------------------------------------------------------------


@pytest.fixture
def cases_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "rebench_cases"
    monkeypatch.setattr(brc, "CASES_DIR", target)
    return target


def test_build_case_materialises_a_case(
    cases_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(brc, "docker", FakeDocker())
    case = brc.build_case(_row(), _args())
    assert case is not None
    assert case["sample_id"] == "org__repo-1"
    assert case["input"]["code_file"] == "pkg/core.py"
    assert case["input"]["failing_test"] == "tests/test_core.py::test_new"
    meta = case["metadata"]
    assert meta["contamination_risk"] == "low"
    assert meta["difficulty"] == "moderate"
    assert meta["source_files"] == 1

    written = cases_dir / "org__repo-1"
    assert (written / "broken.py").read_text(encoding="utf-8").startswith("def core")
    assert (written / "gold.patch").read_text(encoding="utf-8") == ONE_FILE_PATCH
    oracle = json.loads((written / "oracle.json").read_text(encoding="utf-8"))
    assert oracle["workdir"] == "/testbed"
    assert oracle["retrieval"] == "oracle"


@pytest.mark.parametrize(
    ("row_overrides", "fake"),
    [
        ({"patch": TWO_FILE_PATCH}, FakeDocker()),
        ({"docker_image": None}, FakeDocker()),
        ({}, FakeDocker(pull_ok=False)),
        ({}, FakeDocker(found_root=None)),
    ],
    ids=["multi-file", "no-image", "pull-failed", "source-missing"],
)
def test_build_case_skips_unusable_instances(
    cases_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    row_overrides: dict[str, Any],
    fake: FakeDocker,
) -> None:
    monkeypatch.setattr(brc, "docker", fake)
    assert brc.build_case(_row(**row_overrides), _args()) is None
    assert not cases_dir.exists() or not any(cases_dir.iterdir())


def test_load_rows_streams_only_the_full_corpus(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[dict[str, Any]] = []

    def load_dataset(source: str, config: str | None, *, split: str, streaming: bool):
        calls.append({"source": source, "streaming": streaming})
        return iter([{"instance_id": "x"}])

    monkeypatch.setitem(
        sys.modules, "datasets", types.SimpleNamespace(load_dataset=load_dataset)
    )
    assert list(brc.load_rows(brc.DEFAULT_SOURCE, "test", None)) == [
        {"instance_id": "x"}
    ]
    assert list(brc.load_rows("nebius/SWE-rebench", "filtered", None))
    assert [c["streaming"] for c in calls] == [False, True]
    assert "never materialised locally" in capsys.readouterr().out


# --- CLI ----------------------------------------------------------------------


def _run_main(
    monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]], *argv: str
) -> int:
    monkeypatch.setattr(brc, "load_rows", lambda *_: iter(rows))
    monkeypatch.setattr(sys, "argv", ["build_rebench_cases.py", *argv])
    return brc.main()


def test_main_dry_run_builds_nothing(
    cases_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeDocker()
    monkeypatch.setattr(brc, "docker", fake)
    rows = [_row("a"), _row("b"), _row("c", FAIL_TO_PASS=[])]
    rc = _run_main(
        monkeypatch, rows, "--dry-run", "--count", "5", "--out", str(cases_dir / "o")
    )
    assert rc == 0
    assert fake.calls == []
    text = capsys.readouterr().out
    assert "dry run: 2 instances would be built" in text
    assert "empty FAIL_TO_PASS" in text


def test_main_writes_cases_and_honours_filters(
    tmp_path: Path,
    cases_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(brc, "docker", FakeDocker())
    (cases_dir / "already").mkdir(parents=True)
    out = tmp_path / "cases.jsonl"
    rows = [
        _row("already"),
        _row("other", repo="someone/else"),
        _row("offset-skipped"),
        _row("built-1"),
        _row("built-2", created_at="2024-01-01"),
        _row("past-count"),
    ]
    rc = _run_main(
        monkeypatch,
        rows,
        "--repo",
        "org/repo",
        "--offset",
        "1",
        "--count",
        "2",
        "--out",
        str(out),
    )
    assert rc == 0
    written = [
        json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()
    ]
    assert [c["sample_id"] for c in written] == ["built-1", "built-2"]
    text = capsys.readouterr().out
    assert "skipping 1 instances already built" in text
    assert "contamination_risk distribution" in text
    assert "no variance" not in text


def test_main_flags_a_covariate_with_no_variance(
    tmp_path: Path,
    cases_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(brc, "docker", FakeDocker())
    rc = _run_main(monkeypatch, [_row("only")], "--out", str(tmp_path / "cases.jsonl"))
    assert rc == 0
    assert "no variance in contamination_risk" in capsys.readouterr().out


def test_main_fails_when_nothing_is_built(
    tmp_path: Path, cases_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(brc, "docker", FakeDocker(pull_ok=False))
    out = tmp_path / "cases.jsonl"
    assert _run_main(monkeypatch, [_row("x")], "--out", str(out)) == 1
    assert out.read_text(encoding="utf-8") == ""
