"""Shared workflow helper functions.

Pure-computation libraries that support the workflow runtime without depending
on server-specific state. ``ci_calculator`` is the source of truth for research
dimension names, default CI weights, and recency-decay logic.
"""

from __future__ import annotations

from agentic_v2.workflows.lib.ci_calculator import (
    DEFAULT_WEIGHTS,
    DOMAIN_RECENCY_DAYS,
    RESEARCH_DIMENSIONS,
    GateResult,
    check_gate,
    compute_ci,
    get_recency_window,
    load_recency_windows,
    recency_decay,
)

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
