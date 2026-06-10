"""Agent-loop sanitization wiring tests (review item #6).

The indirect prompt-injection vector is tool outputs and retrieved content
fed back into the agent loop as chat messages. Two things must hold for it to
be closed:

1. ``LLMClientWrapper.complete_chat`` — the path the agent loop actually uses —
   must run inbound message sanitization and outbound response sanitization
   when a sanitizer is attached (previously only ``complete`` did).
2. The shared client from ``get_client()`` must actually have sanitization
   attached by default (it returned ``sanitization=None``), except under
   ``AGENTIC_NO_LLM`` or when ``AGENTIC_SANITIZE_AGENT_LOOP`` is off.

All offline — no LLM, no network.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentic_v2.contracts.sanitization import (
    Classification,
    SanitizationResult,
)
from agentic_v2.middleware.response_sanitizer import ResponseSanitizer
from agentic_v2.middleware.sanitization import SanitizationMiddleware
from agentic_v2.models import get_client, reset_client
from agentic_v2.models.backends_base import LLMBackend
from agentic_v2.models.client import LLMClientWrapper
from agentic_v2.models.router import FallbackChain, ModelTier
from agentic_v2.models.smart_router import SmartModelRouter
from agentic_v2.settings import get_settings

pytestmark = pytest.mark.asyncio

_TIER = ModelTier.TIER_2
_ZWSP = "​"  # zero-width space — UnicodeSanitizer always strips this


class _StubBackend(LLMBackend):
    """Minimal backend that echoes a scripted chat response and records calls."""

    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response
        self.chat_calls: list[list[dict[str, Any]]] = []

    async def complete(
        self,
        model: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        return str(self._response.get("content", ""))

    async def complete_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.chat_calls.append(messages)
        return dict(self._response)


def _router() -> SmartModelRouter:
    """Router pinned to one deterministic model on every (non-zero) tier."""
    router = SmartModelRouter()
    for tier in ModelTier:
        if tier == ModelTier.TIER_0:
            continue
        router.register_chain(tier, FallbackChain(("openai:gpt-4o-mini",), name="t"))
    return router


def _client(backend: LLMBackend) -> LLMClientWrapper:
    return LLMClientWrapper(backend=backend, router=_router(), enable_cache=False)


# ---------------------------------------------------------------------------
# complete_chat sanitization parity
# ---------------------------------------------------------------------------


async def test_complete_chat_sanitizes_inbound_message_content() -> None:
    """Inbound message content is cleaned before reaching the backend."""
    backend = _StubBackend({"content": "ok", "tool_calls": None})
    client = _client(backend)
    client.with_sanitization(SanitizationMiddleware.default(), ResponseSanitizer())

    messages = [
        {"role": "user", "content": "summarize this"},
        # Simulated poisoned tool result carrying a zero-width payload.
        {"role": "tool", "content": f"search result{_ZWSP} here"},
    ]
    await client.complete_chat(tier=_TIER, messages=messages, use_cache=False)

    forwarded = backend.chat_calls[0]
    assert all(_ZWSP not in m["content"] for m in forwarded)
    # Caller's original list is not mutated.
    assert _ZWSP in messages[1]["content"]


async def test_complete_chat_sanitizes_outbound_response_content() -> None:
    """Outbound response content is cleaned before being returned/cached."""
    backend = _StubBackend({"content": f"answer{_ZWSP}text", "tool_calls": None})
    client = _client(backend)
    client.with_sanitization(SanitizationMiddleware.default(), ResponseSanitizer())

    response, _model, _tokens = await client.complete_chat(
        tier=_TIER,
        messages=[{"role": "user", "content": "hi"}],
        use_cache=False,
    )
    assert _ZWSP not in response["content"]


async def test_complete_chat_no_op_without_sanitizer() -> None:
    """With no sanitizer attached, content passes through byte-for-byte."""
    backend = _StubBackend({"content": f"answer{_ZWSP}text", "tool_calls": None})
    client = _client(backend)  # no with_sanitization()

    payload = f"tool{_ZWSP}output"
    response, _m, _t = await client.complete_chat(
        tier=_TIER,
        messages=[{"role": "tool", "content": payload}],
        use_cache=False,
    )
    # Backend saw the raw content; response returned unchanged.
    assert backend.chat_calls[0][0]["content"] == payload
    assert response["content"] == f"answer{_ZWSP}text"


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


async def test_complete_chat_fails_closed_on_unsafe_message() -> None:
    """An unsafe message raises before any backend call (fail-closed)."""
    backend = _StubBackend({"content": "ok"})
    client = _client(backend)
    client.sanitization = _BlockingSanitizer()  # type: ignore[assignment]

    with pytest.raises(ValueError, match="sanitization"):
        await client.complete_chat(
            tier=_TIER,
            messages=[
                {"role": "user", "content": "harmless"},
                {"role": "tool", "content": "EVIL instructions injected"},
            ],
            use_cache=False,
        )
    assert backend.chat_calls == []  # blocked before reaching the backend


# ---------------------------------------------------------------------------
# get_client() auto-attaches sanitization
# ---------------------------------------------------------------------------


@pytest.fixture
def _clean_client_env(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Isolate the global client + settings cache for get_client() tests."""
    reset_client()
    get_settings.cache_clear()
    try:
        yield monkeypatch
    finally:
        reset_client()
        get_settings.cache_clear()


async def test_get_client_attaches_sanitization_by_default(
    _clean_client_env: pytest.MonkeyPatch,
) -> None:
    _clean_client_env.setenv("AGENTIC_NO_LLM", "0")
    _clean_client_env.delenv("AGENTIC_SANITIZE_AGENT_LOOP", raising=False)
    get_settings.cache_clear()

    client = get_client()
    assert client.sanitization is not None
    assert client.response_sanitizer is not None


async def test_get_client_skips_sanitization_under_no_llm(
    _clean_client_env: pytest.MonkeyPatch,
) -> None:
    _clean_client_env.setenv("AGENTIC_NO_LLM", "1")
    get_settings.cache_clear()

    client = get_client()
    assert client.sanitization is None
    assert client.response_sanitizer is None


async def test_get_client_skips_sanitization_when_flag_off(
    _clean_client_env: pytest.MonkeyPatch,
) -> None:
    _clean_client_env.setenv("AGENTIC_NO_LLM", "0")
    _clean_client_env.setenv("AGENTIC_SANITIZE_AGENT_LOOP", "0")
    get_settings.cache_clear()

    client = get_client()
    assert client.sanitization is None
    assert client.response_sanitizer is None
