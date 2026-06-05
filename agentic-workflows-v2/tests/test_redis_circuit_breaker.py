"""Tests for Redis-backed circuit breaker state store.

Unit tests use fakeredis to simulate Redis without a running server.
Integration tests (marked @pytest.mark.integration) require a real
Redis instance at localhost:6379.
"""

from __future__ import annotations

import pytest

from agentic_v2.models.model_stats import CircuitState, ModelStats
from agentic_v2.models.redis_state import (
    _REDIS_AVAILABLE,
    RedisCircuitBreakerStore,
)
from agentic_v2.models.smart_router import SmartModelRouter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _make_sample_stats(model_id: str = "ollama:phi4") -> ModelStats:
    """Create a ModelStats with some recorded data."""
    stats = ModelStats(model_id=model_id)
    stats.record_success(latency_ms=150.0)
    stats.record_success(latency_ms=200.0)
    return stats


async def _make_fake_store(
    prefix: str = "test:cb:",
    ttl_seconds: int = 3600,
) -> RedisCircuitBreakerStore:
    """Create a store backed by fakeredis."""
    fake_server = fakeredis.FakeServer()
    fake_client = fakeredis.FakeAsyncRedis(
        server=fake_server, decode_responses=True
    )
    store = RedisCircuitBreakerStore(
        redis_url="redis://fake",
        prefix=prefix,
        ttl_seconds=ttl_seconds,
    )
    store._client = fake_client
    store._connected = True
    # Register the CAS Lua script
    from agentic_v2.models.redis_state import _CAS_LUA_SCRIPT

    store._cas_sha = await fake_client.script_load(_CAS_LUA_SCRIPT)
    return store


# ============================================================================
# Unit Tests — RedisCircuitBreakerStore
# ============================================================================


@skip_no_fakeredis
@skip_no_redis_lib
class TestRedisCircuitBreakerStore:
    """Unit tests for RedisCircuitBreakerStore using fakeredis."""

    async def test_get_nonexistent_key(self):
        """GET on a missing key returns None."""
        store = await _make_fake_store()
        result = await store.get("nonexistent:model")
        assert result is None
        await store.close()

    async def test_set_and_get_roundtrip(self):
        """SET then GET returns the same stats dict."""
        store = await _make_fake_store()
        stats = _make_sample_stats()
        stats_dict = stats.to_dict()

        ok = await store.set("ollama:phi4", stats_dict)
        assert ok is True

        loaded = await store.get("ollama:phi4")
        assert loaded is not None
        assert loaded["model_id"] == "ollama:phi4"
        assert loaded["success_count"] == 2

        await store.close()

    async def test_save_all_and_load_all(self):
        """save_all_stats + load_all_stats round-trip."""
        store = await _make_fake_store()

        model_stats = {
            "ollama:phi4": _make_sample_stats("ollama:phi4"),
            "gh:gpt-4o": _make_sample_stats("gh:gpt-4o"),
        }

        ok = await store.save_all_stats(model_stats)
        assert ok is True

        loaded = await store.load_all_stats()
        assert len(loaded) == 2
        assert "ollama:phi4" in loaded
        assert "gh:gpt-4o" in loaded
        assert loaded["ollama:phi4"].success_count == 2
        assert loaded["gh:gpt-4o"].model_id == "gh:gpt-4o"

        await store.close()

    async def test_cas_succeeds_on_matching_value(self):
        """CAS succeeds when expected value matches current."""
        store = await _make_fake_store()
        stats = _make_sample_stats()
        stats_dict = stats.to_dict()

        # Initial set
        await store.set("ollama:phi4", stats_dict)

        # Read back the raw value
        raw = await store._client.get(store._make_key("ollama:phi4"))

        # CAS with matching expected value
        updated_stats = _make_sample_stats()
        updated_stats.record_failure("timeout")
        ok = await store.cas("ollama:phi4", raw, updated_stats.to_dict())
        assert ok is True

        # Verify the update took effect
        loaded = await store.get("ollama:phi4")
        assert loaded["failure_count"] == 1

        await store.close()

    async def test_cas_fails_on_mismatched_value(self):
        """CAS fails when expected value does not match current."""
        store = await _make_fake_store()
        stats = _make_sample_stats()
        stats_dict = stats.to_dict()

        # Initial set
        await store.set("ollama:phi4", stats_dict)

        # CAS with wrong expected value
        ok = await store.cas(
            "ollama:phi4", '{"wrong": "data"}', {"model_id": "ollama:phi4"}
        )
        assert ok is False

        # Verify original value unchanged
        loaded = await store.get("ollama:phi4")
        assert loaded["success_count"] == 2

        await store.close()

    async def test_cas_prevents_lost_updates(self):
        """Simulate two concurrent writers — one wins, one loses."""
        store = await _make_fake_store()
        stats = _make_sample_stats()
        await store.set("ollama:phi4", stats.to_dict())

        # Read current value (both "workers" see the same snapshot)
        raw = await store._client.get(store._make_key("ollama:phi4"))

        # Worker A writes first — succeeds
        updated_a = _make_sample_stats()
        updated_a.record_success(latency_ms=100.0)
        ok_a = await store.cas("ollama:phi4", raw, updated_a.to_dict())
        assert ok_a is True

        # Worker B uses the stale snapshot — must fail
        updated_b = _make_sample_stats()
        updated_b.record_failure("timeout")
        ok_b = await store.cas("ollama:phi4", raw, updated_b.to_dict())
        assert ok_b is False

        # Verify A's write persisted
        loaded = await store.get("ollama:phi4")
        assert loaded["success_count"] == 3  # original 2 + A's 1

        await store.close()

    async def test_cas_new_key_expects_none(self):
        """CAS with expected_json=None succeeds on missing key."""
        store = await _make_fake_store()
        stats = _make_sample_stats()

        ok = await store.cas("new:model", None, stats.to_dict())
        assert ok is True

        loaded = await store.get("new:model")
        assert loaded is not None
        assert loaded["model_id"] == "ollama:phi4"

        await store.close()

    async def test_cas_new_key_fails_if_exists(self):
        """CAS with expected_json=None fails if key already exists."""
        store = await _make_fake_store()
        stats = _make_sample_stats()

        # Pre-populate the key
        await store.set("new:model", stats.to_dict())

        # CAS expecting empty key — should fail
        ok = await store.cas("new:model", None, {"model_id": "overwrite"})
        assert ok is False

        await store.close()

    async def test_delete(self):
        """Delete removes a key."""
        store = await _make_fake_store()
        stats = _make_sample_stats()
        await store.set("ollama:phi4", stats.to_dict())

        ok = await store.delete("ollama:phi4")
        assert ok is True

        loaded = await store.get("ollama:phi4")
        assert loaded is None

        await store.close()

    async def test_get_all_with_prefix(self):
        """get_all returns only keys matching the prefix."""
        store = await _make_fake_store(prefix="myapp:cb:")

        stats = _make_sample_stats()
        await store.set("model-a", stats.to_dict())
        await store.set("model-b", stats.to_dict())

        # Set a key with a different prefix directly
        await store._client.set("other:key", "irrelevant")

        all_stats = await store.get_all()
        assert len(all_stats) == 2
        assert "model-a" in all_stats
        assert "model-b" in all_stats

        await store.close()

    async def test_health_check(self):
        """health_check returns True when connected."""
        store = await _make_fake_store()
        assert await store.health_check() is True
        await store.close()

    async def test_key_prefix(self):
        """Keys use the configured prefix."""
        store = await _make_fake_store(prefix="custom:")
        assert store._make_key("ollama:phi4") == "custom:ollama:phi4"
        await store.close()


# ============================================================================
# Unit Tests — Fallback behavior
# ============================================================================


@skip_no_redis_lib
class TestFallbackBehavior:
    """Test graceful degradation when Redis is unavailable."""

    async def test_disconnected_store_returns_none_on_get(self):
        """A disconnected store returns None for get()."""
        store = RedisCircuitBreakerStore(
            redis_url="redis://fake",
            prefix="test:",
        )
        # _connected defaults to False
        assert store.is_connected is False
        result = await store.get("any:model")
        assert result is None

    async def test_disconnected_store_returns_false_on_set(self):
        """A disconnected store returns False for set()."""
        store = RedisCircuitBreakerStore(
            redis_url="redis://fake",
            prefix="test:",
        )
        ok = await store.set("any:model", {"model_id": "test"})
        assert ok is False

    async def test_disconnected_store_returns_empty_on_get_all(self):
        """A disconnected store returns empty dict for get_all()."""
        store = RedisCircuitBreakerStore(
            redis_url="redis://fake",
            prefix="test:",
        )
        result = await store.get_all()
        assert result == {}

    async def test_disconnected_store_returns_false_on_cas(self):
        """A disconnected store returns False for cas()."""
        store = RedisCircuitBreakerStore(
            redis_url="redis://fake",
            prefix="test:",
        )
        ok = await store.cas("any:model", None, {"model_id": "test"})
        assert ok is False

    async def test_health_check_disconnected(self):
        """health_check returns False when disconnected."""
        store = RedisCircuitBreakerStore(
            redis_url="redis://fake",
            prefix="test:",
        )
        assert await store.health_check() is False


# ============================================================================
# Unit Tests — TTL behavior
# ============================================================================


@skip_no_fakeredis
@skip_no_redis_lib
class TestTTLBehavior:
    """Test that keys are written with the configured TTL."""

    async def test_set_applies_ttl(self):
        """Keys set via set() have a TTL."""
        store = await _make_fake_store(ttl_seconds=120)
        stats = _make_sample_stats()

        await store.set("ollama:phi4", stats.to_dict())

        ttl = await store._client.ttl(store._make_key("ollama:phi4"))
        # TTL should be > 0 and <= 120
        assert 0 < ttl <= 120

        await store.close()

    async def test_cas_applies_ttl(self):
        """Keys set via CAS have a TTL."""
        store = await _make_fake_store(ttl_seconds=300)
        stats = _make_sample_stats()

        ok = await store.cas("ollama:phi4", None, stats.to_dict())
        assert ok is True

        ttl = await store._client.ttl(store._make_key("ollama:phi4"))
        assert 0 < ttl <= 300

        await store.close()


# ============================================================================
# Unit Tests — SmartModelRouter Redis integration
# ============================================================================


@skip_no_fakeredis
@skip_no_redis_lib
class TestSmartModelRouterRedisIntegration:
    """Test SmartModelRouter with a Redis-backed store."""

    async def test_save_stats_writes_to_redis(self):
        """When Redis store is attached, _save_stats writes to Redis."""
        store = await _make_fake_store()
        router = SmartModelRouter(_redis_store=store, _auto_save=False)

        # Record some stats
        router.record_success("ollama:phi4", 100.0)
        router.record_success("ollama:phi4", 200.0)

        # Manually trigger the async save
        await router._save_stats_to_redis()

        # Verify data landed in Redis
        loaded = await store.get("ollama:phi4")
        assert loaded is not None
        assert loaded["success_count"] == 2

        await store.close()

    async def test_load_stats_from_redis(self):
        """_load_stats_from_redis populates model_stats."""
        store = await _make_fake_store()

        # Pre-populate Redis
        stats = _make_sample_stats("ollama:phi4")
        await store.set("ollama:phi4", stats.to_dict())

        router = SmartModelRouter(_redis_store=store, _auto_save=False)
        assert len(router.model_stats) == 0

        await router._load_stats_from_redis()
        assert "ollama:phi4" in router.model_stats
        assert router.model_stats["ollama:phi4"].success_count == 2

        await store.close()

    async def test_create_with_redis_factory(self):
        """create_with_redis loads initial state from Redis."""
        # We can't use create_with_redis directly with fakeredis because
        # it calls connect() which tries real connection. Test the
        # components instead.
        store = await _make_fake_store()

        # Pre-populate
        stats = _make_sample_stats("gh:gpt-4o")
        await store.save_all_stats({"gh:gpt-4o": stats})

        # Simulate what create_with_redis does
        router = SmartModelRouter(_redis_store=store, _auto_save=False)
        await router._load_stats_from_redis()

        assert "gh:gpt-4o" in router.model_stats
        assert router.model_stats["gh:gpt-4o"].success_count == 2

        await store.close()

    async def test_should_persist_with_redis(self):
        """_should_persist is True when Redis store is connected."""
        store = await _make_fake_store()
        router = SmartModelRouter(_redis_store=store)
        assert router._should_persist is True
        await store.close()

    async def test_should_persist_without_redis_or_file(self):
        """_should_persist is False with no Redis and no stats_file."""
        router = SmartModelRouter()
        assert router._should_persist is False

    async def test_repr_includes_redis_status(self):
        """__repr__ shows redis connection status."""
        store = await _make_fake_store()
        router = SmartModelRouter(_redis_store=store)
        assert "redis=connected" in repr(router)
        await store.close()

    async def test_repr_without_redis(self):
        """__repr__ shows redis=none when no store is attached."""
        router = SmartModelRouter()
        assert "redis=none" in repr(router)


# ============================================================================
# Unit Tests — ModelStats serialization through Redis
# ============================================================================


@skip_no_fakeredis
@skip_no_redis_lib
class TestModelStatsRedisRoundTrip:
    """Verify ModelStats serialization fidelity through Redis."""

    async def test_circuit_state_preserved(self):
        """Circuit breaker state round-trips correctly."""
        store = await _make_fake_store()
        stats = ModelStats(model_id="test:model")

        # Trip the circuit breaker
        for _ in range(5):
            stats.record_failure("error")
        assert stats.circuit_state == CircuitState.OPEN

        await store.set("test:model", stats.to_dict())
        loaded_dict = await store.get("test:model")
        loaded = ModelStats.from_dict(loaded_dict)

        assert loaded.circuit_state == CircuitState.OPEN
        assert loaded.failure_count == 5

        await store.close()

    async def test_latency_metrics_preserved(self):
        """Latency EMA and counts survive round-trip."""
        store = await _make_fake_store()
        stats = ModelStats(model_id="test:model")
        stats.record_success(latency_ms=100.0)
        stats.record_success(latency_ms=200.0)
        stats.record_success(latency_ms=300.0)

        await store.set("test:model", stats.to_dict())
        loaded_dict = await store.get("test:model")
        loaded = ModelStats.from_dict(loaded_dict)

        assert loaded.success_count == 3
        assert loaded._ema_latency_ms > 0

        await store.close()

    async def test_timestamps_preserved(self):
        """Timestamp fields round-trip correctly."""
        store = await _make_fake_store()
        stats = _make_sample_stats("test:model")

        await store.set("test:model", stats.to_dict())
        loaded_dict = await store.get("test:model")
        loaded = ModelStats.from_dict(loaded_dict)

        assert loaded.last_success is not None
        assert loaded.first_seen is not None

        await store.close()


# ============================================================================
# Integration Tests — require real Redis
# ============================================================================


@pytest.mark.integration
@skip_no_redis_lib
class TestRedisIntegration:
    """Integration tests requiring a real Redis server at localhost:6379."""

    async def test_real_connection(self):
        """Connect to a real Redis, write and read back."""
        store = await RedisCircuitBreakerStore.connect(
            redis_url="redis://localhost:6379/15",  # Use DB 15 to avoid conflicts
            prefix="integration-test:cb:",
            ttl_seconds=60,
        )
        if not store.is_connected:
            pytest.skip("Redis not available at localhost:6379")

        try:
            stats = _make_sample_stats()
            ok = await store.set("integration:model", stats.to_dict())
            assert ok is True

            loaded = await store.get("integration:model")
            assert loaded is not None
            assert loaded["model_id"] == "ollama:phi4"
        finally:
            await store.delete("integration:model")
            await store.close()

    async def test_real_cas(self):
        """CAS works correctly against a real Redis."""
        store = await RedisCircuitBreakerStore.connect(
            redis_url="redis://localhost:6379/15",
            prefix="integration-test:cb:",
            ttl_seconds=60,
        )
        if not store.is_connected:
            pytest.skip("Redis not available at localhost:6379")

        try:
            stats = _make_sample_stats()
            await store.set("cas:model", stats.to_dict())

            raw = await store._client.get(store._make_key("cas:model"))

            updated = _make_sample_stats()
            updated.record_failure("test")
            ok = await store.cas("cas:model", raw, updated.to_dict())
            assert ok is True

            # Stale CAS should fail
            ok2 = await store.cas("cas:model", raw, stats.to_dict())
            assert ok2 is False
        finally:
            await store.delete("cas:model")
            await store.close()
