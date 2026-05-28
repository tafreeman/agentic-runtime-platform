"""LangChain execution engine adapter.

Auto-registers the :class:`LangChainEngine` adapter when this package
is imported, provided that the LangChain/LangGraph dependencies are
available.  If they are not installed, registration is silently skipped.
"""

from __future__ import annotations

import logging

from ...langchain.dependencies import (
    is_missing_langchain_dependency_error,
)

logger = logging.getLogger(__name__)
_IMPORT_ERROR: ImportError | None = None

try:
    from ...core.errors import AdapterError
    from ..registry import get_registry
    from .engine import LangChainEngine

    get_registry().register("langchain", LangChainEngine)
except ImportError as exc:
    if not is_missing_langchain_dependency_error(exc):
        raise
    _IMPORT_ERROR = exc
    logger.debug(
        "LangChain/LangGraph not installed — skipping langchain adapter registration"
    )
except AdapterError:
    # Adapter may already be registered (e.g. during test re-imports).
    # Log and continue rather than crashing the import chain.
    logger.debug("langchain adapter registration skipped (already registered?)")


def __getattr__(name: str):
    if name == "LangChainEngine" and _IMPORT_ERROR is not None:
        raise _IMPORT_ERROR
    raise AttributeError(name)


__all__ = ["LangChainEngine"]
