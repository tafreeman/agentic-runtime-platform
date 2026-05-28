"""Shared summary statistic computation for evaluation reporters.

Provides :func:`calculate_summary`, which extracts all numeric fields
from a list of result dicts and computes count, mean, and optionally
min/max aggregates.  Used by JSON, Markdown, and HTML reporters.
"""

from __future__ import annotations

from typing import Any


def calculate_summary(
    results: list[dict[str, Any]],
    *,
    include_min_max: bool = False,
) -> dict[str, Any]:
    """Calculate aggregate summary stats for reporter outputs."""
    if not results:
        return {"count": 0}

    summary: dict[str, Any] = {"count": len(results)}
    numeric_keys: dict[str, list[float]] = {}

    for result in results:
        for key, value in result.items():
            if isinstance(value, (int, float)):
                numeric_keys.setdefault(key, []).append(float(value))

    for key, values in numeric_keys.items():
        if not values:
            continue
        summary[f"{key}_mean"] = sum(values) / len(values)
        if include_min_max:
            summary[f"{key}_min"] = min(values)
            summary[f"{key}_max"] = max(values)

    return summary
