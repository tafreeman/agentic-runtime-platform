"""Unit tests for the pure helpers extracted from client.py (FIX #5).

Covers:
    cache_budget.py   — TokenBudget, CachedResponse
    retry_utils.py    — compute_retry_delay, retry_with_jitter
    fallback_selector.py — run_with_fallback
    sanitization_dispatch.py — sanitize_prompt, sanitize_messages,
                                sanitize_content_blocks,
                                sanitize_response_text,
                                sanitize_response_blocks
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# cache_budget
# ---------------------------------------------------------------------------
from agentic_v2.models.cache_budget import CachedResponse, TokenBudget


class TestTokenBudget:
    def test_remaining_starts_at_max(self) -> None:
        b = TokenBudget(max_tokens=1000)
        assert b.remaining == 1000

    def test_consume_reduces_remaining(self) -> None:
        b = TokenBudget(max_tokens=100)
        assert b.consume(40) is True
        assert b.remaining == 60

    def test_consume_returns_false_when_exceeded(self) -> None:
        b = TokenBudget(max_tokens=50)
        assert b.consume(60) is False
        assert b.remaining == 50  # not consumed

    def test_can_afford_true(self) -> None:
        b = TokenBudget(max_tokens=100, used_tokens=30)
        assert b.can_afford(70) is True

    def test_can_afford_false(self) -> None:
        b = TokenBudget(max_tokens=100, used_tokens=90)
        assert b.can_afford(20) is False

    def test_percentage_used(self) -> None:
        b = TokenBudget(max_tokens=200, used_tokens=50)
        assert b.percentage_used == 25.0

    def test_percentage_used_zero_max(self) -> None:
        b = TokenBudget(max_tokens=0)
        assert b.percentage_used == 100.0

    def test_remaining_floored_at_zero(self) -> None:
        b = TokenBudget(max_tokens=10, used_tokens=15)
        assert b.remaining == 0


class TestCachedResponse:
    def test_age_seconds_increases_over_time(self) -> None:
        ts = datetime.now(UTC)
        cr = CachedResponse(response="ok", model="m", timestamp=ts, tokens_used=5)
        assert cr.age_seconds >= 0.0


# ---------------------------------------------------------------------------
# retry_utils — compute_retry_delay
# ---------------------------------------------------------------------------
from agentic_v2.models.retry_utils import compute_retry_delay


class FakePermanentError(Exception):
    pass


class FakeTransientError(Exception):
    pass


def _patch_classify(monkeypatch, error_code: str, should_retry: bool) -> None:
    """Patch core.errors.classify_error for isolated retry_utils tests."""

    def fake_classify(msg: str):  # type: ignore[misc]
        from agentic_v2.core.errors import ErrorCode

        return ErrorCode(error_code), should_retry

    monkeypatch.setattr(
        "agentic_v2.models.retry_utils.compute_retry_delay.__globals__",
        {},
        raising=False,
    )
    import agentic_v2.core.errors as err_mod

    monkeypatch.setattr(err_mod, "classify_error", fake_classify)


class TestComputeRetryDelay:
    def test_permanent_error_reraises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from agentic_v2.core.errors import ErrorCode

        def fake_classify(msg: str):
            return ErrorCode.AUTH_ERROR, False  # permanent

        import agentic_v2.core.errors as err_mod

        monkeypatch.setattr(err_mod, "classify_error", fake_classify)

        err = FakePermanentError("permanent")
        with pytest.raises(FakePermanentError):
            compute_retry_delay(
                err,
                attempt=0,
                max_retries=3,
                base_delay=1.0,
                max_delay=30.0,
                jitter=0.0,
                func_name="test",
            )

    def test_transient_error_returns_positive_delay(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agentic_v2.core.errors import ErrorCode

        def fake_classify(msg: str):
            return ErrorCode.TRANSIENT, True

        import agentic_v2.core.errors as err_mod

        monkeypatch.setattr(err_mod, "classify_error", fake_classify)

        delay = compute_retry_delay(
            FakeTransientError("transient"),
            attempt=0,
            max_retries=3,
            base_delay=1.0,
            max_delay=30.0,
            jitter=0.0,
            func_name="test",
        )
        assert delay >= 1.0

    def test_delay_respects_max_delay(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from agentic_v2.core.errors import ErrorCode

        def fake_classify(msg: str):
            return ErrorCode.TRANSIENT, True

        import agentic_v2.core.errors as err_mod

        monkeypatch.setattr(err_mod, "classify_error", fake_classify)

        # attempt=10 would give base*2^10=1024, capped at max_delay=5
        delay = compute_retry_delay(
            FakeTransientError(),
            attempt=10,
            max_retries=20,
            base_delay=1.0,
            max_delay=5.0,
            jitter=0.0,
            func_name="test",
        )
        assert delay <= 5.0


# ---------------------------------------------------------------------------
# retry_utils — retry_with_jitter decorator
# ---------------------------------------------------------------------------
from agentic_v2.models.retry_utils import retry_with_jitter


class TestRetryWithJitter:
    @pytest.mark.asyncio
    async def test_returns_on_first_success(self) -> None:
        calls: list[int] = []

        @retry_with_jitter(max_retries=3, base_delay=0.0)
        async def fn() -> str:
            calls.append(1)
            return "ok"

        result = await fn()
        assert result == "ok"
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_succeeds_after_one_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agentic_v2.core.errors import ErrorCode

        def fake_classify(msg: str):
            return ErrorCode.TRANSIENT, True

        import agentic_v2.core.errors as err_mod

        monkeypatch.setattr(err_mod, "classify_error", fake_classify)
        monkeypatch.setattr("asyncio.sleep", AsyncMock())

        calls: list[int] = []

        @retry_with_jitter(max_retries=3, base_delay=0.001)
        async def fn() -> str:
            calls.append(1)
            if len(calls) == 1:
                raise FakeTransientError("first attempt fails")
            return "recovered"

        result = await fn()
        assert result == "recovered"
        assert len(calls) == 2


# ---------------------------------------------------------------------------
# fallback_selector — run_with_fallback
# ---------------------------------------------------------------------------
from agentic_v2.models.fallback_selector import run_with_fallback
from agentic_v2.models.router import ModelTier
from agentic_v2.models.smart_router import SmartModelRouter


class TestRunWithFallback:
    def _make_router(self, models: list[str]) -> SmartModelRouter:
        router = SmartModelRouter()
        for m in models:
            router._available_models.add(m)
        return router

    @pytest.mark.asyncio
    async def test_returns_first_success(self) -> None:
        router = self._make_router(["m1"])
        router.get_model_for_tier = MagicMock(return_value="m1")

        async def attempt(m: str) -> str:
            return f"ok-{m}"

        result = await run_with_fallback(
            router,
            tier=ModelTier.TIER_2,
            model=None,
            max_retries=3,
            pre_attempt=lambda m: None,
            attempt=attempt,
            on_error=lambda m, e: None,
        )
        assert result == "ok-m1"

    @pytest.mark.asyncio
    async def test_circuit_resolved_skips_without_recording_failure(self) -> None:
        """CircuitResolvedError must not be treated as a model failure.

        PR #74 review: a prior probe resolving the HALF_OPEN circuit means
        the model is healthy (or freshly re-opened) — on_error must not run
        (no failure recorded against a healthy model) and the loop moves to
        the next candidate, mirroring call_with_fallback.
        """
        from agentic_v2.models.model_stats import CircuitState
        from agentic_v2.models.smart_router import CircuitResolvedError

        router = SmartModelRouter()
        candidates = iter(["m1", "m2"])
        router.get_model_for_tier = lambda tier: next(candidates, None)

        errors: list[tuple[str, Exception]] = []

        async def attempt(m: str) -> str:
            if m == "m1":
                raise CircuitResolvedError("m1", CircuitState.CLOSED)
            return f"ok-{m}"

        result = await run_with_fallback(
            router,
            tier=ModelTier.TIER_2,
            model=None,
            max_retries=3,
            pre_attempt=lambda m: None,
            attempt=attempt,
            on_error=lambda m, e: errors.append((m, e)),
        )
        assert result == "ok-m2"
        assert errors == [], "circuit-resolved skip must not record a failure"

    @pytest.mark.asyncio
    async def test_raises_last_error_when_all_fail(self) -> None:
        router = SmartModelRouter()
        call_count = 0

        def get_model(tier: ModelTier):
            nonlocal call_count
            call_count += 1
            return "m1" if call_count == 1 else "m2" if call_count == 2 else None

        router.get_model_for_tier = get_model

        async def always_fail(m: str) -> str:
            raise RuntimeError(f"fail-{m}")

        with pytest.raises(RuntimeError, match="fail-"):
            await run_with_fallback(
                router,
                tier=ModelTier.TIER_2,
                model=None,
                max_retries=2,
                pre_attempt=lambda m: None,
                attempt=always_fail,
                on_error=lambda m, e: None,
            )

    @pytest.mark.asyncio
    async def test_no_model_available_raises_runtime_error(self) -> None:
        router = SmartModelRouter()
        router.get_model_for_tier = MagicMock(return_value=None)

        with pytest.raises(RuntimeError, match="All models failed"):
            await run_with_fallback(
                router,
                tier=ModelTier.TIER_2,
                model=None,
                max_retries=1,
                pre_attempt=lambda m: None,
                attempt=lambda m: ...,  # type: ignore[arg-type]
                on_error=lambda m, e: None,
            )

    @pytest.mark.asyncio
    async def test_pre_attempt_exception_propagates(self) -> None:
        router = SmartModelRouter()
        router.get_model_for_tier = MagicMock(return_value="m1")

        def raise_budget_error(m: str) -> None:
            raise ValueError("budget exceeded")

        with pytest.raises(ValueError, match="budget exceeded"):
            await run_with_fallback(
                router,
                tier=ModelTier.TIER_2,
                model=None,
                max_retries=1,
                pre_attempt=raise_budget_error,
                attempt=lambda m: ...,  # type: ignore[arg-type]
                on_error=lambda m, e: None,
            )


# ---------------------------------------------------------------------------
# sanitization_dispatch
# ---------------------------------------------------------------------------
from agentic_v2.models.sanitization_dispatch import (
    sanitize_content_blocks,
    sanitize_messages,
    sanitize_prompt,
    sanitize_response_blocks,
    sanitize_response_text,
)


class FakeSanitizationResult:
    def __init__(self, safe: bool, sanitized: str | None = None) -> None:
        class FakeClass:
            value = "unsafe"

        self.is_safe = safe
        self.classification = FakeClass()
        self.sanitized_text = sanitized


class FakeSanitizationMiddleware:
    def __init__(self, safe: bool, rewrite: str | None = None) -> None:
        self._safe = safe
        self._rewrite = rewrite

    async def process(self, text: str, ctx: dict[str, Any]) -> FakeSanitizationResult:
        return FakeSanitizationResult(self._safe, self._rewrite)


class FakeResponseSanitizer:
    def __init__(self, rewrite: str | None = None) -> None:
        self._rewrite = rewrite

    async def sanitize_response(self, text: str) -> FakeSanitizationResult:
        return FakeSanitizationResult(safe=True, sanitized=self._rewrite)


class TestSanitizePrompt:
    @pytest.mark.asyncio
    async def test_noop_when_no_sanitizer(self) -> None:
        result = await sanitize_prompt(
            "hello", source="s", tier=ModelTier.TIER_2, sanitization=None
        )
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_returns_rewritten_text(self) -> None:
        san = FakeSanitizationMiddleware(safe=True, rewrite="cleaned")
        result = await sanitize_prompt(
            "original", source="s", tier=ModelTier.TIER_2, sanitization=san
        )
        assert result == "cleaned"

    @pytest.mark.asyncio
    async def test_raises_on_unsafe(self) -> None:
        san = FakeSanitizationMiddleware(safe=False)
        with pytest.raises(ValueError, match="blocked"):
            await sanitize_prompt(
                "bad input", source="s", tier=ModelTier.TIER_2, sanitization=san
            )


class TestSanitizeMessages:
    @pytest.mark.asyncio
    async def test_noop_when_no_sanitizer(self) -> None:
        messages = [{"role": "user", "content": "hello"}]
        result = await sanitize_messages(
            messages, source="s", tier=ModelTier.TIER_2, sanitization=None
        )
        assert result == messages

    @pytest.mark.asyncio
    async def test_rewrites_string_content(self) -> None:
        san = FakeSanitizationMiddleware(safe=True, rewrite="cleaned")
        messages = [{"role": "user", "content": "original"}]
        result = await sanitize_messages(
            messages, source="s", tier=ModelTier.TIER_2, sanitization=san
        )
        assert result[0]["content"] == "cleaned"

    @pytest.mark.asyncio
    async def test_passes_through_non_string_content(self) -> None:
        san = FakeSanitizationMiddleware(safe=True, rewrite="cleaned")
        messages = [{"role": "tool", "content": None}]
        result = await sanitize_messages(
            messages, source="s", tier=ModelTier.TIER_2, sanitization=san
        )
        assert result[0]["content"] is None


class TestSanitizeContentBlocks:
    @pytest.mark.asyncio
    async def test_rewrites_text_blocks(self) -> None:
        san = FakeSanitizationMiddleware(safe=True, rewrite="safe")
        blocks: list[Any] = [{"type": "text", "text": "raw"}]
        cleaned, mutated = await sanitize_content_blocks(
            blocks, source="s", tier=ModelTier.TIER_2, sanitization=san
        )
        assert mutated is True
        assert cleaned[0]["text"] == "safe"

    @pytest.mark.asyncio
    async def test_passes_through_non_text_blocks(self) -> None:
        san = FakeSanitizationMiddleware(safe=True, rewrite="safe")
        blocks: list[Any] = [{"type": "image", "url": "http://x"}]
        cleaned, mutated = await sanitize_content_blocks(
            blocks, source="s", tier=ModelTier.TIER_2, sanitization=san
        )
        assert mutated is False
        assert cleaned == blocks


class TestSanitizeResponseText:
    @pytest.mark.asyncio
    async def test_noop_when_no_sanitizer(self) -> None:
        result = await sanitize_response_text("hello", response_sanitizer=None)
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_rewrites_text(self) -> None:
        san = FakeResponseSanitizer(rewrite="redacted")
        result = await sanitize_response_text("secret", response_sanitizer=san)
        assert result == "redacted"


class TestSanitizeResponseBlocks:
    @pytest.mark.asyncio
    async def test_rewrites_text_blocks(self) -> None:
        san = FakeResponseSanitizer(rewrite="safe")
        blocks: list[Any] = [{"type": "text", "text": "raw"}]
        result = await sanitize_response_blocks(blocks, response_sanitizer=san)
        assert result[0]["text"] == "safe"

    @pytest.mark.asyncio
    async def test_passes_through_non_text_blocks(self) -> None:
        blocks: list[Any] = [{"type": "image", "url": "http://x"}]
        result = await sanitize_response_blocks(blocks, response_sanitizer=None)
        assert result == blocks
