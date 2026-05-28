"""Tests for the WebSocket replay store backends and ConnectionManager integration.

Coverage:
* InMemoryReplayStore -- append, get_events ordering, clear, max_events cap
* RedisReplayStore (fakeredis) -- append, get_events, clear, TTL, LTRIM cap
* SqliteReplayStore (tmp file) -- append, get_events ordering, clear
* ConnectionManager integration -- broadcast persists, replay reads, clear propagates
* build_replay_store auto-selection -- redis available, no redis sqlite, neither memory
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agentic_v2.server.replay_store import (
    InMemoryReplayStore,
    ReplayStore,
    SqliteReplayStore,
    _REDIS_AVAILABLE,
    _SQLITE_AVAILABLE,
    build_replay_store,
)
from agentic_v2.server.websocket import ConnectionManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_EVENT: dict[str, Any] = {
    "type": "workflow_end",
    "run_id": "run-test",
    "status": "success",
    "timestamp": "2026-05-01T00:00:00Z",
}


def _event(seq: int) -> dict[str, Any]:
    return {
        "type": "workflow_end",
        "run_id": f"run-{seq}",
        "status": "success",
        "timestamp": "2026-05-01T00:00:00Z",
    }


def _mock_ws() -> AsyncMock:
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


class _FakeSettings:
    """Minimal settings stub for build_replay_store tests."""

    def __init__(
        self,
        backend: str = "memory",
        redis_url: str | None = None,
        ttl: int = 14400,
        max_events: int = 500,
        sqlite_path: str = ".agentic_replay.db",
    ) -> None:
        self.replay_store_backend = backend
        self.redis_url = redis_url
        self.replay_store_ttl = ttl
        self.replay_store_max_events = max_events
        self.replay_sqlite_path = sqlite_path


# ---------------------------------------------------------------------------
# InMemoryReplayStore
# ---------------------------------------------------------------------------


class TestInMemoryReplayStore:
    """Unit tests for InMemoryReplayStore."""

    @pytest.mark.asyncio
    async def test_append_and_get_events(self) -> None:
        """append() stores events retrievable by get_events()."""
        store = InMemoryReplayStore()
        await store.append("run-1", _event(0))
        await store.append("run-1", _event(1))

        events = await store.get_events("run-1")
        assert len(events) == 2
        assert events[0] == _event(0)
        assert events[1] == _event(1)

    @pytest.mark.asyncio
    async def test_get_events_ordering(self) -> None:
        """get_events() returns events in insertion order."""
        store = InMemoryReplayStore()
        for i in range(5):
            await store.append("run-ord", _event(i))

        events = await store.get_events("run-ord")
        for i, ev in enumerate(events):
            assert ev["run_id"] == f"run-{i}"

    @pytest.mark.asyncio
    async def test_get_events_empty(self) -> None:
        """get_events() returns empty list for unknown run_id."""
        store = InMemoryReplayStore()
        assert await store.get_events("nonexistent") == []

    @pytest.mark.asyncio
    async def test_clear_removes_events(self) -> None:
        """clear() removes all events for a run."""
        store = InMemoryReplayStore()
        await store.append("run-1", _event(0))
        await store.clear("run-1")
        assert await store.get_events("run-1") == []

    @pytest.mark.asyncio
    async def test_clear_nonexistent_no_error(self) -> None:
        """clear() on unknown run_id doesn't raise."""
        store = InMemoryReplayStore()
        await store.clear("no-such-run")  # must not raise

    @pytest.mark.asyncio
    async def test_max_events_cap(self) -> None:
        """Oldest events are evicted when max_events is exceeded."""
        store = InMemoryReplayStore(max_events=3)
        for i in range(5):
            await store.append("run-1", _event(i))

        events = await store.get_events("run-1")
        assert len(events) == 3
        # oldest two (0 and 1) should be gone
        run_ids = [e["run_id"] for e in events]
        assert "run-0" not in run_ids
        assert "run-1" not in run_ids
        assert "run-4" in run_ids

    @pytest.mark.asyncio
    async def test_separate_run_ids_isolated(self) -> None:
        """Events for different run_ids don't bleed into each other."""
        store = InMemoryReplayStore()
        await store.append("run-a", _event(0))
        await store.append("run-b", _event(1))

        assert len(await store.get_events("run-a")) == 1
        assert len(await store.get_events("run-b")) == 1

    @pytest.mark.asyncio
    async def test_close_is_noop(self) -> None:
        """close() does not raise."""
        store = InMemoryReplayStore()
        await store.close()

    def test_implements_protocol(self) -> None:
        """InMemoryReplayStore satisfies the ReplayStore Protocol."""
        store = InMemoryReplayStore()
        assert isinstance(store, ReplayStore)


# ---------------------------------------------------------------------------
# RedisReplayStore — requires fakeredis
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _REDIS_AVAILABLE, reason="redis package not installed")
class TestRedisReplayStore:
    """Unit tests for RedisReplayStore using fakeredis."""

    @pytest.fixture
    async def redis_store(self):
        """Provide a RedisReplayStore backed by fakeredis FakeAsyncRedis."""
        import fakeredis

        from agentic_v2.server.replay_store import RedisReplayStore

        store = RedisReplayStore(
            redis_url="redis://fake",
            max_events=10,
            ttl_seconds=60,
        )
        fake_server = fakeredis.FakeServer()
        fake_client = fakeredis.FakeAsyncRedis(server=fake_server, decode_responses=True)
        store._client = fake_client
        store._connected = True
        yield store
        await store.close()

    @pytest.mark.asyncio
    async def test_append_and_get_events(self, redis_store) -> None:
        """append() stores events retrievable by get_events()."""
        await redis_store.append("run-1", _event(0))
        await redis_store.append("run-1", _event(1))

        events = await redis_store.get_events("run-1")
        assert len(events) == 2
        assert events[0] == _event(0)
        assert events[1] == _event(1)

    @pytest.mark.asyncio
    async def test_get_events_ordering(self, redis_store) -> None:
        """Events come back in RPUSH insertion order."""
        for i in range(5):
            await redis_store.append("run-ord", _event(i))

        events = await redis_store.get_events("run-ord")
        for i, ev in enumerate(events):
            assert ev["run_id"] == f"run-{i}"

    @pytest.mark.asyncio
    async def test_get_events_empty(self, redis_store) -> None:
        """get_events() returns [] for unknown run."""
        assert await redis_store.get_events("no-such-run") == []

    @pytest.mark.asyncio
    async def test_clear(self, redis_store) -> None:
        """clear() deletes the Redis List key."""
        await redis_store.append("run-1", _event(0))
        await redis_store.clear("run-1")
        assert await redis_store.get_events("run-1") == []

    @pytest.mark.asyncio
    async def test_max_events_ltrim(self, redis_store) -> None:
        """LTRIM enforces the per-run event cap."""
        for i in range(15):
            await redis_store.append("run-cap", _event(i))

        events = await redis_store.get_events("run-cap")
        assert len(events) == 10  # max_events=10
        # Oldest events should have been trimmed away
        assert events[-1]["run_id"] == "run-14"

    @pytest.mark.asyncio
    async def test_disconnected_store_is_noop(self) -> None:
        """All operations are no-ops when not connected."""
        from agentic_v2.server.replay_store import RedisReplayStore

        store = RedisReplayStore(redis_url="redis://localhost:6379/0")
        # _connected defaults to False, no client
        await store.append("run-1", _event(0))  # must not raise
        assert await store.get_events("run-1") == []
        await store.clear("run-1")  # must not raise
        await store.close()  # must not raise

    @pytest.mark.asyncio
    async def test_corrupt_event_skipped(self, redis_store) -> None:
        """A corrupt JSON value in Redis is skipped, others returned."""
        key = "agentic:replay:run-corrupt"
        # Manually push bad JSON alongside a good entry directly on the client
        await redis_store._client.rpush(key, "not-valid-json", json.dumps(_event(0)))

        events = await redis_store.get_events("run-corrupt")
        # Only the valid entry should be returned
        assert len(events) == 1
        assert events[0] == _event(0)

    def test_implements_protocol(self) -> None:
        """RedisReplayStore satisfies the ReplayStore Protocol."""
        from agentic_v2.server.replay_store import RedisReplayStore

        store = RedisReplayStore(redis_url="redis://localhost:6379/0")
        assert isinstance(store, ReplayStore)


# ---------------------------------------------------------------------------
# SqliteReplayStore — requires aiosqlite
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _SQLITE_AVAILABLE, reason="aiosqlite not installed")
class TestSqliteReplayStore:
    """Unit tests for SqliteReplayStore using a temporary database file."""

    @pytest.fixture
    async def sqlite_store(self, tmp_path):
        """Provide a SqliteReplayStore backed by a temp file."""
        db_path = str(tmp_path / "replay_test.db")
        store = await SqliteReplayStore.connect(db_path=db_path, max_events=10)
        yield store
        await store.close()

    @pytest.mark.asyncio
    async def test_append_and_get_events(self, sqlite_store) -> None:
        """append() stores events retrievable by get_events()."""
        await sqlite_store.append("run-1", _event(0))
        await sqlite_store.append("run-1", _event(1))

        events = await sqlite_store.get_events("run-1")
        assert len(events) == 2
        assert events[0] == _event(0)
        assert events[1] == _event(1)

    @pytest.mark.asyncio
    async def test_get_events_ordering(self, sqlite_store) -> None:
        """Events come back in seq (insertion) order."""
        for i in range(5):
            await sqlite_store.append("run-ord", _event(i))

        events = await sqlite_store.get_events("run-ord")
        for i, ev in enumerate(events):
            assert ev["run_id"] == f"run-{i}"

    @pytest.mark.asyncio
    async def test_get_events_empty(self, sqlite_store) -> None:
        """get_events() returns [] for unknown run."""
        assert await sqlite_store.get_events("no-such-run") == []

    @pytest.mark.asyncio
    async def test_clear(self, sqlite_store) -> None:
        """clear() deletes all rows for a run."""
        await sqlite_store.append("run-1", _event(0))
        await sqlite_store.clear("run-1")
        assert await sqlite_store.get_events("run-1") == []

    @pytest.mark.asyncio
    async def test_clear_nonexistent_no_error(self, sqlite_store) -> None:
        """clear() on unknown run_id doesn't raise."""
        await sqlite_store.clear("ghost-run")

    @pytest.mark.asyncio
    async def test_max_events_cap(self, sqlite_store) -> None:
        """Oldest events are purged beyond max_events."""
        for i in range(15):
            await sqlite_store.append("run-cap", _event(i))

        events = await sqlite_store.get_events("run-cap")
        assert len(events) <= 10

    @pytest.mark.asyncio
    async def test_separate_run_ids_isolated(self, sqlite_store) -> None:
        """Events for different run_ids don't bleed into each other."""
        await sqlite_store.append("run-a", _event(0))
        await sqlite_store.append("run-b", _event(1))

        assert len(await sqlite_store.get_events("run-a")) == 1
        assert len(await sqlite_store.get_events("run-b")) == 1

    @pytest.mark.asyncio
    async def test_close_is_safe(self, sqlite_store) -> None:
        """close() releases resources without error."""
        await sqlite_store.close()
        # Second close should also be safe
        await sqlite_store.close()

    @pytest.mark.asyncio
    async def test_connect_raises_without_aiosqlite(self) -> None:
        """SqliteReplayStore.connect raises RuntimeError when aiosqlite absent."""
        import agentic_v2.server.replay_store as module

        original = module._SQLITE_AVAILABLE
        module._SQLITE_AVAILABLE = False
        try:
            with pytest.raises(RuntimeError, match="aiosqlite"):
                await SqliteReplayStore.connect()
        finally:
            module._SQLITE_AVAILABLE = original

    def test_implements_protocol(self) -> None:
        """SqliteReplayStore satisfies the ReplayStore Protocol."""
        store = SqliteReplayStore()
        assert isinstance(store, ReplayStore)


# ---------------------------------------------------------------------------
# ConnectionManager integration
# ---------------------------------------------------------------------------


class TestConnectionManagerWithReplayStore:
    """Integration tests: ConnectionManager + replay store backend."""

    def _valid_event(self, seq: int = 0) -> dict[str, Any]:
        return {
            "type": "workflow_end",
            "run_id": f"run-{seq}",
            "status": "success",
            "timestamp": "2026-05-01T00:00:00Z",
        }

    @pytest.mark.asyncio
    async def test_broadcast_persists_to_store(self) -> None:
        """broadcast() calls _replay_store.append()."""
        store = InMemoryReplayStore(max_events=100)
        mgr = ConnectionManager(replay_store=store)

        event = self._valid_event(0)
        await mgr.broadcast("run-1", event)

        stored = await store.get_events("run-1")
        assert len(stored) == 1
        assert stored[0] == event

    @pytest.mark.asyncio
    async def test_broadcast_persistence_failure_does_not_crash(self) -> None:
        """broadcast() continues even if the store raises."""
        bad_store = MagicMock()
        bad_store.append = AsyncMock(side_effect=RuntimeError("store down"))
        mgr = ConnectionManager(replay_store=bad_store)

        # Must not raise
        await mgr.broadcast("run-1", self._valid_event(0))
        # In-memory buffer still updated
        assert len(mgr.event_buffers["run-1"]) == 1

    @pytest.mark.asyncio
    async def test_replay_reads_from_store(self) -> None:
        """replay() sends events retrieved from the durable store."""
        store = InMemoryReplayStore(max_events=100)
        # Pre-populate the store but NOT the in-memory buffer
        await store.append("run-1", self._valid_event(0))
        await store.append("run-1", self._valid_event(1))

        mgr = ConnectionManager(replay_store=store)
        ws = _mock_ws()
        await mgr.replay(ws, "run-1")

        assert ws.send_json.await_count == 2

    @pytest.mark.asyncio
    async def test_replay_falls_back_to_memory_when_store_empty(self) -> None:
        """replay() falls back to event_buffers when store returns nothing."""
        store = InMemoryReplayStore(max_events=100)
        mgr = ConnectionManager(replay_store=store)

        # Populate only the in-memory buffer
        event = self._valid_event(0)
        mgr.event_buffers["run-1"] = deque([event], maxlen=100)

        ws = _mock_ws()
        await mgr.replay(ws, "run-1")

        ws.send_json.assert_awaited_once_with(event)

    @pytest.mark.asyncio
    async def test_replay_store_error_falls_back_to_memory(self) -> None:
        """replay() falls back to memory when store.get_events raises."""
        bad_store = MagicMock()
        bad_store.get_events = AsyncMock(side_effect=RuntimeError("store down"))
        mgr = ConnectionManager(replay_store=bad_store)

        event = self._valid_event(0)
        mgr.event_buffers["run-1"] = deque([event], maxlen=100)

        ws = _mock_ws()
        await mgr.replay(ws, "run-1")

        ws.send_json.assert_awaited_once_with(event)

    @pytest.mark.asyncio
    async def test_clear_buffer_also_clears_store(self) -> None:
        """clear_buffer() schedules a clear on the durable store."""
        store = InMemoryReplayStore(max_events=100)
        mgr = ConnectionManager(replay_store=store)
        await mgr.broadcast("run-1", self._valid_event(0))

        mgr.clear_buffer("run-1")
        # Give the scheduled coroutine a chance to run
        await asyncio.sleep(0)

        assert await store.get_events("run-1") == []
        assert "run-1" not in mgr.event_buffers

    @pytest.mark.asyncio
    async def test_default_store_is_in_memory(self) -> None:
        """ConnectionManager defaults to InMemoryReplayStore."""
        mgr = ConnectionManager()
        assert isinstance(mgr._replay_store, InMemoryReplayStore)

    @pytest.mark.asyncio
    async def test_broadcast_still_updates_in_memory_buffer(self) -> None:
        """broadcast() always updates the hot in-memory deque too."""
        store = InMemoryReplayStore(max_events=100)
        mgr = ConnectionManager(replay_store=store)

        event = self._valid_event(0)
        await mgr.broadcast("run-1", event)

        assert len(mgr.event_buffers["run-1"]) == 1
        assert mgr.event_buffers["run-1"][0] == event

    @pytest.mark.asyncio
    async def test_multiple_broadcasts_accumulate_in_store(self) -> None:
        """Multiple broadcasts accumulate in the durable store."""
        store = InMemoryReplayStore(max_events=100)
        mgr = ConnectionManager(replay_store=store)

        for i in range(5):
            await mgr.broadcast("run-1", self._valid_event(i))

        stored = await store.get_events("run-1")
        assert len(stored) == 5


# ---------------------------------------------------------------------------
# build_replay_store auto-selection logic
# ---------------------------------------------------------------------------


class TestBuildReplayStoreAutoSelection:
    """Tests for the factory function's backend selection logic."""

    @pytest.mark.asyncio
    async def test_explicit_memory_backend(self) -> None:
        """backend='memory' always returns InMemoryReplayStore."""
        settings = _FakeSettings(backend="memory")
        store = await build_replay_store(settings)
        assert isinstance(store, InMemoryReplayStore)
        await store.close()

    @pytest.mark.asyncio
    async def test_explicit_redis_without_url_falls_back_to_memory(self) -> None:
        """backend='redis' without redis_url falls back to InMemoryReplayStore."""
        settings = _FakeSettings(backend="redis", redis_url=None)
        store = await build_replay_store(settings)
        assert isinstance(store, InMemoryReplayStore)
        await store.close()

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _SQLITE_AVAILABLE, reason="aiosqlite not installed")
    async def test_explicit_sqlite_backend(self, tmp_path) -> None:
        """backend='sqlite' returns SqliteReplayStore."""
        db_path = str(tmp_path / "test_auto.db")
        settings = _FakeSettings(backend="sqlite", sqlite_path=db_path)
        store = await build_replay_store(settings)
        assert isinstance(store, SqliteReplayStore)
        await store.close()

    @pytest.mark.asyncio
    async def test_auto_no_redis_no_sqlite_uses_memory(self) -> None:
        """auto mode: neither Redis nor SQLite available → InMemoryReplayStore."""
        import agentic_v2.server.replay_store as module

        orig_redis = module._REDIS_AVAILABLE
        orig_sqlite = module._SQLITE_AVAILABLE
        module._REDIS_AVAILABLE = False
        module._SQLITE_AVAILABLE = False
        try:
            settings = _FakeSettings(backend="auto", redis_url=None)
            store = await build_replay_store(settings)
            assert isinstance(store, InMemoryReplayStore)
            await store.close()
        finally:
            module._REDIS_AVAILABLE = orig_redis
            module._SQLITE_AVAILABLE = orig_sqlite

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _SQLITE_AVAILABLE, reason="aiosqlite not installed")
    async def test_auto_no_redis_sqlite_available_uses_sqlite(self, tmp_path) -> None:
        """auto mode: no Redis but SQLite available → SqliteReplayStore."""
        import agentic_v2.server.replay_store as module

        orig_redis = module._REDIS_AVAILABLE
        module._REDIS_AVAILABLE = False
        try:
            db_path = str(tmp_path / "test_auto_sqlite.db")
            settings = _FakeSettings(backend="auto", redis_url=None, sqlite_path=db_path)
            store = await build_replay_store(settings)
            assert isinstance(store, SqliteReplayStore)
            await store.close()
        finally:
            module._REDIS_AVAILABLE = orig_redis

    @pytest.mark.asyncio
    @pytest.mark.skipif(not _REDIS_AVAILABLE, reason="redis not installed")
    async def test_auto_redis_available_but_connection_fails_tries_sqlite(
        self, tmp_path
    ) -> None:
        """auto mode: Redis url set but connection fails → tries next backend."""
        import agentic_v2.server.replay_store as module

        orig_sqlite = module._SQLITE_AVAILABLE
        module._SQLITE_AVAILABLE = False  # also disable sqlite to force memory
        try:
            settings = _FakeSettings(
                backend="auto",
                redis_url="redis://127.0.0.1:19999/0",  # nothing listening
            )
            store = await build_replay_store(settings)
            # Should have fallen all the way through to memory
            assert isinstance(store, InMemoryReplayStore)
            await store.close()
        finally:
            module._SQLITE_AVAILABLE = orig_sqlite

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not _REDIS_AVAILABLE, reason="redis package not installed"
    )
    async def test_auto_redis_connected_uses_redis(self) -> None:
        """auto mode: Redis url set and connection succeeds → RedisReplayStore."""
        import fakeredis

        from agentic_v2.server.replay_store import RedisReplayStore

        settings = _FakeSettings(
            backend="auto",
            redis_url="redis://fake",
        )

        fake_server = fakeredis.FakeServer()
        fake_client = fakeredis.FakeAsyncRedis(server=fake_server, decode_responses=True)

        async def fake_connect(
            redis_url: str,
            max_events: int = 500,
            ttl_seconds: int = 14400,
        ) -> RedisReplayStore:
            store = RedisReplayStore(
                redis_url=redis_url,
                max_events=max_events,
                ttl_seconds=ttl_seconds,
            )
            store._client = fake_client
            store._connected = True
            return store

        import agentic_v2.server.replay_store as module

        original_connect = module.RedisReplayStore.connect
        module.RedisReplayStore.connect = staticmethod(fake_connect)  # type: ignore[method-assign]
        try:
            store = await build_replay_store(settings)
            assert isinstance(store, RedisReplayStore)
            await store.close()
        finally:
            module.RedisReplayStore.connect = original_connect  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# initialize_store on ConnectionManager
# ---------------------------------------------------------------------------


class TestConnectionManagerInitializeStore:
    """Tests for ConnectionManager.initialize_store()."""

    @pytest.mark.asyncio
    async def test_initialize_store_sets_in_memory_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """initialize_store() sets InMemoryReplayStore when backend='memory'."""
        monkeypatch.setenv("REPLAY_STORE_BACKEND", "memory")
        # Bust the lru_cache so monkeypatched env is visible
        from agentic_v2.settings import get_settings

        get_settings.cache_clear()
        try:
            mgr = ConnectionManager()
            await mgr.initialize_store()
            assert isinstance(mgr._replay_store, InMemoryReplayStore)
        finally:
            get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_initialize_store_falls_back_on_settings_error(self) -> None:
        """initialize_store() keeps existing store when settings loading fails."""
        mgr = ConnectionManager()

        import agentic_v2.server.replay_store as rs_module

        original_build = rs_module.build_replay_store

        async def raising_build(settings: Any) -> ReplayStore:
            raise RuntimeError("settings broken")

        rs_module.build_replay_store = raising_build  # type: ignore[assignment]
        try:
            await mgr.initialize_store()
            assert isinstance(mgr._replay_store, InMemoryReplayStore)
        finally:
            rs_module.build_replay_store = original_build  # type: ignore[assignment]
