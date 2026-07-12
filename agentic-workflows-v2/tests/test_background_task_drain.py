"""Tests for SmartModelRouter background-task drain on shutdown.

Block #11 — verifies that fire-and-forget Redis save tasks are awaited
on graceful close, leaving no pending background tasks after drain.
"""

from __future__ import annotations

import asyncio

import pytest

from agentic_v2.models.smart_router import SmartModelRouter

try:
    import fakeredis

    _FAKEREDIS_AVAILABLE = True
except ImportError:
    _FAKEREDIS_AVAILABLE = False
    fakeredis = None  # type: ignore[assignment]

from agentic_v2.models.redis_state import RedisCircuitBreakerStore

skip_no_fakeredis = pytest.mark.skipif(
    not _FAKEREDIS_AVAILABLE,
    reason="fakeredis not installed",
)


async def _make_fake_store() -> RedisCircuitBreakerStore:
    """Create an in-memory Redis store backed by fakeredis."""
    fake_server = fakeredis.FakeServer()
    fake_client = fakeredis.FakeAsyncRedis(server=fake_server, decode_responses=True)
    store = RedisCircuitBreakerStore(
        redis_url="redis://fake",
        prefix="test:drain:",
        ttl_seconds=3600,
    )
    store._client = fake_client
    store._connected = True
    from agentic_v2.models.redis_state import _CAS_LUA_SCRIPT

    store._cas_sha = await fake_client.script_load(_CAS_LUA_SCRIPT)
    return store


# ---------------------------------------------------------------------------
# drain_background_tasks
# ---------------------------------------------------------------------------


@skip_no_fakeredis
@pytest.mark.asyncio
async def test_no_pending_tasks_after_drain() -> None:
    """drain_background_tasks() empties _background_tasks after real saves are queued.

    This test verifies the non-trivial pre/post contract:
    - recording events schedules at least one background save task (non-empty set),
    - drain awaits those tasks and leaves the set empty.
    """
    store = await _make_fake_store()

    # Use a barrier to hold save tasks in-flight until we are ready to drain,
    # ensuring the set is provably non-empty when we assert it.
    save_started = asyncio.Event()
    drain_allowed = asyncio.Event()
    original_save = store.save_stats_cas

    async def gated_save(*args: object, **kwargs: object) -> object:
        save_started.set()
        await drain_allowed.wait()
        return await original_save(*args, **kwargs)

    store.save_stats_cas = gated_save  # type: ignore[method-assign]

    router = SmartModelRouter(_redis_store=store, _auto_save=True)
    router._available_models.add("ollama:phi4")

    # Trigger fire-and-forget saves — these will block inside gated_save
    router.record_success("ollama:phi4", latency_ms=100.0)
    router.record_success("ollama:phi4", latency_ms=120.0)

    # Wait until at least one save task has started so the set is non-empty
    await save_started.wait()
    assert (
        len(router._background_tasks) > 0
    ), "_background_tasks must be non-empty before drain (proves the test is non-trivial)"

    # Release the gated saves and drain
    drain_allowed.set()
    await router.drain_background_tasks()

    assert len(router._background_tasks) == 0


@skip_no_fakeredis
@pytest.mark.asyncio
async def test_drain_is_idempotent_when_no_tasks() -> None:
    """drain_background_tasks() is safe when _background_tasks is empty."""
    router = SmartModelRouter()
    assert len(router._background_tasks) == 0

    # Should not raise
    await router.drain_background_tasks()
    assert len(router._background_tasks) == 0


@skip_no_fakeredis
@pytest.mark.asyncio
async def test_aclose_drains_tasks() -> None:
    """Aclose() delegates to drain_background_tasks() and empties the set."""
    store = await _make_fake_store()
    router = SmartModelRouter(_redis_store=store, _auto_save=True)
    router._available_models.add("ollama:phi4")

    router.record_failure("ollama:phi4", "connection_error")

    await router.aclose()

    assert len(router._background_tasks) == 0


@skip_no_fakeredis
@pytest.mark.asyncio
async def test_drain_awaits_slow_saves() -> None:
    """drain_background_tasks() awaits tasks that are still in-flight."""
    store = await _make_fake_store()
    completed: list[str] = []

    # Patch _save_stats_to_redis to be slow
    original = store.save_stats_cas

    async def slow_save(*args, **kwargs):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0.02)
        result = await original(*args, **kwargs)
        completed.append("saved")
        return result

    store.save_stats_cas = slow_save  # type: ignore[method-assign]

    router = SmartModelRouter(_redis_store=store, _auto_save=True)
    router._available_models.add("ollama:phi4")

    router.record_success("ollama:phi4", latency_ms=50.0)

    # Drain must wait for the slow save to finish
    await router.drain_background_tasks()

    assert len(router._background_tasks) == 0
    assert completed == ["saved"], "drain must await the slow save task"


@skip_no_fakeredis
@pytest.mark.asyncio
async def test_drain_tolerates_failing_background_task() -> None:
    """drain_background_tasks() does not propagate exceptions from tasks."""
    store = await _make_fake_store()

    async def failing_save(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("redis write failed")

    store.save_stats_cas = failing_save  # type: ignore[method-assign]

    router = SmartModelRouter(_redis_store=store, _auto_save=True)
    router._available_models.add("ollama:phi4")

    router.record_success("ollama:phi4", latency_ms=50.0)

    # Should not raise even though the task will fail
    await router.drain_background_tasks()

    assert len(router._background_tasks) == 0
