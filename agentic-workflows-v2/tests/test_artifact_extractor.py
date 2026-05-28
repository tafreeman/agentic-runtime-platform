"""Tests for workflows/artifact_extractor.py — ADR-008 Phase 3.

Covers _collect_strings, _safe_rel_path, _scan_output_for_files,
extract_from_record, and extract_artifacts.

Test tiers (per ADR-008):   Tier 1 — path traversal blocking, branching,
edge cases   Tier 2 — happy-path contracts, file-writing behaviour
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from agentic_v2.contracts import StepResult, StepStatus, WorkflowResult
from agentic_v2.workflows.artifact_extractor import (
    _collect_strings,
    _safe_rel_path,
    _scan_output_for_files,
    extract_artifacts,
    extract_from_record,
)

# ===================================================================
# _collect_strings
# ===================================================================


class TestCollectStrings:
    """Tier 2: recursive string extraction from nested structures."""

    @pytest.mark.parametrize(
        "value, expected",
        [
            ("hello", ["hello"]),
            (42, []),
            (None, []),
            (["a", "b"], ["a", "b"]),
            ({"x": "y", "z": "w"}, ["y", "w"]),
            ({"nested": {"deep": "val"}}, ["val"]),
            ([{"a": "1"}, ["2", "3"]], ["1", "2", "3"]),
        ],
        ids=["str", "int", "none", "list", "dict", "nested-dict", "mixed"],
    )
    def test_collect_strings(self, value: Any, expected: list[str]) -> None:
        """Tier 2: strings are extracted from all nested containers."""
        assert _collect_strings(value) == expected


# ===================================================================
# _safe_rel_path
# ===================================================================


class TestSafeRelPath:
    """Tier 1: path traversal blocking and normalization."""

    @pytest.mark.parametrize(
        "raw, expected_parts",
        [
            ("src/main.py", ("src", "main.py")),
            ("src\\main.py", ("src", "main.py")),
            ("/absolute/file.txt", ("absolute", "file.txt")),
            ("a/../b/c.py", ("a", "b", "c.py")),
        ],
        ids=["posix", "backslash", "leading-slash-stripped", "dotdot-stripped"],
    )
    def test_safe_path_normalizes(
        self, raw: str, expected_parts: tuple[str, ...]
    ) -> None:
        """Tier 1: paths are normalized, traversals stripped."""
        result = _safe_rel_path(raw)
        assert result is not None
        assert result.parts == expected_parts

    @pytest.mark.parametrize(
        "raw",
        [
            "..",
            "../../..",
            "",
            "   ",
        ],
        ids=["single-dotdot", "multi-dotdot", "empty", "whitespace"],
    )
    def test_unsafe_paths_return_none(self, raw: str) -> None:
        """Tier 1: purely traversal or empty paths return None."""
        assert _safe_rel_path(raw) is None


# ===================================================================
# _scan_output_for_files
# ===================================================================


class TestScanOutputForFiles:
    """Tier 2: FILE block regex extraction."""

    def test_single_file_block(self) -> None:
        """Tier 2: a single FILE/ENDFILE block is extracted."""
        blob = "some preamble\nFILE: src/app.py\nprint('hi')\nENDFILE\ntrailing"
        files = _scan_output_for_files(blob)
        assert len(files) == 1
        key = list(files.keys())[0]
        assert key.parts == ("src", "app.py")
        assert "print('hi')" in files[key]

    def test_multiple_file_blocks(self) -> None:
        """Tier 2: multiple blocks in the same string are all extracted."""
        blob = "FILE: a.txt\ncontent_a\nENDFILE\n" "FILE: b.txt\ncontent_b\nENDFILE\n"
        files = _scan_output_for_files(blob)
        assert len(files) == 2

    def test_last_block_wins_same_path(self) -> None:
        """Tier 1: duplicate paths keep the last version (coalesce)."""
        blob = "FILE: x.py\nv1\nENDFILE\nFILE: x.py\nv2\nENDFILE\n"
        files = _scan_output_for_files(blob)
        assert len(files) == 1
        assert "v2" in list(files.values())[0]

    def test_traversal_path_skipped(self) -> None:
        """Tier 1: FILE blocks with purely traversal paths are ignored."""
        blob = "FILE: ../../etc/passwd\nmalicious\nENDFILE\n"
        files = _scan_output_for_files(blob)
        # The path strips ".." components; depending on remaining parts
        # this may or may not produce a result. The key check is that
        # no path with ".." components survives.
        for p in files:
            assert ".." not in p.parts

    def test_nested_dict_output(self) -> None:
        """Tier 2: FILE blocks inside nested dicts/lists are found."""
        output = {"result": {"code": "FILE: nested.py\ncode_here\nENDFILE\n"}}
        files = _scan_output_for_files(output)
        assert len(files) == 1

    def test_no_file_blocks(self) -> None:
        """Tier 1: output with no FILE blocks returns empty dict."""
        assert _scan_output_for_files("just plain text") == {}
        assert _scan_output_for_files(42) == {}


# ===================================================================
# extract_from_record
# ===================================================================


class TestExtractFromRecord:
    """Tier 2: record-level extraction and file writing."""

    def test_extracts_files_to_disk(self, tmp_path: Path) -> None:
        """Tier 2: FILE blocks are written under artifacts/<run_id>/."""
        record = {
            "run_id": "run-001",
            "steps": [
                {
                    "status": "success",
                    "output": "FILE: hello.txt\nHello!\nENDFILE\n",
                },
            ],
        }
        run_dir = extract_from_record(record, artifacts_dir=tmp_path)
        assert run_dir is not None
        assert (run_dir / "hello.txt").read_text(encoding="utf-8") == "Hello!\n"

    def test_skips_failed_steps(self, tmp_path: Path) -> None:
        """Tier 1: steps with status != success/skipped are ignored."""
        record = {
            "run_id": "run-002",
            "steps": [
                {
                    "status": "failed",
                    "output": "FILE: bad.txt\nshould not appear\nENDFILE\n",
                },
            ],
        }
        result = extract_from_record(record, artifacts_dir=tmp_path)
        assert result is None

    def test_skipped_status_included(self, tmp_path: Path) -> None:
        """Tier 1: skipped steps are still scanned for artifacts."""
        record = {
            "run_id": "run-003",
            "steps": [
                {
                    "status": "skipped",
                    "output": "FILE: skipped.txt\ncontent\nENDFILE\n",
                },
            ],
        }
        run_dir = extract_from_record(record, artifacts_dir=tmp_path)
        assert run_dir is not None
        assert (run_dir / "skipped.txt").exists()

    def test_no_file_blocks_returns_none(self, tmp_path: Path) -> None:
        """Tier 1: record with no FILE blocks returns None."""
        record = {
            "run_id": "run-004",
            "steps": [{"status": "success", "output": "just text"}],
        }
        assert extract_from_record(record, artifacts_dir=tmp_path) is None

    def test_subdirectory_creation(self, tmp_path: Path) -> None:
        """Tier 2: nested paths create intermediate directories."""
        record = {
            "run_id": "run-005",
            "steps": [
                {
                    "status": "success",
                    "output": "FILE: deep/nested/file.py\ncode\nENDFILE\n",
                },
            ],
        }
        run_dir = extract_from_record(record, artifacts_dir=tmp_path)
        assert run_dir is not None
        assert (run_dir / "deep" / "nested" / "file.py").exists()


# ===================================================================
# extract_artifacts (WorkflowResult wrapper)
# ===================================================================


class TestExtractArtifacts:
    """Tier 2: WorkflowResult-level extraction."""

    def test_empty_steps_returns_none(self) -> None:
        """Tier 1: WorkflowResult with no steps returns None early."""
        wr = WorkflowResult(
            workflow_id="wf-1",
            workflow_name="test",
            steps=[],
            overall_status=StepStatus.SUCCESS,
        )
        assert extract_artifacts(wr) is None

    def test_delegates_to_extract_from_record(self, tmp_path: Path) -> None:
        """Tier 2: a real WorkflowResult with FILE blocks writes files."""
        step = StepResult(
            step_name="gen",
            status=StepStatus.SUCCESS,
            output_data={"code": "FILE: out.txt\ngenerated\nENDFILE\n"},
        )
        wr = WorkflowResult(
            workflow_id="wf-2",
            workflow_name="test",
            steps=[step],
            overall_status=StepStatus.SUCCESS,
        )
        run_dir = extract_artifacts(wr, artifacts_dir=tmp_path)
        assert run_dir is not None
        assert (run_dir / "out.txt").read_text(encoding="utf-8") == "generated\n"

    def test_status_enum_value_conversion(self, tmp_path: Path) -> None:
        """Tier 1: StepStatus enum .value is correctly mapped to string."""
        step = StepResult(
            step_name="s1",
            status=StepStatus.FAILED,
            output_data={"code": "FILE: nope.txt\ndata\nENDFILE\n"},
        )
        wr = WorkflowResult(
            workflow_id="wf-3",
            workflow_name="test",
            steps=[step],
            overall_status=StepStatus.FAILED,
        )
        # Failed status should be skipped by extract_from_record
        assert extract_artifacts(wr, artifacts_dir=tmp_path) is None
