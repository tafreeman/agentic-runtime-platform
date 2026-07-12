"""Regression tests: ``ExecutionContext(variables=...)`` and the native adapter.

``server/execution.py`` (``_run_via_native_adapter``, line ~307) and
``cli/helpers.py`` construct ``ExecutionContext(variables=dict(...))``. The
dataclass stores variables in the private ``_variables`` field, so without the
``variables`` InitVar shim that kwarg raised
``TypeError: ExecutionContext.__init__() got an unexpected keyword argument
'variables'`` on every native ``POST /api/run`` request. The langchain adapter
(the production default) seeds variables by other means, so this path was
undertested — ``test_server_adapters`` even monkeypatches
``_run_via_native_adapter`` with a fake, so the real constructor + native
execution path was never exercised. These tests close that gap.
"""

from __future__ import annotations

import pytest

from agentic_v2.adapters import get_registry
from agentic_v2.contracts import StepStatus, WorkflowResult
from agentic_v2.engine.context import ExecutionContext
from agentic_v2.engine.dag import DAG
from agentic_v2.engine.step import StepDefinition


def test_execution_context_accepts_variables_kwarg() -> None:
    """``ExecutionContext(variables=...)`` seeds the variable store (root-cause
    guard)."""
    ctx = ExecutionContext(variables={"alpha": 1, "nested": {"k": "v"}})

    assert ctx.get_sync("alpha") == 1
    assert ctx.get_sync("nested") == {"k": "v"}
    # Omitting the kwarg leaves the store empty (no spurious seeding).
    assert ExecutionContext().get_sync("alpha", "missing") == "missing"


async def test_native_adapter_runs_workflow_with_seeded_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A workflow runs end-to-end through the native adapter with seeded inputs.

    Mirrors the production ``_run_via_native_adapter`` path:
    ``ctx = ExecutionContext(variables=dict(workflow_inputs))`` followed by
    ``engine.execute(dag, ctx)``. Before the fix this raised ``TypeError`` at
    construction; the step body also asserts the seeded input is visible, so a
    silently-unseeded store would fail the run rather than pass.
    """
    monkeypatch.setenv("AGENTIC_NO_LLM", "1")

    async def check_input(ctx: ExecutionContext) -> dict[str, object]:
        seen = ctx.get_sync("threshold")
        if seen != 7:
            raise AssertionError(f"seeded workflow input not visible to step: {seen!r}")
        return {"threshold_seen": seen}

    dag = DAG("native_variables_regression")
    dag.add(StepDefinition(name="check_input", func=check_input))

    ctx = ExecutionContext(variables={"threshold": 7})
    engine = get_registry().get_adapter("native")

    result = await engine.execute(dag, ctx)

    assert isinstance(result, WorkflowResult)
    assert result.overall_status == StepStatus.SUCCESS
    assert result.steps[0].step_name == "check_input"
    assert result.steps[0].status == StepStatus.SUCCESS
