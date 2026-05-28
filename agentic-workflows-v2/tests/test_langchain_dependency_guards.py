from __future__ import annotations

import importlib

import pytest
from agentic_v2.langchain.dependencies import (
    MissingLangChainDependencyError,
    is_missing_langchain_dependency_error,
    to_missing_langchain_dependency_error,
)


def test_detects_missing_optional_langchain_dependency() -> None:
    error = ModuleNotFoundError("No module named 'langgraph'")
    error.name = "langgraph"

    assert is_missing_langchain_dependency_error(error) is True


def test_ignores_non_optional_import_errors() -> None:
    error = ImportError("cannot import name 'build_graph' from 'agentic_v2.langchain'")
    error.name = "agentic_v2.langchain"

    assert is_missing_langchain_dependency_error(error) is False


def test_wraps_missing_dependency_with_install_hint() -> None:
    error = ModuleNotFoundError("No module named 'langchain_core'")
    error.name = "langchain_core"

    wrapped = to_missing_langchain_dependency_error(error)

    assert isinstance(wrapped, MissingLangChainDependencyError)
    assert "Install with: pip install -e '.[langchain]'" in str(wrapped)


def test_langchain_adapter_symbol_raises_stored_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("agentic_v2.adapters.langchain")
    monkeypatch.delattr(module, "LangChainEngine", raising=False)
    monkeypatch.setattr(
        module,
        "_IMPORT_ERROR",
        MissingLangChainDependencyError("LangChain extras not installed"),
    )

    with pytest.raises(MissingLangChainDependencyError):
        _ = module.LangChainEngine
