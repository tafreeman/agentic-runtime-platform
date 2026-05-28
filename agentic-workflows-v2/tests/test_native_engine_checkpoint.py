"""Tests for NativeEngine SQLite checkpointing.

Covers:
- Checkpoint rows written on successful step completion
- Resume after mid-workflow failure (only incomplete steps re-run)
- get_checkpoint_state() returns correct step statuses
- resume() with unknown thread_id runs from scratch
- Concurrent executions with different thread_ids are isolated

All tests use ``tmp_path`` for the SQLite database to avoid filesystem
pollution.  The project uses ``asyncio_mode = "auto"`` in pyproject.toml
so ``@pytest.mark.asyncio`` is not needed.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from agentic_v2.adapters.native._checkpoint_store import CheckpointStore
from agentic_v2.adapters.native.engine import NativeEngine
from agentic_v2.contracts import StepResult, StepStatus, WorkflowResult
from agentic_v2.core.protocols import SupportsCheckpointing
from agentic_v2.engine.dag import DAG
from agentic_v2.engine.dag_executor import DAGExecutor
from agentic_v2.engine.step import StepDefinition, StepExecutor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_step(
    name: str,
    depends_on: list[str] | None = None,
) -> StepDefinition:
    """Create a minimal StepDefinition for testing."""
    return StepDefinition(name=name, depends_on=depends_on or [])


def _make_dag(
    name: str,
    steps: list[StepDefinition],
) -> DAG:
    """Build a DAG from a list of step definitions."""
    dag = DAG(name=name)
    for step in steps:
        dag.add(step)
    return dag


def _success_result(step_name: str, output: dict[str, Any] | None = None) -> StepResult:
    """Create a successful StepResult."""
    return StepResult(
        step_name=step_name,
        status=StepStatus.SUCCESS,
        output_data=output or {},
    )


def _failed_result(step_name: str, error: str = "boom") -> StepResult:
    """Create a failed StepResult."""
    return StepResult(
        step_name=step_name,
        status=StepStatus.FAILED,
        error=error,
    )


# ---------------------------------------------------------------------------
# CheckpointStore unit tests
# ---------------------------------------------------------------------------


class TestCheckpointStore:
    """Direct CheckpointStore tests (not mediated by NativeEngine)."""

    async def test_write_and_read(self, tmp_path: Path) -> None:
        """Write a checkpoint and read it back."""
        store = CheckpointStore(tmp_path / "ckpt.db")
        await store.write("t1", "wf", "step_a", "success", {"x": 1})

        rows = await store.read("t1")
        assert "step_a" in rows
        assert rows["step_a"]["status"] == "success"
        assert rows["step_a"]["output_data"] == {"x": 1}

    async def test_read_empty(self, tmp_path: Path) -> None:
        """Reading a nonexistent thread returns empty dict."""
        store = CheckpointStore(tmp_path / "ckpt.db")
        rows = await store.read("nonexistent")
        assert rows == {}

    async def test_upsert_overwrites(self, tmp_path: Path) -> None:
        """INSERT OR REPLACE overwrites existing rows."""
        store = CheckpointStore(tmp_path / "ckpt.db")
        await store.write("t1", "wf", "step_a", "failed", {"old": True})
        await store.write("t1", "wf", "step_a", "success", {"new": True})

        rows = await store.read("t1")
        assert rows["step_a"]["status"] == "success"
        assert rows["step_a"]["output_data"] == {"new": True}

    async def test_clear(self, tmp_path: Path) -> None:
        """Clear removes all rows for a thread."""
        store = CheckpointStore(tmp_path / "ckpt.db")
        await store.write("t1", "wf", "a", "success", {})
        await store.write("t1", "wf", "b", "success", {})
        await store.write("t2", "wf", "a", "success", {})

        await store.clear("t1")
        assert await store.read("t1") == {}
        # t2 is untouched
        assert "a" in await store.read("t2")

    async def test_clear_nonexistent_is_noop(self, tmp_path: Path) -> None:
        """Clearing a nonexistent thread does not raise."""
        store = CheckpointStore(tmp_path / "ckpt.db")
        await store.clear("ghost")  # no error


# ---------------------------------------------------------------------------
# NativeEngine checkpoint integration tests
# ---------------------------------------------------------------------------


class TestNativeEngineCheckpoint:
    """Integration tests for NativeEngine with checkpointing enabled."""

    async def test_execute_drains_checkpoint_tasks(self, tmp_path: Path) -> None:
        """Execute drains internally tracked checkpoint write tasks before return."""
        db_path = tmp_path / "ckpt.db"
        dag = _make_dag("simple", [_make_step("a")])

        mock_step_exec = MagicMock(spec=StepExecutor)
        mock_step_exec.execute = AsyncMock(return_value=_success_result("a"))

        engine = NativeEngine(checkpoint_db_path=db_path)
        engine._dag_executor = DAGExecutor(step_executor=mock_step_exec)

        await engine.execute(dag, thread_id="t-drain")

        assert engine._checkpoint_tasks == set()

    async def test_execute_drains_checkpoint_tasks_when_dispatch_raises(
        self,
        tmp_path: Path,
    ) -> None:
        """Execute drains scheduled checkpoint writes before re-raising failures."""
        db_path = tmp_path / "ckpt.db"
        dag = _make_dag("simple", [_make_step("a")])
        engine = NativeEngine(checkpoint_db_path=db_path)

        async def _raising_dispatch(
            _workflow: Any,
            _ctx: Any,
            on_update: Any,
            **_kwargs: Any,
        ) -> WorkflowResult:
            assert on_update is not None
            await on_update(
                {
                    "type": "step_end",
                    "status": StepStatus.SUCCESS.value,
                    "step": "a",
                    "output": {"result": "ok"},
                }
            )
            raise RuntimeError("dispatch boom")

        engine._dispatch = _raising_dispatch  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="dispatch boom"):
            await engine.execute(dag, thread_id="t-raise")

        assert engine._checkpoint_tasks == set()

        store = CheckpointStore(db_path)
        rows = await store.read("t-raise")
        assert rows["a"]["output_data"] == {"result": "ok"}

    async def test_execute_writes_checkpoints(self, tmp_path: Path) -> None:
        """Execute with thread_id writes checkpoint rows for each completed step."""
        db_path = tmp_path / "ckpt.db"
        dag = _make_dag(
            "linear",
            [
                _make_step("a"),
                _make_step("b", depends_on=["a"]),
            ],
        )

        # Mock step executor to return success with output data
        mock_step_exec = MagicMock(spec=StepExecutor)

        async def _mock_execute(step_def: Any, ctx: Any) -> StepResult:
            return _success_result(step_def.name, {"result": f"{step_def.name}_done"})

        mock_step_exec.execute = AsyncMock(side_effect=_mock_execute)

        engine = NativeEngine(checkpoint_db_path=db_path)
        engine._dag_executor = DAGExecutor(step_executor=mock_step_exec)

        result = await engine.execute(dag, thread_id="thread-1")
        assert result.overall_status == StepStatus.SUCCESS

        store = CheckpointStore(db_path)
        rows = await store.read("thread-1")
        assert "a" in rows
        assert "b" in rows
        assert rows["a"]["status"] == "success"
        assert rows["b"]["status"] == "success"

    async def test_execute_without_thread_id_skips_checkpoint(
        self,
        tmp_path: Path,
    ) -> None:
        """Execute without thread_id does not create any checkpoint rows."""
        db_path = tmp_path / "ckpt.db"
        dag = _make_dag("simple", [_make_step("a")])

        mock_step_exec = MagicMock(spec=StepExecutor)
        mock_step_exec.execute = AsyncMock(
            return_value=_success_result("a"),
        )

        engine = NativeEngine(checkpoint_db_path=db_path)
        engine._dag_executor = DAGExecutor(step_executor=mock_step_exec)

        await engine.execute(dag)

        # DB file should not even exist (lazy creation on first write)
        assert not db_path.exists()

    async def test_resume_after_failure(self, tmp_path: Path) -> None:
        """Resume skips already-completed steps and re-runs the rest.

        The mock StepExecutor mirrors the real one's ``should_run()``
        behaviour: if a step is already in ``ctx.completed_steps`` it
        returns SKIPPED instead of executing the step function.
        """
        db_path = tmp_path / "ckpt.db"
        dag = _make_dag(
            "chain",
            [
                _make_step("a"),
                _make_step("b", depends_on=["a"]),
                _make_step("c", depends_on=["b"]),
            ],
        )

        # Pre-populate checkpoints: step_a succeeded
        store = CheckpointStore(db_path)
        await store.write("t-resume", "chain", "a", "success", {"val": 42})

        # Track which steps actually run their function body
        executed_steps: list[str] = []

        mock_step_exec = MagicMock(spec=StepExecutor)

        async def _mock_execute(step_def: Any, ctx: Any) -> StepResult:
            # Mirror the real StepExecutor: skip if already completed
            if step_def.name in ctx.completed_steps:
                return StepResult(
                    step_name=step_def.name,
                    status=StepStatus.SKIPPED,
                )
            executed_steps.append(step_def.name)
            return _success_result(step_def.name, {"result": "ok"})

        mock_step_exec.execute = AsyncMock(side_effect=_mock_execute)

        engine = NativeEngine(checkpoint_db_path=db_path)
        engine._dag_executor = DAGExecutor(step_executor=mock_step_exec)

        result = await engine.resume(dag, thread_id="t-resume")

        # Step "a" should be skipped (already checkpointed as SUCCESS)
        assert "a" not in executed_steps
        # Steps b and c should have been executed
        assert "b" in executed_steps
        assert "c" in executed_steps

    async def test_get_checkpoint_state(self, tmp_path: Path) -> None:
        """get_checkpoint_state returns correct step statuses."""
        db_path = tmp_path / "ckpt.db"
        store = CheckpointStore(db_path)
        await store.write("t1", "wf", "step_a", "success", {"x": 1})
        await store.write("t1", "wf", "step_b", "success", {"y": 2})

        engine = NativeEngine(checkpoint_db_path=db_path)
        dag = _make_dag("wf", [_make_step("step_a"), _make_step("step_b")])

        state = engine.get_checkpoint_state(dag, thread_id="t1")
        assert state is not None
        assert "step_a" in state
        assert "step_b" in state
        assert state["step_a"]["status"] == "success"
        assert state["step_a"]["output_data"] == {"x": 1}

    async def test_get_checkpoint_state_empty(self, tmp_path: Path) -> None:
        """get_checkpoint_state returns None for unknown thread."""
        db_path = tmp_path / "ckpt.db"
        engine = NativeEngine(checkpoint_db_path=db_path)
        dag = _make_dag("wf", [_make_step("a")])

        state = engine.get_checkpoint_state(dag, thread_id="nonexistent")
        assert state is None

    async def test_get_checkpoint_state_without_store(self) -> None:
        """get_checkpoint_state returns None when no store is configured."""
        engine = NativeEngine()
        dag = _make_dag("wf", [_make_step("a")])

        state = engine.get_checkpoint_state(dag, thread_id="any")
        assert state is None

    async def test_resume_unknown_thread_runs_from_scratch(
        self,
        tmp_path: Path,
    ) -> None:
        """Resume with an unknown thread_id runs the full workflow."""
        db_path = tmp_path / "ckpt.db"
        dag = _make_dag(
            "full",
            [
                _make_step("a"),
                _make_step("b", depends_on=["a"]),
            ],
        )

        executed_steps: list[str] = []

        mock_step_exec = MagicMock(spec=StepExecutor)

        async def _mock_execute(step_def: Any, ctx: Any) -> StepResult:
            executed_steps.append(step_def.name)
            return _success_result(step_def.name)

        mock_step_exec.execute = AsyncMock(side_effect=_mock_execute)

        engine = NativeEngine(checkpoint_db_path=db_path)
        engine._dag_executor = DAGExecutor(step_executor=mock_step_exec)

        result = await engine.resume(dag, thread_id="never-seen")
        assert result.overall_status == StepStatus.SUCCESS
        assert "a" in executed_steps
        assert "b" in executed_steps

    async def test_concurrent_threads_no_cross_contamination(
        self,
        tmp_path: Path,
    ) -> None:
        """Concurrent executions with different thread_ids write isolated checkpoint
        rows to the same SQLite database.

        Each NativeEngine gets its own DAGExecutor to avoid the shared-
        state-manager race that occurs when two DAG runs share one
        executor instance.
        """
        db_path = tmp_path / "ckpt.db"

        dag_1 = _make_dag("wf1", [_make_step("x"), _make_step("y")])
        dag_2 = _make_dag("wf2", [_make_step("p"), _make_step("q")])

        def _build_mock_step_executor() -> MagicMock:
            mock = MagicMock(spec=StepExecutor)

            async def _run(step_def: Any, ctx: Any) -> StepResult:
                await asyncio.sleep(0.02)
                return _success_result(step_def.name, {"source": step_def.name})

            mock.execute = AsyncMock(side_effect=_run)
            return mock

        engine_a = NativeEngine(checkpoint_db_path=db_path)
        engine_a._dag_executor = DAGExecutor(
            step_executor=_build_mock_step_executor(),
        )

        engine_b = NativeEngine(checkpoint_db_path=db_path)
        engine_b._dag_executor = DAGExecutor(
            step_executor=_build_mock_step_executor(),
        )

        result_1, result_2 = await asyncio.gather(
            engine_a.execute(dag_1, thread_id="thread-A"),
            engine_b.execute(dag_2, thread_id="thread-B"),
        )

        assert result_1.overall_status == StepStatus.SUCCESS
        assert result_2.overall_status == StepStatus.SUCCESS

        store = CheckpointStore(db_path)

        rows_a = await store.read("thread-A")
        rows_b = await store.read("thread-B")

        # Thread A should only have steps from wf1
        assert set(rows_a.keys()) == {"x", "y"}
        # Thread B should only have steps from wf2
        assert set(rows_b.keys()) == {"p", "q"}

        # No leakage
        for step_data in rows_a.values():
            assert step_data["workflow_name"] == "wf1"
        for step_data in rows_b.values():
            assert step_data["workflow_name"] == "wf2"


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    """Verify NativeEngine satisfies SupportsCheckpointing."""

    def test_supports_checkpointing_protocol(self, tmp_path: Path) -> None:
        """NativeEngine with checkpoint store satisfies SupportsCheckpointing."""
        engine = NativeEngine(checkpoint_db_path=tmp_path / "ckpt.db")
        assert isinstance(engine, SupportsCheckpointing)

    def test_supports_checkpointing_without_store(self) -> None:
        """NativeEngine without checkpoint store still satisfies the protocol
        structurally (methods exist even if they return None)."""
        engine = NativeEngine()
        assert isinstance(engine, SupportsCheckpointing)
