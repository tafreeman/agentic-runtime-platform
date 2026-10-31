"""SLO smoke test: concurrent workflow executions must not deadlock or crash.

Sprint exit criterion: this test must be green on CI.
Uses AGENTIC_NO_LLM=1 so no provider credentials are required.
"""

from __future__ import annotations

import asyncio

import pytest
from agentic_v2.contracts import StepStatus
from agentic_v2.engine import StepExecutor
from agentic_v2.workflows.runner import WorkflowRunner


@pytest.mark.slow
async def test_concurrent_workflow_runs_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three concurrent executions of test_deterministic must all succeed.

    Each run is given its own StepExecutor so WorkflowRunner builds a
    fresh DAGExecutor per call rather than pulling the shared singleton
    adapter from the AdapterRegistry (which is not safe for concurrent
    use — its internal StepStateManager is reset at the start of each
    _run_dag call but is still a single instance-level attribute,
    creating a race).
    """
    monkeypatch.setenv("AGENTIC_NO_LLM", "1")

    async def _run_once(run_index: int) -> StepStatus:
        # Passing step_executor causes WorkflowRunner._execute_definition to
        # construct a brand-new DAGExecutor rather than using the cached
        # singleton adapter — safe for concurrent execution.
        runner = WorkflowRunner(step_executor=StepExecutor())
        result = await runner.run(
            "test_deterministic",
            input_text=f"smoke-run-{run_index}",
        )
        return result.overall_status

    statuses = await asyncio.gather(
        _run_once(0),
        _run_once(1),
        _run_once(2),
    )

    assert all(
        s == StepStatus.SUCCESS for s in statuses
    ), f"Expected all SUCCESS, got: {statuses}"
