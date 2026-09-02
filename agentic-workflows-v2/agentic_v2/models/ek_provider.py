"""ADR-023 Phase 5a: ExecutionKit ``LLMProvider`` over the runtime router.

This module wraps the runtime :class:`~agentic_v2.models.smart_router.SmartModelRouter`
plus an :class:`~agentic_v2.models.backends_base.LLMBackend` in a class that
satisfies ExecutionKit's structural ``LLMProvider`` / ``ToolCallingProvider``
protocols (see ``executionkit.provider``). It exists so that EK patterns
(``react_loop``, etc.) can drive the runtime's production-hardened router
*without* EK ever learning about tiers, circuit breakers, or bulkheads.

Hard constraints (ADR-023 functionality-preservation + accepted decisions):

* **Flag-gated hot path.** This class is *constructed* here but is only wired
  into ``LLMClientWrapper`` in Phase 5b, behind the ``AGENTIC_EK_PROVIDER``
  env flag (settings: ``agentic_ek_provider``), DEFAULT OFF in P5/P6. When the
  flag is off the legacy path runs byte-for-byte; nothing in this file changes
  that. This file adds a new code path only.
* **Reliability preserved.** Every physical provider call goes through
  ``router.execute_with_bulkhead(model)`` (NOT ``router._execute_call``, which
  is text-only and would collapse the rich ``complete_chat`` dict). The
  per-provider bulkhead semaphore, HALF_OPEN probe lock, circuit breaker,
  rate-limit header cooldown, cross-tier fallback, and Redis-CAS shared state
  all keep working because we reuse the *exact* router methods the legacy
  path uses (``get_model_for_tier``, ``record_success``,
  ``_classify_and_record_error``).
* **Error translation, fired exactly once.** On each physical HTTP failure we
  call ``router._classify_and_record_error(model, exc)`` exactly once (no
  double-cost / double-retry), then translate ``httpx.HTTPStatusError`` to an
  EK error class via :func:`ek_adapters.map_http_error` so EK's
  ``RetryConfig.should_retry`` recognises it (429 -> RateLimitError;
  401/403/404 -> PermanentError; else -> ProviderError). ``record_success``
  fires exactly once on the successful call.
* **No mapping reimplementation.** The canonical ``complete_chat`` dict is
  passed straight through :func:`ek_adapters.dict_to_llm_response`; HTTP-status
  classification reuses :func:`ek_adapters.map_http_error`.
* **supports_tools delegation (F-04).** ``supports_tools`` is a *property* that
  reflects the inner route/backend capability (False for Gemini routes), never
  a hardcoded ``Literal[True]``. ``react_loop`` must therefore REFUSE to run
  tool-calling against a Gemini route rather than silently dropping tools.

Budget precedence (ACCEPTED) and the EK ``react_loop`` vs ``native`` tool-path
selection are layered in Phase 5b at the ``LLMClientWrapper`` seam, NOT here:
this provider is a thin, reliability-preserving ``complete`` shim.
"""

from __future__ import annotations

import time
import weakref
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from typing import Any

from executionkit.errors import ProviderError
from executionkit.provider import LLMResponse

from . import ek_adapters
from .backends_base import LLMBackend
from .rate_limit_tracker import _extract_provider
from .router import ModelTier
from .smart_router import SmartModelRouter

# Optional httpx import — only used for the ``HTTPStatusError`` translation
# branch. The router's ``_classify_and_record_error`` already handles
# circuit-breaker bookkeeping for *any* exception type, so an environment
# without httpx (e.g. AGENTIC_NO_LLM=1 unit tests using a mock backend) still
# works; the translation branch is simply never taken.
try:
    import httpx as _httpx

    _HTTPX_AVAILABLE = True
except ImportError:  # pragma: no cover — optional dependency
    _httpx = None  # type: ignore[assignment]
    _HTTPX_AVAILABLE = False

__all__ = [
    "SmartRouterProvider",
    "get_provider",
    "reset_provider_cache",
]

# Maximum physical attempts inside a single EK ``complete()`` call. Mirrors the
# fallback breadth of the legacy ``LLMClientWrapper.complete`` / router
# ``call_with_fallback`` loops so cross-tier failover + circuit-breaking happen
# *inside* one EK call rather than bubbling a single failure straight out.
_MAX_FALLBACK_TRIES = 6

# Providers whose runtime backends do NOT honour the OpenAI tool-calling wire
# format. ``GeminiBackend.complete_chat`` accepts ``tools`` but silently drops
# them and never emits ``tool_calls``; reporting ``supports_tools=False`` lets
# EK's ``react_loop`` REFUSE rather than silently no-op.
_NO_TOOL_PROVIDERS = frozenset({"gemini"})


class SmartRouterProvider:
    """EK ``LLMProvider`` / ``ToolCallingProvider`` backed by the runtime router.

    Satisfies the structural protocols in ``executionkit.provider`` via a
    matching async ``complete`` signature plus a delegating ``supports_tools``
    property. Not frozen — but holds no per-call mutable state; the router and
    backend own all state.

    Args:
        router: Production-hardened :class:`SmartModelRouter` (circuit breaker,
            bulkhead, rate-limit cooldown, cross-tier fallback, Redis CAS).
        backend: Concrete :class:`LLMBackend` (typically a ``MultiBackend``).
        tier: The :class:`ModelTier` this provider routes to.
    """

    def __init__(
        self,
        router: SmartModelRouter,
        backend: LLMBackend,
        tier: ModelTier,
    ) -> None:
        self.router = router
        self.backend = backend
        self.tier = tier

    # ------------------------------------------------------------------
    # Capability delegation (F-04): never hardcode Literal[True].
    # ------------------------------------------------------------------
    @property
    def supports_tools(self) -> bool:
        """Whether the current route/backend honours OpenAI tool calls.

        Reflects the inner route capability: ``False`` for Gemini routes
        (``GeminiBackend`` drops ``tools``), ``True`` otherwise. Resolved
        against the model the router would currently select for this tier;
        falls back to ``True`` when no model can be selected (capability is
        unknown, not denied — the actual ``complete`` call will surface a
        real ``ProviderError`` if no model is available).
        """
        model = self._peek_model()
        if model is None:
            return True
        return _extract_provider(model) not in _NO_TOOL_PROVIDERS

    def _peek_model(self) -> str | None:
        """Best-effort current model for this tier without raising.

        ``get_model_for_tier`` raises ``NoProviderConfiguredError`` when every
        tier is exhausted (outside AGENTIC_NO_LLM); for a pure capability peek
        we swallow that and report "unknown" by returning ``None``.
        """
        try:
            return self.router.get_model_for_tier(self.tier)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # LLMProvider protocol
    # ------------------------------------------------------------------
    async def complete(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Route a chat completion through the hardened router, return EK type.

        When ``model`` is provided it bypasses tier-based router selection and
        the request is attempted against that exact model only — the fallback
        loop does not re-select other tier candidates, so a forced model that
        fails surfaces its error rather than silently routing elsewhere
        (preserving the legacy ``complete(model=...)`` override contract).

        Runs a bounded fallback loop (``_MAX_FALLBACK_TRIES``) mirroring the
        legacy ``call_with_fallback`` sequence so failover + circuit-breaking
        happen *inside* one EK ``complete()``:

        1. ``model = router.get_model_for_tier(tier)`` — raises EK
           :class:`ProviderError` when no model is available.
        2. Skip already-tried / not-ready models (bulkhead/probe locked).
        3. Call ``backend.complete_chat`` INSIDE
           ``router.execute_with_bulkhead(model)`` (rich-dict path, not
           ``_execute_call``). Time it.
        4. On success: ``router.record_success(model, latency_ms)`` (once),
           map the canonical dict via ``ek_adapters.dict_to_llm_response``,
           return.
        5. On exception: ``router._classify_and_record_error(model, exc)``
           (once), translate ``httpx.HTTPStatusError`` to an EK error class via
           ``ek_adapters.map_http_error`` and raise it so EK's RetryConfig can
           classify; loop to the next candidate otherwise.
        """
        chat_messages = list(messages)
        tool_list = list(tools) if tools else None

        if model is not None:
            # An explicit model bypasses router.get_model_for_tier entirely --
            # and with it, that method's cost-lane ceiling check -- so it must
            # be validated here instead (ARP-IMPROVEMENTS F1).
            from .model_registry import enforce_cost_lane_ceiling

            enforce_cost_lane_ceiling(model)

        tried: list[str] = []
        last_error: Exception | None = None

        for _ in range(_MAX_FALLBACK_TRIES):
            # An explicit ``model`` override bypasses tier selection and is
            # attempted as-is; without one we ask the router for the tier's
            # current best candidate.
            current_model = model or self.router.get_model_for_tier(self.tier)
            if current_model is None:
                # No model for this tier (AGENTIC_NO_LLM single-tier miss, or
                # cross-tier disabled). Surface as an EK ProviderError so EK
                # callers see a contract-typed failure.
                break
            if current_model in tried:
                # Router re-selected an already-attempted model (or the forced
                # override was already tried): every healthy candidate is
                # exhausted for this loop.
                break
            tried.append(current_model)

            # Load-shedding bulkhead gate (INTENTIONAL — mirrors the legacy
            # ``call_with_fallback`` byte-for-byte). When the per-provider
            # semaphore is fully held (or a HALF_OPEN probe is in flight), this
            # SHEDS the caller rather than queuing it: the loop re-selects the
            # same model, finds it in ``tried``, and raises ``ProviderError`` —
            # fast-fail under saturation, not a blocking wait. This is the
            # documented contract asserted by
            # ``test_d_bulkhead_caps_concurrency``. Do NOT remove this gate to
            # "let execute_with_bulkhead queue": that would invert shed->queue
            # and diverge from the legacy loop. (Probe serialisation is still
            # owned by ``execute_with_bulkhead`` regardless of this gate.)
            if not self.router._is_model_ready_for_attempt(current_model):
                continue

            start_mono = time.monotonic()
            try:
                raw = await self._call_backend(
                    current_model,
                    chat_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tools=tool_list,
                    **kwargs,
                )
            except Exception as exc:
                # Fire circuit-breaker bookkeeping EXACTLY once for this
                # physical call (rate-limit headers, cooldown, permanent
                # marking all happen here).
                self.router._classify_and_record_error(current_model, exc)
                last_error = exc
                translated = self._translate_error(exc)
                if translated is not None:
                    # PermanentError / RateLimitError / ProviderError — hand to
                    # EK so RetryConfig.should_retry can classify. Do NOT keep
                    # looping here: EK owns the retry decision for HTTP errors.
                    raise translated from exc
                # Non-HTTP error (transport, timeout, etc.) — already recorded;
                # try the next fallback candidate.
                continue

            latency_ms = (time.monotonic() - start_mono) * 1000.0
            # Success bookkeeping fires EXACTLY once for this physical call.
            self.router.record_success(current_model, latency_ms)
            return ek_adapters.dict_to_llm_response(raw)

        raise ProviderError(
            f"No model available for tier {self.tier.name}. "
            f"Tried: {tried}. Last error: {last_error}"
        )

    # ------------------------------------------------------------------
    # StreamingProvider protocol
    # ------------------------------------------------------------------
    def stream(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        usage_sink: list[LLMResponse] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream text deltas through the hardened router's selected backend.

        Satisfies EK's structural ``StreamingProvider`` protocol: this is a
        *normal* (non-``async``) method that RETURNS an async iterator — call
        it without ``await`` and consume with ``async for``.

        The model is resolved via ``router.get_model_for_tier(tier)`` (same as
        the non-stream path) and each physical streamed call runs inside
        ``router.execute_with_bulkhead(model)`` so the per-provider bulkhead is
        honoured. Success / failure bookkeeping fires exactly once.

        ``tools`` are accepted for protocol-shape parity but not forwarded:
        the platform backend's ``complete_stream`` is a text-delta stream and
        does not carry tool calls.
        """
        return self._stream_impl(
            list(messages),
            temperature=temperature,
            max_tokens=max_tokens,
            usage_sink=usage_sink,
            **kwargs,
        )

    async def _stream_impl(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None,
        max_tokens: int | None,
        usage_sink: list[LLMResponse] | None,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """Async-generator implementation backing :meth:`stream`."""
        model = self.router.get_model_for_tier(self.tier)
        if model is None:
            raise ProviderError(
                f"No model available for tier {self.tier.name} (streaming)."
            )

        prompt = self._messages_to_prompt(messages)
        call_kwargs: dict[str, Any] = dict(kwargs)
        if temperature is not None:
            call_kwargs["temperature"] = temperature
        if max_tokens is not None:
            call_kwargs["max_tokens"] = max_tokens

        start_mono = time.monotonic()
        chunks: list[str] = []
        try:
            async with self.router.execute_with_bulkhead(model):
                async for chunk in self.backend.complete_stream(
                    model, prompt, **call_kwargs
                ):
                    chunks.append(chunk)
                    yield chunk
        except Exception as exc:
            self.router._classify_and_record_error(model, exc)
            raise

        latency_ms = (time.monotonic() - start_mono) * 1000.0
        self.router.record_success(model, latency_ms)
        if usage_sink is not None:
            usage_sink.append(
                LLMResponse(content="".join(chunks), raw={"model": model})
            )

    @staticmethod
    def _messages_to_prompt(messages: Sequence[dict[str, Any]]) -> str:
        """Flatten chat messages into a single prompt for the text stream API.

        The platform ``complete_stream`` backends take a single prompt string;
        we join message contents in order so multi-turn context is preserved.
        """
        parts: list[str] = []
        for message in messages:
            content = message.get("content")
            if isinstance(content, str) and content:
                parts.append(content)
        return "\n".join(parts)

    async def _call_backend(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None,
        max_tokens: int | None,
        tools: list[dict[str, Any]] | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Invoke ``backend.complete_chat`` inside the router bulkhead.

        Uses ``execute_with_bulkhead`` (NOT ``router._execute_call``, which is
        text-only and collapses the rich dict). Only forwards ``temperature`` /
        ``max_tokens`` when explicitly provided so the backend's own defaults
        (``backends_base`` signature) remain authoritative otherwise.
        """
        call_kwargs: dict[str, Any] = dict(kwargs)
        if temperature is not None:
            call_kwargs["temperature"] = temperature
        if max_tokens is not None:
            call_kwargs["max_tokens"] = max_tokens

        async with self.router.execute_with_bulkhead(model):
            return await self.backend.complete_chat(
                model,
                messages,
                tools=tools,
                **call_kwargs,
            )

    @staticmethod
    def _translate_error(exc: Exception) -> Exception | None:
        """Translate an ``httpx.HTTPStatusError`` to an EK error instance.

        Returns ``None`` for any non-HTTP-status exception (transport errors,
        timeouts, backend ``ValueError`` etc.) so the caller falls through to
        the next fallback candidate. Reuses :func:`ek_adapters.map_http_error`
        for the status->class mapping — no reimplementation.
        """
        if not _HTTPX_AVAILABLE or _httpx is None:
            return None
        if not isinstance(exc, _httpx.HTTPStatusError):
            return None

        response = exc.response
        status = response.status_code
        retry_after = _parse_retry_after(response)
        error_cls = ek_adapters.map_http_error(status, retry_after)

        message = f"Provider request failed with HTTP {status}"
        if retry_after is not None and error_cls.__name__ == "RateLimitError":
            # RateLimitError carries retry_after; PermanentError/ProviderError
            # take only (message, ...).
            return error_cls(message, retry_after=retry_after)  # type: ignore[call-arg]
        return error_cls(message)


# ---------------------------------------------------------------------------
# Provider cache (ADR-023 Phase 1): one SmartRouterProvider per
# (router, backend, tier) identity. The provider holds no per-call mutable
# state, so reusing one instance per tier avoids re-allocating a shim on every
# LLMClientWrapper.complete() call while staying correct — a different router,
# backend, or tier yields a distinct entry and a fresh build.
#
# Lifecycle assumption: the cache must NEVER return a provider built against a
# router/backend that has since been garbage-collected. A naive ``id()`` key is
# unsafe because CPython reuses ``id()`` values after an object is freed — a new
# router could collide with a dead one's key and receive a stale provider bound
# to the wrong (dead) router. We therefore:
#   * key on the *stable* ``(id(router), id(backend), tier)`` triple, AND
#   * store the cached provider in a ``WeakValueDictionary`` so a provider whose
#     only references are the (also dead) router/backend can be evicted, AND
#   * additionally hold weak references to the original router/backend and, on
#     every cache hit, VALIDATE that the live objects are identical (``is``).
#     A dead-ref or identity mismatch evicts the stale entry and rebuilds.
# This makes id()-reuse impossible to observe: a recycled id never passes the
# identity re-check, so a fresh provider is always built for a new object.
# ---------------------------------------------------------------------------

_ProviderCacheKey = tuple[int, int, ModelTier]


class _ProviderCacheEntry:
    """A cached provider plus weak refs to the router/backend it was built for.

    Holds the provider strongly (the cache is the owner) and the
    router/backend weakly so we can re-validate identity on hit without
    keeping them alive.
    """

    __slots__ = ("backend_ref", "provider", "router_ref")

    def __init__(
        self,
        provider: SmartRouterProvider,
        router: SmartModelRouter,
        backend: LLMBackend,
    ) -> None:
        self.provider = provider
        self.router_ref: weakref.ref[SmartModelRouter] = weakref.ref(router)
        self.backend_ref: weakref.ref[LLMBackend] = weakref.ref(backend)

    def matches(self, router: SmartModelRouter, backend: LLMBackend) -> bool:
        """True iff both weak refs are alive AND identical to the given pair."""
        return self.router_ref() is router and self.backend_ref() is backend


_provider_cache: dict[_ProviderCacheKey, _ProviderCacheEntry] | None = None


def _cache_key(
    router: SmartModelRouter, backend: LLMBackend, tier: ModelTier
) -> _ProviderCacheKey:
    """Identity-keyed cache key — never coalesces across distinct router/backend.

    Uses ``id()`` so two different router or backend objects never share a
    cached provider (they own divergent circuit-breaker / model state). The
    id()-reuse hazard is neutralised by the weakref identity re-check in
    :func:`get_provider`.
    """
    return (id(router), id(backend), tier)


def get_provider(
    router: SmartModelRouter, backend: LLMBackend, tier: ModelTier
) -> SmartRouterProvider:
    """Return a cached :class:`SmartRouterProvider` for this router/backend/tier.

    Builds and caches a fresh provider on first use for a given identity
    triple; subsequent calls with the same *live* triple return the same
    instance. The provider is immutable after construction (it stores
    only references to the router and backend, which own all mutable
    state), so caching is safe.

    A cache hit is validated against the live router/backend identity
    (see the module-level lifecycle note): a dead weak ref or an
    identity mismatch (the id() was recycled by a different object)
    evicts the stale entry and rebuilds.
    """
    global _provider_cache
    if _provider_cache is None:
        _provider_cache = {}
    key = _cache_key(router, backend, tier)
    entry = _provider_cache.get(key)
    if entry is not None and entry.matches(router, backend):
        return entry.provider
    provider = SmartRouterProvider(router, backend, tier)
    _provider_cache[key] = _ProviderCacheEntry(provider, router, backend)
    return provider


def reset_provider_cache() -> None:
    """Clear the module-level provider cache (test isolation seam)."""
    global _provider_cache
    _provider_cache = None


def _parse_retry_after(response: Any) -> float | None:
    """Extract a numeric ``Retry-After`` seconds value from an httpx response."""
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    raw = headers.get("retry-after")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
