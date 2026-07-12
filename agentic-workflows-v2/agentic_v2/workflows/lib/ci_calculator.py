"""Confidence-index helpers for multidimensional research scoring.

Source of truth for the research dimension names, default weights, and
recency logic shared across the workflow runtime. ``scoring.multidimensional_scoring``
delegates its CI tiebreaker computation here while keeping its own
tier-classification and gate-evaluation responsibilities.

This module is pure computation: it imports nothing from ``server`` or
``scoring`` (no FastAPI, no async server state) so it can be safely imported by
those modules without risking a circular import.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

RESEARCH_DIMENSIONS: tuple[str, ...] = (
    "coverage",
    "source_quality",
    "agreement",
    "verification",
    "recency",
)

DEFAULT_WEIGHTS: Mapping[str, float] = MappingProxyType(
    {
        "coverage": 0.25,
        "source_quality": 0.20,
        "agreement": 0.20,
        "verification": 0.20,
        "recency": 0.15,
    }
)

DOMAIN_RECENCY_DAYS: Mapping[str, int] = MappingProxyType(
    {
        "ai_ml": 90,
        "cloud_infrastructure": 180,
        "programming_languages": 365,
        "academic_research": 730,
        "default": 183,
    }
)


@dataclass(frozen=True)
class GateResult:
    """Result of the non-compensatory research confidence gate."""

    passed: bool
    all_dimensions_high: bool
    sources_floor_passed: bool
    no_critical_contradictions: bool
    no_regression: bool
    reason: str = ""


def _clamp_score(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def compute_ci(
    scores: Mapping[str, float],
    *,
    weights: Mapping[str, float] | None = None,
    method: str = "arithmetic",
) -> float:
    """Compute a normalized confidence index from dimension scores."""

    effective_weights = weights or DEFAULT_WEIGHTS
    total_weight = sum(
        float(effective_weights.get(dim, 0.0)) for dim in RESEARCH_DIMENSIONS
    )
    if total_weight <= 0:
        return 0.0

    if method == "arithmetic":
        total = sum(
            _clamp_score(scores.get(dim, 0.0)) * float(effective_weights.get(dim, 0.0))
            for dim in RESEARCH_DIMENSIONS
        )
        return _clamp_score(total / total_weight)

    if method == "geometric":
        product = 1.0
        for dim in RESEARCH_DIMENSIONS:
            score = _clamp_score(scores.get(dim, 0.0))
            if math.isclose(score, 0.0, abs_tol=1e-10):
                return 0.0
            product *= score ** float(effective_weights.get(dim, 0.0))
        return _clamp_score(product ** (1.0 / total_weight))

    raise ValueError(f"Unsupported CI method: {method}")


def check_gate(
    scores: Mapping[str, float],
    *,
    high_threshold: float = 0.75,
    recent_source_count: int = 0,
    min_recent_sources: int = 0,
    critical_contradictions: int = 0,
    previous_ci: float | None = None,
    current_ci: float | None = None,
) -> GateResult:
    """Evaluate the research stop gate without allowing score compensation."""

    low_dimensions = [
        dim
        for dim in RESEARCH_DIMENSIONS
        if _clamp_score(scores.get(dim, 0.0)) < high_threshold
    ]
    all_dimensions_high = not low_dimensions
    sources_floor_passed = recent_source_count >= min_recent_sources
    no_critical_contradictions = critical_contradictions == 0
    no_regression = (
        previous_ci is None or current_ci is None or current_ci >= previous_ci
    )

    reasons: list[str] = []
    if not all_dimensions_high:
        reasons.append("low dimensions: " + ", ".join(low_dimensions))
    if not sources_floor_passed:
        reasons.append("insufficient recent sources")
    if not no_critical_contradictions:
        reasons.append("critical contradiction detected")
    if not no_regression:
        reasons.append("confidence regression detected")

    passed = (
        all_dimensions_high
        and sources_floor_passed
        and no_critical_contradictions
        and no_regression
    )
    return GateResult(
        passed=passed,
        all_dimensions_high=all_dimensions_high,
        sources_floor_passed=sources_floor_passed,
        no_critical_contradictions=no_critical_contradictions,
        no_regression=no_regression,
        reason="; ".join(reasons),
    )


def load_recency_windows(config: Mapping[str, object]) -> Mapping[str, int]:
    """Load recency windows from evaluation config with safe defaults."""

    windows = dict(DOMAIN_RECENCY_DAYS)
    raw = config.get("evaluation")
    if not isinstance(raw, Mapping):
        return MappingProxyType(windows)
    deep_research = raw.get("deep_research")
    if not isinstance(deep_research, Mapping):
        return MappingProxyType(windows)
    overrides = deep_research.get("recency_windows")
    if not isinstance(overrides, Mapping):
        return MappingProxyType(windows)
    for key, value in overrides.items():
        if isinstance(key, str) and isinstance(value, int) and value > 0:
            windows[key] = value
    return MappingProxyType(windows)


def get_recency_window(
    domain: str = "default",
    *,
    config_windows: Mapping[str, int] | None = None,
) -> int:
    """Return the recency half-life window for a domain."""

    windows = config_windows or DOMAIN_RECENCY_DAYS
    return int(
        windows.get(domain, windows.get("default", DOMAIN_RECENCY_DAYS["default"]))
    )


def recency_decay(
    age_days: float,
    *,
    half_life_days: float | None = None,
    domain: str = "default",
    config_windows: Mapping[str, int] | None = None,
) -> float:
    """Return exponential recency decay where half-life maps to score 0.5."""

    if age_days <= 0:
        return 1.0
    half_life = (
        float(half_life_days)
        if half_life_days is not None
        else float(get_recency_window(domain, config_windows=config_windows))
    )
    if half_life <= 0:
        return 0.0
    return _clamp_score(math.exp(-math.log(2) / half_life * age_days))


__all__ = [
    "RESEARCH_DIMENSIONS",
    "DEFAULT_WEIGHTS",
    "DOMAIN_RECENCY_DAYS",
    "GateResult",
    "compute_ci",
    "check_gate",
    "load_recency_windows",
    "get_recency_window",
    "recency_decay",
]
