"""Tests for input-cap guards in agentic_v2.engine.llm_output_parsing.

The 256 KB cap guard lines are executed on every call to the functions below.
These tests call the functions with small, valid inputs so the cap lines are
reached and counted as covered.

Targets (~lines 33-47, 109, 280 of llm_output_parsing.py):
  - extract_files_from_artifact  — cap guard at line ~365
  - parse_sentinel_output        — cap guard at line ~404
"""

from __future__ import annotations

from agentic_v2.engine.llm_output_parsing import (
    extract_files_from_artifact,
    parse_sentinel_output,
)


class TestExtractFilesFromArtifactCapGuard:
    """Tier 2: extract_files_from_artifact processes normal-sized inputs correctly."""

    def test_returns_empty_dict_for_plain_text_without_file_blocks(self):
        """Content without FILE blocks returns an empty dict.

        The cap guard line executes before the regex search on any call.
        """
        result = extract_files_from_artifact("No FILE blocks here.")
        assert result == {}

    def test_extracts_single_file_block(self):
        """A single FILE/ENDFILE block is extracted correctly."""
        content = "FILE: src/hello.py\nprint('hello')\nENDFILE\n"
        result = extract_files_from_artifact(content)
        assert len(result) == 1
        assert "src/hello.py" in result
        assert "print('hello')" in result["src/hello.py"]

    def test_extracts_multiple_file_blocks(self):
        """Multiple FILE/ENDFILE blocks are all extracted."""
        content = (
            "FILE: a.py\ncontent_a\nENDFILE\n"
            "FILE: b.py\ncontent_b\nENDFILE\n"
        )
        result = extract_files_from_artifact(content)
        assert len(result) == 2
        assert "a.py" in result
        assert "b.py" in result

    def test_empty_string_returns_empty_dict(self):
        """Empty input returns an empty dict without error."""
        assert extract_files_from_artifact("") == {}


class TestParseSentinelOutputCapGuard:
    """Tier 2: parse_sentinel_output processes normal-sized inputs correctly."""

    def test_returns_none_when_no_sentinel_blocks_present(self):
        """Text without <<<ARTIFACT>>> blocks returns None.

        The cap guard line executes before the regex findall on any call.
        """
        result = parse_sentinel_output("Just plain text.", expected_output_keys=None)
        assert result is None

    def test_parses_string_artifact_correctly(self):
        """A simple string artifact is parsed and returned as-is."""
        text = (
            "<<<ARTIFACT result>>>\n"
            "FILE: main.py\nprint('hi')\nENDFILE\n"
            "<<<ENDARTIFACT>>>"
        )
        result = parse_sentinel_output(text, expected_output_keys=None)
        assert result is not None
        assert "result" in result

    def test_parses_json_artifact_correctly(self):
        """A JSON-shaped artifact content is parsed as a dict."""
        text = (
            '<<<ARTIFACT data>>>\n'
            '{"status": "ok", "value": 42}\n'
            '<<<ENDARTIFACT>>>'
        )
        result = parse_sentinel_output(text, expected_output_keys=None)
        assert result is not None
        assert result["data"] == {"status": "ok", "value": 42}

    def test_multiple_artifacts_all_captured(self):
        """Multiple <<<ARTIFACT>>> blocks produce multiple keys in result."""
        text = (
            "<<<ARTIFACT first>>>\nhello\n<<<ENDARTIFACT>>>\n"
            "<<<ARTIFACT second>>>\nworld\n<<<ENDARTIFACT>>>"
        )
        result = parse_sentinel_output(text, expected_output_keys=None)
        assert result is not None
        assert "first" in result
        assert "second" in result
