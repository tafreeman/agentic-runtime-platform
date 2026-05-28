"""
Windows Console Encoding Fix
============================

Provides consistent UTF-8 handling for Windows console output.
Import this module early in any script to fix encoding issues.

Usage:
    from tools.core._encoding import setup_encoding
    setup_encoding()  # Apply fix if needed

    # Or use the safe_print helper:
    from tools.core._encoding import safe_print
    safe_print("Hello 世界 🌍")

Note: This fix is automatically applied when importing from tool_init.py
"""

from __future__ import annotations

import io
import os
import sys
from typing import Any

_ENCODING_SETUP_DONE = False


def _is_pytest_running() -> bool:
    """Check if we're running under pytest."""
    return "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ


def _is_already_wrapped(stream) -> bool:
    """Check if stream is already a TextIOWrapper with UTF-8."""
    return (
        isinstance(stream, io.TextIOWrapper)
        and getattr(stream, "encoding", "").lower() == "utf-8"
    )


def setup_encoding() -> bool:
    """Apply Windows console encoding fix.

    Returns:
        True if fix was applied, False if not needed or already applied
    """
    global _ENCODING_SETUP_DONE

    if _ENCODING_SETUP_DONE:
        return False

    if sys.platform != "win32":
        _ENCODING_SETUP_DONE = True
        return False

    # Don't wrap during pytest (interferes with output capture)
    if _is_pytest_running():
        _ENCODING_SETUP_DONE = True
        return False

    os.environ["PYTHONIOENCODING"] = "utf-8"

    try:
        if not _is_already_wrapped(sys.stdout):
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding="utf-8", errors="replace"
            )
        if not _is_already_wrapped(sys.stderr):
            sys.stderr = io.TextIOWrapper(
                sys.stderr.buffer, encoding="utf-8", errors="replace"
            )
        _ENCODING_SETUP_DONE = True
        return True
    except (OSError, AttributeError):
        # Already wrapped or not available
        _ENCODING_SETUP_DONE = True
        return False


def safe_str(text: Any) -> str:
    """Ensure value is a string safe for console output."""
    if not isinstance(text, str):
        text = str(text)
    return text.encode("utf-8", errors="replace").decode("utf-8")


def safe_print(text: str = "", **kwargs) -> None:
    """Print text safely, handling Unicode errors."""
    try:
        print(text, **kwargs)
    except UnicodeEncodeError:
        print(safe_str(text), **kwargs)


# Auto-apply on import (for convenience)
setup_encoding()
