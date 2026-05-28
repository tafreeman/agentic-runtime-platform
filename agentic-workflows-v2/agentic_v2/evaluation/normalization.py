"""Normalization formula registry for workflow scoring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


def clamp01(value: float) -> float:
    """Clamp to canonical normalized range [0.0, 1.0]."""
    return max(0.0, min(1.0, float(value)))


def _binary(raw: Any, **_: Any) -> float:
    value = float(raw)
    if value not in (0.0, 1.0):
        raise ValueError("binary normalization expects raw value 0 or 1")
    return value


def _likert_1_5(raw: Any, **_: Any) -> float:
    return clamp01((float(raw) - 1.0) / 4.0)


def _likert_neg2_2(raw: Any, **_: Any) -> float:
    return clamp01((float(raw) + 2.0) / 4.0)


def _lower_is_better(raw: Any, **kwargs: Any) -> float:
    slo_good = kwargs.get("slo_good")
    slo_bad = kwargs.get("slo_bad")
    if slo_good is None or slo_bad is None:
        raise ValueError("lower_is_better requires slo_good and slo_bad")
    denominator = float(slo_bad) - float(slo_good)
    if denominator == 0:
        raise ValueError("lower_is_better requires slo_bad != slo_good")
    return clamp01((float(slo_bad) - float(raw)) / denominator)


def _zero_one(raw: Any, **_: Any) -> float:
    return clamp01(float(raw))


def _pairwise(raw: Any = None, **kwargs: Any) -> float:
    wins: float
    losses: float
    ties: float

    if isinstance(raw, dict):
        wins = float(raw.get("wins", 0))
        losses = float(raw.get("losses", 0))
        ties = float(raw.get("ties", 0))
    else:
        wins = float(kwargs.get("wins", 0))
        losses = float(kwargs.get("losses", 0))
        ties = float(kwargs.get("ties", 0))
        if raw is not None and not kwargs:
            return clamp01(float(raw))

    total = wins + losses + ties
    if total <= 0:
        return 0.0
    return clamp01((wins + 0.5 * ties) / total)


@dataclass(frozen=True)
class NormalizationFormula:
    """Registered normalization transform."""

    formula_id: str
    description: str
    transform: Callable[..., float]


FORMULA_REGISTRY: dict[str, NormalizationFormula] = {
    "binary": NormalizationFormula("binary", "Binary 0/1 passthrough", _binary),
    "likert_1_5": NormalizationFormula(
        "likert_1_5", "Likert 1..5 to 0..1", _likert_1_5
    ),
    "likert_neg2_2": NormalizationFormula(
        "likert_neg2_2",
        "Likert -2..2 to 0..1",
        _likert_neg2_2,
    ),
    "lower_is_better": NormalizationFormula(
        "lower_is_better",
        "SLO-bounded normalization for lower-is-better metrics",
        _lower_is_better,
    ),
    "zero_one": NormalizationFormula("zero_one", "Clamp 0..1", _zero_one),
    "pairwise": NormalizationFormula("pairwise", "Wins/losses/ties to 0..1", _pairwise),
}


def list_formula_ids() -> list[str]:
    """Return known formula IDs."""
    return sorted(FORMULA_REGISTRY.keys())


def is_registered_formula(formula_id: str) -> bool:
    """Check whether a formula ID is registered."""
    return formula_id in FORMULA_REGISTRY


def normalize_score(raw_score: Any, formula_id: str, **kwargs: Any) -> float:
    """Normalize a raw score using a registered formula."""
    formula = FORMULA_REGISTRY.get(formula_id)
    if formula is None:
        available = ", ".join(list_formula_ids())
        raise KeyError(
            f"Unknown normalization formula '{formula_id}'. Available: {available}"
        )
    return float(formula.transform(raw_score, **kwargs))


def adjust_for_sample_size(
    norm: float,
    n: int,
    *,
    prior: float = 0.5,
    k: float = 20.0,
) -> float:
    """Apply reliability adjustment for small sample counts."""
    if n < 0:
        raise ValueError("n must be >= 0")
    numerator = (float(n) * float(norm)) + (float(k) * float(prior))
    denominator = float(n) + float(k)
    if denominator <= 0:
        return clamp01(norm)
    return clamp01(numerator / denominator)
