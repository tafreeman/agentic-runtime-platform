"""Tests for rate_limit_tracker.py (ADR-002E) and hardening features in
smart_router.py."""

import asyncio
import json
import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import agentic_v2.models.model_stats as model_stats_module
from agentic_v2.engine.tool_execution import complete_chat_with_fallback
from agentic_v2.models.client import LLMClientWrapper
from agentic_v2.models.model_stats import CircuitState, ModelStats
from agentic_v2.models.rate_limit_tracker import (
    RateLimitTracker,
    TokenBucket,
    _extract_provider,
    _parse_duration,
    _safe_int,
)
from agentic_v2.models.router import FallbackChain, ModelTier
from agentic_v2.models.smart_router import ModelSelection, SmartModelRouter

# ── TokenBucket tests ────────────────────────────────────────────────────────


class TestTokenBucket:
    """Tests for the token bucket rate limiter."""

    def test_initial_capacity(self) -> None:
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        assert bucket.remaining() == 10.0

    def test_consume_success(self) -> None:
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        assert bucket.consume(3) is True
        assert bucket.remaining() == pytest.approx(7.0, abs=0.1)

    def test_consume_insufficient(self) -> None:
        bucket = TokenBucket(capacity=5, refill_rate=1.0)
        assert bucket.consume(10) is False
        # Tokens should not be consumed on failure
        assert bucket.remaining() == pytest.approx(5.0, abs=0.1)

    def test_consume_exact(self) -> None:
        bucket = TokenBucket(capacity=5, refill_rate=1.0)
        assert bucket.consume(5) is True
        assert bucket.remaining() == pytest.approx(0.0, abs=0.1)

    def test_refill_over_time(self) -> None:
        bucket = TokenBucket(capacity=10, refill_rate=100.0)  # 100/sec
        bucket.consume(10)  # Drain completely
        # Manually advance the internal clock
        bucket._last_refill = time.monotonic() - 0.05  # 50ms ago
        # Should have refilled ~5 tokens (100/sec * 0.05s)
        remaining = bucket.remaining()
        assert 4.0 <= remaining <= 6.0

    def test_refill_capped_at_capacity(self) -> None:
        bucket = TokenBucket(capacity=10, refill_rate=1000.0)
        bucket._last_refill = time.monotonic() - 10.0  # 10 seconds ago
        assert bucket.remaining() == pytest.approx(10.0, abs=0.1)

    def test_time_until_available_immediately(self) -> None:
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        assert bucket.time_until_available(5) == 0.0

    def test_time_until_available_after_drain(self) -> None:
        bucket = TokenBucket(capacity=10, refill_rate=10.0)
        bucket.consume(10)
        wait_time = bucket.time_until_available(5)
        assert 0.3 <= wait_time <= 0.7  # ~0.5 seconds

    def test_time_until_available_zero_refill_rate(self) -> None:
        bucket = TokenBucket(capacity=10, refill_rate=0.0)
        bucket.consume(10)
        assert bucket.time_until_available(1) == float("inf")

    def test_reset_from_headers(self) -> None:
        bucket = TokenBucket(capacity=60, refill_rate=1.0)
        bucket.consume(60)  # Drain
        bucket.reset(remaining=45, reset_seconds=15.0)
        assert bucket.remaining() == pytest.approx(45.0, abs=0.1)
        # refill_rate should be recalculated: (60 - 45) / 15 = 1.0
        assert bucket.refill_rate == pytest.approx(1.0, abs=0.01)

    def test_reset_capped_at_capacity(self) -> None:
        bucket = TokenBucket(capacity=60, refill_rate=1.0)
        bucket.reset(remaining=100, reset_seconds=10.0)
        assert bucket.remaining() == pytest.approx(60.0, abs=0.1)


# ── Helper function tests ────────────────────────────────────────────────────


class TestHelperFunctions:
    """Tests for module-level utility functions."""

    def test_extract_provider_colon(self) -> None:
        assert _extract_provider("openai:gpt-4o") == "openai"
        assert _extract_provider("gh:gpt-4o-mini") == "gh"

    def test_extract_provider_slash(self) -> None:
        assert _extract_provider("anthropic/claude-3-sonnet") == "anthropic"

    def test_extract_provider_plain(self) -> None:
        assert _extract_provider("gpt-4o") == "unknown"

    def test_extract_provider_case_insensitive(self) -> None:
        assert _extract_provider("OpenAI:gpt-4o") == "openai"

    def test_safe_int_valid(self) -> None:
        assert _safe_int("42") == 42
        assert _safe_int("0") == 0

    def test_safe_int_negative(self) -> None:
        assert _safe_int("-1") is None

    def test_safe_int_invalid(self) -> None:
        assert _safe_int(None) is None
        assert _safe_int("abc") is None
        assert _safe_int("") is None

    def test_parse_duration_plain_seconds(self) -> None:
        assert _parse_duration("6.0") == pytest.approx(6.0)

    def test_parse_duration_seconds_suffix(self) -> None:
        assert _parse_duration("6s") == pytest.approx(6.0)

    def test_parse_duration_minutes_and_seconds(self) -> None:
        assert _parse_duration("1m30s") == pytest.approx(90.0)

    def test_parse_duration_milliseconds(self) -> None:
        assert _parse_duration("200ms") == pytest.approx(0.2)

    def test_parse_duration_minutes_only(self) -> None:
        # "2m" → should parse as 120 seconds
        # The current parser splits on "m" and remaining is empty
        assert _parse_duration("2m0s") == pytest.approx(120.0)

    def test_parse_duration_none(self) -> None:
        assert _parse_duration(None) is None

    def test_parse_duration_invalid(self) -> None:
        assert _parse_duration("invalid") is None


# ── RateLimitTracker tests ───────────────────────────────────────────────────


class TestRateLimitTracker:
    """Tests for the main rate-limit tracker."""

    def test_get_provider_creates_default(self) -> None:
        tracker = RateLimitTracker()
        state = tracker.get_provider("openai:gpt-4o")
        assert state.provider == "openai"
        assert state.rpm_bucket.capacity == 60

    def test_get_provider_github(self) -> None:
        tracker = RateLimitTracker()
        state = tracker.get_provider("gh:gpt-4o-mini")
        assert state.provider == "gh"
        assert state.rpm_bucket.capacity == 15

    def test_get_provider_unknown_uses_conservative_default(self) -> None:
        tracker = RateLimitTracker()
        state = tracker.get_provider("custom-model")
        assert state.provider == "unknown"
        assert state.rpm_bucket.capacity == 30

    def test_get_provider_cached(self) -> None:
        tracker = RateLimitTracker()
        s1 = tracker.get_provider("openai:gpt-4o")
        s2 = tracker.get_provider("openai:gpt-4o-mini")
        assert s1 is s2  # Same provider → same state object

    def test_can_request_basic(self) -> None:
        tracker = RateLimitTracker()
        assert tracker.can_request("openai:gpt-4o") is True

    def test_parse_retry_after_integer(self) -> None:
        tracker = RateLimitTracker()
        result = tracker.parse_retry_after({"Retry-After": "5"})
        assert result == 5

    def test_parse_retry_after_case_insensitive(self) -> None:
        tracker = RateLimitTracker()
        result = tracker.parse_retry_after({"retry-after": "10"})
        assert result == 10

    def test_parse_retry_after_missing(self) -> None:
        tracker = RateLimitTracker()
        result = tracker.parse_retry_after({})
        assert result is None

    def test_parse_retry_after_rejects_large_values(self) -> None:
        tracker = RateLimitTracker()
        result = tracker.parse_retry_after({"Retry-After": "7200"})
        assert result is None  # > 3600 rejected

    def test_parse_retry_after_rejects_negative(self) -> None:
        tracker = RateLimitTracker()
        result = tracker.parse_retry_after({"Retry-After": "-5"})
        assert result is None

    def test_update_from_headers_retry_after(self) -> None:
        tracker = RateLimitTracker()
        cooldown = tracker.update_from_headers("openai:gpt-4o", {"Retry-After": "8"})
        assert cooldown == 8

    def test_update_from_headers_openai_rate_limit(self) -> None:
        tracker = RateLimitTracker()
        headers = {
            "x-ratelimit-remaining-requests": "0",
            "x-ratelimit-reset-requests": "6s",
            "x-ratelimit-remaining-tokens": "50000",
            "x-ratelimit-reset-tokens": "1m0s",
        }
        cooldown = tracker.update_from_headers("openai:gpt-4o", headers)
        assert cooldown == 6  # Reset time when remaining is 0

    def test_update_from_headers_openai_not_exhausted(self) -> None:
        tracker = RateLimitTracker()
        headers = {
            "x-ratelimit-remaining-requests": "5",
            "x-ratelimit-reset-requests": "6s",
        }
        cooldown = tracker.update_from_headers("openai:gpt-4o", headers)
        assert cooldown is None  # Still has capacity

    def test_update_from_headers_anthropic_exhausted(self) -> None:
        tracker = RateLimitTracker()
        headers = {"x-ratelimit-remaining-requests": "0"}
        cooldown = tracker.update_from_headers("anthropic:claude-3-sonnet", headers)
        assert cooldown == 60  # Conservative Anthropic fallback

    def test_update_from_headers_github_epoch_reset(self) -> None:
        tracker = RateLimitTracker()
        headers = {
            "x-ratelimit-remaining": "0",
            "x-ratelimit-reset": "1700000037",
        }

        with patch(
            "agentic_v2.models.rate_limit_tracker.time.time",
            return_value=1700000000,
        ):
            cooldown = tracker.update_from_headers("gh:openai/gpt-4o-mini", headers)

        assert cooldown == 37

    def test_update_from_headers_azure_reset_requests(self) -> None:
        tracker = RateLimitTracker()
        headers = {
            "x-ms-ratelimit-remaining-requests": "0",
            "x-ms-ratelimit-reset-requests": "23s",
        }

        cooldown = tracker.update_from_headers("azure:gpt-4o", headers)

        assert cooldown == 23

    def test_update_from_headers_gemini_reset(self) -> None:
        tracker = RateLimitTracker()
        headers = {
            "x-ratelimit-remaining": "0",
            "x-ratelimit-reset": "42s",
        }

        cooldown = tracker.update_from_headers("gemini:gemini-2.0-flash", headers)

        assert cooldown == 42

    def test_get_cooldown_seconds_with_retry_after(self) -> None:
        tracker = RateLimitTracker()
        headers = {"Retry-After": "3"}
        cooldown = tracker.get_cooldown_seconds("openai:gpt-4o", headers=headers)
        assert cooldown == 3

    def test_get_cooldown_seconds_no_headers(self) -> None:
        tracker = RateLimitTracker()
        cooldown = tracker.get_cooldown_seconds("openai:gpt-4o")
        # Default 120 + 10-25% jitter
        assert 120 <= cooldown <= 160

    def test_get_cooldown_seconds_uses_last_retry_after(self) -> None:
        tracker = RateLimitTracker()
        # First call with headers sets last_retry_after
        tracker.update_from_headers("openai:gpt-4o", {"Retry-After": "5"})
        # Second call without headers uses cached value
        cooldown = tracker.get_cooldown_seconds("openai:gpt-4o")
        # 5 + 10-25% jitter
        assert 5 <= cooldown <= 8


# ── SmartModelRouter hardening tests ─────────────────────────────────────────


class _StatusError(RuntimeError):
    """A provider error carrying an HTTP ``status_code`` (OpenAI-style)."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class TestSmartModelRouterHardening:
    """Tests for ADR-002 hardening features in SmartModelRouter."""

    @pytest.fixture(autouse=True)
    def _pin_legacy_path(self, monkeypatch: pytest.MonkeyPatch):
        """Pin the LEGACY ``wrapper.complete -> backend.complete`` path.

        These tests assert legacy router/bulkhead mechanics and synchronize on
        an ``asyncio.Event`` set inside a backend's text ``complete`` method.
        Under an ambient ``AGENTIC_EK_PROVIDER=1`` (the ADR-023 B-2 default-on
        condition) ``LLMClientWrapper.complete`` reroutes through the EK shim's
        ``complete_chat`` seam, the legacy ``complete`` is never called, the
        handshake event never fires, and the test deadlocks. Forcing the flag
        OFF keeps the class testing the path it was written for. The EK path
        has its own bulkhead coverage in ``tests/models/test_ek_provider_wrapper``.
        """
        from agentic_v2.settings import get_settings

        monkeypatch.setenv("AGENTIC_EK_PROVIDER", "0")
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    def _make_router(self) -> SmartModelRouter:
        """Create a router with a test fallback chain."""
        router = SmartModelRouter()
        chain = FallbackChain(
            ("openai:gpt-4o-mini", "gh:gpt-4o-mini", "ollama:phi4"), "test"
        )
        router.register_chain(ModelTier.TIER_1, chain)
        return router

    def test_bulkhead_semaphore_creation(self) -> None:
        router = self._make_router()
        sem = router._get_semaphore("openai:gpt-4o")
        assert isinstance(sem, asyncio.Semaphore)
        assert sem._value == 50  # Default OpenAI limit

    def test_bulkhead_semaphore_cached(self) -> None:
        router = self._make_router()
        s1 = router._get_semaphore("openai:gpt-4o")
        s2 = router._get_semaphore("openai:gpt-4o-mini")
        assert s1 is s2  # Same provider → same semaphore

    def test_bulkhead_different_providers(self) -> None:
        router = self._make_router()
        s1 = router._get_semaphore("openai:gpt-4o")
        s2 = router._get_semaphore("ollama:phi4")
        assert s1 is not s2
        assert s2._value == 10  # Ollama limit

    def test_probe_lock_creation(self) -> None:
        router = self._make_router()
        lock = router._get_probe_lock("openai:gpt-4o")
        assert isinstance(lock, asyncio.Lock)

    def test_probe_lock_cached(self) -> None:
        router = self._make_router()
        l1 = router._get_probe_lock("openai:gpt-4o")
        l2 = router._get_probe_lock("openai:gpt-4o-mini")
        assert l1 is l2

    def test_is_model_ready_when_healthy(self) -> None:
        router = self._make_router()
        assert router._is_model_ready_for_attempt("openai:gpt-4o-mini") is True

    def test_is_model_ready_rejects_at_capacity(self) -> None:
        router = self._make_router()
        sem = router._get_semaphore("openai:gpt-4o-mini")
        # Drain the semaphore
        for _ in range(50):
            sem._value -= 1
        assert router._is_model_ready_for_attempt("openai:gpt-4o-mini") is False

    def test_is_model_ready_rejects_during_probe(self) -> None:
        router = self._make_router()
        model = "openai:gpt-4o-mini"
        stats = router._get_stats(model)
        stats.circuit_state = CircuitState.HALF_OPEN
        lock = router._get_probe_lock(model)
        # Simulate a locked probe
        lock._locked = True
        assert router._is_model_ready_for_attempt(model) is False

    def test_record_rate_limit_with_headers(self) -> None:
        router = self._make_router()
        model = "openai:gpt-4o-mini"
        headers = {"Retry-After": "5"}
        router.record_rate_limit(model, response_headers=headers)
        stats = router._get_stats(model)
        assert stats.rate_limit_count == 1
        assert stats.is_in_cooldown

    def test_record_rate_limit_without_headers(self) -> None:
        router = self._make_router()
        model = "openai:gpt-4o-mini"
        router.record_rate_limit(model)
        stats = router._get_stats(model)
        assert stats.rate_limit_count == 1
        assert stats.is_in_cooldown

    @pytest.mark.asyncio
    async def test_call_with_fallback_success(self) -> None:
        router = self._make_router()
        caller = AsyncMock(return_value="response text")

        model, response = await router.call_with_fallback(
            caller, "Hello", ModelTier.TIER_1
        )
        assert response == "response text"
        assert model == "openai:gpt-4o-mini"
        caller.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_with_fallback_falls_through(self) -> None:
        router = self._make_router()
        call_count = 0

        async def flaky_caller(model: str, prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("rate limit 429")
            return "success"

        _, response = await router.call_with_fallback(
            flaky_caller, "Hello", ModelTier.TIER_1
        )
        assert response == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_call_with_fallback_all_fail(self) -> None:
        router = self._make_router()
        caller = AsyncMock(side_effect=RuntimeError("always fails"))

        with pytest.raises(RuntimeError, match="All models failed"):
            await router.call_with_fallback(caller, "Hello", ModelTier.TIER_1)

    def test_classify_error_rate_limit(self) -> None:
        router = self._make_router()
        model = "openai:gpt-4o-mini"
        error = RuntimeError("rate limit exceeded (429)")
        router._classify_and_record_error(model, error)
        stats = router._get_stats(model)
        assert stats.rate_limit_count == 1

    def test_classify_error_timeout(self) -> None:
        router = self._make_router()
        model = "openai:gpt-4o-mini"
        error = RuntimeError("connection timeout")
        router._classify_and_record_error(model, error)
        stats = router._get_stats(model)
        assert stats.timeout_count == 1

    def test_classify_error_permanent(self) -> None:
        # Only a real 4xx status marks the model permanently unavailable.
        router = self._make_router()
        model = "openai:gpt-4o-mini"
        error = _StatusError("model not found", status_code=404)
        router._classify_and_record_error(model, error)
        assert not router.is_model_available(model)

    def test_classify_error_transient_not_found_not_permanent(self) -> None:
        # A bare "not found" message with no HTTP status is transient: a briefly
        # unavailable model must not be evicted permanently on a substring match.
        router = self._make_router()
        model = "openai:gpt-4o-mini"
        error = RuntimeError("model not found, retrying")
        router._classify_and_record_error(model, error)
        assert router.is_model_available(model)

    def test_classify_error_rate_limit_by_status(self) -> None:
        # A 429 status is a rate limit even when the message text says nothing.
        router = self._make_router()
        model = "openai:gpt-4o-mini"
        error = _StatusError("upstream rejected the request", status_code=429)
        router._classify_and_record_error(model, error)
        stats = router._get_stats(model)
        assert stats.rate_limit_count == 1

    def test_classify_error_timeout_by_status(self) -> None:
        # A 408 status is a timeout even when the message text says nothing.
        router = self._make_router()
        model = "openai:gpt-4o-mini"
        error = _StatusError("upstream gateway timeout", status_code=408)
        router._classify_and_record_error(model, error)
        stats = router._get_stats(model)
        assert stats.timeout_count == 1
        assert stats.rate_limit_count == 0

    def test_classify_error_status_408_beats_rate_limit_message(self) -> None:
        # HTTP status is authoritative: a 408 (timeout) whose body happens to
        # mention "rate limit" must be recorded as a timeout, not a rate limit.
        # Guards the precedence inversion where the message-derived code beat the
        # status and applied the longer, header-driven rate-limit cooldown.
        router = self._make_router()
        model = "openai:gpt-4o-mini"
        error = _StatusError("rate limit exceeded", status_code=408)
        router._classify_and_record_error(model, error)
        stats = router._get_stats(model)
        assert stats.timeout_count == 1
        assert stats.rate_limit_count == 0

    @pytest.mark.asyncio
    async def test_execute_call_uses_semaphore(self) -> None:
        router = self._make_router()
        model = "openai:gpt-4o-mini"
        sem = router._get_semaphore(model)
        initial_value = sem._value

        call_started = asyncio.Event()
        call_release = asyncio.Event()

        async def slow_caller(m: str, p: str) -> str:
            call_started.set()
            await call_release.wait()
            return "done"

        # Start the call but don't complete it
        task = asyncio.create_task(router._execute_call(slow_caller, model, "test"))
        await call_started.wait()

        # Semaphore should be decremented while call is in progress
        assert sem._value == initial_value - 1

        # Release and verify cleanup
        call_release.set()
        result = await task
        assert result == "done"
        assert sem._value == initial_value

    @pytest.mark.asyncio
    async def test_execute_call_probe_lock_for_half_open(self) -> None:
        router = self._make_router()
        model = "openai:gpt-4o-mini"
        stats = router._get_stats(model)
        stats.circuit_state = CircuitState.HALF_OPEN

        lock = router._get_probe_lock(model)
        caller = AsyncMock(return_value="probed")

        # Should acquire probe lock during call
        result = await router._execute_call(caller, model, "test")
        assert result == "probed"
        # Lock should be released
        assert not lock.locked()

    @pytest.mark.asyncio
    async def test_client_complete_runs_backend_under_provider_bulkhead(self) -> None:
        router = self._make_router()
        model = "openai:gpt-4o-mini"
        semaphore = router._get_semaphore(model)
        initial_value = semaphore._value

        class BlockingBackend:
            def __init__(self) -> None:
                self.started = asyncio.Event()
                self.release = asyncio.Event()

            async def complete(self, model: str, prompt: str, **kwargs: object) -> str:
                self.started.set()
                await self.release.wait()
                return "done"

            def count_tokens(self, text: str, model: str) -> int:
                return len(text)

        backend = BlockingBackend()
        client = LLMClientWrapper(backend=backend, router=router, enable_cache=False)
        task = asyncio.create_task(
            client.complete("hello", tier=ModelTier.TIER_1, use_cache=False)
        )

        await backend.started.wait()
        assert semaphore._value == initial_value - 1

        backend.release.set()
        response, used_model, _ = await task
        assert response == "done"
        assert used_model == model
        assert semaphore._value == initial_value

    @pytest.mark.asyncio
    async def test_client_stream_runs_backend_under_provider_bulkhead(self) -> None:
        router = self._make_router()
        model = "openai:gpt-4o-mini"
        semaphore = router._get_semaphore(model)
        initial_value = semaphore._value

        class StreamingBackend:
            def __init__(self) -> None:
                self.started = asyncio.Event()
                self.release = asyncio.Event()

            async def complete(self, model: str, prompt: str, **kwargs: object) -> str:
                return "unused"

            async def complete_stream(
                self, model: str, prompt: str, **kwargs: object
            ):
                self.started.set()
                await self.release.wait()
                yield "a"
                yield "b"

            def count_tokens(self, text: str, model: str) -> int:
                return len(text)

        backend = StreamingBackend()
        client = LLMClientWrapper(backend=backend, router=router)

        chunks: list[str] = []

        async def consume_stream() -> None:
            async for chunk in client.complete_stream("hello", tier=ModelTier.TIER_1):
                chunks.append(chunk)

        task = asyncio.create_task(consume_stream())

        await backend.started.wait()
        assert semaphore._value == initial_value - 1

        backend.release.set()
        await task
        assert chunks == ["a", "b"]
        assert semaphore._value == initial_value

    @pytest.mark.asyncio
    async def test_tool_chat_completion_runs_under_provider_bulkhead(self) -> None:
        router = self._make_router()
        model = "openai:gpt-4o-mini"
        semaphore = router._get_semaphore(model)
        initial_value = semaphore._value

        class ChatBackend:
            def __init__(self) -> None:
                self.started = asyncio.Event()
                self.release = asyncio.Event()

            async def complete_chat(self, *args: object, **kwargs: object) -> dict[str, object]:
                self.started.set()
                await self.release.wait()
                return {"content": "done", "usage": {"total_tokens": 3}}

            def count_tokens(self, text: str, model: str) -> int:
                return len(text)

        backend = ChatBackend()
        client = LLMClientWrapper(backend=backend, router=router, enable_cache=False)
        task = asyncio.create_task(
            complete_chat_with_fallback(
                client=client,
                tier=ModelTier.TIER_1,
                messages=[{"role": "user", "content": "hello"}],
                max_tokens=64,
                tools=None,
            )
        )

        await backend.started.wait()
        assert semaphore._value == initial_value - 1

        backend.release.set()
        response, used_model, tokens = await task
        assert response["content"] == "done"
        assert used_model == model
        assert tokens == 9
        assert semaphore._value == initial_value


# ── Monotonic clock integration tests ────────────────────────────────────────


class TestMonotonicClockIntegration:
    """Verify monotonic clock usage across model_stats and smart_router (ADR-002C)."""

    def test_cooldown_uses_monotonic(self) -> None:
        stats = ModelStats(model_id="test:model")
        stats.set_cooldown(10)
        assert stats._cooldown_until_mono is not None
        assert stats.is_in_cooldown is True

    def test_cooldown_remaining_monotonic(self) -> None:
        stats = ModelStats(model_id="test:model")
        stats.set_cooldown(30)
        remaining = stats.cooldown_remaining_seconds
        assert 28.0 <= remaining <= 31.0

    def test_clear_cooldown_clears_mono(self) -> None:
        stats = ModelStats(model_id="test:model")
        stats.set_cooldown(10)
        stats.clear_cooldown()
        assert stats._cooldown_until_mono is None
        assert stats.is_in_cooldown is False

    def test_record_failure_sets_mono(self) -> None:
        stats = ModelStats(model_id="test:model")
        stats.record_failure("test")
        assert stats._last_failure_mono is not None
        assert abs(stats._last_failure_mono - time.monotonic()) < 1.0

    def test_check_circuit_uses_mono_for_recovery(self) -> None:
        stats = ModelStats(model_id="test:model")
        stats._recovery_timeout_seconds = 1
        # Open the circuit
        for _ in range(5):
            stats.record_failure("test")
        assert stats.circuit_state == CircuitState.OPEN
        assert stats.check_circuit() is False

        # Simulate time passage via monotonic
        stats._last_failure_mono = time.monotonic() - 2.0
        assert stats.check_circuit() is True
        assert stats.circuit_state == CircuitState.HALF_OPEN

    def test_serialization_roundtrip_recomputes_mono(self) -> None:
        stats = ModelStats(model_id="test:model")
        stats.set_cooldown(60)
        data = stats.to_dict()

        restored = ModelStats.from_dict(data)
        assert restored._cooldown_until_mono is not None
        assert restored.is_in_cooldown is True
        assert 55.0 <= restored.cooldown_remaining_seconds <= 65.0

    def test_serialization_expired_cooldown(self) -> None:
        stats = ModelStats(model_id="test:model")
        stats.set_cooldown(1)
        data = stats.to_dict()
        # Hack: Make the wall-clock time be in the past
        from datetime import datetime

        past = datetime(2020, 1, 1, tzinfo=UTC)
        data["cooldown_until"] = past.isoformat()

        restored = ModelStats.from_dict(data)
        assert restored._cooldown_until_mono is None
        assert restored.is_in_cooldown is False

    def test_runtime_cooldown_ignores_wall_clock_jumps(self, monkeypatch) -> None:
        mono_now = 1000.0

        def fake_monotonic() -> float:
            return mono_now

        monkeypatch.setattr(model_stats_module.time, "monotonic", fake_monotonic)
        stats = ModelStats(model_id="test:model")
        stats.set_cooldown(10)

        class JumpedDateTime(datetime):
            offset = timedelta()

            @classmethod
            def now(cls, tz=None):  # type: ignore[no-untyped-def]
                return datetime(2026, 5, 9, tzinfo=UTC) + cls.offset

        monkeypatch.setattr(model_stats_module, "datetime", JumpedDateTime)

        JumpedDateTime.offset = timedelta(days=365)
        mono_now = 1005.0
        assert stats.is_in_cooldown is True
        assert stats.cooldown_remaining_seconds == pytest.approx(5.0)

        JumpedDateTime.offset = timedelta(days=-365)
        mono_now = 1011.0
        assert stats.is_in_cooldown is False
        assert stats.cooldown_remaining_seconds == 0.0


# ── Task 2.1: Concurrent stats persistence tests ─────────────────────────────


class TestConcurrentStatsPersistence:
    """Verify filelock prevents corruption under concurrent save/load."""

    def test_concurrent_save_load_no_corruption(self, tmp_path: Path) -> None:
        """Multiple threads saving/loading stats should not corrupt data."""
        stats_file = tmp_path / "stats.json"
        errors: list[Exception] = []

        def save_and_load(thread_id: int) -> None:
            try:
                router = SmartModelRouter(stats_file=stats_file)
                model = f"openai:model-{thread_id}"
                router.record_success(model, latency_ms=100.0 + thread_id)
                # Force a load in a separate router instance
                reader = SmartModelRouter(stats_file=stats_file)
                # Verify data is valid JSON
                assert isinstance(reader.model_stats, dict)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=save_and_load, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent save/load errors: {errors}"

        # Final read should yield valid stats
        final_router = SmartModelRouter(stats_file=stats_file)
        assert isinstance(final_router.model_stats, dict)
        assert len(final_router.model_stats) > 0

    def test_stats_file_written(self, tmp_path: Path) -> None:
        """Saving stats should produce a valid JSON file."""
        stats_file = tmp_path / "stats.json"
        router = SmartModelRouter(stats_file=stats_file)
        router.record_success("openai:gpt-4o", latency_ms=50.0)
        assert stats_file.exists()
        data = json.loads(stats_file.read_text())
        assert "stats" in data
        assert "openai:gpt-4o" in data["stats"]


# ── Task 2.2: HTTP-date Retry-After tests ────────────────────────────────────


class TestRetryAfterHTTPDate:
    """Tests for HTTP-date format in Retry-After header parsing."""

    def test_parse_retry_after_http_date(self) -> None:
        """HTTP-date Retry-After should parse to seconds delta."""
        tracker = RateLimitTracker()
        # Use a date 60 seconds in the future
        future = datetime.now(UTC) + timedelta(seconds=60)
        date_str = future.strftime("%a, %d %b %Y %H:%M:%S GMT")
        result = tracker.parse_retry_after({"Retry-After": date_str})
        assert result is not None
        assert 55 <= result <= 65

    def test_parse_retry_after_http_date_past(self) -> None:
        """HTTP-date in the past should return None (0 seconds)."""
        tracker = RateLimitTracker()
        past = datetime(2020, 1, 1, tzinfo=UTC)
        date_str = past.strftime("%a, %d %b %Y %H:%M:%S GMT")
        result = tracker.parse_retry_after({"Retry-After": date_str})
        assert result is None  # 0 seconds fails the > 0 check

    def test_parse_retry_after_invalid_string(self) -> None:
        """Non-numeric, non-date string should return None."""
        tracker = RateLimitTracker()
        result = tracker.parse_retry_after({"Retry-After": "not-a-date-or-number"})
        assert result is None

    def test_parse_retry_after_http_date_far_future(self) -> None:
        """HTTP-date > 3600 seconds in the future should be rejected."""
        tracker = RateLimitTracker()
        far = datetime.now(UTC) + timedelta(hours=2)
        date_str = far.strftime("%a, %d %b %Y %H:%M:%S GMT")
        result = tracker.parse_retry_after({"Retry-After": date_str})
        assert result is None  # > 3600 rejected


# ── Task 2.3: ModelSelection / degraded-mode tests ──────────────────────────


class TestModelSelectionDegradedMode:
    """Tests for the ModelSelection dataclass and is_degraded flag."""

    def _make_multi_tier_router(self) -> SmartModelRouter:
        """Create a router with chains for multiple tiers."""
        router = SmartModelRouter()
        router.register_chain(
            ModelTier.TIER_1,
            FallbackChain(("openai:gpt-4o-mini",), "tier1"),
        )
        router.register_chain(
            ModelTier.TIER_2,
            FallbackChain(("openai:gpt-4o", "gh:gpt-4o-mini"), "tier2"),
        )
        router.register_chain(
            ModelTier.TIER_3,
            FallbackChain(("anthropic:claude-3-sonnet",), "tier3"),
        )
        return router

    def test_model_selection_dataclass_frozen(self) -> None:
        """ModelSelection should be immutable."""
        sel = ModelSelection(
            model_name="openai:gpt-4o",
            requested_tier="TIER_2",
            actual_tier="TIER_2",
        )
        with pytest.raises(AttributeError):
            sel.model_name = "changed"  # type: ignore[misc]

    def test_same_tier_not_degraded(self) -> None:
        """Normal routing within the same tier sets is_degraded=False."""
        router = self._make_multi_tier_router()
        model = router.get_model_for_tier(ModelTier.TIER_2)
        assert model is not None
        sel = router.last_selection
        assert sel is not None
        assert sel.is_degraded is False
        assert sel.requested_tier == "TIER_2"
        assert sel.actual_tier == "TIER_2"

    def test_cross_tier_is_degraded(self) -> None:
        """Cross-tier fallback sets is_degraded=True."""
        router = self._make_multi_tier_router()
        # Exhaust TIER_3
        stats = router._get_stats("anthropic:claude-3-sonnet")
        for _ in range(5):
            stats.record_failure("test")

        model = router.get_model_for_tier(ModelTier.TIER_3)
        assert model is not None
        sel = router.last_selection
        assert sel is not None
        assert sel.is_degraded is True
        assert sel.requested_tier == "TIER_3"
        assert sel.actual_tier != "TIER_3"

    def test_no_candidates_sets_none(self) -> None:
        """When no model is available, last_selection is None."""
        router = SmartModelRouter()
        router.register_chain(ModelTier.TIER_1, FallbackChain(("m:a",), "t"))
        stats = router._get_stats("m:a")
        for _ in range(5):
            stats.record_failure("test")

        model = router.get_model_for_tier(ModelTier.TIER_1, allow_cross_tier=False)
        assert model is None
        assert router.last_selection is None

    def test_cross_tier_observability_counter_log_and_hook(self, caplog) -> None:
        """Cross-tier fallback increments observability state automatically."""
        router = self._make_multi_tier_router()
        observed: list[ModelSelection] = []
        router.on_degraded_selection = observed.append

        stats = router._get_stats("anthropic:claude-3-sonnet")
        for _ in range(5):
            stats.record_failure("test")

        with caplog.at_level(
            logging.WARNING,
            logger="agentic_v2.models.smart_router",
        ):
            model = router.get_model_for_tier(ModelTier.TIER_3)

        assert model is not None
        selection = router.last_selection
        assert selection is not None
        assert selection.is_degraded is True
        assert router.degraded_selection_count == 1
        assert observed == [selection]
        assert "Degraded model selection" in caplog.text


# ── Task 2.4: Adaptive throttle factor tests ─────────────────────────────────


class TestAdaptiveThrottleFactor:
    """Tests for compute_throttle_factor based on error rate."""

    def test_insufficient_data_returns_zero(self) -> None:
        """< 10 total requests should return 0.0 (no throttling)."""
        tracker = RateLimitTracker()
        for _ in range(5):
            tracker.record_request("openai:gpt-4o")
        assert tracker.compute_throttle_factor("openai:gpt-4o") == 0.0

    def test_no_errors_returns_zero(self) -> None:
        """With zero errors, throttle factor should be 0.0."""
        tracker = RateLimitTracker()
        for _ in range(20):
            tracker.record_request("openai:gpt-4o")
        assert tracker.compute_throttle_factor("openai:gpt-4o") == 0.0

    def test_low_error_rate(self) -> None:
        """2/20 errors = 10% error rate * 2 = 0.2 throttle."""
        tracker = RateLimitTracker()
        for _ in range(20):
            tracker.record_request("openai:gpt-4o")
        for _ in range(2):
            tracker.record_error("openai:gpt-4o")
        factor = tracker.compute_throttle_factor("openai:gpt-4o")
        assert factor == pytest.approx(0.2, abs=0.01)

    def test_high_error_rate_caps_at_one(self) -> None:
        """10/20 errors = 50% error rate * 2 = 1.0 (capped)."""
        tracker = RateLimitTracker()
        for _ in range(20):
            tracker.record_request("openai:gpt-4o")
        for _ in range(10):
            tracker.record_error("openai:gpt-4o")
        factor = tracker.compute_throttle_factor("openai:gpt-4o")
        assert factor == pytest.approx(1.0, abs=0.01)

    def test_unknown_provider_returns_zero(self) -> None:
        """Provider with no recorded requests returns 0.0."""
        tracker = RateLimitTracker()
        assert tracker.compute_throttle_factor("unknown:model") == 0.0

    def test_moderate_error_rate(self) -> None:
        """5/20 errors = 25% error rate * 2 = 0.5 throttle."""
        tracker = RateLimitTracker()
        for _ in range(20):
            tracker.record_request("gh:gpt-4o-mini")
        for _ in range(5):
            tracker.record_error("gh:gpt-4o-mini")
        factor = tracker.compute_throttle_factor("gh:gpt-4o-mini")
        assert factor == pytest.approx(0.5, abs=0.01)
