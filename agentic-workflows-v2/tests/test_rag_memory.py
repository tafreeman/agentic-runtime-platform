"""Tests for RAGMemoryStore — semantic search backed memory store.

TDD — verifies that RAGMemoryStore satisfies MemoryStoreProtocol and
all CRUD + search behaviours are correct when backed by InMemoryEmbedder
and InMemoryVectorStore.

Coverage areas:
- Protocol conformance
- store(): create, overwrite, metadata round-trip, _key_map / vectorstore sync
- retrieve(): known key, unknown key, metadata
- search(): empty store, key/value/score fields, top_k, score ordering
- delete(): known key, unknown key, state after deletion
- list_keys(): empty store, no-prefix, prefix filter, no-match prefix
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from agentic_v2.core.memory import MemoryStoreProtocol
from agentic_v2.rag.embeddings import InMemoryEmbedder
from agentic_v2.rag.memory import RAGMemoryStore
from agentic_v2.rag.vectorstore import InMemoryVectorStore

# ── Helpers ──────────────────────────────────────────────────────────


def _make_store(namespace: str = "test") -> RAGMemoryStore:
    """Return a fresh RAGMemoryStore backed by in-memory components."""
    return RAGMemoryStore(
        embedder=InMemoryEmbedder(dimensions=64),
        vectorstore=InMemoryVectorStore(),
        namespace=namespace,
    )


# ── Protocol conformance ─────────────────────────────────────────────


class TestProtocolConformance:
    """RAGMemoryStore must satisfy the MemoryStoreProtocol interface."""

    def test_isinstance_memory_store_protocol(self):
        """Isinstance check against the runtime-checkable protocol passes."""
        store = _make_store()
        assert isinstance(store, MemoryStoreProtocol)

    @pytest.mark.asyncio
    async def test_protocol_methods_are_callable(self):
        """All five protocol methods exist and are awaitable on a fresh store."""
        store = _make_store()
        # store() — returns None
        await store.store("k", "v")
        # retrieve() — returns value or None
        result = await store.retrieve("k")
        assert result == "v"
        # search() — returns list
        hits = await store.search("v")
        assert isinstance(hits, list)
        # list_keys() — returns list
        keys = await store.list_keys()
        assert isinstance(keys, list)
        # delete() — returns bool
        deleted = await store.delete("k")
        assert deleted is True


# ── store() ──────────────────────────────────────────────────────────


class TestStore:
    """Verify store() semantics."""

    @pytest.fixture
    async def empty_store(self) -> RAGMemoryStore:
        """Return an unpopulated store."""
        return _make_store()

    @pytest.mark.asyncio
    async def test_store_and_retrieve_value(self, empty_store: RAGMemoryStore):
        """Store() followed by retrieve() returns the original value."""
        await empty_store.store("fact:1", "Python was created by Guido")
        result = await empty_store.retrieve("fact:1")
        assert result == "Python was created by Guido"

    @pytest.mark.asyncio
    async def test_store_non_string_value(self, empty_store: RAGMemoryStore):
        """Store() accepts non-string values; retrieve() returns the original type."""
        await empty_store.store("count", 42)
        result = await empty_store.retrieve("count")
        assert result == 42
        assert isinstance(result, int)

    @pytest.mark.asyncio
    async def test_store_dict_value(self, empty_store: RAGMemoryStore):
        """Store() accepts dict values and retrieve() returns the same dict."""
        payload = {"agent": "coder", "status": "active"}
        await empty_store.store("agent:meta", payload)
        result = await empty_store.retrieve("agent:meta")
        assert result == payload

    @pytest.mark.asyncio
    async def test_store_with_no_metadata_defaults_to_empty_dict(
        self, empty_store: RAGMemoryStore
    ):
        """Omitting metadata stores an empty dict, not None."""
        await empty_store.store("k", "v")
        # Verify via list_keys that entry was persisted
        keys = await empty_store.list_keys()
        assert "k" in keys
        # Internal _key_map should hold empty dict for metadata
        _, _, stored_meta = empty_store._key_map["k"]
        assert stored_meta == {}

    @pytest.mark.asyncio
    async def test_store_metadata_persisted_in_key_map(
        self, empty_store: RAGMemoryStore
    ):
        """Metadata passed to store() is kept in _key_map for retrieve()."""
        await empty_store.store("doc:1", "content", metadata={"source": "wiki"})
        _, _, stored_meta = empty_store._key_map["doc:1"]
        assert stored_meta == {"source": "wiki"}

    @pytest.mark.asyncio
    async def test_store_populates_key_map(self, empty_store: RAGMemoryStore):
        """After store(), _key_map contains the key."""
        await empty_store.store("new-key", "hello")
        assert "new-key" in empty_store._key_map

    @pytest.mark.asyncio
    async def test_store_adds_entry_to_vectorstore(self, empty_store: RAGMemoryStore):
        """After store(), the underlying vectorstore has at least one entry."""
        await empty_store.store("entry", "some content for embedding")
        # If we search for something we should get back at least one result
        results = await empty_store.search("some content")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_overwrite_replaces_value(self, empty_store: RAGMemoryStore):
        """Storing to the same key twice replaces the value."""
        await empty_store.store("key", "original")
        await empty_store.store("key", "updated")
        result = await empty_store.retrieve("key")
        assert result == "updated"

    @pytest.mark.asyncio
    async def test_overwrite_cleans_up_old_key_map_entry(
        self, empty_store: RAGMemoryStore
    ):
        """After overwrite, _key_map has exactly one entry for the key."""
        await empty_store.store("key", "v1")
        old_doc_id = empty_store._key_map["key"][0]

        await empty_store.store("key", "v2")
        new_doc_id = empty_store._key_map["key"][0]

        # The doc_id must change — old entry was replaced
        assert old_doc_id != new_doc_id
        # Only one logical entry
        assert list(empty_store._key_map.keys()).count("key") == 1

    @pytest.mark.asyncio
    async def test_overwrite_removes_old_vectorstore_entry(
        self, empty_store: RAGMemoryStore
    ):
        """After overwrite the old vectorstore chunk is gone; search reflects new
        value."""
        await empty_store.store("key", "version one text")
        await empty_store.store("key", "version two text")

        results = await empty_store.search("version two text", top_k=5)
        # Must find the new entry
        values = [r["value"] for r in results]
        assert "version two text" in values

    @pytest.mark.asyncio
    async def test_overwrite_metadata_is_updated(self, empty_store: RAGMemoryStore):
        """Overwriting also updates stored metadata to the new value."""
        await empty_store.store("m", "v", metadata={"rev": 1})
        await empty_store.store("m", "v2", metadata={"rev": 2})
        _, _, meta = empty_store._key_map["m"]
        assert meta == {"rev": 2}

    @pytest.mark.asyncio
    async def test_store_multiple_distinct_keys(self, empty_store: RAGMemoryStore):
        """Multiple distinct keys can be stored independently."""
        await empty_store.store("a", "alpha")
        await empty_store.store("b", "beta")
        await empty_store.store("c", "gamma")

        assert await empty_store.retrieve("a") == "alpha"
        assert await empty_store.retrieve("b") == "beta"
        assert await empty_store.retrieve("c") == "gamma"


# ── retrieve() ───────────────────────────────────────────────────────


class TestRetrieve:
    """Verify retrieve() semantics."""

    @pytest.fixture
    async def populated_store(self) -> RAGMemoryStore:
        """Return a store with two entries."""
        store = _make_store()
        await store.store("greeting", "hello world", metadata={"lang": "en"})
        await store.store("farewell", "goodbye", metadata={"lang": "en"})
        return store

    @pytest.mark.asyncio
    async def test_retrieve_known_key_returns_value(
        self, populated_store: RAGMemoryStore
    ):
        """Retrieve() on an existing key returns the stored value."""
        value = await populated_store.retrieve("greeting")
        assert value == "hello world"

    @pytest.mark.asyncio
    async def test_retrieve_unknown_key_returns_none(
        self, populated_store: RAGMemoryStore
    ):
        """Retrieve() on a missing key returns None."""
        value = await populated_store.retrieve("no-such-key")
        assert value is None

    @pytest.mark.asyncio
    async def test_retrieve_empty_store_returns_none(self):
        """Retrieve() on an empty store returns None for any key."""
        store = _make_store()
        result = await store.retrieve("anything")
        assert result is None

    @pytest.mark.asyncio
    async def test_retrieve_does_not_consume_entry(
        self, populated_store: RAGMemoryStore
    ):
        """Retrieve() is non-destructive; repeated calls return the same value."""
        first = await populated_store.retrieve("greeting")
        second = await populated_store.retrieve("greeting")
        assert first == second == "hello world"

    @pytest.mark.asyncio
    async def test_retrieve_returns_correct_metadata_accessible_via_key_map(
        self, populated_store: RAGMemoryStore
    ):
        """_key_map exposes stored metadata for the key."""
        _, _, meta = populated_store._key_map["greeting"]
        assert meta == {"lang": "en"}


# ── search() ─────────────────────────────────────────────────────────


class TestSearch:
    """Verify search() semantics."""

    @pytest.fixture
    async def store_with_entries(self) -> RAGMemoryStore:
        """Return a store with several entries for search tests."""
        store = _make_store()
        await store.store(
            "python:creator",
            "Python was created by Guido van Rossum",
            metadata={"topic": "python"},
        )
        await store.store(
            "python:version",
            "Python 3 introduced many improvements",
            metadata={"topic": "python"},
        )
        await store.store(
            "rust:creator",
            "Rust was designed by Graydon Hoare at Mozilla",
            metadata={"topic": "rust"},
        )
        return store

    @pytest.mark.asyncio
    async def test_search_empty_store_returns_empty_list(self):
        """Search() on an empty store must return []."""
        store = _make_store()
        results = await store.search("anything")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_returns_list_of_dicts(
        self, store_with_entries: RAGMemoryStore
    ):
        """Search() must return a list of dicts."""
        results = await store_with_entries.search("Python programming language")
        assert isinstance(results, list)
        for item in results:
            assert isinstance(item, dict)

    @pytest.mark.asyncio
    async def test_search_result_has_required_fields(
        self, store_with_entries: RAGMemoryStore
    ):
        """Each search result dict must contain key, value, score, and metadata."""
        results = await store_with_entries.search("Python")
        assert len(results) >= 1
        for item in results:
            assert "key" in item
            assert "value" in item
            assert "score" in item
            assert "metadata" in item

    @pytest.mark.asyncio
    async def test_search_result_key_is_string(
        self, store_with_entries: RAGMemoryStore
    ):
        """Key field in each result must be a string."""
        results = await store_with_entries.search("Python")
        for item in results:
            assert isinstance(item["key"], str)

    @pytest.mark.asyncio
    async def test_search_result_score_is_float(
        self, store_with_entries: RAGMemoryStore
    ):
        """Score field in each result must be a float."""
        results = await store_with_entries.search("Python")
        for item in results:
            assert isinstance(item["score"], float)

    @pytest.mark.asyncio
    async def test_search_result_score_non_negative(
        self, store_with_entries: RAGMemoryStore
    ):
        """All returned scores must be >= 0.0 (cosine similarity clamped at 0)."""
        results = await store_with_entries.search("some query text")
        for item in results:
            assert item["score"] >= 0.0

    @pytest.mark.asyncio
    async def test_search_result_metadata_matches_stored(
        self, store_with_entries: RAGMemoryStore
    ):
        """The metadata in search results must match what was passed to store()."""
        results = await store_with_entries.search("Python was created")
        # Find the python:creator entry
        creator_hits = [r for r in results if r["key"] == "python:creator"]
        assert len(creator_hits) >= 1
        assert creator_hits[0]["metadata"] == {"topic": "python"}

    @pytest.mark.asyncio
    async def test_search_result_metadata_does_not_leak_memory_key(
        self, store_with_entries: RAGMemoryStore
    ):
        """The _memory_key injected into the vectorstore chunk must not appear in
        results."""
        results = await store_with_entries.search("Python")
        for item in results:
            assert "_memory_key" not in item["metadata"]

    @pytest.mark.asyncio
    async def test_search_respects_top_k(self):
        """Search() must return at most top_k results."""
        store = _make_store()
        for i in range(10):
            await store.store(f"key:{i}", f"entry number {i}")

        results = await store.search("entry number", top_k=3)
        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_search_top_k_one_returns_at_most_one(self):
        """top_k=1 limits results to one entry."""
        store = _make_store()
        await store.store("a", "some text alpha")
        await store.store("b", "some text beta")
        await store.store("c", "some text gamma")

        results = await store.search("some text", top_k=1)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_top_k_larger_than_store_returns_all(self):
        """top_k larger than the number of entries returns all entries."""
        store = _make_store()
        await store.store("x", "first entry")
        await store.store("y", "second entry")

        results = await store.search("entry", top_k=100)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_search_results_ordered_by_score_descending(self):
        """Results must be sorted highest score first."""
        store = _make_store()
        await store.store("one", "first stored value")
        await store.store("two", "second stored value")
        await store.store("three", "third stored value")

        results = await store.search("value", top_k=10)
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_search_returns_value_matching_key(
        self, store_with_entries: RAGMemoryStore
    ):
        """The value in each result must match what was stored for that key."""
        results = await store_with_entries.search("Python", top_k=10)
        for item in results:
            expected_value = await store_with_entries.retrieve(item["key"])
            assert item["value"] == expected_value

    @pytest.mark.asyncio
    async def test_search_score_uses_approx_for_exact_match(self):
        """Searching for the stored text itself should yield a high score (>0)."""
        store = _make_store()
        text = "the quick brown fox"
        await store.store("fox", text)
        results = await store.search(text, top_k=1)
        assert len(results) == 1
        assert results[0]["score"] > 0.0

    @pytest.mark.asyncio
    async def test_search_score_values_are_close_across_identical_calls(self):
        """Repeated identical searches yield the same scores (deterministic
        embedder)."""
        store = _make_store()
        await store.store("entry", "consistent content")

        r1 = await store.search("consistent content", top_k=1)
        r2 = await store.search("consistent content", top_k=1)

        assert len(r1) == 1
        assert len(r2) == 1
        assert math.isclose(r1[0]["score"], r2[0]["score"], rel_tol=1e-9)

    @pytest.mark.asyncio
    async def test_search_skips_chunks_without_memory_key_metadata(self):
        """Chunks lacking _memory_key in metadata must be silently skipped."""
        store = _make_store()
        await store.store("valid", "a real memory entry")

        # Inject a chunk into the vectorstore that has no _memory_key
        from agentic_v2.rag.contracts import Chunk

        orphan = Chunk(
            document_id="orphan-doc",
            chunk_index=0,
            content="orphan content",
            metadata={},  # no _memory_key
        )
        embedder = InMemoryEmbedder(dimensions=64)
        embedding = await embedder.embed([orphan.content])
        await store._vectorstore.add([orphan], embedding)

        # search() must not raise — orphan chunk is silently skipped
        results = await store.search("orphan content", top_k=10)
        result_keys = [r["key"] for r in results]
        # The orphan must not appear in results
        assert "orphan-doc" not in result_keys
        # The valid entry may or may not surface depending on similarity;
        # the important assertion is no KeyError / exception was raised.

    @pytest.mark.asyncio
    async def test_search_after_delete_does_not_return_deleted_entry(self):
        """Deleted entries must not appear in subsequent search results."""
        store = _make_store()
        await store.store("gone", "this entry will be deleted")
        await store.store("stays", "this entry remains")

        await store.delete("gone")

        results = await store.search("entry", top_k=10)
        keys = [r["key"] for r in results]
        assert "gone" not in keys


# ── delete() ─────────────────────────────────────────────────────────


class TestDelete:
    """Verify delete() semantics."""

    @pytest.fixture
    async def populated_store(self) -> RAGMemoryStore:
        """Return a store with two entries."""
        store = _make_store()
        await store.store("alpha", "first entry")
        await store.store("beta", "second entry")
        return store

    @pytest.mark.asyncio
    async def test_delete_known_key_returns_true(self, populated_store: RAGMemoryStore):
        """Delete() on an existing key returns True."""
        result = await populated_store.delete("alpha")
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_unknown_key_returns_false(
        self, populated_store: RAGMemoryStore
    ):
        """Delete() on a missing key returns False."""
        result = await populated_store.delete("does-not-exist")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_empty_store_returns_false(self):
        """Delete() on an empty store always returns False."""
        store = _make_store()
        result = await store.delete("nothing")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_removes_from_key_map(self, populated_store: RAGMemoryStore):
        """After delete(), the key is no longer in _key_map."""
        await populated_store.delete("alpha")
        assert "alpha" not in populated_store._key_map

    @pytest.mark.asyncio
    async def test_delete_then_retrieve_returns_none(
        self, populated_store: RAGMemoryStore
    ):
        """Retrieve() after delete() returns None for the deleted key."""
        await populated_store.delete("alpha")
        value = await populated_store.retrieve("alpha")
        assert value is None

    @pytest.mark.asyncio
    async def test_delete_does_not_affect_other_keys(
        self, populated_store: RAGMemoryStore
    ):
        """Deleting one key leaves other keys untouched."""
        await populated_store.delete("alpha")
        value = await populated_store.retrieve("beta")
        assert value == "second entry"

    @pytest.mark.asyncio
    async def test_delete_removes_from_list_keys(self, populated_store: RAGMemoryStore):
        """After delete(), list_keys() no longer includes the deleted key."""
        await populated_store.delete("alpha")
        keys = await populated_store.list_keys()
        assert "alpha" not in keys
        assert "beta" in keys

    @pytest.mark.asyncio
    async def test_double_delete_second_returns_false(
        self, populated_store: RAGMemoryStore
    ):
        """Deleting the same key twice: first returns True, second returns False."""
        first = await populated_store.delete("alpha")
        second = await populated_store.delete("alpha")
        assert first is True
        assert second is False

    @pytest.mark.asyncio
    async def test_delete_removes_chunk_from_vectorstore(self):
        """After delete(), the chunk is removed from the vectorstore."""
        store = _make_store()
        await store.store("target", "content to remove")
        doc_id = store._key_map["target"][0]

        await store.delete("target")

        # The vectorstore should no longer contain the document
        # Verify by checking that delete on the same doc_id now returns False
        was_deleted_again = await store._vectorstore.delete(doc_id)
        assert was_deleted_again is False


# ── list_keys() ──────────────────────────────────────────────────────


class TestListKeys:
    """Verify list_keys() semantics."""

    @pytest.fixture
    async def store_with_keys(self) -> RAGMemoryStore:
        """Return a store with a known set of keys."""
        store = _make_store()
        await store.store("agent:coder", "coder value")
        await store.store("agent:reviewer", "reviewer value")
        await store.store("workflow:codegen", "codegen value")
        await store.store("workflow:research", "research value")
        return store

    @pytest.mark.asyncio
    async def test_list_keys_empty_store_returns_empty(self):
        """list_keys() on an empty store returns []."""
        store = _make_store()
        keys = await store.list_keys()
        assert keys == []

    @pytest.mark.asyncio
    async def test_list_keys_no_prefix_returns_all(
        self, store_with_keys: RAGMemoryStore
    ):
        """list_keys() with no prefix returns all stored keys."""
        keys = await store_with_keys.list_keys()
        assert set(keys) == {
            "agent:coder",
            "agent:reviewer",
            "workflow:codegen",
            "workflow:research",
        }

    @pytest.mark.asyncio
    async def test_list_keys_prefix_filters_correctly(
        self, store_with_keys: RAGMemoryStore
    ):
        """list_keys(prefix=...) returns only keys beginning with that prefix."""
        keys = await store_with_keys.list_keys(prefix="agent:")
        assert set(keys) == {"agent:coder", "agent:reviewer"}

    @pytest.mark.asyncio
    async def test_list_keys_prefix_no_match_returns_empty(
        self, store_with_keys: RAGMemoryStore
    ):
        """list_keys() with a prefix that matches nothing returns []."""
        keys = await store_with_keys.list_keys(prefix="model:")
        assert keys == []

    @pytest.mark.asyncio
    async def test_list_keys_prefix_none_is_same_as_no_prefix(
        self, store_with_keys: RAGMemoryStore
    ):
        """Passing prefix=None explicitly is equivalent to calling without prefix."""
        keys_implicit = await store_with_keys.list_keys()
        keys_explicit = await store_with_keys.list_keys(prefix=None)
        assert set(keys_implicit) == set(keys_explicit)

    @pytest.mark.asyncio
    async def test_list_keys_returns_correct_count(
        self, store_with_keys: RAGMemoryStore
    ):
        """list_keys() with no prefix returns exactly as many keys as were stored."""
        keys = await store_with_keys.list_keys()
        assert len(keys) == 4

    @pytest.mark.asyncio
    async def test_list_keys_reflects_deletions(self, store_with_keys: RAGMemoryStore):
        """After delete(), list_keys() count decreases by one."""
        await store_with_keys.delete("agent:coder")
        keys = await store_with_keys.list_keys()
        assert len(keys) == 3
        assert "agent:coder" not in keys

    @pytest.mark.asyncio
    async def test_list_keys_reflects_overwrites(self):
        """Overwriting a key does not add a duplicate to list_keys()."""
        store = _make_store()
        await store.store("x", "value1")
        await store.store("x", "value2")
        keys = await store.list_keys()
        assert keys.count("x") == 1

    @pytest.mark.asyncio
    async def test_list_keys_prefix_full_key_is_valid_prefix(
        self, store_with_keys: RAGMemoryStore
    ):
        """Using a complete key as the prefix returns exactly that key."""
        keys = await store_with_keys.list_keys(prefix="agent:coder")
        assert keys == ["agent:coder"]

    @pytest.mark.asyncio
    async def test_list_keys_returns_list_type(self, store_with_keys: RAGMemoryStore):
        """list_keys() always returns a plain Python list."""
        keys = await store_with_keys.list_keys()
        assert isinstance(keys, list)


# ── Error / edge cases ───────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases and unusual-input scenarios."""

    @pytest.mark.asyncio
    async def test_store_empty_string_value(self):
        """Store() with an empty-string value raises ValueError from Chunk
        validation."""
        store = _make_store()
        # Chunk.content has min_length=1; empty string should trigger a Pydantic error
        with pytest.raises(ValidationError):
            await store.store("empty", "")

    @pytest.mark.asyncio
    async def test_store_unicode_key_and_value(self):
        """Store() handles Unicode keys and values without error."""
        store = _make_store()
        await store.store("key:emoji", "hello world with unicode: cafe\u0301")
        result = await store.retrieve("key:emoji")
        assert result == "hello world with unicode: cafe\u0301"

    @pytest.mark.asyncio
    async def test_store_key_with_special_characters(self):
        """Keys containing special characters (colons, dashes) are handled correctly."""
        store = _make_store()
        await store.store("ns:sub:key-01", "value")
        result = await store.retrieve("ns:sub:key-01")
        assert result == "value"

    @pytest.mark.asyncio
    async def test_key_map_and_vectorstore_stay_in_sync_after_multiple_ops(self):
        """After a sequence of store/overwrite/delete, _key_map and vectorstore
        agree."""
        store = _make_store()
        await store.store("a", "alpha text")
        await store.store("b", "beta text")
        await store.store("a", "alpha updated")  # overwrite
        await store.delete("b")  # delete

        # Only "a" should remain
        keys = await store.list_keys()
        assert keys == ["a"]
        assert "b" not in store._key_map

        # Vectorstore should contain exactly one chunk (for "a")
        results = await store.search("alpha", top_k=10)
        result_keys = [r["key"] for r in results]
        assert "a" in result_keys
        assert "b" not in result_keys

    @pytest.mark.asyncio
    async def test_namespace_is_embedded_in_doc_id(self):
        """doc_id in _key_map starts with the configured namespace prefix."""
        store = RAGMemoryStore(
            embedder=InMemoryEmbedder(dimensions=64),
            vectorstore=InMemoryVectorStore(),
            namespace="my-ns",
        )
        await store.store("k", "some value")
        doc_id = store._key_map["k"][0]
        assert doc_id.startswith("my-ns:")

    @pytest.mark.asyncio
    async def test_store_large_number_of_entries(self):
        """Store and retrieve 200 entries without errors."""
        store = _make_store()
        n = 200
        for i in range(n):
            await store.store(f"key:{i}", f"value number {i}")

        keys = await store.list_keys()
        assert len(keys) == n

        # Spot-check a few
        assert await store.retrieve("key:0") == "value number 0"
        assert await store.retrieve("key:199") == "value number 199"

    @pytest.mark.asyncio
    async def test_search_query_with_no_similar_entries_returns_results_not_raises(
        self,
    ):
        """Search() with a completely dissimilar query returns results or empty — never
        raises."""
        store = _make_store()
        await store.store("entry", "some stored content about bananas")

        # Query about an entirely different topic
        try:
            results = await store.search(
                "quantum entanglement in superconductors", top_k=5
            )
        except Exception as exc:
            pytest.fail(f"search() raised unexpectedly: {exc}")

        # Must return a list (possibly empty or with low-scoring results)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_retrieve_after_full_store_lifecycle(self):
        """Store → retrieve → overwrite → retrieve → delete → retrieve lifecycle."""
        store = _make_store()

        await store.store("lifecycle", "step-one")
        assert await store.retrieve("lifecycle") == "step-one"

        await store.store("lifecycle", "step-two")
        assert await store.retrieve("lifecycle") == "step-two"

        deleted = await store.delete("lifecycle")
        assert deleted is True
        assert await store.retrieve("lifecycle") is None
