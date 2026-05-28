"""RAG hybrid retrieval — BM25 keyword search, dense retrieval, and RRF fusion.

Provides:
- :class:`BM25Index`: Pure-Python BM25 keyword index (no external deps).
- :func:`reciprocal_rank_fusion`: Reciprocal Rank Fusion merging strategy.
- :class:`HybridRetriever`: Orchestrates dense + BM25 retrieval with RRF.
"""

from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from typing import TYPE_CHECKING

from .contracts import RetrievalResult

if TYPE_CHECKING:
    from .contracts import Chunk
    from .protocols import EmbeddingProtocol, RerankerProtocol, VectorStoreProtocol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BM25 Index
# ---------------------------------------------------------------------------


class BM25Index:
    """Pure-Python in-memory BM25 keyword index.

    Builds an inverted index from chunks, tokenizes on whitespace with
    lowercasing, and computes Okapi BM25 scores for retrieval.

    Args:
        k1: Term saturation parameter (default 1.5).
        b: Length normalization parameter (default 0.75).
    """

    def __init__(self, *, k1: float = 1.5, b: float = 0.75) -> None:
        self._k1 = k1
        self._b = b
        self._chunks: list[Chunk] = []
        self._doc_freqs: dict[str, int] = defaultdict(int)
        self._doc_term_freqs: list[dict[str, int]] = []
        self._doc_lengths: list[int] = []
        self._avg_dl: float = 0.0
        self._n_docs: int = 0

    def build(self, chunks: list[Chunk]) -> None:
        """Replace the BM25 inverted index with the given chunks.

        This is a full rebuild — existing index state is discarded.
        For incremental indexing, use :meth:`add` instead.

        Args:
            chunks: Chunks to index.
        """
        self._chunks = []
        self._doc_freqs = defaultdict(int)
        self._doc_term_freqs = []
        self._doc_lengths = []
        self._n_docs = 0
        self._avg_dl = 0.0
        self.add(chunks)

    def add(self, chunks: list[Chunk]) -> None:
        """Incrementally add chunks to the BM25 index.

        Existing indexed chunks are preserved.  Call :meth:`build` to
        replace the entire index instead.

        Args:
            chunks: New chunks to add to the index.
        """
        for chunk in chunks:
            self._chunks.append(chunk)
            tokens = _tokenize(chunk.content)
            self._doc_lengths.append(len(tokens))

            term_freq: dict[str, int] = defaultdict(int)
            seen_terms: set[str] = set()
            for token in tokens:
                term_freq[token] += 1
                if token not in seen_terms:
                    self._doc_freqs[token] += 1
                    seen_terms.add(token)

            self._doc_term_freqs.append(dict(term_freq))

        self._n_docs = len(self._chunks)
        total_length = sum(self._doc_lengths)
        self._avg_dl = total_length / self._n_docs if self._n_docs > 0 else 0.0

    def search(self, query: str, *, top_k: int = 5) -> list[RetrievalResult]:
        """Search the index with a BM25 query.

        Args:
            query: The search query string.
            top_k: Maximum number of results to return.

        Returns:
            Ranked list of retrieval results, highest BM25 score first.
        """
        query_tokens = _tokenize(query)
        if not query_tokens or self._n_docs == 0:
            return []

        scores: list[tuple[float, int]] = []
        for doc_idx in range(self._n_docs):
            score = self._score_document(query_tokens, doc_idx)
            if score > 0.0:
                scores.append((score, doc_idx))

        scores.sort(key=lambda pair: pair[0], reverse=True)

        results: list[RetrievalResult] = []
        for score, doc_idx in scores[:top_k]:
            chunk = self._chunks[doc_idx]
            results.append(
                RetrievalResult(
                    content=chunk.content,
                    score=score,
                    document_id=chunk.document_id,
                    chunk_id=chunk.chunk_id,
                    metadata=dict(chunk.metadata),
                )
            )
        return results

    def _score_document(self, query_tokens: list[str], doc_idx: int) -> float:
        """Compute BM25 score for a single document against query tokens."""
        score = 0.0
        doc_len = self._doc_lengths[doc_idx]
        term_freqs = self._doc_term_freqs[doc_idx]

        for token in query_tokens:
            if token not in term_freqs:
                continue

            tf = term_freqs[token]
            df = self._doc_freqs.get(token, 0)

            # IDF component: log((N - df + 0.5) / (df + 0.5) + 1)
            idf = math.log((self._n_docs - df + 0.5) / (df + 0.5) + 1.0)

            # TF component with length normalization
            tf_norm = (tf * (self._k1 + 1.0)) / (
                tf + self._k1 * (1.0 - self._b + self._b * doc_len / self._avg_dl)
            )

            score += idf * tf_norm

        return score


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion
# ---------------------------------------------------------------------------


def reciprocal_rank_fusion(
    result_lists: list[list[RetrievalResult]],
    *,
    k: int = 60,
    top_k: int = 5,
) -> list[RetrievalResult]:
    """Merge multiple ranked result lists using Reciprocal Rank Fusion.

    For each result appearing in any list, computes:
        ``score = sum(1 / (k + rank))`` across all lists where it appears.

    Deduplicates by ``chunk_id``, keeping the first-seen content/metadata.

    Args:
        result_lists: Lists of ranked retrieval results to fuse.
        k: RRF constant (default 60, per the original paper).
        top_k: Maximum number of merged results to return.

    Returns:
        Fused and ranked list of retrieval results.
    """
    fused_scores: dict[str, float] = defaultdict(float)
    first_seen: dict[str, RetrievalResult] = {}

    for result_list in result_lists:
        for rank_zero_based, result in enumerate(result_list):
            rank = rank_zero_based + 1  # 1-indexed ranks
            fused_scores[result.chunk_id] += 1.0 / (k + rank)
            if result.chunk_id not in first_seen:
                first_seen[result.chunk_id] = result

    # Sort by fused score descending
    ranked_ids = sorted(
        fused_scores.keys(),
        key=lambda cid: fused_scores[cid],
        reverse=True,
    )

    results: list[RetrievalResult] = []
    for chunk_id in ranked_ids[:top_k]:
        original = first_seen[chunk_id]
        results.append(
            RetrievalResult(
                content=original.content,
                score=fused_scores[chunk_id],
                document_id=original.document_id,
                chunk_id=original.chunk_id,
                metadata=dict(original.metadata),
            )
        )
    return results


# ---------------------------------------------------------------------------
# Hybrid Retriever
# ---------------------------------------------------------------------------


class HybridRetriever:
    """Orchestrates dense + BM25 retrieval with Reciprocal Rank Fusion.

    Combines vector-based semantic search with keyword-based BM25 scoring
    to improve retrieval recall and precision.

    Args:
        embedder: Embedding provider for dense retrieval.
        vectorstore: Vector store backend for nearest-neighbor search.
        rrf_k: RRF constant (default 60).
        score_threshold: Minimum score filter applied after reranking.
        reranker: Optional reranker applied after RRF fusion but before
            score threshold filtering.  When present, RRF fetches 3×
            ``top_k`` candidates to give the reranker a richer pool.
    """

    def __init__(
        self,
        embedder: EmbeddingProtocol,
        vectorstore: VectorStoreProtocol,
        *,
        rrf_k: int = 60,
        score_threshold: float = 0.0,
        reranker: RerankerProtocol | None = None,
    ) -> None:
        self._embedder = embedder
        self._vectorstore = vectorstore
        self._rrf_k = rrf_k
        self._score_threshold = score_threshold
        self._reranker = reranker
        self._bm25 = BM25Index()

    def index_chunks(self, chunks: list[Chunk]) -> None:
        """Add chunks to the BM25 keyword index incrementally.

        Call this after adding chunks to the vector store so that hybrid
        retrieval can combine both dense and keyword signals.

        Args:
            chunks: Chunks to index for BM25 keyword matching.
        """
        self._bm25.add(chunks)
        logger.info(
            "Added %d chunks to BM25 index (total: %d)", len(chunks), self._bm25._n_docs
        )

    async def retrieve(self, query: str, *, top_k: int = 5) -> list[RetrievalResult]:
        """Hybrid retrieval: dense + BM25 merged via Reciprocal Rank Fusion.

        Args:
            query: The search query.
            top_k: Maximum number of results to return.

        Returns:
            Fused and ranked retrieval results.
        """
        # Fetch more candidates when reranking so the reranker has a
        # richer pool to rescore before final top_k truncation.
        rrf_top_k = top_k * 3 if self._reranker is not None else top_k

        dense_results = await self.dense_only(query, top_k=rrf_top_k)
        bm25_results = self._bm25.search(query, top_k=rrf_top_k)

        results = reciprocal_rank_fusion(
            [dense_results, bm25_results],
            k=self._rrf_k,
            top_k=rrf_top_k,
        )

        if self._reranker is not None:
            results = await self._reranker.rerank(query, results, top_k=top_k)

        if self._score_threshold > 0.0:
            results = [r for r in results if r.score >= self._score_threshold]

        return results

    async def dense_only(self, query: str, *, top_k: int = 5) -> list[RetrievalResult]:
        """Dense-only retrieval for comparison or fallback.

        Embeds the query and searches the vector store for nearest neighbors.

        Args:
            query: The search query.
            top_k: Maximum number of results to return.

        Returns:
            Ranked retrieval results from dense vector search only.
        """
        query_embedding = await self._embedder.embed([query])
        return await self._vectorstore.search(query_embedding[0], top_k=top_k)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    """Tokenize text by lowercasing and extracting word characters.

    Strips punctuation so that ``"Python."`` and ``"python"`` match.

    Args:
        text: The input text to tokenize.

    Returns:
        List of lowercase tokens with punctuation removed.
    """
    return re.findall(r"\w+", text.lower())
