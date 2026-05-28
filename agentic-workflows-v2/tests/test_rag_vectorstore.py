"""Tests for RAG in-memory vector store (Sprint 5.3).

TDD — these tests are written FIRST, then the implementation follows.

Verifies:
- InMemoryVectorStore satisfies VectorStoreProtocol.
- add() stores chunks and embeddings.
- search() returns results ranked by cosine similarity.
- search() respects top_k limit.
- delete() removes chunks by document_id and returns boolean status.
- search on empty store returns empty list.
"""

from __future__ import annotations

import math

import pytest
from agentic_v2.rag.contracts import Chunk, RetrievalResult
from agentic_v2.rag.protocols import VectorStoreProtocol

# ── Fixtures ────────────────────────────────────────────────────────


def _make_chunk(
    content: str,
    document_id: str = "doc-1",
    chunk_index: int = 0,
    chunk_id: str | None = None,
) -> Chunk:
    """Create a Chunk for testing."""
    kwargs: dict = {
        "content": content,
        "document_id": document_id,
        "chunk_index": chunk_index,
    }
    if chunk_id is not None:
        kwargs["chunk_id"] = chunk_id
    return Chunk(**kwargs)


def _unit_vector(dimensions: int, index: int) -> list[float]:
    """Create a unit vector with 1.0 at *index* and 0.0 elsewhere."""
    vec = [0.0] * dimensions
    vec[index % dimensions] = 1.0
    return vec


def _normalize(vec: list[float]) -> list[float]:
    """L2-normalize a vector."""
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]


# ── InMemoryVectorStore ─────────────────────────────────────────────


class TestInMemoryVectorStore:
    """Verify InMemoryVectorStore — cosine similarity vector store for dev/test."""

    def test_satisfies_vector_store_protocol(self):
        """InMemoryVectorStore must be recognized as VectorStoreProtocol."""
        from agentic_v2.rag.vectorstore import InMemoryVectorStore

        store = InMemoryVectorStore()
        assert isinstance(store, VectorStoreProtocol)

    @pytest.mark.asyncio
    async def test_add_stores_chunks_and_embeddings(self):
        """Add() should store chunks so search can find them."""
        from agentic_v2.rag.vectorstore import InMemoryVectorStore

        store = InMemoryVectorStore()
        chunk = _make_chunk("hello world")
        embedding = [1.0, 0.0, 0.0]

        await store.add([chunk], [embedding])

        # Search with the same vector should return the chunk
        results = await store.search([1.0, 0.0, 0.0], top_k=1)
        assert len(results) == 1
        assert results[0].content == "hello world"
        assert results[0].chunk_id == chunk.chunk_id
        assert results[0].document_id == "doc-1"

    @pytest.mark.asyncio
    async def test_search_returns_ranked_by_cosine_similarity(self):
        """Search() must return results sorted by descending cosine similarity."""
        from agentic_v2.rag.vectorstore import InMemoryVectorStore

        store = InMemoryVectorStore()
        dims = 4

        # Three chunks with distinct embeddings
        c1 = _make_chunk("closest", document_id="d1", chunk_index=0, chunk_id="c1")
        c2 = _make_chunk("middle", document_id="d2", chunk_index=0, chunk_id="c2")
        c3 = _make_chunk("farthest", document_id="d3", chunk_index=0, chunk_id="c3")

        # Embeddings: c1 is closest to query, c3 is farthest
        e1 = _normalize([1.0, 0.1, 0.0, 0.0])  # very close to query
        e2 = _normalize([0.5, 0.5, 0.0, 0.0])  # moderate
        e3 = _normalize([0.0, 0.0, 1.0, 0.0])  # orthogonal to query

        await store.add([c1, c2, c3], [e1, e2, e3])

        query = _normalize([1.0, 0.0, 0.0, 0.0])
        results = await store.search(query, top_k=3)

        assert len(results) == 3
        assert results[0].chunk_id == "c1"  # highest similarity
        assert results[1].chunk_id == "c2"  # middle
        assert results[2].chunk_id == "c3"  # lowest similarity
        # Scores should be descending
        assert results[0].score >= results[1].score >= results[2].score

    @pytest.mark.asyncio
    async def test_search_respects_top_k(self):
        """Search() should return at most top_k results."""
        from agentic_v2.rag.vectorstore import InMemoryVectorStore

        store = InMemoryVectorStore()
        dims = 3
        chunks = [
            _make_chunk(f"text-{i}", document_id=f"d{i}", chunk_index=0)
            for i in range(10)
        ]
        embeddings = [_unit_vector(dims, i) for i in range(10)]

        await store.add(chunks, embeddings)

        results = await store.search([1.0, 0.0, 0.0], top_k=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_delete_removes_chunks_by_document_id(self):
        """Delete() should remove all chunks for a given document_id."""
        from agentic_v2.rag.vectorstore import InMemoryVectorStore

        store = InMemoryVectorStore()
        c1 = _make_chunk("chunk 1", document_id="doc-A", chunk_index=0)
        c2 = _make_chunk("chunk 2", document_id="doc-A", chunk_index=1)
        c3 = _make_chunk("chunk 3", document_id="doc-B", chunk_index=0)

        e1 = [1.0, 0.0, 0.0]
        e2 = [0.0, 1.0, 0.0]
        e3 = [0.0, 0.0, 1.0]

        await store.add([c1, c2, c3], [e1, e2, e3])

        deleted = await store.delete("doc-A")
        assert deleted is True

        # Only doc-B chunk should remain
        results = await store.search([1.0, 1.0, 1.0], top_k=10)
        assert len(results) == 1
        assert results[0].document_id == "doc-B"

    @pytest.mark.asyncio
    async def test_delete_returns_false_for_unknown_document(self):
        """Delete() should return False if document_id is not found."""
        from agentic_v2.rag.vectorstore import InMemoryVectorStore

        store = InMemoryVectorStore()
        result = await store.delete("nonexistent-doc")
        assert result is False

    @pytest.mark.asyncio
    async def test_search_empty_store_returns_empty(self):
        """Search() on an empty store must return an empty list."""
        from agentic_v2.rag.vectorstore import InMemoryVectorStore

        store = InMemoryVectorStore()
        results = await store.search([1.0, 0.0, 0.0], top_k=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_search_results_are_retrieval_results(self):
        """Search() must return RetrievalResult instances."""
        from agentic_v2.rag.vectorstore import InMemoryVectorStore

        store = InMemoryVectorStore()
        chunk = _make_chunk("test content")
        await store.add([chunk], [[1.0, 0.0, 0.0]])

        results = await store.search([1.0, 0.0, 0.0], top_k=1)
        assert len(results) == 1
        assert isinstance(results[0], RetrievalResult)

    @pytest.mark.asyncio
    async def test_search_scores_are_non_negative(self):
        """Cosine similarity scores should be non-negative (we clamp at 0)."""
        from agentic_v2.rag.vectorstore import InMemoryVectorStore

        store = InMemoryVectorStore()
        chunk = _make_chunk("text")
        # Store a chunk with one direction
        await store.add([chunk], [[1.0, 0.0, 0.0]])

        # Query with opposite direction
        results = await store.search([-1.0, 0.0, 0.0], top_k=1)
        assert len(results) == 1
        assert results[0].score >= 0.0

    @pytest.mark.asyncio
    async def test_add_mismatched_lengths_raises(self):
        """Add() should raise ValueError if chunks and embeddings have different
        lengths."""
        from agentic_v2.rag.vectorstore import InMemoryVectorStore

        store = InMemoryVectorStore()
        chunks = [_make_chunk("a"), _make_chunk("b")]
        embeddings = [[1.0, 0.0]]  # only 1 embedding for 2 chunks

        with pytest.raises(ValueError, match="must have the same length"):
            await store.add(chunks, embeddings)

    @pytest.mark.asyncio
    async def test_chunk_metadata_preserved_in_results(self):
        """Chunk metadata should be passed through to RetrievalResult."""
        from agentic_v2.rag.vectorstore import InMemoryVectorStore

        chunk = Chunk(
            content="metadata test",
            document_id="doc-1",
            chunk_index=0,
            metadata={"section": "intro"},
        )
        store = InMemoryVectorStore()
        await store.add([chunk], [[1.0, 0.0]])

        results = await store.search([1.0, 0.0], top_k=1)
        assert results[0].metadata["section"] == "intro"
