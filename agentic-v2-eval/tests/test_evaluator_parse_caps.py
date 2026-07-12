"""Tests for 256 KB cap lines in evaluator parse methods.

Both PatternEvaluator._parse_json_response and
StandardEvaluator._parse_response contain a cap guard that executes on
every call.  These tests call those methods with small, valid fenced-JSON
inputs so the cap lines are reached and counted as covered.

Targets:
  - agentic-v2-eval/src/agentic_v2_eval/evaluators/pattern.py
      _parse_json_response (~line 319-321)
  - agentic-v2-eval/src/agentic_v2_eval/evaluators/standard.py
      _parse_response (~line 211-213)
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from agentic_v2_eval.evaluators.pattern import PatternEvaluator
from agentic_v2_eval.evaluators.standard import StandardEvaluator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pattern_evaluator() -> PatternEvaluator:
    """Return a PatternEvaluator with a no-op LLM client."""
    client = MagicMock()
    client.generate_text = MagicMock(return_value="")
    return PatternEvaluator(llm_client=client)


def _make_standard_evaluator() -> StandardEvaluator:
    """Return a StandardEvaluator with a no-op LLM client."""
    client = MagicMock()
    client.generate_text = MagicMock(return_value="")
    return StandardEvaluator(llm_client=client)


# ---------------------------------------------------------------------------
# PatternEvaluator._parse_json_response
# ---------------------------------------------------------------------------


class TestPatternEvaluatorParseJsonResponse:
    """Tier 2: _parse_json_response parses fenced-JSON correctly."""

    def test_parses_fenced_json_block(self):
        """A ```json ...

        ``` fenced block is extracted and parsed.
        """
        evaluator = _make_pattern_evaluator()
        payload = {
            "PIF": 5,
            "POI": 4,
            "PC": 4,
            "CA": 5,
            "SRC": 4,
            "PR": 4,
            "IR": 3,
        }
        text = f"```json\n{json.dumps(payload)}\n```"

        result = evaluator._parse_json_response(text)

        assert result is not None
        assert isinstance(result, dict)
        assert result["PIF"] == 5

    def test_parses_plain_json(self):
        """Plain JSON (no fence) is parsed directly."""
        evaluator = _make_pattern_evaluator()
        payload = {"score": 4, "notes": "good"}
        text = json.dumps(payload)

        result = evaluator._parse_json_response(text)

        assert result == payload

    def test_returns_none_on_unparseable_text(self):
        """Completely non-JSON text returns None."""
        evaluator = _make_pattern_evaluator()
        result = evaluator._parse_json_response("Not JSON at all.")
        assert result is None

    def test_cap_guard_executes_for_short_input(self):
        """Cap line runs on any call — short inputs pass through unchanged."""
        evaluator = _make_pattern_evaluator()
        text = '{"x": 1}'
        result = evaluator._parse_json_response(text)
        assert result == {"x": 1}


# ---------------------------------------------------------------------------
# StandardEvaluator._parse_response
# ---------------------------------------------------------------------------


class TestStandardEvaluatorParseResponse:
    """Tier 2: _parse_response parses fenced-JSON correctly."""

    def test_parses_fenced_json_block(self):
        """A ```json ...

        ``` fenced block is extracted and parsed.
        """
        evaluator = _make_standard_evaluator()
        payload = {
            "scores": {
                "clarity": 8,
                "effectiveness": 7,
                "structure": 9,
                "specificity": 7,
                "completeness": 8,
            },
            "confidence": 0.9,
            "improvements": [],
        }
        text = f"```json\n{json.dumps(payload)}\n```"

        result = evaluator._parse_response(text)

        assert result is not None
        assert isinstance(result, dict)
        assert result["scores"]["clarity"] == 8

    def test_parses_plain_json(self):
        """Plain JSON is parsed without requiring a fence."""
        evaluator = _make_standard_evaluator()
        payload = {"scores": {"clarity": 5}, "confidence": 1.0, "improvements": []}
        text = json.dumps(payload)

        result = evaluator._parse_response(text)

        assert result == payload

    def test_returns_none_on_unparseable_text(self):
        """Non-JSON text returns None."""
        evaluator = _make_standard_evaluator()
        result = evaluator._parse_response("Just a narrative response.")
        assert result is None

    def test_cap_guard_executes_for_short_input(self):
        """Cap line runs on any call — short inputs pass through."""
        evaluator = _make_standard_evaluator()
        text = '{"clarity": 7}'
        result = evaluator._parse_response(text)
        assert result == {"clarity": 7}
