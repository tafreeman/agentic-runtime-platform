"""Path safety helpers for validating repository-local file paths.

Containment is decided with ``os.path.commonpath`` over fully realpath-ed
operands. That is deliberate: it is the barrier pattern CodeQL recognizes for
``py/path-injection``. ``Path.is_relative_to`` (and the ``in .parents`` check
before it) are equivalent in behavior but are not treated as sanitizers, which
is why alerts kept firing at every call site that reached this module.

The check is inlined in both public helpers rather than shared through a third
function so each one carries the barrier in the same frame as the value it
returns.
"""

from __future__ import annotations

import os
from pathlib import Path


def _validate_path_input(path: str | Path) -> str:
    """Return ``path`` as a string, rejecting empty and null-byte inputs.

    The value is returned unmodified — leading and trailing whitespace can be
    legal in a filename, so it is only inspected, never stripped.

    Raises:
        ValueError: If the path is empty, whitespace-only, or contains a null
            byte (which would truncate the path inside the C layer).
    """
    path_str = str(path)
    if not path_str.strip():
        raise ValueError("Path must not be empty")
    if "\0" in path_str:
        raise ValueError("Path must not contain null bytes")
    return path_str


def is_within_base(path: str | Path, base_dir: str | Path) -> bool:
    """Return True when ``path`` resolves under ``base_dir``."""
    resolved_path = os.path.realpath(_validate_path_input(path))
    resolved_base = os.path.realpath(base_dir)

    try:
        return os.path.commonpath([resolved_base, resolved_path]) == resolved_base
    except ValueError:
        # Raised when the operands share no prefix at all — on Windows that
        # means separate drives. Treat it as "outside the base" rather than
        # letting it surface to the caller as an unexpected error.
        return False


def ensure_within_base(path: str | Path, base_dir: str | Path) -> Path:
    """Resolve ``path`` and raise ValueError when it escapes ``base_dir``."""
    resolved_path = os.path.realpath(_validate_path_input(path))
    resolved_base = os.path.realpath(base_dir)

    try:
        within = os.path.commonpath([resolved_base, resolved_path]) == resolved_base
    except ValueError:
        within = False

    if not within:
        raise ValueError(f"Path escapes base directory: {path}")
    return Path(resolved_path)
