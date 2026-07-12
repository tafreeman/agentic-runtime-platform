"""Tests that the LangGraph adapter emits DeprecationWarning on import.

The deprecation warning is emitted from the top-level module
(agentic_v2.langchain) and is also triggered transitively when the
adapter registration path (agentic_v2.adapters.langchain) is imported.
The adapter test requires langgraph; the module-level test does not
because the warning fires before any langgraph-dependent code.
"""

import importlib
import warnings

import pytest


@pytest.mark.skip(
    reason="agentic_v2.adapters.langchain does not emit DeprecationWarning on reload; warning is only raised from agentic_v2.langchain top-level module"
)
def test_langchain_adapter_emits_deprecation_warning() -> None:
    """Adapter package triggers deprecation warning via transitive import."""
    pytest.importorskip("langgraph")
    import agentic_v2.adapters.langchain

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.reload(agentic_v2.adapters.langchain)

    deprecation_warnings = [
        w for w in caught if issubclass(w.category, DeprecationWarning)
    ]
    assert deprecation_warnings, "Expected at least one DeprecationWarning"
    messages = [str(w.message) for w in deprecation_warnings]
    assert any(
        "ADR-013" in msg for msg in messages
    ), f"ADR-013 not found in warning messages: {messages}"
    assert any(
        "LangGraph" in msg or "langchain" in msg for msg in messages
    ), f"Adapter name not found in warning messages: {messages}"


@pytest.mark.xfail(
    reason=(
        "Canonical has NOT adopted the ADR-013 LangChain EOL deprecation "
        "warning (open decision, ADR-023 lab->canonical reconciliation). The "
        "lab fork emits it; canonical still actively supports the LangGraph "
        "adapter. Remove this xfail when ADR-013 EOL is accepted in canonical."
    ),
    strict=False,
)
def test_langchain_module_emits_deprecation_warning() -> None:
    """Top-level langchain module warns with ADR-013 reference on import."""
    pytest.importorskip("langgraph")
    import agentic_v2.langchain

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.reload(agentic_v2.langchain)

    deprecation_warnings = [
        w for w in caught if issubclass(w.category, DeprecationWarning)
    ]
    assert deprecation_warnings, "Expected at least one DeprecationWarning"
    messages = [str(w.message) for w in deprecation_warnings]
    assert any(
        "ADR-013" in msg for msg in messages
    ), f"ADR-013 not found in warning messages: {messages}"
    assert any(
        "LangGraph" in msg or "langchain" in msg for msg in messages
    ), f"Adapter name not found in warning messages: {messages}"


@pytest.mark.xfail(
    reason=(
        "Canonical has NOT adopted the ADR-013 LangChain EOL deprecation "
        "warning (open decision, ADR-023 lab->canonical reconciliation). The "
        "lab fork emits it; canonical still actively supports the LangGraph "
        "adapter. Remove this xfail when ADR-013 EOL is accepted in canonical."
    ),
    strict=False,
)
def test_langchain_module_warns_without_langgraph() -> None:
    """Warning fires even when langgraph is not installed.

    The deprecation warning is at module scope in agentic_v2.langchain,
    before any langgraph-dependent imports.  This test verifies the most
    common user scenario (langgraph not installed) by reloading the
    module directly — no langgraph dependency required.
    """
    import agentic_v2.langchain

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.reload(agentic_v2.langchain)

    deprecation_warnings = [
        w for w in caught if issubclass(w.category, DeprecationWarning)
    ]
    assert deprecation_warnings, "Expected at least one DeprecationWarning"
    messages = [str(w.message) for w in deprecation_warnings]
    assert any(
        "ADR-013" in msg for msg in messages
    ), f"ADR-013 not found in warning messages: {messages}"
