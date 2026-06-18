"""Tests for execution engine components."""

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from agentic_v2.contracts import StepStatus
from agentic_v2.engine import (  # Context; Steps; Pipeline; Executor
    DAG,
    EventType,
    ExecutionConfig,
    ExecutionContext,
    Pipeline,
    PipelineBuilder,
    RetryConfig,
    RetryStrategy,
    ServiceContainer,
    StepDefinition,
    StepExecutor,
    WorkflowExecutor,
    execute,
    reset_context,
    reset_executor,
    run,
    run_pipeline,
    step,
)
from agentic_v2.engine.agent_resolver import _parse_llm_json_output, resolve_agent
from agentic_v2.models import ModelTier

# ============================================================================
# ExecutionContext Tests
# ============================================================================


class TestExecutionContext:
    """Tests for ExecutionContext."""

    def setup_method(self):
        reset_context()

    @pytest.mark.asyncio
    async def test_basic_variable_operations(self):
        """Test get/set/delete operations."""
        ctx = ExecutionContext()

        await ctx.set("foo", "bar")
        assert await ctx.get("foo") == "bar"

        await ctx.delete("foo")
        assert await ctx.get("foo") is None

    @pytest.mark.asyncio
    async def test_jmespath_queries(self):
        """Test JMESPath variable queries."""
        ctx = ExecutionContext()

        await ctx.set(
            "data",
            {"items": [{"name": "first", "value": 1}, {"name": "second", "value": 2}]},
        )

        # Query nested path
        result = await ctx.get("data.items[0].name")
        assert result == "first"

        # Array access
        result = await ctx.get("data.items[1].value")
        assert result == 2

    @pytest.mark.asyncio
    async def test_child_context_inheritance(self):
        """Test child context inherits from parent."""
        parent = ExecutionContext()
        await parent.set("parent_var", "parent_value")

        child = parent.child("test_step")

        # Child can read parent variables
        assert await child.get("parent_var") == "parent_value"

        # Child writes are local
        await child.set("child_var", "child_value")
        assert await child.get("child_var") == "child_value"
        assert await parent.get("child_var") is None

    def test_interpolation(self):
        """Test variable interpolation in templates."""
        ctx = ExecutionContext()
        ctx.set_sync("name", "Alice")
        ctx.set_sync("count", 42)

        result = ctx.interpolate("Hello ${name}, you have ${count} items")
        assert result == "Hello Alice, you have 42 items"

    @pytest.mark.asyncio
    async def test_event_handlers(self):
        """Test event emission and handling."""
        ctx = ExecutionContext()
        events = []

        def handler(ctx, event_type, data):
            events.append((event_type, data))

        ctx.on(EventType.VARIABLE_SET, handler)

        await ctx.set("test", "value")

        assert len(events) == 1
        assert events[0][0] == EventType.VARIABLE_SET
        assert events[0][1]["key"] == "test"

    @pytest.mark.asyncio
    async def test_step_tracking(self):
        """Test step completion tracking."""
        ctx = ExecutionContext()

        await ctx.mark_step_start("step1")
        assert ctx.current_step == "step1"

        await ctx.mark_step_complete("step1")
        assert ctx.is_step_complete("step1")
        assert ctx.current_step is None

        await ctx.mark_step_failed("step2", "error")
        assert ctx.is_step_failed("step2")

    @pytest.mark.asyncio
    async def test_checkpoint_save_restore(self):
        """Test checkpoint save and restore."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = ExecutionContext(checkpoint_dir=Path(tmpdir))

            await ctx.set("key1", "value1")
            await ctx.set("key2", {"nested": "data"})
            ctx.completed_steps.append("step1")

            # Save checkpoint
            checkpoint_path = await ctx.save_checkpoint("test")
            assert checkpoint_path.exists()

            # Create new context and restore
            ctx2 = ExecutionContext(checkpoint_dir=Path(tmpdir))
            await ctx2.restore_checkpoint(checkpoint_path)

            assert await ctx2.get("key1") == "value1"
            assert "step1" in ctx2.completed_steps

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "variables",
        [
            {"bad.path": "value"},
            {"workflow_id": "shadow"},
            {"": "empty"},
        ],
    )
    async def test_restore_checkpoint_rejects_invalid_variable_keys(self, variables):
        """Checkpoint restore validates variables before mutating state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint_path = Path(tmpdir) / "invalid.json"
            checkpoint_path.write_text(
                json.dumps(
                    {
                        "variables": variables,
                        "completed_steps": ["from_checkpoint"],
                        "failed_steps": [],
                        "metadata": {"from_checkpoint": True},
                    }
                )
            )

            ctx = ExecutionContext(checkpoint_dir=Path(tmpdir))
            await ctx.set("existing", "keep")

            with pytest.raises(ValueError, match="checkpoint"):
                await ctx.restore_checkpoint(checkpoint_path)

            assert await ctx.get("existing") == "keep"
            assert ctx.completed_steps == []
            assert ctx.metadata == {}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "key",
        ["", "data.items[0].name", "data.name", "inputs.name"],
    )
    async def test_rejects_invalid_variable_names_on_async_set(self, key):
        """Public writes reject empty keys and JMESPath-style paths."""
        ctx = ExecutionContext()

        with pytest.raises(ValueError):
            await ctx.set(key, "value")

    def test_rejects_non_string_variable_names_on_sync_set(self):
        """Variable keys must be plain strings."""
        ctx = ExecutionContext()

        with pytest.raises(TypeError, match="strings"):
            ctx.set_sync(123, "value")

    def test_set_sync_rejects_legacy_inputs_path_writes(self):
        """Compatibility namespaces do not bypass public write validation."""
        ctx = ExecutionContext()

        with pytest.raises(ValueError, match="path expressions"):
            ctx.set_sync("inputs.name", "Alice")

    @pytest.mark.asyncio
    async def test_update_rejects_invalid_keys_without_partial_write(self):
        """Bulk updates validate all keys before mutating context variables."""
        ctx = ExecutionContext()

        with pytest.raises(ValueError):
            await ctx.update(valid="ok", **{"bad.path": "blocked"})

        assert await ctx.get("valid") is None

        with pytest.raises(ValueError, match="path expressions"):
            await ctx.update(**{"inputs.name": "Alice"})

    @pytest.mark.parametrize(
        "key",
        [
            "workflow_id",
            "run_id",
            "current_step",
            "completed_steps",
            "failed_steps",
            "metadata",
            "services",
            "start_time",
            "checkpoint_dir",
        ],
    )
    def test_protects_lifecycle_fields_from_public_variable_writes(self, key):
        """Variables cannot shadow context identity and lifecycle fields."""
        ctx = ExecutionContext()

        with pytest.raises(ValueError, match="protected"):
            ctx.set_sync(key, "shadow")

        assert key not in ctx.all_variables()

    def test_internal_variable_write_can_seed_protected_keys_explicitly(self):
        """System helpers make protected writes opt-in and easy to audit."""
        ctx = ExecutionContext()

        ctx.set_internal_sync("workflow_id", "shadow")

        assert ctx.get_sync("workflow_id") == "shadow"
        assert ctx.workflow_id != "shadow"


class TestServiceContainer:
    """Tests for ServiceContainer."""

    def test_singleton_registration(self):
        """Test singleton service registration."""
        container = ServiceContainer()

        class MyService:
            pass

        instance = MyService()
        container.register_singleton(MyService, instance)

        resolved = container.resolve(MyService)
        assert resolved is instance

    def test_factory_registration(self):
        """Test factory service registration."""
        container = ServiceContainer()

        class Counter:
            count = 0

            def __init__(self):
                Counter.count += 1

        container.register_factory(Counter, Counter)

        # Each resolve creates new instance
        c1 = container.resolve(Counter)
        c2 = container.resolve(Counter)

        assert c1 is not c2
        assert Counter.count == 2

    def test_resolve_required_raises(self):
        """Test resolve_required raises for missing service."""
        container = ServiceContainer()

        with pytest.raises(KeyError):
            container.resolve_required(str)


# ============================================================================
# StepDefinition Tests
# ============================================================================


class TestStepDefinition:
    """Tests for StepDefinition."""

    def test_fluent_builder(self):
        """Test fluent builder methods."""
        step_def = (
            StepDefinition(name="test")
            .with_timeout(30)
            .with_retry(max_retries=5, strategy=RetryStrategy.EXPONENTIAL)
            .with_dependency("step1", "step2")
            .with_input(code="source_code")
            .with_output(result="step_result")
        )

        assert step_def.timeout_seconds == 30
        assert step_def.retry.max_retries == 5
        assert step_def.depends_on == ["step1", "step2"]
        assert step_def.input_mapping == {"code": "source_code"}
        assert step_def.output_mapping == {"result": "step_result"}

    @pytest.mark.asyncio
    async def test_conditions(self):
        """Test when/unless conditions."""
        ctx = ExecutionContext()
        ctx.set_sync("enabled", True)

        # Step with when condition
        step_def = StepDefinition(
            name="conditional", when=lambda c: c.get_sync("enabled")
        )

        assert step_def.should_run(ctx)

        ctx.set_sync("enabled", False)
        assert not step_def.should_run(ctx)

    def test_step_decorator(self):
        """Test @step decorator."""

        @step("generate", tier=ModelTier.TIER_2, timeout=60)
        async def generate_code(ctx):
            return {"code": "print('hello')"}

        assert isinstance(generate_code, StepDefinition)
        assert generate_code.name == "generate"
        assert generate_code.tier == ModelTier.TIER_2
        assert generate_code.timeout_seconds == 60


class TestStepExecutor:
    """Tests for StepExecutor."""

    @pytest.mark.asyncio
    async def test_basic_execution(self):
        """Test basic step execution."""

        async def simple_step(ctx):
            return {"message": "done"}

        step_def = StepDefinition(name="simple", func=simple_step)
        executor = StepExecutor()
        ctx = ExecutionContext()

        result = await executor.execute(step_def, ctx)

        assert result.is_success
        assert result.output_data["message"] == "done"

    @pytest.mark.asyncio
    async def test_output_mapping(self):
        """Test output mapping to context."""

        async def produce_output(ctx):
            return {"result": 42}

        step_def = StepDefinition(
            name="producer",
            func=produce_output,
        ).with_output(result="final_value")

        executor = StepExecutor()
        ctx = ExecutionContext()

        await executor.execute(step_def, ctx)

        assert await ctx.get("final_value") == 42

    @pytest.mark.asyncio
    async def test_records_resolved_input_data(self):
        """StepResult includes resolved mapped inputs for UI/run logs."""

        async def echo(ctx):
            payload = await ctx.get("code")
            return {"echo": payload}

        step_def = StepDefinition(name="echo", func=echo).with_input(code="source_code")
        executor = StepExecutor()
        ctx = ExecutionContext()
        await ctx.set("source_code", "print('hi')")

        result = await executor.execute(step_def, ctx)

        assert result.is_success
        assert result.input_data == {"code": "print('hi')"}

    @pytest.mark.asyncio
    async def test_synthesizes_review_status_from_raw_response(self):
        """Review steps with raw_response-only output still expose review_report for
        gates."""

        async def reviewer_like_step(ctx):
            return {"raw_response": """```json
{
    \"review_report\": {
        \"overall_assessment\": \"Needs significant changes\"
    }
}
```"""}

        step_def = StepDefinition(
            name="review_code",
            func=reviewer_like_step,
        ).with_output(review_report="code_review")

        executor = StepExecutor()
        ctx = ExecutionContext()

        result = await executor.execute(step_def, ctx)

        assert result.is_success
        assert "review_report" in result.output_data
        assert result.output_data["review_report"]["overall_status"] == "NEEDS_FIXES"
        assert await ctx.get("code_review") is not None

    @pytest.mark.asyncio
    async def test_timeout_handling(self):
        """Test step timeout."""

        async def slow_step(ctx):
            await asyncio.sleep(10)
            return {}

        step_def = StepDefinition(name="slow", func=slow_step, timeout_seconds=0.1)

        executor = StepExecutor()
        ctx = ExecutionContext()

        result = await executor.execute(step_def, ctx)

        assert result.is_failed
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """Test retry behavior."""
        attempts = []

        async def flaky_step(ctx):
            attempts.append(1)
            if len(attempts) < 3:
                raise ValueError("Not ready yet")
            return {"success": True}

        step_def = StepDefinition(
            name="flaky",
            func=flaky_step,
            retry=RetryConfig(max_retries=3, base_delay_seconds=0.01),
        )

        executor = StepExecutor()
        ctx = ExecutionContext()

        result = await executor.execute(step_def, ctx)

        assert result.is_success
        assert len(attempts) == 3
        assert result.retry_count == 2

    @pytest.mark.asyncio
    async def test_skip_on_conditions(self):
        """Test step skipping."""

        async def should_not_run(ctx):
            raise AssertionError("Should not be called")

        step_def = StepDefinition(
            name="skipped", func=should_not_run, when=lambda ctx: False
        )

        executor = StepExecutor()
        ctx = ExecutionContext()

        result = await executor.execute(step_def, ctx)

        assert result.status == StepStatus.SKIPPED


class TestAgentResolverParsing:
    """Regression tests for resilient reviewer-output parsing."""

    def test_parse_malformed_review_response_extracts_status(self):
        """When JSON is malformed, fallback still provides review_report status."""
        response = (
            "```json\n{\n"
            '  "review_report": {\n'
            '    "overall_status": "needs_major_rework",\n'
            '    "summary": "Missing pieces"\n'
            "  }\n"
            # Intentionally malformed/truncated JSON (missing closing brace)
            "```"
        )

        parsed = _parse_llm_json_output(response, ["review_report"])

        assert "review_report" in parsed
        assert parsed["review_report"]["overall_status"] == "NEEDS_MAJOR_REWORK"
        assert "raw_response" in parsed

    def test_parse_unstructured_review_defaults_to_needs_fixes(self):
        """When no status can be extracted, fallback should force rework path."""
        response = "Model returned narrative text, not JSON."

        parsed = _parse_llm_json_output(response, ["review_report"])

        assert parsed["review_report"]["overall_status"] == "NEEDS_FIXES"

    def test_parse_nested_raw_response_review_report(self):
        """Recover review_report when model wraps it under raw_response JSON field."""
        response = (
            '{"raw_response":"```json\\n{\\n  \\"review_report\\": {\\n'
            '    \\"overall_assessment\\": \\"Looks decent but incomplete.\\"\\n'
            '  }\\n}\\n```"}'
        )

        parsed = _parse_llm_json_output(response, ["review_report"])

        assert "review_report" in parsed
        assert parsed["review_report"]["overall_status"] == "NEEDS_FIXES"

    def test_parse_malformed_nested_raw_response_defaults_to_needs_fixes(self):
        """When nested raw_response JSON is truncated, still force non-approved
        status."""
        response = (
            '{"raw_response":"```json\\n{\\n  \\"review_report\\": {\\n'
            '    \\"overall_assessment\\": \\"Good start\\"\\n'
            # Intentionally malformed nested JSON (missing closing braces)
            '```"}'
        )

        parsed = _parse_llm_json_output(response, ["review_report"])

        assert "review_report" in parsed
        assert parsed["review_report"]["overall_status"] == "NEEDS_FIXES"

    def test_parse_malformed_json_salvages_expected_non_review_keys(self):
        """Malformed/truncated JSON should still salvage expected top-level keys.

        This protects workflow handoffs (e.g. fullstack_generation) where
        downstream steps depend on keys like api_spec/db_schema/component_tree.
        """
        response = (
            "```json\n{\n"
            '  "api_spec": {"style": "REST", "version": "v1"},\n'
            '  "db_schema": {"tables": ["users", "repos"]},\n'
            '  "component_tree": {"root": "Dashboard", "children": ["RepoList"]},\n'
            '  "notes": "truncated here"\n'
            # Intentionally malformed/truncated JSON
        )

        parsed = _parse_llm_json_output(
            response,
            ["api_spec", "db_schema", "component_tree"],
        )

        assert "raw_response" in parsed
        assert parsed["api_spec"]["style"] == "REST"
        assert parsed["db_schema"]["tables"] == ["users", "repos"]
        assert parsed["component_tree"]["root"] == "Dashboard"


class TestAgentResolverTooling:
    """Runtime tool-calling behavior for YAML-resolved LLM steps."""

    @pytest.mark.asyncio
    async def test_llm_step_executes_tool_calls(self, monkeypatch):
        """Resolved LLM steps should execute tool calls before final answer."""
        from agentic_v2.models.client import get_client

        class _ToolCallingBackend:
            def __init__(self):
                self.calls = []

            async def complete(self, model, prompt, **kwargs):
                return ""

            async def complete_chat(
                self,
                model,
                messages,
                max_tokens=4096,
                temperature=0.7,
                tools=None,
                **kwargs,
            ):
                self.calls.append(
                    {
                        "model": model,
                        "messages": messages,
                        "tools": tools,
                    }
                )

                if len(self.calls) == 1:
                    return {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "json_dump",
                                    "arguments": '{"data": {"value": 7}, "indent": null}',
                                },
                            }
                        ],
                        "usage": {"total_tokens": 12},
                        "finish_reason": "tool_calls",
                        "model": model,
                    }

                return {
                    "content": (
                        "<<<ARTIFACT result>>>\n"
                        '{"status":"ok","source":"tool"}\n'
                        "<<<ENDARTIFACT>>>"
                    ),
                    "tool_calls": None,
                    "usage": {"total_tokens": 10},
                    "finish_reason": "stop",
                    "model": model,
                }

            async def complete_stream(self, model, prompt, **kwargs):
                yield ""

            def count_tokens(self, text, model):
                return max(1, len(text) // 4)

        client = get_client(auto_configure=False)
        backend = _ToolCallingBackend()
        client.set_backend(backend)
        monkeypatch.setattr(
            client.router,
            "get_model_for_tier",
            lambda _: "openai:gpt-4o-mini",
        )

        step = StepDefinition(
            name="tool_enabled_step",
            description="Use available tools before answering.",
            metadata={"agent": "tier2_coder"},
        ).with_output(result="tooling_output")
        resolve_agent(step)

        result = await StepExecutor().execute(step, ExecutionContext())

        assert result.is_success
        assert result.output_data["result"]["status"] == "ok"
        assert result.output_data["result"]["source"] == "tool"
        assert len(backend.calls) == 2

        first_call_tools = backend.calls[0]["tools"] or []
        tool_names = {t.get("function", {}).get("name") for t in first_call_tools}
        assert "json_dump" in tool_names

        second_messages = backend.calls[1]["messages"]
        assert any(msg.get("role") == "tool" for msg in second_messages)


# ============================================================================
# Pipeline Tests
# ============================================================================


class TestPipeline:
    """Tests for Pipeline."""

    def test_pipeline_builder(self):
        """Test PipelineBuilder fluent API."""

        async def step1(ctx):
            return {}

        async def step2(ctx):
            return {}

        pipeline = (
            PipelineBuilder("test-pipeline")
            .step(StepDefinition(name="s1", func=step1))
            .step(StepDefinition(name="s2", func=step2))
            .with_checkpoints(5)
            .fail_fast(True)
            .tag("test", "example")
            .build()
        )

        assert pipeline.name == "test-pipeline"
        assert len(pipeline.elements) == 2
        assert pipeline.checkpoint_interval == 5
        assert pipeline.fail_fast
        assert "test" in pipeline.tags

    @pytest.mark.asyncio
    async def test_sequential_execution(self):
        """Test sequential pipeline execution."""
        results = []

        async def step_a(ctx):
            results.append("a")
            return {}

        async def step_b(ctx):
            results.append("b")
            return {}

        pipeline = (
            PipelineBuilder("sequential")
            .step(StepDefinition(name="a", func=step_a))
            .step(StepDefinition(name="b", func=step_b))
            .build()
        )

        result = await run_pipeline(pipeline)

        assert result.overall_status == StepStatus.SUCCESS
        assert results == ["a", "b"]

    @pytest.mark.asyncio
    async def test_parallel_execution(self):
        """Test parallel step execution."""
        results = []
        lock = asyncio.Lock()

        async def parallel_step(ctx):
            async with lock:
                results.append(ctx.current_step)
            await asyncio.sleep(0.01)
            return {}

        pipeline = Pipeline(name="parallel-test")
        pipeline.add_parallel(
            StepDefinition(name="p1", func=parallel_step),
            StepDefinition(name="p2", func=parallel_step),
            StepDefinition(name="p3", func=parallel_step),
            name="parallel_group",
        )

        result = await run_pipeline(pipeline)

        assert result.overall_status == StepStatus.SUCCESS
        assert len(result.steps) == 3

    @pytest.mark.asyncio
    async def test_conditional_branching(self):
        """Test conditional branch execution."""
        executed = []

        async def then_step(ctx):
            executed.append("then")
            return {}

        async def else_step(ctx):
            executed.append("else")
            return {}

        ctx = ExecutionContext()
        ctx.set_sync("condition", True)

        pipeline = Pipeline(name="branching")
        pipeline.add_branch(
            condition=lambda c: c.get_sync("condition"),
            then_steps=[StepDefinition(name="then", func=then_step)],
            else_steps=[StepDefinition(name="else", func=else_step)],
        )

        result = await run_pipeline(pipeline, ctx)

        assert executed == ["then"]

        # Test else branch
        executed.clear()
        ctx.set_sync("condition", False)

        result = await run_pipeline(pipeline, ctx)

        assert executed == ["else"]

    @pytest.mark.asyncio
    async def test_fail_fast(self):
        """Test fail-fast behavior."""
        executed = []

        async def failing_step(ctx):
            executed.append("fail")
            raise ValueError("Intentional failure")

        async def after_fail(ctx):
            executed.append("after")
            return {}

        # Disable retry so we only see one failure
        no_retry = RetryConfig(max_retries=0)

        pipeline = (
            PipelineBuilder("fail-fast")
            .step(StepDefinition(name="fail", func=failing_step, retry=no_retry))
            .step(StepDefinition(name="after", func=after_fail))
            .fail_fast(True)
            .build()
        )

        result = await run_pipeline(pipeline)

        assert result.overall_status == StepStatus.FAILED
        assert executed == ["fail"]  # "after" not executed


# ============================================================================
# WorkflowExecutor Tests
# ============================================================================


class TestWorkflowExecutor:
    """Tests for WorkflowExecutor."""

    def setup_method(self):
        reset_executor()

    @pytest.mark.asyncio
    async def test_execute_single_step(self):
        """Test executing a single step."""

        async def my_step(ctx):
            return {"value": 123}

        step_def = StepDefinition(name="single", func=my_step)

        result = await execute(step_def)

        assert result.overall_status == StepStatus.SUCCESS
        assert len(result.steps) == 1

    @pytest.mark.asyncio
    async def test_default_timeout_does_not_mutate_shared_step(self):
        """Re-executing a step must not write the default timeout back onto it.

        Regression for C-02: _execute_step applied the config default timeout by
        mutating the shared StepDefinition in place, so after the first run a
        re-entrant run could no longer tell "caller set no timeout" from
        "default already applied". The definition must stay timeout_seconds=None.
        """

        async def my_step(ctx):
            return {"value": 1}

        step_def = StepDefinition(name="reused", func=my_step, timeout_seconds=None)
        executor = WorkflowExecutor(
            config=ExecutionConfig(step_default_timeout_seconds=42.0)
        )

        await executor.execute(step_def, ExecutionContext())
        assert step_def.timeout_seconds is None  # not mutated by the first run

        await executor.execute(step_def, ExecutionContext())
        assert step_def.timeout_seconds is None  # still pristine after the second run

    @pytest.mark.asyncio
    async def test_execute_step_list(self):
        """Test executing a list of steps."""
        ctx = ExecutionContext()

        async def step1(ctx):
            return {"x": 1}

        async def step2(ctx):
            # Use parent context via step's get
            x = ctx.get_sync("x", 0)  # Read from mapped context
            result = x + 1
            return {"y": result}

        steps = [
            StepDefinition(name="s1", func=step1).with_output(x="x"),
            StepDefinition(name="s2", func=step2).with_output(y="y"),
        ]

        executor = WorkflowExecutor()
        result = await executor.execute(steps, ctx)

        assert result.overall_status == StepStatus.SUCCESS
        assert await ctx.get("y") == 2

    @pytest.mark.asyncio
    async def test_initial_variables(self):
        """Test passing initial variables."""

        async def use_vars(ctx):
            name = await ctx.get("name")
            return {"greeting": f"Hello, {name}!"}

        step_def = StepDefinition(name="greet", func=use_vars)

        result = await execute(step_def, name="World")

        assert result.steps[0].output_data["greeting"] == "Hello, World!"

    @pytest.mark.asyncio
    async def test_global_timeout(self):
        """Test global execution timeout."""

        async def slow_step(ctx):
            await asyncio.sleep(10)
            return {}

        executor = WorkflowExecutor(
            config=ExecutionConfig(
                global_timeout_seconds=0.1,
                step_default_timeout_seconds=60.0,  # Step timeout longer than global
            )
        )

        # Step has no timeout of its own, so global timeout should apply
        result = await executor.execute(
            StepDefinition(name="slow", func=slow_step, timeout_seconds=None)
        )

        assert result.overall_status == StepStatus.FAILED
        # Global timeout cancels the step task, which becomes CancelledError in the step
        # The step catches this and marks itself as cancelled
        step_result = result.steps[0]
        assert (
            step_result.error_type == "CancelledError"
            or "timeout" in step_result.error.lower()
        )

    @pytest.mark.asyncio
    async def test_event_listeners(self):
        """Test executor event listeners."""
        events = []

        def listener(event, data):
            events.append(event.value)

        async def simple_step(ctx):
            return {}

        executor = WorkflowExecutor()
        executor.add_listener(listener)

        await executor.execute(StepDefinition(name="test", func=simple_step))

        assert "workflow_start" in events
        assert "step_start" in events
        assert "step_end" in events
        assert "workflow_end" in events

    @pytest.mark.asyncio
    async def test_execution_history(self):
        """Test execution history tracking."""

        async def my_step(ctx):
            return {}

        executor = WorkflowExecutor()
        await executor.execute(StepDefinition(name="tracked", func=my_step))

        history = executor.history

        assert len(history.entries) > 0
        assert any(e["event"] == "workflow_start" for e in history.entries)
        assert any(e["step"] == "tracked" for e in history.entries)

    @pytest.mark.asyncio
    async def test_run_convenience_function(self):
        """Test run() convenience function."""

        async def my_step(ctx):
            return {"result": "done"}

        step_def = StepDefinition(name="quick", func=my_step)

        result = await run(step_def)

        assert result.is_success
        assert result.output_data["result"] == "done"

    @pytest.mark.asyncio
    async def test_execute_rejects_invalid_context(self):
        """WorkflowExecutor validates ctx before execution side effects."""

        async def noop(ctx):
            return {}

        executor = WorkflowExecutor()
        step_def = StepDefinition(name="noop", func=noop)

        with pytest.raises(TypeError, match="ExecutionContext"):
            await executor.execute(step_def, ctx=object())

        assert executor.current_context is None

    @pytest.mark.asyncio
    async def test_execute_rejects_non_mapping_initial_vars(self):
        """Initial variables must be supplied as a mapping."""

        async def noop(ctx):
            return {}

        executor = WorkflowExecutor()

        with pytest.raises(TypeError, match="initial_vars"):
            await executor.execute(
                StepDefinition(name="noop", func=noop),
                initial_vars=[("x", 1)],
            )

    @pytest.mark.asyncio
    async def test_execute_rejects_unsupported_workflow_shape(self):
        """Unsupported workflow objects fail before lifecycle events."""
        events = []
        executor = WorkflowExecutor()
        executor.add_listener(lambda event, data: events.append(event))

        with pytest.raises(TypeError, match="workflow"):
            await executor.execute({"steps": []})

        assert events == []

    @pytest.mark.asyncio
    async def test_execute_rejects_non_step_items_in_step_lists(self):
        """Sequential step lists must contain only StepDefinition objects."""

        async def noop(ctx):
            return {}

        executor = WorkflowExecutor()

        with pytest.raises(TypeError, match="StepDefinition"):
            await executor.execute([StepDefinition(name="noop", func=noop), "bad"])

    @pytest.mark.asyncio
    async def test_execute_validates_dag_before_workflow_start(self):
        """DAG cycles and missing dependencies fail before runtime execution."""

        async def noop(ctx):
            return {}

        dag = DAG("invalid")
        dag.add(StepDefinition(name="dependent", func=noop).with_dependency("missing"))

        events = []
        executor = WorkflowExecutor()
        executor.add_listener(lambda event, data: events.append(event))

        with pytest.raises(ValueError, match="missing"):
            await executor.execute(dag)

        assert events == []

    @pytest.mark.asyncio
    async def test_execute_validates_pipeline_elements_before_workflow_start(self):
        """Pipeline element shape errors fail before runtime execution."""
        pipeline = Pipeline("invalid")
        pipeline.add("not-a-pipeline-element")

        events = []
        executor = WorkflowExecutor()
        executor.add_listener(lambda event, data: events.append(event))

        with pytest.raises(TypeError, match="Pipeline element"):
            await executor.execute(pipeline)

        assert events == []


# ============================================================================
# RetryConfig Tests
# ============================================================================


class TestRetryConfig:
    """Tests for RetryConfig."""

    def test_exponential_backoff(self):
        """Test exponential backoff delay calculation."""
        config = RetryConfig(
            strategy=RetryStrategy.EXPONENTIAL,
            base_delay_seconds=1.0,
            max_delay_seconds=60.0,
            jitter=0,  # Disable jitter for predictable testing
        )

        assert config.get_delay(1) == 1.0
        assert config.get_delay(2) == 2.0
        assert config.get_delay(3) == 4.0
        assert config.get_delay(4) == 8.0

    def test_linear_backoff(self):
        """Test linear backoff."""
        config = RetryConfig(
            strategy=RetryStrategy.LINEAR, base_delay_seconds=2.0, jitter=0
        )

        assert config.get_delay(1) == 2.0
        assert config.get_delay(2) == 4.0
        assert config.get_delay(3) == 6.0

    def test_max_delay_cap(self):
        """Test max delay cap."""
        config = RetryConfig(
            strategy=RetryStrategy.EXPONENTIAL,
            base_delay_seconds=10.0,
            max_delay_seconds=30.0,
            jitter=0,
        )

        # 10 * 2^5 = 320, but capped at 30
        assert config.get_delay(6) == 30.0

    def test_should_retry(self):
        """Test retry decision."""
        config = RetryConfig(
            retry_on=(ValueError, RuntimeError), no_retry_on=(KeyError,)
        )

        assert config.should_retry(ValueError("test"))
        assert config.should_retry(RuntimeError("test"))
        assert not config.should_retry(KeyError("test"))
        assert not config.should_retry(TypeError("test"))  # Not in retry_on
