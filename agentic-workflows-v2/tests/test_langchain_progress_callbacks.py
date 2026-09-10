"""Progress callbacks observe one real graph execution, including failures."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langgraph.graph import END, START, StateGraph

from agentic_v2.adapters.langchain import LangChainEngine
from agentic_v2.contracts import StepStatus
from agentic_v2.langchain.runner import WorkflowRunner
from agentic_v2.langchain.state import WorkflowState


@pytest.mark.parametrize("node_fails", [False, True])
async def test_progress_observes_success_or_failure_once(node_fails, monkeypatch):
    calls = []
    events = []

    async def node(state):
        calls.append(state)
        if node_fails:
            raise ValueError("node failed")
        return {
            "steps": {"step1": {"status": "success", "outputs": {"result": "done"}}}
        }

    async def updated(event):
        events.append(event)

    trace = MagicMock()
    runner = WorkflowRunner(trace_adapter=trace)
    graph = (
        StateGraph(WorkflowState)
        .add_node("step1", node)
        .add_edge(START, "step1")
        .add_edge("step1", END)
        .compile(checkpointer=runner._checkpointer)
    )
    monkeypatch.setattr(runner, "_get_or_compile", lambda *args: graph)
    config = runner.load_workflow("test_deterministic")
    result = await LangChainEngine(runner=runner).execute(
        config, on_update=updated, input_text="hello", thread_id="observed"
    )
    assert len(calls) == 1
    assert [e["type"] for e in events] == [
        "step_start",
        "step_error" if node_fails else "step_end",
    ]
    assert all(e["step"] == "step1" and e["run_id"] == "observed" for e in events)
    assert result.overall_status is (
        StepStatus.FAILED if node_fails else StepStatus.SUCCESS
    )
    trace.emit_workflow_start.assert_called_once()
    trace.emit_workflow_end.assert_called_once()
    if node_fails:
        assert "node failed" in events[-1]["error"]


async def test_callback_failure_propagates_without_replaying_graph(monkeypatch):
    calls = []

    async def node(state):
        calls.append(state)
        return {
            "steps": {"step1": {"status": "success", "outputs": {"result": "done"}}}
        }

    async def updated(event):
        if event["type"] == "step_end":
            raise RuntimeError("observer failed")

    trace = MagicMock()
    runner = WorkflowRunner(trace_adapter=trace)
    graph = (
        StateGraph(WorkflowState)
        .add_node("step1", node)
        .add_edge(START, "step1")
        .add_edge("step1", END)
        .compile(checkpointer=runner._checkpointer)
    )
    monkeypatch.setattr(runner, "_get_or_compile", lambda *args: graph)
    config = runner.load_workflow("test_deterministic")
    with pytest.raises(RuntimeError, match="observer failed"):
        await LangChainEngine(runner=runner).execute(
            config, on_update=updated, input_text="hello"
        )
    assert len(calls) == 1
    assert trace.emit_workflow_end.call_args.args[2] == "failed"
    trace.emit_workflow_end.assert_called_once()
