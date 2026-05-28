"""Helpers for classifying optional LangChain/LangGraph import failures."""

from __future__ import annotations

_OPTIONAL_PREFIXES = ("langchain", "langgraph")


class MissingLangChainDependencyError(ImportError):
    """Raised when optional LangChain/LangGraph extras are not installed."""


def is_missing_langchain_dependency_error(exc: BaseException | None) -> bool:
    """Return True when *exc* is caused by a missing optional dependency."""
    for error in _walk_error_chain(exc):
        if not isinstance(error, ImportError):
            continue
        name = getattr(error, "name", None)
        if isinstance(name, str) and name.startswith(_OPTIONAL_PREFIXES):
            return True
    return False


def to_missing_langchain_dependency_error(
    exc: ImportError,
    *,
    install_hint: str = "pip install -e '.[langchain]'",
) -> MissingLangChainDependencyError:
    """Wrap an optional-dependency import error in a consistent message."""
    return MissingLangChainDependencyError(
        "LangChain extras not installed. Install with: " f"{install_hint}"
    )


def _walk_error_chain(exc: BaseException | None):
    """Yield *exc* and its chained causes/contexts without looping forever."""
    seen: set[int] = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__
