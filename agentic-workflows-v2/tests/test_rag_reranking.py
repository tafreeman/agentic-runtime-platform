"""Tests for RAG reranking implementations.

Covers NoOpReranker, CrossEncoderReranker, and LLMReranker against the
RerankerProtocol contract.
"""

from __future__ import annotations

import asyncio

import pytest
from agentic_v2.rag.contracts import RetrievalResult
from agentic_v2.rag.protocols import RerankerProtocol

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_result(content: str, score: float, chunk_id: str) -> RetrievalResult:
    """Helper to build a RetrievalResult with minimal fields."""
    return RetrievalResult(
        content=content,
        score=score,
        document_id="doc-1",
        chunk_id=chunk_id,
        metadata={},
    )


@pytest.fixture()
def sample_results() -> list[RetrievalResult]:
    """Five results in descending score order."""
    return [
        _make_result("Alpha result", 0.9, "c1"),
        _make_result("Beta result", 0.8, "c2"),
        _make_result("Gamma result", 0.7, "c3"),
        _make_result("Delta result", 0.6, "c4"),
        _make_result("Epsilon result", 0.5, "c5"),
    ]


# ===================================================================
# NoOpReranker
# ===================================================================


class TestNoOpReranker:
    """NoOpReranker passes results through, slicing to top_k."""

    async def test_protocol_conformance(self) -> None:
        from agentic_v2.rag.reranking import NoOpReranker

        assert isinstance(NoOpReranker(), RerankerProtocol)

    async def test_passthrough_preserves_order(
        self, sample_results: list[RetrievalResult]
    ) -> None:
        from agentic_v2.rag.reranking import NoOpReranker

        reranker = NoOpReranker()
        reranked = await reranker.rerank("query", sample_results, top_k=5)
        assert [r.chunk_id for r in reranked] == ["c1", "c2", "c3", "c4", "c5"]

    async def test_top_k_truncation(
        self, sample_results: list[RetrievalResult]
    ) -> None:
        from agentic_v2.rag.reranking import NoOpReranker

        reranker = NoOpReranker()
        reranked = await reranker.rerank("query", sample_results, top_k=3)
        assert len(reranked) == 3
        assert [r.chunk_id for r in reranked] == ["c1", "c2", "c3"]

    async def test_empty_results(self) -> None:
        from agentic_v2.rag.reranking import NoOpReranker

        reranker = NoOpReranker()
        reranked = await reranker.rerank("query", [], top_k=5)
        assert reranked == []

    async def test_top_k_larger_than_results(
        self, sample_results: list[RetrievalResult]
    ) -> None:
        from agentic_v2.rag.reranking import NoOpReranker

        reranker = NoOpReranker()
        reranked = await reranker.rerank("query", sample_results, top_k=100)
        assert len(reranked) == 5


# ===================================================================
# CrossEncoderReranker
# ===================================================================


class TestCrossEncoderReranker:
    """CrossEncoderReranker uses a cross-encoder model to reorder results."""

    async def test_protocol_conformance(self) -> None:
        from agentic_v2.rag.reranking import CrossEncoderReranker

        # Construct with a mock predict_fn to avoid needing sentence-transformers
        reranker = CrossEncoderReranker(predict_fn=lambda pairs: [0.5] * len(pairs))
        assert isinstance(reranker, RerankerProtocol)

    async def test_reorders_by_score(
        self, sample_results: list[RetrievalResult]
    ) -> None:
        from agentic_v2.rag.reranking import CrossEncoderReranker

        # Mock predict_fn: reverse the order (last result gets highest score)
        def mock_predict(pairs: list[tuple[str, str]]) -> list[float]:
            n = len(pairs)
            return [float(i) / n for i in range(n)]  # ascending scores

        reranker = CrossEncoderReranker(predict_fn=mock_predict)
        reranked = await reranker.rerank("query", sample_results, top_k=5)

        # The result with highest cross-encoder score should be first
        assert reranked[0].chunk_id == "c5"  # got highest score (4/5)
        assert reranked[-1].chunk_id == "c1"  # got lowest score (0/5)

    async def test_top_k_after_reranking(
        self, sample_results: list[RetrievalResult]
    ) -> None:
        from agentic_v2.rag.reranking import CrossEncoderReranker

        def mock_predict(pairs: list[tuple[str, str]]) -> list[float]:
            return [0.9, 0.1, 0.8, 0.2, 0.7]

        reranker = CrossEncoderReranker(predict_fn=mock_predict)
        reranked = await reranker.rerank("query", sample_results, top_k=2)
        assert len(reranked) == 2

    async def test_scores_updated(self, sample_results: list[RetrievalResult]) -> None:
        from agentic_v2.rag.reranking import CrossEncoderReranker

        def mock_predict(pairs: list[tuple[str, str]]) -> list[float]:
            return [0.95, 0.85, 0.75, 0.65, 0.55]

        reranker = CrossEncoderReranker(predict_fn=mock_predict)
        reranked = await reranker.rerank("query", sample_results, top_k=5)
        # Scores should reflect cross-encoder output, not original scores
        assert reranked[0].score == pytest.approx(0.95)


# ===================================================================
# LLMReranker
# ===================================================================


class TestLLMReranker:
    """LLMReranker uses an async scoring callable to reorder results."""

    async def test_protocol_conformance(self) -> None:
        from agentic_v2.rag.reranking import LLMReranker

        async def dummy_score(query: str, doc: str) -> float:
            return 0.5

        reranker = LLMReranker(score_fn=dummy_score)
        assert isinstance(reranker, RerankerProtocol)

    async def test_reorders_by_llm_score(
        self, sample_results: list[RetrievalResult]
    ) -> None:
        from agentic_v2.rag.reranking import LLMReranker

        # Score based on content length (longer = higher score)
        async def length_score(query: str, doc: str) -> float:
            return float(len(doc)) / 100.0

        reranker = LLMReranker(score_fn=length_score)
        reranked = await reranker.rerank("query", sample_results, top_k=5)

        # "Epsilon result" is longest (14 chars) → should be first
        assert reranked[0].chunk_id == "c5"

    async def test_concurrent_scoring(
        self, sample_results: list[RetrievalResult]
    ) -> None:
        from agentic_v2.rag.reranking import LLMReranker

        call_count = 0

        async def counting_score(query: str, doc: str) -> float:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.01)  # Simulate async work
            return 0.5

        reranker = LLMReranker(score_fn=counting_score, max_concurrency=3)
        await reranker.rerank("query", sample_results, top_k=5)
        assert call_count == 5  # All results scored

    async def test_top_k_truncation(
        self, sample_results: list[RetrievalResult]
    ) -> None:
        from agentic_v2.rag.reranking import LLMReranker

        async def fixed_score(query: str, doc: str) -> float:
            return 0.5

        reranker = LLMReranker(score_fn=fixed_score)
        reranked = await reranker.rerank("query", sample_results, top_k=2)
        assert len(reranked) == 2

    async def test_empty_results(self) -> None:
        from agentic_v2.rag.reranking import LLMReranker

        async def fixed_score(query: str, doc: str) -> float:
            return 0.5

        reranker = LLMReranker(score_fn=fixed_score)
        reranked = await reranker.rerank("query", [], top_k=5)
        assert reranked == []

    async def test_semaphore_bounds_concurrency(
        self, sample_results: list[RetrievalResult]
    ) -> None:
        from agentic_v2.rag.reranking import LLMReranker

        max_concurrent_seen = 0
        current_concurrent = 0

        async def tracking_score(query: str, doc: str) -> float:
            nonlocal max_concurrent_seen, current_concurrent
            current_concurrent += 1
            if current_concurrent > max_concurrent_seen:
                max_concurrent_seen = current_concurrent
            await asyncio.sleep(0.05)  # Hold the semaphore briefly
            current_concurrent -= 1
            return 0.5

        reranker = LLMReranker(score_fn=tracking_score, max_concurrency=2)
        await reranker.rerank("query", sample_results, top_k=5)
        assert max_concurrent_seen <= 2


# ===================================================================
# HybridRetriever integration
# ===================================================================


class TestHybridRetrieverReranking:
    """Integration tests for reranker wiring in HybridRetriever."""

    async def test_retrieve_without_reranker_unchanged(self) -> None:
        """Without a reranker, retrieve() behaves identically to before."""
        from agentic_v2.rag.embeddings import InMemoryEmbedder
        from agentic_v2.rag.retrieval import HybridRetriever
        from agentic_v2.rag.vectorstore import InMemoryVectorStore

        embedder = InMemoryEmbedder(dimensions=32)
        store = InMemoryVectorStore()

        retriever = HybridRetriever(embedder, store)
        results = await retriever.retrieve("test query", top_k=5)
        # Empty store → no results, but no error
        assert results == []

    async def test_retrieve_applies_reranker(self) -> None:
        """Reranker is called on RRF-fused results."""
        from unittest.mock import AsyncMock

        from agentic_v2.rag.contracts import Chunk
        from agentic_v2.rag.embeddings import InMemoryEmbedder
        from agentic_v2.rag.reranking import NoOpReranker
        from agentic_v2.rag.retrieval import HybridRetriever
        from agentic_v2.rag.vectorstore import InMemoryVectorStore

        embedder = InMemoryEmbedder(dimensions=32)
        store = InMemoryVectorStore()

        # Add some data so retrieval returns results
        chunks = [
            Chunk(content="Hello world", document_id="d1", chunk_index=0),
            Chunk(content="Goodbye world", document_id="d1", chunk_index=1),
        ]
        embeddings = await embedder.embed([c.content for c in chunks])
        await store.add(chunks, embeddings)

        # Use a NoOpReranker with a spy to verify it's called
        reranker = NoOpReranker()
        reranker.rerank = AsyncMock(wraps=reranker.rerank)  # type: ignore[method-assign]

        retriever = HybridRetriever(embedder, store, reranker=reranker)
        retriever.index_chunks(chunks)

        results = await retriever.retrieve("Hello", top_k=2)
        reranker.rerank.assert_called_once()
        assert len(results) <= 2

    async def test_reranker_runs_before_threshold(self) -> None:
        """Score threshold is applied AFTER reranking, not before."""
        from agentic_v2.rag.contracts import Chunk
        from agentic_v2.rag.embeddings import InMemoryEmbedder
        from agentic_v2.rag.reranking import CrossEncoderReranker
        from agentic_v2.rag.retrieval import HybridRetriever
        from agentic_v2.rag.vectorstore import InMemoryVectorStore

        embedder = InMemoryEmbedder(dimensions=32)
        store = InMemoryVectorStore()

        chunks = [
            Chunk(content="Relevant doc", document_id="d1", chunk_index=0),
            Chunk(content="Irrelevant doc", document_id="d1", chunk_index=1),
        ]
        embeddings = await embedder.embed([c.content for c in chunks])
        await store.add(chunks, embeddings)

        # Reranker gives high score to first, low to second
        def mock_predict(pairs: list[tuple[str, str]]) -> list[float]:
            return [0.9 if "Relevant" in p[1] else 0.1 for p in pairs]

        reranker = CrossEncoderReranker(predict_fn=mock_predict)

        # Threshold of 0.5 should filter out the 0.1-scored result
        retriever = HybridRetriever(
            embedder, store, reranker=reranker, score_threshold=0.5
        )
        retriever.index_chunks(chunks)

        results = await retriever.retrieve("test", top_k=5)
        # Only the "Relevant doc" should survive the threshold
        assert all(r.score >= 0.5 for r in results)
