"""Tests for the 256 KB cap guard in
agentic_v2.workflows.artifact_extractor._scan_output_for_files.

The cap guard at ~line 75-76 of artifact_extractor.py executes on every call
that passes a string blob.  These tests call _scan_output_for_files with
small, valid artifact blobs so those lines are reached and counted as covered.

Target:
  - agentic-workflows-v2/agentic_v2/workflows/artifact_extractor.py
      _scan_output_for_files (~line 29 / cap at ~lines 75-76)
"""

from __future__ import annotations

from agentic_v2.workflows.artifact_extractor import _scan_output_for_files


class TestScanOutputForFilesCapGuard:
    """Tier 2: _scan_output_for_files processes normal-sized blobs correctly."""

    def test_extracts_single_file_block_from_string(self):
        """A single FILE/ENDFILE block in a string blob is extracted.

        The cap guard is evaluated for every blob string before the
        regex runs.
        """
        blob = "FILE: src/app.py\nprint('hello')\nENDFILE\n"
        result = _scan_output_for_files(blob)

        assert len(result) == 1
        key = list(result.keys())[0]
        assert key.parts == ("src", "app.py")
        assert "print('hello')" in result[key]

    def test_extracts_multiple_file_blocks(self):
        """Multiple FILE/ENDFILE blocks in one string blob are all extracted."""
        blob = "FILE: a.txt\nContent A\nENDFILE\n" "FILE: b.txt\nContent B\nENDFILE\n"
        result = _scan_output_for_files(blob)
        assert len(result) == 2

    def test_returns_empty_dict_for_string_without_file_blocks(self):
        """A plain string with no FILE blocks returns an empty dict."""
        result = _scan_output_for_files("just some output text without FILE blocks")
        assert result == {}

    def test_returns_empty_dict_for_non_string_non_container(self):
        """A non-string, non-container value (int) returns an empty dict."""
        result = _scan_output_for_files(42)
        assert result == {}

    def test_handles_nested_dict_output(self):
        """FILE blocks inside nested dicts/lists are reached by _collect_strings."""
        output = {"step_result": {"code": "FILE: nested.py\ncode_here\nENDFILE\n"}}
        result = _scan_output_for_files(output)
        assert len(result) == 1

    def test_cap_guard_executes_for_short_blob(self):
        """The cap check runs for any string blob — short blobs pass through."""
        blob = "FILE: tiny.py\nx = 1\nENDFILE\n"
        result = _scan_output_for_files(blob)
        assert len(result) == 1
