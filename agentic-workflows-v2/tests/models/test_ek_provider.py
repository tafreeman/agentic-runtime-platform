"""ADR-023 Phase 5a: tests for ``agentic_v2.models.ek_provider``.

Proves the ExecutionKit ``LLMProvider`` shim over the runtime router:

* preserves router reliability (bulkhead context, circuit-breaker
  bookkeeping, cross-model fallback) by exercising the *real*
  :class:`SmartModelRouter` with a controllable fake backend;
* translates ``httpx.HTTPStatusError`` to EK error classes via
  ``ek_adapters.map_http_error`` (429 -> RateLimitError(retry_after);
  401/403/404 -> PermanentError; else -> ProviderError);
* records success / failure EXACTLY once per physical call;
* delegates ``supports_tools`` (False for Gemini routes), never hardcoded.

Runs offline with ``AGENTIC_NO_LLM=1`` — no live keys, no network. These tests
assert the behaviour of the flag-ON (provider-active) path: the provider is
constructed and driven directly, exactly as Phase 5b will drive it when
``AGENTIC_EK_PROVIDER`` is set.
"""

from __future__ import annotations

from typing import Any

import pytest

# ExecutionKit value types + error tree (ADR-023 Option A′) + Phase 5a provider
# — guard so the suite skips gracefully when ExecutionKit / httpx is absent.
try:
    import httpx

    from executionkit.errors import (
        PermanentError,
        ProviderError,
        RateLimitError,
    )
    from executionkit.provider import LLMResponse

    from agentic_v2.models.backends_base import LLMBackend
    from agentic_v2.models.ek_provider import SmartRouterProvider
    from agentic_v2.models.router import FallbackChain, ModelTier
    from agentic_v2.models.smart_router import SmartModelRouter
    from agentic_v2.settings import get_settings
except ImportError:  # pragma: no cover — guarded for isolated environments
    pytest.skip(
        "executionkit / httpx not installed (ADR-023 dependency); "
        "Phase 5a provider suite skipped in this environment.",
        allow_module_level=True,
    )


@pytest.fixture(autouse=True, scope="module")
def _force_no_llm_env() -> Any:
    """Set ``AGENTIC_NO_LLM=1`` for THIS module only (restored at teardown).

    Belt-and-suspenders so these tests never hit the network. Uses a
    module-scoped ``MonkeyPatch`` so the flag is undone at module teardown
    instead of leaking session-wide — the prior module-level
    ``os.environ.setdefault`` leaked ``AGENTIC_NO_LLM`` into every later test.
    Mirrors ``_force_no_llm_env`` in ``tests/engine/test_step_tool_path.py``.
    """
    mp = pytest.MonkeyPatch()
    mp.setenv("AGENTIC_NO_LLM", "1")
    get_settings.cache_clear()
    try:
        yield
    finally:
        mp.undo()
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeBackend(LLMBackend):
    """Backend whose ``complete_chat`` is scripted per call.

    ``script`` is a list of either canonical-dict results or Exception
    instances to raise, consumed in order. Records every call so tests can
    assert the bulkhead/fallback sequence and that ``tools`` are forwarded.
    """

    def __init__(self, script: list[Any]) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def complete(  # abstract, unused here
        self,
        model: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        raise NotImplementedError

    async def complete_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "tools": tools,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _http_status_error(status: int, retry_after: str | None = None) -> httpx.HTTPStatusError:
    """Build a real ``httpx.HTTPStatusError`` with the given status."""
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    request = httpx.Request("POST", "https://example.test/chat/completions")
    response = httpx.Response(status, request=request, headers=headers)
    return httpx.HTTPStatusError(
        f"HTTP {status}", request=request, response=response
    )


def _router_with(chain: tuple[str, ...], tier: ModelTier) -> SmartModelRouter:
    """A real router with a deterministic single-tier chain (no cross-tier)."""
    router = SmartModelRouter()
    router.register_chain(tier, FallbackChain(chain, name="test-chain"))
    return router


_TIER = ModelTier.TIER_2
_MESSAGES = [{"role": "user", "content": "hi"}]


# ---------------------------------------------------------------------------
# Happy path + adapter pass-through
# ---------------------------------------------------------------------------


async def test_complete_returns_llm_response_and_records_success_once() -> None:
    chain = ("openai:gpt-4o-mini",)
    router = _router_with(chain, _TIER)
    backend = _FakeBackend(
        [{"content": "hello", "tool_calls": None, "finish_reason": "stop"}]
    )
    provider = SmartRouterProvider(router, backend, _TIER)

    resp = await provider.complete(_MESSAGES)

    assert isinstance(resp, LLMResponse)
    assert resp.content == "hello"
    assert len(backend.calls) == 1
    # record_success fired exactly once: one recorded success, zero failures.
    stats = router.model_stats["openai:gpt-4o-mini"]
    assert stats.success_count == 1
    assert stats.failure_count == 0


async def test_tools_forwarded_to_backend() -> None:
    chain = ("openai:gpt-4o-mini",)
    router = _router_with(chain, _TIER)
    backend = _FakeBackend(
        [{"content": "", "tool_calls": None, "finish_reason": "stop"}]
    )
    provider = SmartRouterProvider(router, backend, _TIER)

    tools = [{"type": "function", "function": {"name": "t", "parameters": {}}}]
    await provider.complete(_MESSAGES, tools=tools)

    assert backend.calls[0]["tools"] == tools


# ---------------------------------------------------------------------------
# model= override (ADR-023 review): bypasses tier selection, no silent fallback
# ---------------------------------------------------------------------------


async def test_model_override_bypasses_tier_selection() -> None:
    """An explicit ``model=`` is attempted as-is, not the tier's default pick."""
    # Tier default (first in chain) is the openai model; we force the second.
    chain = ("openai:gpt-4o-mini", "anthropic:claude-3-5-haiku-20241022")
    router = _router_with(chain, _TIER)
    backend = _FakeBackend(
        [{"content": "forced", "tool_calls": None, "finish_reason": "stop"}]
    )
    provider = SmartRouterProvider(router, backend, _TIER)

    override = "anthropic:claude-3-5-haiku-20241022"
    resp = await provider.complete(_MESSAGES, model=override)

    assert resp.content == "forced"
    # The forced model served the call; the tier default was never touched.
    assert len(backend.calls) == 1
    assert backend.calls[0]["model"] == override
    assert router.model_stats[override].success_count == 1
    # The tier default was never selected, so its stats were never created
    # (model_stats entries are populated lazily on first use).
    assert "openai:gpt-4o-mini" not in router.model_stats


async def test_model_override_does_not_fall_back_on_failure() -> None:
    """A forced model that fails surfaces its error — no tier-candidate swap."""
    chain = ("openai:gpt-4o-mini", "anthropic:claude-3-5-haiku-20241022")
    router = _router_with(chain, _TIER)
    # Non-HTTP error normally falls through to the next candidate; with a
    # forced model the loop re-selects it, finds it in ``tried``, and breaks —
    # so the tier's other model is never reached.
    backend = _FakeBackend(
        [
            TimeoutError("connection timeout"),
            {"content": "unreached", "tool_calls": None, "finish_reason": "stop"},
        ]
    )
    provider = SmartRouterProvider(router, backend, _TIER)

    override = "anthropic:claude-3-5-haiku-20241022"
    with pytest.raises(ProviderError):
        await provider.complete(_MESSAGES, model=override)

    assert len(backend.calls) == 1  # exactly one physical call — the override
    assert backend.calls[0]["model"] == override
    assert router.model_stats[override].failure_count == 1


# ---------------------------------------------------------------------------
# HTTP error translation -> EK error classes (RetryConfig-recognisable)
# ---------------------------------------------------------------------------


async def test_429_translates_to_rate_limit_error_with_retry_after() -> None:
    chain = ("openai:gpt-4o-mini",)
    router = _router_with(chain, _TIER)
    backend = _FakeBackend([_http_status_error(429, retry_after="7")])
    provider = SmartRouterProvider(router, backend, _TIER)

    with pytest.raises(RateLimitError) as excinfo:
        await provider.complete(_MESSAGES)
    assert excinfo.value.retry_after == 7.0


@pytest.mark.parametrize("status", [401, 403, 404])
async def test_permanent_statuses_translate_to_permanent_error(status: int) -> None:
    chain = ("openai:gpt-4o-mini",)
    router = _router_with(chain, _TIER)
    backend = _FakeBackend([_http_status_error(status)])
    provider = SmartRouterProvider(router, backend, _TIER)

    with pytest.raises(PermanentError):
        await provider.complete(_MESSAGES)


@pytest.mark.parametrize("status", [400, 500, 502, 503])
async def test_other_statuses_translate_to_provider_error(status: int) -> None:
    chain = ("openai:gpt-4o-mini",)
    router = _router_with(chain, _TIER)
    backend = _FakeBackend([_http_status_error(status)])
    provider = SmartRouterProvider(router, backend, _TIER)

    with pytest.raises(ProviderError):
        await provider.complete(_MESSAGES)


async def test_http_error_records_failure_exactly_once_and_does_not_loop() -> None:
    # Two models in the chain, but an HTTP error must be raised immediately
    # (EK owns the retry decision) — the second model is never tried.
    chain = ("openai:gpt-4o-mini", "anthropic:claude-3-5-haiku-20241022")
    router = _router_with(chain, _TIER)
    backend = _FakeBackend(
        [
            _http_status_error(500),
            {"content": "second", "tool_calls": None},  # must NOT be reached
        ]
    )
    provider = SmartRouterProvider(router, backend, _TIER)

    with pytest.raises(ProviderError):
        await provider.complete(_MESSAGES)

    assert len(backend.calls) == 1  # no double-call / no fallback on HTTP error
    stats = router.model_stats["openai:gpt-4o-mini"]
    assert stats.failure_count == 1  # recorded exactly once


# ---------------------------------------------------------------------------
# Reliability: non-HTTP failures DO fall through to the next candidate
# ---------------------------------------------------------------------------


async def test_non_http_error_falls_through_to_next_model() -> None:
    chain = ("openai:gpt-4o-mini", "anthropic:claude-3-5-haiku-20241022")
    router = _router_with(chain, _TIER)
    backend = _FakeBackend(
        [
            TimeoutError("connection timeout"),
            {"content": "recovered", "tool_calls": None, "finish_reason": "stop"},
        ]
    )
    provider = SmartRouterProvider(router, backend, _TIER)

    resp = await provider.complete(_MESSAGES)

    assert resp.content == "recovered"
    assert len(backend.calls) == 2
    # First model recorded a failure; second recorded a success — each once.
    assert router.model_stats["openai:gpt-4o-mini"].failure_count == 1
    assert router.model_stats["anthropic:claude-3-5-haiku-20241022"].success_count == 1


async def test_no_model_available_raises_provider_error() -> None:
    # Override EVERY tier's chain with the same single model, then mark it
    # unavailable so cross-tier fallback also finds nothing. Under
    # AGENTIC_NO_LLM=1 the router returns None (rather than raising
    # NoProviderConfiguredError) when every candidate is exhausted, so the
    # provider surfaces the contract-typed EK ProviderError itself —
    # without ever touching the backend.
    router = SmartModelRouter()
    for tier in ModelTier:
        if tier == ModelTier.TIER_0:
            continue
        router.register_chain(tier, FallbackChain(("openai:gpt-4o-mini",)))
    router.mark_unavailable("openai:gpt-4o-mini")
    backend = _FakeBackend([])
    provider = SmartRouterProvider(router, backend, _TIER)

    with pytest.raises(ProviderError):
        await provider.complete(_MESSAGES)
    assert backend.calls == []


# ---------------------------------------------------------------------------
# supports_tools delegation (F-04): False for Gemini, never hardcoded True
# ---------------------------------------------------------------------------


def test_supports_tools_true_for_openai_route() -> None:
    router = _router_with(("openai:gpt-4o-mini",), _TIER)
    provider = SmartRouterProvider(router, _FakeBackend([]), _TIER)
    assert provider.supports_tools is True


def test_supports_tools_false_for_gemini_route() -> None:
    router = _router_with(("gemini:gemini-2.0-flash",), _TIER)
    provider = SmartRouterProvider(router, _FakeBackend([]), _TIER)
    assert provider.supports_tools is False


def test_supports_tools_not_hardcoded_literal_true() -> None:
    # The protocol's ToolCallingProvider uses Literal[True]; the F-04 note
    # forbids copying that verbatim. Assert it is a real delegating property
    # that can return False, not a class-level constant.
    gemini = SmartRouterProvider(
        _router_with(("gemini:gemini-2.0-flash",), _TIER), _FakeBackend([]), _TIER
    )
    openai = SmartRouterProvider(
        _router_with(("openai:gpt-4o-mini",), _TIER), _FakeBackend([]), _TIER
    )
    assert gemini.supports_tools != openai.supports_tools
