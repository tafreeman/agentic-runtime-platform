"""Replay deterministic adversaries against the independent Lean specification.

Build with ``cd proofs && lake build``. Opt in with ARP_LEAN_REPLAY=1.
Import errors are deliberately never converted into skips.
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
OUTCOMES = [status.value for status in StepStatus] + ["exception"]


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


def oracle(binary: Path, plan: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    """Obtain all expected statuses from Lean, without a Python copy of spec."""
    process = subprocess.run(
        [str(binary)],
        input=json.dumps({"plan": plan, "max_concurrency": limit}) + "\n",
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
        self.raised: set[int] = set()

    async def execute(
        self, step_def: StepDefinition, ctx: ExecutionContext
    ) -> StepResult:
        index = int(step_def.name)
        for _ in range(self.delays[index]):
            await asyncio.sleep(0)
        self.finished.add(index)
        outcome = self.plan[index]["outcome"]
        if outcome == "exception":
            self.raised.add(index)
            raise RuntimeError("scripted exception")
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

    async def on_update(event: dict[str, Any]) -> None:
        if event["type"] == "step_start":
            index = int(event["step"])
            assert index not in starts, "a step started twice"
            for dep in plan[index]["depends_on"]:
                assert dep in ends, "dependency did not emit step_end before start"
                # This is the actual weaker contract: nonterminal statuses also
                # unblock. Terminal-only assignments check theorem 1 exactly.
                assert plan[dep]["outcome"] not in {"failed", "exception"}
            starts.add(index)
            # Exceptions emit no step_end. Use runner evidence to close those
            # intervals explicitly, rather than claiming event-only coverage.
            active.difference_update(runner.raised)
            active.add(index)
            assert len(active) <= limit, "concurrency exceeded"
        elif event["type"] == "step_end":
            index = int(event["step"])
            assert index in starts and index not in ends
            ends.add(index)
            active.remove(index)

    result = await DAGExecutor(step_executor=runner).execute(
        dag, ctx=ExecutionContext(), max_concurrency=limit, on_update=on_update
    )
    assert starts == runner.finished
    assert starts - ends == runner.raised
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


@pytest.mark.parametrize("seed", range(32))
async def test_dag_executor_lean_seeded_replay(lean_binary: Path, seed: int) -> None:
    """Check randomized DAGs, duplicate edges, outcomes and completion orders."""
    rng = random.Random(seed)
    choices = ["success", "skipped", "failed", "exception"] if seed % 2 else OUTCOMES
    plan = []
    for index in range(rng.randint(2, 12)):
        deps = [d for d in range(index) if rng.random() < 0.3]
        if deps and rng.random() < 0.5:
            deps.append(rng.choice(deps))
        plan.append({"depends_on": deps, "outcome": rng.choice(choices)})
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


@pytest.mark.parametrize("outcome", ["pending", "running", "retrying", "exception"])
async def test_dag_executor_lean_lifecycle_counterexamples(
    lean_binary: Path, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    """Reproduce the result/lifecycle mismatch without changing engine code."""
    manager = StepStateManager()
    monkeypatch.setattr(
        "agentic_v2.engine.dag_executor.StepStateManager", lambda: manager
    )
    plan = [
        {"depends_on": [], "outcome": outcome},
        {"depends_on": [0], "outcome": "success"},
    ]
    actual = await run_case(plan, 1, [0, 0], [0, 1])
    assert actual == oracle(lean_binary, plan, 1)
    expected_life = StepState.RUNNING if outcome == "exception" else StepState.FAILED
    assert manager.get_state("0") == expected_life


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
