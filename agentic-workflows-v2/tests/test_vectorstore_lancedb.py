"""Tests for LanceDBVectorStore — persistent vector store backend."""

from __future__ import annotations

import pytest

lancedb = pytest.importorskip("lancedb")

from agentic_v2.rag.contracts import Chunk
from agentic_v2.rag.vectorstore import LanceDBVectorStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

EMBEDDING_DIM = 3


@pytest.fixture
def store(tmp_path):
    """Create a fresh LanceDBVectorStore in a temporary directory."""
    return LanceDBVectorStore(
        db_path=tmp_path / "test_lance",
        table_name="chunks",
        embedding_dim=EMBEDDING_DIM,
    )


@pytest.fixture
def sample_chunks():
    """Three chunks with distinct content."""
    return [
        Chunk(
            chunk_id="c1",
            document_id="doc1",
            chunk_index=0,
            content="Python is great",
            metadata={"language": "python"},
        ),
        Chunk(
            chunk_id="c2",
            document_id="doc1",
            chunk_index=1,
            content="TypeScript is typed",
            metadata={"language": "typescript"},
        ),
        Chunk(
            chunk_id="c3",
            document_id="doc2",
            chunk_index=0,
            content="Machine learning basics",
            metadata={"topic": "ml"},
        ),
    ]


@pytest.fixture
def sample_embeddings():
    """Three distinct 3-d embeddings."""
    return [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ]


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


async def test_add_persists_and_len_reflects_count(
    store, sample_chunks, sample_embeddings
):
    """Add() persists chunks; __len__() reflects the count."""
    assert len(store) == 0

    await store.add(sample_chunks, sample_embeddings)

    assert len(store) == 3


async def test_search_returns_top_k_with_correct_fields(
    store, sample_chunks, sample_embeddings
):
    """Search() returns top_k results with correct chunk_id and score."""
    await store.add(sample_chunks, sample_embeddings)

    # Query vector aligned with c1's embedding
    results = await store.search([1.0, 0.0, 0.0], top_k=2)

    assert len(results) == 2
    # Best match should be c1 (cosine similarity 1.0)
    assert results[0].chunk_id == "c1"
    assert results[0].score == pytest.approx(1.0, abs=0.01)
    assert results[0].document_id == "doc1"
    assert results[0].content == "Python is great"
    # Score field exists and is non-negative
    assert all(r.score >= 0.0 for r in results)


async def test_delete_removes_chunks(store, sample_chunks, sample_embeddings):
    """Delete() removes chunks; subsequent search excludes deleted."""
    await store.add(sample_chunks, sample_embeddings)
    assert len(store) == 3

    # Delete doc1 (c1 and c2)
    deleted = await store.delete("doc1")
    assert deleted is True
    assert len(store) == 1

    # Search should only find c3
    results = await store.search([0.0, 0.0, 1.0], top_k=10)
    assert len(results) == 1
    assert results[0].chunk_id == "c3"


async def test_delete_nonexistent_returns_false(store):
    """Delete() for a missing document_id returns False."""
    deleted = await store.delete("no_such_doc")
    assert deleted is False


async def test_persistence_survives_reinstantiation(
    tmp_path, sample_chunks, sample_embeddings
):
    """Store survives re-instantiation from the same db_path."""
    db_path = tmp_path / "persist_test"

    store1 = LanceDBVectorStore(
        db_path=db_path, table_name="chunks", embedding_dim=EMBEDDING_DIM
    )
    await store1.add(sample_chunks, sample_embeddings)
    assert len(store1) == 3

    # Create a new instance pointing at the same path
    store2 = LanceDBVectorStore(
        db_path=db_path, table_name="chunks", embedding_dim=EMBEDDING_DIM
    )
    assert len(store2) == 3

    # Search still works on the reopened store
    results = await store2.search([1.0, 0.0, 0.0], top_k=1)
    assert len(results) == 1
    assert results[0].chunk_id == "c1"


async def test_content_hash_dedup(store, sample_chunks, sample_embeddings):
    """Adding the same chunk twice does not duplicate rows."""
    await store.add(sample_chunks, sample_embeddings)
    assert len(store) == 3

    # Add the same chunks again (identical content_hash values)
    await store.add(sample_chunks, sample_embeddings)
    assert len(store) == 3


async def test_search_empty_store_returns_empty(store):
    """Searching an empty store returns an empty list."""
    results = await store.search([1.0, 0.0, 0.0], top_k=5)
    assert results == []


async def test_add_length_mismatch_raises(store, sample_chunks):
    """Add() raises ValueError when chunks/embeddings lengths differ."""
    with pytest.raises(ValueError, match="same length"):
        await store.add(sample_chunks, [[1.0, 0.0, 0.0]])


async def test_search_metadata_preserved(store):
    """Metadata round-trips through add/search correctly."""
    chunk = Chunk(
        chunk_id="m1",
        document_id="doc_meta",
        chunk_index=0,
        content="metadata test",
        metadata={"key": "value", "num": 42},
    )
    await store.add([chunk], [[1.0, 0.0, 0.0]])

    results = await store.search([1.0, 0.0, 0.0], top_k=1)
    assert len(results) == 1
    assert results[0].metadata == {"key": "value", "num": 42}
