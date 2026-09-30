"""Exhaustive bounded replay of DAGExecutor against the Lean operational model.

The seeded replay in ``test_dag_executor_lean_replay`` checks a few dozen
sampled schedules. This module replaces sampling with enumeration inside a size
bound: every acyclic dependency graph of at most ``MAX_STEPS`` steps, every
assignment of step outcomes, every ``max_concurrency`` from 1 to the step
count, and every legal sequence of ``asyncio.wait(FIRST_COMPLETED)`` batches.

The real ``DAGExecutor`` runs unchanged. A stand-in for ``asyncio`` inside
``dag_executor`` parks every step task at a gate and, at each wait, lets a
chooser release an ordered, nonempty subset of the parked steps: exactly the
batches ``Legal`` admits. Choice vectors are explored by re-execution, so each
schedule runs once. Lean answers all cases of a graph in one process, and its
operational model must equal what the executor did, step for step.

Bound: complete within ``ARP_LEAN_EXHAUSTIVE_MAX_STEPS`` steps (default 3, all
six outcome classes; above 3 only success, skipped, failed and exception).
Not covered: larger plans, duplicate dependency edges (the seeded replay has
them), timeouts, and cancellation at an await inside a batch.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from agentic_v2.contracts import StepResult, StepStatus
from agentic_v2.engine.context import ExecutionContext
from agentic_v2.engine.dag import DAG
from agentic_v2.engine.dag_executor import DAGExecutor
from agentic_v2.engine.step import StepDefinition, StepExecutor
from agentic_v2.engine.step_state import StepStateManager

ROOT = Path(__file__).resolve().parents[3]
MAX_STEPS = int(os.environ.get("ARP_LEAN_EXHAUSTIVE_MAX_STEPS", "3"))
FULL_OUTCOMES = ("success", "skipped", "failed", "pending", "exception", "cancelled")
CORE_OUTCOMES = ("success", "skipped", "failed", "exception")
FULL_OUTCOME_LIMIT = 3  # steps up to which every outcome class is enumerated
LEAN_CHUNK = 2000  # cases per Lean process call
SPIN_LIMIT = 1000  # loop turns a step may take to reach its gate
SKIP_CATEGORIES = {
    "conditions not met": "condition",
    "dependency failed": "upstream",
    "unhandled exception": "upstream",
    "workflow timeout": "timeout",
    "scheduler deadlock": "deadlock",
}
FINISHED_LEGALLY = {"complete": True, "legal": True}

Deps = list[list[int]]
Batches = list[list[int]]


def acyclic_graphs(size: int) -> Iterator[Deps]:
    """Every acyclic dependency relation on ``size`` labelled steps.

    ``deps[j]`` lists the steps ``j`` depends on; steps are added to the DAG in
    label order, so an edge may point forward, to a step added later.
    """
    pairs = [(a, b) for a in range(size) for b in range(size) if a != b]
    for mask in range(1 << len(pairs)):
        deps: Deps = [[] for _ in range(size)]
        for bit, (dependency, step) in enumerate(pairs):
            if mask >> bit & 1:
                deps[step].append(dependency)
        if _is_acyclic(deps):
            yield deps


def _is_acyclic(deps: Deps) -> bool:
    remaining = {step: set(ds) for step, ds in enumerate(deps)}
    while remaining:
        free = [step for step, ds in remaining.items() if not ds]
        if not free:
            return False
        for step in free:
            del remaining[step]
        for ds in remaining.values():
            ds.difference_update(free)
    return True


def outcome_classes(size: int) -> tuple[str, ...]:
    return FULL_OUTCOMES if size <= FULL_OUTCOME_LIMIT else CORE_OUTCOMES


def batch_options(parked: list[str]) -> list[list[str]]:
    """Every ordered, nonempty subset of the parked steps: the legal batches."""
    names = sorted(parked)
    return [
        list(picked)
        for size in range(1, len(names) + 1)
        for picked in itertools.permutations(names, size)
    ]


class Schedule:
    """One schedule: follow ``prefix``, then take the first option each time."""

    def __init__(self, prefix: list[int]) -> None:
        self.prefix = prefix
        self.taken: list[int] = []
        self.counts: list[int] = []

    def pick(self, options: list[list[str]]) -> list[str]:
        position = len(self.taken)
        choice = self.prefix[position] if position < len(self.prefix) else 0
        self.taken.append(choice)
        self.counts.append(len(options))
        return options[choice]

    def next_prefix(self) -> list[int] | None:
        """The next unexplored choice vector, or None when all are visited."""
        for position in reversed(range(len(self.taken))):
            if self.taken[position] + 1 < self.counts[position]:
                return [*self.taken[:position], self.taken[position] + 1]
        return None


class GatedRunner(StepExecutor):
    """Park every step at a gate; release it to return the scripted outcome."""

    def __init__(self, outcomes: tuple[str, ...]) -> None:
        super().__init__()
        self.outcomes = outcomes
        self.events: dict[str, asyncio.Event] = {}
        self.parked: set[str] = set()

    async def execute(
        self, step_def: StepDefinition, ctx: ExecutionContext
    ) -> StepResult:
        name = step_def.name
        self.events[name] = asyncio.Event()
        self.parked.add(name)
        await self.events[name].wait()
        outcome = self.outcomes[int(name)]
        if outcome == "exception":
            raise RuntimeError("scripted exception")
        if outcome == "cancelled":
            raise asyncio.CancelledError
        result = StepResult(step_name=name, status=StepStatus(outcome))
        if result.status == StepStatus.SKIPPED:
            result.metadata["skip_reason"] = "conditions not met"
        return result

    def release(self, name: str) -> None:
        self.parked.discard(name)
        self.events[name].set()


class ControlledAsyncio:
    """Stand-in for ``asyncio`` inside dag_executor that chooses each batch.

    Everything is forwarded to asyncio except ``create_task`` (records the
    start order) and ``wait``, which lets every in-flight step reach its gate,
    asks the schedule for a batch, releases those steps, and returns them as
    ``done`` in the chosen order. The executor iterates ``done`` as given.
    """

    def __init__(self, runner: GatedRunner, schedule: Schedule) -> None:
        self.runner = runner
        self.schedule = schedule
        self.created: list[str] = []
        self.batches: list[list[str]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(asyncio, name)

    def create_task(self, coro: Any, *, name: str | None = None) -> asyncio.Task[Any]:
        self.created.append(str(name))
        return asyncio.create_task(coro, name=name)

    async def wait(
        self, tasks: Any, *, return_when: str
    ) -> tuple[list[asyncio.Task[Any]], set[asyncio.Task[Any]]]:
        assert return_when == asyncio.FIRST_COMPLETED
        by_name = {task.get_name(): task for task in tasks}
        for _ in range(SPIN_LIMIT):
            if set(by_name) <= self.runner.parked:
                break
            await asyncio.sleep(0)
        else:
            raise AssertionError(f"steps never reached their gate: {sorted(by_name)}")
        chosen = self.schedule.pick(batch_options(list(by_name)))
        for name in chosen:
            self.runner.release(name)
        done = [by_name[name] for name in chosen]
        await asyncio.wait(done)
        self.batches.append(chosen)
        return done, set(tasks) - set(done)


async def run_trace(
    deps: Deps, outcomes: tuple[str, ...], limit: int, prefix: list[int]
) -> tuple[dict[str, Any], Batches, Schedule]:
    """Run the executor once under the schedule; return its end state."""
    dag = DAG(name="exhaustive")
    for index, step_deps in enumerate(deps):
        dag.add(StepDefinition(name=str(index), depends_on=[str(d) for d in step_deps]))
    runner = GatedRunner(outcomes)
    schedule = Schedule(prefix)
    stand_in = ControlledAsyncio(runner, schedule)
    manager = StepStateManager()
    ends: list[str] = []

    async def on_update(event: dict[str, Any]) -> None:
        if event["type"] == "step_end":
            ends.append(event["step"])

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("agentic_v2.engine.dag_executor.asyncio", stand_in)
        patch.setattr(
            "agentic_v2.engine.dag_executor.StepStateManager", lambda: manager
        )
        result = await DAGExecutor(step_executor=runner).execute(
            dag, ctx=ExecutionContext(), max_concurrency=limit, on_update=on_update
        )
    by_name = {step.step_name: step for step in result.steps}
    results: list[dict[str, str]] = []
    for index in range(len(deps)):
        step = by_name[str(index)]
        skip = "none"
        if step.status == StepStatus.SKIPPED:
            skip = SKIP_CATEGORIES[step.metadata["skip_reason"]]
        results.append({"status": step.status.value, "skip": skip})
    end_state = {
        "starts": [int(name) for name in stand_in.created],
        "ends": [int(name) for name in ends],
        "results": results,
        "life": [manager.get_state(str(i)).value for i in range(len(deps))],
        "overall": result.overall_status.value,
        "timed_out": bool(result.metadata.get("timeout_exceeded")),
        "deadlocked": str(result.metadata.get("error", "")).startswith(
            "Scheduler deadlock"
        ),
    }
    batches = [[int(name) for name in batch] for batch in stand_in.batches]
    return end_state, batches, schedule


async def explore(
    deps: Deps, outcomes: tuple[str, ...], limit: int
) -> list[tuple[dict[str, Any], Batches]]:
    """Run every legal schedule of one (graph, outcomes, limit) case."""
    traces: list[tuple[dict[str, Any], Batches]] = []
    prefix: list[int] | None = []
    while prefix is not None:
        end_state, batches, schedule = await run_trace(deps, outcomes, limit, prefix)
        traces.append((end_state, batches))
        prefix = schedule.next_prefix()
    return traces


def lean_answers(binary: Path, requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ask Lean for each request's answer, in chunks of one process call."""
    answers: list[dict[str, Any]] = []
    for start in range(0, len(requests), LEAN_CHUNK):
        process = subprocess.run(
            [str(binary)],
            input=json.dumps({"cases": requests[start : start + LEAN_CHUNK]}) + "\n",
            text=True,
            capture_output=True,
            timeout=120,
            check=True,
        )
        answers.extend(json.loads(process.stdout)["answers"])
    return answers


@pytest.fixture(autouse=True)
def quiet_executor_errors() -> Iterator[None]:
    """Scripted exceptions log a traceback per trace; tens of thousands add up."""
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


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


CASES = [
    pytest.param(deps, limit, id=f"n{size}-{index}-limit{limit}")
    for size in range(1, MAX_STEPS + 1)
    for index, deps in enumerate(acyclic_graphs(size))
    for limit in range(1, size + 1)
]


@pytest.mark.parametrize(("deps", "limit"), CASES)
async def test_executor_matches_lean_on_every_legal_schedule(
    lean_binary: Path, deps: Deps, limit: int
) -> None:
    """Every outcome assignment and legal batch sequence of one graph and limit.

    Start order, end events, results, lifecycle states and flags must
    equal the Lean operational model's, the batches must be legal and
    the run complete (so the Lean theorems apply to the trace), and the
    model must end in the recursive spec's results and overall status.
    """
    size = len(deps)
    cases: list[tuple[tuple[str, ...], dict[str, Any], Batches]] = []
    for outcomes in itertools.product(outcome_classes(size), repeat=size):
        for end_state, batches in await explore(deps, outcomes, limit):
            cases.append((outcomes, end_state, batches))
    requests = [
        {
            "plan": [
                {"depends_on": deps[i], "outcome": outcomes[i]} for i in range(size)
            ],
            "max_concurrency": limit,
            "batches": batches,
        }
        for outcomes, _, batches in cases
    ]
    answers = lean_answers(lean_binary, requests)
    assert len(answers) == len(cases)
    for (outcomes, end_state, batches), answer in zip(cases, answers, strict=True):
        label = (deps, limit, outcomes, batches)
        assert answer["model"] == {**end_state, **FINISHED_LEGALLY}, label
        assert answer["model"]["results"] == answer["steps"], label
        assert answer["model"]["overall"] == answer["overall"], label


def test_acyclic_graph_counts() -> None:
    """Labelled acyclic digraphs: 1, 3, 25, 543 for 1 to 4 steps."""
    assert [len(list(acyclic_graphs(size))) for size in (1, 2, 3, 4)] == [
        1,
        3,
        25,
        543,
    ]


@pytest.mark.parametrize(("limit", "expected"), [(1, 1), (2, 4)])
async def test_enumerator_visits_every_schedule_once(limit: int, expected: int) -> None:
    """Two independent steps: limit 1 starts them one after the other, so one
    schedule; limit 2 has four (two orders, two simultaneous batches). No Lean."""
    traces = await explore([[], []], ("success", "success"), limit)
    batches = [tuple(map(tuple, batches)) for _, batches in traces]
    assert len(batches) == len(set(batches)) == expected


async def test_enumerator_batches_are_legal_orderings() -> None:
    """With two steps running, every nonempty ordered subset is offered."""
    assert batch_options(["1", "0"]) == [["0"], ["1"], ["0", "1"], ["1", "0"]]
    traces = await explore([[], []], ("success", "success"), 2)
    assert sorted(tuple(map(tuple, batches)) for _, batches in traces) == [
        ((0,), (1,)),
        ((0, 1),),
        ((1,), (0,)),
        ((1, 0),),
    ]
