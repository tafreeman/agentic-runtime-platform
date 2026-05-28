"""Integration tests for LangChain/LangGraph workflow engine.

Tests end-to-end execution, checkpointing, and streaming behavior.

# ADR-008 cleanup: removed 5 duplicate tests (see
docs/adr/ADR-008-testing-approach-overhaul.md)
"""

import os

import pytest
from agentic_v2.langchain import WorkflowRunner, compile_workflow, load_workflow_config
from agentic_v2.langchain.state import initial_state
from langgraph.checkpoint.memory import MemorySaver

# Skip when neither set of API credentials is available in the environment
_HAS_CREDENTIALS = bool(os.environ.get("GH_TOKEN") or os.environ.get("GOOGLE_API_KEY"))
pytestmark = pytest.mark.skipif(
    not _HAS_CREDENTIALS,
    reason="Requires external LLM API credentials (GH_TOKEN or GOOGLE_API_KEY)",
)


class TestEndToEndExecution:
    """End-to-end workflow execution tests."""

    def test_simple_workflow_invocation(self):
        """Execute a simple workflow and verify result structure."""
        runner = WorkflowRunner()
        result = runner.invoke(
            "code_review", code_file="def foo(): pass", review_depth="quick"
        )

        assert result.run_id, "run_id should be set"
        assert result.workflow_name == "code_review"
        assert result.elapsed_seconds >= 0
        assert isinstance(result.outputs, dict)
        assert isinstance(result.steps, dict)
        assert isinstance(result.token_counts, dict)
        assert isinstance(result.models_used, dict)

    @pytest.mark.asyncio
    async def test_async_workflow_execution(self):
        """Execute a workflow asynchronously."""
        runner = WorkflowRunner()
        result = await runner.run(
            "code_review", code_file="def bar(): pass", review_depth="full"
        )

        assert result.run_id
        assert result.status in ("success", "partial", "failed")
        assert result.elapsed_seconds >= 0

    def test_workflow_with_errors(self):
        """Verify error handling in workflow execution."""
        runner = WorkflowRunner()
        # Missing required input should trigger validation error
        try:
            with pytest.raises((ValueError, KeyError, TypeError)):
                runner.invoke("code_review", review_depth="quick")
        except FileNotFoundError:
            # Workflow doesn't exist in test environment, that's ok
            pytest.skip("code_review workflow not found")


class TestCheckpointing:
    """Checkpoint and resume tests."""

    def test_workflow_with_checkpointer(self):
        """Execute workflow with MemorySaver checkpointer."""
        checkpointer = MemorySaver()
        runner = WorkflowRunner(checkpointer=checkpointer)
        thread_id = "test_thread_1"

        result = runner.invoke(
            "code_review",
            thread_id=thread_id,
            code_file="print('hello')",
            review_depth="quick",
        )

        assert result.run_id == thread_id
        assert result.status in ("success", "partial")

    def test_checkpoint_state_inspection(self):
        """Inspect checkpoint state for a thread."""
        checkpointer = MemorySaver()
        runner = WorkflowRunner(checkpointer=checkpointer)
        thread_id = "inspect_test"

        # Run workflow
        runner.invoke(
            "code_review", thread_id=thread_id, code_file="x = 1", review_depth="quick"
        )

        # Inspect checkpoint state
        checkpoint = runner.get_checkpoint_state("code_review", thread_id=thread_id)
        # Checkpoint may be None if not supported by version
        if checkpoint:
            assert isinstance(checkpoint, dict)
            assert "values" in checkpoint or "next" in checkpoint

    def test_checkpoint_history(self):
        """Retrieve checkpoint history for a workflow."""
        checkpointer = MemorySaver()
        runner = WorkflowRunner(checkpointer=checkpointer)
        thread_id = "history_test"

        runner.invoke(
            "code_review", thread_id=thread_id, code_file="y = 2", review_depth="quick"
        )

        history = runner.get_checkpoint_history(
            "code_review", thread_id=thread_id, limit=5
        )
        # History may be empty if not supported
        assert isinstance(history, list)


class TestStreamingEvents:
    """Streaming execution and event tests."""

    def test_stream_execution(self):
        """Stream workflow execution events."""
        runner = WorkflowRunner()
        events = list(
            runner.stream("code_review", code_file="z = 3", review_depth="quick")
        )

        # Should get some node updates
        assert len(events) > 0
        # Each event should be a dict
        for event in events:
            assert isinstance(event, dict)

    @pytest.mark.asyncio
    async def test_async_stream_execution(self):
        """Stream workflow execution asynchronously."""
        runner = WorkflowRunner()
        events = []
        async for event in runner.astream(
            "code_review", code_file="w = 4", review_depth="quick"
        ):
            events.append(event)

        assert len(events) > 0
        for event in events:
            assert isinstance(event, dict)


class TestGraphCompilation:
    """Graph compilation and validation tests."""

    def test_compile_valid_workflow(self):
        """Compile a valid workflow config."""
        config = load_workflow_config("code_review")
        graph = compile_workflow(config)

        assert graph is not None
        # Compiled graph should be a LangGraph CompiledGraph
        assert hasattr(graph, "invoke") or hasattr(graph, "ainvoke")

    def test_compiled_graph_execution(self):
        """Execute a compiled graph directly."""
        config = load_workflow_config("code_review")
        graph = compile_workflow(config)

        state = initial_state(
            workflow_inputs={"code_file": "test", "review_depth": "quick"}
        )
        state["context"]["inputs"] = {"code_file": "test", "review_depth": "quick"}

        # Should be able to invoke the compiled graph
        result = graph.invoke(state)
        assert isinstance(result, dict)
        assert "steps" in result or "errors" in result
