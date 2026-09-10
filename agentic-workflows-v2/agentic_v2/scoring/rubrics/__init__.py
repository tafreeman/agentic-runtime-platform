"""Runtime-owned rubric resources (ADR-042 Slice C)."""

from __future__ import annotations

from importlib.resources import files
from typing import Any

import yaml


def load_rubric(name: str) -> dict[str, Any]:
    """Load a bundled rubric without depending on the legacy eval package."""
    if name not in {"agent", "code", "default"}:
        raise FileNotFoundError(f"Unknown runtime rubric: {name}")
    try:
        data = yaml.safe_load(
            files(__package__).joinpath(f"{name}.yaml").read_text("utf-8")
        )
    except yaml.YAMLError as exc:
        raise ValueError(f"Rubric {name} contains invalid YAML") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Rubric {name} must contain a mapping")
    return data
