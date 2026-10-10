"""Saved legacy results remain usable without the legacy package installed."""

import json
from pathlib import Path

import pytest

from agentic_v2.scoring.criterion_aggregation import CriterionScorer

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/criterion_scores_legacy.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("case", FIXTURES["cases"], ids=lambda case: case["name"])
def test_saved_legacy_result(case):
    scorer = CriterionScorer(case["rubric"])
    actual = scorer.score(case["values"])
    assert {
        "total_score": actual.total_score,
        "weighted_score": actual.weighted_score,
        "criterion_scores": dict(actual.criterion_scores),
        "missing_criteria": list(actual.missing_criteria),
    } == case["expected"]
    assert (
        scorer.validate_results(case["values"]) == case["expected"]["missing_criteria"]
    )


def test_inputs_and_results_do_not_share_mutable_state():
    rubric = {"criteria": [{"name": "A"}]}
    scorer = CriterionScorer(rubric)
    rubric["criteria"][0]["name"] = "changed"
    values = {"A": 0.5}
    result = scorer.score(values)
    values["A"] = 1.0
    assert result.criterion_scores == {"A": 0.5}
    with pytest.raises(TypeError):
        result.criterion_scores["A"] = 1.0
