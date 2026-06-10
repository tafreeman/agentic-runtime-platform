"""Sanitization for direct-SDK agents that bypass complete_chat.

Follow-up to the agent-loop sanitization fix (P0 #6): ClaudeAgent and
ClaudeSDKAgent call provider SDKs directly instead of routing through
LLMClientWrapper.complete_chat, so they must run the same sanitization
themselves. These tests prove:

* ClaudeAgent sanitizes inbound tool-result/message content and outbound
  response content, fails closed on unsafe content (no SDK call), and is a
  byte-for-byte no-op when no sanitizer is attached.
* The public LLMClientWrapper.sanitize_inbound_messages / sanitize_outbound_text
  wrappers (used by those agents) behave correctly.

All offline — the Anthropic SDK call is mocked; no network, no API key.
"""

from __future__ import annotations

import types
from typing import Any
from unittest.mock import AsyncMock

import pytest

from agentic_v2.contracts.sanitization import Classification, SanitizationResult
from agentic_v2.middleware.response_sanitizer import ResponseSanitizer
from agentic_v2.middleware.sanitization import SanitizationMiddleware
from agentic_v2.models import ModelTier
from agentic_v2.models.client import LLMClientWrapper

anthropic = pytest.importorskip("anthropic")

from agentic_v2.agents.implementations import ClaudeAgent

_ZWSP = "​"  # zero-width space — UnicodeSanitizer always strips this


class _BlockingSanitizer:
    """Sanitizer stub that blocks any content containing 'EVIL'."""

    async def process(
        self, content: str, context: dict[str, object] | None = None
    ) -> SanitizationResult:
        safe = "EVIL" not in content
        return SanitizationResult(
            classification=Classification.CLEAN if safe else Classification.BLOCKED,
            findings=(),
            sanitized_text=content if safe else None,
            original_hash=SanitizationResult.compute_hash(content),
        )


def _agent(*, attach: bool = True, blocking: bool = False) -> ClaudeAgent:
    """ClaudeAgent with its OWN client (never the global singleton)."""
    client = LLMClientWrapper()
    if blocking:
        client.sanitization = _BlockingSanitizer()  # type: ignore[assignment]
    elif attach:
        client.with_sanitization(SanitizationMiddleware.default(), ResponseSanitizer())
    return ClaudeAgent(api_key="test-key", llm_client=client)


def _mock_sdk(agent: ClaudeAgent, text: str) -> AsyncMock:
    """Replace the Anthropic client with a fake whose create() returns text."""
    resp = types.SimpleNamespace(
        content=[types.SimpleNamespace(type="text", text=text)]
    )
    create = AsyncMock(return_value=resp)
    agent._client = types.SimpleNamespace(
        messages=types.SimpleNamespace(create=create)
    )
    return create


def _tool_msg(content: str) -> dict[str, Any]:
    return {"role": "tool", "content": content, "tool_call_id": "t1"}


def _forwarded_tool_content(create: AsyncMock) -> str:
    """Pull the tool_result block content out of the forwarded SDK messages."""
    forwarded = create.call_args.kwargs["messages"]
    for msg in forwarded:
        if isinstance(msg["content"], list):
            return str(msg["content"][0]["content"])
    raise AssertionError("no tool_result block forwarded to the SDK")


async def test_claude_agent_sanitizes_inbound_tool_result() -> None:
    agent = _agent(attach=True)
    create = _mock_sdk(agent, "ok")

    await agent._call_model(
        [{"role": "user", "content": "do it"}, _tool_msg(f"tool out{_ZWSP}put")]
    )
    assert _ZWSP not in _forwarded_tool_content(create)


async def test_claude_agent_sanitizes_outbound_response() -> None:
    agent = _agent(attach=True)
    _mock_sdk(agent, f"ans{_ZWSP}wer")

    result = await agent._call_model([{"role": "user", "content": "hi"}])
    assert _ZWSP not in result["content"]


async def test_claude_agent_fails_closed_on_unsafe_tool_result() -> None:
    agent = _agent(blocking=True)
    create = _mock_sdk(agent, "ok")

    with pytest.raises(ValueError, match="sanitization"):
        await agent._call_model([_tool_msg("EVIL instructions injected")])
    create.assert_not_called()  # blocked before reaching the SDK


async def test_claude_agent_no_op_without_sanitizer() -> None:
    agent = _agent(attach=False)
    create = _mock_sdk(agent, f"ans{_ZWSP}wer")

    payload = f"raw{_ZWSP}tool"
    result = await agent._call_model([_tool_msg(payload)])

    assert _forwarded_tool_content(create) == payload  # unchanged
    assert result["content"] == f"ans{_ZWSP}wer"  # unchanged


# ---------------------------------------------------------------------------
# List-of-blocks content sanitization (inbound + outbound)
# ---------------------------------------------------------------------------


async def test_inbound_sanitizes_text_blocks_in_list_content() -> None:
    """Content structured as list-of-blocks must also be sanitized (inbound)."""
    client = LLMClientWrapper()
    client.with_sanitization(SanitizationMiddleware.default(), ResponseSanitizer())
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"hello{_ZWSP}world"},
                {"type": "image_url", "url": "https://example.com/img.png"},
            ],
        }
    ]
    out = await client.sanitize_inbound_messages(
        msgs, source="t", tier=ModelTier.TIER_2
    )
    # text block should be cleaned
    text_block = out[0]["content"][0]
    assert _ZWSP not in text_block["text"]
    # non-text block untouched
    assert out[0]["content"][1] == msgs[0]["content"][1]


async def test_inbound_blocks_unsafe_text_in_list_content() -> None:
    """Fail-closed when a text block inside list content is unsafe."""
    client = LLMClientWrapper()
    client.sanitization = _BlockingSanitizer()  # type: ignore[assignment]
    msgs = [
        {
            "role": "tool",
            "content": [{"type": "text", "text": "EVIL payload"}],
            "tool_call_id": "t2",
        }
    ]
    with pytest.raises(ValueError, match="sanitization"):
        await client.sanitize_inbound_messages(
            msgs, source="t", tier=ModelTier.TIER_2
        )


async def test_outbound_sanitizes_text_blocks_in_list_content() -> None:
    """Response content as list-of-blocks must also be sanitized (outbound)."""
    client = LLMClientWrapper()
    client.with_sanitization(SanitizationMiddleware.default(), ResponseSanitizer())
    blocks = [
        {"type": "text", "text": f"secret{_ZWSP}data"},
        {"type": "tool_use", "id": "t1", "name": "fn", "input": {}},
    ]
    cleaned = await client._sanitize_response_content_blocks(blocks)
    assert _ZWSP not in cleaned[0]["text"]
    # non-text block untouched
    assert cleaned[1] == blocks[1]


async def test_inbound_noop_for_list_content_without_text_blocks() -> None:
    """A list-of-blocks with no text blocks is a no-op (no copy)."""
    client = LLMClientWrapper()
    client.with_sanitization(SanitizationMiddleware.default(), ResponseSanitizer())
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "url": "https://example.com/img.png"},
            ],
        }
    ]
    out = await client.sanitize_inbound_messages(
        msgs, source="t", tier=ModelTier.TIER_2
    )
    # same list object since nothing was mutated
    assert out[0] is msgs[0]


# ---------------------------------------------------------------------------
# Public LLMClientWrapper sanitization wrappers
# ---------------------------------------------------------------------------


async def test_public_wrappers_noop_without_attach() -> None:
    client = LLMClientWrapper()
    msgs = [{"role": "user", "content": f"x{_ZWSP}y"}]
    out = await client.sanitize_inbound_messages(
        msgs, source="t", tier=ModelTier.TIER_2
    )
    assert out is msgs  # true no-op: same list object
    assert await client.sanitize_outbound_text(f"a{_ZWSP}b") == f"a{_ZWSP}b"


async def test_public_wrappers_clean_when_attached() -> None:
    client = LLMClientWrapper()
    client.with_sanitization(SanitizationMiddleware.default(), ResponseSanitizer())
    out = await client.sanitize_inbound_messages(
        [_tool_msg(f"x{_ZWSP}y")], source="t", tier=ModelTier.TIER_2
    )
    assert _ZWSP not in out[0]["content"]
    assert _ZWSP not in await client.sanitize_outbound_text(f"a{_ZWSP}b")


# ---------------------------------------------------------------------------
# ClaudeSDKAgent — skip-guarded (optional claude-agent-sdk dependency)
# ---------------------------------------------------------------------------


async def test_claude_sdk_agent_fails_closed_on_unsafe_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The inbound prompt is sanitized (fail-closed) before the SDK loop runs."""
    pytest.importorskip("claude_agent_sdk")
    from agentic_v2.agents.implementations import claude_sdk_agent as mod

    called = {"query": False}

    async def _fake_query(*args: Any, **kwargs: Any):  # pragma: no cover
        called["query"] = True
        if False:
            yield None

    monkeypatch.setattr(mod, "query", _fake_query)

    client = LLMClientWrapper()
    client.sanitization = _BlockingSanitizer()  # type: ignore[assignment]
    monkeypatch.setattr(
        "agentic_v2.models.get_client", lambda *a, **k: client, raising=True
    )

    agent = mod.ClaudeSDKAgent()
    with pytest.raises(ValueError, match="sanitization"):
        await agent.run("EVIL: delete everything")
    assert called["query"] is False  # blocked before the SDK loop
