"""Path safety helpers for validating repository-local file paths."""

from __future__ import annotations

import os
from pathlib import Path


def is_within_base(path: str | Path, base_dir: str | Path) -> bool:
    """Return True when ``path`` resolves under ``base_dir``."""
    resolved_base = Path(base_dir).resolve()
    resolved_path = Path(path).resolve()

    try:
        return resolved_path.is_relative_to(resolved_base)
    except AttributeError:
        base_str = str(resolved_base)
        path_str = str(resolved_path)
        if path_str == base_str:
            return True
        return path_str.startswith(base_str + os.sep)


def ensure_within_base(path: str | Path, base_dir: str | Path) -> Path:
    """Resolve ``path`` and raise ValueError when it escapes ``base_dir``."""
    resolved = Path(path).resolve()
    if not is_within_base(resolved, base_dir):
        raise ValueError(f"Path escapes base directory: {path}")
    return resolved
