"""Failure and recovery paths for tamper-evident audit logging.

Complements ``tests/test_audit_log.py`` (happy-path chain building) with the
paths that make the audit log trustworthy under adversity: tamper detection in
``verify_audit_chain``, tail recovery in ``FileAuditStore``, Redis store
degradation and cleanup, backend fallback in ``build_audit_logger``, and the
never-raise contract of ``audit_request_event``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "agentic_v2"


def _load_audit_module() -> types.ModuleType:
    """Load audit_log without executing the broad server package exports.

    Mirrors the loader in ``tests/test_audit_log.py`` (including its
    ``setdefault`` semantics for already-imported modules) so the two files
    share one module object regardless of collection order.
    """
    existing = sys.modules.get("agentic_v2.server.audit_log")
    if existing is not None:
        return existing

    package = types.ModuleType("agentic_v2")
    package.__path__ = [str(_PACKAGE_ROOT)]  # type: ignore[attr-defined]
    sys.modules.setdefault("agentic_v2", package)

    server_package = types.ModuleType("agentic_v2.server")
    server_package.__path__ = [str(_PACKAGE_ROOT / "server")]  # type: ignore[attr-defined]
    sys.modules.setdefault("agentic_v2.server", server_package)

    def _load(module_name: str, path: Path) -> types.ModuleType:
        spec = importlib.util.spec_from_file_location(module_name, path)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    if "agentic_v2.settings" not in sys.modules:
        _load("agentic_v2.settings", _PACKAGE_ROOT / "settings.py")
    return _load(
        "agentic_v2.server.audit_log",
        _PACKAGE_ROOT / "server" / "audit_log.py",
    )


audit_module = _load_audit_module()
AuditLogger = audit_module.AuditLogger
FileAuditStore = audit_module.FileAuditStore
NullAuditStore = audit_module.NullAuditStore
RedisAuditStore = audit_module.RedisAuditStore
audit_request_event = audit_module.audit_request_event
build_audit_logger = audit_module.build_audit_logger
verify_audit_chain = audit_module.verify_audit_chain


async def _write_chain(path: Path, count: int = 2) -> list[dict[str, Any]]:
    logger = AuditLogger(FileAuditStore(path))
    return [
        await logger.audit(f"event.{index}", outcome="success")
        for index in range(count)
    ]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------------------
# verify_audit_chain: tamper detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_chain_rejects_mutated_payload(tmp_path: Path) -> None:
    await _write_chain(tmp_path / "audit.jsonl")
    records = _read_jsonl(tmp_path / "audit.jsonl")

    records[0]["outcome"] = "denied"  # post-hoc edit invalidates the hash

    assert verify_audit_chain(records) is False


@pytest.mark.asyncio
async def test_verify_chain_rejects_deleted_and_reordered_records(
    tmp_path: Path,
) -> None:
    await _write_chain(tmp_path / "audit.jsonl", count=3)
    records = _read_jsonl(tmp_path / "audit.jsonl")

    assert verify_audit_chain(records[1:]) is False  # first record removed
    assert verify_audit_chain([records[1], records[0], records[2]]) is False


# ---------------------------------------------------------------------------
# FileAuditStore: tail recovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_file_store_resumes_chain_from_existing_file(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.jsonl"
    first_run = await _write_chain(audit_path)

    resumed = AuditLogger(FileAuditStore(audit_path))  # e.g. after process restart
    third = await resumed.audit("event.resumed", outcome="success")

    assert third["prev_hash"] == first_run[-1]["hash"]
    assert verify_audit_chain(_read_jsonl(audit_path)) is True


@pytest.mark.asyncio
async def test_file_store_last_hash_none_for_corrupt_or_empty_tail(
    tmp_path: Path,
) -> None:
    blank = tmp_path / "blank.jsonl"
    blank.write_text("\n   \n", encoding="utf-8")
    assert await FileAuditStore(blank).get_last_hash() is None

    corrupt = tmp_path / "corrupt.jsonl"
    corrupt.write_text('{"hash": "abc"}\n{{{not json\n', encoding="utf-8")
    assert await FileAuditStore(corrupt).get_last_hash() is None

    hashless = tmp_path / "hashless.jsonl"
    hashless.write_text('{"event_type": "x"}\n', encoding="utf-8")
    assert await FileAuditStore(hashless).get_last_hash() is None


@pytest.mark.asyncio
async def test_null_store_reports_record_id_and_no_history() -> None:
    store = NullAuditStore()

    assert await store.append({"id": "abc123"}) == "abc123"
    assert await store.get_last_hash() is None
    assert await store.close() is None


# ---------------------------------------------------------------------------
# RedisAuditStore: degradation without redis I/O
# ---------------------------------------------------------------------------


class _StubRedisClient:
    """Minimal async client double for the calls RedisAuditStore makes."""

    def __init__(
        self,
        *,
        xadd_error: Exception | None = None,
        xrevrange_rows: list[Any] | None = None,
        aclose_error: Exception | None = None,
    ) -> None:
        self.xadd_error = xadd_error
        self.xrevrange_rows = xrevrange_rows or []
        self.aclose_error = aclose_error
        self.closed = False

    async def xadd(self, *args: Any, **kwargs: Any) -> str:
        if self.xadd_error is not None:
            raise self.xadd_error
        return "1-1"

    async def xrevrange(self, *args: Any, **kwargs: Any) -> list[Any]:
        return self.xrevrange_rows

    async def aclose(self) -> None:
        if self.aclose_error is not None:
            raise self.aclose_error
        self.closed = True


def _connected_store(client: _StubRedisClient) -> RedisAuditStore:
    store = RedisAuditStore("redis://unused:0")
    store._client = client
    store._connected = True
    return store


@pytest.mark.asyncio
async def test_redis_store_noops_when_never_connected() -> None:
    store = RedisAuditStore("redis://unused:0")

    assert await store.append({"hash": "h", "event_type": "e", "timestamp": "t"}) == ""
    assert await store.get_last_hash() is None


@pytest.mark.asyncio
async def test_redis_store_demotes_to_disconnected_on_append_error() -> None:
    store = _connected_store(_StubRedisClient(xadd_error=OSError("gone")))

    result = await store.append({"hash": "h", "event_type": "e", "timestamp": "t"})

    assert result == ""
    assert store.is_connected is False


@pytest.mark.asyncio
async def test_redis_store_last_hash_falls_back_to_record_json() -> None:
    record_json = json.dumps({"hash": "deadbeef"})
    store = _connected_store(
        _StubRedisClient(xrevrange_rows=[("1-1", {"record": record_json})])
    )

    assert await store.get_last_hash() == "deadbeef"

    empty_fields = _connected_store(_StubRedisClient(xrevrange_rows=[("1-1", {})]))
    assert await empty_fields.get_last_hash() is None


@pytest.mark.asyncio
async def test_redis_store_close_releases_client_even_on_error() -> None:
    failing = _connected_store(_StubRedisClient(aclose_error=RuntimeError("boom")))

    await failing.close()

    assert failing._client is None
    assert failing.is_connected is False


# ---------------------------------------------------------------------------
# build_audit_logger: redis backend fallback
# ---------------------------------------------------------------------------


def _settings_stub(tmp_path: Path, backend: str) -> SimpleNamespace:
    return SimpleNamespace(
        audit_log_enabled=True,
        audit_log_backend=backend,
        audit_log_max_events=10,
        redis_url="redis://unused:0",
        audit_log_redis_stream="test:audit",
        audit_log_file_path=str(tmp_path / "audit.jsonl"),
    )


@pytest.mark.asyncio
async def test_build_falls_back_to_file_when_redis_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_connect(**kwargs: Any) -> RedisAuditStore:
        return RedisAuditStore("redis://unused:0")  # never connected

    monkeypatch.setattr(audit_module.RedisAuditStore, "connect", fake_connect)

    logger = await build_audit_logger(_settings_stub(tmp_path, "redis"))

    assert isinstance(logger.store, FileAuditStore)
    assert logger.enabled is True


@pytest.mark.asyncio
async def test_build_uses_redis_store_when_connected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _connected_store(_StubRedisClient())

    async def fake_connect(**kwargs: Any) -> RedisAuditStore:
        return store

    monkeypatch.setattr(audit_module.RedisAuditStore, "connect", fake_connect)

    logger = await build_audit_logger(_settings_stub(tmp_path, "redis"))

    assert logger.store is store


# ---------------------------------------------------------------------------
# audit_request_event: never breaks the request path
# ---------------------------------------------------------------------------


def _request_stub(audit_logger: Any) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(audit_logger=audit_logger)),
        client=SimpleNamespace(host="203.0.113.7"),
        headers={"x-request-id": "req-42"},
        url=SimpleNamespace(path="/api/run"),
    )


@pytest.mark.asyncio
async def test_request_event_returns_quietly_without_logger() -> None:
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    assert await audit_request_event(request, "auth.failed", outcome="failure") is None


@pytest.mark.asyncio
async def test_request_event_swallows_store_failure() -> None:
    class _ExplodingStore:
        async def append(self, record: dict[str, Any]) -> str:
            raise OSError("disk full")

        async def get_last_hash(self) -> str | None:
            return None

        async def close(self) -> None:
            return None

    request = _request_stub(AuditLogger(_ExplodingStore()))

    # Must not raise even though the underlying append fails.
    await audit_request_event(request, "workflow.run_requested", outcome="success")


@pytest.mark.asyncio
async def test_request_event_records_request_id_and_client_ip(
    tmp_path: Path,
) -> None:
    audit_path = tmp_path / "audit.jsonl"
    request = _request_stub(AuditLogger(FileAuditStore(audit_path)))

    await audit_request_event(
        request,
        "auth.succeeded",
        outcome="success",
        metadata={"scheme": "api_key"},
    )

    (record,) = _read_jsonl(audit_path)
    assert record["request_id"] == "req-42"
    assert record["metadata"]["client_ip"] == "203.0.113.7"
    assert record["metadata"]["scheme"] == "api_key"


# ---------------------------------------------------------------------------
# JSON safety helpers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_serializable_metadata_is_coerced_not_fatal(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.jsonl"
    logger = AuditLogger(FileAuditStore(audit_path))

    record = await logger.audit(
        "event.messy",
        outcome="success",
        metadata={"obj": object(), "tags": {"b", "a"}},
    )

    round_tripped = json.loads(json.dumps(record["metadata"]))
    assert isinstance(round_tripped["obj"], str)
    assert sorted(round_tripped["tags"]) == ["a", "b"]
    assert verify_audit_chain(_read_jsonl(audit_path)) is True


def test_decode_redis_value_handles_bytes_and_str() -> None:
    assert audit_module._decode_redis_value(b"abc") == "abc"
    assert audit_module._decode_redis_value("abc") == "abc"
    assert audit_module._decode_redis_value(7) == "7"
