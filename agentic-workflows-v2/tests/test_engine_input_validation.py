"""Regression tests: engine rejects degenerate timeout/concurrency/checkpoint input."""

import json
from pathlib import Path

import pytest

from agentic_v2.engine import ExecutionContext, StepDefinition
from agentic_v2.engine.pipeline import ParallelGroup


async def _noop(ctx: ExecutionContext) -> dict[str, int]:
    return {}


@pytest.mark.parametrize("bad", [0, 0.0, -1, -0.5])
def test_step_definition_rejects_non_positive_timeout(bad: float) -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        StepDefinition(name="s", func=_noop, timeout_seconds=bad)


@pytest.mark.parametrize("bad", [0, -3])
def test_with_timeout_rejects_non_positive_and_leaves_value_unchanged(
    bad: float,
) -> None:
    step_def = StepDefinition(name="s", func=_noop, timeout_seconds=5.0)
    with pytest.raises(ValueError, match="timeout_seconds"):
        step_def.with_timeout(bad)
    assert step_def.timeout_seconds == 5.0


def test_step_definition_accepts_none_and_positive_timeout() -> None:
    assert StepDefinition(name="a", func=_noop).timeout_seconds is None
    assert StepDefinition(name="b", func=_noop, timeout_seconds=0.1).timeout_seconds


@pytest.mark.parametrize("bad", [0, -1])
def test_parallel_group_rejects_non_positive_max_concurrency(bad: int) -> None:
    step_def = StepDefinition(name="s", func=_noop)
    with pytest.raises(ValueError, match="max_concurrency"):
        ParallelGroup(name="g", steps=[step_def], max_concurrency=bad)


def test_parallel_group_accepts_none_and_one() -> None:
    step_def = StepDefinition(name="s", func=_noop)
    assert ParallelGroup(name="g", steps=[step_def]).max_concurrency is None
    assert ParallelGroup(name="g", steps=[step_def], max_concurrency=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], "text", 3, None])
async def test_restore_checkpoint_rejects_non_object_json(
    tmp_path: Path, payload: object
) -> None:
    path = tmp_path / "ckpt.json"
    path.write_text(json.dumps(payload))
    ctx = ExecutionContext()
    before_run_id = ctx.run_id

    with pytest.raises(ValueError, match="expected a JSON object"):
        await ctx.restore_checkpoint(path)

    assert ctx.run_id == before_run_id
    assert ctx.completed_steps == []
