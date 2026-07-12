"""Unit tests for the ``AGENTIC_NO_LLM=1`` short-circuit in ``langchain/models.py``.

Covers:
  - ``get_chat_model()`` short-circuiting to ``build_placeholder_model``
    before any provider builder runs (proves zero ``GITHUB_TOKEN`` /
    provider-key imports under the flag)
  - ``PlaceholderChatModel`` contract: ``_llm_type == "placeholder"``,
    ``bind_tools`` returns a new instance, ``_astream`` yields a single
    chunk, negative-control ``ValueError`` regression
"""

from __future__ import annotations

import pytest

# Skip this entire module at collection time if langchain_core is not installed.
# Users running only the native suite must not be forced to install LangChain.
langchain_core = pytest.importorskip("langchain_core")

from agentic_v2.langchain.models import get_chat_model
from agentic_v2.settings import get_settings

_PLACEHOLDER_PREFIX = "[AGENTIC_NO_LLM placeholder]"


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch):
    """Bust the settings LRU cache before and after every test so that monkeypatch env
    changes are visible to get_settings() callers."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.unit
def test_flag_returns_placeholder_chat_model_without_credentials(monkeypatch):
    """AGENTIC_NO_LLM=1 must let get_chat_model() return a placeholder model even when
    GITHUB_TOKEN is absent — no credential error should be raised.

    FAILS today: get_chat_model() calls build_github_model() which raises
    ValueError("GITHUB_TOKEN environment variable is required...") before
    the flag short-circuit exists.
    """
    monkeypatch.setenv("AGENTIC_NO_LLM", "1")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    get_settings.cache_clear()

    print("DEBUG TEST 1:", get_settings().agentic_no_llm)

    model = get_chat_model("gh:openai/gpt-4o")

    assert (
        model._llm_type == "placeholder"
    ), f"Expected _llm_type='placeholder', got {model._llm_type!r}"


@pytest.mark.unit
def test_flag_placeholder_generates_prefixed_aimessage(monkeypatch):
    """Invoking the placeholder model must return an AIMessage whose content starts with
    the placeholder prefix.

    FAILS today: get_chat_model() never reaches the placeholder path.
    """
    from langchain_core.messages import HumanMessage

    monkeypatch.setenv("AGENTIC_NO_LLM", "1")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    get_settings.cache_clear()

    model = get_chat_model("gh:openai/gpt-4o")
    result = model.invoke([HumanMessage(content="hi")])

    assert result.content.startswith(_PLACEHOLDER_PREFIX), (
        f"AIMessage content {result.content!r} does not start with "
        f"{_PLACEHOLDER_PREFIX!r}"
    )


@pytest.mark.unit
def test_flag_bind_tools_is_noop_and_still_returns_placeholder(monkeypatch):
    """bind_tools() on the placeholder model must degrade cleanly.

    After binding a tool schema, invoke() must still return a placeholder
    AIMessage — no errors, no real tool calls.

    FAILS today: get_chat_model() never reaches the placeholder path.
    """
    from langchain_core.messages import HumanMessage

    monkeypatch.setenv("AGENTIC_NO_LLM", "1")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    get_settings.cache_clear()

    bound_model = get_chat_model("gh:openai/gpt-4o").bind_tools(
        [
            {
                "type": "function",
                "function": {
                    "name": "noop",
                    "description": "x",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
    )
    result = bound_model.invoke([HumanMessage(content="hi")])

    assert result.content.startswith(_PLACEHOLDER_PREFIX), (
        f"After bind_tools(), AIMessage content {result.content!r} does not "
        f"start with {_PLACEHOLDER_PREFIX!r}"
    )


@pytest.mark.unit
def test_flag_unset_still_raises_on_missing_credentials(monkeypatch):
    """When AGENTIC_NO_LLM is absent, get_chat_model('gh:...') must still raise
    ValueError mentioning GITHUB_TOKEN when the token is not set.

    This is the no-regression control — the short-circuit must be
    strictly gated on the flag.
    """
    monkeypatch.delenv("AGENTIC_NO_LLM", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="GITHUB_TOKEN"):
        get_chat_model("gh:openai/gpt-4o")


@pytest.mark.unit
async def test_flag_astream_yields_single_placeholder_chunk(monkeypatch):
    """Under the flag, ``PlaceholderChatModel._astream`` must yield exactly one chunk
    containing the placeholder prefix (P1 from Sprint B #5 follow-up review).

    Without an explicit ``_astream``, LangChain falls back to running
    ``_generate`` in a thread executor, whose signature has broken across
    minor langchain-core bumps.  Defining ``_astream`` explicitly
    future-proofs no-LLM streaming.
    """
    from langchain_core.messages import HumanMessage

    monkeypatch.setenv("AGENTIC_NO_LLM", "1")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    get_settings.cache_clear()

    model = get_chat_model("gh:openai/gpt-4o")
    all_chunks = [chunk async for chunk in model.astream([HumanMessage(content="hi")])]

    # langchain-core>=1.4 / langgraph>=1.2 emit a trailing empty chunk with
    # ``chunk_position='last'`` for streaming v2 protocol compatibility.
    # Filter on content directly — the test's intent is exactly one *content*
    # chunk, which is unambiguous regardless of how the streaming protocol
    # frames empty positional markers.
    content_chunks = [c for c in all_chunks if c.content]

    assert len(content_chunks) == 1, (
        f"Expected exactly one content chunk, got {len(content_chunks)} "
        f"(out of {len(all_chunks)} total): {all_chunks!r}"
    )
    assert content_chunks[0].content.startswith(_PLACEHOLDER_PREFIX), (
        f"Stream chunk content {content_chunks[0].content!r} does not start with "
        f"{_PLACEHOLDER_PREFIX!r}"
    )


@pytest.mark.unit
def test_flag_bind_tools_returns_new_instance_not_self(monkeypatch):
    """``bind_tools`` must return a *new* ``PlaceholderChatModel`` instance, not
    ``self`` (P3 from Sprint B #5 follow-up review).

    Sharing a single instance across bind_tools calls could become a
    concurrency footgun if future maintainers add mutable state to the
    placeholder.  The contract also matches LangChain's "bind_tools
    returns a new thing" convention.
    """
    monkeypatch.setenv("AGENTIC_NO_LLM", "1")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    get_settings.cache_clear()

    model = get_chat_model("gh:openai/gpt-4o")
    bound = model.bind_tools(
        [
            {
                "type": "function",
                "function": {
                    "name": "noop",
                    "description": "x",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
    )
    assert (
        bound is not model
    ), "bind_tools should return a NEW PlaceholderChatModel instance, not self"
    # But both should be instances of the SAME cached class (P4 — class
    # identity must be stable across calls so ``isinstance`` checks work).
    assert type(bound) is type(
        model
    ), "bound and original should share the same PlaceholderChatModel class"
