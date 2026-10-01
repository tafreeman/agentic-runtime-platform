"""Pin the orchestrator's scheduler to the DAGExecutor rules that ADR-060 proves.

``OrchestratorAgent._execute_plan`` is a second scheduler that the Lean model
does not cover (``proofs/README.md``: "not modelled"). ADR-060 part 1 aligned
its rules with ``DAGExecutor`` in code; this module keeps them aligned on
generated plans, and records the one place they deliberately differ.

Scheduling is isolated from agent behaviour: ``_execute_subtask_with_fallback``
is replaced by a scripted step that succeeds or fails after a few loop turns,
so fallback chains and escalation handoffs stay out of scope.

Compared on every generated plan and concurrency limit:

* each step's final status, so the same steps succeed, fail and are skipped;
* each skipped step's reason, through ``REASON_MAP``; a reason on either side
  that the table does not cover fails the test;
* the set of steps that ran;
* safety on each side's own trace: a step starts only after all of its
  dependencies ended, and no more than ``max_parallel`` steps run at once.

Not compared, because it differs by design: start/end ordering. The
orchestrator runs ready steps in ``gather()`` waves and starts nothing until
the whole wave ends; ``DAGExecutor`` starts a dependent as soon as any step
ends. ``test_wave_barrier_ordering_divergence_is_pinned`` fixes the smallest
case, which becomes the acceptance oracle if the orchestrator moves onto
``DAGExecutor``.

The orchestrator reuses ``DAG.validate``, so its verdict is checked against the
real ``DAG.validate`` and, when ``ARP_LEAN_REPLAY=1``, against the Lean model,
so that the two Python sides cannot agree on a shared bug.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agentic_v2.agents.orchestrator import OrchestratorAgent, OrchestratorInput
from agentic_v2.agents.orchestrator_models import SubTask
from agentic_v2.contracts import StepResult, StepStatus
from agentic_v2.engine.context import ExecutionContext
from agentic_v2.engine.dag import DAG, CycleDetectedError, MissingDependencyError
from agentic_v2.engine.dag_executor import DAGExecutor
from agentic_v2.engine.step import StepDefinition, StepExecutor

ROOT = Path(__file__).resolve().parents[2]
MAX_STEPS = 7
MAX_DELAY = 4  # event-loop turns a scripted step takes

# Executor skip reason -> the orchestrator's reason for the same situation. A
# plan of FAILED/SUCCESS steps only ever skips a step because a dependency
# failed; any other reason on either side means the rules have drifted.
REASON_MAP = {"dependency failed": "dependency failed"}

Deps = list[list[int]]
Trace = list[tuple[str, str]]
Outcome = dict[str, Any]
Plan = tuple[Deps, list[str], list[int], int]


@st.composite
def plans(draw: st.DrawFn) -> Plan:
    """A plan: backward dependency edges (some repeated), outcomes, delays, limit."""
    size = draw(st.integers(min_value=1, max_value=MAX_STEPS))
    deps: Deps = []
    for index in range(size):
        picked: list[int] = []
        if index:
            picked = draw(st.lists(st.integers(0, index - 1), max_size=3))
        deps.append(picked)
    outcomes = draw(
        st.lists(st.sampled_from(["success", "failed"]), min_size=size, max_size=size)
    )
    delays = draw(st.lists(st.integers(0, MAX_DELAY), min_size=size, max_size=size))
    limit = draw(st.integers(min_value=1, max_value=size + 1))
    return deps, outcomes, delays, limit


def _safety_violations(deps: Deps, limit: int, trace: Trace) -> list[str]:
    """Check one side's trace: dependencies ended before a start, limit held."""
    problems: list[str] = []
    ended: set[str] = set()
    running: set[str] = set()
    for kind, name in trace:
        if kind == "start":
            if not all(str(d) in ended for d in deps[int(name)]):
                problems.append(f"{name} started before its dependencies ended")
            running.add(name)
            if len(running) > limit:
                problems.append(f"more than {limit} steps running at {name}")
        else:
            running.discard(name)
            ended.add(name)
    return problems


def _orchestrator_with(deps: Deps) -> OrchestratorAgent:
    orch = OrchestratorAgent()
    for index, step_deps in enumerate(deps):
        orch._subtasks[str(index)] = SubTask(
            id=str(index),
            description=f"step {index}",
            required_capabilities=[],
            dependencies=[str(d) for d in step_deps],
        )
    return orch


async def run_orchestrator(
    deps: Deps, outcomes: list[str], delays: list[int], limit: int
) -> tuple[dict[str, Outcome], Trace]:
    """Run ``_execute_plan`` on a plan with scripted subtasks."""
    orch = _orchestrator_with(deps)
    trace: Trace = []

    async def scripted(subtask: SubTask) -> tuple[str, Any]:
        index = int(subtask.id)
        trace.append(("start", subtask.id))
        for _ in range(delays[index]):
            await asyncio.sleep(0)
        ok = outcomes[index] == "success"
        subtask.status = StepStatus.SUCCESS if ok else StepStatus.FAILED
        trace.append(("end", subtask.id))
        return subtask.id, ({"output": "ok"} if ok else {"error": "scripted failure"})

    orch._execute_subtask_with_fallback = scripted  # type: ignore[method-assign]
    results = await orch._execute_plan(OrchestratorInput(task="t", max_parallel=limit))
    final: dict[str, Outcome] = {}
    for index in range(len(deps)):
        subtask = orch._subtasks[str(index)]
        reason = None
        if subtask.status == StepStatus.SKIPPED:
            reason = results[str(index)]["reason"]
        final[str(index)] = {"status": subtask.status.value, "reason": reason}
    return final, trace


class ScriptedRunner(StepExecutor):
    """Succeed or fail after a few loop turns."""

    def __init__(self, outcomes: list[str], delays: list[int]) -> None:
        super().__init__()
        self.outcomes = outcomes
        self.delays = delays

    async def execute(
        self, step_def: StepDefinition, ctx: ExecutionContext
    ) -> StepResult:
        index = int(step_def.name)
        for _ in range(self.delays[index]):
            await asyncio.sleep(0)
        return StepResult(
            step_name=step_def.name, status=StepStatus(self.outcomes[index])
        )


async def run_executor(
    deps: Deps, outcomes: list[str], delays: list[int], limit: int
) -> tuple[dict[str, Outcome], Trace]:
    """Run ``DAGExecutor`` on the same plan."""
    dag = DAG(name="differential")
    for index, step_deps in enumerate(deps):
        dag.add(StepDefinition(name=str(index), depends_on=[str(d) for d in step_deps]))
    trace: Trace = []

    async def on_update(event: dict[str, Any]) -> None:
        if event["type"] == "step_start":
            trace.append(("start", event["step"]))
        elif event["type"] == "step_end" and event["status"] != "skipped":
            trace.append(("end", event["step"]))

    runner = ScriptedRunner(outcomes, delays)
    result = await DAGExecutor(step_executor=runner).execute(
        dag, ctx=ExecutionContext(), max_concurrency=limit, on_update=on_update
    )
    final: dict[str, Outcome] = {}
    for step in result.steps:
        reason = None
        if step.status == StepStatus.SKIPPED:
            reason = REASON_MAP[step.metadata["skip_reason"]]
        final[step.step_name] = {"status": step.status.value, "reason": reason}
    return final, trace


@settings(max_examples=300, deadline=None, derandomize=True)
@given(plan=plans())
async def test_orchestrator_and_executor_agree_on_every_plan(plan: Plan) -> None:
    """Same statuses, skip reasons, steps run, and safe traces on both sides."""
    deps, outcomes, delays, limit = plan
    orchestrated, orch_trace = await run_orchestrator(deps, outcomes, delays, limit)
    executed, exec_trace = await run_executor(deps, outcomes, delays, limit)

    assert orchestrated == executed, plan
    ran = {name for kind, name in orch_trace if kind == "start"}
    assert ran == {name for kind, name in exec_trace if kind == "start"}, plan
    assert ran == {n for n, o in orchestrated.items() if o["status"] != "skipped"}
    assert not _safety_violations(deps, limit, orch_trace), (plan, orch_trace)
    assert not _safety_violations(deps, limit, exec_trace), (plan, exec_trace)


async def test_wave_barrier_ordering_divergence_is_pinned() -> None:
    """The orchestrator waits for a whole wave; the executor does not.

    ``c`` depends on ``a``. ``a`` ends first, so ``DAGExecutor`` starts ``c``
    while ``b`` still runs; the orchestrator starts nothing until ``b`` ends
    as well. Only the relative order of ``b``'s end and ``c``'s start is pinned. Both orders are correct (neither breaks a dependency), but they
    are not the same schedule. When the orchestrator moves onto
    ``DAGExecutor`` this test is expected to change, which makes the move a
    behaviour change to review, not a refactor.
    """
    deps: Deps = [[], [], [0]]
    outcomes = ["success", "success", "success"]
    delays = [1, 3, 0]
    _, orch_trace = await run_orchestrator(deps, outcomes, delays, 2)
    _, exec_trace = await run_executor(deps, outcomes, delays, 2)

    assert orch_trace.index(("end", "1")) < orch_trace.index(("start", "2"))
    assert exec_trace.index(("start", "2")) < exec_trace.index(("end", "1"))
    assert not _safety_violations(deps, 2, orch_trace)
    assert not _safety_violations(deps, 2, exec_trace)


@st.composite
def graphs(draw: st.DrawFn) -> Deps:
    """1 to 6 steps; edges may point forward, to the step itself or to a missing one."""
    size = draw(st.integers(min_value=1, max_value=6))
    return [draw(st.lists(st.integers(0, size), max_size=3)) for _ in range(size)]


def _verdict(validate: Callable[[], None]) -> dict[str, Any]:
    try:
        validate()
    except MissingDependencyError as error:
        return {
            "verdict": "missing",
            "step": int(error.step),
            "dependency": int(error.missing_dep),
        }
    except CycleDetectedError as error:
        return {"verdict": "cycle", "path": [int(name) for name in error.cycle_path]}
    return {"verdict": "ok"}


def _dag_verdict(deps: Deps) -> dict[str, Any]:
    dag = DAG(name="validate")
    for index, step_deps in enumerate(deps):
        dag.add(StepDefinition(name=str(index), depends_on=[str(d) for d in step_deps]))
    return _verdict(dag.validate)


@settings(max_examples=300, deadline=None, derandomize=True)
@given(deps=graphs())
def test_orchestrator_validation_is_dag_validate(deps: Deps) -> None:
    """The orchestrator refuses exactly what ``DAG.validate`` refuses, with the same
    cycle path and the same missing pair."""
    verdict = _verdict(_orchestrator_with(deps)._validate_plan)
    assert verdict == _dag_verdict(deps), deps


def test_empty_plan_is_not_validated_by_design() -> None:
    """``DAG.validate`` calls an empty plan an error; the orchestrator has nothing to
    run and nothing to validate, so it accepts it."""
    assert _verdict(_orchestrator_with([])._validate_plan) == {"verdict": "ok"}
    with pytest.raises(ValueError, match="no steps"):
        DAG(name="empty").validate()


def test_orchestrator_validation_matches_the_lean_model() -> None:
    """Both Python sides must also match Lean's ``validate`` on every verdict path, so
    they cannot agree with each other on a shared bug."""
    if os.environ.get("ARP_LEAN_REPLAY") != "1":
        pytest.skip("set ARP_LEAN_REPLAY=1 to cross-check against the Lean model")
    binary = ROOT / "proofs" / ".lake" / "build" / "bin" / "replay"
    if os.name == "nt":
        binary = binary.with_suffix(".exe")
    assert binary.is_file(), f"Lean replay binary missing: {binary}; run lake build"
    cases: list[Deps] = [
        [[]],
        [[], [0, 0], [1, 0]],
        [[0]],
        [[2], [0], [1]],
        [[], [2]],
        [[1], [0], [3]],
        [[1], [], [0, 3]],
    ]
    process = subprocess.run(
        [str(binary)],
        input=json.dumps({"validate": cases}) + "\n",
        text=True,
        capture_output=True,
        timeout=30,
        check=True,
    )
    lean = json.loads(process.stdout)["verdicts"]
    assert [_verdict(_orchestrator_with(deps)._validate_plan) for deps in cases] == lean
    assert {verdict["verdict"] for verdict in lean} == {"ok", "missing", "cycle"}
