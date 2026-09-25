"""Replay deterministic adversaries against the Lean model of DAGExecutor.

Two comparisons: final results against the independent recursive spec, and
each recorded completion order against the operational scheduling loop
(ADR-060 section 3). Build with ``cd proofs && lake build``. Tests that need
the compiled model skip unless ARP_LEAN_REPLAY=1. The executor defect regression tests need no Lean and
run in every suite. Import errors are deliberately never converted into skips.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import subprocess
from pathlib import Path
from typing import Any

import pytest

from agentic_v2.contracts import StepResult, StepStatus
from agentic_v2.engine.context import ExecutionContext
from agentic_v2.engine.dag import DAG
from agentic_v2.engine.dag_executor import DAGExecutor
from agentic_v2.engine.step import StepDefinition, StepExecutor
from agentic_v2.engine.step_state import StepState, StepStateManager

ROOT = Path(__file__).resolve().parents[3]
OUTCOMES = [status.value for status in StepStatus] + ["exception", "cancelled"]
TERMINAL = ["success", "skipped", "failed", "exception", "cancelled"]
SKIP_CATEGORIES = {
    "conditions not met": "condition",
    "dependency failed": "upstream",
    "unhandled exception": "upstream",
    "workflow timeout": "timeout",
    "scheduler deadlock": "deadlock",
}
# Every replayed run finishes, and its recorded batches satisfy the Lean
# theorems' hypothesis: each consumed batch is a nonempty, duplicate-free set of
# running steps (``checkLegal``). The theorems then cover the recorded trace.
FINISHED_LEGALLY = {"complete": True, "legal": True}


@pytest.fixture
def lean_binary() -> Path:
    """Require the executable when replay is explicitly requested."""
    if os.environ.get("ARP_LEAN_REPLAY") != "1":
        pytest.skip("set ARP_LEAN_REPLAY=1 to run the Lean differential replay")
    binary = ROOT / "proofs" / ".lake" / "build" / "bin" / "replay"
    if os.name == "nt":
        binary = binary.with_suffix(".exe")
    assert binary.is_file(), f"Lean replay binary missing: {binary}; run lake build"
    return binary


def oracle(
    binary: Path, plan: list[dict[str, Any]], limit: int, **trace: Any
) -> dict[str, Any]:
    """Ask Lean for the expected outcome; no Python copy of the model exists.

    With ``batches`` (and ``timeout``) in *trace*, the answer also carries
    the operational model's run under that completion order as ``model``.
    """
    request = {"plan": plan, "max_concurrency": limit, **trace}
    process = subprocess.run(
        [str(binary)],
        input=json.dumps(request) + "\n",
        text=True,
        capture_output=True,
        timeout=30,
        check=True,
    )
    return json.loads(process.stdout)


class ScriptedRunner(StepExecutor):
    """Return assigned outcomes after deterministic cooperative yields."""

    def __init__(self, plan: list[dict[str, Any]], delays: list[int]) -> None:
        super().__init__()
        self.plan = plan
        self.delays = delays
        self.finished: set[int] = set()

    async def execute(
        self, step_def: StepDefinition, ctx: ExecutionContext
    ) -> StepResult:
        index = int(step_def.name)
        for _ in range(self.delays[index]):
            await asyncio.sleep(0)
        outcome = self.plan[index]["outcome"]
        if outcome == "hang":
            await asyncio.Event().wait()
        self.finished.add(index)
        if outcome == "exception":
            raise RuntimeError("scripted exception")
        if outcome == "cancelled":
            raise asyncio.CancelledError
        result = StepResult(step_name=step_def.name, status=StepStatus(outcome))
        if result.status == StepStatus.SKIPPED:
            result.metadata["skip_reason"] = "conditions not met"
        return result


async def run_case(
    plan: list[dict[str, Any]], limit: int, delays: list[int], order: list[int]
) -> dict[str, Any]:
    """Run the actual executor; verify starts, dependencies and capacity."""
    dag = DAG(name="lean-replay")
    for index in order:
        dag.add(
            StepDefinition(
                name=str(index), depends_on=[str(d) for d in plan[index]["depends_on"]]
            )
        )
    runner = ScriptedRunner(plan, delays)
    starts: set[int] = set()
    ends: set[int] = set()
    active: set[int] = set()
    violations: list[str] = []

    def check(event: dict[str, Any]) -> None:
        if event["type"] == "step_start":
            index = int(event["step"])
            assert index not in starts, "a step started twice"
            for dep in plan[index]["depends_on"]:
                assert dep in ends, "dependency did not emit step_end before start"
                # ADR-060 safety: only a SUCCESS or SKIPPED dependency unblocks.
                assert plan[dep]["outcome"] in {"success", "skipped"}
            starts.add(index)
            active.add(index)
            assert len(active) <= limit, "concurrency exceeded"
        elif event["type"] == "step_end":
            index = int(event["step"])
            assert index in starts and index not in ends
            ends.add(index)
            active.remove(index)

    async def on_update(event: dict[str, Any]) -> None:
        # The executor logs and swallows observer exceptions, so record each
        # violation and assert on the list after the run.
        try:
            check(event)
        except AssertionError as error:
            violations.append(f"{event['type']} {event.get('step')}: {error}")

    result = await DAGExecutor(step_executor=runner).execute(
        dag, ctx=ExecutionContext(), max_concurrency=limit, on_update=on_update
    )
    assert not violations, violations
    assert "observer_errors" not in result.metadata
    assert starts == runner.finished
    # Every started step, raised or not, emits exactly one step_end.
    assert starts == ends
    steps = {}
    for step in result.steps:
        category = "none"
        if step.status == StepStatus.SKIPPED:
            reason = step.metadata.get("skip_reason")
            if reason == "conditions not met":
                category = "condition"
            else:
                assert reason in {"dependency failed", "unhandled exception"}
                category = "upstream"
        steps[int(step.step_name)] = {"status": step.status.value, "skip": category}
    assert set(steps) == set(range(len(plan)))
    return {
        "steps": [steps[i] for i in range(len(plan))],
        "overall": result.overall_status.value,
    }


def random_plan(rng: random.Random, choices: list[str]) -> list[dict[str, Any]]:
    """Draw 2 to 12 steps with random edges, some duplicated, and outcomes."""
    plan = []
    for index in range(rng.randint(2, 12)):
        deps = [d for d in range(index) if rng.random() < 0.3]
        if deps and rng.random() < 0.5:
            deps.append(rng.choice(deps))
        plan.append({"depends_on": deps, "outcome": rng.choice(choices)})
    return plan


@pytest.mark.parametrize("seed", range(32))
async def test_dag_executor_lean_seeded_replay(lean_binary: Path, seed: int) -> None:
    """Check randomized DAGs, duplicate edges, outcomes and completion orders."""
    rng = random.Random(seed)
    plan = random_plan(rng, TERMINAL if seed % 2 else OUTCOMES)
    for limit in (1, 2, len(plan) + 3):
        expected = oracle(lean_binary, plan, limit)
        for _ in range(3):
            order = list(range(len(plan)))
            rng.shuffle(order)
            delays = [rng.randrange(8) for _ in plan]
            actual = await run_case(plan, limit, delays, order)
            assert actual == expected, (seed, limit, delays, order)


async def test_dag_executor_lean_failure_propagation(lean_binary: Path) -> None:
    """A mandatory failure chain makes the requested mutation detectable."""
    plan = [
        {"depends_on": [], "outcome": "failed"},
        {"depends_on": [0, 0], "outcome": "success"},
        {"depends_on": [1], "outcome": "success"},
    ]
    assert await run_case(plan, 2, [0, 0, 0], [0, 1, 2]) == oracle(lean_binary, plan, 2)


@pytest.mark.parametrize("outcome", ["pending", "running", "retrying"])
async def test_dag_executor_nonterminal_outcome_fails_closed(
    monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    """A step that ends nonterminal must fail and skip its dependents."""
    manager = StepStateManager()
    monkeypatch.setattr(
        "agentic_v2.engine.dag_executor.StepStateManager", lambda: manager
    )
    plan = [
        {"depends_on": [], "outcome": outcome},
        {"depends_on": [0], "outcome": "success"},
    ]
    assert await run_case(plan, 1, [0, 0], [0, 1]) == {
        "steps": [
            {"status": "failed", "skip": "none"},
            {"status": "skipped", "skip": "upstream"},
        ],
        "overall": "failed",
    }
    assert manager.get_state("0") == StepState.FAILED


async def test_dag_executor_nonterminal_result_records_why() -> None:
    """The FAILED copy names the original status and keeps the step's error.

    The context agrees: the step is failed, and a completion the executor
    recorded before returning the non-terminal status is dropped.
    """
    plan = [{"depends_on": [], "outcome": "retrying"}]

    class ErroredRunner(ScriptedRunner):
        async def execute(
            self, step_def: StepDefinition, ctx: ExecutionContext
        ) -> StepResult:
            result = await super().execute(step_def, ctx)
            await ctx.mark_step_complete(step_def.name)
            result.error = "rate limited"
            return result

    dag = DAG(name="nonterminal-why").add(StepDefinition(name="0"))
    ctx = ExecutionContext()
    result = await DAGExecutor(step_executor=ErroredRunner(plan, [0])).execute(
        dag, ctx=ctx
    )
    [step] = result.steps
    assert step.status == StepStatus.FAILED
    assert (
        step.error == "step finished with non-terminal status 'retrying': rate limited"
    )
    assert step.error_type == "NonTerminalStatus"
    assert step.metadata["nonterminal_status"] == "retrying"
    assert step.end_time is not None
    assert ctx.is_step_failed("0")
    assert not ctx.is_step_complete("0")


async def test_dag_executor_exception_ends_step_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A step that raises must end FAILED in its lifecycle and in a step_end event."""
    manager = StepStateManager()
    monkeypatch.setattr(
        "agentic_v2.engine.dag_executor.StepStateManager", lambda: manager
    )
    events: list[dict[str, Any]] = []

    async def on_update(event: dict[str, Any]) -> None:
        events.append(event)

    plan = [{"depends_on": [], "outcome": "exception"}]
    dag = DAG(name="exception-lifecycle").add(StepDefinition(name="0"))
    result = await DAGExecutor(step_executor=ScriptedRunner(plan, [0])).execute(
        dag, ctx=ExecutionContext(), on_update=on_update
    )
    assert result.overall_status == StepStatus.FAILED
    assert manager.get_state("0") == StepState.FAILED
    step_ends = [e for e in events if e["type"] == "step_end" and e["step"] == "0"]
    assert [e["status"] for e in step_ends] == ["failed"]


@pytest.mark.parametrize("outcome", ["success", "exception"])
async def test_dag_executor_timeout_during_step_end_keeps_bookkeeping(
    monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    """A timeout that interrupts the step_end callback finds the step recorded.

    Timeout recovery skips completed steps, so the lifecycle, result and
    propagation must all happen before the callback is awaited.
    """
    manager = StepStateManager()
    monkeypatch.setattr(
        "agentic_v2.engine.dag_executor.StepStateManager", lambda: manager
    )

    async def on_update(event: dict[str, Any]) -> None:
        if event["type"] == "step_end":
            await asyncio.sleep(5)

    plan = [
        {"depends_on": [], "outcome": outcome},
        {"depends_on": [0], "outcome": "success"},
    ]
    dag = DAG(name="timeout-in-callback")
    dag.add(StepDefinition(name="0")).add(StepDefinition(name="1", depends_on=["0"]))
    result = await DAGExecutor(step_executor=ScriptedRunner(plan, [0, 0])).execute(
        dag, ctx=ExecutionContext(), on_update=on_update, timeout=0.2
    )
    assert result.metadata["timeout_exceeded"]
    finished = StepState.SUCCESS if outcome == "success" else StepState.FAILED
    assert manager.get_state("0") == finished
    assert manager.get_state("1") == StepState.SKIPPED
    assert [step.status for step in result.steps][1] == StepStatus.SKIPPED


@pytest.mark.parametrize("limit", [-1, 0])
async def test_dag_executor_lean_rejects_nonpositive_limit(
    lean_binary: Path, limit: int
) -> None:
    """The current main rejects the historical counterexample at its API."""
    plan = [{"depends_on": [], "outcome": "success"}]
    with pytest.raises(subprocess.CalledProcessError):
        oracle(lean_binary, plan, limit)
    dag = DAG(name="zero-limit").add(StepDefinition(name="0"))
    with pytest.raises(ValueError, match="max_concurrency"):
        await DAGExecutor(step_executor=ScriptedRunner(plan, [0])).execute(
            dag, ctx=ExecutionContext(), max_concurrency=limit
        )


async def test_dag_executor_cancelled_step_fails_without_escaping() -> None:
    """A step task that ends cancelled is a failed step; the run still returns."""
    plan = [
        {"depends_on": [], "outcome": "cancelled"},
        {"depends_on": [0], "outcome": "success"},
        {"depends_on": [], "outcome": "success"},
    ]
    dag = DAG(name="cancelled-step")
    for index, node in enumerate(plan):
        dag.add(
            StepDefinition(
                name=str(index), depends_on=[str(d) for d in node["depends_on"]]
            )
        )
    result = await DAGExecutor(step_executor=ScriptedRunner(plan, [0, 0, 4])).execute(
        dag, ctx=ExecutionContext()
    )
    by_name = {step.step_name: step for step in result.steps}
    assert result.overall_status == StepStatus.FAILED
    assert by_name["0"].status == StepStatus.FAILED
    assert by_name["0"].error_type == "CancelledError"
    assert by_name["1"].status == StepStatus.SKIPPED
    assert by_name["2"].status == StepStatus.SUCCESS


async def test_dag_executor_cancel_cancels_running_steps() -> None:
    """Cancelling execute() cancels and awaits its step tasks, then propagates."""
    started = asyncio.Event()
    cancelled: set[str] = set()

    class BlockingRunner(StepExecutor):
        async def execute(
            self, step_def: StepDefinition, ctx: ExecutionContext
        ) -> StepResult:
            if step_def.name == "b":
                started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.add(step_def.name)
                raise
            raise AssertionError("unreachable")

    dag = DAG(name="outer-cancel")
    dag.add(StepDefinition(name="a")).add(StepDefinition(name="b"))
    run = asyncio.create_task(
        DAGExecutor(step_executor=BlockingRunner()).execute(dag, ctx=ExecutionContext())
    )
    await started.wait()
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    assert cancelled == {"a", "b"}


@pytest.mark.parametrize(
    "event_type", ["workflow_start", "step_start", "step_end", "workflow_end"]
)
async def test_dag_executor_observer_failure_does_not_change_the_run(
    event_type: str,
) -> None:
    """An on_update exception is logged and counted; scheduling carries on."""
    plan = [
        {"depends_on": [], "outcome": "success"},
        {"depends_on": [0], "outcome": "success"},
        {"depends_on": [], "outcome": "success"},
    ]
    # Step 2 is still running when step 0's step_end fires.
    runner = ScriptedRunner(plan, [0, 0, 6])
    seen: list[str] = []

    async def on_update(event: dict[str, Any]) -> None:
        seen.append(event["type"])
        if event["type"] == event_type:
            raise RuntimeError(f"observer failed on {event_type}")

    dag = DAG(name="observer-failure")
    for index, node in enumerate(plan):
        dag.add(
            StepDefinition(
                name=str(index), depends_on=[str(d) for d in node["depends_on"]]
            )
        )
    result = await DAGExecutor(step_executor=runner).execute(
        dag, ctx=ExecutionContext(), on_update=on_update
    )
    assert result.overall_status == StepStatus.SUCCESS
    assert [step.status for step in result.steps] == [StepStatus.SUCCESS] * 3
    assert runner.finished == {0, 1, 2}
    once = event_type in {"workflow_start", "workflow_end"}
    assert result.metadata["observer_errors"] == (1 if once else 3)
    assert seen.count("step_end") == 3
    assert seen[-1] == "workflow_end"


def _masking_observer() -> tuple[Any, asyncio.Event]:
    """Observer that blocks on the first step_end and masks its cancellation."""
    blocked = asyncio.Event()

    async def on_update(event: dict[str, Any]) -> None:
        if event["type"] != "step_end" or blocked.is_set():
            return
        blocked.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise OSError("observer cleanup failed") from None

    return on_update, blocked


def _chain_dag(name: str) -> DAG:
    dag = DAG(name=name)
    dag.add(StepDefinition(name="0")).add(StepDefinition(name="1", depends_on=["0"]))
    return dag


async def test_dag_executor_timeout_survives_an_observer_masking_it() -> None:
    """A timeout that an observer turns into another exception still ends the run."""
    plan = [
        {"depends_on": [], "outcome": "success"},
        {"depends_on": [0], "outcome": "success"},
    ]
    runner = ScriptedRunner(plan, [0, 0])
    on_update, _ = _masking_observer()
    result = await DAGExecutor(step_executor=runner).execute(
        _chain_dag("observer-masks-timeout"),
        ctx=ExecutionContext(),
        on_update=on_update,
        timeout=0.2,
    )
    by_name = {step.step_name: step for step in result.steps}
    assert result.metadata["timeout_exceeded"] is True
    assert result.overall_status == StepStatus.FAILED
    assert by_name["1"].status == StepStatus.SKIPPED
    assert runner.finished == {0}
    assert "observer_errors" not in result.metadata


async def test_dag_executor_cancel_survives_an_observer_masking_it() -> None:
    """Caller cancellation that an observer turns into another exception propagates."""
    plan = [
        {"depends_on": [], "outcome": "success"},
        {"depends_on": [0], "outcome": "success"},
    ]
    runner = ScriptedRunner(plan, [0, 0])
    on_update, blocked = _masking_observer()
    run = asyncio.create_task(
        DAGExecutor(step_executor=runner).execute(
            _chain_dag("observer-masks-cancel"),
            ctx=ExecutionContext(),
            on_update=on_update,
        )
    )
    await blocked.wait()
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    assert runner.finished == {0}


async def test_dag_executor_pending_cancel_survives_an_observer_masking_it() -> None:
    """A cancel requested before execute(), delivered inside the observer.

    The request is already in ``Task.cancelling()`` when the observer is
    entered, so the count does not rise; the masking exception's context is
    what shows the cancel was swallowed.
    """
    plan = [
        {"depends_on": [], "outcome": "success"},
        {"depends_on": [0], "outcome": "success"},
    ]
    runner = ScriptedRunner(plan, [0, 0])

    async def on_update(event: dict[str, Any]) -> None:
        if event["type"] != "workflow_start":
            return
        try:
            await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise OSError("observer cleanup failed") from None

    async def caller() -> Any:
        task = asyncio.current_task()
        assert task is not None
        task.cancel()
        return await DAGExecutor(step_executor=runner).execute(
            _chain_dag("observer-masks-pending-cancel"),
            ctx=ExecutionContext(),
            on_update=on_update,
        )

    with pytest.raises(asyncio.CancelledError):
        await asyncio.create_task(caller())
    assert runner.finished == set()


async def test_dag_executor_stale_cancel_count_keeps_observer_errors() -> None:
    """A cancel the caller swallowed earlier does not turn observer errors into one.

    Catching ``CancelledError`` without ``uncancel()`` leaves
    ``Task.cancelling()`` nonzero for the rest of the task. Only a cancel
    requested while the observer was awaiting may be re-raised.
    """
    plan = [
        {"depends_on": [], "outcome": "success"},
        {"depends_on": [0], "outcome": "success"},
    ]
    runner = ScriptedRunner(plan, [0, 0])

    async def on_update(event: dict[str, Any]) -> None:
        if event["type"] == "step_end":
            raise RuntimeError("observer failed")

    async def caller() -> Any:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass  # swallowed without uncancel(): cancelling() stays at 1
        task = asyncio.current_task()
        assert task is not None and task.cancelling() == 1
        return await DAGExecutor(step_executor=runner).execute(
            _chain_dag("stale-cancel-count"),
            ctx=ExecutionContext(),
            on_update=on_update,
        )

    run = asyncio.create_task(caller())
    await asyncio.sleep(0)
    run.cancel()
    result = await run
    assert result.overall_status == StepStatus.SUCCESS
    assert runner.finished == {0, 1}
    assert result.metadata["observer_errors"] == 2


class RecordingAsyncio:
    """Stand-in for ``asyncio`` inside dag_executor that records its schedule.

    Everything is forwarded to asyncio. ``create_task`` records each step as
    it is started, and ``wait`` records each FIRST_COMPLETED batch in the order
    the executor processes it: the executor iterates the same unmodified set.
    """

    def __init__(self) -> None:
        self.created: list[str] = []
        self.batches: list[list[str]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(asyncio, name)

    def create_task(self, coro: Any, *, name: str | None = None) -> asyncio.Task[Any]:
        self.created.append(str(name))
        return asyncio.create_task(coro, name=name)

    async def wait(self, tasks: Any, **kwargs: Any) -> tuple[set[Any], set[Any]]:
        done, pending = await asyncio.wait(tasks, **kwargs)
        self.batches.append([task.get_name() for task in done])
        return done, pending


async def run_traced(
    plan: list[dict[str, Any]],
    limit: int,
    delays: list[int],
    order: list[int],
    timeout: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[list[int]]]:
    """Run the executor and return its plan, end state and batches, relabelled.

    The model's ready queue and adjacency follow plan order and Python's
    follow ``DAG.add`` order, so node k of the returned plan is the k-th step
    added. Under that relabelling the model can predict the exact start order.
    """
    position = {index: k for k, index in enumerate(order)}
    relabelled = [
        {
            "depends_on": [position[d] for d in plan[index]["depends_on"]],
            "outcome": plan[index]["outcome"],
        }
        for index in order
    ]
    dag = DAG(name="lean-trace")
    for index in order:
        dag.add(
            StepDefinition(
                name=str(index), depends_on=[str(d) for d in plan[index]["depends_on"]]
            )
        )
    recorder = RecordingAsyncio()
    manager = StepStateManager()
    ends: list[str] = []

    async def on_update(event: dict[str, Any]) -> None:
        if event["type"] == "step_end":
            ends.append(event["step"])

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("agentic_v2.engine.dag_executor.asyncio", recorder)
        patch.setattr(
            "agentic_v2.engine.dag_executor.StepStateManager", lambda: manager
        )
        result = await DAGExecutor(step_executor=ScriptedRunner(plan, delays)).execute(
            dag,
            ctx=ExecutionContext(),
            max_concurrency=limit,
            on_update=on_update,
            timeout=timeout,
        )

    def at(names: list[str]) -> list[int]:
        return [position[int(name)] for name in names]

    by_name = {step.step_name: step for step in result.steps}
    results: list[dict[str, str] | None] = []
    for index in order:
        step = by_name.get(str(index))
        if step is None:
            results.append(None)
            continue
        skip = "none"
        if step.status == StepStatus.SKIPPED:
            skip = SKIP_CATEGORIES[step.metadata["skip_reason"]]
        results.append({"status": step.status.value, "skip": skip})
    end_state = {
        "starts": at(recorder.created),
        "ends": at(ends),
        "results": results,
        "life": [manager.get_state(str(index)).value for index in order],
        "overall": result.overall_status.value,
        "timed_out": bool(result.metadata.get("timeout_exceeded")),
        "deadlocked": str(result.metadata.get("error", "")).startswith(
            "Scheduler deadlock"
        ),
    }
    return relabelled, end_state, [at(batch) for batch in recorder.batches]


@pytest.mark.parametrize("seed", range(32))
async def test_dag_executor_matches_operational_model(
    lean_binary: Path, seed: int
) -> None:
    """Replay each recorded completion order through the Lean scheduling loop.

    Start order, end events, results, lifecycle states and flags must
    all be the model's, and the recorded batches must be legal, so the
    Lean theorems apply to the trace. On it the model must also end in
    the recursive spec's results and overall status, which
    ``legal_run_matches_spec`` proves for every legal trace of a
    validated plan that finishes every step: the ``legal`` and
    ``complete`` flags asserted here are its premises.
    """
    rng = random.Random(seed)
    plan = random_plan(rng, TERMINAL if seed % 2 else OUTCOMES)
    for limit in (1, 2, len(plan) + 3):
        for _ in range(2):
            order = list(range(len(plan)))
            rng.shuffle(order)
            delays = [rng.randrange(8) for _ in plan]
            relabelled, end_state, batches = await run_traced(
                plan, limit, delays, order
            )
            answer = oracle(lean_binary, relabelled, limit, batches=batches)
            case = (seed, limit, delays, order, batches)
            assert answer["model"] == {**end_state, **FINISHED_LEGALLY}, case
            assert answer["model"]["results"] == answer["steps"], case
            assert answer["model"]["overall"] == answer["overall"], case


@pytest.mark.parametrize("seed", range(8))
async def test_dag_executor_timeout_matches_operational_model(
    lean_binary: Path, seed: int
) -> None:
    """A workflow timeout lands at the same scheduling boundary in the model.

    The first step never completes, so every run times out. The timeout
    can only interrupt the executor at its FIRST_COMPLETED wait, which
    follows a scheduling pass, and that is where the model applies it.
    """
    rng = random.Random(seed)
    plan = random_plan(rng, TERMINAL)
    plan[0]["outcome"] = "hang"
    for limit in (1, len(plan) + 3):
        order = list(range(len(plan)))
        rng.shuffle(order)
        delays = [rng.randrange(8) for _ in plan]
        relabelled, end_state, batches = await run_traced(
            plan, limit, delays, order, timeout=0.2
        )
        assert end_state["timed_out"]
        answer = oracle(lean_binary, relabelled, limit, batches=batches, timeout=True)
        case = (seed, limit, delays, order, batches)
        assert answer["model"] == {**end_state, **FINISHED_LEGALLY}, case


@pytest.mark.parametrize(
    ("batches", "legal"),
    [([[0], [1]], True), ([[1]], False), ([[0, 0]], False), ([[], [0]], False)],
    ids=["legal", "not-running", "duplicate", "empty"],
)
def test_lean_replay_checks_batch_legality(
    lean_binary: Path, batches: list[list[int]], legal: bool
) -> None:
    """``legal`` rejects batches that no FIRST_COMPLETED wait could return."""
    plan = [
        {"depends_on": [], "outcome": "success"},
        {"depends_on": [0], "outcome": "success"},
    ]
    answer = oracle(lean_binary, plan, 1, batches=batches)
    assert answer["model"]["legal"] is legal


@pytest.mark.parametrize(
    "trace",
    [{}, {"batches": [], "timeout": False}, {"batches": [[0]], "timeout": True}],
    ids=["no-batches", "not-a-timeout", "hang-in-a-batch"],
)
def test_lean_replay_rejects_hang_that_could_complete(
    lean_binary: Path, trace: dict[str, Any]
) -> None:
    """``hang`` never completes, so no answer may treat it as a completion."""
    plan = [{"depends_on": [], "outcome": "hang"}]
    with pytest.raises(subprocess.CalledProcessError):
        oracle(lean_binary, plan, 1, **trace)


def test_lean_replay_reports_only_the_model_for_a_hanging_plan(
    lean_binary: Path,
) -> None:
    """The spec assumes every step completes, so it is omitted for ``hang``."""
    plan = [
        {"depends_on": [], "outcome": "hang"},
        {"depends_on": [0], "outcome": "success"},
    ]
    answer = oracle(lean_binary, plan, 1, batches=[], timeout=True)
    assert "steps" not in answer
    assert "overall" not in answer
    assert answer["model"]["timed_out"] is True
    assert answer["model"]["results"] == [
        {"status": "failed", "skip": "none"},
        {"status": "skipped", "skip": "timeout"},
    ]
