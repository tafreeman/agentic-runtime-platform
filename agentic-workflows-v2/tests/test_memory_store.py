"""Tests for MemoryStoreProtocol implementations.

Covers:
- InMemoryStore (core/memory.py) — full CRUD + search + list_keys

TDD: Tests written FIRST, then implementations.
"""

from __future__ import annotations

import pytest

from agentic_v2.core.memory import InMemoryStore, MemoryStoreProtocol

# ── InMemoryStore Tests ──────────────────────────────────────────────


class TestInMemoryStoreProtocolConformance:
    """Verify InMemoryStore satisfies MemoryStoreProtocol via runtime_checkable."""

    def test_protocol_conformance(self) -> None:
        store = InMemoryStore()
        assert isinstance(store, MemoryStoreProtocol)


class TestInMemoryStoreStoreAndRetrieve:
    """Store and retrieve values by key."""

    @pytest.mark.asyncio
    async def test_store_and_retrieve_string(self) -> None:
        store = InMemoryStore()
        await store.store("key1", "value1")
        result = await store.retrieve("key1")
        assert result == "value1"

    @pytest.mark.asyncio
    async def test_store_and_retrieve_dict(self) -> None:
        store = InMemoryStore()
        data = {"name": "test", "count": 42}
        await store.store("key1", data)
        result = await store.retrieve("key1")
        assert result == data

    @pytest.mark.asyncio
    async def test_store_and_retrieve_list(self) -> None:
        store = InMemoryStore()
        data = [1, 2, 3]
        await store.store("key1", data)
        result = await store.retrieve("key1")
        assert result == data

    @pytest.mark.asyncio
    async def test_store_overwrites_existing(self) -> None:
        store = InMemoryStore()
        await store.store("key1", "original")
        await store.store("key1", "updated")
        result = await store.retrieve("key1")
        assert result == "updated"


class TestInMemoryStoreRetrieveMissing:
    """Retrieve returns None for missing keys."""

    @pytest.mark.asyncio
    async def test_retrieve_missing_returns_none(self) -> None:
        store = InMemoryStore()
        result = await store.retrieve("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_retrieve_after_delete_returns_none(self) -> None:
        store = InMemoryStore()
        await store.store("key1", "value1")
        await store.delete("key1")
        result = await store.retrieve("key1")
        assert result is None


class TestInMemoryStoreSearch:
    """Search finds matches by case-insensitive substring on str(value)."""

    @pytest.mark.asyncio
    async def test_search_finds_matches(self) -> None:
        store = InMemoryStore()
        await store.store("k1", "Hello World")
        await store.store("k2", "hello there")
        await store.store("k3", "goodbye")

        results = await store.search("hello")
        keys = [r["key"] for r in results]
        assert "k1" in keys
        assert "k2" in keys
        assert "k3" not in keys

    @pytest.mark.asyncio
    async def test_search_case_insensitive(self) -> None:
        store = InMemoryStore()
        await store.store("k1", "UPPERCASE")
        await store.store("k2", "lowercase")

        results = await store.search("upper")
        assert len(results) == 1
        assert results[0]["key"] == "k1"

    @pytest.mark.asyncio
    async def test_search_empty_returns_empty(self) -> None:
        store = InMemoryStore()
        results = await store.search("anything")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_no_matches_returns_empty(self) -> None:
        store = InMemoryStore()
        await store.store("k1", "apple")
        await store.store("k2", "banana")
        results = await store.search("cherry")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_respects_top_k(self) -> None:
        store = InMemoryStore()
        for i in range(10):
            await store.store(f"k{i}", f"match item {i}")

        results = await store.search("match", top_k=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_search_result_structure(self) -> None:
        store = InMemoryStore()
        await store.store("k1", "search target", metadata={"tag": "test"})

        results = await store.search("target")
        assert len(results) == 1
        result = results[0]
        assert result["key"] == "k1"
        assert result["value"] == "search target"
        assert "score" in result
        assert result["metadata"] == {"tag": "test"}

    @pytest.mark.asyncio
    async def test_search_sorted_by_timestamp_descending(self) -> None:
        """More recently stored items should appear first."""
        store = InMemoryStore()
        await store.store("old", "common term")
        await store.store("new", "common term")

        results = await store.search("common")
        assert len(results) == 2
        # newest first
        assert results[0]["key"] == "new"
        assert results[1]["key"] == "old"


class TestInMemoryStoreDelete:
    """Delete removes entries and returns correct boolean."""

    @pytest.mark.asyncio
    async def test_delete_existing(self) -> None:
        store = InMemoryStore()
        await store.store("key1", "value1")
        result = await store.delete("key1")
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_missing_returns_false(self) -> None:
        store = InMemoryStore()
        result = await store.delete("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_removes_from_search(self) -> None:
        store = InMemoryStore()
        await store.store("k1", "searchable")
        await store.delete("k1")
        results = await store.search("searchable")
        assert results == []


class TestInMemoryStoreListKeys:
    """List keys with optional prefix filtering."""

    @pytest.mark.asyncio
    async def test_list_keys(self) -> None:
        store = InMemoryStore()
        await store.store("alpha", "a")
        await store.store("beta", "b")
        await store.store("gamma", "g")

        keys = await store.list_keys()
        assert set(keys) == {"alpha", "beta", "gamma"}

    @pytest.mark.asyncio
    async def test_list_keys_empty_store(self) -> None:
        store = InMemoryStore()
        keys = await store.list_keys()
        assert keys == []

    @pytest.mark.asyncio
    async def test_list_keys_with_prefix(self) -> None:
        store = InMemoryStore()
        await store.store("user:1", "Alice")
        await store.store("user:2", "Bob")
        await store.store("session:1", "s1")

        keys = await store.list_keys(prefix="user:")
        assert set(keys) == {"user:1", "user:2"}

    @pytest.mark.asyncio
    async def test_list_keys_with_prefix_no_match(self) -> None:
        store = InMemoryStore()
        await store.store("user:1", "Alice")

        keys = await store.list_keys(prefix="session:")
        assert keys == []


class TestInMemoryStoreMetadata:
    """Metadata is preserved through store/retrieve/search."""

    @pytest.mark.asyncio
    async def test_metadata_preserved(self) -> None:
        store = InMemoryStore()
        meta = {"source": "test", "priority": 1}
        await store.store("key1", "value1", metadata=meta)

        # Verify metadata appears in search results
        results = await store.search("value1")
        assert len(results) == 1
        assert results[0]["metadata"] == meta

    @pytest.mark.asyncio
    async def test_default_metadata_is_empty_dict(self) -> None:
        store = InMemoryStore()
        await store.store("key1", "value1")

        results = await store.search("value1")
        assert len(results) == 1
        assert results[0]["metadata"] == {}
