"""Tier 0 persistent memory tools.

These provide a small, dependency-free, file-backed key/value store that agents
can use as long-lived memory across turns or runs.

Design goals:
- deterministic, fast, and dependency-free
- safe by default (fixed storage path via env var)
- JSON-serializable values (fallback to str)

Storage location:
- env: AGENTIC_MEMORY_PATH
- default: .agentic_memory.json (in current working directory)
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..base import BaseTool, ToolResult

MEMORY_KEY_LABEL = "Memory key"


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class _MemoryEntry:
    value: Any
    tags: list[str]
    created_at_ms: int
    updated_at_ms: int


class _FileMemoryStore:
    """A tiny persistent JSON store.

    This is intentionally simple. Concurrency is protected with a
    threading lock since file IO is synchronous and the operations are
    small.
    """

    def __init__(self, storage_path: str | None = None):
        from ...settings import get_settings

        env_path = (
            os.environ.get("AGENTIC_MEMORY_PATH") or get_settings().agentic_memory_path
        )
        self._path = Path(storage_path or env_path or ".agentic_memory.json").resolve()
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        raw = self._path.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        return json.loads(raw)

    def _save(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp_path.replace(self._path)

    def _normalize_value(self, value: Any) -> Any:
        try:
            json.dumps(value)
            return value
        except TypeError:
            return str(value)

    def upsert(
        self, key: str, value: Any, tags: list[str] | None = None
    ) -> dict[str, Any]:
        key = str(key).strip()
        if not key:
            raise ValueError("key must be a non-empty string")

        tags = [str(t) for t in (tags or []) if str(t).strip()]
        now = _now_ms()
        value_norm = self._normalize_value(value)

        with self._lock:
            data = self._load()
            existing = data.get(key)
            if isinstance(existing, dict) and "created_at_ms" in existing:
                created_at = int(existing.get("created_at_ms") or now)
            else:
                created_at = now

            entry = _MemoryEntry(
                value=value_norm,
                tags=tags,
                created_at_ms=created_at,
                updated_at_ms=now,
            )
            data[key] = {
                "value": entry.value,
                "tags": entry.tags,
                "created_at_ms": entry.created_at_ms,
                "updated_at_ms": entry.updated_at_ms,
            }
            self._save(data)

        return {"key": key, "entry": data[key]}

    def get(self, key: str) -> dict[str, Any]:
        key = str(key).strip()
        with self._lock:
            data = self._load()
            entry = data.get(key)
        return {"key": key, "found": entry is not None, "entry": entry}

    def delete(self, key: str) -> dict[str, Any]:
        key = str(key).strip()
        with self._lock:
            data = self._load()
            existed = key in data
            if existed:
                del data[key]
                self._save(data)
        return {"key": key, "deleted": existed}

    def clear(self) -> dict[str, Any]:
        with self._lock:
            self._save({})
        return {"cleared": True}

    def list(self, prefix: str = "", limit: int = 100) -> dict[str, Any]:
        prefix = (prefix or "").strip()
        limit = int(limit or 100)

        with self._lock:
            data = self._load()

        keys = sorted(data.keys())
        if prefix:
            keys = [k for k in keys if k.startswith(prefix)]
        keys = keys[: max(0, limit)]
        return {"keys": keys, "count": len(keys)}

    def search(self, query: str, limit: int = 10) -> dict[str, Any]:
        q = str(query).strip().lower()
        limit = int(limit or 10)
        if not q:
            raise ValueError("query must be a non-empty string")

        with self._lock:
            data = self._load()

        hits: list[dict[str, Any]] = []
        for key, entry in data.items():
            haystacks = self._entry_haystacks(key, entry)
            if any(q in h.lower() for h in haystacks):
                hits.append({"key": key, "entry": entry})
                if len(hits) >= limit:
                    break

        return {"query": q, "results": hits, "count": len(hits)}

    @staticmethod
    def _entry_haystacks(key: str, entry: Any) -> list[str]:
        """Build the searchable text fragments for one stored entry."""
        haystacks = [str(key)]
        if isinstance(entry, dict) and "value" in entry:
            try:
                haystacks.append(json.dumps(entry.get("value"), ensure_ascii=False))
            except TypeError:
                haystacks.append(str(entry.get("value")))
            tags = entry.get("tags")
            if tags:
                haystacks.append(" ".join(str(t) for t in tags))
        else:
            haystacks.append(str(entry))
        return haystacks


class _MemoryToolBase(BaseTool):
    """Base class for memory tools sharing a store."""

    def __init__(self):
        super().__init__()
        # Instantiate per-tool so env var overrides (AGENTIC_MEMORY_PATH) are
        # respected in tests and per-process configuration.
        self._store = _FileMemoryStore()


class MemoryUpsertTool(_MemoryToolBase):
    @property
    def name(self) -> str:
        return "memory_upsert"

    @property
    def description(self) -> str:
        return (
            "WRITE side of persistent key-value memory: create a new entry or "
            "overwrite an existing one at `key` with a JSON-serializable "
            "`value` (and optional `tags`). Upsert semantics — same key "
            "replaces, so it is idempotent. Use this to durably record a fact "
            "for later runs (a repo root, a known error). PREFER `memory_get` "
            "to read one key back, `memory_search` to find entries by content, "
            "and `memory_delete` to remove a single key."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "key": {
                "type": "string",
                "description": MEMORY_KEY_LABEL,
                "required": True,
            },
            "value": {
                "type": "object",
                "description": "JSON-serializable value",
                "required": True,
            },
            "tags": {
                "type": "array",
                "description": "Optional tags",
                "required": False,
            },
        }

    @property
    def examples(self) -> list[str]:
        return [
            "memory_upsert(key='repo.root', value='d:/source/agentic-workflows')",
            "memory_upsert(key='last_error', value={'msg': '...', 'file': 'x.py'}, tags=['debug'])",
        ]

    async def execute(
        self, key: str, value: Any, tags: list[str] | None = None
    ) -> ToolResult:
        try:
            result = self._store.upsert(key=key, value=value, tags=tags)
            return ToolResult(
                success=True, data=result, metadata={"path": str(self._store.path)}
            )
        except Exception as e:
            return ToolResult(
                success=False, error=str(e), metadata={"path": str(self._store.path)}
            )


class MemoryGetTool(_MemoryToolBase):
    @property
    def name(self) -> str:
        return "memory_get"

    @property
    def description(self) -> str:
        return (
            "READ one persistent memory entry by its EXACT `key`, returning its "
            "stored value (or a not-found result if the key is absent). This is "
            "a point lookup — you must already know the key. PREFER `memory_get` "
            "when you have the exact key; use `memory_search` to find entries by "
            "substring across keys/values, or `memory_list` to enumerate keys "
            "by prefix when you do not know the exact key."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "key": {
                "type": "string",
                "description": MEMORY_KEY_LABEL,
                "required": True,
            },
        }

    async def execute(self, key: str) -> ToolResult:
        try:
            result = self._store.get(key=key)
            return ToolResult(
                success=True, data=result, metadata={"path": str(self._store.path)}
            )
        except Exception as e:
            return ToolResult(
                success=False, error=str(e), metadata={"path": str(self._store.path)}
            )


class MemoryListTool(_MemoryToolBase):
    @property
    def name(self) -> str:
        return "memory_list"

    @property
    def description(self) -> str:
        return (
            "ENUMERATE persistent memory KEYS (names only, not values), "
            "optionally narrowed to those starting with `prefix` and capped by "
            "`limit` (default 100). Use this to discover what keys exist before "
            "reading or to browse a namespace like 'repo.*'. PREFER "
            "`memory_list` for key discovery by prefix; use `memory_search` to "
            "match against stored VALUES, and `memory_get` once you know the "
            "exact key you want."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "prefix": {
                "type": "string",
                "description": "Optional key prefix filter",
                "required": False,
            },
            "limit": {
                "type": "integer",
                "description": "Max keys to return (default 100)",
                "required": False,
            },
        }

    async def execute(self, prefix: str = "", limit: int = 100) -> ToolResult:
        try:
            result = self._store.list(prefix=prefix, limit=limit)
            return ToolResult(
                success=True, data=result, metadata={"path": str(self._store.path)}
            )
        except Exception as e:
            return ToolResult(
                success=False, error=str(e), metadata={"path": str(self._store.path)}
            )


class MemorySearchTool(_MemoryToolBase):
    @property
    def name(self) -> str:
        return "memory_search"

    @property
    def description(self) -> str:
        return (
            "FULL-TEXT lookup over persistent memory: case-insensitive substring "
            "match of `query` against both keys AND serialized values, returning "
            "up to `limit` matching entries (default 10). Use this when you "
            "remember some content but not the exact key. PREFER `memory_search` "
            "for content discovery; use `memory_list` to browse keys by prefix, "
            "or `memory_get` for a direct exact-key read."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "query": {
                "type": "string",
                "description": "Search query",
                "required": True,
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (default 10)",
                "required": False,
            },
        }

    async def execute(self, query: str, limit: int = 10) -> ToolResult:
        try:
            result = self._store.search(query=query, limit=limit)
            return ToolResult(
                success=True, data=result, metadata={"path": str(self._store.path)}
            )
        except Exception as e:
            return ToolResult(
                success=False, error=str(e), metadata={"path": str(self._store.path)}
            )


class MemoryDeleteTool(_MemoryToolBase):
    @property
    def name(self) -> str:
        return "memory_delete"

    @property
    def description(self) -> str:
        return (
            "Remove ONE persistent memory entry by its exact `key` "
            "(irreversible for that single key; absent keys are a no-op "
            "success). Scope is exactly one key — it never touches others. "
            "PREFER `memory_delete` to forget a single fact; use `memory_clear` "
            "(which demands confirm=true) only to wipe ALL entries at once."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "key": {
                "type": "string",
                "description": MEMORY_KEY_LABEL,
                "required": True,
            },
        }

    async def execute(self, key: str) -> ToolResult:
        try:
            result = self._store.delete(key=key)
            return ToolResult(
                success=True, data=result, metadata={"path": str(self._store.path)}
            )
        except Exception as e:
            return ToolResult(
                success=False, error=str(e), metadata={"path": str(self._store.path)}
            )


class MemoryClearTool(_MemoryToolBase):
    @property
    def name(self) -> str:
        return "memory_clear"

    @property
    def description(self) -> str:
        return (
            "DESTRUCTIVE bulk wipe: delete EVERY persistent memory entry. A "
            "guard requires `confirm=true`; any other value refuses and changes "
            "nothing. This empties the whole store and cannot be undone. PREFER "
            "`memory_delete` to remove a single key; reach for `memory_clear` "
            "only for a deliberate full reset."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "confirm": {
                "type": "boolean",
                "description": "Must be true to clear",
                "required": True,
            },
        }

    async def execute(self, confirm: bool) -> ToolResult:
        if confirm is not True:
            return ToolResult(
                success=False, error="Refusing to clear memory without confirm=true"
            )
        try:
            result = self._store.clear()
            return ToolResult(
                success=True, data=result, metadata={"path": str(self._store.path)}
            )
        except Exception as e:
            return ToolResult(
                success=False, error=str(e), metadata={"path": str(self._store.path)}
            )
