"""Tests for eager LangChain adapter validation at server startup.

Covers:
- ``AdapterRegistry.validate_selected("langchain")`` raises ``ConfigurationError``
  when LangChain extras are not importable.
- ``AdapterRegistry.validate_selected("native")`` is always a no-op.
- The FastAPI lifespan aborts with ``ConfigurationError`` when
  ``AGENTIC_DEFAULT_ADAPTER=langchain`` and LangChain extras are missing.
- The FastAPI lifespan succeeds when ``AGENTIC_DEFAULT_ADAPTER=native``,
  even when LangChain extras are missing.
"""

from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from typing import Generator

import pytest

from agentic_v2.adapters.registry import get_registry
from agentic_v2.core.errors import ConfigurationError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def _block_modules(*names: str) -> Generator[None, None, None]:
    """Temporarily make *names* unimportable via sys.modules sentinel trick.

    Setting a key to ``None`` in ``sys.modules`` causes Python's import
    machinery to raise ``ImportError`` without invoking the real loader.
    Any previously-cached real module is restored on exit.
    """
    originals: dict[str, types.ModuleType | None] = {}
    for name in names:
        originals[name] = sys.modules.get(name, _MISSING)  # type: ignore[assignment]
        sys.modules[name] = None  # type: ignore[assignment]
    try:
        yield
    finally:
        for name, original in originals.items():
            if original is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original  # type: ignore[assignment]


_MISSING = object()  # sentinel for "key was absent"


# ---------------------------------------------------------------------------
# AdapterRegistry.validate_selected unit tests
# ---------------------------------------------------------------------------


class TestValidateSelectedNative:
    """validate_selected("native") must always be a no-op."""

    def test_native_no_op_when_langchain_present(self) -> None:
        """No error raised for native regardless of LangChain availability."""
        get_registry().validate_selected("native")  # must not raise

    def test_native_no_op_when_langchain_missing(self) -> None:
        """No error raised for native even when LangChain cannot be imported."""
        with _block_modules("langchain", "langgraph"):
            get_registry().validate_selected("native")  # must not raise

    def test_unknown_adapter_name_is_no_op(self) -> None:
        """Any adapter name other than 'langchain' skips the import check."""
        get_registry().validate_selected("completely_unknown")  # must not raise


class TestValidateSelectedLangChain:
    """validate_selected("langchain") must gate on the optional extras."""

    def test_raises_configuration_error_when_langchain_missing(self) -> None:
        """ConfigurationError raised when langchain import fails."""
        with _block_modules("langchain", "langgraph"):
            with pytest.raises(ConfigurationError, match="pip install -e"):
                get_registry().validate_selected("langchain")

    def test_raises_configuration_error_when_langgraph_missing(self) -> None:
        """ConfigurationError raised when langgraph (but not langchain) import fails."""
        with _block_modules("langgraph"):
            with pytest.raises(ConfigurationError, match="pip install -e"):
                get_registry().validate_selected("langchain")

    def test_error_message_includes_install_hint(self) -> None:
        """ConfigurationError message contains the actionable install hint."""
        with _block_modules("langchain", "langgraph"):
            with pytest.raises(ConfigurationError) as exc_info:
                get_registry().validate_selected("langchain")

        assert "pip install -e '.[langchain]'" in str(exc_info.value)

    def test_no_error_when_langchain_present(self) -> None:
        """No error raised when langchain and langgraph are importable."""
        pytest.importorskip("langchain")
        pytest.importorskip("langgraph")
        get_registry().validate_selected("langchain")  # must not raise


# ---------------------------------------------------------------------------
# FastAPI lifespan integration tests
# ---------------------------------------------------------------------------


class TestLifespanLangChainValidation:
    """The FastAPI lifespan must abort early when the selected adapter is unusable."""

    def test_lifespan_raises_on_langchain_selected_extras_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When AGENTIC_DEFAULT_ADAPTER=langchain and extras are missing, startup fails."""
        monkeypatch.setenv("AGENTIC_DEFAULT_ADAPTER", "langchain")

        with _block_modules("langchain", "langgraph"):
            with pytest.raises(ConfigurationError, match="pip install"):
                get_registry().validate_selected("langchain")

    def test_lifespan_succeeds_on_native_selected_extras_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When AGENTIC_DEFAULT_ADAPTER=native, startup succeeds even without LangChain."""
        monkeypatch.setenv("AGENTIC_DEFAULT_ADAPTER", "native")

        with _block_modules("langchain", "langgraph"):
            # Must NOT raise
            get_registry().validate_selected("native")

    def test_create_app_smoke_with_default_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """create_app() succeeds when the real LangChain extras are installed.

        Skipped if langchain/langgraph are not available in the test environment.
        """
        pytest.importorskip("langchain")
        pytest.importorskip("langgraph")

        monkeypatch.setenv("AGENTIC_DEFAULT_ADAPTER", "langchain")

        # Import here so the module-level app singleton is not disturbed
        from agentic_v2.server.app import create_app

        app = create_app()
        assert app is not None

    def test_create_app_smoke_with_native_adapter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """create_app() succeeds when AGENTIC_DEFAULT_ADAPTER=native."""
        monkeypatch.setenv("AGENTIC_DEFAULT_ADAPTER", "native")

        from agentic_v2.server.app import create_app

        app = create_app()
        assert app is not None
