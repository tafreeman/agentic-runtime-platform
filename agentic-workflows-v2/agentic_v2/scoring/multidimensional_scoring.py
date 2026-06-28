"""ADR-007: Multidimensional research quality scoring engine.

Implements the DORA-style classification matrix described in ADR-007.
Each dimension (coverage, source_quality, agreement, verification, recency)
is independently classified into a performance tier (Elite, High, Medium, Low).
The stop gate is entirely non-compensatory: ALL dimensions must reach ``High``
or better before the pipeline may halt.

A Confidence Index (CI) weighted sum is retained ONLY as a tiebreaker for
``coalesce()`` best-of-N round selection; it has no role in the pass/fail gate.

Usage
-----
This module runs **alongside** the legacy ``evaluation_scoring.py`` engine.
To activate it set ``scoring_engine: multidimensional`` in ``evaluation.yaml``
(under ``evaluation.deep_research``) or pass ``engine="multidimensional"`` to
:func:`score_research_round`.  The legacy engine remains the default until the
flag is flipped.

Feature flag location::

    evaluation:
      deep_research:
        scoring_engine: multidimensional   # or "legacy" (default)

Backward compatibility
----------------------
All public functions return plain ``dict`` payloads so callers need no imports
from this module.  The ``ci_score`` key is still present in every payload for
compatibility with the workflow YAML and the ``final_synthesis`` step.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from agentic_v2.workflows.lib import ci_calculator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Dimension names used by the multidimensional scoring engine.
#: Single source of truth: ``workflows.lib.ci_calculator`` (ADR-023 reconciliation —
#: re-introduced from the lab fork; this module re-exports the names rather than
#: re-declaring them). ``ci_calculator`` is pure-stdlib and imports nothing from
#: ``server``, so there is no import cycle.
RESEARCH_DIMENSIONS: tuple[str, ...] = ci_calculator.RESEARCH_DIMENSIONS

#: CI tiebreaker weights — used ONLY inside ``coalesce()`` best-of-N ranking.
#: Per ADR-007 §4.3 these are provisional; equal weights may be substituted.
_TIEBREAKER_WEIGHTS: Mapping[str, float] = MappingProxyType(
    {
        "coverage": 0.25,
        "source_quality": 0.20,
        "agreement": 0.20,
        "verification": 0.20,
        "recency": 0.15,
    }
)

#: Minimum ``recent_sources_count`` required by the hard floor gate.
_DEFAULT_MIN_RECENT_SOURCES: int = 10

# ---------------------------------------------------------------------------
# Tier model
# ---------------------------------------------------------------------------


class ResearchTier(str, Enum):
    """Performance tier for a single research dimension (DORA-inspired)."""

    ELITE = "Elite"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"

    @property
    def rank(self) -> int:
        """Numeric rank: higher is better (Elite=3, High=2, Medium=1, Low=0)."""
        return {"Elite": 3, "High": 2, "Medium": 1, "Low": 0}[self.value]

    def meets_minimum(self, minimum: "ResearchTier") -> bool:
        """Return True iff this tier is at or above *minimum*."""
        return self.rank >= minimum.rank


#: Default tier thresholds for normalised 0-1 dimension scores.
#: Recency is not special-cased: its ``recency_score`` is a normalised 0-1 value
#: classified through these same thresholds as every other dimension. The
#: separate ``recent_sources_count >= min_recent_sources`` hard floor (see
#: :class:`MultidimensionalGateResult.sources_floor_passed`) gates the round
#: independently of the recency tier.
_SCORE_THRESHOLDS: dict[str, tuple[float, float, float]] = {
    # dimension: (elite_floor, high_floor, medium_floor)
    "coverage": (0.90, 0.75, 0.50),
    "source_quality": (0.90, 0.75, 0.50),
    "agreement": (0.90, 0.75, 0.50),
    "verification": (0.90, 0.75, 0.50),
    "recency": (0.90, 0.75, 0.50),  # recency_score, normalised 0-1
}


def classify_dimension(
    dimension: str,
    score_0_1: float,
    thresholds: dict[str, tuple[float, float, float]] | None = None,
) -> ResearchTier:
    """Classify a single normalised dimension score (0–1) into a tier.

    Parameters
    ----------
    dimension:
        One of ``RESEARCH_DIMENSIONS``.
    score_0_1:
        Normalised dimension score in ``[0, 1]``.
    thresholds:
        Optional override threshold map.  If omitted the module-level
        ``_SCORE_THRESHOLDS`` is used.

    Returns
    -------
    ResearchTier
    """
    effective = thresholds if thresholds is not None else _SCORE_THRESHOLDS
    elite_f, high_f, medium_f = effective.get(dimension, (0.90, 0.75, 0.50))
    if score_0_1 >= elite_f:
        return ResearchTier.ELITE
    if score_0_1 >= high_f:
        return ResearchTier.HIGH
    if score_0_1 >= medium_f:
        return ResearchTier.MEDIUM
    return ResearchTier.LOW


# ---------------------------------------------------------------------------
# Core data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DimensionResult:
    """Classification result for one research dimension."""

    dimension: str
    score_0_1: float
    tier: ResearchTier
    gate_passed: bool  # True iff tier >= High

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "score": round(self.score_0_1, 4),
            "tier": self.tier.value,
            "tier_rank": self.tier.rank,
            "gate_passed": self.gate_passed,
        }


@dataclass(frozen=True)
class MultidimensionalGateResult:
    """Full non-compensatory gate evaluation for one research round."""

    dimensions: tuple[DimensionResult, ...] = ()
    recent_sources_count: int = 0
    min_recent_sources: int = _DEFAULT_MIN_RECENT_SOURCES
    critical_contradictions: int = 0
    consecutive_regression: bool = False

    # Computed
    ci_tiebreaker: float = 0.0  # CI scalar — tiebreaker only

    def __post_init__(self) -> None:
        object.__setattr__(self, "dimensions", tuple(self.dimensions))

    @property
    def all_dimensions_high(self) -> bool:
        return all(d.gate_passed for d in self.dimensions)

    @property
    def sources_floor_passed(self) -> bool:
        return self.recent_sources_count >= self.min_recent_sources

    @property
    def no_critical_contradictions(self) -> bool:
        return self.critical_contradictions == 0

    @property
    def gate_passed(self) -> bool:
        """Non-compensatory conjunction: every sub-gate must pass."""
        return (
            self.all_dimensions_high
            and self.sources_floor_passed
            and self.no_critical_contradictions
            and not self.consecutive_regression
        )

    @property
    def failed_dimensions(self) -> tuple[str, ...]:
        return tuple(d.dimension for d in self.dimensions if not d.gate_passed)

    def to_dict(self) -> dict[str, Any]:
        dim_by_name = {d.dimension: d.to_dict() for d in self.dimensions}
        return {
            # Per-dimension classification matrix
            "dimension_matrix": dim_by_name,
            "dimensions": [d.to_dict() for d in self.dimensions],
            # Non-compensatory gate sub-results
            "all_dimensions_high": self.all_dimensions_high,
            "sources_floor_passed": self.sources_floor_passed,
            "no_critical_contradictions": self.no_critical_contradictions,
            "consecutive_regression": self.consecutive_regression,
            # Top-level gate
            "gate_passed": self.gate_passed,
            "failed_dimensions": self.failed_dimensions,
            # Hard counts
            "recent_sources_count": self.recent_sources_count,
            "min_recent_sources": self.min_recent_sources,
            "critical_contradictions": self.critical_contradictions,
            # CI tiebreaker — retained for coalesce() compatibility
            "ci_score": round(self.ci_tiebreaker, 4),
            "ci_role": "tiebreaker_only",
            "generated_at": datetime.now(UTC).isoformat(),
            "scoring_engine": "multidimensional",
        }


# ---------------------------------------------------------------------------
# CI tiebreaker (ADR-007 §4.3)
# ---------------------------------------------------------------------------


def compute_ci_tiebreaker(
    scores: dict[str, float],
    *,
    weights: Mapping[str, float] | None = None,
) -> float:
    """Compute the CI weighted sum for coalesce() tiebreaking only.

    This is NOT the stop gate.  It is used only when ``coalesce()`` must
    rank multiple passing rounds or select the "least bad" round when all
    rounds fail.

    Computes a weighted arithmetic mean over the five research dimensions.
    Missing dimensions are treated as zero. The result is clamped to ``[0, 1]``.

    Parameters
    ----------
    scores:
        Mapping of ``{dimension: normalised_score_0_1}`` for each of the
        five research dimensions.
    weights:
        Optional override weight map.  Defaults to :data:`_TIEBREAKER_WEIGHTS`.

    Returns
    -------
    float
        Weighted CI score in ``[0, 1]``.
    """
    effective_weights = (
        dict(weights) if weights is not None else dict(_TIEBREAKER_WEIGHTS)
    )
    weight_total = sum(effective_weights.values())
    if weight_total <= 0:
        return 0.0
    weighted_sum = sum(
        float(scores.get(dim, 0.0)) * float(w) for dim, w in effective_weights.items()
    )
    return max(0.0, min(1.0, weighted_sum / weight_total))


# ---------------------------------------------------------------------------
# Main evaluation entry point
# ---------------------------------------------------------------------------


def evaluate_research_round(
    *,
    coverage_score: float,
    source_quality_score: float,
    agreement_score: float,
    verification_score: float,
    recency_score: float,
    recent_sources_count: int,
    critical_contradictions: int,
    min_recent_sources: int = _DEFAULT_MIN_RECENT_SOURCES,
    consecutive_regression: bool = False,
    tiebreaker_weights: Mapping[str, float] | None = None,
    tier_thresholds: dict[str, tuple[float, float, float]] | None = None,
) -> MultidimensionalGateResult:
    """Evaluate one research round through the multidimensional gate.

    All score parameters are normalised floats in ``[0, 1]``.

    Returns
    -------
    MultidimensionalGateResult
        Full gate evaluation including per-dimension tiers, gate decision,
        and CI tiebreaker value.
    """
    # Build a local threshold map — never mutate the module-level constant.
    thresholds = dict(_SCORE_THRESHOLDS)
    if tier_thresholds:
        thresholds.update(tier_thresholds)

    raw_scores = {
        "coverage": coverage_score,
        "source_quality": source_quality_score,
        "agreement": agreement_score,
        "verification": verification_score,
        "recency": recency_score,
    }

    min_tier = ResearchTier.HIGH
    dimensions: list[DimensionResult] = []
    for dim in RESEARCH_DIMENSIONS:
        score = max(0.0, min(1.0, raw_scores.get(dim, 0.0)))
        tier = classify_dimension(dim, score, thresholds)
        dimensions.append(
            DimensionResult(
                dimension=dim,
                score_0_1=score,
                tier=tier,
                gate_passed=tier.meets_minimum(min_tier),
            )
        )

    ci = compute_ci_tiebreaker(raw_scores, weights=tiebreaker_weights)

    return MultidimensionalGateResult(
        dimensions=dimensions,
        recent_sources_count=recent_sources_count,
        min_recent_sources=min_recent_sources,
        critical_contradictions=critical_contradictions,
        consecutive_regression=consecutive_regression,
        ci_tiebreaker=ci,
    )


def evaluate_research_round_from_step_outputs(
    step_outputs: dict[str, Any],
    *,
    min_recent_sources: int = _DEFAULT_MIN_RECENT_SOURCES,
    consecutive_regression: bool = False,
    tiebreaker_weights: Mapping[str, float] | None = None,
) -> MultidimensionalGateResult:
    """Convenience wrapper that reads directly from a ``coverage_confidence_audit`` step
    output dict.

    The step output keys produced by ``deep_research.yaml`` are::

        coverage_score, source_quality_score, agreement_score,
        verification_score, recency_score, recent_source_count,
        critical_contradictions

    Parameters
    ----------
    step_outputs:
        The ``outputs`` dict from a ``coverage_confidence_audit_roundN`` step.
    """

    def _float(key: str, default: float = 0.0) -> float:
        try:
            return float(step_outputs.get(key, default))
        except (TypeError, ValueError):
            return default

    def _int(key: str, default: int = 0) -> int:
        try:
            return int(step_outputs.get(key, default))
        except (TypeError, ValueError):
            return default

    return evaluate_research_round(
        coverage_score=_float("coverage_score"),
        source_quality_score=_float("source_quality_score"),
        agreement_score=_float("agreement_score"),
        verification_score=_float("verification_score"),
        recency_score=_float("recency_score"),
        recent_sources_count=_int("recent_source_count"),
        critical_contradictions=_int("critical_contradictions"),
        min_recent_sources=min_recent_sources,
        consecutive_regression=consecutive_regression,
        tiebreaker_weights=tiebreaker_weights,
    )


# ---------------------------------------------------------------------------
# Feature-flag router
# ---------------------------------------------------------------------------


def is_multidimensional_engine_active(eval_config: dict[str, Any]) -> bool:
    """Return True iff the multidimensional engine is enabled in config.

    Reads ``evaluation.deep_research.scoring_engine`` from the loaded config.
    Any value other than ``"multidimensional"`` keeps the legacy engine active.

    Example config::

        evaluation:
          deep_research:
            scoring_engine: multidimensional
    """
    engine = (
        eval_config.get("evaluation", {})
        .get("deep_research", {})
        .get("scoring_engine", "legacy")
    )
    return str(engine).strip().lower() == "multidimensional"


def research_stop_gate(
    step_outputs: dict[str, Any],
    eval_config: dict[str, Any],
    *,
    min_recent_sources: int = _DEFAULT_MIN_RECENT_SOURCES,
    consecutive_regression: bool = False,
) -> dict[str, Any]:
    """Route-aware stop gate: returns multidimensional or legacy result dict.

    Call this from orchestration code that needs to remain engine-agnostic.
    The returned dict always contains ``gate_passed`` and ``ci_score`` for
    backward compatibility with the YAML ``when:`` expressions.

    Parameters
    ----------
    step_outputs:
        Outputs dict from the ``coverage_confidence_audit_roundN`` step.
    eval_config:
        The loaded evaluation YAML config (from ``_load_eval_config()``).

    Returns
    -------
    dict
        Always includes ``gate_passed`` (bool) and ``ci_score`` (float 0–1).
        If the multidimensional engine is active also includes
        ``dimension_matrix``, ``failed_dimensions``, and ``scoring_engine``.
    """
    if is_multidimensional_engine_active(eval_config):
        result = evaluate_research_round_from_step_outputs(
            step_outputs,
            min_recent_sources=min_recent_sources,
            consecutive_regression=consecutive_regression,
        )
        return result.to_dict()

    # Legacy: re-use the existing ci_score + simple threshold logic so the
    # caller gets a uniform dict shape (gate_passed + ci_score always present).
    try:
        ci = float(step_outputs.get("ci_score", 0.0))
    except (TypeError, ValueError):
        ci = 0.0

    try:
        recent = int(step_outputs.get("recent_source_count", 0))
    except (TypeError, ValueError):
        recent = 0

    try:
        contradictions = int(step_outputs.get("critical_contradictions", 0))
    except (TypeError, ValueError):
        contradictions = 0

    min_ci = float(
        eval_config.get("evaluation", {}).get("deep_research", {}).get("min_ci", 0.80)
    )
    gate_passed = (
        ci >= min_ci
        and recent >= min_recent_sources
        and contradictions == 0
        and not consecutive_regression
    )
    return {
        "gate_passed": gate_passed,
        "ci_score": round(ci, 4),
        "scoring_engine": "legacy",
        "recent_sources_count": recent,
        "critical_contradictions": contradictions,
    }


# ---------------------------------------------------------------------------
# coalesce() helper: select best-of-N round
# ---------------------------------------------------------------------------


def _round_sort_key(result: dict[str, Any], index: int) -> tuple[int, float, int]:
    """Build a lexicographic sort key for round selection.

    Order (descending priority):
    1. ``gate_passed`` — passing rounds always beat failing ones.
    2. ``ci_score`` — higher CI tiebreaker wins among same gate status.
    3. ``-index`` — earlier rounds win when gate and CI are identical
       (prefer the first converging round to minimise compute).
    """
    gate = 1 if result.get("gate_passed", False) else 0
    ci = float(result.get("ci_score", 0.0))
    return (gate, ci, -index)


def coalesce_best_round(
    round_results: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Select the best research round using lexicographic ranking.

    Selection order (highest priority first):
    1. ``gate_passed`` — passing rounds always beat failing rounds.
    2. ``ci_score`` — among rounds with the same gate status, higher CI wins.
    3. Round index — earlier rounds win ties (prefer the first converging
       round to minimize unnecessary compute).

    Parameters
    ----------
    round_results:
        List of dicts returned by :func:`research_stop_gate` or
        :meth:`MultidimensionalGateResult.to_dict`, one per round R1–R4.
        Pass ``None`` entries for rounds that did not execute.

    Returns
    -------
    dict or None
        The selected round result, or ``None`` if the list is empty.
    """
    indexed: list[tuple[dict[str, Any], int]] = [
        (r, i) for i, r in enumerate(round_results) if isinstance(r, dict)
    ]
    if not indexed:
        return None

    best_result, _best_idx = max(
        indexed,
        key=lambda pair: _round_sort_key(pair[0], pair[1]),
    )
    return best_result


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

__all__ = [
    "RESEARCH_DIMENSIONS",
    "DimensionResult",
    "MultidimensionalGateResult",
    "ResearchTier",
    "classify_dimension",
    "coalesce_best_round",
    "compute_ci_tiebreaker",
    "evaluate_research_round",
    "evaluate_research_round_from_step_outputs",
    "is_multidimensional_engine_active",
    "research_stop_gate",
]
