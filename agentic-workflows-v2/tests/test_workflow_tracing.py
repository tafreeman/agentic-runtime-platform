"""Integration test for tracing in WorkflowRunner."""

import os
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from agentic_v2.integrations.base import CanonicalEvent, TraceAdapter
from agentic_v2.workflows.runner import WorkflowRunner


class CaptureTraceAdapter(TraceAdapter):
    """Test adapter that captures events in a list."""

    def __init__(self):
        self.events = []

    def emit(self, event: CanonicalEvent):
        self.events.append(event)


def make_event(event_type: str, step_name: str | None = None, **data) -> CanonicalEvent:
    """Helper to create CanonicalEvent with timestamp."""
    return CanonicalEvent(
        type=event_type,
        timestamp=datetime.now(),
        step_name=step_name,
        data=data,
    )


@pytest.mark.asyncio
async def test_workflow_runner_uses_null_adapter_by_default():
    """WorkflowRunner uses NullTraceAdapter when none provided."""
    runner = WorkflowRunner()
    from agentic_v2.integrations.tracing import NullTraceAdapter

    assert isinstance(runner._trace_adapter, NullTraceAdapter)


@pytest.mark.asyncio
async def test_workflow_runner_accepts_trace_adapter():
    """WorkflowRunner accepts and stores a custom trace adapter."""
    capture = CaptureTraceAdapter()
    runner = WorkflowRunner(trace_adapter=capture)

    assert runner._trace_adapter is capture
    assert isinstance(runner._trace_adapter, TraceAdapter)


# ─────────────────────────────────────────────────────────────────────────────
# OTEL module tests
# ─────────────────────────────────────────────────────────────────────────────


class TestOtelTracingEnabled:
    """Tests for is_tracing_enabled() logic."""

    def test_tracing_disabled_by_default(self):
        """Tracing should be disabled when AGENTIC_TRACING is not set."""
        from agentic_v2.integrations.otel import is_tracing_enabled

        with patch.dict(os.environ, {}, clear=True):
            # Remove the var if present
            os.environ.pop("AGENTIC_TRACING", None)
            assert is_tracing_enabled() is False

    def test_tracing_disabled_when_zero(self):
        """Tracing should be disabled when AGENTIC_TRACING=0."""
        from agentic_v2.integrations.otel import is_tracing_enabled

        with patch.dict(os.environ, {"AGENTIC_TRACING": "0"}):
            assert is_tracing_enabled() is False

    def test_tracing_enabled_when_one(self):
        """Tracing should be enabled when AGENTIC_TRACING=1."""
        from agentic_v2.integrations.otel import is_tracing_enabled

        with patch.dict(os.environ, {"AGENTIC_TRACING": "1"}):
            assert is_tracing_enabled() is True

    def test_tracing_enabled_when_true(self):
        """Tracing should be enabled when AGENTIC_TRACING=true."""
        from agentic_v2.integrations.otel import is_tracing_enabled

        with patch.dict(os.environ, {"AGENTIC_TRACING": "true"}):
            assert is_tracing_enabled() is True


class TestOtelAdapterFactory:
    """Tests for create_trace_adapter() factory."""

    def test_returns_null_adapter_when_disabled(self):
        """Factory returns NullTraceAdapter when tracing is disabled."""
        from agentic_v2.integrations.otel import create_trace_adapter
        from agentic_v2.integrations.tracing import NullTraceAdapter

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("AGENTIC_TRACING", None)
            adapter = create_trace_adapter()
            assert isinstance(adapter, NullTraceAdapter)


class TestOtelTraceAdapter:
    """Tests for OtelTraceAdapter behavior."""

    @pytest.fixture
    def mock_tracer(self):
        """Create a mock tracer that returns mock spans."""
        tracer = MagicMock()
        mock_span = MagicMock()
        tracer.start_span.return_value = mock_span
        return tracer

    @pytest.fixture
    def adapter(self, mock_tracer):
        """Create an OtelTraceAdapter with sensitive content excluded."""
        from agentic_v2.integrations.tracing import OtelTraceAdapter

        return OtelTraceAdapter(tracer=mock_tracer, capture_sensitive=False)

    @pytest.fixture
    def sensitive_adapter(self, mock_tracer):
        """Create an OtelTraceAdapter with sensitive content included."""
        from agentic_v2.integrations.tracing import OtelTraceAdapter

        return OtelTraceAdapter(tracer=mock_tracer, capture_sensitive=True)

    def test_sensitive_content_excluded_by_default(self, mock_tracer):
        """OtelTraceAdapter excludes sensitive content by default."""
        from agentic_v2.integrations.tracing import OtelTraceAdapter

        adapter = OtelTraceAdapter(tracer=mock_tracer)
        assert adapter._capture_sensitive is False

    def test_workflow_start_event_creates_span(self, adapter, mock_tracer):
        """workflow_start event creates a root span."""
        event = make_event(
            "workflow_start",
            workflow_name="test-workflow",
            workflow_id="wf-123",
            run_id="run-456",
        )
        # Should not raise
        adapter.emit(event)
        # tracer.start_span should have been called
        mock_tracer.start_span.assert_called()
        # Span should be tracked
        assert "run-456" in adapter._workflow_spans

    def test_workflow_end_ends_span(self, adapter, mock_tracer):
        """workflow_end event ends the workflow span."""
        mock_span = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        # Start a workflow
        start_event = make_event(
            "workflow_start",
            workflow_name="test-workflow",
            run_id="run-789",
        )
        adapter.emit(start_event)
        assert "run-789" in adapter._workflow_spans

        # Complete the workflow
        end_event = make_event(
            "workflow_end",
            run_id="run-789",
            status="success",
        )
        adapter.emit(end_event)
        # Span should be ended and removed
        assert "run-789" not in adapter._workflow_spans
        # span.end() should have been called
        mock_span.end.assert_called()

    def test_step_start_creates_child_span(self, adapter, mock_tracer):
        """step_start event creates a child span under the workflow."""
        # Start workflow first
        adapter.emit(
            make_event(
                "workflow_start",
                workflow_name="test-workflow",
                run_id="run-001",
            )
        )

        # Start step
        adapter.emit(
            make_event(
                "step_start",
                step_name="analyze",
                run_id="run-001",
            )
        )

        # Step span should be tracked with run_id:step_name key
        assert "run-001:analyze" in adapter._workflow_spans

    def test_step_complete_ends_step_span(self, adapter, mock_tracer):
        """step_complete event ends the step span."""
        mock_span = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        # Setup: workflow + step
        adapter.emit(
            make_event(
                "workflow_start",
                run_id="run-002",
            )
        )
        adapter.emit(
            make_event(
                "step_start",
                step_name="generate",
                run_id="run-002",
            )
        )
        assert "run-002:generate" in adapter._workflow_spans

        # Complete step
        adapter.emit(
            make_event(
                "step_complete",
                step_name="generate",
                run_id="run-002",
                status="success",
            )
        )
        assert "run-002:generate" not in adapter._workflow_spans

    def test_sensitive_content_excluded_in_sanitize(self, adapter):
        """Sensitive fields are excluded when capture_sensitive=False."""
        data = {
            "inputs": {"secret": "value"},
            "outputs": {"result": "data"},
            "prompt": "This is a secret prompt",
            "response": "This is a secret response",
            "model": "gpt-4",  # Non-sensitive, should be included
            "status": "success",  # Non-sensitive, should be included
        }
        sanitized = adapter._sanitize_data(data)
        # Sensitive fields should be excluded
        assert "inputs" not in sanitized
        assert "outputs" not in sanitized
        assert "prompt" not in sanitized
        assert "response" not in sanitized
        # Non-sensitive fields should be included
        assert sanitized["model"] == "gpt-4"
        assert sanitized["status"] == "success"

    def test_sensitive_content_included_when_enabled(self, sensitive_adapter):
        """Sensitive fields are included when capture_sensitive=True."""
        data = {
            "inputs": {"secret": "value"},
            "prompt": "This is a secret prompt",
            "model": "gpt-4",
        }
        sanitized = sensitive_adapter._sanitize_data(data)
        # All fields should be included
        assert "inputs" in sanitized
        assert "prompt" in sanitized
        assert sanitized["model"] == "gpt-4"

    def test_non_sensitive_fields_always_included(self, adapter):
        """Non-sensitive fields are included regardless of capture_sensitive."""
        data = {
            "model": "gpt-4",
            "step_name": "analyze",
            "workflow_name": "code-review",
            "status": "completed",
        }
        sanitized = adapter._sanitize_data(data)
        assert sanitized["model"] == "gpt-4"
        assert sanitized["step_name"] == "analyze"
        assert sanitized["workflow_name"] == "code-review"
        assert sanitized["status"] == "completed"
