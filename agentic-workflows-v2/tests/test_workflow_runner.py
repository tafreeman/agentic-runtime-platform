"""Integration tests for WorkflowRunner + DAG execution.

Covers:
- End-to-end: load YAML → validate inputs → execute DAG → resolve outputs
- Input validation (missing required, enum mismatch)
- Expression-based conditional execution (when clauses)
- Parallel execution through diamond DAGs
- WorkflowExecutor accepting DAG objects
- on_update event callbacks
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import yaml
from agentic_v2.contracts import StepStatus, WorkflowResult
from agentic_v2.engine import (
    DAG,
    ExecutionContext,
    StepDefinition,
    WorkflowExecutor,
)
from agentic_v2.workflows.runner import (
    WorkflowRunner,
    WorkflowValidationError,
    run_workflow,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_workflow(tmp: Path, name: str, data: dict) -> Path:
    """Write a YAML workflow to a temp directory and return the dir."""
    defs_dir = tmp / "definitions"
    defs_dir.mkdir(parents=True, exist_ok=True)
    path = defs_dir / f"{name}.yaml"
    path.write_text(yaml.dump(data, sort_keys=False), encoding="utf-8")
    return defs_dir


# ---------------------------------------------------------------------------
# WorkflowRunner – input validation
# ---------------------------------------------------------------------------


class TestWorkflowRunnerValidation:
    """Input validation before execution."""

    @pytest.mark.asyncio
    async def test_missing_required_input_raises(self):
        """Missing a required input raises WorkflowValidationError."""
        with TemporaryDirectory() as tmp:
            defs = _write_workflow(
                Path(tmp),
                "needs_input",
                {
                    "name": "needs_input",
                    "inputs": {
                        "required_field": {
                            "type": "string",
                            "description": "A required field",
                        }
                    },
                    "steps": [
                        {
                            "name": "placeholder",
                            "agent": "tier2_coder",
                            "description": "placeholder",
                        },
                    ],
                },
            )

            runner = WorkflowRunner(definitions_dir=defs)
            with pytest.raises(WorkflowValidationError, match="required_field"):
                await runner.run("needs_input")  # no inputs supplied

    @pytest.mark.asyncio
    async def test_default_value_fills_missing_input(self):
        """Inputs with defaults do not raise even when omitted."""
        with TemporaryDirectory() as tmp:
            defs = _write_workflow(
                Path(tmp),
                "with_default",
                {
                    "name": "with_default",
                    "inputs": {
                        "opt": {
                            "type": "string",
                            "default": "hello",
                        }
                    },
                    "steps": [
                        {
                            "name": "placeholder",
                            "agent": "tier2_coder",
                            "description": "placeholder",
                        },
                    ],
                },
            )

            runner = WorkflowRunner(definitions_dir=defs)
            result = await runner.run("with_default")  # no inputs
            assert result.overall_status == StepStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_enum_validation_rejects_bad_value(self):
        """Input with enum constraint rejects values not in the list."""
        with TemporaryDirectory() as tmp:
            defs = _write_workflow(
                Path(tmp),
                "enum_check",
                {
                    "name": "enum_check",
                    "inputs": {
                        "mode": {
                            "type": "string",
                            "enum": ["fast", "slow"],
                        }
                    },
                    "steps": [
                        {
                            "name": "placeholder",
                            "agent": "tier2_coder",
                            "description": "placeholder",
                        },
                    ],
                },
            )

            runner = WorkflowRunner(definitions_dir=defs)
            with pytest.raises(WorkflowValidationError, match="mode"):
                await runner.run("enum_check", mode="turbo")

    @pytest.mark.asyncio
    async def test_inputs_seeded_as_top_level_mapping_only(self):
        """Runner preserves inputs.name reads without dotted variable writes."""

        async def use_input(ctx):
            return {"seen": await ctx.get("inputs.mode")}

        from agentic_v2.workflows.loader import WorkflowDefinition, WorkflowInput

        dag = DAG("input_seed")
        dag.add(StepDefinition(name="use_input", func=use_input))
        definition = WorkflowDefinition(
            name="input_seed",
            inputs={"mode": WorkflowInput(name="mode")},
            dag=dag,
        )
        ctx = ExecutionContext(workflow_id="wf-input_seed")

        runner = WorkflowRunner()
        result = await runner.run_definition(definition, ctx, mode="fast")

        assert result.overall_status == StepStatus.SUCCESS
        assert result.steps[0].output_data["seen"] == "fast"
        assert ctx.get_sync("inputs.mode") == "fast"
        assert ctx.all_variables()["inputs"] == {"mode": "fast"}
        assert "inputs.mode" not in ctx.all_variables()


# ---------------------------------------------------------------------------
# WorkflowRunner – end-to-end DAG execution
# ---------------------------------------------------------------------------


class TestWorkflowRunnerExecution:
    """Run YAML workflows through the full pipeline."""

    @pytest.mark.asyncio
    async def test_simple_linear_workflow(self):
        """A → B linear workflow executes and populates context."""

        # We need agent-resolved or func-bearing steps.
        # Build a minimal YAML with tier0 agents (which resolve to noop).
        with TemporaryDirectory() as tmp:
            defs = _write_workflow(
                Path(tmp),
                "linear",
                {
                    "name": "linear",
                    "steps": [
                        {
                            "name": "first",
                            "agent": "tier0_parser",
                            "description": "First step",
                        },
                        {
                            "name": "second",
                            "agent": "tier0_parser",
                            "description": "Second step",
                            "depends_on": ["first"],
                        },
                    ],
                },
            )

            runner = WorkflowRunner(definitions_dir=defs)
            result = await runner.run("linear")

            assert result.overall_status == StepStatus.SUCCESS
            step_names = {s.step_name for s in result.steps}
            assert "first" in step_names
            assert "second" in step_names

    @pytest.mark.asyncio
    async def test_parallel_diamond_workflow(self):
        """Diamond pattern: root → (left, right) → join."""

        async def root(ctx):
            await ctx.set("root_done", True)
            return {"root": "ok"}

        async def left(ctx):
            return {"left": "ok"}

        async def right(ctx):
            return {"right": "ok"}

        async def join(ctx):
            return {"join": "ok"}

        from agentic_v2.workflows.loader import WorkflowDefinition

        dag = DAG("diamond", description="parallel diamond")
        dag.add(StepDefinition(name="root", func=root).with_output(root="root_out"))
        dag.add(
            StepDefinition(name="left", func=left)
            .with_dependency("root")
            .with_output(left="left_out")
        )
        dag.add(
            StepDefinition(name="right", func=right)
            .with_dependency("root")
            .with_output(right="right_out")
        )
        dag.add(
            StepDefinition(name="join", func=join)
            .with_dependency("left", "right")
            .with_output(join="join_out")
        )

        definition = WorkflowDefinition(name="diamond", dag=dag)

        runner = WorkflowRunner()
        result = await runner.run_definition(definition)

        assert result.overall_status == StepStatus.SUCCESS
        assert len(result.steps) == 4

    @pytest.mark.asyncio
    async def test_on_update_receives_events(self):
        """on_update callback fires for workflow and step events."""
        events: list[dict] = []

        async def capture(event: dict):
            events.append(event)

        async def noop(ctx):
            return {}

        from agentic_v2.workflows.loader import WorkflowDefinition

        dag = DAG("events")
        dag.add(StepDefinition(name="s1", func=noop))

        definition = WorkflowDefinition(name="events", dag=dag)
        runner = WorkflowRunner()
        await runner.run_definition(definition, on_update=capture)

        event_types = {e["type"] for e in events}
        assert "workflow_start" in event_types
        assert "step_start" in event_types
        assert "step_end" in event_types
        assert "workflow_end" in event_types


# ---------------------------------------------------------------------------
# WorkflowRunner – conditional (when) execution
# ---------------------------------------------------------------------------


class TestWorkflowRunnerConditionalExecution:
    """Steps with 'when' expressions are skipped when condition is false."""

    @pytest.mark.asyncio
    async def test_when_false_skips_step(self):
        """Step with when:false is skipped."""

        async def always_run(ctx):
            return {"ran": True}

        async def should_skip(ctx):
            return {"ran": True}

        from agentic_v2.workflows.loader import WorkflowDefinition

        dag = DAG("conditional")
        dag.add(StepDefinition(name="base", func=always_run))
        dag.add(
            StepDefinition(
                name="guarded",
                func=should_skip,
                when=lambda ctx: False,
            ).with_dependency("base")
        )

        definition = WorkflowDefinition(name="conditional", dag=dag)
        runner = WorkflowRunner()
        result = await runner.run_definition(definition)

        statuses = {s.step_name: s.status for s in result.steps}
        assert statuses["base"] == StepStatus.SUCCESS
        assert statuses["guarded"] == StepStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_when_true_runs_step(self):
        """Step with when:true executes normally."""

        async def step_fn(ctx):
            return {"ok": True}

        from agentic_v2.workflows.loader import WorkflowDefinition

        dag = DAG("cond_true")
        dag.add(
            StepDefinition(
                name="guarded",
                func=step_fn,
                when=lambda ctx: True,
            )
        )

        definition = WorkflowDefinition(name="cond_true", dag=dag)
        runner = WorkflowRunner()
        result = await runner.run_definition(definition)

        statuses = {s.step_name: s.status for s in result.steps}
        assert statuses["guarded"] == StepStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_when_expression_triggers_rework_on_non_approved_review(self):
        """Kickback path runs when review overall_status is not APPROVED."""

        async def review_step(ctx):
            return {
                "review_report": {
                    "overall_status": "REJECTED",
                }
            }

        async def rework_step(ctx):
            return {"rework_report": {"status": "reworked"}}

        from agentic_v2.engine.expressions import ExpressionEvaluator
        from agentic_v2.workflows.loader import WorkflowDefinition

        def _needs_rework(ctx) -> bool:
            return ExpressionEvaluator(ctx).evaluate(
                "${steps.review_code.outputs.review_report.overall_status != 'APPROVED'}"
            )

        dag = DAG("conditional_rework")
        dag.add(
            StepDefinition(name="review_code", func=review_step).with_output(
                review_report="review_report"
            )
        )
        dag.add(
            StepDefinition(
                name="developer_rework",
                func=rework_step,
                when=_needs_rework,
            )
            .with_dependency("review_code")
            .with_output(rework_report="rework_report")
        )

        definition = WorkflowDefinition(name="conditional_rework", dag=dag)
        runner = WorkflowRunner()
        result = await runner.run_definition(definition)

        statuses = {s.step_name: s.status for s in result.steps}
        assert statuses["review_code"] == StepStatus.SUCCESS
        assert statuses["developer_rework"] == StepStatus.SUCCESS


# ---------------------------------------------------------------------------
# WorkflowRunner – output resolution metadata
# ---------------------------------------------------------------------------


class TestWorkflowRunnerOutputResolution:
    """Required output resolution should annotate unresolved outputs."""

    @pytest.mark.asyncio
    async def test_unresolved_required_output_flagged(self):
        """Missing required output is recorded in result metadata."""

        async def producer(ctx):
            return {"present": "value"}

        from agentic_v2.workflows.loader import WorkflowDefinition, WorkflowOutput

        dag = DAG("required_missing")
        dag.add(StepDefinition(name="producer", func=producer))
        definition = WorkflowDefinition(
            name="required_missing",
            dag=dag,
            outputs={
                "required_result": WorkflowOutput(
                    name="required_result",
                    from_expr="${steps.producer.outputs.missing}",
                    optional=False,
                )
            },
        )

        runner = WorkflowRunner()
        result = await runner.run_definition(definition)
        assert "unresolved_required_outputs" in result.metadata
        assert "required_result" in result.metadata["unresolved_required_outputs"]

    @pytest.mark.asyncio
    async def test_resolved_output_no_flag(self):
        """Resolved required output does not produce unresolved metadata."""

        async def producer(ctx):
            return {"present": "value"}

        from agentic_v2.workflows.loader import WorkflowDefinition, WorkflowOutput

        dag = DAG("required_present")
        dag.add(StepDefinition(name="producer", func=producer))
        definition = WorkflowDefinition(
            name="required_present",
            dag=dag,
            outputs={
                "required_result": WorkflowOutput(
                    name="required_result",
                    from_expr="${steps.producer.outputs.present}",
                    optional=False,
                )
            },
        )

        runner = WorkflowRunner()
        result = await runner.run_definition(definition)
        assert not result.metadata.get("unresolved_required_outputs")


# ---------------------------------------------------------------------------
# WorkflowExecutor – DAG branch
# ---------------------------------------------------------------------------


class TestWorkflowExecutorDAG:
    """WorkflowExecutor now accepts DAG objects."""

    @pytest.mark.asyncio
    async def test_executor_runs_dag(self):
        """WorkflowExecutor.execute(dag) delegates to DAGExecutor."""

        async def step_a(ctx):
            return {"a": 1}

        async def step_b(ctx):
            return {"b": 2}

        dag = DAG("exec_dag")
        dag.add(StepDefinition(name="a", func=step_a))
        dag.add(StepDefinition(name="b", func=step_b).with_dependency("a"))

        executor = WorkflowExecutor()
        result = await executor.execute(dag)

        assert result.overall_status == StepStatus.SUCCESS
        assert len(result.steps) == 2

    @pytest.mark.asyncio
    async def test_executor_dag_failure(self):
        """WorkflowExecutor propagates DAG failures."""

        async def fail_step(ctx):
            raise RuntimeError("boom")

        dag = DAG("fail_dag")
        dag.add(StepDefinition(name="fail", func=fail_step))

        executor = WorkflowExecutor()
        result = await executor.execute(dag)

        assert result.overall_status == StepStatus.FAILED


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


class TestRunWorkflowConvenience:
    """run_workflow() one-liner."""

    @pytest.mark.asyncio
    async def test_run_workflow_loads_builtin(self):
        """run_workflow can load built-in code_review workflow."""
        # code_review requires code_file input; use a dummy path
        result = await run_workflow("code_review", code_file="__init__.py")

        # It should at least start and produce a result (tier0_parser
        # produces output even if the file doesn't exist at the path)
        assert isinstance(result, WorkflowResult)
