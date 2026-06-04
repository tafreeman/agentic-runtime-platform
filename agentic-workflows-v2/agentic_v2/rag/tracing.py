"""RAG tracing — structured event emission for RAG pipeline operations.

Provides :class:`RAGTracer` which emits :class:`CanonicalEvent` instances
through the project's :class:`TraceAdapter` infrastructure.  Tracing is
opt-in: a :class:`NullTraceAdapter` is used by default so that the RAG
pipeline works without any tracing configuration.

Events emitted:
- ``rag.query_start``: When a RAG query begins.
- ``rag.embed``: When text is embedded.
- ``rag.search``: When vector search completes (with result count, latency).
- ``rag.assemble``: When context is assembled (with token count).
- ``rag.query_complete``: When the full RAG pipeline finishes (with total latency).
- ``rag.ingest_start``: When ingestion begins.
- ``rag.ingest_complete``: When ingestion finishes (with chunk count).
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Generator

from ..integrations.base import CanonicalEvent, TraceAdapter
from ..integrations.tracing import NullTraceAdapter

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


#: Type alias for span accumulators — single-element lists that the caller
#: writes into (e.g., ``count[0] = N``).  Using a list (rather than a mutable
#: dataclass) avoids violating the project's "immutability first" rule for
#: domain objects while still allowing the context manager to read back
#: the value on exit.
IngestChunkCount = list[int]
QueryResultCount = list[int]


class RAGTracer:
    """Emit structured trace events for RAG operations.

    All events are emitted via the project's :class:`TraceAdapter` interface
    and simultaneously logged at DEBUG level for local observability.

    Args:
        adapter: TraceAdapter implementation for event emission.
            Defaults to :class:`NullTraceAdapter` (no-op).
    """

    def __init__(self, adapter: TraceAdapter | None = None) -> None:
        self._adapter: TraceAdapter = adapter or NullTraceAdapter()

    # -----------------------------------------------------------------
    # Individual event emitters
    # -----------------------------------------------------------------

    def emit_query_start(self, *, query: str) -> None:
        """Emit a ``rag.query_start`` event.

        Args:
            query: The search query text.
        """
        self._emit("rag.query_start", data={"query": query})

    def emit_embed(self, *, text_count: int, latency_ms: float) -> None:
        """Emit a ``rag.embed`` event.

        Args:
            text_count: Number of texts embedded.
            latency_ms: Embedding latency in milliseconds.
        """
        self._emit(
            "rag.embed",
            data={"text_count": text_count, "latency_ms": latency_ms},
        )

    def emit_search(self, *, result_count: int, latency_ms: float) -> None:
        """Emit a ``rag.search`` event.

        Args:
            result_count: Number of results returned.
            latency_ms: Search latency in milliseconds.
        """
        self._emit(
            "rag.search",
            data={"result_count": result_count, "latency_ms": latency_ms},
        )

    def emit_assemble(self, *, token_count: int, result_count: int) -> None:
        """Emit a ``rag.assemble`` event.

        Args:
            token_count: Token count of assembled context.
            result_count: Number of results included.
        """
        self._emit(
            "rag.assemble",
            data={"token_count": token_count, "result_count": result_count},
        )

    def emit_query_complete(
        self,
        *,
        total_latency_ms: float,
        result_count: int,
        error: str | None = None,
    ) -> None:
        """Emit a ``rag.query_complete`` event.

        Args:
            total_latency_ms: Total query pipeline latency in milliseconds.
            result_count: Number of results in the final response.
            error: Error message if the query failed.
        """
        data: dict[str, Any] = {
            "total_latency_ms": total_latency_ms,
            "result_count": result_count,
        }
        if error is not None:
            data["error"] = error
        self._emit("rag.query_complete", data=data)

    def emit_ingest_start(self, *, source: str) -> None:
        """Emit a ``rag.ingest_start`` event.

        Args:
            source: Source path or identifier being ingested.
        """
        self._emit("rag.ingest_start", data={"source": source})

    def emit_ingest_complete(
        self,
        *,
        source: str,
        chunk_count: int,
        latency_ms: float,
    ) -> None:
        """Emit a ``rag.ingest_complete`` event.

        Args:
            source: Source path or identifier.
            chunk_count: Number of chunks produced.
            latency_ms: Ingestion latency in milliseconds.
        """
        self._emit(
            "rag.ingest_complete",
            data={
                "source": source,
                "chunk_count": chunk_count,
                "latency_ms": latency_ms,
            },
        )

    # -----------------------------------------------------------------
    # Context managers for automatic start/complete
    # -----------------------------------------------------------------

    @contextmanager
    def query_span(self, *, query: str) -> Generator[QueryResultCount, None, None]:
        """Context manager that emits query_start/query_complete automatically.

        Yields a single-element ``list[int]`` accumulator.  The caller
        records the result count by writing ``result_count[0] = N``.
        Tracks latency via ``time.monotonic()``.  On exception, the
        complete event includes the error message, and the exception
        is re-raised.

        Args:
            query: The search query text.

        Yields:
            Single-element list — write ``result[0] = count``.
        """
        self.emit_query_start(query=query)
        result_count: QueryResultCount = [0]
        start_ns = time.perf_counter_ns()
        error_msg: str | None = None
        try:
            yield result_count
        except Exception as exc:
            error_msg = str(exc)
            raise
        finally:
            elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
            self.emit_query_complete(
                total_latency_ms=elapsed_ms,
                result_count=result_count[0],
                error=error_msg,
            )

    @contextmanager
    def ingest_span(self, *, source: str) -> Generator[IngestChunkCount, None, None]:
        """Context manager that emits ingest_start/ingest_complete automatically.

        Yields a single-element ``list[int]`` accumulator.  The caller records
        the chunk count by writing ``chunk_count[0] = N``.  The context
        manager reads the value on exit for the complete event.

        Args:
            source: Source path or identifier.

        Yields:
            Single-element list — write ``result[0] = chunk_count``.
        """
        self.emit_ingest_start(source=source)
        chunk_count: IngestChunkCount = [0]
        start_ns = time.perf_counter_ns()
        try:
            yield chunk_count
        finally:
            elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0
            self.emit_ingest_complete(
                source=source,
                chunk_count=chunk_count[0],
                latency_ms=elapsed_ms,
            )

    # -----------------------------------------------------------------
    # Internal
    # -----------------------------------------------------------------

    def _emit(self, event_type: str, *, data: dict[str, Any]) -> None:
        """Create a CanonicalEvent and emit it via the adapter.

        Also logs the event at DEBUG level.

        Args:
            event_type: The event type string (e.g. ``rag.query_start``).
            data: Event payload.
        """
        event = CanonicalEvent(
            type=event_type,
            timestamp=_utc_now(),
            data=data,
        )
        logger.debug("Emitting %s: %s", event_type, data)
        self._adapter.emit(event)
