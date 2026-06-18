"""Regression tests for C-03: lock-inversion deadlock in ExecutionContext.get.

``ExecutionContext.get`` used to ``await self._parent.get(...)`` while still
holding ``self._lock``. That held the child lock across the acquisition of the
parent lock, so two tasks descending opposite ends of the parent/child chain
could deadlock (classic lock inversion). It also let a concurrent writer on the
child block behind an unrelated parent read.

``update`` had a related TOCTOU: it validated keys outside the lock and wrote
inside, so a concurrent writer could mutate state between the check and the
commit.

These tests use ``asyncio.wait_for`` with a short timeout as the assertion: the
buggy implementation hangs and the wrapped future raises ``TimeoutError``.
"""

from __future__ import annotations

import asyncio

import pytest

from agentic_v2.engine import ExecutionContext

_DEADLOCK_TIMEOUT_S = 2.0


class TestGetDeadlock:
    """Get() must not hold its own lock while descending to the parent."""

    async def test_concurrent_parent_child_get_does_not_hang(self) -> None:
        """Two tasks reading opposite ends of the chain both complete."""
        parent = ExecutionContext()
        await parent.set("shared", "from_parent")
        child = parent.child()
        await child.set("local", "from_child")

        async def read_from_child() -> object:
            # Misses locally for "shared" -> must descend to the parent.
            return await child.get("shared")

        async def read_from_parent() -> object:
            return await parent.get("shared")

        # Hammer the inversion-prone path from both directions concurrently.
        results = await asyncio.wait_for(
            asyncio.gather(
                *(read_from_child() for _ in range(25)),
                *(read_from_parent() for _ in range(25)),
            ),
            timeout=_DEADLOCK_TIMEOUT_S,
        )
        assert all(value == "from_parent" for value in results)

    async def test_child_lock_released_before_descending_to_parent(self) -> None:
        """Get() must drop its own lock before calling into the parent.

        This is the precise root cause of the inversion: the buggy code held
        ``child._lock`` across ``await self._parent.get(...)``, so a task holding
        the parent lock could not also take the child lock (and vice versa). We
        pause the parent read mid-descent and assert the child's own lock is
        acquirable — under the buggy code this acquisition hangs and the
        ``wait_for`` raises ``TimeoutError``.
        """
        parent = ExecutionContext()
        child = parent.child()

        parent_entered = asyncio.Event()
        let_parent_finish = asyncio.Event()

        async def slow_parent_get(key: str, default: object = None) -> object:
            parent_entered.set()
            await let_parent_finish.wait()
            return "parent_value"

        # Instance-level override so only the parent's read is paused.
        parent.get = slow_parent_get  # type: ignore[method-assign]

        # "missing" is absent locally on the child, forcing a parent descent.
        descent = asyncio.create_task(child.get("missing"))
        try:
            await asyncio.wait_for(parent_entered.wait(), timeout=_DEADLOCK_TIMEOUT_S)

            # While the parent read is parked, the child's lock must be free.
            await asyncio.wait_for(child._lock.acquire(), timeout=_DEADLOCK_TIMEOUT_S)
            child._lock.release()
        finally:
            let_parent_finish.set()
            assert await descent == "parent_value"

    async def test_missing_key_returns_default_through_parent(self) -> None:
        """Default still propagates to the parent when the key is absent."""
        parent = ExecutionContext()
        child = parent.child()
        assert await child.get("nope", "fallback") == "fallback"


class TestUpdateAtomicValidation:
    """Update() validates and writes atomically (no TOCTOU window)."""

    async def test_update_rejects_protected_key_without_partial_write(self) -> None:
        parent = ExecutionContext()
        with pytest.raises(ValueError):
            await parent.update(good="ok", workflow_id="hijack")
        # The rejected batch must not have committed the valid key either, and
        # must not have clobbered the protected lifecycle key.
        assert await parent.get("good") is None

    async def test_update_commits_valid_batch(self) -> None:
        parent = ExecutionContext()
        await parent.update(a=1, b=2)
        assert await parent.get("a") == 1
        assert await parent.get("b") == 2
