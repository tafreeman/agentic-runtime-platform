"""Durable replay-buffer backends for per-run WebSocket event history.

Late-connecting WebSocket clients need to catch up on events they missed.
This module provides three backends, selectable via ``Settings.replay_store_backend``:

* **RedisReplayStore** -- uses a Redis List (``RPUSH`` / ``LRANGE``) so that any
  worker in a multi-process deployment can serve a full replay.  Events are
  JSON-serialized and capped with ``LTRIM``.  Keys expire automatically via TTL.

* **SqliteReplayStore** -- async SQLite via ``aiosqlite``; suitable for a
  single-node dev setup that wants event history to survive a restart without
  requiring Redis.  The database path defaults to an ABSOLUTE path anchored at
  the repo root (:data:`DEFAULT_SQLITE_PATH`), never the process CWD -- see
  ADR context in ``Settings.replay_sqlite_path``.  Rows older than
  ``retention_seconds`` are purged lazily (on ``append``/``get_events``/
  ``_initialize``) rather than via a background sweep thread.

* **InMemoryReplayStore** -- wraps a plain ``collections.deque``; zero
  dependencies, zero durability.  Used when neither Redis nor SQLite is
  available or desired.

Usage::

    from agentic_v2.server.replay_store import build_replay_store
    from agentic_v2.settings import get_settings

    store = await build_replay_store(get_settings())
    await store.append("run-abc", {"type": "step_start", ...})
    events = await store.get_events("run-abc")
    await store.clear("run-abc")
    await store.close()
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from pathlib import Path
from typing import Any, Final, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional Redis import guard — mirrors redis_state.py pattern
# ---------------------------------------------------------------------------
try:
    import redis.asyncio as aioredis
    from redis.asyncio import ConnectionPool as AsyncConnectionPool
    from redis.exceptions import ConnectionError as RedisConnectionError
    from redis.exceptions import RedisError

    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False
    aioredis = None  # type: ignore[assignment]
    AsyncConnectionPool = None  # type: ignore[assignment,misc]
    RedisConnectionError = ConnectionError  # type: ignore[assignment,misc]
    RedisError = Exception  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Optional aiosqlite import guard
# ---------------------------------------------------------------------------
try:
    import aiosqlite

    _SQLITE_AVAILABLE = True
except ImportError:
    _SQLITE_AVAILABLE = False
    aiosqlite = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Key constants
# ---------------------------------------------------------------------------
REPLAY_DB_FILENAME: Final[str] = ".agentic_replay.db"

# Anchor the default SQLite path at the repo root, not the process CWD.
# Mirrors run_logger.py's _DEFAULT_RUNS_DIR: replay_store.py lives at
# agentic_v2/server/replay_store.py (same depth as agentic_v2/workflows/
# run_logger.py), so parents[3] resolves to the repo root in both the
# installed package and an editable/worktree checkout.
DEFAULT_SQLITE_PATH: Final[Path] = (
    Path(__file__).resolve().parents[3] / REPLAY_DB_FILENAME
)

_REDIS_KEY_PREFIX = "agentic:replay:"
_DEFAULT_MAX_EVENTS: int = 500
_DEFAULT_TTL_SECONDS: int = 14400  # 4 hours — RedisReplayStore native EXPIRE
_DEFAULT_RETENTION_SECONDS: int = 3600  # 1 hour — grace period post-completion


def _resolve_absolute_sqlite_path(db_path: str | Path) -> Path:
    """Resolve *db_path* to an absolute path, anchoring relative input at the repo root
    instead of the process CWD.

    An explicitly absolute path (or one already resolving to
    :data:`DEFAULT_SQLITE_PATH`, e.g. the bare default filename) is honoured
    as-is other than being made absolute; a genuinely different relative
    path is still resolved against the current directory via
    :meth:`Path.resolve` (Pydantic settings and callers that pass a custom
    relative path get ordinary CWD-relative semantics -- only the *default*
    is required to be CWD-independent).

    Args:
        db_path: Caller-supplied path, typically ``Settings.replay_sqlite_path``
            or the ``REPLAY_DB_FILENAME`` default.

    Returns:
        An absolute :class:`~pathlib.Path`.
    """
    path = Path(db_path)
    if not path.is_absolute() and str(path) == REPLAY_DB_FILENAME:
        return DEFAULT_SQLITE_PATH
    return path.resolve()


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ReplayStore(Protocol):
    """Async protocol for a per-run event replay buffer.

    All methods are fire-and-forget-safe from the caller's perspective:
    implementations must catch their own errors and never propagate them
    to the broadcast path.
    """

    async def append(self, run_id: str, event: dict[str, Any]) -> None:
        """Persist a single event for *run_id*.

        Args:
            run_id: Workflow run identifier.
            event: JSON-serializable event dict.
        """
        ...

    async def get_events(self, run_id: str) -> list[dict[str, Any]]:
        """Return all events for *run_id* in insertion order.

        Args:
            run_id: Workflow run identifier.

        Returns:
            Ordered list of event dicts; empty list if none exist.
        """
        ...

    async def clear(self, run_id: str) -> None:
        """Delete all stored events for *run_id*.

        Args:
            run_id: Workflow run identifier.
        """
        ...

    async def close(self) -> None:
        """Release any held resources (connection pools, file handles)."""
        ...


# ---------------------------------------------------------------------------
# InMemoryReplayStore
# ---------------------------------------------------------------------------


class InMemoryReplayStore:
    """Zero-dependency in-process replay store backed by a ``deque``.

    Not durable across restarts, not shared across workers.  Use as
    a last-resort fallback when neither Redis nor SQLite is available.

    Attributes:
        max_events: Maximum events retained per run (oldest are evicted).
    """

    def __init__(self, max_events: int = _DEFAULT_MAX_EVENTS) -> None:
        """Initialise the store.

        Args:
            max_events: Per-run event cap.  Older entries are evicted
                automatically by the underlying ``deque(maxlen=...)``.
        """
        self.max_events = max_events
        self._buffers: dict[str, deque[dict[str, Any]]] = {}

    async def append(self, run_id: str, event: dict[str, Any]) -> None:
        """Append *event* to the in-memory buffer for *run_id*.

        Args:
            run_id: Workflow run identifier.
            event: JSON-serializable event dict.
        """
        if run_id not in self._buffers:
            self._buffers[run_id] = deque(maxlen=self.max_events)
        self._buffers[run_id].append(event)

    async def get_events(self, run_id: str) -> list[dict[str, Any]]:
        """Return buffered events for *run_id*.

        Args:
            run_id: Workflow run identifier.

        Returns:
            List of events in insertion order.
        """
        return list(self._buffers.get(run_id, []))

    async def clear(self, run_id: str) -> None:
        """Remove the buffer for *run_id*.

        Args:
            run_id: Workflow run identifier.
        """
        self._buffers.pop(run_id, None)

    async def close(self) -> None:
        """No-op — nothing to release."""


# ---------------------------------------------------------------------------
# RedisReplayStore
# ---------------------------------------------------------------------------


class RedisReplayStore:
    """Redis-backed durable replay store using a Redis List per run.

    Events are stored under the key ``agentic:replay:{run_id}`` as a JSON
    list.  ``RPUSH`` appends; ``LTRIM`` enforces the cap; ``EXPIRE`` sets the
    TTL.  ``LRANGE 0 -1`` retrieves all events in order.

    Falls back gracefully — on any Redis error the method logs a warning and
    returns a safe value rather than propagating to the broadcast path.

    Attributes:
        redis_url: Redis connection URL.
        max_events: Per-run event cap enforced via ``LTRIM``.
        ttl_seconds: Key TTL; refreshed on every ``append``.
    """

    def __init__(
        self,
        redis_url: str,
        max_events: int = _DEFAULT_MAX_EVENTS,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    ) -> None:
        """Initialise but do not connect yet; call :meth:`connect` first.

        Args:
            redis_url: Redis connection URL.
            max_events: Maximum events retained per run key.
            ttl_seconds: Key TTL in seconds.
        """
        self.redis_url = redis_url
        self.max_events = max_events
        self.ttl_seconds = ttl_seconds
        self._pool: Any = None
        self._client: Any = None
        self._connected: bool = False

    @classmethod
    async def connect(
        cls,
        redis_url: str,
        max_events: int = _DEFAULT_MAX_EVENTS,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    ) -> RedisReplayStore:
        """Create a store and establish the Redis connection.

        Args:
            redis_url: Redis connection URL.
            max_events: Per-run event cap.
            ttl_seconds: Key TTL in seconds.

        Returns:
            A connected store, or a disconnected store on failure (graceful
            degradation — callers should check :attr:`is_connected`).
        """
        store = cls(redis_url=redis_url, max_events=max_events, ttl_seconds=ttl_seconds)
        if not _REDIS_AVAILABLE:
            logger.warning(
                "redis package not installed; RedisReplayStore will not persist events"
            )
            return store
        await store._establish_connection()
        return store

    async def _establish_connection(self) -> None:
        """Create pool, client, verify ping."""
        try:
            self._pool = AsyncConnectionPool.from_url(
                self.redis_url,
                decode_responses=True,
                max_connections=10,
            )
            self._client = aioredis.Redis(connection_pool=self._pool)
            await self._client.ping()
            self._connected = True
            logger.info(
                "RedisReplayStore connected: url=%s max_events=%d ttl=%ds",
                self.redis_url,
                self.max_events,
                self.ttl_seconds,
            )
        except (RedisError, OSError) as exc:
            logger.warning(
                "RedisReplayStore connection failed (%s); events will not be persisted",
                exc,
            )
            self._connected = False
            self._client = None
            self._pool = None

    @property
    def is_connected(self) -> bool:
        """Whether the store has an active Redis connection."""
        return self._connected

    def _make_key(self, run_id: str) -> str:
        """Build the full Redis key for a run."""
        return f"{_REDIS_KEY_PREFIX}{run_id}"

    async def append(self, run_id: str, event: dict[str, Any]) -> None:
        """Append *event* to the Redis List for *run_id*.

        Uses a pipeline to atomically: RPUSH the serialized event, LTRIM to
        enforce the cap, and EXPIRE to refresh the TTL.

        Args:
            run_id: Workflow run identifier.
            event: JSON-serializable event dict.
        """
        if not self._connected or self._client is None:
            return

        key = self._make_key(run_id)
        try:
            serialized = json.dumps(event)
            async with self._client.pipeline(transaction=False) as pipe:
                pipe.rpush(key, serialized)
                # LTRIM keeps indices 0..(max_events-1), evicting oldest
                pipe.ltrim(key, -self.max_events, -1)
                pipe.expire(key, self.ttl_seconds)
                await pipe.execute()
        except (RedisError, OSError, json.JSONDecodeError) as exc:
            logger.warning("RedisReplayStore.append failed for run %s: %s", run_id, exc)
            self._handle_connection_loss(exc)

    async def get_events(self, run_id: str) -> list[dict[str, Any]]:
        """Retrieve all events for *run_id* from Redis.

        Args:
            run_id: Workflow run identifier.

        Returns:
            Ordered list of event dicts; empty on error or miss.
        """
        if not self._connected or self._client is None:
            return []

        key = self._make_key(run_id)
        try:
            raw_list: list[str] = await self._client.lrange(key, 0, -1)
            result: list[dict[str, Any]] = []
            for raw in raw_list:
                try:
                    result.append(json.loads(raw))
                except json.JSONDecodeError:
                    logger.warning(
                        "RedisReplayStore: corrupt event in key=%s, skipping", key
                    )
            return result
        except (RedisError, OSError) as exc:
            logger.warning(
                "RedisReplayStore.get_events failed for run %s: %s", run_id, exc
            )
            self._handle_connection_loss(exc)
            return []

    async def clear(self, run_id: str) -> None:
        """Delete the Redis List for *run_id*.

        Args:
            run_id: Workflow run identifier.
        """
        if not self._connected or self._client is None:
            return

        key = self._make_key(run_id)
        try:
            await self._client.delete(key)
        except (RedisError, OSError) as exc:
            logger.warning("RedisReplayStore.clear failed for run %s: %s", run_id, exc)
            self._handle_connection_loss(exc)

    def _handle_connection_loss(self, exc: BaseException) -> None:
        """Mark disconnected on connection-class errors."""
        if isinstance(exc, (RedisConnectionError, OSError)):
            logger.error(
                "RedisReplayStore: connection lost, replay persistence disabled: %s",
                exc,
            )
            self._connected = False

    async def close(self) -> None:
        """Close the Redis connection pool."""
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception as exc:
                logger.debug("Error closing replay_store Redis client: %s", exc)
            self._client = None
        if self._pool is not None:
            try:
                await self._pool.disconnect()
            except Exception as exc:
                logger.debug("Error disconnecting replay_store Redis pool: %s", exc)
            self._pool = None
        self._connected = False


# ---------------------------------------------------------------------------
# SqliteReplayStore
# ---------------------------------------------------------------------------

_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS replay_events (
    run_id    TEXT    NOT NULL,
    seq       INTEGER NOT NULL,
    event     TEXT    NOT NULL,
    created_at REAL   NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_replay_run_id ON replay_events (run_id, seq);
"""


class SqliteReplayStore:
    """Async SQLite-backed replay store using ``aiosqlite``.

    Events are stored in a local ``replay_events`` table ordered by an
    auto-incremented sequence number.  The database file is created
    automatically on first use, resolved to an ABSOLUTE path so it never
    depends on the process's current working directory (see
    :data:`DEFAULT_SQLITE_PATH`).

    Rows older than ``retention_seconds`` are purged lazily -- on
    ``append()``, ``get_events()``, and once at ``_initialize()`` -- rather
    than via a background sweep thread/task.  This bounds unbounded disk
    growth (the operational gap this store used to have relative to
    :class:`RedisReplayStore`, which sets a native key TTL) while keeping the
    store dependency-free of any scheduler.

    Attributes:
        db_path: Absolute filesystem path to the SQLite database file.
        max_events: Maximum events retained per run (oldest purged on append).
        retention_seconds: Age (seconds, by ``created_at``) beyond which rows
            are purged regardless of the per-run event cap.
    """

    def __init__(
        self,
        db_path: str | Path = REPLAY_DB_FILENAME,
        max_events: int = _DEFAULT_MAX_EVENTS,
        retention_seconds: float = _DEFAULT_RETENTION_SECONDS,
    ) -> None:
        """Initialise the store.  Call :meth:`connect` before use.

        Args:
            db_path: Path to the SQLite database file. A relative path (or
                the bare default filename) is resolved against
                :data:`DEFAULT_SQLITE_PATH`'s parent (the repo root) rather
                than the process CWD.
            max_events: Per-run event cap.
            retention_seconds: Age beyond which rows are purged lazily.
                ``float`` (not just whole seconds) so tests can inject a
                sub-second retention instead of sleeping for real minutes.
        """
        self.db_path = _resolve_absolute_sqlite_path(db_path)
        self.max_events = max_events
        self.retention_seconds = retention_seconds
        self._db: Any = None

    @classmethod
    async def connect(
        cls,
        db_path: str | Path = REPLAY_DB_FILENAME,
        max_events: int = _DEFAULT_MAX_EVENTS,
        retention_seconds: float = _DEFAULT_RETENTION_SECONDS,
    ) -> SqliteReplayStore:
        """Create and initialise the SQLite store.

        Args:
            db_path: Path to the SQLite database file (see :meth:`__init__`).
            max_events: Per-run event cap.
            retention_seconds: Age beyond which rows are purged lazily.

        Returns:
            Ready-to-use store instance.

        Raises:
            RuntimeError: If ``aiosqlite`` is not installed.
        """
        if not _SQLITE_AVAILABLE:
            raise RuntimeError(
                "aiosqlite is not installed; install agentic-workflows-v2[sqlite] "
                "or choose a different replay_store_backend"
            )
        store = cls(
            db_path=db_path, max_events=max_events, retention_seconds=retention_seconds
        )
        await store._initialize()
        return store

    async def _initialize(self) -> None:
        """Open the database and create the schema if needed.

        Creates the parent directory first so an absolute path under a
        not-yet-existing directory (e.g. a fresh repo root) does not fail
        with ``sqlite3.OperationalError: unable to open database file``.
        """
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SQLITE_DDL)
        await self._db.commit()
        await self._purge_expired()
        logger.info(
            "SqliteReplayStore initialized: path=%s max_events=%d "
            "retention_seconds=%s",
            self.db_path,
            self.max_events,
            self.retention_seconds,
        )

    async def _purge_expired(self) -> None:
        """Delete rows older than ``retention_seconds`` across all runs.

        Best-effort: a failure here must never prevent the store from
        otherwise functioning, so errors are logged and swallowed.
        """
        if self.retention_seconds <= 0:
            return
        cutoff = time.time() - self.retention_seconds
        try:
            await self._db.execute(
                "DELETE FROM replay_events WHERE created_at < ?", (cutoff,)
            )
            await self._db.commit()
        except Exception as exc:
            logger.warning(
                "SqliteReplayStore._purge_expired failed (path=%s): %s",
                self.db_path,
                exc,
            )

    async def append(self, run_id: str, event: dict[str, Any]) -> None:
        """Append *event*, enforce the per-run event cap, and purge stale rows.

        Args:
            run_id: Workflow run identifier.
            event: JSON-serializable event dict.
        """
        if self._db is None:
            return

        try:
            serialized = json.dumps(event)
            # Determine next seq
            async with self._db.execute(
                "SELECT COALESCE(MAX(seq), -1) + 1 FROM replay_events WHERE run_id = ?",
                (run_id,),
            ) as cursor:
                row = await cursor.fetchone()
                next_seq: int = row[0] if row else 0

            await self._db.execute(
                "INSERT INTO replay_events (run_id, seq, event, created_at) VALUES (?, ?, ?, ?)",
                (run_id, next_seq, serialized, time.time()),
            )

            # Enforce cap: delete oldest rows beyond max_events
            await self._db.execute(
                """
                DELETE FROM replay_events
                WHERE run_id = ?
                  AND seq < (
                      SELECT seq FROM replay_events
                      WHERE run_id = ?
                      ORDER BY seq DESC
                      LIMIT 1 OFFSET ?
                  )
                """,
                (run_id, run_id, self.max_events - 1),
            )
            await self._db.commit()
            await self._purge_expired()
        except Exception as exc:
            logger.warning(
                "SqliteReplayStore.append failed for run %s: %s", run_id, exc
            )

    async def get_events(self, run_id: str) -> list[dict[str, Any]]:
        """Return all events for *run_id* ordered by insertion sequence.

        Purges retention-expired rows lazily before reading, so a
        long-lived read path also converges on the retention policy even if
        no ``append()`` calls happen to trigger it.

        Args:
            run_id: Workflow run identifier.

        Returns:
            Ordered list of event dicts; empty list on error.
        """
        if self._db is None:
            return []

        await self._purge_expired()

        try:
            async with self._db.execute(
                "SELECT event FROM replay_events WHERE run_id = ? ORDER BY seq ASC",
                (run_id,),
            ) as cursor:
                rows = await cursor.fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                try:
                    result.append(json.loads(row[0]))
                except json.JSONDecodeError:
                    logger.warning(
                        "SqliteReplayStore: corrupt event for run=%s, skipping", run_id
                    )
            return result
        except Exception as exc:
            logger.warning(
                "SqliteReplayStore.get_events failed for run %s: %s", run_id, exc
            )
            return []

    async def clear(self, run_id: str) -> None:
        """Delete all events for *run_id*.

        Args:
            run_id: Workflow run identifier.
        """
        if self._db is None:
            return

        try:
            await self._db.execute(
                "DELETE FROM replay_events WHERE run_id = ?", (run_id,)
            )
            await self._db.commit()
        except Exception as exc:
            logger.warning("SqliteReplayStore.clear failed for run %s: %s", run_id, exc)

    async def close(self) -> None:
        """Close the SQLite connection."""
        if self._db is not None:
            try:
                await self._db.close()
            except Exception as exc:
                logger.debug("Error closing replay_store SQLite connection: %s", exc)
            self._db = None


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------


async def build_replay_store(settings: Any) -> ReplayStore:
    """Build the appropriate :class:`ReplayStore` from application settings.

    Selection logic for ``replay_store_backend = 'auto'``:

    1. If ``redis_url`` is set and ``redis`` package is available → try Redis.
    2. If ``aiosqlite`` is available → try SQLite.
    3. Fall back to in-memory.

    Args:
        settings: Application :class:`~agentic_v2.settings.Settings` instance.
            Accessed attributes: ``replay_store_backend``, ``redis_url``,
            ``replay_store_ttl``, ``replay_store_max_events``,
            ``replay_sqlite_path``, ``replay_store_retention_seconds``.

    Returns:
        A ready-to-use :class:`ReplayStore` implementation.
    """
    backend: str = getattr(settings, "replay_store_backend", "auto")
    max_events: int = getattr(settings, "replay_store_max_events", _DEFAULT_MAX_EVENTS)
    ttl: int = getattr(settings, "replay_store_ttl", _DEFAULT_TTL_SECONDS)
    retention: int = getattr(
        settings, "replay_store_retention_seconds", _DEFAULT_RETENTION_SECONDS
    )
    # An empty/unset setting resolves to the absolute repo-root default;
    # _resolve_absolute_sqlite_path only special-cases the bare filename, so
    # empty string must be normalised here first.
    sqlite_path: str = getattr(settings, "replay_sqlite_path", "") or REPLAY_DB_FILENAME
    redis_url: str | None = getattr(settings, "redis_url", None)

    if backend == "redis":
        return await _build_explicit_redis_store(
            redis_url, max_events=max_events, ttl=ttl
        )

    if backend == "sqlite":
        return await _build_explicit_sqlite_store(
            sqlite_path, max_events=max_events, retention=retention
        )

    if backend == "memory":
        return InMemoryReplayStore(max_events=max_events)

    return await _build_auto_store(
        redis_url,
        sqlite_path=sqlite_path,
        max_events=max_events,
        ttl=ttl,
        retention=retention,
    )


async def _build_explicit_redis_store(
    redis_url: str | None, *, max_events: int, ttl: int
) -> ReplayStore:
    """Build a Redis store for ``backend='redis'``, falling back to in-memory."""
    if not redis_url:
        logger.warning(
            "replay_store_backend='redis' but redis_url is not set; "
            "falling back to InMemoryReplayStore"
        )
        return InMemoryReplayStore(max_events=max_events)
    store = await RedisReplayStore.connect(
        redis_url=redis_url, max_events=max_events, ttl_seconds=ttl
    )
    if not store.is_connected:
        logger.warning(
            "replay_store_backend='redis' but connection failed; "
            "falling back to InMemoryReplayStore"
        )
        return InMemoryReplayStore(max_events=max_events)
    return store


async def _build_explicit_sqlite_store(
    sqlite_path: str, *, max_events: int, retention: int
) -> ReplayStore:
    """Build a SQLite store for ``backend='sqlite'``, falling back to in-memory."""
    if not _SQLITE_AVAILABLE:
        logger.warning(
            "replay_store_backend='sqlite' but aiosqlite not installed; "
            "falling back to InMemoryReplayStore"
        )
        return InMemoryReplayStore(max_events=max_events)
    try:
        return await SqliteReplayStore.connect(
            db_path=sqlite_path, max_events=max_events, retention_seconds=retention
        )
    except Exception as exc:
        resolved = _resolve_absolute_sqlite_path(sqlite_path)
        logger.warning(
            "replay_store_backend='sqlite' but init failed (path=%s, resolved=%s): "
            "%s; falling back to InMemoryReplayStore",
            sqlite_path,
            resolved,
            exc,
        )
        return InMemoryReplayStore(max_events=max_events)


async def _build_auto_store(
    redis_url: str | None,
    *,
    sqlite_path: str,
    max_events: int,
    ttl: int,
    retention: int,
) -> ReplayStore:
    """Auto-select Redis, then SQLite, then in-memory based on availability."""
    if redis_url and _REDIS_AVAILABLE:
        store = await RedisReplayStore.connect(
            redis_url=redis_url, max_events=max_events, ttl_seconds=ttl
        )
        if store.is_connected:
            logger.info("ReplayStore: selected Redis backend")
            return store
        logger.warning("ReplayStore: Redis unavailable, trying SQLite")

    if _SQLITE_AVAILABLE:
        try:
            sqlite_store = await SqliteReplayStore.connect(
                db_path=sqlite_path, max_events=max_events, retention_seconds=retention
            )
            logger.info("ReplayStore: selected SQLite backend (path=%s)", sqlite_path)
            return sqlite_store
        except Exception as exc:
            resolved = _resolve_absolute_sqlite_path(sqlite_path)
            logger.warning(
                "ReplayStore: SQLite init failed (path=%s, resolved=%s): %s; "
                "using memory",
                sqlite_path,
                resolved,
                exc,
            )

    logger.info("ReplayStore: selected InMemory backend (no persistence)")
    return InMemoryReplayStore(max_events=max_events)
