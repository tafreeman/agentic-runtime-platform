"""Regression tests for ctx handling across the LangChain execution path.

What this file protects:
- Adapter-level forwarding from `LangChainEngine` to `WorkflowRunner` for:
  - `execute(..., ctx=...) -> runner.run(..., ctx=...)`
  - `stream(..., ctx=...)  -> runner.astream(..., ctx=...)`
- Runner-level merge behavior that injects `ctx.all_variables()` into the
  LangGraph `state["context"]` for both `run()` and `astream()`.
- `ctx=None` behavior for all code paths, ensuring null context does not
  raise `TypeError` and still returns expected outputs/events.

Design notes:
- Tests are intentionally split into adapter forwarding and runner state merge
  groups to isolate regressions quickly.
- The runner tests patch config loading/graph compilation/input validation so
  they can assert only state construction and context merge semantics.
- `asyncio_mode = "auto"` is configured in `pyproject.toml`, so async tests do
  not need explicit `@pytest.mark.asyncio` decorators.

How to run this file only:
`pytest tests/test_langchain_engine_ctx.py -q`
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from agentic_v2.adapters.langchain.engine import LangChainEngine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_runner() -> MagicMock:
    """Return a MagicMock that quacks like WorkflowRunner."""
    runner = MagicMock()
    # run() is a coroutine
    runner.run = AsyncMock(return_value=MagicMock(name="WorkflowResult"))

    # astream() is an async generator; yield one event to exercise stream flows.
    async def _astream(*args: Any, **kwargs: Any):
        yield {"event": "test"}

    runner.astream = _astream
    return runner


def _make_ctx(variables: dict | None = None) -> MagicMock:
    """Return a mock ExecutionContext with all_variables() returning *variables*."""
    ctx = MagicMock()
    # Tests only rely on all_variables(), so a lightweight MagicMock is enough.
    ctx.all_variables.return_value = variables or {"key": "value"}
    return ctx


# ---------------------------------------------------------------------------
# execute() — ctx forwarded to runner.run()
# ---------------------------------------------------------------------------


async def test_execute_forwards_ctx_to_runner_run() -> None:
    """Ctx supplied to execute() must be passed as ctx= to runner.run()."""
    runner = _make_mock_runner()
    engine = LangChainEngine(runner=runner)
    ctx = _make_ctx({"user_id": "abc"})

    await engine.execute("code_review", ctx=ctx)

    runner.run.assert_awaited_once()
    _args, kwargs = runner.run.call_args
    assert (
        kwargs.get("ctx") is ctx
    ), "runner.run() was not called with the ctx that was passed to execute()"


async def test_execute_ctx_none_does_not_raise() -> None:
    """Ctx=None must not cause a TypeError in execute()."""
    runner = _make_mock_runner()
    engine = LangChainEngine(runner=runner)

    # Should complete without any exception
    await engine.execute("code_review", ctx=None)

    runner.run.assert_awaited_once()
    _args, kwargs = runner.run.call_args
    assert kwargs.get("ctx") is None


async def test_execute_forwards_extra_kwargs_alongside_ctx() -> None:
    """Extra **kwargs must reach runner.run() unchanged alongside ctx."""
    runner = _make_mock_runner()
    engine = LangChainEngine(runner=runner)
    ctx = _make_ctx()

    await engine.execute("code_review", ctx=ctx, use_cache=False, thread_id="t1")

    _args, kwargs = runner.run.call_args
    assert kwargs.get("ctx") is ctx
    assert kwargs.get("use_cache") is False
    assert kwargs.get("thread_id") == "t1"


# ---------------------------------------------------------------------------
# stream() — ctx forwarded to runner.astream()
# ---------------------------------------------------------------------------


async def test_stream_forwards_ctx_to_runner_astream() -> None:
    """Ctx supplied to stream() must be passed as ctx= to runner.astream()."""
    received: dict = {}

    async def _astream(workflow_name: str, *, ctx: Any = None, **kwargs: Any):
        received["ctx"] = ctx
        received["workflow_name"] = workflow_name
        yield {"event": "ok"}

    runner = MagicMock()
    runner.astream = _astream
    engine = LangChainEngine(runner=runner)
    ctx = _make_ctx({"session": "xyz"})

    events = [e async for e in engine.stream("code_review", ctx=ctx)]

    assert (
        received.get("ctx") is ctx
    ), "runner.astream() was not called with the ctx that was passed to stream()"
    assert received.get("workflow_name") == "code_review"
    assert events == [{"event": "ok"}]


async def test_stream_ctx_none_does_not_raise() -> None:
    """Ctx=None must not cause a TypeError in stream()."""
    received: dict = {}

    async def _astream(workflow_name: str, *, ctx: Any = None, **kwargs: Any):
        received["ctx"] = ctx
        yield {"event": "ok"}

    runner = MagicMock()
    runner.astream = _astream
    engine = LangChainEngine(runner=runner)

    events = [e async for e in engine.stream("code_review", ctx=None)]

    assert received.get("ctx") is None
    assert events == [{"event": "ok"}]


async def test_stream_forwards_extra_kwargs_alongside_ctx() -> None:
    """Extra **kwargs must reach runner.astream() unchanged alongside ctx."""
    received: dict = {}

    async def _astream(workflow_name: str, *, ctx: Any = None, **kwargs: Any):
        received.update(kwargs)
        received["ctx"] = ctx
        yield {}

    runner = MagicMock()
    runner.astream = _astream
    engine = LangChainEngine(runner=runner)
    ctx = _make_ctx()

    async for _ in engine.stream("code_review", ctx=ctx, use_cache=False):
        pass

    assert received.get("ctx") is ctx
    assert received.get("use_cache") is False


# ---------------------------------------------------------------------------
# WorkflowRunner.run() — ctx merged into LangGraph state
# ---------------------------------------------------------------------------


async def test_runner_run_merges_ctx_variables_into_state() -> None:
    """WorkflowRunner.run() must merge ctx vars into state['context']."""
    from agentic_v2.langchain.runner import WorkflowRunner

    ctx = _make_ctx({"tenant_id": "tenant-alpha", "env": "prod"})

    # Capture the initial LangGraph state to inspect context merge behavior.
    captured_state: dict = {}

    async def _fake_ainvoke(state: dict, **kwargs: Any) -> dict:
        captured_state.update(state)
        return {
            "steps": {},
            "errors": [],
            "context": state.get("context", {}),
            "inputs": {},
            "outputs": {},
            "messages": [],
            "current_step": "",
        }

    mock_graph = MagicMock()
    mock_graph.ainvoke = _fake_ainvoke

    runner = WorkflowRunner()

    # Patch external dependencies so this test focuses only on run() state setup.
    with (
        patch("agentic_v2.langchain.runner.load_workflow_config") as mock_load_cfg,
        patch(
            "agentic_v2.langchain.runner.WorkflowRunner._get_or_compile",
            return_value=mock_graph,
        ),
        patch(
            "agentic_v2.langchain.runner.WorkflowRunner._validate_inputs",
            return_value={"input_key": "input_val"},
        ),
    ):
        mock_cfg = MagicMock()
        mock_cfg.name = "code_review"
        mock_cfg.inputs = {}
        mock_cfg.outputs = {}
        mock_load_cfg.return_value = mock_cfg

        await runner.run("code_review", ctx=ctx)

    state_ctx = captured_state.get("context", {})
    assert (
        state_ctx.get("tenant_id") == "tenant-alpha"
    ), "ctx variable 'tenant_id' was not merged into LangGraph state['context']"
    assert (
        state_ctx.get("env") == "prod"
    ), "ctx variable 'env' was not merged into LangGraph state['context']"
    # Workflow-level keys must not be overwritten by ctx
    assert state_ctx.get("inputs") == {"input_key": "input_val"}
    assert "workflow_run_id" in state_ctx


async def test_runner_run_syncs_final_context_updates_back_to_ctx() -> None:
    """WorkflowRunner.run() syncs safe final state['context'] updates to ctx."""
    from agentic_v2.engine.context import ExecutionContext
    from agentic_v2.langchain.runner import WorkflowRunner

    ctx = ExecutionContext(workflow_id="caller-workflow", run_id="caller-run")
    ctx.set_sync("tenant_id", "before")

    async def _fake_ainvoke(state: dict, **kwargs: Any) -> dict:
        final_context = dict(state.get("context", {}))
        final_context.update({"tenant_id": "after", "node_value": 42})
        return {
            "steps": {},
            "errors": [],
            "context": final_context,
            "inputs": {},
            "outputs": {},
            "messages": [],
            "current_step": "",
        }

    mock_graph = MagicMock()
    mock_graph.ainvoke = _fake_ainvoke
    runner = WorkflowRunner()

    with (
        patch("agentic_v2.langchain.runner.load_workflow_config") as mock_load_cfg,
        patch(
            "agentic_v2.langchain.runner.WorkflowRunner._get_or_compile",
            return_value=mock_graph,
        ),
        patch(
            "agentic_v2.langchain.runner.WorkflowRunner._validate_inputs",
            return_value={},
        ),
    ):
        mock_cfg = MagicMock()
        mock_cfg.name = "code_review"
        mock_cfg.inputs = {}
        mock_cfg.outputs = {}
        mock_load_cfg.return_value = mock_cfg

        await runner.run("code_review", ctx=ctx)

    assert ctx.get_sync("tenant_id") == "after"
    assert ctx.get_sync("node_value") == 42


async def test_runner_run_sync_skips_reserved_and_protected_context_keys() -> None:
    """Final context sync must not overwrite workflow or caller identity keys."""
    from agentic_v2.engine.context import ExecutionContext
    from agentic_v2.langchain.runner import WorkflowRunner

    ctx = ExecutionContext(workflow_id="caller-workflow", run_id="caller-run")
    ctx.set_sync("inputs", {"caller": "inputs"})
    ctx.set_sync("workflow_run_id", "caller-workflow-run")

    async def _fake_ainvoke(state: dict, **kwargs: Any) -> dict:
        final_context = dict(state.get("context", {}))
        final_context.update(
            {
                "inputs": {"node": "inputs"},
                "workflow_run_id": "node-workflow-run",
                "workflow_id": "node-workflow",
                "run_id": "node-run",
                "safe_result": "synced",
            }
        )
        return {
            "steps": {},
            "errors": [],
            "context": final_context,
            "inputs": {},
            "outputs": {},
            "messages": [],
            "current_step": "",
        }

    mock_graph = MagicMock()
    mock_graph.ainvoke = _fake_ainvoke
    runner = WorkflowRunner()

    with (
        patch("agentic_v2.langchain.runner.load_workflow_config") as mock_load_cfg,
        patch(
            "agentic_v2.langchain.runner.WorkflowRunner._get_or_compile",
            return_value=mock_graph,
        ),
        patch(
            "agentic_v2.langchain.runner.WorkflowRunner._validate_inputs",
            return_value={"input_key": "input_val"},
        ),
    ):
        mock_cfg = MagicMock()
        mock_cfg.name = "code_review"
        mock_cfg.inputs = {}
        mock_cfg.outputs = {}
        mock_load_cfg.return_value = mock_cfg

        await runner.run("code_review", ctx=ctx)

    assert ctx.workflow_id == "caller-workflow"
    assert ctx.run_id == "caller-run"
    assert ctx.get_sync("inputs") == {"caller": "inputs"}
    assert ctx.get_sync("workflow_run_id") == "caller-workflow-run"
    assert ctx.get_sync("workflow_id") is None
    assert ctx.get_sync("run_id") is None
    assert ctx.get_sync("safe_result") == "synced"


async def test_runner_run_ctx_none_no_error() -> None:
    """WorkflowRunner.run() with ctx=None must proceed without error."""
    from agentic_v2.langchain.runner import WorkflowRunner

    async def _fake_ainvoke(state: dict, **kwargs: Any) -> dict:
        return {
            "steps": {},
            "errors": [],
            "context": state.get("context", {}),
            "inputs": {},
            "outputs": {},
            "messages": [],
            "current_step": "",
        }

    mock_graph = MagicMock()
    mock_graph.ainvoke = _fake_ainvoke
    runner = WorkflowRunner()

    # Keep run() deterministic while verifying ctx=None is accepted.
    with (
        patch("agentic_v2.langchain.runner.load_workflow_config") as mock_load_cfg,
        patch(
            "agentic_v2.langchain.runner.WorkflowRunner._get_or_compile",
            return_value=mock_graph,
        ),
        patch(
            "agentic_v2.langchain.runner.WorkflowRunner._validate_inputs",
            return_value={},
        ),
    ):
        mock_cfg = MagicMock()
        mock_cfg.name = "code_review"
        mock_cfg.inputs = {}
        mock_cfg.outputs = {}
        mock_load_cfg.return_value = mock_cfg

        result = await runner.run("code_review", ctx=None)

    # A result should be returned regardless
    assert result is not None


# ---------------------------------------------------------------------------
# WorkflowRunner.astream() — ctx merged into LangGraph state
# ---------------------------------------------------------------------------


async def test_runner_astream_merges_ctx_variables_into_state() -> None:
    """WorkflowRunner.astream() must merge ctx vars into state['context']."""
    from agentic_v2.langchain.runner import WorkflowRunner

    ctx = _make_ctx({"request_id": "req-999"})

    # Capture the initial LangGraph state to inspect context merge behavior.
    captured_state: dict = {}

    async def _fake_astream(state: dict, **kwargs: Any):
        captured_state.update(state)
        yield {"node": "step1", "data": {}}

    mock_graph = MagicMock()
    mock_graph.astream = _fake_astream

    runner = WorkflowRunner()

    # Patch external dependencies so this test focuses on astream() state setup.
    with (
        patch("agentic_v2.langchain.runner.load_workflow_config") as mock_load_cfg,
        patch(
            "agentic_v2.langchain.runner.WorkflowRunner._get_or_compile",
            return_value=mock_graph,
        ),
        patch(
            "agentic_v2.langchain.runner.WorkflowRunner._validate_inputs",
            return_value={},
        ),
    ):
        mock_cfg = MagicMock()
        mock_cfg.name = "code_review"
        mock_cfg.inputs = {}
        mock_cfg.outputs = {}
        mock_load_cfg.return_value = mock_cfg

        events = [e async for e in runner.astream("code_review", ctx=ctx)]

    state_ctx = captured_state.get("context", {})
    assert state_ctx.get("request_id") == "req-999", (
        "ctx variable 'request_id' was not merged into LangGraph state['context'] "
        "during astream()"
    )
    assert events == [{"node": "step1", "data": {}}]


async def test_runner_astream_does_not_sync_context_without_final_state() -> None:
    """Astream() documents no ctx write-back because final state is unavailable."""
    from agentic_v2.engine.context import ExecutionContext
    from agentic_v2.langchain.runner import WorkflowRunner

    ctx = ExecutionContext()

    async def _fake_astream(state: dict, **kwargs: Any):
        event_context = dict(state.get("context", {}))
        event_context["stream_only"] = "event-value"
        yield {"context": event_context}

    mock_graph = MagicMock()
    mock_graph.astream = _fake_astream
    runner = WorkflowRunner()

    with (
        patch("agentic_v2.langchain.runner.load_workflow_config") as mock_load_cfg,
        patch(
            "agentic_v2.langchain.runner.WorkflowRunner._get_or_compile",
            return_value=mock_graph,
        ),
        patch(
            "agentic_v2.langchain.runner.WorkflowRunner._validate_inputs",
            return_value={},
        ),
    ):
        mock_cfg = MagicMock()
        mock_cfg.name = "code_review"
        mock_cfg.inputs = {}
        mock_cfg.outputs = {}
        mock_load_cfg.return_value = mock_cfg

        events = [e async for e in runner.astream("code_review", ctx=ctx)]

    assert len(events) == 1
    event_ctx = events[0]["context"]
    assert event_ctx["inputs"] == {}
    assert event_ctx["stream_only"] == "event-value"
    assert "workflow_run_id" in event_ctx
    assert ctx.get_sync("stream_only") is None


async def test_runner_astream_ctx_none_no_error() -> None:
    """WorkflowRunner.astream() with ctx=None must proceed without error."""
    from agentic_v2.langchain.runner import WorkflowRunner

    async def _fake_astream(state: dict, **kwargs: Any):
        yield {"event": "done"}

    mock_graph = MagicMock()
    mock_graph.astream = _fake_astream
    runner = WorkflowRunner()

    # Keep astream() deterministic while verifying ctx=None is accepted.
    with (
        patch("agentic_v2.langchain.runner.load_workflow_config") as mock_load_cfg,
        patch(
            "agentic_v2.langchain.runner.WorkflowRunner._get_or_compile",
            return_value=mock_graph,
        ),
        patch(
            "agentic_v2.langchain.runner.WorkflowRunner._validate_inputs",
            return_value={},
        ),
    ):
        mock_cfg = MagicMock()
        mock_cfg.name = "code_review"
        mock_cfg.inputs = {}
        mock_cfg.outputs = {}
        mock_load_cfg.return_value = mock_cfg

        events = [e async for e in runner.astream("code_review", ctx=None)]

    assert events == [{"event": "done"}]
