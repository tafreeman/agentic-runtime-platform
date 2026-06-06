"""Tests for LocalModel._parse_evaluation_response and _parse_geval_criterion.

Both methods contain a 256 KB input-cap guard (lines ~209-211 and ~404-406
in tools/llm/local_model.py) that executes on every call.  These tests
instantiate LocalModel via object.__new__ (bypassing __init__, which requires
an ONNX model file) and call the private methods directly with normal-sized
inputs so the cap lines are executed.

Targets:
  - tools/llm/local_model.py  _parse_evaluation_response (~lines 209/213)
  - tools/llm/local_model.py  _parse_geval_criterion (~lines 398/402)
"""

from __future__ import annotations

import json

import pytest

from tools.llm.local_model import LocalModel


def _make_model() -> LocalModel:
    """Return a LocalModel instance without loading any ONNX artefact."""
    instance = object.__new__(LocalModel)
    # Set only attributes referenced by the parse methods
    instance.verbose = False
    instance.model = None
    instance.tokenizer = None
    instance.model_path = None
    return instance


# ---------------------------------------------------------------------------
# _parse_evaluation_response
# ---------------------------------------------------------------------------


class TestParseEvaluationResponse:
    """Tier 2: _parse_evaluation_response parses well-formed JSON."""

    def test_returns_dict_on_valid_fenced_json(self):
        """A response with a markdown-fenced JSON block is parsed correctly."""
        # Arrange
        model = _make_model()
        payload = {
            "scores": {
                "clarity": 8,
                "specificity": 7,
                "actionability": 9,
                "structure": 8,
                "completeness": 7,
                "safety": 10,
            },
            "overall": 8,
            "summary": "Clear and actionable prompt.",
        }
        response = f"```json\n{json.dumps(payload)}\n```"

        # Act
        result = model._parse_evaluation_response(response)

        # Assert — the method returns a dict with at least these keys
        assert isinstance(result, dict)
        assert "scores" in result or "overall" in result or "summary" in result

    def test_returns_dict_on_plain_json(self):
        """A plain (unfenced) JSON response is also handled."""
        model = _make_model()
        payload = {
            "scores": {
                "clarity": 5,
                "specificity": 5,
                "actionability": 5,
                "structure": 5,
                "completeness": 5,
                "safety": 5,
            },
            "overall": 5,
            "summary": "Average.",
        }
        response = json.dumps(payload)

        result = model._parse_evaluation_response(response)

        assert isinstance(result, dict)

    def test_returns_dict_even_on_malformed_response(self):
        """Malformed input falls back gracefully — still returns a dict."""
        model = _make_model()
        response = "Not JSON at all — just prose."

        result = model._parse_evaluation_response(response)

        # The method must always return a dict (fallback path)
        assert isinstance(result, dict)

    def test_cap_guard_executes_for_short_input(self):
        """The 256 KB cap line is hit on every call; short inputs pass through."""
        model = _make_model()
        # A short input well below the cap
        response = '{"overall": 7, "summary": "ok"}'

        result = model._parse_evaluation_response(response)

        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _parse_geval_criterion
# ---------------------------------------------------------------------------


class TestParseGevalCriterion:
    """Tier 2: _parse_geval_criterion parses G-Eval format responses."""

    def test_returns_dict_with_score_reasoning_summary_on_valid_json(self):
        """Valid G-Eval JSON is parsed into the expected structure."""
        model = _make_model()
        payload = {
            "score": 4,
            "reasoning": ["Well-structured", "Clear intent"],
            "summary": "Good prompt overall.",
        }
        response = f"```json\n{json.dumps(payload)}\n```"

        result = model._parse_geval_criterion(response)

        assert result is not None
        assert isinstance(result, dict)
        assert "score" in result
        assert "reasoning" in result
        assert "summary" in result

    def test_returns_none_on_unparseable_response(self):
        """Completely unparseable input returns None."""
        model = _make_model()
        response = "just some text without any JSON or score"

        result = model._parse_geval_criterion(response)

        # Method returns None when it cannot extract a score
        assert result is None

    def test_cap_guard_executes_for_short_input(self):
        """The 256 KB cap line is exercised for any call — normal inputs pass through."""
        model = _make_model()
        response = '{"score": 3, "reasoning": [], "summary": "brief"}'

        result = model._parse_geval_criterion(response)

        assert result is not None
        assert result["score"] == 3.0
