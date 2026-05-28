"""RAG reranking implementations — rescore retrieval results for precision.

Provides:
- :class:`NoOpReranker`: Passthrough (slices to ``top_k``).
- :class:`CrossEncoderReranker`: Reranks via a cross-encoder scoring function.
- :class:`LLMReranker`: Reranks via an async LLM scoring callable with
  bounded concurrency.

All implementations satisfy :class:`~agentic_v2.rag.protocols.RerankerProtocol`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence

from .contracts import RetrievalResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# NoOpReranker
# ---------------------------------------------------------------------------


class NoOpReranker:
    """Passthrough reranker — returns results unchanged, sliced to *top_k*.

    Useful as a baseline or when reranking is disabled.
    """

    async def rerank(
        self,
        query: str,
        results: list[RetrievalResult],
        *,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        """Return *results* unchanged, truncated to *top_k*."""
        return results[:top_k]


# ---------------------------------------------------------------------------
# CrossEncoderReranker
# ---------------------------------------------------------------------------


class CrossEncoderReranker:
    """Reranker using a cross-encoder scoring function.

    Accepts a *predict_fn* that takes a list of ``(query, document)``
    pairs and returns a list of relevance scores.  If no *predict_fn*
    is supplied, falls back to ``sentence_transformers.CrossEncoder``.

    Args:
        model_name: Cross-encoder model identifier (used when
            *predict_fn* is ``None``).
        predict_fn: Optional callable ``(pairs) → scores``.  When
            supplied, *model_name* is ignored.
        batch_size: Batch size for model inference.
    """

    def __init__(
        self,
        *,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        predict_fn: Callable[[list[tuple[str, str]]], Sequence[float]] | None = None,
        batch_size: int = 32,
    ) -> None:
        self._batch_size = batch_size

        if predict_fn is not None:
            self._predict = predict_fn
        else:
            try:
                from sentence_transformers import (
                    CrossEncoder,  # type: ignore[import-untyped]
                )

                model = CrossEncoder(model_name)

                def _predict(pairs: list[tuple[str, str]]) -> Sequence[float]:
                    return model.predict(pairs, batch_size=self._batch_size)

                self._predict = _predict
            except ImportError as exc:
                raise ImportError(
                    "sentence-transformers is required for CrossEncoderReranker. "
                    "Install it with: pip install sentence-transformers"
                ) from exc

    async def rerank(
        self,
        query: str,
        results: list[RetrievalResult],
        *,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        """Rerank *results* using cross-encoder scores."""
        if not results:
            return []

        pairs = [(query, r.content) for r in results]

        # Run synchronous predict in a thread to avoid blocking the loop
        loop = asyncio.get_running_loop()
        scores = await loop.run_in_executor(None, self._predict, pairs)

        # Pair results with their new scores and sort descending
        scored = sorted(
            zip(scores, results),
            key=lambda pair: pair[0],
            reverse=True,
        )

        reranked: list[RetrievalResult] = []
        for score, result in scored[:top_k]:
            reranked.append(
                RetrievalResult(
                    content=result.content,
                    score=float(score),
                    document_id=result.document_id,
                    chunk_id=result.chunk_id,
                    metadata=dict(result.metadata),
                )
            )

        logger.debug(
            "CrossEncoder reranked %d → %d results", len(results), len(reranked)
        )
        return reranked


# ---------------------------------------------------------------------------
# LLMReranker
# ---------------------------------------------------------------------------


class LLMReranker:
    """Reranker using an async LLM scoring callable.

    Scores each ``(query, document)`` pair concurrently via *score_fn*,
    bounded by an :class:`asyncio.Semaphore` to limit concurrency.

    Args:
        score_fn: Async callable ``(query, doc) → float`` returning a
            relevance score.
        max_concurrency: Maximum concurrent scoring calls.
    """

    def __init__(
        self,
        *,
        score_fn: Callable[[str, str], Awaitable[float]],
        max_concurrency: int = 5,
    ) -> None:
        self._score_fn = score_fn
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def _score_one(self, query: str, content: str) -> float:
        """Score a single document with semaphore-bounded concurrency."""
        async with self._semaphore:
            return await self._score_fn(query, content)

    async def rerank(
        self,
        query: str,
        results: list[RetrievalResult],
        *,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        """Rerank *results* using concurrent LLM scoring."""
        if not results:
            return []

        # Score all results concurrently (bounded by semaphore)
        score_tasks = [self._score_one(query, r.content) for r in results]
        scores = await asyncio.gather(*score_tasks)

        # Pair results with scores and sort descending
        scored = sorted(
            zip(scores, results),
            key=lambda pair: pair[0],
            reverse=True,
        )

        reranked: list[RetrievalResult] = []
        for score, result in scored[:top_k]:
            reranked.append(
                RetrievalResult(
                    content=result.content,
                    score=float(score),
                    document_id=result.document_id,
                    chunk_id=result.chunk_id,
                    metadata=dict(result.metadata),
                )
            )

        logger.debug("LLM reranked %d → %d results", len(results), len(reranked))
        return reranked
