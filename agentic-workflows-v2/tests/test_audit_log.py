"""Tests for tamper-evident server audit logging."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

_PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "agentic_v2"


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_audit_module():
    """Load audit_log without executing the broad agentic_v2 package exports."""
    package = types.ModuleType("agentic_v2")
    package.__path__ = [str(_PACKAGE_ROOT)]  # type: ignore[attr-defined]
    sys.modules.setdefault("agentic_v2", package)

    server_package = types.ModuleType("agentic_v2.server")
    server_package.__path__ = [str(_PACKAGE_ROOT / "server")]  # type: ignore[attr-defined]
    sys.modules.setdefault("agentic_v2.server", server_package)

    # Preserve an already-imported ``agentic_v2.settings``. ``_load_module``
    # assigns ``sys.modules[name]`` unconditionally, so calling it here would
    # REPLACE a settings module the rest of the suite already imported with a
    # second copy that owns a distinct ``get_settings`` lru_cache. That split
    # cache is invisible to the conftest cache-reset (which holds the original
    # reference), so flag-sensitive tests (AGENTIC_NO_LLM / AGENTIC_EK_PROVIDER)
    # read a stale flag and fail in full-suite order (ADR-023 B-1). Only load
    # from file when settings is genuinely absent (isolated single-module run).
    if "agentic_v2.settings" not in sys.modules:
        _load_module("agentic_v2.settings", _PACKAGE_ROOT / "settings.py")
    return _load_module(
        "agentic_v2.server.audit_log",
        _PACKAGE_ROOT / "server" / "audit_log.py",
    )


audit_module = _load_audit_module()
AuditLogger = audit_module.AuditLogger
AuditStore = audit_module.AuditStore
FileAuditStore = audit_module.FileAuditStore
NullAuditStore = audit_module.NullAuditStore
RedisAuditStore = audit_module.RedisAuditStore
_GENESIS_HASH = audit_module._GENESIS_HASH
_REDIS_AVAILABLE = audit_module._REDIS_AVAILABLE
build_audit_logger = audit_module.build_audit_logger
compute_audit_hash = audit_module.compute_audit_hash
verify_audit_chain = audit_module.verify_audit_chain


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.asyncio
async def test_audit_record_structure_and_hash_chain(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.jsonl"
    logger = AuditLogger(FileAuditStore(audit_path))

    first = await logger.audit(
        "auth.succeeded",
        outcome="success",
        actor={"type": "api_key"},
        target={"path": "/api/run"},
    )
    second = await logger.audit(
        "workflow.run_requested",
        outcome="success",
        run_id="run-1",
        metadata={"adapter": "native"},
    )

    records = _read_jsonl(audit_path)
    assert records == [first, second]
    assert first["schema_version"] == "audit.v1"
    assert first["prev_hash"] == _GENESIS_HASH
    assert first["hash"] == compute_audit_hash(first)
    assert second["prev_hash"] == first["hash"]
    assert verify_audit_chain(records) is True


@pytest.mark.asyncio
async def test_file_audit_store_growth_is_append_only(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.jsonl"
    logger = AuditLogger(FileAuditStore(audit_path))

    await logger.audit("auth.failed", outcome="failure")
    first_bytes = audit_path.read_bytes()

    await logger.audit("auth.succeeded", outcome="success")
    second_bytes = audit_path.read_bytes()

    assert len(second_bytes) > len(first_bytes)
    assert second_bytes.startswith(first_bytes)
    assert len(_read_jsonl(audit_path)) == 2


class _FlakyAuditStore:
    """Audit store whose ``append`` can be toggled to fail (C-09 regression)."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self.fail_next = False

    async def append(self, record: dict[str, Any]) -> str:
        if self.fail_next:
            raise OSError("disk full")
        self.records.append(record)
        return str(len(self.records))

    async def get_last_hash(self) -> str | None:
        return self.records[-1]["hash"] if self.records else None

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_last_hash_not_advanced_when_append_fails() -> None:
    store = _FlakyAuditStore()
    logger = AuditLogger(store)

    first = await logger.audit("auth.succeeded", outcome="success")
    hash_before_failure = logger._last_hash
    assert hash_before_failure == first["hash"]

    store.fail_next = True
    with pytest.raises(OSError, match="disk full"):
        await logger.audit("auth.failed", outcome="failure")

    # The failed record must not advance the in-memory chain: the next durable
    # record has to chain off the last persisted hash, not an orphaned one.
    assert logger._last_hash == hash_before_failure
    assert len(store.records) == 1

    store.fail_next = False
    third = await logger.audit("workflow.run_requested", outcome="success")
    assert third["prev_hash"] == hash_before_failure
    assert len(store.records) == 2
    assert verify_audit_chain(store.records) is True


@pytest.mark.skipif(not _REDIS_AVAILABLE, reason="redis package not installed")
@pytest.mark.asyncio
async def test_redis_audit_store_uses_xadd_maxlen_with_fakeredis() -> None:
    fakeredis = pytest.importorskip("fakeredis")

    class SpyRedis:
        def __init__(self) -> None:
            self.client = fakeredis.FakeAsyncRedis(decode_responses=True)
            self.xadd_calls: list[dict[str, Any]] = []

        async def xadd(self, *args: Any, **kwargs: Any) -> str:
            self.xadd_calls.append({"args": args, "kwargs": kwargs})
            return await self.client.xadd(*args, **kwargs)

        async def xrevrange(self, *args: Any, **kwargs: Any) -> Any:
            return await self.client.xrevrange(*args, **kwargs)

        async def xrange(self, *args: Any, **kwargs: Any) -> Any:
            return await self.client.xrange(*args, **kwargs)

        async def aclose(self) -> None:
            await self.client.aclose()

    spy = SpyRedis()
    store = RedisAuditStore(
        redis_url="redis://fake",
        stream_name="audit:test",
        max_events=2,
    )
    store._client = spy
    store._connected = True
    logger = AuditLogger(store)

    for index in range(3):
        await logger.audit("workflow.run_requested", metadata={"index": index})

    entries = await spy.xrange("audit:test")
    assert entries
    assert spy.xadd_calls[-1]["kwargs"]["maxlen"] == 2
    assert spy.xadd_calls[-1]["kwargs"]["approximate"] is True
    assert await store.get_last_hash() == json.loads(entries[-1][1]["record"])["hash"]
    await store.close()


@pytest.mark.asyncio
async def test_concurrent_writes_preserve_valid_hash_chain(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.jsonl"
    logger = AuditLogger(FileAuditStore(audit_path))

    async def emit(index: int) -> None:
        await logger.audit("evaluation.dataset_previewed", metadata={"index": index})

    await asyncio.gather(*(emit(index) for index in range(25)))

    records = _read_jsonl(audit_path)
    assert len(records) == 25
    assert verify_audit_chain(records) is True
    assert len({record["hash"] for record in records}) == 25


def test_file_audit_store_implements_protocol(tmp_path: Path) -> None:
    assert isinstance(FileAuditStore(tmp_path / "audit.jsonl"), AuditStore)
    assert isinstance(NullAuditStore(), AuditStore)


@pytest.mark.asyncio
async def test_build_audit_logger_from_file_settings(tmp_path: Path) -> None:
    class SettingsStub:
        audit_log_enabled = True
        audit_log_backend = "file"
        audit_log_file_path = str(tmp_path / "audit.jsonl")
        audit_log_redis_stream = "audit:test"
        audit_log_max_events = 10
        redis_url = None

    logger = await build_audit_logger(SettingsStub())
    await logger.audit("auth.succeeded", outcome="success")

    records = _read_jsonl(tmp_path / "audit.jsonl")
    assert len(records) == 1
    assert records[0]["event_type"] == "auth.succeeded"


@pytest.mark.asyncio
async def test_build_audit_logger_disabled_uses_noop_store() -> None:
    class SettingsStub:
        audit_log_enabled = False

    logger = await build_audit_logger(SettingsStub())
    record = await logger.audit("auth.failed", outcome="failure")

    assert logger.enabled is False
    assert record["prev_hash"] == _GENESIS_HASH
