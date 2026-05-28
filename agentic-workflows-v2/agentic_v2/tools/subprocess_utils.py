"""Shared subprocess environment utilities for tool modules."""

from __future__ import annotations

import os

_SAFE_ENV_KEYS: frozenset[str] = frozenset(
    {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "TMPDIR",
        "HOME",
        "USERPROFILE",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PYTHONDONTWRITEBYTECODE",
    }
)


def minimal_subprocess_env() -> dict[str, str]:
    """Return a minimal environment for subprocess execution.

    Includes only keys required for the subprocess to locate executables
    and write temporary files. Excludes all API keys, tokens, and
    secrets.
    """
    safe_upper = {k.upper() for k in _SAFE_ENV_KEYS}
    env = {key: value for key, value in os.environ.items() if key.upper() in safe_upper}
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    return env
