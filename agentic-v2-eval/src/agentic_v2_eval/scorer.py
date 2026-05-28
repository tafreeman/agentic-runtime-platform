"""YAML-rubric-driven weighted scoring engine.

Loads a rubric (from a YAML file or an in-memory dict), extracts named
criteria with weights and value ranges, then computes a normalized
weighted score for a given set of metric results.

The rubric YAML schema is::

    name: My Rubric
    version: "1.0"
    criteria:
      - name: Accuracy
        weight: 2.0
        min_value: 0.0
        max_value: 1.0
      - name: Completeness
        weight: 1.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Criterion:
    """A single scoring criterion parsed from a rubric.

    Attributes:
        name: Display name used as the key in result dicts.
        weight: Relative importance multiplier (default 1.0).
        description: Human-readable explanation of the criterion.
        min_value: Lower bound of the valid score range.
        max_value: Upper bound of the valid score range.
    """

    name: str
    weight: float = 1.0
    description: str = ""
    min_value: float = 0.0
    max_value: float = 1.0


@dataclass
class ScoringResult:
    """Result of a rubric-based scoring operation.

    Attributes:
        total_score: Unweighted mean of normalized criterion scores.
        weighted_score: Weight-adjusted aggregate score in ``[0.0, 1.0]``.
        criterion_scores: Mapping of criterion name to its clamped raw value.
        missing_criteria: Names of criteria absent from the input results.
    """

    total_score: float
    weighted_score: float
    criterion_scores: dict[str, float] = field(default_factory=dict)
    missing_criteria: list[str] = field(default_factory=list)


class Scorer:
    """Score evaluation results based on rubric criteria.

    Example:
        >>> scorer = Scorer("rubrics/default.yaml")
        >>> result = scorer.score({"Accuracy": 0.8, "Completeness": 0.9})
        >>> print(f"Score: {result.weighted_score:.2f}")
    """

    def __init__(self, rubric: str | Path | dict[str, Any]):
        """Initialize scorer with a rubric.

        Args:
            rubric: Either a path to a YAML rubric file, or an in-memory rubric dict.

        Raises:
            FileNotFoundError: If rubric file doesn't exist.
            ValueError: If rubric format is invalid.
        """
        if isinstance(rubric, dict):
            self.rubric = rubric
        else:
            rubric_path = Path(rubric)

            if not rubric_path.exists():
                raise FileNotFoundError(f"Rubric file not found: {rubric_path}")

            with rubric_path.open("r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                self.rubric = loaded if loaded is not None else {}

        if not isinstance(self.rubric, dict):
            raise ValueError("Rubric must be a YAML dictionary")

        self.criteria = self._parse_criteria(self.rubric.get("criteria", []))
        self.name = self.rubric.get("name", "Unnamed Rubric")
        self.version = self.rubric.get("version", "1.0")

    def _parse_criteria(self, raw_criteria: list[dict[str, Any]]) -> list[Criterion]:
        """Parse raw criteria from rubric."""
        criteria = []

        for item in raw_criteria:
            if not isinstance(item, dict) or "name" not in item:
                continue

            criteria.append(
                Criterion(
                    name=item["name"],
                    weight=float(item.get("weight", 1.0)),
                    description=item.get("description", ""),
                    min_value=float(item.get("min_value", 0.0)),
                    max_value=float(item.get("max_value", 1.0)),
                )
            )

        return criteria

    def score(self, results: dict[str, float]) -> ScoringResult:
        """Score results based on rubric criteria.

        Args:
            results: Dictionary of metric results, e.g., {'Accuracy': 0.8, 'Completeness': 0.9}

        Returns:
            ScoringResult with weighted and raw scores.
        """
        if not self.criteria:
            return ScoringResult(
                total_score=0.0,
                weighted_score=0.0,
            )

        total_weight = sum(c.weight for c in self.criteria)
        weighted_sum = 0.0
        raw_sum = 0.0
        criterion_scores: dict[str, float] = {}
        missing: list[str] = []

        for criterion in self.criteria:
            name = criterion.name

            if name not in results:
                missing.append(name)
                continue

            value = float(results[name])

            # Clamp to valid range
            value = max(criterion.min_value, min(criterion.max_value, value))

            # Normalize to 0-1 range
            range_size = criterion.max_value - criterion.min_value
            if range_size > 0:
                normalized = (value - criterion.min_value) / range_size
            else:
                normalized = value

            criterion_scores[name] = value
            weighted_sum += criterion.weight * normalized
            raw_sum += normalized

        weighted_score = weighted_sum / total_weight if total_weight > 0 else 0.0
        total_score = raw_sum / len(self.criteria) if self.criteria else 0.0

        return ScoringResult(
            total_score=total_score,
            weighted_score=weighted_score,
            criterion_scores=criterion_scores,
            missing_criteria=missing,
        )

    def validate_results(self, results: dict[str, float]) -> list[str]:
        """Validate that results contain all required criteria.

        Args:
            results: Dictionary of metric results.

        Returns:
            List of missing criterion names.
        """
        return [c.name for c in self.criteria if c.name not in results]
