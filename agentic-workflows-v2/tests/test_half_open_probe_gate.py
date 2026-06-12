"""Concurrency tests for the HALF_OPEN single-probe invariant.

Block #10 — verifies that exactly ONE probe call reaches the provider when
N callers race against a model whose recovery timeout just elapsed.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from agentic_v2.models.model_stats import CircuitState, ModelStats
from agentic_v2.models.router import FallbackChain, ModelTier
from agentic_v2.models.smart_router import SmartModelRouter, CircuitResolvedError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_open_router(model: str = "test:model") -> SmartModelRouter:
    """Return a SmartModelRouter with `model` in OPEN state ready to tip to HALF_OPEN."""
    router = SmartModelRouter()
    router.register_chain(
        ModelTier.TIER_1, FallbackChain((model,), "test-chain")
    )
    # Make the model available to routing
    router._available_models.add(model)

    stats = router._get_stats(model)
    # Drive to OPEN state
    for _ in range(stats._failure_threshold + 1):
        stats.record_failure("error")
    assert stats.circuit_state == CircuitState.OPEN
    # Backdate last_failure so recovery timeout has elapsed
    stats._last_failure_mono = time.monotonic() - (stats._recovery_timeout_seconds + 1)
    stats._last_failure_time = None  # force monotonic path
    return router


# ---------------------------------------------------------------------------
# Unit — ModelStats.check_circuit HALF_OPEN behavior
# ---------------------------------------------------------------------------


class TestCheckCircuitHalfOpen:
    """ModelStats.check_circuit() gating in HALF_OPEN state."""

    def test_half_open_allows_first_check(self) -> None:
        """First check_circuit in HALF_OPEN with no probe returns True."""
        stats = ModelStats(model_id="test")
        stats.circuit_state = CircuitState.HALF_OPEN
        stats.probe_in_progress = False
        assert stats.check_circuit() is True

    def test_half_open_blocks_when_probe_in_progress(self) -> None:
        """check_circuit returns False when a probe is already in-flight."""
        stats = ModelStats(model_id="test")
        stats.circuit_state = CircuitState.HALF_OPEN
        stats.probe_in_progress = True
        assert stats.check_circuit() is False

    def test_check_circuit_transitions_to_half_open(self) -> None:
        """OPEN→HALF_OPEN transition still works as before."""
        stats = ModelStats(model_id="test")
        for _ in range(stats._failure_threshold + 1):
            stats.record_failure("error")
        assert stats.circuit_state == CircuitState.OPEN

        stats._last_failure_mono = time.monotonic() - (stats._recovery_timeout_seconds + 1)
        result = stats.check_circuit()

        assert result is True
        assert stats.circuit_state == CircuitState.HALF_OPEN
        # probe_in_progress is NOT set by check_circuit itself — only by execute_with_bulkhead
        assert stats.probe_in_progress is False


# ---------------------------------------------------------------------------
# Concurrency — single probe under N concurrent callers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exactly_one_probe_reaches_provider() -> None:
    """N concurrent callers: exactly 1 reaches the provider before circuit resolves.

    Spec (block #10): "a concurrent test with N callers against a model whose
    recovery timeout just elapsed shows exactly ONE probe call reaches the
    provider before the circuit resolves."
    """
    model = "test:model"
    router = _make_open_router(model)

    # Tip the model to HALF_OPEN so callers see it as a candidate
    stats = router._get_stats(model)
    result = stats.check_circuit()
    assert result is True
    assert stats.circuit_state == CircuitState.HALF_OPEN

    probe_count = 0
    barrier = asyncio.Barrier(8)  # synchronise 8 callers to maximise contention

    async def fake_provider(m: str, prompt: str) -> str:
        nonlocal probe_count
        probe_count += 1
        # Simulate a successful probe response
        await asyncio.sleep(0.01)
        return f"ok-from-{m}"

    async def caller() -> None:
        await barrier.wait()
        try:
            await router._execute_call(fake_provider, model, "hello")
        except CircuitResolvedError:
            # Expected: probe was already taken by another caller
            pass

    tasks = [asyncio.create_task(caller()) for _ in range(8)]
    await asyncio.gather(*tasks)

    assert probe_count == 1, (
        f"Expected exactly 1 probe call to reach the provider, got {probe_count}"
    )


@pytest.mark.asyncio
async def test_probe_in_progress_flag_cleared_after_probe() -> None:
    """probe_in_progress is False after execute_with_bulkhead completes."""
    model = "test:model"
    router = _make_open_router(model)
    stats = router._get_stats(model)
    stats.check_circuit()  # tip to HALF_OPEN
    assert stats.circuit_state == CircuitState.HALF_OPEN

    async def fast_provider(m: str, prompt: str) -> str:
        return "ok"

    await router._execute_call(fast_provider, model, "ping")

    assert stats.probe_in_progress is False


@pytest.mark.asyncio
async def test_probe_in_progress_cleared_on_probe_failure() -> None:
    """probe_in_progress is cleared even when the probe raises an exception."""
    model = "test:model"
    router = _make_open_router(model)
    stats = router._get_stats(model)
    stats.check_circuit()  # tip to HALF_OPEN
    assert stats.circuit_state == CircuitState.HALF_OPEN

    async def failing_provider(m: str, prompt: str) -> str:
        raise ValueError("provider error")

    with pytest.raises(ValueError, match="provider error"):
        await router._execute_call(failing_provider, model, "ping")

    assert stats.probe_in_progress is False


@pytest.mark.asyncio
async def test_circuit_resolved_error_not_raised_for_closed_circuit() -> None:
    """execute_with_bulkhead does not raise CircuitResolvedError for CLOSED circuit."""
    router = SmartModelRouter()
    model = "test:model"
    router._available_models.add(model)
    stats = router._get_stats(model)
    assert stats.circuit_state == CircuitState.CLOSED

    probe_count = 0

    async def counter_provider(m: str, prompt: str) -> str:
        nonlocal probe_count
        probe_count += 1
        return "ok"

    result = await router._execute_call(counter_provider, model, "ping")
    assert result == "ok"
    assert probe_count == 1


@pytest.mark.asyncio
async def test_call_with_fallback_does_not_record_failure_on_circuit_resolved() -> None:
    """call_with_fallback skips CircuitResolvedError without recording a failure.

    When a probe slot is already taken, the call is not a failure — it's a
    routing signal. The failure_count should not increase.
    """
    model = "test:model"
    router = _make_open_router(model)
    stats = router._get_stats(model)
    stats.check_circuit()  # tip to HALF_OPEN

    initial_failures = stats.failure_count

    async def probe_provider(m: str, prompt: str) -> str:
        return "ok"

    # The first (and only) probe succeeds
    used_model, response = await router.call_with_fallback(
        probe_provider, "hello", ModelTier.TIER_1
    )
    assert used_model == model
    assert response == "ok"
    # No spurious failure recorded
    assert stats.failure_count == initial_failures
