"""ADR-023 Phase 1 — EK bridge default-on + streaming + cache reset tests.

Covers the Phase 1 bridge behaviour at the new default:

* bridge active by default (no env override) -> EK chat path is used;
* ``AGENTIC_EK_PROVIDER=0`` forces the legacy text path;
* settings-cache reset between tests (two-test ordering proof);
* provider built from settings (the EK chat seam, not the legacy text seam);
* ``SmartModelRouter.select`` resolves the tier model before ``complete``;
* streaming yields two ``token_delta``-shaped chunks from a mocked stream;
* initialization/usability is fast (no multi-second hang);
* executionkit-not-importable falls back gracefully;
* ``reset_provider_cache()`` forces a fresh provider build.

All tests run offline under ``AGENTIC_NO_LLM=1`` with a mocked router/backend —
no live keys, no network.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

try:
    from agentic_v2.contracts.events import TokenDeltaEvent
    from agentic_v2.models import ek_provider
    from agentic_v2.models.backends_base import LLMBackend
    from agentic_v2.models.client import LLMClientWrapper
    from agentic_v2.models.ek_provider import (
        SmartRouterProvider,
        get_provider,
        reset_provider_cache,
    )
    from agentic_v2.models.router import FallbackChain, ModelTier
    from agentic_v2.models.smart_router import SmartModelRouter
    from agentic_v2.settings import get_settings
except ImportError:  # pragma: no cover — guarded for isolated environments
    pytest.skip(
        "executionkit / httpx not installed (ADR-023 dependency); "
        "Phase 1 bridge suite skipped.",
        allow_module_level=True,
    )


_TIER = ModelTier.TIER_2
_PROMPT = "hi"
_MODEL = "openai:gpt-4o-mini"


@pytest.fixture(autouse=True, scope="module")
def _force_no_llm_env() -> Any:
    """Set ``AGENTIC_NO_LLM=1`` for this module only (restored at teardown)."""
    mp = pytest.MonkeyPatch()
    mp.setenv("AGENTIC_NO_LLM", "1")
    get_settings.cache_clear()
    try:
        yield
    finally:
        mp.undo()
        get_settings.cache_clear()


class _FakeBackend(LLMBackend):
    """Backend whose ``complete`` / ``complete_chat`` / stream are scripted."""

    def __init__(self, chunks: list[str] | None = None) -> None:
        self.chat_calls: list[dict[str, Any]] = []
        self.text_calls: list[dict[str, Any]] = []
        self.stream_calls: list[dict[str, Any]] = []
        self._chunks = chunks or []

    async def complete(
        self,
        model: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        self.text_calls.append({"model": model, "prompt": prompt})
        return "legacy-answer"

    async def complete_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.chat_calls.append({"model": model, "messages": messages})
        return {
            "content": "ek-answer",
            "tool_calls": None,
            "finish_reason": "stop",
            "model": model,
        }

    async def complete_stream(self, model: str, prompt: str, **kwargs: Any) -> Any:
        self.stream_calls.append({"model": model, "prompt": prompt})
        for chunk in self._chunks:
            yield chunk


def _router(chain: tuple[str, ...] = (_MODEL,)) -> SmartModelRouter:
    router = SmartModelRouter()
    for tier in ModelTier:
        if tier == ModelTier.TIER_0:
            continue
        router.register_chain(tier, FallbackChain(chain, name="test-chain"))
    return router


def _wrapper(backend: LLMBackend, router: SmartModelRouter) -> LLMClientWrapper:
    return LLMClientWrapper(backend=backend, router=router, enable_cache=False)


# ---------------------------------------------------------------------------
# Default-on / legacy override
# ---------------------------------------------------------------------------


async def test_bridge_active_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """No env override -> EK chat path is used (default-on)."""
    monkeypatch.delenv("AGENTIC_EK_PROVIDER", raising=False)
    get_settings.cache_clear()
    backend = _FakeBackend()
    wrapper = _wrapper(backend, _router())

    content, model_used, _ = await wrapper.complete(_PROMPT, tier=_TIER)

    assert content == "ek-answer"  # EK chat seam, not legacy text seam
    assert backend.chat_calls and backend.text_calls == []
    assert model_used == _MODEL


async def test_env_zero_uses_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    """AGENTIC_EK_PROVIDER=0 forces the legacy text path."""
    monkeypatch.setenv("AGENTIC_EK_PROVIDER", "0")
    get_settings.cache_clear()
    backend = _FakeBackend()
    wrapper = _wrapper(backend, _router())

    content, _, _ = await wrapper.complete(_PROMPT, tier=_TIER, use_cache=False)

    assert content == "legacy-answer"
    assert backend.text_calls and backend.chat_calls == []


# ---------------------------------------------------------------------------
# Settings-cache reset proof (two-test ordering): the conftest cache reset
# means the env set in test_env_zero_uses_legacy never leaks into this test.
# ---------------------------------------------------------------------------


async def test_settings_cache_isolated_from_prior_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default re-reads as True even after a prior test forced it off."""
    monkeypatch.delenv("AGENTIC_EK_PROVIDER", raising=False)
    get_settings.cache_clear()
    assert get_settings().agentic_ek_provider is True


# ---------------------------------------------------------------------------
# Provider built from settings; router select() called before complete()
# ---------------------------------------------------------------------------


async def test_router_select_called_before_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tier model is resolved via the router before the backend call."""
    monkeypatch.delenv("AGENTIC_EK_PROVIDER", raising=False)
    get_settings.cache_clear()
    router = _router()
    backend = _FakeBackend()

    order: list[str] = []
    real_select = router.get_model_for_tier

    def _tracking_select(tier: ModelTier) -> str | None:
        order.append("select")
        return real_select(tier)

    monkeypatch.setattr(router, "get_model_for_tier", _tracking_select)

    real_chat = backend.complete_chat

    async def _tracking_chat(*args: Any, **kwargs: Any) -> dict[str, Any]:
        order.append("complete")
        return await real_chat(*args, **kwargs)

    monkeypatch.setattr(backend, "complete_chat", _tracking_chat)

    wrapper = _wrapper(backend, router)
    await wrapper.complete(_PROMPT, tier=_TIER)

    assert order[0] == "select"
    assert "complete" in order
    assert order.index("select") < order.index("complete")


# ---------------------------------------------------------------------------
# Streaming -> token deltas
# ---------------------------------------------------------------------------


async def test_stream_yields_two_token_deltas() -> None:
    """SmartRouterProvider.stream yields each chunk from the mocked stream."""
    router = _router()
    backend = _FakeBackend(chunks=["Hello", " world"])
    provider = SmartRouterProvider(router, backend, _TIER)

    deltas: list[str] = []
    async for chunk in provider.stream([{"role": "user", "content": _PROMPT}]):
        deltas.append(chunk)

    assert deltas == ["Hello", " world"]
    # Each delta marshals to a valid TokenDeltaEvent.
    events = [
        TokenDeltaEvent(run_id="r1", step="s1", delta=d, timestamp="t") for d in deltas
    ]
    assert [e.delta for e in events] == ["Hello", " world"]
    assert all(e.type == "token_delta" for e in events)
    # Success recorded exactly once after the stream is exhausted.
    assert router.model_stats[_MODEL].success_count == 1


async def test_client_complete_stream_via_ek(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wrapper's complete_stream routes through the EK provider when on."""
    monkeypatch.delenv("AGENTIC_EK_PROVIDER", raising=False)
    get_settings.cache_clear()
    backend = _FakeBackend(chunks=["Hello", " world"])
    wrapper = _wrapper(backend, _router())

    chunks = [chunk async for chunk in wrapper.complete_stream(_PROMPT, tier=_TIER)]

    assert chunks == ["Hello", " world"]
    assert backend.stream_calls  # the EK stream path hit the backend stream


# ---------------------------------------------------------------------------
# Fast initialization (no multi-second hang)
# ---------------------------------------------------------------------------


async def test_complete_is_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    """A default-on complete() returns well under a few seconds."""
    monkeypatch.delenv("AGENTIC_EK_PROVIDER", raising=False)
    get_settings.cache_clear()
    wrapper = _wrapper(_FakeBackend(), _router())

    start = time.monotonic()
    await wrapper.complete(_PROMPT, tier=_TIER)
    assert (time.monotonic() - start) < 3.0


# ---------------------------------------------------------------------------
# Graceful fallback when executionkit is not importable
# ---------------------------------------------------------------------------


async def test_import_error_falls_back_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When get_provider import fails, complete() falls back to the legacy path."""
    monkeypatch.delenv("AGENTIC_EK_PROVIDER", raising=False)
    get_settings.cache_clear()
    backend = _FakeBackend()
    wrapper = _wrapper(backend, _router())

    import builtins

    real_import = builtins.__import__

    def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.endswith("ek_provider") or name == "ek_provider":
            raise ImportError("simulated missing executionkit")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    content, _, _ = await wrapper.complete(_PROMPT, tier=_TIER, use_cache=False)

    assert content == "legacy-answer"
    assert backend.text_calls and backend.chat_calls == []


# ---------------------------------------------------------------------------
# Provider cache + reset
# ---------------------------------------------------------------------------


def test_get_provider_caches_per_identity() -> None:
    """get_provider returns the same instance for the same router/backend/tier."""
    reset_provider_cache()
    router = _router()
    backend = _FakeBackend()

    first = get_provider(router, backend, _TIER)
    second = get_provider(router, backend, _TIER)
    assert first is second

    # A different tier or backend yields a distinct provider.
    assert get_provider(router, backend, ModelTier.TIER_1) is not first
    assert get_provider(router, _FakeBackend(), _TIER) is not first


def test_reset_provider_cache_forces_fresh_build() -> None:
    """After reset_provider_cache(), get_provider builds a new instance."""
    reset_provider_cache()
    router = _router()
    backend = _FakeBackend()

    first = get_provider(router, backend, _TIER)
    reset_provider_cache()
    second = get_provider(router, backend, _TIER)
    assert first is not second
    assert ek_provider._provider_cache is not None


async def test_concurrent_complete_is_safe() -> None:
    """Concurrent default-on completes share a cached provider without error."""
    reset_provider_cache()
    backend = _FakeBackend()
    wrapper = _wrapper(backend, _router())

    results = await asyncio.gather(
        *(wrapper.complete(_PROMPT, tier=_TIER) for _ in range(5))
    )
    assert all(content == "ek-answer" for content, _, _ in results)
