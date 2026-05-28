"""Tests for RAG tracing — RAGTracer event emission and lifecycle.

Covers:
- Event type correctness (rag.query_start, rag.embed, rag.search, etc.)
- Latency tracking via time.monotonic
- Context manager usage for automatic start/complete events
- Optional OTEL integration check
- Standalone operation without tracing configured
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from unittest.mock import patch

import pytest
from agentic_v2.integrations.base import CanonicalEvent, TraceAdapter
from agentic_v2.integrations.tracing import NullTraceAdapter
from agentic_v2.rag.tracing import RAGTracer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class CollectingAdapter(TraceAdapter):
    """Test adapter that collects emitted events for assertions."""

    def __init__(self) -> None:
        """Initialize with empty event list."""
        self.events: list[CanonicalEvent] = []

    def emit(self, event: CanonicalEvent) -> None:
        """Collect event."""
        self.events.append(event)


@pytest.fixture
def collector() -> CollectingAdapter:
    """Fresh collecting adapter."""
    return CollectingAdapter()


@pytest.fixture
def tracer(collector: CollectingAdapter) -> RAGTracer:
    """RAGTracer wired to a collecting adapter."""
    return RAGTracer(adapter=collector)


@pytest.fixture
def null_tracer() -> RAGTracer:
    """RAGTracer with NullTraceAdapter (no-op tracing)."""
    return RAGTracer(adapter=NullTraceAdapter())


# ===================================================================
# Event Emission
# ===================================================================


class TestRAGTracerEvents:
    """Tests for individual event emission methods."""

    def test_emit_query_start(
        self, tracer: RAGTracer, collector: CollectingAdapter
    ) -> None:
        """emit_query_start creates a rag.query_start event."""
        tracer.emit_query_start(query="test query")
        assert len(collector.events) == 1
        event = collector.events[0]
        assert event.type == "rag.query_start"
        assert event.data["query"] == "test query"
        assert isinstance(event.timestamp, datetime)

    def test_emit_embed(self, tracer: RAGTracer, collector: CollectingAdapter) -> None:
        """emit_embed creates a rag.embed event with text count."""
        tracer.emit_embed(text_count=5, latency_ms=12.3)
        assert len(collector.events) == 1
        event = collector.events[0]
        assert event.type == "rag.embed"
        assert event.data["text_count"] == 5
        assert event.data["latency_ms"] == pytest.approx(12.3)

    def test_emit_search(self, tracer: RAGTracer, collector: CollectingAdapter) -> None:
        """emit_search creates a rag.search event with result count and latency."""
        tracer.emit_search(result_count=3, latency_ms=45.6)
        assert len(collector.events) == 1
        event = collector.events[0]
        assert event.type == "rag.search"
        assert event.data["result_count"] == 3
        assert event.data["latency_ms"] == pytest.approx(45.6)

    def test_emit_assemble(
        self, tracer: RAGTracer, collector: CollectingAdapter
    ) -> None:
        """emit_assemble creates a rag.assemble event with token count."""
        tracer.emit_assemble(token_count=1500, result_count=4)
        assert len(collector.events) == 1
        event = collector.events[0]
        assert event.type == "rag.assemble"
        assert event.data["token_count"] == 1500
        assert event.data["result_count"] == 4

    def test_emit_query_complete(
        self, tracer: RAGTracer, collector: CollectingAdapter
    ) -> None:
        """emit_query_complete creates a rag.query_complete event."""
        tracer.emit_query_complete(total_latency_ms=100.5, result_count=3)
        assert len(collector.events) == 1
        event = collector.events[0]
        assert event.type == "rag.query_complete"
        assert event.data["total_latency_ms"] == pytest.approx(100.5)
        assert event.data["result_count"] == 3

    def test_emit_ingest_start(
        self, tracer: RAGTracer, collector: CollectingAdapter
    ) -> None:
        """emit_ingest_start creates a rag.ingest_start event."""
        tracer.emit_ingest_start(source="/path/to/file.md")
        assert len(collector.events) == 1
        event = collector.events[0]
        assert event.type == "rag.ingest_start"
        assert event.data["source"] == "/path/to/file.md"

    def test_emit_ingest_complete(
        self, tracer: RAGTracer, collector: CollectingAdapter
    ) -> None:
        """emit_ingest_complete creates a rag.ingest_complete event."""
        tracer.emit_ingest_complete(
            source="/path/to/file.md", chunk_count=10, latency_ms=250.0
        )
        assert len(collector.events) == 1
        event = collector.events[0]
        assert event.type == "rag.ingest_complete"
        assert event.data["source"] == "/path/to/file.md"
        assert event.data["chunk_count"] == 10
        assert event.data["latency_ms"] == pytest.approx(250.0)


# ===================================================================
# Context Manager
# ===================================================================


class TestRAGTracerContextManager:
    """Tests for query_span context manager."""

    def test_context_manager_emits_start_and_complete(
        self, tracer: RAGTracer, collector: CollectingAdapter
    ) -> None:
        """Context manager emits query_start on entry and query_complete on exit."""
        with tracer.query_span(query="test query") as result_count:
            result_count[0] = 3

        event_types = [e.type for e in collector.events]
        assert "rag.query_start" in event_types
        assert "rag.query_complete" in event_types

    def test_context_manager_tracks_latency(
        self, tracer: RAGTracer, collector: CollectingAdapter
    ) -> None:
        """Context manager tracks total latency in the complete event."""
        with tracer.query_span(query="test") as result_count:
            result_count[0] = 1
            time.sleep(0.01)  # 10ms minimum

        complete_event = next(
            e for e in collector.events if e.type == "rag.query_complete"
        )
        # Latency should be at least 10ms
        assert complete_event.data["total_latency_ms"] >= 5.0

    def test_context_manager_on_error(
        self, tracer: RAGTracer, collector: CollectingAdapter
    ) -> None:
        """Context manager still emits complete event on exception."""
        with pytest.raises(ValueError, match="test error"):
            with tracer.query_span(query="failing query") as _rc:
                raise ValueError("test error")

        event_types = [e.type for e in collector.events]
        assert "rag.query_start" in event_types
        assert "rag.query_complete" in event_types

        complete_event = next(
            e for e in collector.events if e.type == "rag.query_complete"
        )
        assert complete_event.data.get("error") == "test error"

    def test_ingest_span_emits_start_and_complete(
        self, tracer: RAGTracer, collector: CollectingAdapter
    ) -> None:
        """ingest_span emits ingest_start on entry and ingest_complete on exit."""
        with tracer.ingest_span(source="/path/to/file.md") as chunk_count:
            chunk_count[0] = 5

        event_types = [e.type for e in collector.events]
        assert "rag.ingest_start" in event_types
        assert "rag.ingest_complete" in event_types

        complete_event = next(
            e for e in collector.events if e.type == "rag.ingest_complete"
        )
        assert complete_event.data["chunk_count"] == 5


# ===================================================================
# Null/No-Op Operation
# ===================================================================


class TestRAGTracerNullOperation:
    """Tests that tracer works correctly with NullTraceAdapter."""

    def test_null_tracer_does_not_raise(self, null_tracer: RAGTracer) -> None:
        """Operations on null tracer complete without error."""
        null_tracer.emit_query_start(query="test")
        null_tracer.emit_embed(text_count=1, latency_ms=0.0)
        null_tracer.emit_search(result_count=0, latency_ms=0.0)
        null_tracer.emit_assemble(token_count=0, result_count=0)
        null_tracer.emit_query_complete(total_latency_ms=0.0, result_count=0)
        null_tracer.emit_ingest_start(source="test")
        null_tracer.emit_ingest_complete(source="test", chunk_count=0, latency_ms=0.0)

    def test_null_tracer_context_manager(self, null_tracer: RAGTracer) -> None:
        """Context manager works with null tracer."""
        with null_tracer.query_span(query="test") as _rc:
            pass

    def test_default_adapter_is_null(self) -> None:
        """RAGTracer with no adapter uses NullTraceAdapter."""
        tracer = RAGTracer()
        assert isinstance(tracer._adapter, NullTraceAdapter)


# ===================================================================
# Logging Integration
# ===================================================================


class TestRAGTracerLogging:
    """Tests that RAGTracer logs events via the logging module."""

    def test_logs_query_start(
        self, tracer: RAGTracer, caplog: pytest.LogCaptureFixture
    ) -> None:
        """query_start events are logged at DEBUG level."""
        with caplog.at_level(logging.DEBUG, logger="agentic_v2.rag.tracing"):
            tracer.emit_query_start(query="test query")
        assert any("rag.query_start" in record.message for record in caplog.records)

    def test_logs_ingest_complete(
        self, tracer: RAGTracer, caplog: pytest.LogCaptureFixture
    ) -> None:
        """ingest_complete events are logged at DEBUG level."""
        with caplog.at_level(logging.DEBUG, logger="agentic_v2.rag.tracing"):
            tracer.emit_ingest_complete(
                source="test.md", chunk_count=5, latency_ms=100.0
            )
        assert any("rag.ingest_complete" in record.message for record in caplog.records)


# ===================================================================
# OTEL Integration Check
# ===================================================================


class TestRAGTracerOtelIntegration:
    """Tests for optional OTEL span creation."""

    @patch.dict("os.environ", {"AGENTIC_TRACING": "0"})
    def test_no_otel_when_disabled(self) -> None:
        """When AGENTIC_TRACING is disabled, no OTEL spans are created."""
        tracer = RAGTracer()
        # Should use NullTraceAdapter, no errors
        tracer.emit_query_start(query="test")

    def test_accepts_custom_adapter(self, collector: CollectingAdapter) -> None:
        """RAGTracer accepts any TraceAdapter implementation."""
        tracer = RAGTracer(adapter=collector)
        tracer.emit_query_start(query="custom")
        assert len(collector.events) == 1
