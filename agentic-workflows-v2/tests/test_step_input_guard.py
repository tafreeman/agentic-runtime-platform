"""Input-side null guard tests (July 2026 bug triage).

Covers the case where a workflow step's declared input expression resolves
to ``None`` at runtime — the step used to run anyway, silently handing the
agent a missing value (observed live on
``fullstack_generation-06362db9``: ``generate_api`` produced C#/ASP.NET
output because its resolved inputs were all null). This module tests the
resulting structured WARNING on both execution paths:

- langchain (server default): ``graph_wiring.resolve_inputs_into_context``.
- native engine: ``engine.step.StepExecutor._prepare_inputs``.

Both paths are warn-only (no required/optional distinction exists on
``StepConfig.inputs`` or ``StepDefinition.input_mapping`` today), so these
tests assert the step still completes — only a WARNING is emitted.
"""

from __future__ import annotations

import logging

import pytest

from agentic_v2.contracts import StepResult, StepStatus
from agentic_v2.engine.context import ExecutionContext
from agentic_v2.engine.step import StepDefinition, StepExecutor
from agentic_v2.langchain.config import StepConfig
from agentic_v2.langchain.graph_wiring import resolve_inputs_into_context
from agentic_v2.langchain.state import initial_state

# ---------------------------------------------------------------------------
# langchain path: resolve_inputs_into_context
# ---------------------------------------------------------------------------


class TestLangchainResolveInputsNullGuard:
    """``graph_wiring.resolve_inputs_into_context`` null-input warning."""

    def test_null_resolving_input_emits_warning_naming_step_and_key(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A step input expression that resolves to None logs one WARNING naming the
        step and the offending input key."""
        step = StepConfig(
            name="generate_api",
            agent="tier2_coder",
            inputs={"api_spec": "${steps.design_architecture.outputs.api_spec}"},
        )
        state = initial_state()

        with caplog.at_level(
            logging.WARNING, logger="agentic_v2.langchain.graph_wiring"
        ):
            ctx, resolved = resolve_inputs_into_context(step, state)

        assert resolved == {"api_spec": None}
        assert ctx["api_spec"] is None

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        message = warnings[0].getMessage()
        assert "generate_api" in message
        assert "api_spec" in message
        assert "null" in message.lower()

    def test_all_inputs_present_emits_no_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When every declared input resolves to a non-null value, no WARNING is
        logged."""
        step = StepConfig(
            name="design_architecture",
            agent="tier3_architect",
            inputs={"spec": "${inputs.feature_spec}", "stack": "${inputs.tech_stack}"},
        )
        state = initial_state(
            workflow_inputs={"feature_spec": "a todo app", "tech_stack": "fastapi"}
        )

        with caplog.at_level(
            logging.WARNING, logger="agentic_v2.langchain.graph_wiring"
        ):
            ctx, resolved = resolve_inputs_into_context(step, state)

        assert resolved == {"spec": "a todo app", "stack": "fastapi"}
        assert not any(r.levelno == logging.WARNING for r in caplog.records)

    def test_coalesce_resolving_non_null_emits_no_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A ``coalesce(...)`` expression that ultimately resolves to a non-null
        fallback value does not warn (mirrors the fullstack_generation.yaml convention
        of aliased output keys)."""
        step = StepConfig(
            name="generate_api",
            agent="tier2_coder",
            inputs={
                "api_spec": (
                    "${coalesce(steps.design_architecture.outputs.api_spec, "
                    "steps.design_architecture.outputs.api_design)}"
                )
            },
        )
        state = initial_state()
        state["steps"]["design_architecture"] = {
            "status": "success",
            # First alias (api_spec) is absent; coalesce falls through to
            # the second alias (api_design), which IS present.
            "outputs": {"api_design": {"routes": ["/todos"]}},
        }

        with caplog.at_level(
            logging.WARNING, logger="agentic_v2.langchain.graph_wiring"
        ):
            ctx, resolved = resolve_inputs_into_context(step, state)

        assert resolved == {"api_spec": {"routes": ["/todos"]}}
        assert not any(r.levelno == logging.WARNING for r in caplog.records)

    def test_coalesce_resolving_null_still_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A ``coalesce(...)`` expression whose every argument is missing still resolves
        to None and still warns — coalesce is a fallback mechanism, not an opt-out from
        the guard."""
        step = StepConfig(
            name="generate_api",
            agent="tier2_coder",
            inputs={
                "api_spec": (
                    "${coalesce(steps.design_architecture.outputs.api_spec, "
                    "steps.design_architecture.outputs.api_design)}"
                )
            },
        )
        state = initial_state()
        state["steps"]["design_architecture"] = {"status": "success", "outputs": {}}

        with caplog.at_level(
            logging.WARNING, logger="agentic_v2.langchain.graph_wiring"
        ):
            _ctx, resolved = resolve_inputs_into_context(step, state)

        assert resolved == {"api_spec": None}
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "generate_api" in warnings[0].getMessage()

    def test_multiple_null_inputs_aggregate_into_one_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Multiple null-resolving inputs on the same step produce ONE aggregated
        warning line (not one per key) to keep log noise reasonable."""
        step = StepConfig(
            name="generate_api",
            agent="tier2_coder",
            inputs={
                "api_spec": "${steps.design_architecture.outputs.api_spec}",
                "db_schema": "${steps.design_architecture.outputs.db_schema}",
            },
        )
        state = initial_state()

        with caplog.at_level(
            logging.WARNING, logger="agentic_v2.langchain.graph_wiring"
        ):
            resolve_inputs_into_context(step, state)

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        message = warnings[0].getMessage()
        assert "api_spec" in message
        assert "db_schema" in message


# ---------------------------------------------------------------------------
# native engine path: StepExecutor._prepare_inputs
# ---------------------------------------------------------------------------


class TestNativeEnginePrepareInputsNullGuard:
    """``engine.step.StepExecutor._prepare_inputs`` null-input warning."""

    @pytest.mark.asyncio
    async def test_null_mapped_input_emits_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A step input mapped from an unset context variable resolves to None and logs
        one WARNING naming the step and the input key."""
        step_def = StepDefinition(name="generate_api").with_input(
            api_spec="architecture_output"
        )
        ctx = ExecutionContext()
        result = StepResult(step_name="generate_api", status=StepStatus.PENDING)
        executor = StepExecutor()

        with caplog.at_level(logging.WARNING, logger="agentic_v2.engine.step"):
            child_ctx = await executor._prepare_inputs(step_def, ctx, result)

        assert result.input_data == {"api_spec": None}
        assert await child_ctx.get("api_spec") is None

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        message = warnings[0].getMessage()
        assert "generate_api" in message
        assert "api_spec" in message
        assert "null" in message.lower()

    @pytest.mark.asyncio
    async def test_present_mapped_input_emits_no_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A step input mapped from a context variable that IS set does not warn."""
        step_def = StepDefinition(name="generate_api").with_input(
            api_spec="architecture_output"
        )
        ctx = ExecutionContext()
        await ctx.set("architecture_output", {"routes": ["/todos"]})
        result = StepResult(step_name="generate_api", status=StepStatus.PENDING)
        executor = StepExecutor()

        with caplog.at_level(logging.WARNING, logger="agentic_v2.engine.step"):
            child_ctx = await executor._prepare_inputs(step_def, ctx, result)

        assert result.input_data == {"api_spec": {"routes": ["/todos"]}}
        assert await child_ctx.get("api_spec") == {"routes": ["/todos"]}
        assert not any(r.levelno == logging.WARNING for r in caplog.records)

    @pytest.mark.asyncio
    async def test_multiple_null_inputs_aggregate_into_one_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Multiple null-resolving mapped inputs aggregate into ONE warning line for the
        step."""
        step_def = StepDefinition(name="generate_api").with_input(
            api_spec="architecture_output", db_schema="database_schema"
        )
        ctx = ExecutionContext()
        result = StepResult(step_name="generate_api", status=StepStatus.PENDING)
        executor = StepExecutor()

        with caplog.at_level(logging.WARNING, logger="agentic_v2.engine.step"):
            await executor._prepare_inputs(step_def, ctx, result)

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        message = warnings[0].getMessage()
        assert "api_spec" in message
        assert "db_schema" in message

    @pytest.mark.asyncio
    async def test_end_to_end_execute_with_null_input_still_succeeds(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Full StepExecutor.execute() with a null-resolving input still completes
        SUCCESS (warn-only: the guard does not fail the step)."""

        async def echo(child_ctx: ExecutionContext) -> dict[str, object]:
            return {"received": await child_ctx.get("api_spec")}

        step_def = StepDefinition(name="generate_api", func=echo).with_input(
            api_spec="architecture_output"
        )
        ctx = ExecutionContext()
        executor = StepExecutor()

        with caplog.at_level(logging.WARNING, logger="agentic_v2.engine.step"):
            result = await executor.execute(step_def, ctx)

        assert result.is_success
        assert result.output_data == {"received": None}
        assert any(
            "generate_api" in r.getMessage()
            for r in caplog.records
            if r.levelno == logging.WARNING
        )
