"""Evaluation rubrics for scoring criteria.

This module provides rubric loading and management utilities.

Available Rubrics:
    - default: Basic 3-criteria rubric (Accuracy, Completeness, Efficiency)
    - agent: Comprehensive 6-criteria rubric for agent outputs
    - code: Specialized rubric for code generation
    - pattern: Rubric for reasoning pattern evaluation (ReAct, CoVe, etc.)

Example:
    >>> from agentic_v2_eval.rubrics import load_rubric, list_rubrics
    >>> print(list_rubrics())
    ['agent', 'code', 'default', 'pattern']
    >>> rubric = load_rubric("agent")
    >>> for criterion in rubric["criteria"]:
    ...     print(f"{criterion['name']}: {criterion['weight']}")
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

RUBRICS_DIR = Path(__file__).parent

# Rubric name constants for convenience
DEFAULT = "default"
AGENT = "agent"
CODE = "code"
PATTERN = "pattern"


def load_rubric(name: str = "default") -> dict[str, Any]:
    """Load a rubric by name.

    Args:
        name: Rubric name (without .yaml extension). Default is "default".
            Available: "default", "agent", "code", "pattern"

    Returns:
        Rubric configuration dictionary with keys:
            - criteria: List of scoring criteria
            - thresholds: Pass/fail thresholds (if defined)
            - metadata: Rubric metadata (if defined)

    Raises:
        FileNotFoundError: If rubric file doesn't exist.
    """
    rubric_path = RUBRICS_DIR / f"{name}.yaml"
    if not rubric_path.exists():
        available = ", ".join(list_rubrics())
        raise FileNotFoundError(f"Rubric not found: {name}. Available: {available}")

    with rubric_path.open("r", encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
    return data


def list_rubrics() -> list[str]:
    """List all available rubric names.

    Returns:
        List of rubric names (without .yaml extension).
    """
    return sorted([p.stem for p in RUBRICS_DIR.glob("*.yaml")])


def get_rubric_path(name: str) -> Path:
    """Get the filesystem path to a rubric file.

    Args:
        name: Rubric name (without .yaml extension).

    Returns:
        Path to the rubric YAML file.

    Raises:
        FileNotFoundError: If rubric doesn't exist.
    """
    rubric_path = RUBRICS_DIR / f"{name}.yaml"
    if not rubric_path.exists():
        available = ", ".join(list_rubrics())
        raise FileNotFoundError(f"Rubric not found: {name}. Available: {available}")
    return rubric_path


__all__ = [
    "AGENT",
    "CODE",
    # Constants
    "DEFAULT",
    "PATTERN",
    "RUBRICS_DIR",
    "get_rubric_path",
    "list_rubrics",
    "load_rubric",
]
