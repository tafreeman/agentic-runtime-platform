"""Backward-compatible re-exports for score normalization helpers.

The canonical normalization utilities now live in
:mod:`agentic_v2.evaluation.normalization`.  This shim re-exports all
public names so that existing ``from .normalization import ...`` imports
within the server package continue to work without modification.

Re-exported names:
    :data:`FORMULA_REGISTRY`, :class:`NormalizationFormula`,
    :func:`adjust_for_sample_size`, :func:`clamp01`,
    :func:`is_registered_formula`, :func:`list_formula_ids`,
    :func:`normalize_score`.
"""

from __future__ import annotations

from ..evaluation.normalization import (
    FORMULA_REGISTRY,
    NormalizationFormula,
    adjust_for_sample_size,
    clamp01,
    is_registered_formula,
    list_formula_ids,
    normalize_score,
)

__all__ = [
    "FORMULA_REGISTRY",
    "NormalizationFormula",
    "adjust_for_sample_size",
    "clamp01",
    "is_registered_formula",
    "list_formula_ids",
    "normalize_score",
]
