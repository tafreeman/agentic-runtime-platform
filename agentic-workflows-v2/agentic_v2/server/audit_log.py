"""Tamper-evident audit logging for server security and workflow events.

Audit events are structured JSON records linked by a SHA-256 hash chain.
The store implementations are append-only from the application perspective:
``FileAuditStore`` writes JSONL with ``O_APPEND`` and ``RedisAuditStore`` writes
to Redis Streams via ``XADD`` with ``MAXLEN`` trimming.

OIDC integration note for E8-1:
    ``auth_oidc.py`` is not present yet.  When that module lands, call
    :func:`audit_auth_request_event` from login/callback/logout branches with
    event types such as ``"auth.oidc.login_succeeded"`` and metadata that
    contains issuer/client identifiers but never raw tokens.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import uuid4

from ..settings import get_settings

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

try:
    import structlog

    _log = structlog.get_logger(__name__)
except ImportError:
    structlog = None  # type: ignore[assignment]
    _log = logging.getLogger(__name__)

logger = logging.getLogger(__name__)

AuditOutcome = Literal["success", "failure", "denied", "error", "unknown"]
_GENESIS_HASH = "0" * 64
_DEFAULT_FILE_PATH = ".agentic_audit.jsonl"
_DEFAULT_REDIS_STREAM = "agentic:audit"
_DEFAULT_MAX_EVENTS = 10000


@runtime_checkable
class AuditStore(Protocol):
    """Async append-only persistence contract for audit records."""

    async def append(self, record: dict[str, Any]) -> str:
        """Append a canonical audit record and return the storage identifier."""
        ...

    async def get_last_hash(self) -> str | None:
        """Return the newest record hash, or ``None`` when the store is empty."""
        ...

    async def close(self) -> None:
        """Release any store resources."""
        ...


class NullAuditStore:
    """No-op audit store used when audit logging is disabled."""

    async def append(self, record: dict[str, Any]) -> str:
        return str(record.get("id", "noop"))

    async def get_last_hash(self) -> str | None:
        return None

    async def close(self) -> None:
        return None


class FileAuditStore:
    """Append audit records to a JSONL file using OS append semantics."""

    def __init__(self, path: str | os.PathLike[str] = _DEFAULT_FILE_PATH) -> None:
        self.path = Path(path)
        self._lock = asyncio.Lock()

    async def append(self, record: dict[str, Any]) -> str:
        """Append one JSONL record.

        The file is opened with ``os.O_APPEND`` for each write, so concurrent
        writers cannot seek and overwrite prior records.
        """
        line = _canonical_json(record).encode("utf-8") + b"\n"
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
            fd = os.open(self.path, flags, 0o600)
            try:
                os.write(fd, line)
                os.fsync(fd)
            finally:
                os.close(fd)
        return str(self.path)

    async def get_last_hash(self) -> str | None:
        if not self.path.exists():
            return None
        try:
            last_line = ""
            with self.path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        last_line = line
            if not last_line:
                return None
            record = json.loads(last_line)
            value = record.get("hash")
            return value if isinstance(value, str) and value else None
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read audit log tail from %s: %s", self.path, exc)
            return None

    async def close(self) -> None:
        return None


class RedisAuditStore:
    """Append audit records to a Redis Stream with ``XADD MAXLEN``."""

    def __init__(
        self,
        redis_url: str,
        stream_name: str = _DEFAULT_REDIS_STREAM,
        max_events: int = _DEFAULT_MAX_EVENTS,
    ) -> None:
        self.redis_url = redis_url
        self.stream_name = stream_name
        self.max_events = max_events
        self._pool: Any = None
        self._client: Any = None
        self._connected = False

    @classmethod
    async def connect(
        cls,
        redis_url: str,
        stream_name: str = _DEFAULT_REDIS_STREAM,
        max_events: int = _DEFAULT_MAX_EVENTS,
    ) -> RedisAuditStore:
        store = cls(
            redis_url=redis_url,
            stream_name=stream_name,
            max_events=max_events,
        )
        if not _REDIS_AVAILABLE:
            logger.warning("redis package not installed; RedisAuditStore disabled")
            return store
        await store._establish_connection()
        return store

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def _establish_connection(self) -> None:
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
                "RedisAuditStore connected: stream=%s max_events=%d",
                self.stream_name,
                self.max_events,
            )
        except (RedisError, OSError) as exc:
            logger.warning("RedisAuditStore connection failed: %s", exc)
            self._connected = False
            self._client = None
            self._pool = None

    async def append(self, record: dict[str, Any]) -> str:
        if not self._connected or self._client is None:
            return ""
        try:
            entry_id = await self._client.xadd(
                self.stream_name,
                {
                    "record": _canonical_json(record),
                    "hash": record["hash"],
                    "event_type": record["event_type"],
                    "timestamp": record["timestamp"],
                },
                id="*",
                maxlen=self.max_events,
                approximate=True,
            )
            return _decode_redis_value(entry_id)
        except (RedisError, OSError) as exc:
            logger.warning("RedisAuditStore.append failed: %s", exc)
            self._handle_connection_loss(exc)
            return ""

    async def get_last_hash(self) -> str | None:
        if not self._connected or self._client is None:
            return None
        try:
            rows = await self._client.xrevrange(self.stream_name, count=1)
            if not rows:
                return None
            _entry_id, fields = rows[0]
            if isinstance(fields, dict):
                value = fields.get("hash")
                if value is not None:
                    return _decode_redis_value(value)
                record_raw = fields.get("record")
                if record_raw is not None:
                    record = json.loads(_decode_redis_value(record_raw))
                    hash_value = record.get("hash")
                    return hash_value if isinstance(hash_value, str) else None
            return None
        except (RedisError, OSError, json.JSONDecodeError) as exc:
            logger.warning("RedisAuditStore.get_last_hash failed: %s", exc)
            self._handle_connection_loss(exc)
            return None

    def _handle_connection_loss(self, exc: BaseException) -> None:
        if isinstance(exc, (RedisConnectionError, OSError)):
            self._connected = False

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None
        if self._pool is not None:
            try:
                await self._pool.disconnect()
            except Exception:
                pass
            self._pool = None
        self._connected = False


class AuditLogger:
    """Build and persist hash-chained audit events."""

    def __init__(self, store: AuditStore, *, enabled: bool = True) -> None:
        self.store = store
        self.enabled = enabled
        self._lock = asyncio.Lock()
        self._last_hash: str | None = None

    async def audit(
        self,
        event_type: str,
        *,
        outcome: AuditOutcome = "unknown",
        actor: dict[str, Any] | None = None,
        target: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        run_id: str | None = None,
        request_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create and append one tamper-evident audit record."""
        async with self._lock:
            if self._last_hash is None:
                self._last_hash = await self.store.get_last_hash() or _GENESIS_HASH
            record = self._build_record(
                event_type,
                outcome=outcome,
                actor=actor,
                target=target,
                tenant_id=tenant_id,
                run_id=run_id,
                request_id=request_id,
                metadata=metadata,
                prev_hash=self._last_hash,
            )
            if self.enabled:
                try:
                    await self.store.append(record)
                except Exception as exc:
                    logger.exception("Audit store append failed: %s", exc)
                _log_audit_event(event_type, outcome, record["hash"])
            self._last_hash = record["hash"]
            return record

    def _build_record(
        self,
        event_type: str,
        *,
        outcome: AuditOutcome,
        actor: dict[str, Any] | None,
        target: dict[str, Any] | None,
        tenant_id: str | None,
        run_id: str | None,
        request_id: str | None,
        metadata: dict[str, Any] | None,
        prev_hash: str,
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "schema_version": "audit.v1",
            "id": uuid4().hex,
            "timestamp": datetime.now(UTC).isoformat(),
            "event_type": event_type,
            "outcome": outcome,
            "actor": _json_safe(actor or {}),
            "target": _json_safe(target or {}),
            "tenant_id": tenant_id,
            "run_id": run_id,
            "request_id": request_id,
            "metadata": _json_safe(metadata or {}),
            "prev_hash": prev_hash,
        }
        record["hash"] = compute_audit_hash(record)
        return record

    async def close(self) -> None:
        await self.store.close()


async def build_audit_logger(settings: Any | None = None) -> AuditLogger:
    """Build an :class:`AuditLogger` from application settings."""
    settings = settings or get_settings()
    enabled = bool(getattr(settings, "audit_log_enabled", False))
    if not enabled:
        return AuditLogger(NullAuditStore(), enabled=False)

    backend = str(getattr(settings, "audit_log_backend", "file")).strip().lower()
    max_events = int(getattr(settings, "audit_log_max_events", _DEFAULT_MAX_EVENTS))

    if backend == "redis":
        redis_url = getattr(settings, "redis_url", None)
        if redis_url:
            store = await RedisAuditStore.connect(
                redis_url=redis_url,
                stream_name=getattr(settings, "audit_log_redis_stream", _DEFAULT_REDIS_STREAM),
                max_events=max_events,
            )
            if store.is_connected:
                return AuditLogger(store, enabled=True)
        logger.warning("Audit redis backend unavailable; falling back to file audit store")

    store = FileAuditStore(
        path=getattr(settings, "audit_log_file_path", _DEFAULT_FILE_PATH)
    )
    return AuditLogger(store, enabled=True)


async def audit_auth_request_event(
    request: Any,
    event_type: str,
    *,
    outcome: AuditOutcome,
    actor: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Emit an auth audit event from API key or future OIDC request paths."""
    await audit_request_event(
        request,
        event_type,
        outcome=outcome,
        actor=actor,
        target={"path": getattr(getattr(request, "url", None), "path", None)},
        metadata=metadata,
    )


async def audit_request_event(
    request: Any,
    event_type: str,
    *,
    outcome: AuditOutcome,
    actor: dict[str, Any] | None = None,
    target: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    run_id: str | None = None,
    tenant_id: str | None = None,
) -> None:
    """Best-effort route helper that never lets audit failures break requests."""
    audit_logger = getattr(getattr(request, "app", None), "state", None)
    audit_logger = getattr(audit_logger, "audit_logger", None)
    if not isinstance(audit_logger, AuditLogger):
        logger.warning(
            "audit_request_event called for %s but audit_logger is missing or invalid type",
            event_type,
        )
        return
    client = getattr(request, "client", None)
    request_id = None
    headers = getattr(request, "headers", None)
    if headers is not None:
        request_id = headers.get("x-request-id") or headers.get("traceparent")
    try:
        await audit_logger.audit(
            event_type,
            outcome=outcome,
            actor=actor,
            target=target,
            tenant_id=tenant_id,
            run_id=run_id,
            request_id=request_id,
            metadata={
                "client_ip": getattr(client, "host", None),
                **(metadata or {}),
            },
        )
    except Exception as exc:
        logger.warning("Audit request helper failed for %s: %s", event_type, exc)


def compute_audit_hash(record: dict[str, Any]) -> str:
    """Compute the canonical SHA-256 hash for a record."""
    payload = {key: value for key, value in record.items() if key != "hash"}
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def verify_audit_chain(records: list[dict[str, Any]]) -> bool:
    """Return True when records form a valid contiguous hash chain."""
    expected_prev = _GENESIS_HASH
    for record in records:
        if record.get("prev_hash") != expected_prev:
            return False
        if record.get("hash") != compute_audit_hash(record):
            return False
        expected_prev = str(record["hash"])
    return True


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(key): _json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [_json_safe(item) for item in value]
        return str(value)


def _decode_redis_value(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _log_audit_event(event_type: str, outcome: str, audit_hash: str) -> None:
    if structlog is not None:
        _log.bind(component="audit").info(
            "audit_event",
            event_type=event_type,
            outcome=outcome,
            audit_hash=audit_hash,
        )
        return
    _log.info(
        "audit_event event_type=%s outcome=%s audit_hash=%s",
        event_type,
        outcome,
        audit_hash,
    )
