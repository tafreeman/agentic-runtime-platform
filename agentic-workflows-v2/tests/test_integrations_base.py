"""Unit tests for base adapter contracts and tracing."""

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from agentic_v2.integrations.base import (
    AgentAdapter,
    CanonicalEvent,
    ToolAdapter,
    TraceAdapter,
    WorkflowAdapter,
)
from agentic_v2.integrations.tracing import (
    CompositeTraceAdapter,
    ConsoleTraceAdapter,
    FileTraceAdapter,
    NullTraceAdapter,
)


# Test W1-AD-001 requirement #1: AgentAdapter is abstract
def test_agent_adapter_is_abstract():
    """Cannot instantiate AgentAdapter directly."""
    with pytest.raises(TypeError) as exc_info:
        AgentAdapter()

    assert (
        "abstract" in str(exc_info.value).lower()
        or "instantiate" in str(exc_info.value).lower()
    )


# Test W1-AD-001 requirement #2: CanonicalEvent round-trips through JSON
def test_canonical_event_serializable():
    """CanonicalEvent round-trips through JSON."""
    event = CanonicalEvent(
        type="test_event",
        timestamp=datetime(2026, 2, 13, 10, 30, 0),
        step_name="test_step",
        data={"key": "value", "count": 42},
    )

    # Serialize to dict
    event_dict = event.to_dict()
    assert event_dict["type"] == "test_event"
    assert event_dict["step_name"] == "test_step"
    assert event_dict["data"]["key"] == "value"

    # Serialize to JSON string
    event_json = event.to_json()
    loaded = json.loads(event_json)
    assert loaded["type"] == "test_event"

    # Round-trip through from_dict
    recovered = CanonicalEvent.from_dict(event_dict)
    assert recovered.type == event.type
    assert recovered.step_name == event.step_name
    assert recovered.data == event.data


# Test W1-AD-001 requirement #3: Concrete stub implementing all methods passes isinstance checks
def test_adapter_subclass_contract():
    """Concrete stub implementing all methods passes isinstance checks."""

    class StubAgentAdapter(AgentAdapter):
        async def invoke(self, prompt: str, context: dict):
            return {"output": "stub response"}

    class StubToolAdapter(ToolAdapter):
        async def execute(self, tool_name: str, args: dict):
            return {"output": "stub result", "success": True}

    class StubWorkflowAdapter(WorkflowAdapter):
        async def run(self, workflow_def: dict, inputs: dict):
            return {"status": "success", "outputs": {}, "metadata": {}}

    class StubTraceAdapter(TraceAdapter):
        def emit(self, event: CanonicalEvent):
            pass

    # All stubs should pass isinstance checks
    agent = StubAgentAdapter()
    tool = StubToolAdapter()
    workflow = StubWorkflowAdapter()
    trace = StubTraceAdapter()

    assert isinstance(agent, AgentAdapter)
    assert isinstance(tool, ToolAdapter)
    assert isinstance(workflow, WorkflowAdapter)
    assert isinstance(trace, TraceAdapter)


# Additional tests for concrete tracing implementations


def test_console_trace_adapter_emits():
    """ConsoleTraceAdapter emits events without error."""
    adapter = ConsoleTraceAdapter(pretty_print=True)

    event = CanonicalEvent(
        type="test_event",
        timestamp=datetime.now(),
        step_name="test_step",
        data={"test": "data"},
    )

    # Should not raise
    adapter.emit(event)


def test_file_trace_adapter_writes():
    """FileTraceAdapter writes events to file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "trace.jsonl"
        adapter = FileTraceAdapter(file_path, buffer_size=1)

        event1 = CanonicalEvent(
            type="event_1", timestamp=datetime.now(), data={"id": 1}
        )
        event2 = CanonicalEvent(
            type="event_2", timestamp=datetime.now(), data={"id": 2}
        )

        adapter.emit(event1)
        adapter.emit(event2)

        # Force flush
        adapter._flush()

        # Read and verify
        lines = file_path.read_text().strip().split("\n")
        assert len(lines) == 2

        loaded1 = json.loads(lines[0])
        loaded2 = json.loads(lines[1])

        assert loaded1["type"] == "event_1"
        assert loaded1["data"]["id"] == 1
        assert loaded2["type"] == "event_2"
        assert loaded2["data"]["id"] == 2


def test_composite_trace_adapter_forwards():
    """CompositeTraceAdapter forwards to multiple adapters."""
    captured_events = []

    class CaptureAdapter(TraceAdapter):
        def emit(self, event: CanonicalEvent):
            captured_events.append(event)

    adapter1 = CaptureAdapter()
    adapter2 = CaptureAdapter()
    composite = CompositeTraceAdapter(adapter1, adapter2)

    event = CanonicalEvent(type="test", timestamp=datetime.now())

    composite.emit(event)

    # Both adapters should have received the event
    assert len(captured_events) == 2
    assert captured_events[0].type == "test"
    assert captured_events[1].type == "test"


def test_null_trace_adapter_no_op():
    """NullTraceAdapter discards events without error."""
    adapter = NullTraceAdapter()

    event = CanonicalEvent(type="test", timestamp=datetime.now())

    # Should not raise
    adapter.emit(event)


def test_trace_adapter_helpers():
    """TraceAdapter helper methods emit correct event types."""
    captured = []

    class CaptureAdapter(TraceAdapter):
        def emit(self, event: CanonicalEvent):
            captured.append(event)

    adapter = CaptureAdapter()

    adapter.emit_workflow_start("test_workflow", "run_123", {"input": "value"})
    adapter.emit_step_start("step_1", "run_123", {"arg": "val"})
    adapter.emit_step_complete("step_1", "run_123", "success", {"output": "result"})
    adapter.emit_workflow_end(
        "test_workflow", "run_123", "success", {"final": "output"}
    )

    assert len(captured) == 4
    assert captured[0].type == "workflow_start"
    assert captured[0].data["workflow_name"] == "test_workflow"
    assert captured[1].type == "step_start"
    assert captured[1].step_name == "step_1"
    assert captured[2].type == "step_complete"
    assert captured[2].data["status"] == "success"
    assert captured[3].type == "workflow_end"
