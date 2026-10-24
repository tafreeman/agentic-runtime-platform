"""StepExecutor must not conflate same-named steps from concurrent runs."""

from __future__ import annotations

import asyncio
from typing import Any

from agentic_v2.contracts import StepStatus
from agentic_v2.engine.context import ExecutionContext
from agentic_v2.engine.step import StepDefinition, StepExecutor


def _blocking_step(started: asyncio.Event, release: asyncio.Event) -> StepDefinition:
    async def _fn(ctx: ExecutionContext) -> dict[str, Any]:
        started.set()
        await release.wait()
        return {"ok": True}

    return StepDefinition(name="shared_name", func=_fn)


async def test_cancel_all_scoped_to_run_leaves_other_runs_alone() -> None:
    executor = StepExecutor()
    ctx_a, ctx_b = ExecutionContext(), ExecutionContext()
    started_a, started_b = asyncio.Event(), asyncio.Event()
    release = asyncio.Event()

    task_a = asyncio.create_task(
        executor.execute(_blocking_step(started_a, release), ctx_a)
    )
    task_b = asyncio.create_task(
        executor.execute(_blocking_step(started_b, release), ctx_b)
    )
    await asyncio.wait_for(
        asyncio.gather(started_a.wait(), started_b.wait()), timeout=5
    )
    assert len(executor._running_tasks) == 2  # same name, distinct runs

    assert await executor.cancel_all(run_id=ctx_a.run_id) == 1

    release.set()
    result_a, result_b = await asyncio.gather(task_a, task_b)
    assert result_a.status == StepStatus.FAILED
    assert result_b.status == StepStatus.SUCCESS
    assert executor._running_tasks == {}


async def test_cancel_by_name_without_run_id_hits_every_run() -> None:
    executor = StepExecutor()
    ctxs = [ExecutionContext(), ExecutionContext()]
    events = [asyncio.Event(), asyncio.Event()]
    release = asyncio.Event()
    tasks = [
        asyncio.create_task(executor.execute(_blocking_step(e, release), c))
        for e, c in zip(events, ctxs, strict=True)
    ]
    await asyncio.wait_for(asyncio.gather(*(e.wait() for e in events)), timeout=5)

    assert await executor.cancel("shared_name") is True
    results = await asyncio.gather(*tasks)
    assert all(r.status == StepStatus.FAILED for r in results)
