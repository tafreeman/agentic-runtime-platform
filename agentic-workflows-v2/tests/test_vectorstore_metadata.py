"""Tests for VectorStore metadata filtering."""

import pytest
from agentic_v2.rag.contracts import Chunk
from agentic_v2.rag.vectorstore import InMemoryVectorStore


@pytest.fixture
def chunks_with_metadata():
    """Create chunks with varied metadata."""
    return [
        Chunk(
            chunk_id="c1",
            document_id="doc1",
            chunk_index=0,
            content="Python is great",
            metadata={"language": "python", "topic": "programming"},
        ),
        Chunk(
            chunk_id="c2",
            document_id="doc2",
            chunk_index=0,
            content="TypeScript is typed",
            metadata={"language": "typescript", "topic": "programming"},
        ),
        Chunk(
            chunk_id="c3",
            document_id="doc3",
            chunk_index=0,
            content="Machine learning basics",
            metadata={"language": "python", "topic": "ml"},
        ),
    ]


@pytest.fixture
def embeddings():
    """Three distinct embeddings."""
    return [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.5, 0.5, 0.0],
    ]


async def test_search_without_filter_returns_all(chunks_with_metadata, embeddings):
    """Search without metadata_filter returns top_k from all chunks."""
    store = InMemoryVectorStore()
    await store.add(chunks_with_metadata, embeddings)

    results = await store.search([1.0, 0.0, 0.0], top_k=10)
    assert len(results) == 3


async def test_search_with_single_filter(chunks_with_metadata, embeddings):
    """Filtering by one metadata key narrows results."""
    store = InMemoryVectorStore()
    await store.add(chunks_with_metadata, embeddings)

    results = await store.search(
        [1.0, 0.0, 0.0],
        top_k=10,
        metadata_filter={"language": "python"},
    )
    assert len(results) == 2
    assert all(r.metadata["language"] == "python" for r in results)


async def test_search_with_multi_key_filter(chunks_with_metadata, embeddings):
    """Filtering by multiple keys requires all to match."""
    store = InMemoryVectorStore()
    await store.add(chunks_with_metadata, embeddings)

    results = await store.search(
        [1.0, 0.0, 0.0],
        top_k=10,
        metadata_filter={"language": "python", "topic": "ml"},
    )
    assert len(results) == 1
    assert results[0].chunk_id == "c3"


async def test_search_filter_no_matches(chunks_with_metadata, embeddings):
    """Filter that matches nothing returns empty list."""
    store = InMemoryVectorStore()
    await store.add(chunks_with_metadata, embeddings)

    results = await store.search(
        [1.0, 0.0, 0.0],
        top_k=10,
        metadata_filter={"language": "rust"},
    )
    assert len(results) == 0


async def test_search_filter_respects_top_k(chunks_with_metadata, embeddings):
    """Filter + top_k limits results correctly."""
    store = InMemoryVectorStore()
    await store.add(chunks_with_metadata, embeddings)

    results = await store.search(
        [1.0, 0.0, 0.0],
        top_k=1,
        metadata_filter={"language": "python"},
    )
    assert len(results) == 1


async def test_search_none_filter_same_as_no_filter(chunks_with_metadata, embeddings):
    """Passing metadata_filter=None behaves like no filter."""
    store = InMemoryVectorStore()
    await store.add(chunks_with_metadata, embeddings)

    results = await store.search([1.0, 0.0, 0.0], top_k=10, metadata_filter=None)
    assert len(results) == 3
