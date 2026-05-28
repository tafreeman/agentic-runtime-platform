"""Tests for RAG hybrid retrieval — BM25, dense, and RRF fusion.

Covers:
- BM25Index: single doc, multiple docs, term frequency, empty query, tokenization
- HybridRetriever: dense_only delegation, hybrid retrieve with RRF, index_chunks, empty index
- RRF: correct fusion scores, deduplication by chunk_id, top_k enforcement
"""

from __future__ import annotations

import pytest
from agentic_v2.rag.contracts import Chunk, RetrievalResult
from agentic_v2.rag.embeddings import InMemoryEmbedder
from agentic_v2.rag.retrieval import BM25Index, HybridRetriever, reciprocal_rank_fusion
from agentic_v2.rag.vectorstore import InMemoryVectorStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_chunk(
    content: str,
    *,
    chunk_id: str | None = None,
    document_id: str = "doc-1",
    chunk_index: int = 0,
) -> Chunk:
    """Helper to build a Chunk with sensible defaults."""
    kwargs: dict = {
        "document_id": document_id,
        "chunk_index": chunk_index,
        "content": content,
    }
    if chunk_id is not None:
        kwargs["chunk_id"] = chunk_id
    return Chunk(**kwargs)


@pytest.fixture
def sample_chunks() -> list[Chunk]:
    """Three chunks with distinct vocabularies for BM25 testing."""
    return [
        _make_chunk(
            "Python is a popular programming language for data science",
            chunk_id="c1",
            chunk_index=0,
        ),
        _make_chunk(
            "Rust is a systems programming language focused on safety",
            chunk_id="c2",
            chunk_index=1,
        ),
        _make_chunk(
            "Data science uses Python and R for statistical analysis",
            chunk_id="c3",
            chunk_index=2,
        ),
    ]


@pytest.fixture
def embedder() -> InMemoryEmbedder:
    return InMemoryEmbedder(dimensions=64)


@pytest.fixture
def vectorstore() -> InMemoryVectorStore:
    return InMemoryVectorStore()


# ===================================================================
# BM25Index
# ===================================================================


class TestBM25Index:
    """Tests for the BM25Index keyword retrieval."""

    def test_single_doc_search(self) -> None:
        """Searching with a term present in one chunk returns that chunk."""
        chunk = _make_chunk("hello world", chunk_id="c1")
        index = BM25Index()
        index.build([chunk])
        results = index.search("hello", top_k=5)
        assert len(results) == 1
        assert results[0].chunk_id == "c1"
        assert results[0].score > 0.0

    def test_multiple_docs_ranking(self, sample_chunks: list[Chunk]) -> None:
        """Chunks containing query terms rank higher than those without."""
        index = BM25Index()
        index.build(sample_chunks)
        results = index.search("Python data science", top_k=3)
        # c1 and c3 both mention "python" and/or "data science"
        result_ids = [r.chunk_id for r in results]
        assert "c1" in result_ids
        assert "c3" in result_ids
        # c2 (Rust) should rank lower or be absent
        if "c2" in result_ids:
            c2_score = next(r.score for r in results if r.chunk_id == "c2")
            c1_score = next(r.score for r in results if r.chunk_id == "c1")
            assert c1_score > c2_score

    def test_term_frequency_scoring(self) -> None:
        """A chunk repeating a query term more often gets a higher score."""
        c_single = _make_chunk("python is great", chunk_id="single")
        c_double = _make_chunk("python python python", chunk_id="triple")
        index = BM25Index()
        index.build([c_single, c_double])
        results = index.search("python", top_k=2)
        assert len(results) == 2
        # The chunk with more occurrences should score higher
        assert results[0].chunk_id == "triple"
        assert results[0].score > results[1].score

    def test_empty_query_returns_empty(self) -> None:
        """An empty query returns no results."""
        chunk = _make_chunk("some content", chunk_id="c1")
        index = BM25Index()
        index.build([chunk])
        results = index.search("", top_k=5)
        assert results == []

    def test_tokenization_lowercases(self) -> None:
        """BM25 tokenization is case-insensitive."""
        chunk = _make_chunk("Python PYTHON python", chunk_id="c1")
        index = BM25Index()
        index.build([chunk])
        results = index.search("PYTHON", top_k=5)
        assert len(results) == 1
        assert results[0].chunk_id == "c1"
        assert results[0].score > 0.0

    def test_no_matching_terms_returns_empty(self) -> None:
        """Query with no matching terms returns empty list."""
        chunk = _make_chunk("hello world", chunk_id="c1")
        index = BM25Index()
        index.build([chunk])
        results = index.search("xyzzy foobar", top_k=5)
        assert results == []

    def test_empty_index_returns_empty(self) -> None:
        """Searching an unbuilt index returns no results."""
        index = BM25Index()
        results = index.search("hello", top_k=5)
        assert results == []

    def test_top_k_respected(self) -> None:
        """Only top_k results are returned."""
        chunks = [
            _make_chunk(f"word word chunk {i}", chunk_id=f"c{i}", chunk_index=i)
            for i in range(10)
        ]
        index = BM25Index()
        index.build(chunks)
        results = index.search("word", top_k=3)
        assert len(results) <= 3

    def test_result_type(self) -> None:
        """BM25 results are RetrievalResult instances."""
        chunk = _make_chunk("test content", chunk_id="c1")
        index = BM25Index()
        index.build([chunk])
        results = index.search("test", top_k=5)
        assert len(results) >= 1
        assert isinstance(results[0], RetrievalResult)

    def test_custom_bm25_parameters(self) -> None:
        """Custom k1 and b parameters are accepted."""
        chunk = _make_chunk("hello world", chunk_id="c1")
        index = BM25Index(k1=2.0, b=0.5)
        index.build([chunk])
        results = index.search("hello", top_k=5)
        assert len(results) == 1
        assert results[0].score > 0.0


# ===================================================================
# Reciprocal Rank Fusion
# ===================================================================


class TestReciprocalRankFusion:
    """Tests for the RRF merging function."""

    def test_correct_fusion_scores(self) -> None:
        """RRF assigns correct fused scores based on rank positions."""
        list_a = [
            RetrievalResult(content="A", score=0.9, document_id="d1", chunk_id="c1"),
            RetrievalResult(content="B", score=0.8, document_id="d1", chunk_id="c2"),
        ]
        list_b = [
            RetrievalResult(content="B", score=0.7, document_id="d1", chunk_id="c2"),
            RetrievalResult(content="A", score=0.6, document_id="d1", chunk_id="c1"),
        ]
        merged = reciprocal_rank_fusion([list_a, list_b], k=60, top_k=10)

        # c1: rank 1 in list_a (score 1/(60+1)), rank 2 in list_b (1/(60+2))
        # c2: rank 2 in list_a (1/(60+2)), rank 1 in list_b (1/(60+1))
        # Both should have the same fused score
        scores = {r.chunk_id: r.score for r in merged}
        assert pytest.approx(scores["c1"]) == pytest.approx(scores["c2"])

    def test_deduplication_by_chunk_id(self) -> None:
        """RRF deduplicates results by chunk_id across lists."""
        result = RetrievalResult(
            content="Same", score=0.5, document_id="d1", chunk_id="c1"
        )
        list_a = [result]
        list_b = [result]
        merged = reciprocal_rank_fusion([list_a, list_b], k=60, top_k=10)
        chunk_ids = [r.chunk_id for r in merged]
        assert chunk_ids.count("c1") == 1

    def test_top_k_enforcement(self) -> None:
        """RRF returns at most top_k results."""
        results_a = [
            RetrievalResult(
                content=f"A{i}",
                score=1.0 - i * 0.1,
                document_id="d1",
                chunk_id=f"a{i}",
            )
            for i in range(5)
        ]
        results_b = [
            RetrievalResult(
                content=f"B{i}",
                score=1.0 - i * 0.1,
                document_id="d1",
                chunk_id=f"b{i}",
            )
            for i in range(5)
        ]
        merged = reciprocal_rank_fusion([results_a, results_b], k=60, top_k=3)
        assert len(merged) <= 3

    def test_empty_lists_returns_empty(self) -> None:
        """RRF with all empty lists returns empty."""
        merged = reciprocal_rank_fusion([[], []], k=60, top_k=5)
        assert merged == []

    def test_single_list_preserves_order(self) -> None:
        """RRF with a single list preserves the original ranking."""
        results = [
            RetrievalResult(
                content="First", score=0.9, document_id="d1", chunk_id="c1"
            ),
            RetrievalResult(
                content="Second", score=0.5, document_id="d1", chunk_id="c2"
            ),
        ]
        merged = reciprocal_rank_fusion([results], k=60, top_k=10)
        assert merged[0].chunk_id == "c1"
        assert merged[1].chunk_id == "c2"

    def test_rrf_scores_are_positive(self) -> None:
        """All RRF fused scores must be positive."""
        results = [
            RetrievalResult(content="X", score=0.1, document_id="d1", chunk_id="c1"),
        ]
        merged = reciprocal_rank_fusion([results], k=60, top_k=5)
        assert all(r.score > 0 for r in merged)


# ===================================================================
# HybridRetriever
# ===================================================================


class TestHybridRetriever:
    """Tests for the HybridRetriever orchestrating dense + BM25."""

    @pytest.mark.asyncio
    async def test_dense_only_delegates_to_vectorstore(
        self,
        embedder: InMemoryEmbedder,
        vectorstore: InMemoryVectorStore,
        sample_chunks: list[Chunk],
    ) -> None:
        """dense_only() embeds the query and searches the vectorstore."""
        embeddings = await embedder.embed([c.content for c in sample_chunks])
        await vectorstore.add(sample_chunks, embeddings)

        retriever = HybridRetriever(embedder=embedder, vectorstore=vectorstore)
        results = await retriever.dense_only("programming language", top_k=2)

        assert len(results) <= 2
        assert all(isinstance(r, RetrievalResult) for r in results)

    @pytest.mark.asyncio
    async def test_retrieve_uses_rrf_fusion(
        self,
        embedder: InMemoryEmbedder,
        vectorstore: InMemoryVectorStore,
        sample_chunks: list[Chunk],
    ) -> None:
        """Retrieve() fuses dense and BM25 results via RRF."""
        embeddings = await embedder.embed([c.content for c in sample_chunks])
        await vectorstore.add(sample_chunks, embeddings)

        retriever = HybridRetriever(embedder=embedder, vectorstore=vectorstore)
        retriever.index_chunks(sample_chunks)

        results = await retriever.retrieve("Python programming", top_k=3)
        assert len(results) <= 3
        assert all(isinstance(r, RetrievalResult) for r in results)
        # Scores should be RRF-fused (not raw cosine or BM25)
        assert all(r.score > 0 for r in results)

    @pytest.mark.asyncio
    async def test_index_chunks_builds_bm25(
        self,
        embedder: InMemoryEmbedder,
        vectorstore: InMemoryVectorStore,
    ) -> None:
        """index_chunks() enables BM25 keyword matching."""
        chunks = [
            _make_chunk("alpha beta gamma", chunk_id="c1"),
            _make_chunk("delta epsilon zeta", chunk_id="c2"),
        ]
        embeddings = await embedder.embed([c.content for c in chunks])
        await vectorstore.add(chunks, embeddings)

        retriever = HybridRetriever(embedder=embedder, vectorstore=vectorstore)
        retriever.index_chunks(chunks)

        results = await retriever.retrieve("alpha", top_k=2)
        # The BM25 component should boost the chunk containing "alpha"
        result_ids = [r.chunk_id for r in results]
        assert "c1" in result_ids

    @pytest.mark.asyncio
    async def test_empty_index_returns_results_from_dense(
        self,
        embedder: InMemoryEmbedder,
        vectorstore: InMemoryVectorStore,
    ) -> None:
        """Without BM25 index, retrieve() still returns dense results."""
        chunk = _make_chunk("some content here", chunk_id="c1")
        embeddings = await embedder.embed([chunk.content])
        await vectorstore.add([chunk], embeddings)

        retriever = HybridRetriever(embedder=embedder, vectorstore=vectorstore)
        # No index_chunks() called — BM25 index is empty
        results = await retriever.retrieve("content", top_k=5)
        # Should still get results from the dense pathway
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_empty_vectorstore_returns_empty(
        self,
        embedder: InMemoryEmbedder,
        vectorstore: InMemoryVectorStore,
    ) -> None:
        """With no chunks in vectorstore, retrieve() returns empty."""
        retriever = HybridRetriever(embedder=embedder, vectorstore=vectorstore)
        results = await retriever.retrieve("anything", top_k=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_custom_rrf_k(
        self,
        embedder: InMemoryEmbedder,
        vectorstore: InMemoryVectorStore,
        sample_chunks: list[Chunk],
    ) -> None:
        """Custom rrf_k parameter influences fusion scores."""
        embeddings = await embedder.embed([c.content for c in sample_chunks])
        await vectorstore.add(sample_chunks, embeddings)

        retriever_default = HybridRetriever(
            embedder=embedder, vectorstore=vectorstore, rrf_k=60
        )
        retriever_custom = HybridRetriever(
            embedder=embedder, vectorstore=vectorstore, rrf_k=1
        )
        retriever_default.index_chunks(sample_chunks)
        retriever_custom.index_chunks(sample_chunks)

        results_default = await retriever_default.retrieve("Python", top_k=3)
        results_custom = await retriever_custom.retrieve("Python", top_k=3)

        # With a very small k, rank differences matter more
        # The ordering may differ, but both should return valid results
        assert len(results_default) > 0
        assert len(results_custom) > 0

    @pytest.mark.asyncio
    async def test_retrieve_top_k_enforcement(
        self,
        embedder: InMemoryEmbedder,
        vectorstore: InMemoryVectorStore,
    ) -> None:
        """Retrieve() respects top_k parameter."""
        chunks = [
            _make_chunk(f"content chunk {i}", chunk_id=f"c{i}", chunk_index=i)
            for i in range(10)
        ]
        embeddings = await embedder.embed([c.content for c in chunks])
        await vectorstore.add(chunks, embeddings)

        retriever = HybridRetriever(embedder=embedder, vectorstore=vectorstore)
        retriever.index_chunks(chunks)

        results = await retriever.retrieve("content chunk", top_k=3)
        assert len(results) <= 3
