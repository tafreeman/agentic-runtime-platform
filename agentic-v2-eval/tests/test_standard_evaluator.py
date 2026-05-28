"""Focused tests for standard prompt evaluation parsing and aggregation."""

from __future__ import annotations

import json
from typing import Any

import pytest

from agentic_v2_eval.evaluators.standard import StandardEvaluator


class SequencedLLMClient:
    """Returns predefined judge responses and records prompts."""

    def __init__(self, responses: list[str | Exception]):
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def generate_text(
        self,
        model_name: str,
        prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 1000,
        **kwargs: Any,
    ) -> str:
        self.calls.append(
            {
                "model_name": model_name,
                "prompt": prompt,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "kwargs": kwargs,
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def standard_payload(
    clarity: float,
    effectiveness: float,
    structure: float,
    specificity: float,
    completeness: float,
    confidence: float = 1.0,
    improvements: list[str] | None = None,
) -> str:
    return json.dumps(
        {
            "scores": {
                "clarity": clarity,
                "effectiveness": effectiveness,
                "structure": structure,
                "specificity": specificity,
                "completeness": completeness,
            },
            "confidence": confidence,
            "improvements": improvements or [],
        }
    )


def test_parse_response_accepts_fenced_json() -> None:
    evaluator = StandardEvaluator(SequencedLLMClient([]))

    parsed = evaluator._parse_response(
        '```json\n{"scores": {"clarity": 9}, "confidence": 0.8}\n```'
    )

    assert parsed == {"scores": {"clarity": 9}, "confidence": 0.8}


def test_parse_response_extracts_fallback_json_object() -> None:
    evaluator = StandardEvaluator(SequencedLLMClient([]))

    parsed = evaluator._parse_response(
        'Judge notes before JSON {"scores": {"structure": 7}} trailing text'
    )

    assert parsed == {"scores": {"structure": 7}}


def test_empty_score_when_no_runs_parse() -> None:
    evaluator = StandardEvaluator(
        SequencedLLMClient(["not json", RuntimeError("judge failed")])
    )

    score = evaluator.score_prompt("empty.md", "content", runs=2)

    assert score.prompt_file == "empty.md"
    assert score.scores == {}
    assert score.overall_score == 0
    assert score.grade == "F"
    assert score.passed is False
    assert score.improvements == ["Evaluation failed"]
    assert score.successful_runs == 0
    assert score.runs == 2


def test_score_prompt_aggregates_medians_and_deduplicates_improvements() -> None:
    client = SequencedLLMClient(
        [
            standard_payload(4, 5, 6, 7, 8, 0.3, ["tighten scope", "add examples"]),
            standard_payload(10, 9, 8, 7, 6, 0.9, ["tighten scope"]),
            standard_payload(8, 7, 6, 5, 4, 0.5, ["clarify audience"]),
        ]
    )
    evaluator = StandardEvaluator(client)

    score = evaluator.score_prompt(
        "prompt.md", "content", model="judge", runs=3, temperature=0.2
    )

    assert score.scores == {
        "clarity": 8,
        "effectiveness": 7,
        "structure": 6,
        "specificity": 7,
        "completeness": 6,
    }
    assert score.overall_score == 6.8
    assert score.grade == "D"
    assert score.passed is False
    assert score.confidence == 0.5
    assert score.improvements == [
        "tighten scope",
        "add examples",
        "clarify audience",
    ]
    assert score.successful_runs == 3
    assert client.calls[0]["model_name"] == "judge"
    assert client.calls[0]["temperature"] == 0.2
    assert client.calls[0]["max_tokens"] == 900


def test_score_prompt_truncates_long_content_for_judge() -> None:
    client = SequencedLLMClient([standard_payload(9, 9, 9, 9, 9)])
    evaluator = StandardEvaluator(client)
    long_content = "a" * 17_500 + "middle should be removed" + "z" * 1_200

    score = evaluator.score_prompt("long.md", long_content)

    prompt = client.calls[0]["prompt"]
    assert "[...TRUNCATED... tail of prompt follows]" in prompt
    assert "middle should be removed" not in prompt
    assert "a" * 100 in prompt
    assert "z" * 100 in prompt
    assert score.overall_score == 9.0


@pytest.mark.parametrize(
    ("score", "expected"),
    [(9, "A"), (8, "B"), (7, "C"), (6, "D"), (5.9, "F")],
)
def test_get_grade_maps_boundaries(score: float, expected: str) -> None:
    evaluator = StandardEvaluator(SequencedLLMClient([]))

    assert evaluator._get_grade(score, 10.0) == expected
