"""Loader for the evaluation YAML configuration.

This is scoring-domain configuration (rubric versions, dataset weights, pass
thresholds) consumed by the scoring logic in this package. It was extracted from
``agentic_v2.server.datasets`` so that the scoring package has no dependency on
the server transport layer; ``server`` now imports this loader from ``scoring``
(server -> scoring), not the reverse. See ADR-0007.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def _resolve_project_root() -> Path:
    """Locate the project root by searching parent directories for ``pyproject.toml``.

    Returns:
        Path to the project root directory.
    """
    this_file = Path(__file__).resolve()
    candidates = [this_file.parents[2], this_file.parents[3]]
    for root in candidates:
        if (root / "agentic_v2").exists() and (root / "pyproject.toml").exists():
            return root
        if (root / "src" / "agentic_v2").exists() and (
            root / "pyproject.toml"
        ).exists():
            return root
    return this_file.parents[2]


def _resolve_eval_config_path(project_root: Path) -> Path:
    """Resolve the path to ``evaluation.yaml`` under the project root.

    Args:
        project_root: Resolved project root directory.

    Returns:
        Path to the evaluation config file (may not exist on disk).
    """
    candidates = [
        project_root / "agentic_v2" / "config" / "defaults" / "evaluation.yaml",
        project_root / "src" / "agentic_v2" / "config" / "defaults" / "evaluation.yaml",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


_PROJECT_ROOT = _resolve_project_root()
_EVAL_CONFIG_PATH = _resolve_eval_config_path(_PROJECT_ROOT)


def _load_eval_config() -> dict[str, Any]:
    """Load and parse the evaluation YAML configuration file.

    Returns:
        Parsed config dict, or empty dict if the file is missing or invalid.
    """
    if not _EVAL_CONFIG_PATH.exists():
        return {}
    try:
        with _EVAL_CONFIG_PATH.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, yaml.YAMLError, ValueError) as exc:
        logger.warning("Failed to load evaluation config: %s", exc)
        return {}
