"""Tests for DAGExecutor parallel execution engine.

Covers:
- Parallel execution with max concurrency
- Failure cascade and skip propagation
- Step result collection
- State transitions during execution
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from agentic_v2.contracts import StepResult, StepStatus
from agentic_v2.engine.context import ExecutionContext
from agentic_v2.engine.dag import DAG
from agentic_v2.engine.dag_executor import DAGExecutor
from agentic_v2.engine.step import StepDefinition, StepExecutor


def make_step(name: str, depends_on: list[str] | None = None) -> StepDefinition:
    """Create a minimal StepDefinition for testing."""
    return StepDefinition(
        name=name,
        depends_on=depends_on or [],
    )


class TestDAGExecutorBasic:
    """Basic DAGExecutor tests."""

    @pytest.mark.asyncio
    async def test_execute_empty_dag(self):
        """Executing empty DAG raises ValueError."""
        dag = DAG(name="empty")
        executor = DAGExecutor()

        with pytest.raises(ValueError, match="has no steps"):
            await executor.execute(dag)

    @pytest.mark.asyncio
    async def test_execute_single_step(self):
        """Single step DAG executes successfully."""
        dag = DAG(name="single")
        dag.add(make_step("only"))

        # Mock the step executor to return success
        mock_step_executor = MagicMock(spec=StepExecutor)
        mock_step_executor.execute = AsyncMock(
            return_value=StepResult(
                step_name="only",
                status=StepStatus.SUCCESS,
                output_data={"result": "done"},
            )
        )

        executor = DAGExecutor(step_executor=mock_step_executor)
        result = await executor.execute(dag)

        assert result.overall_status == StepStatus.SUCCESS
        assert len(result.steps) == 1
        assert result.steps[0].step_name == "only"

    @pytest.mark.asyncio
    async def test_execute_linear_chain(self):
        """Linear A → B → C executes in order."""
        dag = DAG(name="chain")
        dag.add(make_step("a"))
        dag.add(make_step("b", depends_on=["a"]))
        dag.add(make_step("c", depends_on=["b"]))

        execution_order = []

        async def mock_execute(step_def, ctx):
            execution_order.append(step_def.name)
            return StepResult(step_name=step_def.name, status=StepStatus.SUCCESS)

        mock_step_executor = MagicMock(spec=StepExecutor)
        mock_step_executor.execute = AsyncMock(side_effect=mock_execute)

        executor = DAGExecutor(step_executor=mock_step_executor)
        result = await executor.execute(dag)

        assert execution_order == ["a", "b", "c"]
        assert result.overall_status == StepStatus.SUCCESS


class TestDAGExecutorParallel:
    """Tests for parallel execution behavior."""

    @pytest.mark.asyncio
    async def test_parallel_independent_steps(self):
        """Independent steps run in parallel."""
        dag = DAG(name="parallel")
        dag.add(make_step("a"))
        dag.add(make_step("b"))
        dag.add(make_step("c"))

        running_at_once = []
        currently_running = set()
        lock = asyncio.Lock()

        async def mock_execute(step_def, ctx):
            async with lock:
                currently_running.add(step_def.name)
                running_at_once.append(len(currently_running))

            await asyncio.sleep(0.05)  # Simulate work

            async with lock:
                currently_running.discard(step_def.name)

            return StepResult(step_name=step_def.name, status=StepStatus.SUCCESS)

        mock_step_executor = MagicMock(spec=StepExecutor)
        mock_step_executor.execute = AsyncMock(side_effect=mock_execute)

        executor = DAGExecutor(step_executor=mock_step_executor)
        await executor.execute(dag, max_concurrency=10)

        # At some point, multiple steps were running
        assert max(running_at_once) >= 2

    @pytest.mark.asyncio
    async def test_max_concurrency_limit(self):
        """max_concurrency limits parallel execution."""
        dag = DAG(name="limited")
        for i in range(5):
            dag.add(make_step(f"step{i}"))

        max_observed = 0
        currently_running = 0
        lock = asyncio.Lock()

        async def mock_execute(step_def, ctx):
            nonlocal max_observed, currently_running
            async with lock:
                currently_running += 1
                max_observed = max(max_observed, currently_running)

            await asyncio.sleep(0.03)

            async with lock:
                currently_running -= 1

            return StepResult(step_name=step_def.name, status=StepStatus.SUCCESS)

        mock_step_executor = MagicMock(spec=StepExecutor)
        mock_step_executor.execute = AsyncMock(side_effect=mock_execute)

        executor = DAGExecutor(step_executor=mock_step_executor)
        await executor.execute(dag, max_concurrency=2)

        assert max_observed <= 2


class TestDAGExecutorFailure:
    """Tests for failure handling."""

    @pytest.mark.asyncio
    async def test_step_failure_cascades_to_dependents(self):
        """Failed step causes dependent steps to be skipped."""
        dag = DAG(name="cascade")
        dag.add(make_step("parent"))
        dag.add(make_step("child", depends_on=["parent"]))
        dag.add(make_step("grandchild", depends_on=["child"]))

        call_count = {"parent": 0, "child": 0, "grandchild": 0}

        async def mock_execute(step_def, ctx):
            call_count[step_def.name] += 1
            if step_def.name == "parent":
                return StepResult(
                    step_name="parent", status=StepStatus.FAILED, error="Parent failed"
                )
            return StepResult(step_name=step_def.name, status=StepStatus.SUCCESS)

        mock_step_executor = MagicMock(spec=StepExecutor)
        mock_step_executor.execute = AsyncMock(side_effect=mock_execute)

        executor = DAGExecutor(step_executor=mock_step_executor)
        result = await executor.execute(dag)

        # Parent was executed, children were skipped (not executed)
        assert call_count["parent"] == 1
        assert call_count["child"] == 0
        assert call_count["grandchild"] == 0

        # Check result status
        assert result.overall_status == StepStatus.FAILED

        step_statuses = {s.step_name: s.status for s in result.steps}
        assert step_statuses["parent"] == StepStatus.FAILED
        assert step_statuses["child"] == StepStatus.SKIPPED
        assert step_statuses["grandchild"] == StepStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_partial_failure_allows_independent_steps(self):
        """Failure in one branch doesn't affect independent branches."""
        dag = DAG(name="branches")
        dag.add(make_step("root"))
        dag.add(make_step("left", depends_on=["root"]))
        dag.add(make_step("right", depends_on=["root"]))
        dag.add(make_step("left_child", depends_on=["left"]))
        dag.add(make_step("right_child", depends_on=["right"]))

        async def mock_execute(step_def, ctx):
            if step_def.name == "left":
                return StepResult(
                    step_name="left", status=StepStatus.FAILED, error="Left failed"
                )
            return StepResult(step_name=step_def.name, status=StepStatus.SUCCESS)

        mock_step_executor = MagicMock(spec=StepExecutor)
        mock_step_executor.execute = AsyncMock(side_effect=mock_execute)

        executor = DAGExecutor(step_executor=mock_step_executor)
        result = await executor.execute(dag)

        step_statuses = {s.step_name: s.status for s in result.steps}

        # Left branch failed
        assert step_statuses["left"] == StepStatus.FAILED
        assert step_statuses["left_child"] == StepStatus.SKIPPED

        # Right branch succeeded
        assert step_statuses["right"] == StepStatus.SUCCESS
        assert step_statuses["right_child"] == StepStatus.SUCCESS


class TestDAGExecutorContext:
    """Tests for context integration."""

    @pytest.mark.asyncio
    async def test_uses_provided_context(self):
        """DAGExecutor uses the provided ExecutionContext."""
        dag = DAG(name="context_test")
        dag.add(make_step("step1"))

        ctx = ExecutionContext(workflow_id="test-123")

        captured_ctx = None

        async def mock_execute(step_def, context):
            nonlocal captured_ctx
            captured_ctx = context
            return StepResult(step_name=step_def.name, status=StepStatus.SUCCESS)

        mock_step_executor = MagicMock(spec=StepExecutor)
        mock_step_executor.execute = AsyncMock(side_effect=mock_execute)

        executor = DAGExecutor(step_executor=mock_step_executor)
        result = await executor.execute(dag, ctx=ctx)

        assert captured_ctx is ctx
        assert result.workflow_id == "test-123"

    @pytest.mark.asyncio
    async def test_creates_context_if_not_provided(self):
        """DAGExecutor creates context when not provided."""
        dag = DAG(name="auto_context")
        dag.add(make_step("step1"))

        mock_step_executor = MagicMock(spec=StepExecutor)
        mock_step_executor.execute = AsyncMock(
            return_value=StepResult(step_name="step1", status=StepStatus.SUCCESS)
        )

        executor = DAGExecutor(step_executor=mock_step_executor)
        result = await executor.execute(dag)  # No ctx provided

        assert result.workflow_id is not None
        assert result.workflow_name == "auto_context"


class TestDAGExecutorResult:
    """Tests for WorkflowResult generation."""

    @pytest.mark.asyncio
    async def test_result_contains_all_steps(self):
        """Result includes all executed and skipped steps."""
        dag = DAG(name="full_result")
        dag.add(make_step("a"))
        dag.add(make_step("b"))
        dag.add(make_step("c", depends_on=["a"]))

        async def mock_execute(step_def, ctx):
            if step_def.name == "a":
                return StepResult(step_name="a", status=StepStatus.FAILED)
            return StepResult(step_name=step_def.name, status=StepStatus.SUCCESS)

        mock_step_executor = MagicMock(spec=StepExecutor)
        mock_step_executor.execute = AsyncMock(side_effect=mock_execute)

        executor = DAGExecutor(step_executor=mock_step_executor)
        result = await executor.execute(dag)

        step_names = {s.step_name for s in result.steps}
        assert step_names == {"a", "b", "c"}

    @pytest.mark.asyncio
    async def test_result_final_output_contains_context(self):
        """Result final_output contains context variables."""
        dag = DAG(name="output_test")
        dag.add(make_step("step1"))

        ctx = ExecutionContext()
        ctx.set_sync("test_var", "test_value")

        mock_step_executor = MagicMock(spec=StepExecutor)
        mock_step_executor.execute = AsyncMock(
            return_value=StepResult(step_name="step1", status=StepStatus.SUCCESS)
        )

        executor = DAGExecutor(step_executor=mock_step_executor)
        result = await executor.execute(dag, ctx=ctx)

        assert result.final_output.get("test_var") == "test_value"
