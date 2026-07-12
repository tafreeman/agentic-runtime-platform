"""ARP-5: LLMClientWrapper.complete_chat threads backend token usage onto
SmartModelRouter.record_success, so the llm_tokens_total metric stops being
dead on the real success path (not just the router unit-level plumbing
covered in tests/test_otel_metrics.py::TestSmartRouterMetrics).

Uses a stubbed backend (mirrors tests/models/test_agent_loop_sanitization.py's
_StubBackend pattern) returning an OpenAI-shaped ``usage`` dict — the same
shape every backend in agentic_v2.models.backends_cloud.py produces. Runs
under AGENTIC_NO_LLM=1 (no network, no live provider).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from agentic_v2.models.backends_base import LLMBackend
from agentic_v2.models.client import LLMClientWrapper
from agentic_v2.models.router import FallbackChain, ModelTier
from agentic_v2.models.smart_router import SmartModelRouter

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

_TIER = ModelTier.TIER_2
_MODEL = "openai:gpt-4o-mini"


class _StubChatBackend(LLMBackend):
    """Minimal backend returning a scripted chat response with real usage."""

    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response

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
        return dict(self._response)


def _router() -> SmartModelRouter:
    """Router pinned to one deterministic model on every (non-zero) tier."""
    router = SmartModelRouter()
    for tier in ModelTier:
        if tier == ModelTier.TIER_0:
            continue
        router.register_chain(tier, FallbackChain((_MODEL,), name="t"))
    return router


async def test_complete_chat_threads_usage_into_record_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mocked complete_chat call with real usage reaches record_success with non-zero
    token counts (AGENTIC_NO_LLM=1, no network)."""
    monkeypatch.setenv("AGENTIC_NO_LLM", "1")
    from agentic_v2.settings import get_settings

    get_settings.cache_clear()

    mocked_usage = {"prompt_tokens": 31, "completion_tokens": 9, "total_tokens": 40}
    backend = _StubChatBackend(
        {"content": "hello", "tool_calls": None, "usage": mocked_usage}
    )
    router = _router()
    client = LLMClientWrapper(backend=backend, router=router, enable_cache=False)

    captured: list[dict[str, Any]] = []
    original_record_success = router.record_success

    def spy_record_success(model: str, latency_ms: float, usage: Any = None) -> None:
        captured.append({"model": model, "usage": usage})
        original_record_success(model, latency_ms, usage=usage)

    with patch.object(router, "record_success", side_effect=spy_record_success):
        await client.complete_chat(
            tier=_TIER,
            messages=[{"role": "user", "content": "hi"}],
            use_cache=False,
        )

    assert len(captured) == 1
    assert captured[0]["model"] == _MODEL
    usage = captured[0]["usage"]
    assert usage is not None
    assert usage["prompt_tokens"] > 0
    assert usage["completion_tokens"] > 0
