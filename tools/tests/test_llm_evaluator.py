"""Tests for llm_evaluator -- prompt construction, response parsing, scoring, and
evaluation.

Covers:
- build_evaluation_prompt construction with various gold standard fields
- parse_evaluation_response with valid JSON, markdown-wrapped, malformed, and empty inputs
- Score normalization and clamping to 0.0-10.0
- EvaluationResult.grade_from_score mapping
- DimensionScore.weighted_score calculation
- evaluate_with_llm end-to-end with mocked LLM
- Error handling for LLM failures
- Edge cases: empty responses, missing dimensions, parse errors
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from tools.agents.benchmarks.evaluator_models import (
    EVALUATION_DIMENSIONS,
    SCORE_RUBRIC,
    DimensionScore,
    EvaluationResult,
)
from tools.agents.benchmarks.llm_evaluator import (
    build_evaluation_prompt,
    evaluate_with_llm,
    parse_evaluation_response,
)

# ---------------------------------------------------------------------------
# build_evaluation_prompt
# ---------------------------------------------------------------------------


class TestBuildEvaluationPrompt:
    """Tests for evaluation prompt construction."""

    def test_includes_task_prompt(self):
        """Generated prompt includes the task prompt text."""
        prompt = build_evaluation_prompt(
            task_prompt="Write a fibonacci function",
            generated_output="def fib(n): ...",
            gold_standard={},
        )
        assert "Write a fibonacci function" in prompt

    def test_includes_generated_output(self):
        """Generated prompt includes the generated output."""
        prompt = build_evaluation_prompt(
            task_prompt="task",
            generated_output="my generated code",
            gold_standard={},
        )
        assert "my generated code" in prompt

    def test_includes_gold_standard_components(self):
        """Gold standard fields like required_components appear in prompt."""
        gold = {
            "required_components": ["auth module", "database layer"],
            "required_patterns": ["repository pattern"],
            "key_decisions": ["Use PostgreSQL"],
        }
        prompt = build_evaluation_prompt(
            task_prompt="task",
            generated_output="output",
            gold_standard=gold,
        )
        assert "auth module" in prompt
        assert "repository pattern" in prompt
        assert "Use PostgreSQL" in prompt

    def test_includes_api_endpoints(self):
        """API endpoint gold standard data is formatted in the prompt."""
        gold = {
            "api_endpoints": [
                {"method": "GET", "path": "/api/users"},
                {"method": "POST", "path": "/api/users"},
            ]
        }
        prompt = build_evaluation_prompt(
            task_prompt="task",
            generated_output="output",
            gold_standard=gold,
        )
        assert "GET /api/users" in prompt

    def test_includes_dimension_descriptions(self):
        """All evaluation dimensions appear in the prompt."""
        prompt = build_evaluation_prompt(
            task_prompt="task",
            generated_output="output",
            gold_standard={},
        )
        for dim_name in EVALUATION_DIMENSIONS:
            assert dim_name in prompt

    def test_includes_scoring_rubric(self):
        """Score rubric descriptions are included."""
        prompt = build_evaluation_prompt(
            task_prompt="task",
            generated_output="output",
            gold_standard={},
        )
        assert "Perfect" in prompt
        assert "Failed" in prompt

    def test_custom_dimensions(self):
        """Custom dimensions override the defaults."""
        custom = {"my_dim": {"description": "Custom check", "weight": 1.0}}
        prompt = build_evaluation_prompt(
            task_prompt="task",
            generated_output="output",
            gold_standard={},
            dimensions=custom,
        )
        assert "my_dim" in prompt
        assert "Custom check" in prompt

    def test_empty_gold_standard(self):
        """Empty gold standard produces a fallback message."""
        prompt = build_evaluation_prompt(
            task_prompt="task",
            generated_output="output",
            gold_standard={},
        )
        assert "No specific gold standard defined" in prompt

    def test_extra_gold_keys_included(self):
        """Extra keys not in the skip set are included generically."""
        gold = {"custom_field": "some value"}
        prompt = build_evaluation_prompt(
            task_prompt="task",
            generated_output="output",
            gold_standard=gold,
        )
        assert "Custom Field" in prompt
        assert "some value" in prompt


# ---------------------------------------------------------------------------
# parse_evaluation_response
# ---------------------------------------------------------------------------


class TestParseEvaluationResponse:
    """Tests for LLM response parsing."""

    def test_valid_json(self):
        """Direct JSON string is parsed correctly."""
        data = {
            "dimension_scores": {
                "completeness": {"score": 8.0, "reasoning": "Good", "evidence": []}
            },
            "strengths": ["clear code"],
            "weaknesses": [],
            "improvement_suggestions": [],
            "key_findings": [],
        }
        result = parse_evaluation_response(json.dumps(data))
        assert result["dimension_scores"]["completeness"]["score"] == 8.0

    def test_markdown_wrapped_json(self):
        """JSON wrapped in ```json code blocks is parsed."""
        data = {"dimension_scores": {}, "strengths": []}
        wrapped = f"```json\n{json.dumps(data)}\n```"
        result = parse_evaluation_response(wrapped)
        assert "dimension_scores" in result

    def test_json_embedded_in_text(self):
        """JSON embedded in surrounding text is extracted."""
        data = {"dimension_scores": {}, "strengths": ["good"]}
        text = f"Here is my evaluation:\n{json.dumps(data)}\nEnd of evaluation."
        result = parse_evaluation_response(text)
        assert result["strengths"] == ["good"]

    def test_malformed_response_returns_error_structure(self):
        """Completely unparseable response returns error structure."""
        result = parse_evaluation_response("This is not JSON at all")
        assert result.get("parse_error") is True
        assert "Failed to parse" in result["weaknesses"][0]

    def test_empty_response(self):
        """Empty string returns error structure."""
        result = parse_evaluation_response("")
        assert result.get("parse_error") is True

    def test_whitespace_handling(self):
        """Response with leading/trailing whitespace is trimmed."""
        data = {"dimension_scores": {}, "strengths": []}
        result = parse_evaluation_response(f"  \n  {json.dumps(data)}  \n  ")
        assert "dimension_scores" in result


# ---------------------------------------------------------------------------
# DimensionScore
# ---------------------------------------------------------------------------


class TestDimensionScore:
    """Tests for the DimensionScore dataclass."""

    def test_weighted_score_calculation(self):
        """weighted_score = score * weight."""
        ds = DimensionScore(dimension="test", score=8.0, reasoning="ok", weight=0.25)
        assert ds.weighted_score == pytest.approx(2.0)

    def test_default_weight(self):
        """Default weight is 0.2."""
        ds = DimensionScore(dimension="test", score=10.0, reasoning="ok")
        assert ds.weight == 0.2
        assert ds.weighted_score == pytest.approx(2.0)

    def test_zero_score(self):
        """Zero score produces zero weighted score."""
        ds = DimensionScore(dimension="test", score=0.0, reasoning="bad", weight=0.5)
        assert ds.weighted_score == 0.0


# ---------------------------------------------------------------------------
# EvaluationResult
# ---------------------------------------------------------------------------


class TestEvaluationResult:
    """Tests for the EvaluationResult dataclass."""

    @pytest.mark.parametrize(
        "score,grade",
        [
            (10.0, "A"),
            (9.0, "A"),
            (8.5, "B"),
            (8.0, "B"),
            (7.5, "C"),
            (7.0, "C"),
            (6.5, "D"),
            (6.0, "D"),
            (5.0, "F"),
            (0.0, "F"),
        ],
    )
    def test_grade_from_score(self, score: float, grade: str):
        """grade_from_score maps scores to correct letter grades."""
        assert EvaluationResult.grade_from_score(score) == grade

    def test_to_dict_structure(self):
        """to_dict returns a dict with all expected keys."""
        result = EvaluationResult(
            task_id="1",
            model="gpt-4o",
            benchmark_id="test",
            timestamp=datetime.now().isoformat(),
            overall_score=7.5,
            grade="C",
        )
        d = result.to_dict()
        assert d["task_id"] == "1"
        assert d["overall_score"] == 7.5
        assert d["grade"] == "C"

    def test_default_values(self):
        """Default values are sensible."""
        result = EvaluationResult(
            task_id="1",
            model="test",
            benchmark_id="test",
            timestamp="2025-01-01",
        )
        assert result.overall_score == 0.0
        assert result.grade == "F"
        assert result.strengths == []
        assert result.weaknesses == []


# ---------------------------------------------------------------------------
# evaluate_with_llm
# ---------------------------------------------------------------------------


class TestEvaluateWithLlm:
    """Tests for the end-to-end LLM evaluation function."""

    def _mock_llm_response(self) -> str:
        """Return a valid LLM evaluation response JSON string."""
        return json.dumps(
            {
                "dimension_scores": {
                    "completeness": {
                        "score": 8.0,
                        "reasoning": "Covers all requirements",
                        "evidence": ["evidence1"],
                    },
                    "correctness": {
                        "score": 9.0,
                        "reasoning": "Technically sound",
                        "evidence": [],
                    },
                    "quality": {
                        "score": 7.5,
                        "reasoning": "Well structured",
                        "evidence": [],
                    },
                    "specificity": {
                        "score": 8.0,
                        "reasoning": "Detailed",
                        "evidence": [],
                    },
                    "alignment": {
                        "score": 7.0,
                        "reasoning": "Good alignment",
                        "evidence": [],
                    },
                },
                "strengths": ["clear code", "good tests"],
                "weaknesses": ["missing docs"],
                "improvement_suggestions": ["add docstrings"],
                "key_findings": ["solid implementation"],
            }
        )

    @patch("tools.llm.llm_client.LLMClient")
    def test_successful_evaluation(self, mock_client_cls):
        """Successful LLM call produces scored EvaluationResult."""
        mock_client_cls.generate_text.return_value = self._mock_llm_response()

        result = evaluate_with_llm(
            task_id="task_001",
            task_prompt="Write a fibonacci function",
            generated_output="def fib(n): ...",
            gold_standard={"expected_output": "correct fibonacci"},
            model="gpt-4o-mini",
            benchmark_id="test_bench",
        )

        assert isinstance(result, EvaluationResult)
        assert result.task_id == "task_001"
        assert result.overall_score > 0.0
        assert result.grade != "F"
        assert len(result.dimension_scores) == 5
        assert "completeness" in result.dimension_scores

    @patch("tools.llm.llm_client.LLMClient")
    def test_score_clamping(self, mock_client_cls):
        """Scores outside 0-10 are clamped."""
        response = json.dumps(
            {
                "dimension_scores": {
                    "completeness": {
                        "score": 15.0,
                        "reasoning": "over",
                        "evidence": [],
                    },
                    "correctness": {
                        "score": -5.0,
                        "reasoning": "under",
                        "evidence": [],
                    },
                    "quality": {"score": 8.0, "reasoning": "ok", "evidence": []},
                    "specificity": {"score": 8.0, "reasoning": "ok", "evidence": []},
                    "alignment": {"score": 8.0, "reasoning": "ok", "evidence": []},
                },
                "strengths": [],
                "weaknesses": [],
                "improvement_suggestions": [],
                "key_findings": [],
            }
        )
        mock_client_cls.generate_text.return_value = response

        result = evaluate_with_llm(
            task_id="1",
            task_prompt="t",
            generated_output="o",
            gold_standard={},
            model="m",
            benchmark_id="b",
        )

        assert result.dimension_scores["completeness"].score == 10.0
        assert result.dimension_scores["correctness"].score == 0.0

    @patch("tools.llm.llm_client.LLMClient")
    def test_llm_failure_returns_error_result(self, mock_client_cls):
        """When LLM call raises, error EvaluationResult is returned."""
        mock_client_cls.generate_text.side_effect = RuntimeError("API down")

        result = evaluate_with_llm(
            task_id="1",
            task_prompt="t",
            generated_output="o",
            gold_standard={},
            model="m",
            benchmark_id="b",
        )

        assert result.overall_score == 0.0
        assert result.grade == "F"
        assert any("API down" in w for w in result.weaknesses)

    @patch("tools.llm.llm_client.LLMClient")
    def test_malformed_llm_response(self, mock_client_cls):
        """Malformed LLM response still produces a result with zero scores."""
        mock_client_cls.generate_text.return_value = "Not valid JSON"

        result = evaluate_with_llm(
            task_id="1",
            task_prompt="t",
            generated_output="o",
            gold_standard={},
            model="m",
            benchmark_id="b",
        )

        # All dimension scores should be 0.0 since parsing failed
        assert result.overall_score == 0.0

    @patch("tools.llm.llm_client.LLMClient")
    def test_evaluator_model_override(self, mock_client_cls):
        """evaluator_model param is used instead of generation model."""
        mock_client_cls.generate_text.return_value = self._mock_llm_response()

        result = evaluate_with_llm(
            task_id="1",
            task_prompt="t",
            generated_output="o",
            gold_standard={},
            model="gpt-4o-mini",
            benchmark_id="b",
            evaluator_model="gpt-4o",
        )

        assert result.evaluator_model == "gpt-4o"
        # Check that generate_text was called with the evaluator model
        call_args = mock_client_cls.generate_text.call_args
        assert call_args[0][0] == "gpt-4o"

    @patch("tools.llm.llm_client.LLMClient")
    def test_missing_dimensions_default_to_zero(self, mock_client_cls):
        """Missing dimensions in LLM response get score 0.0."""
        response = json.dumps(
            {
                "dimension_scores": {
                    "completeness": {"score": 8.0, "reasoning": "ok"},
                    # Missing other dimensions
                },
                "strengths": [],
                "weaknesses": [],
                "improvement_suggestions": [],
                "key_findings": [],
            }
        )
        mock_client_cls.generate_text.return_value = response

        result = evaluate_with_llm(
            task_id="1",
            task_prompt="t",
            generated_output="o",
            gold_standard={},
            model="m",
            benchmark_id="b",
        )

        assert result.dimension_scores["completeness"].score == 8.0
        assert result.dimension_scores["correctness"].score == 0.0


# ---------------------------------------------------------------------------
# SCORE_RUBRIC
# ---------------------------------------------------------------------------


class TestScoreRubric:
    """Tests for the scoring rubric constants."""

    def test_rubric_covers_full_range(self):
        """Rubric has entries from 0.0 to 10.0."""
        assert 0.0 in SCORE_RUBRIC
        assert 10.0 in SCORE_RUBRIC

    def test_rubric_entries_are_strings(self):
        """All rubric descriptions are non-empty strings."""
        for _score, desc in SCORE_RUBRIC.items():
            assert isinstance(desc, str)
            assert len(desc) > 0

    def test_evaluation_dimensions_weights_sum_to_one(self):
        """Dimension weights should sum to 1.0."""
        total = sum(d["weight"] for d in EVALUATION_DIMENSIONS.values())
        assert total == pytest.approx(1.0)
