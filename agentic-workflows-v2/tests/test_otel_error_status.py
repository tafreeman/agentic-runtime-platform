"""OTEL error-status and span-nesting tests for OtelTraceAdapter.

Acceptance tests for the observability fix: failed workflows/steps must
produce spans with ``StatusCode.ERROR`` and a recorded exception event
(previously failed runs rendered green), and step spans must appear as
children of the workflow span (previously the trace tree was flat because
spans were started without a parent context).

All assertions run against an in-memory span exporter — no collector needed.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentic_v2.integrations.base import CanonicalEvent

# The whole module is meaningless without the OpenTelemetry SDK (tracing extra).
pytest.importorskip("opentelemetry.sdk.trace")

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import StatusCode

from agentic_v2.integrations.tracing import OtelTraceAdapter


@pytest.fixture
def exporter_and_adapter():
    """Return an (InMemorySpanExporter, OtelTraceAdapter) pair.

    The adapter is wired to a real tracer backed by the in-memory
    exporter so that emitted canonical events produce inspectable OTEL
    spans.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("agentic-error-status-test")
    adapter = OtelTraceAdapter(tracer=tracer, capture_sensitive=False)
    yield exporter, adapter
    exporter.clear()


def _event(event_type: str, step_name: str | None = None, **data) -> CanonicalEvent:
    return CanonicalEvent(
        type=event_type,
        timestamp=datetime.now(UTC),
        step_name=step_name,
        data=data,
    )


def _span_by_type(exporter: InMemorySpanExporter, span_type: str):
    for span in exporter.get_finished_spans():
        if span.name == span_type:
            return span
    return None


# ---------------------------------------------------------------------------
# Error status recording
# ---------------------------------------------------------------------------


def test_failed_step_span_has_error_status(exporter_and_adapter):
    """A step_complete with status=failed yields a StatusCode.ERROR span."""
    exporter, adapter = exporter_and_adapter
    run_id = "run-err-1"

    adapter.emit(_event("workflow_start", workflow_name="wf", run_id=run_id))
    adapter.emit(_event("step_start", step_name="analyze", run_id=run_id))
    adapter.emit(
        _event(
            "step_complete",
            step_name="analyze",
            run_id=run_id,
            status="failed",
            error="boom: analyze step blew up",
        )
    )
    adapter.emit(_event("workflow_end", run_id=run_id, status="failed"))

    step_span = _span_by_type(exporter, "step_start")
    assert step_span is not None
    assert step_span.status.status_code is StatusCode.ERROR
    # The recorded exception surfaces the error message to trace backends.
    event_names = [e.name for e in step_span.events]
    assert "exception" in event_names


def test_failed_workflow_span_has_error_status(exporter_and_adapter):
    """A workflow_end with status=failed yields a StatusCode.ERROR span."""
    exporter, adapter = exporter_and_adapter
    run_id = "run-err-2"

    adapter.emit(_event("workflow_start", workflow_name="wf", run_id=run_id))
    adapter.emit(_event("workflow_end", run_id=run_id, status="failed"))

    wf_span = _span_by_type(exporter, "workflow_start")
    assert wf_span is not None
    assert wf_span.status.status_code is StatusCode.ERROR
    assert "exception" in [e.name for e in wf_span.events]


def test_error_status_string_also_marks_error(exporter_and_adapter):
    """Status='error' (not just 'failed') is treated as a failure."""
    exporter, adapter = exporter_and_adapter
    run_id = "run-err-3"

    adapter.emit(_event("workflow_start", workflow_name="wf", run_id=run_id))
    adapter.emit(_event("step_start", step_name="gen", run_id=run_id))
    adapter.emit(
        _event("step_complete", step_name="gen", run_id=run_id, status="error")
    )
    adapter.emit(_event("workflow_end", run_id=run_id, status="error"))

    step_span = _span_by_type(exporter, "step_start")
    assert step_span.status.status_code is StatusCode.ERROR


def test_successful_spans_are_not_marked_error(exporter_and_adapter):
    """A successful run leaves spans without an ERROR status."""
    exporter, adapter = exporter_and_adapter
    run_id = "run-ok-1"

    adapter.emit(_event("workflow_start", workflow_name="wf", run_id=run_id))
    adapter.emit(_event("step_start", step_name="analyze", run_id=run_id))
    adapter.emit(
        _event("step_complete", step_name="analyze", run_id=run_id, status="success")
    )
    adapter.emit(_event("workflow_end", run_id=run_id, status="success"))

    for span in exporter.get_finished_spans():
        assert (
            span.status.status_code is not StatusCode.ERROR
        ), f"span {span.name} unexpectedly marked ERROR on a successful run"
        assert "exception" not in [e.name for e in span.events]


# ---------------------------------------------------------------------------
# Parent-child span nesting
# ---------------------------------------------------------------------------


def test_step_span_is_child_of_workflow_span(exporter_and_adapter):
    """Step spans nest under the workflow span (not flat siblings)."""
    exporter, adapter = exporter_and_adapter
    run_id = "run-tree-1"

    adapter.emit(_event("workflow_start", workflow_name="wf", run_id=run_id))
    adapter.emit(_event("step_start", step_name="analyze", run_id=run_id))
    adapter.emit(
        _event("step_complete", step_name="analyze", run_id=run_id, status="success")
    )
    adapter.emit(_event("workflow_end", run_id=run_id, status="success"))

    wf_span = _span_by_type(exporter, "workflow_start")
    step_span = _span_by_type(exporter, "step_start")

    assert wf_span is not None and step_span is not None
    assert step_span.parent is not None, "step span has no parent — flat trace"
    assert (
        step_span.parent.span_id == wf_span.context.span_id
    ), "step span is not parented to the workflow span"
    # Same trace → they belong to one logical workflow trace.
    assert step_span.context.trace_id == wf_span.context.trace_id


def test_multiple_steps_all_child_of_workflow(exporter_and_adapter):
    """Every step span in a run is a child of the same workflow span."""
    exporter, adapter = exporter_and_adapter
    run_id = "run-tree-2"

    adapter.emit(_event("workflow_start", workflow_name="wf", run_id=run_id))
    for step in ("analyze", "generate", "review"):
        adapter.emit(_event("step_start", step_name=step, run_id=run_id))
        adapter.emit(
            _event("step_complete", step_name=step, run_id=run_id, status="success")
        )
    adapter.emit(_event("workflow_end", run_id=run_id, status="success"))

    wf_span = _span_by_type(exporter, "workflow_start")
    assert wf_span is not None
    step_spans = [s for s in exporter.get_finished_spans() if s.name == "step_start"]
    assert len(step_spans) == 3
    for step_span in step_spans:
        assert step_span.parent is not None
        assert step_span.parent.span_id == wf_span.context.span_id
