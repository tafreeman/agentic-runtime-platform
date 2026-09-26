"""Tests for DAG workflow execution."""

# ADR-008 cleanup: removed 3 duplicate tests (see docs/adr/ADR-008-testing-approach-overhaul.md)

import asyncio

import pytest

from agentic_v2.contracts import StepStatus
from agentic_v2.engine import (
    DAG,
    CycleDetectedError,
    DAGExecutor,
    ExecutionContext,
    MissingDependencyError,
    StepDefinition,
)


@pytest.mark.asyncio
async def test_simple_dag_execution():
    """DAG executes steps in dependency order."""

    async def step_a(ctx):
        await ctx.set("a", 1)
        return {"value": 1}

    async def step_b(ctx):
        a_val = await ctx.get("a")
        return {"sum": a_val + 1}

    dag = DAG("simple")
    dag.add(StepDefinition(name="a", func=step_a).with_output(value="a"))
    dag.add(
        StepDefinition(name="b", func=step_b).with_dependency("a").with_output(sum="b")
    )

    ctx = ExecutionContext()
    executor = DAGExecutor()
    result = await executor.execute(dag, ctx)

    assert result.overall_status == StepStatus.SUCCESS
    assert await ctx.get("b") == 2


@pytest.mark.asyncio
async def test_parallel_dag_execution_diamond():
    """Diamond pattern runs parallel steps and joins."""
    order = []
    lock = asyncio.Lock()

    async def step_1(ctx):
        async with lock:
            order.append("step1")
        return {}

    async def step_2(ctx):
        await asyncio.sleep(0.02)
        async with lock:
            order.append("step2")
        return {}

    async def step_3(ctx):
        await asyncio.sleep(0.01)
        async with lock:
            order.append("step3")
        return {}

    async def step_4(ctx):
        async with lock:
            order.append("step4")
        return {}

    dag = DAG("diamond")
    dag.add(StepDefinition(name="step1", func=step_1))
    dag.add(StepDefinition(name="step2", func=step_2).with_dependency("step1"))
    dag.add(StepDefinition(name="step3", func=step_3).with_dependency("step1"))
    dag.add(StepDefinition(name="step4", func=step_4).with_dependency("step2", "step3"))

    executor = DAGExecutor()
    result = await executor.execute(dag)

    assert result.overall_status == StepStatus.SUCCESS
    assert order[-1] == "step4"
    assert "step2" in order and "step3" in order


def test_cycle_detection():
    """Cycle detection raises error."""
    dag = DAG("cycle")
    dag.add(StepDefinition(name="a").with_dependency("b"))
    dag.add(StepDefinition(name="b").with_dependency("a"))

    with pytest.raises(CycleDetectedError):
        dag.validate()


def _long_chain(closing_dep: str | None = None) -> DAG:
    """Build steps ``s0`` to ``s4999``, each depending on the one before.

    The chain is five times Python's default recursion limit. With
    *closing_dep*, ``s1`` also depends on it.
    """
    dag = DAG("long-chain")
    dag.add(StepDefinition(name="s0"))
    for index in range(1, 5000):
        deps = [f"s{index - 1}"]
        if index == 1 and closing_dep is not None:
            deps.append(closing_dep)
        dag.add(StepDefinition(name=f"s{index}", depends_on=deps))
    return dag


def test_validate_accepts_a_chain_past_the_recursion_limit():
    """A dependency chain deeper than the Python stack validates."""
    _long_chain().validate()


def test_validate_reports_a_long_cycle_path():
    """A long chain closed into a cycle reports the whole cycle.

    The path starts at ``s1``, the step the back edge reaches, not at the DFS
    root ``s0``.
    """
    dag = _long_chain(closing_dep="s4999")

    with pytest.raises(CycleDetectedError) as caught:
        dag.validate()

    assert caught.value.cycle_path == [f"s{i}" for i in range(1, 5000)] + ["s1"]


def test_missing_dependency_error():
    """Missing dependency raises error."""
    dag = DAG("missing")
    dag.add(StepDefinition(name="a").with_dependency("missing"))

    with pytest.raises(MissingDependencyError):
        dag.validate()


@pytest.mark.asyncio
async def test_conditional_execution_in_dag():
    """Conditional step is skipped when condition is false."""

    async def step_ok(ctx):
        return {"value": 1}

    async def step_conditional(ctx):
        return {"value": 2}

    dag = DAG("conditional")
    dag.add(StepDefinition(name="base", func=step_ok))
    dag.add(
        StepDefinition(
            name="conditional",
            func=step_conditional,
            when=lambda ctx: False,
        ).with_dependency("base")
    )

    executor = DAGExecutor()
    result = await executor.execute(dag)

    step_status = {step.step_name: step.status for step in result.steps}
    assert step_status["conditional"] == StepStatus.SKIPPED
