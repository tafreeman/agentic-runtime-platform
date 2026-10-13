"""ARP rubric arithmetic, independent of either evaluation package."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class CriterionSpec:
    name: str
    weight: float = 1.0
    min_value: float = 0.0
    max_value: float = 1.0


@dataclass(frozen=True)
class CriterionScoreSummary:
    total_score: float
    weighted_score: float
    criterion_scores: Mapping[str, float]
    missing_criteria: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "criterion_scores", MappingProxyType(dict(self.criterion_scores))
        )


def parse_criteria(rubric_data: Mapping[str, Any]) -> tuple[CriterionSpec, ...]:
    """Read the legacy criterion fields and defaults in their original order."""
    return tuple(
        CriterionSpec(
            name=item["name"],
            weight=float(item.get("weight", 1.0)),
            min_value=float(item.get("min_value", 0.0)),
            max_value=float(item.get("max_value", 1.0)),
        )
        for item in rubric_data.get("criteria", [])
        if isinstance(item, dict) and "name" in item
    )


def score_criterion_values(
    criteria: tuple[CriterionSpec, ...], values: Mapping[str, float]
) -> CriterionScoreSummary:
    """Keep missing criteria in both denominators, matching ARP's scorer."""
    total_weight = sum(criterion.weight for criterion in criteria)
    weighted_sum = 0.0
    raw_sum = 0.0
    scores: dict[str, float] = {}
    missing: list[str] = []
    for criterion in criteria:
        if criterion.name not in values:
            missing.append(criterion.name)
            continue
        value = float(values[criterion.name])
        value = max(criterion.min_value, min(criterion.max_value, value))
        span = criterion.max_value - criterion.min_value
        normalized = (value - criterion.min_value) / span if span > 0 else value
        scores[criterion.name] = value
        weighted_sum += criterion.weight * normalized
        raw_sum += normalized
    return CriterionScoreSummary(
        total_score=raw_sum / len(criteria) if criteria else 0.0,
        weighted_score=weighted_sum / total_weight if total_weight > 0 else 0.0,
        criterion_scores=scores,
        missing_criteria=tuple(missing),
    )


class CriterionScorer:
    def __init__(self, rubric_data: Mapping[str, Any]) -> None:
        self.criteria = parse_criteria(rubric_data)

    def score(self, values: Mapping[str, float]) -> CriterionScoreSummary:
        return score_criterion_values(self.criteria, values)

    def validate_results(self, values: Mapping[str, float]) -> list[str]:
        return [
            criterion.name
            for criterion in self.criteria
            if criterion.name not in values
        ]
