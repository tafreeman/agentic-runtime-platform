"""ADR-023 Phase 5b: wrapper-seam tests for the flag-gated EK provider path.

Companion to ``tests/models/test_ek_provider.py`` (Phase 5a, which drives the
:class:`SmartRouterProvider` directly). This module exercises the *seam added in
Phase 5b*: ``LLMClientWrapper.complete`` re-pointed onto
``SmartRouterProvider(...).complete(messages)`` when
``settings.agentic_ek_provider`` is ON, while the legacy text path stays
byte-for-byte when the flag is OFF.

Coverage map (task P5b a-h):

* (a) tool_calls + finish_reason + real usage survive end-to-end through the
      wrapper -> :func:`test_a_tool_calls_finish_reason_usage_survive`.
* (b) repeated 429 opens the circuit breaker ->
      :func:`test_b_repeated_429_opens_circuit_breaker`.
* (c) cross-tier fallback skips the sick model ->
      :func:`test_c_cross_tier_fallback_skips_sick_model`.
* (d) bulkhead caps concurrency ->
      :func:`test_d_bulkhead_caps_concurrency`.
* (e) rate-limit header -> cooldown ->
      :func:`test_e_rate_limit_header_sets_cooldown`.
* (f) httpx 429/401/500 -> RateLimitError/PermanentError/ProviderError ->
      :func:`test_f_http_status_translates_to_ek_errors`.
* (g) supports_tools False for a Gemini route causes react_loop to refuse ->
      :func:`test_g_gemini_route_react_loop_refuses`.
* (h) flag-OFF leaves legacy behaviour unchanged ->
      :func:`test_h_flag_off_uses_legacy_text_path`.

All tests run offline under ``AGENTIC_NO_LLM=1`` with a mocked router/backend —
no live keys, no network. The flag-ON tests assert reliability behaviour with
``AGENTIC_EK_PROVIDER`` set.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

# ExecutionKit value types + patterns (ADR-023 Option A′) + Phase 5a/5b wiring.
# Skip the whole module if the executionkit/httpx stack is not present.
try:
    import httpx
    from executionkit.errors import (
        PermanentError,
        ProviderError,
        RateLimitError,
    )
    from executionkit.patterns import react_loop

    from agentic_v2.models.backends_base import LLMBackend
    from agentic_v2.models.client import LLMClientWrapper, TokenBudget
    from agentic_v2.models.ek_provider import SmartRouterProvider
    from agentic_v2.models.model_stats import CircuitState
    from agentic_v2.models.router import FallbackChain, ModelTier
    from agentic_v2.models.smart_router import SmartModelRouter
    from agentic_v2.settings import get_settings
except ImportError:  # pragma: no cover — guarded for isolated environments
    pytest.skip(
        "executionkit / httpx not installed "
        "(ADR-023 dependency); Phase 5b wrapper suite skipped.",
        allow_module_level=True,
    )


@pytest.fixture(autouse=True, scope="module")
def _force_no_llm_env() -> Any:
    """Set ``AGENTIC_NO_LLM=1`` for THIS module only (restored at teardown).

    Belt-and-suspenders so these tests never hit the network. Uses a
    module-scoped ``MonkeyPatch`` so the flag is undone at module teardown
    instead of leaking session-wide — the prior module-level
    ``os.environ.setdefault`` leaked ``AGENTIC_NO_LLM`` into every later test,
    forcing the placeholder backend and breaking order-dependent suites such as
    ``tests/test_agents.py`` (agents looped to max-iterations on placeholder
    output). Mirrors ``_force_no_llm_env`` in ``tests/engine/test_step_tool_path.py``.
    ``get_settings`` is ``lru_cache``-d, so the cache is cleared on entry and
    exit to force a re-read of the env.
    """
    mp = pytest.MonkeyPatch()
    mp.setenv("AGENTIC_NO_LLM", "1")
    get_settings.cache_clear()
    try:
        yield
    finally:
        mp.undo()
        get_settings.cache_clear()


_TIER = ModelTier.TIER_2
_PROMPT = "hi"


# ---------------------------------------------------------------------------
# Fixtures / test doubles
# ---------------------------------------------------------------------------


@pytest.fixture
def ek_flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn the EK provider hot path ON for one test (cache-aware).

    ``get_settings`` is ``lru_cache``d, so the env change is invisible until
    the cache is cleared. We clear before AND after so neither this test nor a
    later one reads a stale Settings singleton.
    """
    monkeypatch.setenv("AGENTIC_EK_PROVIDER", "1")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def ek_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the EK provider hot path OFF (legacy text path)."""
    monkeypatch.setenv("AGENTIC_EK_PROVIDER", "0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _FakeBackend(LLMBackend):
    """Backend whose ``complete_chat`` / ``complete`` are scripted per call.

    ``script`` is consumed in order; an ``Exception`` entry is raised, any
    other entry is returned. ``complete`` (legacy text path) and
    ``complete_chat`` (EK path) share the same script so a single fixture can
    serve both branches. Every chat call is recorded for assertions about
    forwarding and the bulkhead/fallback sequence.
    """

    def __init__(self, script: list[Any]) -> None:
        self._script = list(script)
        self.chat_calls: list[dict[str, Any]] = []
        self.text_calls: list[dict[str, Any]] = []

    async def complete(
        self,
        model: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        self.text_calls.append({"model": model, "prompt": prompt})
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        # Legacy path expects a plain string.
        return step if isinstance(step, str) else str(step.get("content", ""))

    async def complete_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.chat_calls.append({"model": model, "messages": messages, "tools": tools})
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class _GatedBackend(_FakeBackend):
    """Backend whose ``complete_chat`` blocks until released — for concurrency.

    Each call increments ``concurrent`` on entry, records the running peak in
    ``max_concurrent``, waits on a shared event, then returns a canned dict.
    Lets a test prove the per-provider bulkhead semaphore caps simultaneous
    in-flight calls.
    """

    def __init__(self, gate: asyncio.Event) -> None:
        super().__init__(script=[])
        self._gate = gate
        self.concurrent = 0
        self.max_concurrent = 0

    async def complete_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.concurrent += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent)
        try:
            await self._gate.wait()
        finally:
            self.concurrent -= 1
        return {"content": "ok", "tool_calls": None, "finish_reason": "stop"}


def _http_status_error(
    status: int, retry_after: str | None = None
) -> httpx.HTTPStatusError:
    """Build a real ``httpx.HTTPStatusError`` with the given status."""
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    request = httpx.Request("POST", "https://example.test/chat/completions")
    response = httpx.Response(status, request=request, headers=headers)
    return httpx.HTTPStatusError(f"HTTP {status}", request=request, response=response)


def _router_single_tier(chain: tuple[str, ...]) -> SmartModelRouter:
    """A router pinned to ``chain`` on EVERY tier.

    A fresh :class:`SmartModelRouter` ships default chains on all tiers, and
    ``get_model_for_tier`` is allowed to degrade *cross-tier* when the
    requested tier is exhausted. Pinning the same chain to every tier makes
    routing deterministic: the only models the router can ever pick are the
    ones under test, so cross-tier degradation can never reach an unscripted
    default model.
    """
    router = SmartModelRouter()
    for tier in ModelTier:
        if tier == ModelTier.TIER_0:
            continue
        router.register_chain(tier, FallbackChain(chain, name="test-chain"))
    return router


def _wrapper(router: SmartModelRouter, backend: LLMBackend) -> LLMClientWrapper:
    """An LLMClientWrapper wired to the given router + backend, cache off.

    Caching is disabled by default so each test controls the cache
    surface it cares about explicitly (the dedicated legacy/budget tests
    set it as needed).
    """
    return LLMClientWrapper(backend=backend, router=router, enable_cache=False)


_USAGE = {"prompt_tokens": 11, "completion_tokens": 7}  # total_tokens == 18


# ---------------------------------------------------------------------------
# (a) tool_calls + finish_reason + real usage survive end-to-end
# ---------------------------------------------------------------------------


async def test_a_tool_calls_finish_reason_usage_survive(ek_flag_on: None) -> None:
    tool_calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "lookup", "arguments": '{"q": "x"}'},
        }
    ]
    router = _router_single_tier(("openai:gpt-4o-mini",))
    backend = _FakeBackend(
        [
            {
                "content": "partial",
                "tool_calls": tool_calls,
                "finish_reason": "tool_calls",
                "usage": _USAGE,
                "model": "openai:gpt-4o-mini",
            }
        ]
    )
    wrapper = _wrapper(router, backend)

    content, model_used, tokens = await wrapper.complete(_PROMPT, tier=_TIER)

    # The wrapper's public tuple carries content + model + real token total.
    assert content == "partial"
    assert model_used == "openai:gpt-4o-mini"
    assert tokens == 18  # prompt 11 + completion 7, from real usage (not est)
    # The chat path was used (not the legacy text path) and the messages
    # envelope was built correctly.
    assert backend.text_calls == []
    assert backend.chat_calls[0]["messages"] == [{"role": "user", "content": _PROMPT}]
    # record_success fired exactly once.
    stats = router.model_stats["openai:gpt-4o-mini"]
    assert stats.success_count == 1
    assert stats.failure_count == 0


# ---------------------------------------------------------------------------
# (b) repeated 429 opens the circuit breaker
# ---------------------------------------------------------------------------


async def test_b_repeated_429_opens_circuit_breaker(ek_flag_on: None) -> None:
    model = "openai:gpt-4o-mini"
    router = _router_single_tier((model,))
    # Five consecutive 429s -> consecutive_failures hits the threshold (5) ->
    # circuit OPEN. Each wrapper.complete raises RateLimitError (EK owns retry).
    # A 429 ALSO arms a provider cooldown, which would make the model
    # unselectable on the next attempt; clear it between calls so all five
    # physical 429s land and we observe the breaker (not cooldown) opening.
    backend = _FakeBackend([_http_status_error(429) for _ in range(5)])
    wrapper = _wrapper(router, backend)

    for _ in range(5):
        with pytest.raises(RateLimitError):
            await wrapper.complete(_PROMPT, tier=_TIER)
        router.model_stats[model].clear_cooldown()

    stats = router.model_stats[model]
    assert stats.failure_count == 5  # recorded once per physical call
    assert stats.rate_limit_count == 5
    assert stats.circuit_state == CircuitState.OPEN


# ---------------------------------------------------------------------------
# (c) cross-tier fallback skips the sick model
# ---------------------------------------------------------------------------


async def test_c_cross_tier_fallback_skips_sick_model(ek_flag_on: None) -> None:
    sick = "openai:gpt-4o-mini"
    healthy = "anthropic:claude-3-5-haiku-20241022"
    router = SmartModelRouter()
    # Requested tier holds ONLY the sick model; every other (non-TIER_0) tier
    # holds ONLY the healthy model, so the sole cross-tier candidate is healthy.
    for tier in ModelTier:
        if tier == ModelTier.TIER_0:
            continue
        chain = (sick,) if tier == _TIER else (healthy,)
        router.register_chain(tier, FallbackChain(chain, name=f"{tier.name}-chain"))
    # Mark the sick model unavailable so get_model_for_tier degrades cross-tier.
    router.mark_unavailable(sick)

    backend = _FakeBackend(
        [{"content": "from-healthy", "tool_calls": None, "finish_reason": "stop"}]
    )
    wrapper = _wrapper(router, backend)

    content, model_used, _ = await wrapper.complete(_PROMPT, tier=_TIER)

    assert content == "from-healthy"
    assert model_used == healthy
    # The sick model was never physically called.
    assert all(call["model"] == healthy for call in backend.chat_calls)


# ---------------------------------------------------------------------------
# (d) bulkhead caps concurrency
# ---------------------------------------------------------------------------


async def test_d_bulkhead_caps_concurrency(
    ek_flag_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = "openai:gpt-4o-mini"
    router = _router_single_tier((model,))
    # Force the provider's bulkhead semaphore down to 2 so we can observe the
    # cap directly. The router's readiness gate rejects callers that arrive
    # while the semaphore is fully held (they fail over rather than queue), so
    # the load-bearing invariant is: no more than 2 calls are EVER inside
    # complete_chat simultaneously.
    sem = asyncio.Semaphore(2)
    router._provider_semaphores["openai"] = sem

    gate = asyncio.Event()
    backend = _GatedBackend(gate)
    wrapper = _wrapper(router, backend)

    async def _one() -> tuple[str, str, int]:
        return await wrapper.complete(_PROMPT, tier=_TIER)

    tasks = [asyncio.create_task(_one()) for _ in range(5)]
    # Let the scheduler fan the tasks out; the semaphore must cap in-flight
    # complete_chat calls at 2 regardless of how many tasks are runnable.
    for _ in range(20):
        await asyncio.sleep(0)
    assert backend.max_concurrent <= 2

    gate.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    # The bulkhead never let more than 2 calls run at once, for the whole run.
    assert backend.max_concurrent <= 2
    # Whatever got admitted returned cleanly; excess callers were shed by the
    # readiness gate as ProviderError (bulkhead pressure, not a crash).
    admitted = [r for r in results if not isinstance(r, BaseException)]
    assert admitted, "expected at least one admitted call to complete"
    assert all(content == "ok" for content, _, _ in admitted)
    assert all(
        isinstance(r, ProviderError) for r in results if isinstance(r, BaseException)
    )


# ---------------------------------------------------------------------------
# (e) rate-limit header -> cooldown
# ---------------------------------------------------------------------------


async def test_e_rate_limit_header_sets_cooldown(ek_flag_on: None) -> None:
    model = "openai:gpt-4o-mini"
    router = _router_single_tier((model,))
    # A 429 carrying Retry-After. The provider records the error exactly once;
    # the router parses the header and puts the model into cooldown.
    backend = _FakeBackend([_http_status_error(429, retry_after="42")])
    wrapper = _wrapper(router, backend)

    with pytest.raises(RateLimitError):
        await wrapper.complete(_PROMPT, tier=_TIER)

    stats = router.model_stats[model]
    assert stats.rate_limit_count == 1
    assert stats.is_in_cooldown  # cooldown was applied from the rate-limit hit


# ---------------------------------------------------------------------------
# (f) httpx 429/401/500 -> RateLimitError/PermanentError/ProviderError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (429, RateLimitError),
        (401, PermanentError),
        (500, ProviderError),
    ],
)
async def test_f_http_status_translates_to_ek_errors(
    ek_flag_on: None, status: int, expected: type[Exception]
) -> None:
    model = "openai:gpt-4o-mini"
    router = _router_single_tier((model,))
    backend = _FakeBackend([_http_status_error(status)])
    wrapper = _wrapper(router, backend)

    with pytest.raises(expected):
        await wrapper.complete(_PROMPT, tier=_TIER)

    # Exactly one physical call, exactly one recorded failure (no double-cost).
    assert len(backend.chat_calls) == 1
    assert router.model_stats[model].failure_count == 1


# ---------------------------------------------------------------------------
# (g) supports_tools False for a Gemini route -> react_loop refuses
# ---------------------------------------------------------------------------


async def test_g_gemini_route_react_loop_refuses() -> None:
    # The provider delegates supports_tools to the route capability: a Gemini
    # route reports False, so EK's react_loop must REFUSE (TypeError) rather
    # than silently dropping the tools. This is the F-04 invariant the EK tool
    # path relies on.
    router = _router_single_tier(("gemini:gemini-2.0-flash",))
    backend = _FakeBackend([])
    provider = SmartRouterProvider(router, backend, _TIER)

    assert provider.supports_tools is False

    with pytest.raises(TypeError):
        await react_loop(provider, prompt="do a thing", tools=[])

    # No physical provider call was made — refusal happens before any routing.
    assert backend.chat_calls == []


# ---------------------------------------------------------------------------
# (h) flag-OFF leaves legacy behaviour unchanged
# ---------------------------------------------------------------------------


async def test_h_flag_off_uses_legacy_text_path(ek_flag_off: None) -> None:
    model = "openai:gpt-4o-mini"
    router = _router_single_tier((model,))
    backend = _FakeBackend(["legacy-answer"])
    wrapper = _wrapper(router, backend)

    # use_cache=False so the legacy branch runs without touching the cache
    # surface (this wrapper has caching disabled).
    content, model_used, tokens = await wrapper.complete(
        _PROMPT, tier=_TIER, use_cache=False
    )

    # Legacy path used the text complete(); the EK chat path was NOT touched.
    assert content == "legacy-answer"
    assert model_used == model
    assert backend.text_calls != []
    assert backend.chat_calls == []
    # Legacy token accounting is the count_tokens estimate, not real usage.
    assert tokens == backend.count_tokens(_PROMPT + "legacy-answer", model)


async def test_h_budget_consume_raises_before_return_on_ek_path(
    ek_flag_on: None,
) -> None:
    # Budget precedence (ACCEPTED): runtime TokenBudget owns the token-sum
    # ceiling and must raise BEFORE returning when consume() reports False.
    model = "openai:gpt-4o-mini"
    router = _router_single_tier((model,))
    backend = _FakeBackend(
        [
            {
                "content": "answer",
                "tool_calls": None,
                "finish_reason": "stop",
                "usage": _USAGE,  # total 18
                "model": model,
            }
        ]
    )
    wrapper = _wrapper(router, backend)
    wrapper.budget = TokenBudget(max_tokens=5)  # 18 > 5 -> consume() is False

    with pytest.raises(ValueError, match="Budget exceeded"):
        await wrapper.complete(_PROMPT, tier=_TIER)
