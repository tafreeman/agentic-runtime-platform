"""LLM client wrapper with smart routing integration.

:class:`LLMClientWrapper` is the primary interface for making LLM calls
within the native engine.  It combines:

- **Smart routing** — delegates model selection to :class:`SmartModelRouter`,
  which provides health-weighted fallback, circuit-breaking, and adaptive
  cooldowns.
- **Response caching** — SHA-256 keyed, TTL-based deduplication with LRU
  pruning at 1 000 entries.
- **Token budget tracking** — :class:`TokenBudget` enforces a per-run cap
  on total token consumption.
- **Streaming support** — :meth:`complete_stream` yields response chunks
  while still recording router metrics on completion.
- **Retry with jitter** — :func:`retry_with_jitter` decorator provides
  exponential backoff with configurable jitter factor.

The :class:`LLMBackend` ABC (re-exported from
:mod:`agentic_v2.models.backends_base`) defines the interface that
concrete backends (OpenAI, Anthropic, Gemini, etc.) must implement.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable

if TYPE_CHECKING:
    from executionkit.provider import LLMResponse

    from ..middleware.response_sanitizer import ResponseSanitizer
    from ..middleware.sanitization import SanitizationMiddleware

from .backends_base import LLMBackend
from .cache_budget import CachedResponse, TokenBudget
from .fallback_selector import run_with_fallback
from .retry_utils import retry_with_jitter
from .router import ModelTier
from .sanitization_dispatch import (
    sanitize_content_blocks as _sd_content_blocks,
)
from .sanitization_dispatch import (
    sanitize_messages as _sd_messages,
)
from .sanitization_dispatch import (
    sanitize_prompt as _sd_prompt,
)
from .sanitization_dispatch import (
    sanitize_response_blocks as _sd_response_blocks,
)
from .sanitization_dispatch import (
    sanitize_response_text as _sd_response_text,
)
from .smart_router import SmartModelRouter, get_smart_router

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# String constants (extracted to satisfy python:S1192 — define once, reuse)
# ---------------------------------------------------------------------------

ERR_NO_LLM_BACKEND = "No LLM backend configured"


# LLMBackend re-exported from backends_base for backward compatibility.
# ADR-023 Phase 2: unified the divergent Protocol/ABC definitions onto the
# single ABC in backends_base. The ABC is a strict superset of the prior
# Protocol (adds complete_chat + default complete_stream/count_tokens),
# so existing call sites that only touched complete/complete_stream/
# count_tokens remain behavior-identical.
__all_reexports__ = ("LLMBackend",)


# TokenBudget and CachedResponse are defined in cache_budget.py and
# re-imported above.  retry_with_jitter is imported from retry_utils.


@dataclass
class LLMClientWrapper:
    """High-level LLM client with smart routing, caching, and budgeting.

    Wraps a pluggable :class:`LLMBackend` with :class:`SmartModelRouter`
    integration.  On each call, the router selects the best model for the
    requested tier, the client executes the call, and the router records
    the outcome (success + latency, or failure type) to improve future
    selections.

    Attributes:
        backend: Injected LLM backend (``None`` = placeholder mode).
        router: Smart model router for selection and health tracking.
        cache: In-memory response cache keyed by prompt + tier hash.
        cache_ttl_seconds: Time-to-live for cached responses (default 300 s).
        enable_cache: Master switch for response caching.
        budget: Optional token budget enforcing a per-run cap.
        log_prompts: Log truncated prompts at INFO level.
        log_responses: Log truncated responses at INFO level.
    """

    # Backend (injected)
    backend: LLMBackend | None = None

    # Router
    router: SmartModelRouter = field(default_factory=get_smart_router)

    # Caching
    cache: dict[str, CachedResponse] = field(default_factory=dict)
    cache_ttl_seconds: int = 300  # 5 minutes
    enable_cache: bool = True

    # Token budget
    budget: TokenBudget | None = None

    # Logging
    log_prompts: bool = False
    log_responses: bool = False

    # Sanitization (optional)
    sanitization: SanitizationMiddleware | None = None
    response_sanitizer: ResponseSanitizer | None = None

    @property
    def model_id(self) -> str | None:
        """Return the current default model ID from the router."""
        return self.router.get_model_for_tier(ModelTier.TIER_2)

    def set_backend(self, backend: LLMBackend) -> None:
        """Attach a concrete LLM backend."""
        self.backend = backend

    def set_budget(self, max_tokens: int) -> None:
        """Install a per-run token budget cap."""
        self.budget = TokenBudget(max_tokens=max_tokens)

    def _cache_key(self, prompt: str, tier: ModelTier, **kwargs: Any) -> str:
        """SHA-256 cache key from prompt, tier, and sorted kwargs (first 16 hex chars)."""
        key_data = f"{prompt}:{tier.value}:{sorted(kwargs.items())}"
        return hashlib.sha256(key_data.encode()).hexdigest()[:16]

    def _get_cached(self, key: str) -> CachedResponse | None:
        """Return the cached response for *key* if present and not TTL-expired."""
        if not self.enable_cache:
            return None

        cached = self.cache.get(key)
        if cached is None:
            return None

        # Expiry check
        if cached.age_seconds > self.cache_ttl_seconds:
            del self.cache[key]
            return None

        return cached

    def _set_cached(self, key: str, response: str, model: str, tokens: int) -> None:
        """Cache a response.

        Stores the model used and token count alongside the content to
        preserve metadata on cache hit. Includes LRU-style pruning if
        cache size exceeds 1000 entries.
        """
        if not self.enable_cache:
            return

        self.cache[key] = CachedResponse(
            response=response,
            model=model,
            timestamp=datetime.now(UTC),
            tokens_used=tokens,
        )

        # Cache Pruning Policy:
        # If cache too large, remove the oldest 100 entries (10%).
        if len(self.cache) > 1000:
            sorted_keys = sorted(
                self.cache.keys(), key=lambda k: self.cache[k].timestamp
            )
            for k in sorted_keys[:100]:
                del self.cache[k]

    async def _sanitize_prompt(self, prompt: str, source: str, tier: ModelTier) -> str:
        """Inbound prompt sanitizer — no-op when no sanitizer is attached."""
        return await _sd_prompt(
            prompt, source=source, tier=tier, sanitization=self.sanitization
        )

    async def _sanitize_messages(
        self, messages: list[dict[str, Any]], source: str, tier: ModelTier
    ) -> list[dict[str, Any]]:
        """Inbound chat-message sanitizer — no-op when no sanitizer is attached."""
        return await _sd_messages(
            messages, source=source, tier=tier, sanitization=self.sanitization
        )

    async def _sanitize_content_blocks(
        self, blocks: list[Any], source: str, tier: ModelTier
    ) -> tuple[list[Any], bool]:
        """Inbound list-of-blocks sanitizer — no-op when no sanitizer is attached."""
        return await _sd_content_blocks(
            blocks, source=source, tier=tier, sanitization=self.sanitization
        )

    async def _sanitize_response_text(self, response: str) -> str:
        """Outbound response sanitizer — no-op when no response sanitizer attached."""
        return await _sd_response_text(response, response_sanitizer=self.response_sanitizer)

    async def _sanitize_response_content_blocks(self, blocks: list[Any]) -> list[Any]:
        """Outbound list-of-blocks response sanitizer."""
        return await _sd_response_blocks(
            blocks, response_sanitizer=self.response_sanitizer
        )

    async def complete(
        self,
        prompt: str,
        tier: ModelTier = ModelTier.TIER_2,
        max_retries: int = 3,
        use_cache: bool = True,
        model: str | None = None,
        **kwargs: Any,
    ) -> tuple[str, str, int]:
        """Send completion request with smart routing.

        Dispatches between the flag-gated EK provider path and the legacy
        text path. This wrapper is intentionally **undecorated**: the EK
        branch must NOT be subject to :func:`retry_with_jitter`'s sleep-retry
        (the router + EK already own retry/record-once semantics, and an EK
        ``RateLimitError`` would otherwise trigger a multi-second backoff
        sleep here and hang). The legacy branch delegates to
        :meth:`_complete_legacy`, which carries the ``retry_with_jitter``
        decorator so its retry behaviour is byte-for-byte unchanged.

        Args:
            prompt: Prompt to send
            tier: Model tier to use
            max_retries: Maximum models to try
            use_cache: Whether to use response cache
            model: Optional explicit model override to bypass router selection
            **kwargs: Additional arguments for backend

        Returns:
            Tuple of (response, model_used, tokens_used)

        Raises:
            RuntimeError: If no backend configured or all models fail
            ValueError: If budget exceeded
        """
        if self.backend is None:
            raise RuntimeError(ERR_NO_LLM_BACKEND)

        # ADR-023 Phase 5b: flag-gated EK provider hot path. DEFAULT ON since
        # P7 (ADR-023) — the EK path is now the default. Force the legacy
        # branch with AGENTIC_EK_PROVIDER=0; when off, the legacy branch below
        # runs byte-for-byte. The EK path is dispatched HERE, in the
        # undecorated wrapper, so it early-returns before the
        # retry_with_jitter boundary that wraps _complete_legacy.
        from ..settings import get_settings

        if get_settings().agentic_ek_provider:
            return await self._complete_via_ek(
                prompt,
                tier,
                max_retries=max_retries,
                use_cache=use_cache,
                model=model,
                **kwargs,
            )

        return await self._complete_legacy(
            prompt,
            tier,
            max_retries=max_retries,
            use_cache=use_cache,
            model=model,
            **kwargs,
        )

    @retry_with_jitter(max_retries=3)
    async def _complete_legacy(
        self,
        prompt: str,
        tier: ModelTier = ModelTier.TIER_2,
        max_retries: int = 3,
        use_cache: bool = True,
        model: str | None = None,
        **kwargs: Any,
    ) -> tuple[str, str, int]:
        """Legacy text-only ``complete`` path (ADR-023), retry-decorated.

        Retained as the bake-in rollback path (reachable via
        ``AGENTIC_EK_PROVIDER=0``). Slated for removal post-bake-in once the
        EK provider path has soaked in production. Do NOT extend this branch
        with new behaviour — changes belong in ``_complete_via_ek``.

        Carries ``@retry_with_jitter`` so the legacy retry/backoff semantics
        remain byte-for-byte identical to the pre-restructure ``complete``.
        """
        if self.backend is None:
            raise RuntimeError(ERR_NO_LLM_BACKEND)

        # Check cache
        cache_key: str | None = None
        if use_cache and self.enable_cache:
            cache_key = self._cache_key(prompt, tier, model=model, **kwargs)
            cached = self._get_cached(cache_key)
            if cached:
                logger.debug(f"Cache hit for key {cache_key}")
                return cached.response, cached.model, cached.tokens_used

        # Log prompt if enabled
        if self.log_prompts:
            logger.info(f"Prompt (tier={tier.name}): {prompt[:200]}...")

        # Pre-send sanitization
        effective_prompt = await self._sanitize_prompt(prompt, "llm_complete", tier)

        # Use router for model selection and fallback
        async def call_model(m: str, p: str) -> str:
            return await self.backend.complete(m, p, **kwargs)

        def pre_attempt(selected_model: str) -> None:
            self._check_prompt_budget(effective_prompt, selected_model)

        async def attempt(selected_model: str) -> tuple[str, str, int]:
            start = time.monotonic()
            return await self._run_complete_attempt(
                call_model,
                selected_model,
                effective_prompt,
                start=start,
                use_cache=use_cache,
                cache_key=cache_key,
                cache_model=model,
            )

        def on_error(selected_model: str, error: Exception) -> None:
            self.router._classify_and_record_error(selected_model, error)
            logger.warning(f"Model {selected_model} failed: {error}")
            logger.warning(f"Model {model} failed: {error}")

        return await run_with_fallback(
            self.router,
            tier=tier,
            model=model,
            max_retries=max_retries,
            pre_attempt=pre_attempt,
            attempt=attempt,
            on_error=on_error,
        )

    def _check_prompt_budget(self, effective_prompt: str, selected_model: str) -> None:
        """Raise ValueError if the prompt's estimated cost exceeds the budget."""
        assert self.backend is not None  # guarded by callers before invocation
        prompt_tokens = self.backend.count_tokens(effective_prompt, selected_model)
        if self.budget and not self.budget.can_afford(prompt_tokens * 2):
            raise ValueError(
                f"Budget exceeded: {self.budget.used_tokens}/{self.budget.max_tokens}"
            )

    async def _run_complete_attempt(
        self,
        call_model: Callable[[str, str], Any],
        selected_model: str,
        effective_prompt: str,
        *,
        start: float,
        use_cache: bool,
        cache_key: str | None,
        cache_model: str | None,
    ) -> tuple[str, str, int]:
        """Execute one legacy ``complete`` attempt and record its success.

        Runs the routed call, counts tokens, records router success, applies
        response sanitization, updates the budget, and caches the result.
        """
        assert self.backend is not None  # guarded by complete() before invocation
        response = await self.router._execute_call(
            call_model, selected_model, effective_prompt
        )
        tokens = self.backend.count_tokens(effective_prompt + response, selected_model)
        latency = (time.monotonic() - start) * 1000

        # Record success
        self.router.record_success(selected_model, latency)

        # Post-receive response sanitization
        response = await self._sanitize_response_text(response)

        # Update budget
        if self.budget:
            self.budget.consume(tokens)

        # Cache response. Guard on enable_cache too: cache_key is only
        # set above when caching is enabled, so storing under the
        # bare `use_cache` flag raised UnboundLocalError when caching
        # was disabled. _set_cached is itself a no-op when disabled, so
        # this is behaviour-preserving.
        if use_cache and self.enable_cache and cache_key is not None:
            self._set_cached(cache_key, response, cache_model, tokens)

        # Log response if enabled
        if self.log_responses:
            logger.info(f"Response from {selected_model}: {response[:200]}...")

        return response, selected_model, tokens

    async def _complete_via_ek(
        self,
        prompt: str,
        tier: ModelTier,
        max_retries: int = 3,
        use_cache: bool = True,
        model: str | None = None,
        **kwargs: Any,
    ) -> tuple[str, str, int]:
        """ADR-023 Phase 5b EK provider path (``AGENTIC_EK_PROVIDER=1``).

        Sequence: cache → sanitize → EK ``checked_complete`` (retry-wrapped
        ``SmartRouterProvider.complete``) → sanitize response → budget → cache
        store. Record-once is owned by the router; FAILOVER on a retryable HTTP
        error (429 → RateLimitError, 5xx → ProviderError) is owned by EK's
        ``DEFAULT_RETRY``, which re-invokes ``complete()`` so the router
        re-selects a healthy model — restoring the multi-model failover the
        legacy ``complete()`` had and matching the tool path's
        ``_TrackedProvider(retry=None)`` seam (a ``PermanentError`` such as a
        401/403 is NOT retried). ``retry_with_jitter`` is NOT applied (the EK
        retry layer replaces it). ``max_retries`` is accepted only so the
        ImportError fallback can forward the caller's value to the legacy path;
        on the EK path retry breadth is governed by ``DEFAULT_RETRY``.

        Graceful fallback: if ExecutionKit is not importable, log a warning and
        fall back to the legacy path rather than raising — the EK provider is an
        optional acceleration, not a hard dependency.
        """
        if self.backend is None:
            raise RuntimeError(ERR_NO_LLM_BACKEND)

        try:
            from executionkit.cost import CostTracker
            from executionkit.patterns.base import checked_complete

            from .ek_provider import get_provider
        except ImportError:
            logger.warning(
                "ExecutionKit not importable; falling back to the legacy "
                "complete() path for this call (AGENTIC_EK_PROVIDER on)."
            )
            return await self._complete_legacy(
                prompt,
                tier,
                max_retries=max_retries,
                use_cache=use_cache,
                model=model,
                **kwargs,
            )

        # 1. Cache lookup (short-circuit). Same key as the legacy path —
        # scoped by the model override so a forced model never reads a cache
        # entry served by the tier default (mirrors the legacy path).
        cache_key = self._cache_key(prompt, tier, model=model, **kwargs)
        if use_cache and self.enable_cache:
            cached = self._get_cached(cache_key)
            if cached:
                logger.debug(f"Cache hit for key {cache_key} (EK path)")
                return cached.response, cached.model, cached.tokens_used

        if self.log_prompts:
            logger.info(f"Prompt (tier={tier.name}, EK): {prompt[:200]}...")

        # 2. Pre-send sanitization (identical gate to the legacy path).
        effective_prompt = await self._sanitize_prompt(prompt, "llm_complete", tier)

        # 3. Route through the EK provider shim (reliability lives here),
        # wrapped in EK's retry layer (checked_complete + DEFAULT_RETRY) so a
        # retryable HTTP failure re-invokes complete() and the router re-selects
        # a healthy model — restoring legacy complete() failover. budget=None:
        # the runtime TokenBudget below owns the token-sum ceiling, so EK's
        # call-budget stays unused here (mirrors the tool path's
        # _TrackedProvider(budget=None, retry=None)). The throwaway CostTracker
        # is required by the EK seam but its usage record is not consumed.
        messages = [{"role": "user", "content": effective_prompt}]
        provider = get_provider(self.router, self.backend, tier)
        response = await checked_complete(
            provider,
            messages,
            tracker=CostTracker(),
            budget=None,
            retry=None,
            model=model,
            **kwargs,
        )

        content = response.content
        total_tokens = response.total_tokens

        # 4. Post-receive response sanitization.
        content = await self._sanitize_response_text(content)

        # 5. Runtime TokenBudget owns the token-sum ceiling — consume FIRST and
        # raise on cap BEFORE returning or caching (ACCEPTED budget precedence).
        if self.budget and not self.budget.consume(total_tokens):
            raise ValueError(
                f"Budget exceeded: {self.budget.used_tokens}/{self.budget.max_tokens}"
            )

        # Resolve the model that served the request for cache metadata + return.
        model_used = self._resolve_ek_model_used(response, model, tier)

        # 6. Cache store.
        if use_cache:
            self._set_cached(cache_key, content, model_used, total_tokens)

        if self.log_responses:
            logger.info(f"Response from {model_used} (EK): {content[:200]}...")

        return content, model_used, total_tokens

    def _resolve_ek_model_used(
        self, response: Any, model: str | None, tier: ModelTier
    ) -> str:
        """Resolve the model that served an EK response for cache metadata.

        Prefers the model echoed in ``response.raw``; falls back to the
        explicit override, then the tier default, then an empty string.
        """
        raw = getattr(response, "raw", None)
        if isinstance(raw, dict):
            model_used = str(raw.get("model") or "")
            if model_used:
                return model_used
        return model or self.router.get_model_for_tier(tier) or ""

    async def complete_stream(
        self, prompt: str, tier: ModelTier = ModelTier.TIER_2, **kwargs: Any
    ) -> AsyncIterator[str]:
        """Send streaming completion request.

        Note: Streaming bypasses cache.

        Args:
            prompt: Prompt to send
            tier: Model tier
            **kwargs: Additional arguments

        Yields:
            Response chunks
        """
        if self.backend is None:
            raise RuntimeError(ERR_NO_LLM_BACKEND)

        # ADR-023: flag-gated EK streaming path. When on, delegate to the EK
        # provider's StreamingProvider.stream(); on ImportError or when the
        # flag is off, the legacy streaming path below runs unchanged.
        from ..settings import get_settings

        if get_settings().agentic_ek_provider:
            try:
                from .ek_provider import get_provider
            except ImportError:
                logger.warning(
                    "ExecutionKit not importable; falling back to the legacy "
                    "complete_stream() path (AGENTIC_EK_PROVIDER on)."
                )
                # Explicit fallback (mirrors _complete_via_ek): stream the legacy
                # path and return, so a future edit cannot silently break the
                # fall-through by reordering the branches below.
                async for chunk in self._complete_stream_legacy(
                    prompt, tier, **kwargs
                ):
                    yield chunk
                return
            else:
                async for chunk in self._complete_stream_via_ek(
                    prompt, tier, get_provider, **kwargs
                ):
                    yield chunk
                return

        async for chunk in self._complete_stream_legacy(prompt, tier, **kwargs):
            yield chunk

    async def _complete_stream_via_ek(
        self,
        prompt: str,
        tier: ModelTier,
        get_provider: Callable[..., Any],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """EK streaming path: sanitize → SmartRouterProvider.stream → budget.

        Reliability (bulkhead, record-once) lives inside the provider's
        ``stream``; here we own sanitization and budget accounting.
        """
        assert self.backend is not None  # guarded by complete_stream
        effective_prompt = await self._sanitize_prompt(prompt, "llm_stream", tier)
        messages = [{"role": "user", "content": effective_prompt}]
        provider = get_provider(self.router, self.backend, tier)

        usage_sink: list[LLMResponse] = []
        async for chunk in provider.stream(messages, usage_sink=usage_sink, **kwargs):
            yield chunk

        if self.budget and usage_sink:
            full_response = usage_sink[-1].content
            model_used = self.router.get_model_for_tier(tier) or ""
            tokens = self.backend.count_tokens(
                effective_prompt + full_response, model_used
            )
            self.budget.consume(tokens)

    async def _complete_stream_legacy(
        self, prompt: str, tier: ModelTier, **kwargs: Any
    ) -> AsyncIterator[str]:
        """Legacy streaming path — byte-for-byte unchanged from pre-EK."""
        assert self.backend is not None  # guarded by complete_stream
        model = self.router.get_model_for_tier(tier)
        if model is None:
            raise RuntimeError(f"No available model for tier {tier.name}")

        # Pre-send sanitization
        effective_prompt = await self._sanitize_prompt(prompt, "llm_stream", tier)

        start = time.monotonic()
        total_response = []

        try:
            async with self.router.execute_with_bulkhead(model):
                async for chunk in self.backend.complete_stream(
                    model, effective_prompt, **kwargs
                ):
                    total_response.append(chunk)
                    yield chunk

            # Record success after stream completes
            latency = (time.monotonic() - start) * 1000
            full_response = "".join(total_response)
            tokens = self.backend.count_tokens(effective_prompt + full_response, model)

            self.router.record_success(model, latency)

            if self.budget:
                self.budget.consume(tokens)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.router._classify_and_record_error(model, e)
            raise

    async def complete_chat(
        self,
        messages: list[dict[str, Any]],
        tier: ModelTier = ModelTier.TIER_2,
        max_retries: int = 3,
        use_cache: bool = True,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> tuple[dict[str, Any], str, int]:
        """Send a chat completion with smart routing.

        Sanitization runs outside the retry boundary so blocked content
        raises ``ValueError`` immediately without backoff.  Returns
        ``(response_dict, model_used, tokens_used)``.
        """
        if self.backend is None:
            raise RuntimeError(ERR_NO_LLM_BACKEND)

        if not hasattr(self.backend, "complete_chat"):
            raise RuntimeError("Backend does not support complete_chat")

        # Inbound sanitization runs OUTSIDE the retry boundary so blocked
        # content fails closed immediately (no backoff retries on ValueError).
        messages = await self._sanitize_messages(messages, "llm_chat", tier)

        return await self._complete_chat_with_retry(
            messages, tier, max_retries, use_cache, tools, model, **kwargs
        )

    @retry_with_jitter(max_retries=3)
    async def _complete_chat_with_retry(
        self,
        messages: list[dict[str, Any]],
        tier: ModelTier = ModelTier.TIER_2,
        max_retries: int = 3,
        use_cache: bool = True,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> tuple[dict[str, Any], str, int]:
        """Inner chat completion with retry — called after sanitization."""

        # Check cache
        cache_key: str | None = None
        if use_cache and self.enable_cache:
            cache_key = self._cache_key(str(messages), tier, tools=tools, model=model, **kwargs)
            cached_chat = self._get_cached_chat(cache_key)
            if cached_chat is not None:
                return cached_chat

        # Use router for model selection and fallback
        async def call_model(m: str, p: str) -> dict[str, Any]:
            # The prompt string 'p' is just passed to fulfill the interface but we ignore it
            # since complete_chat takes messages natively
            return await self.backend.complete_chat(m, messages, tools=tools, **kwargs)

        # Estimate tokens - rudimentary for messages
        # Convert messages to a single string to count tokens
        prompt_str = " ".join([m.get("content", "") for m in messages])

        def pre_attempt(selected_model: str) -> None:
            self._check_prompt_budget(prompt_str, selected_model)

        async def attempt(selected_model: str) -> tuple[dict[str, Any], str, int]:
            start = time.monotonic()
            return await self._run_chat_attempt(
                call_model,
                selected_model,
                prompt_str,
                start=start,
                use_cache=use_cache,
                cache_key=cache_key,
            )

        def on_error(selected_model: str, error: Exception) -> None:
            self.router._classify_and_record_error(selected_model, error)
            logger.warning(f"Model {selected_model} failed: {error}")

        return await run_with_fallback(
            self.router,
            tier=tier,
            model=model,
            max_retries=max_retries,
            pre_attempt=pre_attempt,
            attempt=attempt,
            on_error=on_error,
        )

    def _get_cached_chat(
        self, cache_key: str
    ) -> tuple[dict[str, Any], str, int] | None:
        """Return a decoded cached chat response, or None on miss/corruption."""
        cached = self._get_cached(cache_key)
        if cached is None:
            return None
        import json
        try:
            response_dict = json.loads(cached.response)
        except json.JSONDecodeError:
            return None  # Fall through if cache is corrupted
        logger.debug(f"Cache hit for chat key {cache_key}")
        return response_dict, cached.model, cached.tokens_used

    async def _run_chat_attempt(
        self,
        call_model: Callable[[str, str], Any],
        selected_model: str,
        prompt_str: str,
        *,
        start: float,
        use_cache: bool,
        cache_key: str | None,
    ) -> tuple[dict[str, Any], str, int]:
        """Execute one ``complete_chat`` attempt and record its success.

        Runs the routed call, counts request+response tokens, records router
        success, updates the budget, and caches the serialized response.
        """
        assert self.backend is not None  # guarded by complete_chat() before invocation
        # _execute_call expects a prompt string, so we pass prompt_str
        response_dict = await self.router._execute_call(
            call_model, selected_model, prompt_str
        )

        # Post-receive response sanitization (parity with the text path).
        # Runs before token counting so the budget reflects sanitized output.
        # Guarded on response_sanitizer so the no-op path avoids a dict copy.
        if self.response_sanitizer is not None:
            content = response_dict.get("content")
            if isinstance(content, str):
                response_dict = {
                    **response_dict,
                    "content": await self._sanitize_response_text(content),
                }
            elif isinstance(content, list):
                cleaned_blocks = await self._sanitize_response_content_blocks(
                    content
                )
                response_dict = {**response_dict, "content": cleaned_blocks}

        # Prefer real usage from the provider; fall back to char estimate.
        usage = response_dict.get("usage") or {}
        reported = (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)
        if reported > 0:
            tokens = reported
        else:
            response_text = response_dict.get("content", "") or ""
            if response_dict.get("tool_calls"):
                response_text += str(response_dict.get("tool_calls"))
            tokens = self.backend.count_tokens(prompt_str + response_text, selected_model)
        latency = (time.monotonic() - start) * 1000

        # Record success
        self.router.record_success(selected_model, latency)

        # Update budget
        if self.budget:
            self.budget.consume(tokens)

        # Cache response
        if use_cache and self.enable_cache and cache_key is not None:
            import json
            self._set_cached(cache_key, json.dumps(response_dict), selected_model, tokens)

        return response_dict, selected_model, tokens

    def with_sanitization(
        self,
        sanitization: SanitizationMiddleware | None = None,
        response_sanitizer: ResponseSanitizer | None = None,
    ) -> None:
        """Attach inbound and/or outbound sanitization middleware."""
        self.sanitization = sanitization
        self.response_sanitizer = response_sanitizer

    async def sanitize_inbound_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        source: str,
        tier: ModelTier,
    ) -> list[dict[str, Any]]:
        """Public inbound message sanitizer for non-``complete_chat`` callers.

        Closes the indirect-prompt-injection vector for agents that call a
        provider SDK directly.  No-op when no sanitizer is attached.

        Raises:
            ValueError: If any message content is classified as unsafe.
        """
        return await self._sanitize_messages(messages, source, tier)

    async def sanitize_outbound_text(self, text: str) -> str:
        """Public outbound response sanitizer — no-op when no sanitizer attached."""
        return await self._sanitize_response_text(text)

    def clear_cache(self) -> int:
        """Clear the response cache; returns the number of entries removed."""
        count = len(self.cache)
        self.cache.clear()
        return count

    def get_stats(self) -> dict[str, Any]:
        """Get client statistics."""
        return {
            "cache_entries": len(self.cache),
            "cache_enabled": self.enable_cache,
            "budget": {
                "max": self.budget.max_tokens if self.budget else None,
                "used": self.budget.used_tokens if self.budget else None,
                "remaining": self.budget.remaining if self.budget else None,
            },
            "router_stats": self.router.get_stats_summary(),
        }

    def __repr__(self) -> str:
        backend_name = type(self.backend).__name__ if self.backend else "None"
        return (
            f"LLMClientWrapper(backend={backend_name}, "
            f"cache_size={len(self.cache)}, "
            f"budget={'set' if self.budget else 'none'})"
        )


# Global client instance
_client: LLMClientWrapper | None = None


def get_client(auto_configure: bool = False) -> LLMClientWrapper:
    """Get the global LLM client.

    If ``AGENTIC_NO_LLM=1``, installs a ``MockBackend`` with an
    identifiable placeholder response and skips provider probing
    entirely.  See ``docs/NO_LLM_MODE.md``.

    Args:
        auto_configure: If True and no client exists, probe environment
            variables and set up a MultiBackend automatically.  Default
            is False so that unit tests get a backend-less client
            (placeholder mode).
    """
    global _client
    if _client is None:
        _client = LLMClientWrapper()
        from ..settings import is_agentic_no_llm_enabled

        if is_agentic_no_llm_enabled():
            from .backends import PLACEHOLDER_RESPONSE_TEXT, MockBackend

            _client.set_backend(
                MockBackend(default_response=PLACEHOLDER_RESPONSE_TEXT)
            )
            logger.warning(
                "AGENTIC_NO_LLM=1: all LLM calls return a placeholder. "
                "Disable for production workloads."
            )
        elif auto_configure:
            from .backends import auto_configure_backend

            try:
                _client.set_backend(auto_configure_backend())
            except RuntimeError:
                pass  # No backends available — will fail at call time

        _maybe_attach_agent_loop_sanitization(_client)
    return _client


def _maybe_attach_agent_loop_sanitization(client: LLMClientWrapper) -> None:
    """Attach default sanitization to the shared agent-loop client.

    Closes the indirect-prompt-injection vector by ensuring per-step LLM calls
    inside the agent loop — not just the HTTP request boundary — run inbound
    prompt sanitization and outbound response sanitization. Controlled by
    ``AGENTIC_SANITIZE_AGENT_LOOP`` (default on).

    Skipped under ``AGENTIC_NO_LLM`` (placeholder/demo mode), when the flag is
    off, or when a sanitizer is already attached (idempotent).
    """
    from ..settings import get_settings, is_agentic_no_llm_enabled

    if is_agentic_no_llm_enabled():
        return
    if not get_settings().agentic_sanitize_agent_loop:
        return
    if client.sanitization is not None or client.response_sanitizer is not None:
        return

    from ..middleware.response_sanitizer import ResponseSanitizer
    from ..middleware.sanitization import SanitizationMiddleware

    client.with_sanitization(
        sanitization=SanitizationMiddleware.default(),
        response_sanitizer=ResponseSanitizer(),
    )
    logger.info(
        "Agent-loop sanitization attached to the shared LLM client "
        "(AGENTIC_SANITIZE_AGENT_LOOP on)."
    )


def reset_client() -> None:
    """Reset the global client (for testing)."""
    global _client
    _client = None
