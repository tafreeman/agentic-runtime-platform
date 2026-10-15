"""Failure-path tests for the Redis-backed circuit breaker state store.

``agentic_v2.models.redis_state`` promises two things its happy-path tests in
``test_redis_circuit_breaker.py`` never exercise:

1. **A WATCH/MULTI/EXEC fallback CAS.**  ``cas()`` only uses the pre-registered
   Lua script when ``_cas_sha`` is set; otherwise it falls through to
   :meth:`RedisCircuitBreakerStore._cas_via_watch`.  That happens after a
   ``SCRIPT FLUSH`` or a Redis failover, i.e. exactly when the fleet is already
   degraded.  The two implementations must agree, or circuit-breaker counters
   silently diverge across workers.

2. **Graceful degradation** — "Falls back gracefully to local state when Redis
   is unavailable" (module docstring).  Every public method must *return* its
   documented fallback value when Redis errors, never raise: the circuit
   breaker guards every provider call, so an exception escaping here takes the
   router down instead of the one flaky dependency.

These tests pin both contracts.  All of them run against fakeredis or an
in-process stub — no network I/O, no real Redis, no credentials.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import pytest

from agentic_v2.models import redis_state
from agentic_v2.models.model_stats import ModelStats
from agentic_v2.models.redis_state import (
    _CAS_LUA_SCRIPT,
    _CAS_MAX_RETRIES,
    _REDIS_AVAILABLE,
    RedisCircuitBreakerStore,
)

try:
    import fakeredis

    _FAKEREDIS_AVAILABLE = True
except ImportError:
    _FAKEREDIS_AVAILABLE = False
    fakeredis = None  # type: ignore[assignment]

skip_no_fakeredis = pytest.mark.skipif(
    not _FAKEREDIS_AVAILABLE,
    reason="fakeredis not installed",
)

skip_no_redis_lib = pytest.mark.skipif(
    not _REDIS_AVAILABLE,
    reason="redis package not installed",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_store(
    *,
    use_lua: bool,
    server: Any = None,
    prefix: str = "test:cb:",
    ttl_seconds: int = 3600,
) -> RedisCircuitBreakerStore:
    """Build a fakeredis-backed store.

    Args:
        use_lua: When ``True`` the CAS Lua script is registered, so ``cas()``
            takes the ``EVALSHA`` path.  When ``False`` ``_cas_sha`` is left
            unset, forcing the WATCH/MULTI/EXEC fallback.
        server: Optional shared ``FakeServer`` so two stores can model two
            workers talking to one Redis.
        prefix: Key prefix.
        ttl_seconds: Key TTL.
    """
    fake_server = server if server is not None else fakeredis.FakeServer()
    client = fakeredis.FakeAsyncRedis(server=fake_server, decode_responses=True)
    store = RedisCircuitBreakerStore(
        redis_url="redis://fake",
        prefix=prefix,
        ttl_seconds=ttl_seconds,
    )
    store._client = client
    store._connected = True
    store._cas_sha = await client.script_load(_CAS_LUA_SCRIPT) if use_lua else None
    return store


class _RaisingPipeline:
    """Pipeline stub that buffers commands and fails on ``execute()``."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.buffered: list[tuple[str, Any]] = []

    async def __aenter__(self) -> _RaisingPipeline:
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    def set(self, key: str, value: Any, **kwargs: Any) -> None:
        self.buffered.append((key, value))

    async def execute(self) -> None:
        raise self._exc


class _RaisingRedis:
    """Async Redis stub whose every command raises a configured exception.

    Models a Redis that has gone away mid-flight: the store still believes it
    is connected, and each call has to degrade on its own.
    """

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.last_pipeline: _RaisingPipeline | None = None

    async def get(self, *args: Any, **kwargs: Any) -> Any:
        raise self._exc

    async def set(self, *args: Any, **kwargs: Any) -> Any:
        raise self._exc

    async def delete(self, *args: Any, **kwargs: Any) -> Any:
        raise self._exc

    async def evalsha(self, *args: Any, **kwargs: Any) -> Any:
        raise self._exc

    async def ping(self, *args: Any, **kwargs: Any) -> Any:
        raise self._exc

    async def scan_iter(self, *args: Any, **kwargs: Any) -> AsyncIterator[str]:
        raise self._exc
        yield ""  # pragma: no cover - unreachable; makes this an async generator

    def pipeline(self, *args: Any, **kwargs: Any) -> _RaisingPipeline:
        self.last_pipeline = _RaisingPipeline(self._exc)
        return self.last_pipeline


def _make_broken_store(exc: BaseException) -> RedisCircuitBreakerStore:
    """Build a store that believes it is connected but whose client errors."""
    store = RedisCircuitBreakerStore(redis_url="redis://fake", prefix="test:cb:")
    store._client = _RaisingRedis(exc)
    store._connected = True
    store._cas_sha = "deadbeef"
    return store


def _connection_error() -> BaseException:
    """A connection-class Redis error (should disable the store)."""
    from redis.exceptions import ConnectionError as RedisConnectionError

    return RedisConnectionError("connection reset by peer")


def _command_error() -> BaseException:
    """A non-connection Redis error (should NOT disable the store)."""
    from redis.exceptions import ResponseError

    return ResponseError("WRONGTYPE Operation against a key")


# ===========================================================================
# The WATCH/MULTI/EXEC fallback CAS
# ===========================================================================


@skip_no_fakeredis
@skip_no_redis_lib
class TestCasViaWatchFallback:
    """``cas()`` must be correct when the Lua script is unavailable."""

    async def test_watch_fallback_writes_when_key_absent(self) -> None:
        """expected=None succeeds only against a missing key."""
        store = await _make_store(use_lua=False)

        assert await store.cas("m", None, {"failure_count": 1}) is True
        assert await store.get("m") == {"failure_count": 1}

    async def test_watch_fallback_rejects_expected_none_when_key_exists(self) -> None:
        """expected=None must not clobber a key another worker created."""
        store = await _make_store(use_lua=False)
        await store.set("m", {"failure_count": 7})

        assert await store.cas("m", None, {"failure_count": 1}) is False
        # The other worker's value survives untouched.
        assert await store.get("m") == {"failure_count": 7}

    async def test_watch_fallback_writes_on_matching_value(self) -> None:
        """A CAS whose expected value matches is applied."""
        store = await _make_store(use_lua=False)
        await store.set("m", {"failure_count": 1})
        current = await store._read_raw("m")

        assert await store.cas("m", current, {"failure_count": 2}) is True
        assert await store.get("m") == {"failure_count": 2}

    async def test_watch_fallback_rejects_mismatched_value(self) -> None:
        """A stale expected value is refused and the store is left alone."""
        store = await _make_store(use_lua=False)
        await store.set("m", {"failure_count": 5})

        stale = json.dumps({"failure_count": 1})
        assert await store.cas("m", stale, {"failure_count": 99}) is False
        assert await store.get("m") == {"failure_count": 5}

    async def test_watch_fallback_applies_ttl(self) -> None:
        """The fallback path must not write a key that never expires."""
        store = await _make_store(use_lua=False, ttl_seconds=120)

        assert await store.cas("m", None, {"failure_count": 1}) is True
        ttl = await store._client.ttl("test:cb:m")
        assert 0 < ttl <= 120

    @pytest.mark.parametrize(
        ("seed", "expected_factory", "should_write"),
        [
            (None, lambda _current: None, True),
            ({"failure_count": 1}, lambda current: current, True),
            ({"failure_count": 1}, lambda _current: None, False),
            ({"failure_count": 1}, lambda _current: '{"failure_count": 42}', False),
        ],
        ids=["new-key", "match", "expect-none-but-exists", "stale-expected"],
    )
    async def test_lua_and_watch_paths_agree(
        self,
        seed: dict[str, Any] | None,
        expected_factory: Any,
        should_write: bool,
    ) -> None:
        """The Lua and WATCH implementations must produce identical outcomes.

        Two implementations of one contract drift silently; this pins them
        together so a change to either is caught.
        """
        new_value = {"failure_count": 1234}
        outcomes: dict[bool, tuple[bool, dict[str, Any] | None]] = {}

        for use_lua in (True, False):
            store = await _make_store(use_lua=use_lua)
            if seed is not None:
                await store.set("m", seed)
            expected = expected_factory(await store._read_raw("m"))

            wrote = await store.cas("m", expected, new_value)
            outcomes[use_lua] = (wrote, await store.get("m"))

        assert outcomes[True] == outcomes[False], (
            f"EVALSHA path returned {outcomes[True]} but WATCH path returned "
            f"{outcomes[False]}"
        )
        assert outcomes[True][0] is should_write

    async def test_save_stats_cas_persists_without_lua_script(self) -> None:
        """The real persist path works end-to-end on the fallback CAS."""
        store = await _make_store(use_lua=False)
        stats = ModelStats(model_id="ollama:phi4")
        stats.record_failure()
        stats.record_failure()

        baseline = await store.save_stats_cas("ollama:phi4", stats, None)

        assert baseline == {
            "success_count": 0,
            "failure_count": 2,
            "rate_limit_count": 0,
            "timeout_count": 0,
        }
        stored = await store.get("ollama:phi4")
        assert stored is not None
        assert stored["failure_count"] == 2

    async def test_watch_fallback_returns_false_when_another_writer_wins(
        self,
    ) -> None:
        """A WatchError is a lost race, not an error to propagate.

        WATCH exists precisely to detect a concurrent write between the read
        and the EXEC; the caller must see a plain CAS conflict and retry.
        """
        from redis.exceptions import WatchError

        class _WatchLosingPipeline:
            async def __aenter__(self) -> Any:
                return self

            async def __aexit__(self, *exc_info: object) -> bool:
                return False

            async def watch(self, *args: Any) -> None:
                return None

            async def get(self, *args: Any) -> None:
                return None

            async def unwatch(self) -> None:  # pragma: no cover - not reached
                return None

            def multi(self) -> None:
                return None

            def set(self, *args: Any, **kwargs: Any) -> None:
                return None

            async def execute(self) -> None:
                raise WatchError("WATCHed key changed")

        store = await _make_store(use_lua=False)
        store._client.pipeline = lambda **kwargs: _WatchLosingPipeline()

        assert await store.cas("m", None, {"failure_count": 1}) is False

    async def test_watch_fallback_returns_false_without_a_client(self) -> None:
        store = await _make_store(use_lua=False)
        store._client = None

        assert await store._cas_via_watch("test:cb:m", None, "{}") is False

    async def test_watch_fallback_merges_across_two_workers(self) -> None:
        """Counter-summing survives on the fallback path, not just under Lua."""
        server = fakeredis.FakeServer()
        worker_a = await _make_store(use_lua=False, server=server)
        worker_b = await _make_store(use_lua=False, server=server)

        stats_a = ModelStats(model_id="m")
        stats_a.record_failure()
        stats_b = ModelStats(model_id="m")
        stats_b.record_failure()

        await worker_a.save_stats_cas("m", stats_a, None)
        await worker_b.save_stats_cas("m", stats_b, None)

        stored = await worker_a.get("m")
        assert stored is not None
        assert stored["failure_count"] == 2, "one worker's failure was clobbered"


# ===========================================================================
# Graceful degradation when Redis errors mid-flight
# ===========================================================================


@skip_no_redis_lib
class TestGracefulDegradation:
    """Every public method returns its fallback value instead of raising."""

    async def test_get_returns_none(self) -> None:
        store = _make_broken_store(_connection_error())
        assert await store.get("m") is None

    async def test_get_all_returns_empty(self) -> None:
        store = _make_broken_store(_connection_error())
        assert await store.get_all() == {}

    async def test_set_returns_false(self) -> None:
        store = _make_broken_store(_connection_error())
        assert await store.set("m", {"failure_count": 1}) is False

    async def test_cas_returns_false(self) -> None:
        store = _make_broken_store(_connection_error())
        assert await store.cas("m", None, {"failure_count": 1}) is False

    async def test_delete_returns_false(self) -> None:
        store = _make_broken_store(_connection_error())
        assert await store.delete("m") is False

    async def test_save_all_stats_returns_false(self) -> None:
        store = _make_broken_store(_connection_error())
        stats = {"m": ModelStats(model_id="m")}
        assert await store.save_all_stats(stats) is False

    async def test_read_raw_returns_none(self) -> None:
        store = _make_broken_store(_connection_error())
        assert await store._read_raw("m") is None

    async def test_health_check_returns_false_and_disconnects(self) -> None:
        store = _make_broken_store(_command_error())
        assert await store.health_check() is False
        assert store.is_connected is False

    async def test_load_all_stats_returns_empty(self) -> None:
        store = _make_broken_store(_connection_error())
        assert await store.load_all_stats() == {}

    async def test_save_stats_cas_returns_none(self) -> None:
        """A dead Redis must not lose the caller's baseline."""
        store = _make_broken_store(_connection_error())
        stats = ModelStats(model_id="m")
        stats.record_failure()

        assert await store.save_stats_cas("m", stats, None) is None

    async def test_connection_error_disables_the_store(self) -> None:
        """A connection-class error flips the store to local-only fallback."""
        store = _make_broken_store(_connection_error())
        assert store.is_connected is True

        await store.get("m")

        assert store.is_connected is False

    async def test_command_error_keeps_the_store_connected(self) -> None:
        """One bad command must not disable fleet-wide breaker sharing.

        ``_handle_connection_loss`` deliberately only disconnects on
        connection-class errors.  Broadening that check would let a single
        ``WRONGTYPE`` permanently drop every worker back to local state.
        """
        store = _make_broken_store(_command_error())

        assert await store.get("m") is None
        assert store.is_connected is True

    async def test_disconnected_store_short_circuits_every_read(self) -> None:
        """With no client at all, reads return fallbacks without touching it."""
        store = RedisCircuitBreakerStore(redis_url="redis://fake")
        store._connected = False
        store._client = None

        assert await store.get("m") is None
        assert await store.get_all() == {}
        assert await store._read_raw("m") is None
        assert await store.delete("m") is False
        assert await store.save_all_stats({}) is False
        assert await store.save_stats_cas("m", ModelStats(model_id="m"), None) is None


# ===========================================================================
# Corrupt state in Redis
# ===========================================================================


@skip_no_fakeredis
@skip_no_redis_lib
class TestCorruptStateResilience:
    """A poisoned key must not take down reads of the healthy keys."""

    async def test_get_returns_none_for_unparseable_value(self) -> None:
        store = await _make_store(use_lua=True)
        await store._client.set("test:cb:m", "{not json")

        assert await store.get("m") is None

    async def test_get_all_skips_corrupt_and_returns_the_rest(self) -> None:
        store = await _make_store(use_lua=True)
        await store.set("good", {"failure_count": 3})
        await store._client.set("test:cb:bad", "{not json")

        result = await store.get_all()

        assert "bad" not in result
        assert result["good"] == {"failure_count": 3}

    async def test_load_all_stats_skips_undeserializable_entries(self) -> None:
        """A schema-incompatible record is dropped, not raised."""
        store = await _make_store(use_lua=True)
        healthy = ModelStats(model_id="healthy")
        healthy.record_success(latency_ms=10.0)
        await store.set("healthy", healthy.to_dict())
        # Valid JSON, but missing the required model_id -> KeyError in from_dict.
        await store.set("broken", {"failure_count": 1})

        result = await store.load_all_stats()

        assert "broken" not in result
        assert result["healthy"].model_id == "healthy"

    async def test_load_all_stats_skips_invalid_circuit_state(self) -> None:
        """An unknown enum value raises ValueError and is likewise dropped."""
        store = await _make_store(use_lua=True)
        payload = ModelStats(model_id="m").to_dict()
        payload["circuit_state"] = "NOT_A_REAL_STATE"
        await store.set("m", payload)

        assert await store.load_all_stats() == {}


# ===========================================================================
# CAS retry exhaustion
# ===========================================================================


@skip_no_fakeredis
@skip_no_redis_lib
class TestSaveStatsCasRetryExhaustion:
    """Unbounded contention must degrade to a retry, not a spin or a loss."""

    async def test_returns_none_after_exhausting_retries(self) -> None:
        store = await _make_store(use_lua=True)
        attempts = 0

        async def _always_conflict(*args: Any, **kwargs: Any) -> int:
            nonlocal attempts
            attempts += 1
            return 0  # Lua script's "CAS conflict" return value

        store._client.evalsha = _always_conflict  # type: ignore[method-assign]

        stats = ModelStats(model_id="m")
        stats.record_failure()

        result = await store.save_stats_cas("m", stats, None)

        assert result is None, "caller must keep its old baseline"
        assert attempts == _CAS_MAX_RETRIES, "retry loop must be bounded"

    async def test_unpersisted_delta_survives_for_the_next_save(self) -> None:
        """Returning None lets the caller re-apply the whole delta later."""
        store = await _make_store(use_lua=True)
        stats = ModelStats(model_id="m")
        stats.record_failure()
        stats.record_failure()

        original = store._client.evalsha

        async def _always_conflict(*args: Any, **kwargs: Any) -> int:
            return 0

        store._client.evalsha = _always_conflict  # type: ignore[method-assign]
        baseline = await store.save_stats_cas("m", stats, None)
        assert baseline is None

        # Redis recovers; the caller retries with the baseline it kept (None).
        store._client.evalsha = original  # type: ignore[method-assign]
        baseline = await store.save_stats_cas("m", stats, None)

        assert baseline == {
            "success_count": 0,
            "failure_count": 2,
            "rate_limit_count": 0,
            "timeout_count": 0,
        }
        stored = await store.get("m")
        assert stored is not None
        assert stored["failure_count"] == 2, "the delta was lost, not retried"


# ===========================================================================
# Connection lifecycle
# ===========================================================================


@skip_no_fakeredis
@skip_no_redis_lib
class TestConnectionLifecycle:
    """connect / close / reconnect must never raise on the unhappy path."""

    async def test_connect_without_redis_package_returns_local_only_store(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(redis_state, "_REDIS_AVAILABLE", False)

        store = await RedisCircuitBreakerStore.connect(
            "redis://localhost:6379/0",
            prefix="p:",
            ttl_seconds=42,
        )

        assert store.is_connected is False
        assert store.prefix == "p:"
        assert store.ttl_seconds == 42

    async def test_connect_with_unreachable_redis_degrades_instead_of_raising(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A refused connection yields a disconnected store, not an exception."""

        class _DeadPool:
            @classmethod
            def from_url(cls, *args: Any, **kwargs: Any) -> _DeadPool:
                return cls()

            async def disconnect(self) -> None:
                return None

        def _dead_redis(**kwargs: Any) -> _RaisingRedis:
            return _RaisingRedis(_connection_error())

        monkeypatch.setattr(redis_state, "AsyncConnectionPool", _DeadPool)
        monkeypatch.setattr(
            redis_state,
            "aioredis",
            type("_M", (), {"Redis": staticmethod(_dead_redis)}),
        )

        store = await RedisCircuitBreakerStore.connect("redis://unreachable:6379/0")

        assert store.is_connected is False
        # Degraded store still answers every call.
        assert await store.get("m") is None
        assert await store.health_check() is False

    async def test_close_releases_client_and_pool(self) -> None:
        store = await _make_store(use_lua=True)
        disconnected = False

        class _Pool:
            async def disconnect(self) -> None:
                nonlocal disconnected
                disconnected = True

        store._pool = _Pool()

        await store.close()

        assert store._client is None
        assert store._pool is None
        assert store.is_connected is False
        assert disconnected is True

    async def test_close_is_idempotent(self) -> None:
        """Double-close (e.g. lifespan shutdown racing a signal) is safe."""
        store = await _make_store(use_lua=True)

        await store.close()
        await store.close()

        assert store.is_connected is False

    async def test_reconnect_without_redis_package_returns_false(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        store = await _make_store(use_lua=True)
        monkeypatch.setattr(redis_state, "_REDIS_AVAILABLE", False)

        assert await store.reconnect() is False

    async def test_reconnect_reestablishes_the_connection(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A successful reconnect restores connected state and the CAS script."""
        server = fakeredis.FakeServer()

        class _Pool:
            @classmethod
            def from_url(cls, *args: Any, **kwargs: Any) -> _Pool:
                return cls()

            async def disconnect(self) -> None:
                return None

        def _fresh_client(**kwargs: Any) -> Any:
            return fakeredis.FakeAsyncRedis(server=server, decode_responses=True)

        monkeypatch.setattr(redis_state, "AsyncConnectionPool", _Pool)
        monkeypatch.setattr(
            redis_state,
            "aioredis",
            type("_M", (), {"Redis": staticmethod(_fresh_client)}),
        )

        store = RedisCircuitBreakerStore(redis_url="redis://fake")
        store._connected = False

        assert await store.reconnect() is True
        assert store.is_connected is True
        assert store._cas_sha is not None
        # The restored connection is usable.
        assert await store.set("m", {"failure_count": 1}) is True
        assert await store.get("m") == {"failure_count": 1}
