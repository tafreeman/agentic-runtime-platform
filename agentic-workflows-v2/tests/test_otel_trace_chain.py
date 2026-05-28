"""OTEL parent-child trace chain assertion.

Verifies the engine → agent span hierarchy is correctly wired.
Runs with in-memory span export — no external collector required.

Audit findings (2026-04-21):
- Engine layer (dag_executor.py): added engine.execute span via _run_dag() extraction
- Agent layer (agents/base.py): added agent.<name> span via contextlib.nullcontext() wrap
- Tool layer: no instrumentation yet (tools called inline from agents)
- RAG layer: no instrumentation yet (called from rag_agent)
"""
from __future__ import annotations

import pytest


@pytest.fixture
def otel_memory_exporter(monkeypatch):
    """Configure OTEL with InMemorySpanExporter and return it."""
    pytest.importorskip("opentelemetry.sdk.trace")
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    monkeypatch.setenv("AGENTIC_TRACING", "1")

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    yield exporter

    trace.set_tracer_provider(trace.NoOpTracerProvider())
    exporter.clear()


def _get_span_names(exporter) -> list[str]:
    return [span.name for span in exporter.get_finished_spans()]


def _find_span(exporter, name_fragment: str):
    for span in exporter.get_finished_spans():
        if name_fragment in span.name:
            return span
    return None


def _assert_parent_child(parent_span, child_span, exporter):
    """Assert child_span's parent is parent_span."""
    assert child_span is not None, (
        f"Expected a span containing '{child_span}' but found none. "
        f"Available spans: {_get_span_names(exporter)}"
    )
    assert child_span.parent is not None, (
        f"Span '{child_span.name}' has no parent"
    )
    assert child_span.parent.span_id == parent_span.context.span_id, (
        f"Expected '{child_span.name}' parent to be '{parent_span.name}' "
        f"but got span_id {child_span.parent.span_id}"
    )


@pytest.mark.integration
async def test_engine_agent_trace_chain(otel_memory_exporter):
    """Engine span is ancestor of agent span."""
    from agentic_v2.adapters.registry import get_registry
    from agentic_v2.engine.context import ExecutionContext
    from agentic_v2.workflows import WorkflowLoader

    registry = get_registry()
    engine = registry.get_adapter("native")

    loader = WorkflowLoader()
    workflow = loader.load("code_review")

    ctx = ExecutionContext(run_id="test-trace-chain")

    await engine.execute(workflow, ctx=ctx)

    spans = otel_memory_exporter.get_finished_spans()
    assert len(spans) > 0, "No spans were captured — check AGENTIC_TRACING=1 is set"

    engine_span = _find_span(otel_memory_exporter, "engine.")
    agent_span = _find_span(otel_memory_exporter, "agent.")

    assert engine_span is not None, (
        f"No engine span found. Spans: {_get_span_names(otel_memory_exporter)}"
    )
    assert agent_span is not None, (
        f"No agent span found. Spans: {_get_span_names(otel_memory_exporter)}"
    )
    _assert_parent_child(engine_span, agent_span, otel_memory_exporter)

    tool_span = _find_span(otel_memory_exporter, "tool.")
    if tool_span:
        _assert_parent_child(agent_span, tool_span, otel_memory_exporter)

    rag_span = _find_span(otel_memory_exporter, "rag.")
    if rag_span:
        assert tool_span is not None, "RAG span present but no tool span to parent it"
        _assert_parent_child(tool_span, rag_span, otel_memory_exporter)
