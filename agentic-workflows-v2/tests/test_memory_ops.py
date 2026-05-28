"""Tests for tools/builtin/memory_ops.py — ADR-008 Phase 3.

Covers the _FileMemoryStore and six tool wrappers (upsert, get, list,
search, delete, clear).  All tests use ``tmp_path`` for isolation so
no real filesystem state leaks between runs.

Test tiers (per ADR-008):
  Tier 1 — error paths, branching, edge cases
  Tier 2 — happy-path contracts, boundary conditions
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from agentic_v2.tools.builtin.memory_ops import (
    MemoryClearTool,
    MemoryDeleteTool,
    MemoryGetTool,
    MemoryListTool,
    MemorySearchTool,
    MemoryUpsertTool,
    _FileMemoryStore,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> _FileMemoryStore:
    """Return a fresh file-backed memory store rooted in a temp dir."""
    return _FileMemoryStore(storage_path=str(tmp_path / "mem.json"))


@pytest.fixture()
def _env_memory_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set AGENTIC_MEMORY_PATH so tool constructors point to tmp_path."""
    p = tmp_path / "env_mem.json"
    monkeypatch.setenv("AGENTIC_MEMORY_PATH", str(p))
    return p


def _make_tool(tool_cls: type, tmp_path: Path) -> Any:
    """Instantiate a memory tool with its store redirected to tmp_path."""
    tool = tool_cls()
    tool._store = _FileMemoryStore(storage_path=str(tmp_path / "tool_mem.json"))
    return tool


# ===================================================================
# _FileMemoryStore — unit tests
# ===================================================================


class TestFileMemoryStoreUpsert:
    """Tier 1/2: upsert branching and contracts."""

    def test_upsert_creates_entry(self, store: _FileMemoryStore) -> None:
        """Tier 2: basic upsert creates a new entry with timestamps."""
        result = store.upsert("k1", "hello")
        assert result["key"] == "k1"
        entry = result["entry"]
        assert entry["value"] == "hello"
        assert entry["tags"] == []
        assert isinstance(entry["created_at_ms"], int)
        assert entry["created_at_ms"] == entry["updated_at_ms"]

    def test_upsert_preserves_created_at_on_update(
        self, store: _FileMemoryStore
    ) -> None:
        """Tier 1: updating a key must keep the original created_at_ms."""
        first = store.upsert("k1", "v1")
        created = first["entry"]["created_at_ms"]
        second = store.upsert("k1", "v2")
        assert second["entry"]["created_at_ms"] == created
        assert second["entry"]["value"] == "v2"

    def test_upsert_empty_key_raises(self, store: _FileMemoryStore) -> None:
        """Tier 1: empty key must raise ValueError."""
        with pytest.raises(ValueError, match="non-empty"):
            store.upsert("   ", "value")

    def test_upsert_with_tags(self, store: _FileMemoryStore) -> None:
        """Tier 2: tags are stored and empty strings are filtered."""
        result = store.upsert("k1", 42, tags=["a", "", "b"])
        assert result["entry"]["tags"] == ["a", "b"]

    def test_upsert_non_serializable_value_falls_back_to_str(
        self, store: _FileMemoryStore
    ) -> None:
        """Tier 1: non-JSON-serializable values are coerced to str."""
        result = store.upsert("k1", {1, 2, 3})
        # Sets are not JSON-serializable; should become their str repr
        assert isinstance(result["entry"]["value"], str)


class TestFileMemoryStoreGet:
    """Tier 2: get contracts."""

    def test_get_existing_key(self, store: _FileMemoryStore) -> None:
        """Tier 2: get returns found=True and the stored entry."""
        store.upsert("k1", "v1")
        result = store.get("k1")
        assert result["found"] is True
        assert result["entry"]["value"] == "v1"

    def test_get_missing_key(self, store: _FileMemoryStore) -> None:
        """Tier 2: get returns found=False for a key that does not exist."""
        result = store.get("nope")
        assert result["found"] is False
        assert result["entry"] is None


class TestFileMemoryStoreDelete:
    """Tier 1: delete branching."""

    def test_delete_existing(self, store: _FileMemoryStore) -> None:
        """Tier 2: deleting an existing key returns deleted=True."""
        store.upsert("k1", "v1")
        result = store.delete("k1")
        assert result["deleted"] is True
        assert store.get("k1")["found"] is False

    def test_delete_missing(self, store: _FileMemoryStore) -> None:
        """Tier 1: deleting a missing key returns deleted=False (idempotent)."""
        result = store.delete("nope")
        assert result["deleted"] is False


class TestFileMemoryStoreClear:
    """Tier 2: clear contract."""

    def test_clear_removes_all(self, store: _FileMemoryStore) -> None:
        """Tier 2: clear empties the entire store."""
        store.upsert("a", 1)
        store.upsert("b", 2)
        result = store.clear()
        assert result["cleared"] is True
        assert store.list()["count"] == 0


class TestFileMemoryStoreList:
    """Tier 1/2: list filtering and limit."""

    def test_list_all_keys_sorted(self, store: _FileMemoryStore) -> None:
        """Tier 2: list returns keys in sorted order."""
        for k in ["beta", "alpha", "gamma"]:
            store.upsert(k, k)
        result = store.list()
        assert result["keys"] == ["alpha", "beta", "gamma"]

    def test_list_prefix_filter(self, store: _FileMemoryStore) -> None:
        """Tier 1: prefix narrows the result set."""
        for k in ["user.name", "user.email", "system.version"]:
            store.upsert(k, k)
        result = store.list(prefix="user.")
        assert result["keys"] == ["user.email", "user.name"]

    @pytest.mark.parametrize("limit, expected", [(1, 1), (2, 2), (100, 3)])
    def test_list_limit(
        self, store: _FileMemoryStore, limit: int, expected: int
    ) -> None:
        """Tier 1: limit caps the number of returned keys."""
        for k in ["a", "b", "c"]:
            store.upsert(k, k)
        result = store.list(limit=limit)
        assert len(result["keys"]) == expected

    def test_list_zero_limit_uses_default(self, store: _FileMemoryStore) -> None:
        """Tier 1: limit=0 is falsy and falls back to default (100)."""
        for k in ["a", "b"]:
            store.upsert(k, k)
        result = store.list(limit=0)
        # 0 is falsy -> `int(0 or 100)` = 100, so all keys returned
        assert len(result["keys"]) == 2


class TestFileMemoryStoreSearch:
    """Tier 1: search branching and edge cases."""

    def test_search_by_key(self, store: _FileMemoryStore) -> None:
        """Tier 2: search matches on key substring."""
        store.upsert("my_secret", "data")
        result = store.search("secret")
        assert result["count"] == 1

    def test_search_by_value(self, store: _FileMemoryStore) -> None:
        """Tier 2: search matches on value content."""
        store.upsert("k", {"msg": "hello world"})
        result = store.search("hello")
        assert result["count"] == 1

    def test_search_by_tags(self, store: _FileMemoryStore) -> None:
        """Tier 2: search matches on tags."""
        store.upsert("k", "v", tags=["debug", "error"])
        result = store.search("debug")
        assert result["count"] == 1

    def test_search_empty_query_raises(self, store: _FileMemoryStore) -> None:
        """Tier 1: empty query must raise ValueError."""
        with pytest.raises(ValueError, match="non-empty"):
            store.search("   ")

    def test_search_limit_respected(self, store: _FileMemoryStore) -> None:
        """Tier 1: search stops at the limit."""
        for i in range(5):
            store.upsert(f"item_{i}", f"match_{i}")
        result = store.search("match", limit=2)
        assert result["count"] == 2

    def test_search_case_insensitive(self, store: _FileMemoryStore) -> None:
        """Tier 1: search is case-insensitive."""
        store.upsert("KEY", "VALUE")
        result = store.search("key")
        assert result["count"] == 1


class TestFileMemoryStoreFilePersistence:
    """Tier 1: file-system edge cases."""

    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """Tier 1: first load on a missing file returns {}."""
        s = _FileMemoryStore(storage_path=str(tmp_path / "nonexistent.json"))
        assert s.list()["count"] == 0

    def test_load_empty_file_returns_empty(self, tmp_path: Path) -> None:
        """Tier 1: an empty file is treated as an empty store."""
        f = tmp_path / "empty.json"
        f.write_text("", encoding="utf-8")
        s = _FileMemoryStore(storage_path=str(f))
        assert s.list()["count"] == 0

    def test_env_var_path(
        self,
        _env_memory_path: Path,
    ) -> None:
        """Tier 1: AGENTIC_MEMORY_PATH env var overrides the default."""
        s = _FileMemoryStore()
        assert s.path == _env_memory_path.resolve()


# ===================================================================
# Tool wrappers — async execute() tests
# ===================================================================


class TestMemoryUpsertTool:
    """Tier 2: upsert tool contract."""

    async def test_execute_success(self, tmp_path: Path) -> None:
        """Tier 2: successful upsert returns success=True with data."""
        tool = _make_tool(MemoryUpsertTool, tmp_path)
        result = await tool.execute(key="k", value="v")
        assert result.success is True
        assert result.data["key"] == "k"

    async def test_execute_empty_key_returns_failure(self, tmp_path: Path) -> None:
        """Tier 1: empty key yields success=False with error message."""
        tool = _make_tool(MemoryUpsertTool, tmp_path)
        result = await tool.execute(key="", value="v")
        assert result.success is False
        assert "non-empty" in result.error

    async def test_name_and_description(self) -> None:
        """Tier 2: tool metadata is correct."""
        tool = MemoryUpsertTool()
        assert tool.name == "memory_upsert"
        assert (
            "upsert" in tool.description.lower() or "create" in tool.description.lower()
        )


class TestMemoryGetTool:
    """Tier 2: get tool contract."""

    async def test_execute_found(self, tmp_path: Path) -> None:
        """Tier 2: get returns found=True for an existing key."""
        tool = _make_tool(MemoryGetTool, tmp_path)
        tool._store.upsert("k1", "v1")
        result = await tool.execute(key="k1")
        assert result.success is True
        assert result.data["found"] is True

    async def test_execute_not_found(self, tmp_path: Path) -> None:
        """Tier 2: get returns found=False for a missing key."""
        tool = _make_tool(MemoryGetTool, tmp_path)
        result = await tool.execute(key="missing")
        assert result.success is True
        assert result.data["found"] is False


class TestMemoryDeleteTool:
    """Tier 1: delete tool branching."""

    async def test_execute_delete_existing(self, tmp_path: Path) -> None:
        """Tier 2: deleting existing key returns deleted=True."""
        tool = _make_tool(MemoryDeleteTool, tmp_path)
        tool._store.upsert("k", "v")
        result = await tool.execute(key="k")
        assert result.success is True
        assert result.data["deleted"] is True

    async def test_execute_delete_missing(self, tmp_path: Path) -> None:
        """Tier 1: deleting missing key returns deleted=False."""
        tool = _make_tool(MemoryDeleteTool, tmp_path)
        result = await tool.execute(key="nope")
        assert result.success is True
        assert result.data["deleted"] is False


class TestMemoryClearTool:
    """Tier 1: clear tool confirm guard."""

    async def test_clear_without_confirm_refused(self, tmp_path: Path) -> None:
        """Tier 1: clear without confirm=True returns failure."""
        tool = _make_tool(MemoryClearTool, tmp_path)
        result = await tool.execute(confirm=False)
        assert result.success is False
        assert "confirm" in result.error.lower()

    async def test_clear_with_confirm(self, tmp_path: Path) -> None:
        """Tier 2: clear with confirm=True succeeds."""
        tool = _make_tool(MemoryClearTool, tmp_path)
        tool._store.upsert("k", "v")
        result = await tool.execute(confirm=True)
        assert result.success is True
        assert result.data["cleared"] is True


class TestMemoryListTool:
    """Tier 2: list tool contract."""

    async def test_list_returns_keys(self, tmp_path: Path) -> None:
        """Tier 2: list returns stored keys."""
        tool = _make_tool(MemoryListTool, tmp_path)
        tool._store.upsert("a", 1)
        tool._store.upsert("b", 2)
        result = await tool.execute()
        assert result.success is True
        assert result.data["count"] == 2


class TestMemorySearchTool:
    """Tier 1: search tool error path."""

    async def test_search_empty_query_returns_failure(self, tmp_path: Path) -> None:
        """Tier 1: empty query yields success=False."""
        tool = _make_tool(MemorySearchTool, tmp_path)
        result = await tool.execute(query="")
        assert result.success is False
        assert "non-empty" in result.error

    async def test_search_match(self, tmp_path: Path) -> None:
        """Tier 2: search returns matching entries."""
        tool = _make_tool(MemorySearchTool, tmp_path)
        tool._store.upsert("user.name", "Alice")
        result = await tool.execute(query="alice")
        assert result.success is True
        assert result.data["count"] == 1
