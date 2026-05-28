"""Redis-backed circuit breaker state store for multi-worker deployments.

Provides atomic Compare-And-Swap (CAS) operations for model stats so that
multiple workers can share circuit breaker state without lost updates.
Falls back gracefully to local state when Redis is unavailable.

Usage::

    from agentic_v2.models.redis_state import RedisCircuitBreakerStore

    store = await RedisCircuitBreakerStore.connect("redis://localhost:6379/0")
    stats_dict = await store.get("ollama:phi4")
    success = await store.cas("ollama:phi4", expected_version, new_stats_dict)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from .model_stats import ModelStats

logger = logging.getLogger(__name__)

# Guard Redis imports — package works without redis installed
try:
    import redis.asyncio as aioredis
    from redis.asyncio import ConnectionPool as AsyncConnectionPool
    from redis.exceptions import ConnectionError as RedisConnectionError
    from redis.exceptions import RedisError, WatchError

    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False
    aioredis = None  # type: ignore[assignment]
    AsyncConnectionPool = None  # type: ignore[assignment,misc]
    RedisConnectionError = ConnectionError  # type: ignore[assignment,misc]
    RedisError = Exception  # type: ignore[assignment,misc]
    WatchError = Exception  # type: ignore[assignment,misc]

# Lua script for atomic CAS: SET only if the current value matches expected
# KEYS[1] = model key
# ARGV[1] = expected JSON value (empty string "" means key must not exist)
# ARGV[2] = new JSON value
# ARGV[3] = TTL in seconds
# Returns: 1 if set succeeded, 0 if CAS conflict
_CAS_LUA_SCRIPT = """
local current = redis.call('GET', KEYS[1])
local expected = ARGV[1]
if expected == '' then
    if current ~= false then
        return 0
    end
else
    if current ~= expected then
        return 0
    end
end
redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
return 1
"""

# Default TTL: 1 hour
DEFAULT_TTL_SECONDS: int = 3600


@dataclass
class RedisCircuitBreakerStore:
    """Async Redis-backed store for circuit breaker model stats.

    Attributes:
        redis_url: Redis connection URL.
        prefix: Key prefix for circuit breaker state.
        ttl_seconds: TTL for Redis keys (auto-expire stale state).
    """

    redis_url: str
    prefix: str = "agentic:cb:"
    ttl_seconds: int = DEFAULT_TTL_SECONDS

    _pool: Any = field(default=None, repr=False)
    _client: Any = field(default=None, repr=False)
    _cas_sha: str | None = field(default=None, repr=False)
    _connected: bool = field(default=False, repr=False)

    @classmethod
    async def connect(
        cls,
        redis_url: str,
        prefix: str = "agentic:cb:",
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> RedisCircuitBreakerStore:
        """Create a store and establish the Redis connection.

        Args:
            redis_url: Redis connection URL (e.g. ``redis://localhost:6379/0``).
            prefix: Key prefix for all circuit breaker keys.
            ttl_seconds: TTL for keys in seconds.

        Returns:
            Connected store instance, or a disconnected instance if Redis
            is unreachable (graceful degradation).
        """
        if not _REDIS_AVAILABLE:
            logger.warning(
                "redis package not installed; "
                "circuit breaker state will use local fallback only"
            )
            return cls(
                redis_url=redis_url,
                prefix=prefix,
                ttl_seconds=ttl_seconds,
            )

        store = cls(
            redis_url=redis_url,
            prefix=prefix,
            ttl_seconds=ttl_seconds,
        )
        await store._establish_connection()
        return store

    async def _establish_connection(self) -> None:
        """Create the connection pool and register the CAS Lua script."""
        try:
            self._pool = AsyncConnectionPool.from_url(
                self.redis_url,
                decode_responses=True,
                max_connections=10,
            )
            self._client = aioredis.Redis(connection_pool=self._pool)
            # Verify connectivity
            await self._client.ping()
            # Pre-register Lua script for CAS
            self._cas_sha = await self._client.script_load(_CAS_LUA_SCRIPT)
            self._connected = True
            logger.info(
                "Redis circuit breaker store connected: url=%s prefix=%s ttl=%ds",
                self.redis_url,
                self.prefix,
                self.ttl_seconds,
            )
        except (RedisError, OSError) as exc:
            logger.warning(
                "Redis connection failed (%s); "
                "circuit breaker state will use local fallback",
                exc,
            )
            self._connected = False
            self._client = None
            self._pool = None

    @property
    def is_connected(self) -> bool:
        """Whether the store has an active Redis connection."""
        return self._connected

    def _make_key(self, model: str) -> str:
        """Build the full Redis key for a model."""
        return f"{self.prefix}{model}"

    async def get(self, model: str) -> dict[str, Any] | None:
        """Get stats for a model from Redis.

        Args:
            model: Model identifier (e.g. ``ollama:phi4``).

        Returns:
            The stats dictionary, or ``None`` if the key does not exist
            or Redis is unavailable.
        """
        if not self._connected or self._client is None:
            return None

        try:
            raw = await self._client.get(self._make_key(model))
            if raw is None:
                return None
            return json.loads(raw)
        except (RedisError, json.JSONDecodeError, OSError) as exc:
            logger.warning("Redis GET failed for model=%s: %s", model, exc)
            self._handle_connection_loss(exc)
            return None

    async def get_all(self) -> dict[str, dict[str, Any]]:
        """Get all circuit breaker stats from Redis.

        Returns:
            Mapping of model name to stats dict.  Empty dict if Redis
            is unavailable.
        """
        if not self._connected or self._client is None:
            return {}

        try:
            pattern = f"{self.prefix}*"
            result: dict[str, dict[str, Any]] = {}
            async for key in self._client.scan_iter(match=pattern, count=100):
                model = key.removeprefix(self.prefix)
                raw = await self._client.get(key)
                if raw is not None:
                    try:
                        result[model] = json.loads(raw)
                    except json.JSONDecodeError:
                        logger.warning("Corrupt Redis value for key=%s", key)
            return result
        except (RedisError, OSError) as exc:
            logger.warning("Redis SCAN failed: %s", exc)
            self._handle_connection_loss(exc)
            return {}

    async def set(self, model: str, stats_dict: dict[str, Any]) -> bool:
        """Unconditionally set stats for a model in Redis.

        Args:
            model: Model identifier.
            stats_dict: Serialized model stats (from ``ModelStats.to_dict()``).

        Returns:
            ``True`` if the write succeeded, ``False`` otherwise.
        """
        if not self._connected or self._client is None:
            return False

        try:
            value = json.dumps(stats_dict)
            await self._client.set(
                self._make_key(model),
                value,
                ex=self.ttl_seconds,
            )
            return True
        except (RedisError, OSError) as exc:
            logger.warning("Redis SET failed for model=%s: %s", model, exc)
            self._handle_connection_loss(exc)
            return False

    async def cas(
        self,
        model: str,
        expected_json: str | None,
        new_stats_dict: dict[str, Any],
    ) -> bool:
        """Atomic Compare-And-Swap for a model's stats.

        Only writes ``new_stats_dict`` if the current value in Redis
        matches ``expected_json`` exactly.  If ``expected_json`` is None,
        the key must not exist for the write to succeed.

        Args:
            model: Model identifier.
            expected_json: The JSON string currently stored (or None for
                new keys).
            new_stats_dict: New stats to write.

        Returns:
            ``True`` if the CAS succeeded, ``False`` on conflict or error.
        """
        if not self._connected or self._client is None:
            return False

        key = self._make_key(model)
        new_json = json.dumps(new_stats_dict)
        expected = expected_json if expected_json is not None else ""

        try:
            if self._cas_sha:
                result = await self._client.evalsha(
                    self._cas_sha,
                    1,
                    key,
                    expected,
                    new_json,
                    str(self.ttl_seconds),
                )
                return result == 1

            # Fallback: WATCH/MULTI/EXEC pipeline
            return await self._cas_via_watch(key, expected_json, new_json)
        except (RedisError, OSError) as exc:
            logger.warning("Redis CAS failed for model=%s: %s", model, exc)
            self._handle_connection_loss(exc)
            return False

    async def _cas_via_watch(
        self,
        key: str,
        expected_json: str | None,
        new_json: str,
    ) -> bool:
        """Fallback CAS using WATCH/MULTI/EXEC."""
        if self._client is None:
            return False

        try:
            async with self._client.pipeline(transaction=True) as pipe:
                await pipe.watch(key)
                current = await pipe.get(key)

                if expected_json is None:
                    if current is not None:
                        await pipe.unwatch()
                        return False
                elif current != expected_json:
                    await pipe.unwatch()
                    return False

                pipe.multi()
                pipe.set(key, new_json, ex=self.ttl_seconds)
                await pipe.execute()
                return True
        except WatchError:
            return False

    async def delete(self, model: str) -> bool:
        """Delete stats for a model.

        Args:
            model: Model identifier.

        Returns:
            ``True`` if the key was deleted, ``False`` otherwise.
        """
        if not self._connected or self._client is None:
            return False

        try:
            await self._client.delete(self._make_key(model))
            return True
        except (RedisError, OSError) as exc:
            logger.warning("Redis DELETE failed for model=%s: %s", model, exc)
            self._handle_connection_loss(exc)
            return False

    async def save_all_stats(
        self,
        model_stats: dict[str, ModelStats],
    ) -> bool:
        """Save all model stats to Redis atomically via pipeline.

        Args:
            model_stats: Mapping of model name to ``ModelStats`` instance.

        Returns:
            ``True`` if all writes succeeded.
        """
        if not self._connected or self._client is None:
            return False

        try:
            async with self._client.pipeline(transaction=False) as pipe:
                for model, stats in model_stats.items():
                    value = json.dumps(stats.to_dict())
                    pipe.set(self._make_key(model), value, ex=self.ttl_seconds)
                await pipe.execute()
            return True
        except (RedisError, OSError) as exc:
            logger.warning("Redis save_all_stats failed: %s", exc)
            self._handle_connection_loss(exc)
            return False

    async def load_all_stats(self) -> dict[str, ModelStats]:
        """Load all model stats from Redis.

        Returns:
            Mapping of model name to ``ModelStats`` instances.  Empty dict
            if Redis is unavailable or no keys exist.
        """
        raw_all = await self.get_all()
        result: dict[str, ModelStats] = {}
        for model, stats_dict in raw_all.items():
            try:
                result[model] = ModelStats.from_dict(stats_dict)
            except (KeyError, ValueError) as exc:
                logger.warning(
                    "Failed to deserialize stats for model=%s: %s", model, exc
                )
        return result

    def _handle_connection_loss(self, exc: BaseException) -> None:
        """Mark the store as disconnected on connection-class errors."""
        if isinstance(exc, (RedisConnectionError, OSError)):
            logger.error(
                "Redis connection lost; falling back to local state: %s", exc
            )
            self._connected = False

    async def close(self) -> None:
        """Close the Redis connection pool."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        if self._pool is not None:
            await self._pool.disconnect()
            self._pool = None
        self._connected = False

    async def health_check(self) -> bool:
        """Verify Redis connectivity.

        Returns:
            ``True`` if Redis responds to PING.
        """
        if not self._connected or self._client is None:
            return False

        try:
            return await self._client.ping()
        except (RedisError, OSError):
            self._connected = False
            return False

    async def reconnect(self) -> bool:
        """Attempt to re-establish a dropped Redis connection.

        Returns:
            ``True`` if reconnection succeeded.
        """
        if not _REDIS_AVAILABLE:
            return False

        await self.close()
        await self._establish_connection()
        return self._connected
