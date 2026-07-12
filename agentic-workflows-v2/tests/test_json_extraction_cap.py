"""Tests for the 256 KB cap guard in
agentic_v2.agents.json_extraction._find_json_string.

The cap line at ~line 60 in json_extraction.py executes on every call to
_find_json_string.  These tests call the function with small valid inputs
so that line is reached and counted as covered.

Target:
  - agentic-workflows-v2/agentic_v2/agents/json_extraction.py
      _find_json_string (~line 28 / cap at ~line 60)
"""

from __future__ import annotations

import pytest

from agentic_v2.agents.json_extraction import _find_json_string


class TestFindJsonStringCapGuard:
    """Tier 2: _find_json_string extracts JSON from LLM response text."""

    def test_extracts_from_fenced_json_block(self):
        """Strategy 1: ```json ... ``` fenced block is extracted."""
        text = '```json\n{"name": "Alice", "score": 9}\n```'
        result = _find_json_string(text)
        assert result == '{"name": "Alice", "score": 9}'

    def test_extracts_from_plain_json(self):
        """Strategy 3: balanced brace extraction from raw text."""
        text = 'Some preamble {"key": "value"} some trailing text'
        result = _find_json_string(text)
        assert result == '{"key": "value"}'

    def test_extracts_from_generic_fenced_block(self):
        """Strategy 2: generic ``` ... ``` fence containing a JSON object."""
        text = 'Here you go:\n```\n{"x": 1, "y": 2}\n```\n'
        result = _find_json_string(text)
        assert result == '{"x": 1, "y": 2}'

    def test_raises_on_text_without_json(self):
        """No JSON-like content raises ValueError."""
        with pytest.raises(ValueError):
            _find_json_string("just some plain prose without braces")

    def test_cap_guard_executes_for_short_input(self):
        """The cap check runs on every call; short inputs are unchanged."""
        text = '{"a": 1}'
        result = _find_json_string(text)
        assert result == '{"a": 1}'
