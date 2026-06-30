"""Regression tests for C-01: ambient context/executor must be per-task.

``get_context``/``set_context`` and ``get_executor`` used to read and write
plain module-level globals. Inside an event loop every concurrent ``asyncio``
Task shares those globals, so two workflow runs racing in the same loop would
clobber each other's ambient context (and history) -- run A could observe run
B's variables, and the convenience ``execute``/``run`` helpers shared a single
mutable executor.

The fix backs both with ``contextvars.ContextVar``. A ContextVar is copied into
each Task at creation, so each run reads and writes its own isolated slot. These
tests drive two concurrent runs through ``asyncio.gather`` (which wraps each
coroutine in its own Task) and assert each sees only its own context -- under
the buggy globals they would see the other's.
"""

from __future__ import annotations

import asyncio

from agentic_v2.engine import (
    ExecutionContext,
    get_context,
    get_executor,
    reset_context,
    set_context,
)

_HANDOFF_TIMEOUT_S = 2.0
# Non-protected variable key (PROTECTED_VARIABLE_KEYS rejects run_id/workflow_id).
_MARKER_KEY = "marker"


class TestConcurrentContextIsolation:
    """Two concurrent tasks must each see only their own ambient context."""

    async def test_concurrent_runs_do_not_share_ambient_context(self) -> None:
        """Each gathered task's set_context/get_context stays private to it.

        A cross-task barrier forces interleaving: both tasks set their own
        context and then wait until *both* have set before reading back. With a
        shared module global the later setter would win for both readers; with a
        per-task ContextVar each reader still observes its own context.
        """
        both_set = asyncio.Barrier(2)

        async def run(run_label: str) -> tuple[str, str]:
            own_ctx = ExecutionContext()
            await own_ctx.set(_MARKER_KEY, run_label)
            set_context(own_ctx)

            # Sync so the other task has definitely also called set_context
            # before either of us reads it back. A shared global would already
            # be corrupted by this point.
            await both_set.wait()

            observed = get_context()
            return run_label, await observed.get(_MARKER_KEY)

        results = await asyncio.wait_for(
            asyncio.gather(run("run-a"), run("run-b")),
            timeout=_HANDOFF_TIMEOUT_S,
        )

        observed_by_run = dict(results)
        assert observed_by_run == {"run-a": "run-a", "run-b": "run-b"}

    async def test_merge_step_view_concurrent_keeps_every_entry(self) -> None:
        """Concurrent merge_step_view calls all survive — no torn update.

        The read-modify-write of the shared ``steps`` namespace is held under the
        context lock, so N steps merging concurrently each keep their entry. (The
        prior sync get/set path was already atomic under asyncio's single thread;
        this guards the invariant should an ``await`` ever be introduced into the
        critical section.)
        """
        ctx = ExecutionContext()
        n = 50
        await asyncio.gather(
            *(
                ctx.merge_step_view(
                    f"step_{i}", {"status": "success", "outputs": {"i": i}}
                )
                for i in range(n)
            )
        )

        steps = ctx.get_sync("steps")
        assert isinstance(steps, dict)
        assert len(steps) == n
        assert all(f"step_{i}" in steps for i in range(n))

    async def test_lazy_get_context_is_per_task(self) -> None:
        """Lazy get_context() in two tasks creates two distinct contexts."""
        ready = asyncio.Barrier(2)
        seen: dict[str, str] = {}

        async def run(run_label: str) -> None:
            # First touch lazily creates this task's own context.
            ctx = get_context()
            await ctx.set(_MARKER_KEY, run_label)
            await ready.wait()
            # The other task's lazy context must not have leaked in.
            seen[run_label] = await get_context().get(_MARKER_KEY)

        await asyncio.wait_for(
            asyncio.gather(run("alpha"), run("beta")),
            timeout=_HANDOFF_TIMEOUT_S,
        )
        assert seen == {"alpha": "alpha", "beta": "beta"}

    async def test_concurrent_get_executor_is_per_task(self) -> None:
        """get_executor() yields a distinct executor per concurrent task."""
        ready = asyncio.Barrier(2)
        executors: dict[str, int] = {}

        async def run(run_label: str) -> None:
            executor = get_executor()
            await ready.wait()
            executors[run_label] = id(executor)
            # Identity is stable within the task even after the barrier.
            assert get_executor() is executor

        await asyncio.wait_for(
            asyncio.gather(run("first"), run("second")),
            timeout=_HANDOFF_TIMEOUT_S,
        )
        assert executors["first"] != executors["second"]

    async def test_reset_in_one_task_does_not_affect_other(self) -> None:
        """reset_context() in a child Task is scoped to that Task only.

        ContextVar isolation happens at Task boundaries, so a sibling Task that
        resets its ambient context must not disturb the context the parent Task
        installed. (A plain ``await`` shares the parent's context by design, so
        the reset is deliberately driven through ``create_task``.)
        """
        keep = ExecutionContext()
        await keep.set(_MARKER_KEY, "keeper")
        set_context(keep)

        async def resetter() -> None:
            reset_context()
            # Fresh, empty context for this task only.
            assert await get_context().get(_MARKER_KEY) is None

        child = asyncio.create_task(resetter())
        await asyncio.wait_for(child, timeout=_HANDOFF_TIMEOUT_S)

        # The parent task's context survives the child task's reset.
        assert get_context() is keep
        assert await get_context().get(_MARKER_KEY) == "keeper"
