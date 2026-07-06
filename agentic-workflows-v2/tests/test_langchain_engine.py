"""Tests for the LangChain workflow engine.

Tests config loading, expression evaluation, and graph compilation
without requiring any API keys (tier-0 only).

# ADR-008 cleanup: removed 5 duplicate tests (see
docs/adr/ADR-008-testing-approach-overhaul.md)
"""

import json
import os
from datetime import datetime

import pytest

from agentic_v2.contracts import StepStatus
from agentic_v2.integrations.base import CanonicalEvent, TraceAdapter
from agentic_v2.integrations.tracing import LangSmithTraceAdapter
from agentic_v2.langchain.config import (
    StepConfig,
    WorkflowConfig,
    list_workflows,
    load_workflow_config,
)
from agentic_v2.langchain.graph import compile_workflow
from agentic_v2.langchain.runner import WorkflowRunner
from agentic_v2.langchain.state import initial_state
from agentic_v2.langchain.tools import get_tools_for_tier, web_search

# ---------------------------------------------------------------------------
# Config loader tests
# ---------------------------------------------------------------------------


class TestConfigLoader:
    """Test YAML config loading.

    Note: test_list_workflows and test_load_nonexistent_raises have been moved
    to tests/test_langchain_config.py during ADR-008 cleanup.
    """

    def test_load_code_review(self):
        config = load_workflow_config("code_review")
        assert config.name == "code_review"
        assert config.version == "1.0"
        assert len(config.steps) >= 3
        assert "code_file" in config.inputs
        assert config.evaluation is not None
        assert len(config.evaluation.criteria) > 0

    def test_step_config_fields(self):
        config = load_workflow_config("code_review")
        parse_step = next(s for s in config.steps if s.name == "parse_code")
        assert parse_step.agent == "tier0_parser"
        assert "file_path" in parse_step.inputs

    def test_step_dependencies(self):
        config = load_workflow_config("code_review")
        review_step = next(s for s in config.steps if s.name == "review_code")
        assert "style_check" in review_step.depends_on
        assert "complexity_analysis" in review_step.depends_on

    def test_conditional_step(self):
        config = load_workflow_config("code_review")
        summary_step = next(s for s in config.steps if s.name == "generate_summary")
        assert summary_step.when is not None
        assert "review_depth" in summary_step.when

    def test_capabilities_parsed(self):
        config = load_workflow_config("code_review")
        assert "inputs" in config.capabilities
        assert "code_file" in config.capabilities["inputs"]

    def test_evaluation_criteria(self):
        config = load_workflow_config("code_review")
        assert config.evaluation is not None
        criteria_names = [c.name for c in config.evaluation.criteria]
        assert "correctness_rubric" in criteria_names
        assert "code_quality" in criteria_names

    def test_compile_validate_only_all_runnable_workflows(self):
        """All runnable workflow definitions should compile in validate_only mode."""
        workflows = list_workflows()
        assert workflows, "Expected at least one runnable workflow definition"

        for name in workflows:
            config = load_workflow_config(name)
            graph = compile_workflow(config, validate_only=True)
            assert graph is not None


class TestLangChainTooling:
    """Tooling registry tests for LangChain-native tools."""

    def test_tier2_includes_web_search(self):
        tools = get_tools_for_tier(2)
        names = {tool.name for tool in tools}
        assert "web_search" in names
        assert "http_get" in names

    def test_web_search_applies_allowlist(self, monkeypatch):
        class _Resp:
            def __init__(self, text):
                self.text = text

        html = """
        <a class="result__a" href="https://openai.com/research">OpenAI</a>
        <a class="result__snippet">openai snippet</a>
        <a class="result__a" href="https://example.org/post">Example</a>
        <a class="result__snippet">example snippet</a>
        """

        # Patch the guard helper directly: it owns transport details (client
        # reuse, SSRF validation, IP pinning), keeping this test offline and
        # focused on the domain-filter behavior.
        monkeypatch.setattr(
            "agentic_v2.langchain.tools._http_get_with_redirect_guard",
            lambda url, **kwargs: _Resp(html),
        )

        raw = web_search.invoke(
            {
                "query": "test",
                "max_results": 5,
                "allowed_domains": ["openai.com"],
            }
        )
        payload = json.loads(raw)
        assert len(payload["results"]) == 1
        assert payload["results"][0]["domain"] == "openai.com"
        assert payload["filters"]["allowed_domains"] == ["openai.com"]

    def test_web_search_applies_blocklist(self, monkeypatch):
        class _Resp:
            def __init__(self, text):
                self.text = text

        html = """
        <a class="result__a" href="https://openai.com/research">OpenAI</a>
        <a class="result__snippet">openai snippet</a>
        <a class="result__a" href="https://example.org/post">Example</a>
        <a class="result__snippet">example snippet</a>
        """

        monkeypatch.setattr(
            "agentic_v2.langchain.tools._http_get_with_redirect_guard",
            lambda url, **kwargs: _Resp(html),
        )

        raw = web_search.invoke(
            {
                "query": "test",
                "max_results": 5,
                "blocked_domains": ["openai.com"],
            }
        )
        payload = json.loads(raw)
        assert len(payload["results"]) == 1
        assert payload["results"][0]["domain"] == "example.org"
        assert payload["filters"]["blocked_domains"] == ["openai.com"]


class TestPerStepModelOverride:
    """Per-step model override behavior tests."""

    def test_parse_step_model_override(self):
        from agentic_v2.langchain.config import _parse

        data = {
            "name": "wf_model_override",
            "steps": [
                {
                    "name": "s1",
                    "agent": "tier2_researcher",
                    "model_override": "gh:openai/gpt-4o-mini",
                },
                {
                    "name": "s2",
                    "agent": "tier2_researcher",
                    "model": "gh:openai/gpt-4o",
                },
            ],
        }
        config = _parse(data, "wf_model_override")
        assert config.steps[0].model_override == "gh:openai/gpt-4o-mini"
        assert config.steps[1].model_override == "gh:openai/gpt-4o"

    async def test_step_model_override_is_passed_to_agent_factory(self, monkeypatch):
        from langchain_core.messages import AIMessage

        from agentic_v2.langchain import graph as graph_module

        captured = {}

        class _DummyAgent:
            def invoke(self, payload):
                return {"messages": [AIMessage(content='{"report":"ok"}')]}

        def _fake_create_agent(
            agent_name,
            *,
            tool_names=None,
            prompt_file=None,
            model_override=None,
        ):
            captured["agent_name"] = agent_name
            captured["model_override"] = model_override
            return _DummyAgent()

        monkeypatch.setattr(graph_module, "create_agent", _fake_create_agent)

        step = StepConfig(
            name="llm_step",
            agent="tier2_researcher",
            model_override="gh:openai/gpt-4o-mini",
            outputs={"report": "report_ctx"},
        )
        workflow = WorkflowConfig(name="wf", steps=[step])
        node = graph_module._make_step_node(step, workflow)
        state = {
            "inputs": {},
            "context": {},
            "steps": {},
            "messages": [],
            "errors": [],
            "outputs": {},
            "current_step": "",
        }
        pending = node(state)
        assert isinstance(pending, dict)
        result = await pending

        assert captured["agent_name"] == "tier2_researcher"
        assert captured["model_override"] == "gh:openai/gpt-4o-mini"
        assert result["context"]["report_ctx"] == "ok"


# ---------------------------------------------------------------------------
# Expression evaluator tests
# ---------------------------------------------------------------------------


# TestExpressions, TestCoalesceExpression, and TestCompositeExpressions
# have been moved to tests/test_langchain_expressions.py during ADR-008 cleanup.


# ---------------------------------------------------------------------------
# State tests
# ---------------------------------------------------------------------------


class TestState:
    """Test state creation."""

    def test_initial_state(self):
        state = initial_state(workflow_inputs={"code_file": "test.py"})
        assert state["inputs"]["code_file"] == "test.py"
        assert state["messages"] == []
        assert state["errors"] == []
        assert state["steps"] == {}

    def test_initial_state_defaults(self):
        state = initial_state()
        assert state["inputs"] == {}
        assert state["context"] == {}


# ---------------------------------------------------------------------------
# Graph compilation tests (tier-0 only, no API keys)
# ---------------------------------------------------------------------------


class TestGraphCompilation:
    """Test graph compilation from config."""

    @pytest.mark.skipif(
        not os.environ.get("OPENAI_API_KEY"),
        reason="Requires OPENAI_API_KEY to instantiate LLM agents",
    )
    def test_compile_code_review(self):
        """Verify the code_review workflow compiles without errors."""
        config = load_workflow_config("code_review")
        graph = compile_workflow(config)
        assert graph is not None

    def test_empty_workflow_raises(self):
        config = WorkflowConfig(name="empty", steps=[])
        with pytest.raises(ValueError, match="no steps"):
            compile_workflow(config)

    def test_missing_dependency_raises(self):
        config = WorkflowConfig(
            name="bad_deps",
            steps=[
                StepConfig(
                    name="step1",
                    agent="tier0_parser",
                    depends_on=["nonexistent"],
                ),
            ],
        )
        with pytest.raises(ValueError, match="unknown step"):
            compile_workflow(config)

    def test_tier0_only_workflow_runs(self):
        """A workflow with only tier-0 steps should execute end-to-end."""
        config = WorkflowConfig(
            name="test_tier0",
            steps=[
                StepConfig(
                    name="parse",
                    agent="tier0_parser",
                    inputs={"file_path": "${inputs.code_file}"},
                    outputs={"parsed_ast": "ast_result"},
                ),
            ],
            inputs={},
        )
        graph = compile_workflow(config)
        state = initial_state(workflow_inputs={"code_file": "nonexistent.py"})
        state["context"]["inputs"] = state["inputs"]
        result = graph.invoke(state)
        assert "parse" in result["steps"]
        assert result["steps"]["parse"]["status"] == "success"

    def test_test_deterministic_workflow_produces_outputs(self):
        """The first-run deterministic workflow should return stable demo outputs."""
        config = load_workflow_config("test_deterministic")
        graph = compile_workflow(config)

        state = initial_state(workflow_inputs={"input_text": "Hello World"})
        state["context"]["inputs"] = {"input_text": "Hello World"}
        state["context"]["workflow_run_id"] = "deterministic-smoke"

        final_state = graph.invoke(state)
        outputs = WorkflowRunner.resolve_outputs(config, final_state)

        assert outputs == {
            "processed_text": "Hello World",
            "step_count": 11,
        }
        assert final_state["steps"]["step1"]["outputs"] == {"result": "Hello World"}
        assert final_state["steps"]["step2"]["outputs"] == {"count": 11}


class TestWorkflowRunner:
    """Test WorkflowRunner integration points for LangGraph runtime config."""

    def test_get_or_compile_passes_checkpointer(self):
        captured = {}

        def _fake_compile(config, checkpointer=None, **kwargs):
            captured["checkpointer"] = checkpointer
            return object()

        config = WorkflowConfig(
            name="wf_checkpointer",
            steps=[StepConfig(name="parse", agent="tier0_parser")],
        )
        checkpointer = object()
        runner = WorkflowRunner(checkpointer=checkpointer)

        from agentic_v2.langchain import runner as runner_module

        original_compile = runner_module.compile_workflow
        runner_module.compile_workflow = _fake_compile
        try:
            runner._get_or_compile(config, use_cache=False)
        finally:
            runner_module.compile_workflow = original_compile

        assert captured["checkpointer"] is checkpointer

    def test_invoke_passes_thread_id_in_config(self):
        class _DummyGraph:
            def __init__(self):
                self.config = None

            def invoke(self, state, config=None):
                self.config = config
                return {
                    "steps": {},
                    "errors": [],
                    "context": state.get("context", {}),
                }

        dummy_graph = _DummyGraph()
        runner = WorkflowRunner()

        config = WorkflowConfig(name="wf_thread", steps=[])

        from agentic_v2.langchain import runner as runner_module

        original_loader = runner_module.load_workflow_config
        original_compiler = runner_module.compile_workflow
        runner_module.load_workflow_config = lambda *_args, **_kwargs: config
        runner_module.compile_workflow = lambda *_args, **_kwargs: dummy_graph
        try:
            result = runner.invoke("wf_thread", thread_id="thread-123")
        finally:
            runner_module.load_workflow_config = original_loader
            runner_module.compile_workflow = original_compiler

        assert result.overall_status == StepStatus.SUCCESS
        assert dummy_graph.config is not None
        assert (
            dummy_graph.config.get("configurable", {}).get("thread_id") == "thread-123"
        )

    def test_invoke_uses_run_id_for_checkpoint_thread_when_missing(self):
        class _DummyGraph:
            def __init__(self):
                self.config = None

            def invoke(self, state, config=None):
                self.config = config
                return {
                    "steps": {},
                    "errors": [],
                    "context": state.get("context", {}),
                }

        dummy_graph = _DummyGraph()
        runner = WorkflowRunner(checkpointer=object())
        config = WorkflowConfig(name="wf_generated_thread", steps=[])

        from agentic_v2.langchain import runner as runner_module

        original_loader = runner_module.load_workflow_config
        original_compiler = runner_module.compile_workflow
        runner_module.load_workflow_config = lambda *_args, **_kwargs: config
        runner_module.compile_workflow = lambda *_args, **_kwargs: dummy_graph
        try:
            result = runner.invoke("wf_generated_thread")
        finally:
            runner_module.load_workflow_config = original_loader
            runner_module.compile_workflow = original_compiler

        assert result.overall_status == StepStatus.SUCCESS
        assert dummy_graph.config is not None
        assert (
            dummy_graph.config.get("configurable", {}).get("thread_id") == result.run_id
        )

    def test_invoke_fails_fast_when_graph_rejects_config(self):
        """langgraph>=1.2 always accepts config=; a graph that doesn't is a bug.

        The old TypeError shim (pre-langgraph-1.2) has been removed.  If a
        non-compliant graph raises TypeError on the config= kwarg, it propagates
        through the outer ``except Exception`` handler and surfaces as a FAILED
        WorkflowResult — fail-fast is the correct behaviour.
        """

        class _NonCompliantGraph:
            def invoke(self, state):  # no config= kwarg → TypeError at call site
                return {
                    "steps": {},
                    "errors": [],
                    "context": state.get("context", {}),
                }

        runner = WorkflowRunner()
        config = WorkflowConfig(name="wf_noncomp", steps=[])

        from agentic_v2.langchain import runner as runner_module

        original_loader = runner_module.load_workflow_config
        original_compiler = runner_module.compile_workflow
        runner_module.load_workflow_config = lambda *_args, **_kwargs: config
        runner_module.compile_workflow = lambda *_args, **_kwargs: _NonCompliantGraph()
        try:
            result = runner.invoke("wf_noncomp", thread_id="t1")
        finally:
            runner_module.load_workflow_config = original_loader
            runner_module.compile_workflow = original_compiler

        # Fail-fast: a graph that rejects config= returns a failed result, not success.
        assert result.overall_status == StepStatus.FAILED

    def test_stream_passes_thread_id_in_config(self):
        class _StreamingGraph:
            def __init__(self):
                self.config = None

            def stream(self, state, config=None):
                self.config = config
                yield {"event": "step_start", "state": state.get("current_step", "")}

        streaming_graph = _StreamingGraph()
        runner = WorkflowRunner()
        config = WorkflowConfig(name="wf_stream", steps=[])

        from agentic_v2.langchain import runner as runner_module

        original_loader = runner_module.load_workflow_config
        original_compiler = runner_module.compile_workflow
        runner_module.load_workflow_config = lambda *_args, **_kwargs: config
        runner_module.compile_workflow = lambda *_args, **_kwargs: streaming_graph
        try:
            events = list(runner.stream("wf_stream", thread_id="stream-thread"))
        finally:
            runner_module.load_workflow_config = original_loader
            runner_module.compile_workflow = original_compiler

        assert len(events) == 1
        assert streaming_graph.config is not None
        assert (
            streaming_graph.config.get("configurable", {}).get("thread_id")
            == "stream-thread"
        )

    def test_invoke_emits_trace_events(self):
        class _TraceCollector(TraceAdapter):
            def __init__(self):
                self.events = []

            def emit(self, event):
                self.events.append(event)

        class _DummyGraph:
            def invoke(self, state, config=None):
                return {
                    "steps": {"s": {"status": "success", "outputs": {}}},
                    "errors": [],
                    "context": state.get("context", {}),
                }

        trace = _TraceCollector()
        runner = WorkflowRunner(trace_adapter=trace)
        config = WorkflowConfig(name="wf_trace", steps=[])

        from agentic_v2.langchain import runner as runner_module

        original_loader = runner_module.load_workflow_config
        original_compiler = runner_module.compile_workflow
        runner_module.load_workflow_config = lambda *_args, **_kwargs: config
        runner_module.compile_workflow = lambda *_args, **_kwargs: _DummyGraph()
        try:
            result = runner.invoke("wf_trace")
        finally:
            runner_module.load_workflow_config = original_loader
            runner_module.compile_workflow = original_compiler

        assert result.overall_status == StepStatus.SUCCESS
        assert len(trace.events) >= 2
        assert trace.events[0].type == "workflow_start"
        assert trace.events[-1].type == "workflow_end"

    def test_get_checkpoint_state_reads_snapshot(self):
        class _Snapshot:
            values = {"foo": "bar"}
            next = ("step_b",)
            metadata = {"checkpoint_id": "cp-1"}
            created_at = "2026-02-16T00:00:00Z"

        class _GraphWithState:
            def get_state(self, config=None):
                return _Snapshot()

        runner = WorkflowRunner(checkpointer=object())
        config = WorkflowConfig(name="wf_state", steps=[])

        from agentic_v2.langchain import runner as runner_module

        original_loader = runner_module.load_workflow_config
        original_compiler = runner_module.compile_workflow
        runner_module.load_workflow_config = lambda *_args, **_kwargs: config
        runner_module.compile_workflow = lambda *_args, **_kwargs: _GraphWithState()
        try:
            snapshot = runner.get_checkpoint_state("wf_state", thread_id="t-1")
        finally:
            runner_module.load_workflow_config = original_loader
            runner_module.compile_workflow = original_compiler

        assert snapshot is not None
        assert snapshot["values"]["foo"] == "bar"
        assert snapshot["next"] == ["step_b"]

    def test_get_checkpoint_history_limit(self):
        class _Snapshot:
            def __init__(self, i):
                self.values = {"i": i}
                self.next = ()
                self.metadata = {"checkpoint_id": f"cp-{i}"}
                self.created_at = "2026-02-16T00:00:00Z"

        class _GraphWithHistory:
            def get_state_history(self, config=None):
                for i in range(10):
                    yield _Snapshot(i)

        runner = WorkflowRunner(checkpointer=object())
        config = WorkflowConfig(name="wf_hist", steps=[])

        from agentic_v2.langchain import runner as runner_module

        original_loader = runner_module.load_workflow_config
        original_compiler = runner_module.compile_workflow
        runner_module.load_workflow_config = lambda *_args, **_kwargs: config
        runner_module.compile_workflow = lambda *_args, **_kwargs: _GraphWithHistory()
        try:
            history = runner.get_checkpoint_history("wf_hist", thread_id="t-1", limit=3)
        finally:
            runner_module.load_workflow_config = original_loader
            runner_module.compile_workflow = original_compiler

        assert len(history) == 3
        assert history[0]["values"]["i"] == 0

    def test_resume_uses_thread_checkpoint(self):
        class _ResumeGraph:
            def __init__(self):
                self.invoked_with = None
                self.config = None

            def invoke(self, state, config=None):
                self.invoked_with = state
                self.config = config
                return {
                    "steps": {"resume": {"status": "success", "outputs": {}}},
                    "errors": [],
                    "context": {"ok": True},
                }

        graph = _ResumeGraph()
        runner = WorkflowRunner(checkpointer=object())
        config = WorkflowConfig(name="wf_resume", steps=[])

        from agentic_v2.langchain import runner as runner_module

        original_loader = runner_module.load_workflow_config
        original_compiler = runner_module.compile_workflow
        runner_module.load_workflow_config = lambda *_args, **_kwargs: config
        runner_module.compile_workflow = lambda *_args, **_kwargs: graph
        try:
            result = runner.resume("wf_resume", thread_id="thread-resume")
        finally:
            runner_module.load_workflow_config = original_loader
            runner_module.compile_workflow = original_compiler

        assert result.overall_status == StepStatus.SUCCESS
        assert graph.invoked_with is None
        assert graph.config is not None
        assert graph.config.get("configurable", {}).get("thread_id") == "thread-resume"


class TestLangSmithTracing:
    """LangSmith adapter behavior tests (without network)."""

    def test_langsmith_adapter_wires_parent_child_runs(self):
        class _FakeClient:
            def __init__(self):
                self.created = []
                self.updated = []

            def create_run(self, **kwargs):
                self.created.append(kwargs)

            def update_run(self, run_id, **kwargs):
                self.updated.append((run_id, kwargs))

        client = _FakeClient()
        adapter = LangSmithTraceAdapter(client=client, project_name="test-project")

        adapter.emit(
            CanonicalEvent(
                type="workflow_start",
                timestamp=datetime.now(),
                data={"workflow_name": "wf", "run_id": "run-1", "inputs": {"a": 1}},
            )
        )
        adapter.emit(
            CanonicalEvent(
                type="step_start",
                timestamp=datetime.now(),
                step_name="step-a",
                data={"run_id": "run-1", "inputs": {"x": 1}},
            )
        )
        adapter.emit(
            CanonicalEvent(
                type="workflow_end",
                timestamp=datetime.now(),
                data={
                    "workflow_name": "wf",
                    "run_id": "run-1",
                    "status": "success",
                    "outputs": {"ok": True},
                },
            )
        )

        assert len(client.created) >= 2
        # Root workflow run + child step run
        root_run = client.created[0]
        child_run = client.created[1]
        assert root_run["run_type"] == "chain"
        assert child_run["run_type"] == "tool"
        assert "parent_run_id" in child_run
        assert len(client.updated) == 1


# ---------------------------------------------------------------------------
# Phase 1 fix tests
# ---------------------------------------------------------------------------


class TestConfigParserNonStringInputs:
    """Tests that config parser preserves non-string input values."""

    def test_dict_input_preserved(self):
        from agentic_v2.langchain.config import _parse

        data = {
            "name": "test_wf",
            "steps": [
                {
                    "name": "step_a",
                    "agent": "tier0_parser",
                    "inputs": {
                        "simple": "${inputs.code_file}",
                        "composite": {
                            "backend": "${steps.x.outputs.code}",
                            "frontend": "${steps.y.outputs.ui}",
                        },
                    },
                }
            ],
        }
        config = _parse(data, "test_wf")
        assert "simple" in config.steps[0].inputs
        assert "composite" in config.steps[0].inputs
        assert isinstance(config.steps[0].inputs["composite"], dict)


class TestLoopIterationCounter:
    """Tests that loop iteration is tracked correctly in step data."""

    def test_tier0_node_increments_iteration(self):
        """Running a tier-0 step twice should show loop_iteration=2 on second call."""
        from agentic_v2.langchain.config import StepConfig, WorkflowConfig
        from agentic_v2.langchain.graph import compile_workflow

        config = WorkflowConfig(
            name="loop_test",
            steps=[
                StepConfig(
                    name="parse",
                    agent="tier0_parser",
                    depends_on=[],
                    loop_until="${steps.parse.outputs.done}",
                    loop_max=3,
                )
            ],
        )
        # Just verify the graph compiles and loop edge wiring doesn't crash
        g = compile_workflow(config)
        assert g is not None

    def test_loop_max_expression_uses_runtime_input(self):
        """Runtime inputs override the parsed loop_max fallback."""
        from agentic_v2.langchain.graph_wiring import resolve_loop_max

        step = StepConfig(
            name="review_loop",
            agent="tier2_reviewer",
            loop_max=2,
            loop_max_expr="${inputs.max_review_rounds}",
        )
        state = initial_state(workflow_inputs={"max_review_rounds": 5})

        assert resolve_loop_max(step, state) == 5


class TestConditionalFanOut:
    """Tests that unconditional siblings are not dropped when conditional edges
    exist."""

    def _make_config(self, cond_true: bool) -> WorkflowConfig:
        from agentic_v2.langchain.config import InputConfig, StepConfig, WorkflowConfig

        return WorkflowConfig(
            name="fanout_test",
            inputs={"flag": InputConfig(name="flag", default="yes", required=False)},
            steps=[
                StepConfig(name="root", agent="tier0_parser", depends_on=[]),
                StepConfig(name="always", agent="tier0_parser", depends_on=["root"]),
                StepConfig(
                    name="conditional",
                    agent="tier0_parser",
                    depends_on=["root"],
                    when=(
                        "${inputs.flag} == 'yes'"
                        if cond_true
                        else "${inputs.flag} == 'no'"
                    ),
                ),
            ],
        )

    def test_unconditional_sibling_always_runs(self):
        """The 'always' step must execute even when a conditional sibling exists."""
        config = self._make_config(cond_true=False)
        g = compile_workflow(config)
        state = {
            "inputs": {"flag": "no"},
            "context": {"inputs": {"flag": "no"}},
            "steps": {},
            "messages": [],
            "errors": [],
            "outputs": {},
            "current_step": "",
        }
        result = g.invoke(state)
        assert "always" in result["steps"]
        assert result["steps"]["always"]["status"] == "success"

    def test_conditional_step_runs_when_condition_true(self):
        """The 'conditional' step must execute when its when-expression is true."""
        config = self._make_config(cond_true=True)
        g = compile_workflow(config)
        state = {
            "inputs": {"flag": "yes"},
            "context": {"inputs": {"flag": "yes"}},
            "steps": {},
            "messages": [],
            "errors": [],
            "outputs": {},
            "current_step": "",
        }
        result = g.invoke(state)
        assert "always" in result["steps"]
        assert "conditional" in result["steps"]

    def test_self_skipped_conditional_allows_downstream_join(self):
        """A self-skipped conditional node should still allow join dependents to run."""
        from agentic_v2.langchain.config import InputConfig, StepConfig, WorkflowConfig

        config = WorkflowConfig(
            name="skip_propagation_join",
            inputs={"flag": InputConfig(name="flag", default="no", required=False)},
            steps=[
                StepConfig(name="root", agent="tier0_parser", depends_on=[]),
                StepConfig(name="always", agent="tier0_parser", depends_on=["root"]),
                StepConfig(
                    name="conditional",
                    agent="tier0_parser",
                    depends_on=["root"],
                    when="${inputs.flag} == 'yes'",
                ),
                StepConfig(
                    name="join_step",
                    agent="tier0_parser",
                    depends_on=["always", "conditional"],
                ),
            ],
        )

        graph = compile_workflow(config)
        state = {
            "inputs": {"flag": "no"},
            "context": {"inputs": {"flag": "no"}},
            "steps": {},
            "messages": [],
            "errors": [],
            "outputs": {},
            "current_step": "",
        }
        result = graph.invoke(state)

        assert result["steps"]["conditional"]["status"] == "skipped"
        assert "join_step" in result["steps"]
        assert result["steps"]["join_step"]["status"] == "success"


# ---------------------------------------------------------------------------
# Phase 2: Model provider tests
# ---------------------------------------------------------------------------


class TestModelRegistry:
    """Tests for model provider registry."""

    def test_unsupported_provider_raises(self):
        from agentic_v2.langchain.models import get_chat_model

        with pytest.raises(ValueError, match="Unsupported model provider"):
            get_chat_model("azure:some-model")

    def test_gh_prefix_requires_github_token(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        from agentic_v2.langchain.models import get_chat_model

        with pytest.raises((ValueError, ImportError)):
            get_chat_model("gh:openai/gpt-4o-mini")

    def test_gh_prefix_builds_openai_with_token(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
        from agentic_v2.langchain.models import get_chat_model

        try:
            model = get_chat_model("gh:openai/gpt-4o-mini")
            assert model is not None
            # Model name should be the part after gh:
            assert "gpt-4o-mini" in str(model.model_name)
        except ImportError:
            pytest.skip("langchain-openai not installed")

    def test_ollama_prefix_builds_ollama_model(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
        from agentic_v2.langchain.models import get_chat_model

        try:
            model = get_chat_model("ollama:qwen2.5-coder")
            assert model is not None
        except ImportError:
            pytest.skip("langchain-ollama not installed")

    def test_bare_name_treated_as_ollama(self, monkeypatch):
        from agentic_v2.langchain.models import get_chat_model

        try:
            model = get_chat_model("llama3.2")
            assert model is not None
        except ImportError:
            pytest.skip("langchain-ollama not installed")

    def test_openai_prefix_requires_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from agentic_v2.langchain.models import get_chat_model

        with pytest.raises((ValueError, ImportError)):
            get_chat_model("openai:gpt-4o-mini")

    def test_openai_prefix_builds_model(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")
        from agentic_v2.langchain.models import get_chat_model

        try:
            model = get_chat_model("openai:gpt-4o-mini")
            assert model is not None
            assert "gpt-4o-mini" in str(model.model_name)
        except ImportError:
            pytest.skip("langchain-openai not installed")

    def test_anthropic_prefix_requires_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from agentic_v2.langchain.models import get_chat_model

        with pytest.raises((ValueError, ImportError)):
            get_chat_model("anthropic:claude-3-5-sonnet-latest")

    def test_claude_alias_prefix(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-anthropic-key")
        from agentic_v2.langchain.models import get_chat_model

        try:
            model = get_chat_model("claude:claude-3-5-sonnet-latest")
            assert model is not None
        except ImportError:
            pytest.skip("langchain-anthropic not installed")

    @pytest.mark.slow
    def test_gemini_prefix_requires_key(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        from agentic_v2.langchain.models import get_chat_model

        with pytest.raises((ValueError, ImportError)):
            get_chat_model("gemini:gemini-2.5-pro")

    def test_notebooklm_alias_model_resolution(self, monkeypatch):
        monkeypatch.delenv("NOTEBOOKLM_MODEL", raising=False)
        monkeypatch.delenv("NOTEBOOKLM_GEMINI_MODEL", raising=False)
        from agentic_v2.langchain.models import _resolve_notebooklm_model_name

        assert _resolve_notebooklm_model_name("") == "gemini-2.5-pro"

        monkeypatch.setenv("NOTEBOOKLM_MODEL", "gemini-2.5-flash")
        assert _resolve_notebooklm_model_name("") == "gemini-2.5-flash"

        # Explicit suffix takes precedence over env.
        assert _resolve_notebooklm_model_name("gemini-2.0-pro") == "gemini-2.0-pro"

    def test_local_onnx_prefix_builds_wrapper(self):
        from agentic_v2.langchain.models import get_chat_model

        model = get_chat_model("local:phi4mini")
        assert model is not None
        assert model._llm_type == "local-onnx"

    def test_model_candidates_include_gh_backup_with_token(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
        from agentic_v2.langchain.models import get_model_candidates_for_tier

        candidates = get_model_candidates_for_tier(3)
        assert "gh:openai/gpt-4o-mini" in candidates


class TestGraphResponseParsing:
    """Regression tests for provider-specific response parsing."""

    def test_extract_agent_response_text_handles_content_list(self):
        from langchain_core.messages import AIMessage

        from agentic_v2.langchain import graph as graph_module

        payload = {
            "messages": [
                AIMessage(
                    content=[
                        {
                            "type": "text",
                            "text": '```json\n{"scoped_goal":"ok"}\n```',
                        }
                    ]
                )
            ]
        }

        text = graph_module._extract_agent_response_text(payload)
        assert isinstance(text, str)
        assert '"scoped_goal":"ok"' in text

    def test_parse_step_outputs_extracts_fenced_json(self):
        from agentic_v2.langchain import graph as graph_module

        parsed = graph_module._parse_step_outputs(
            '```json\n{"executive_summary":"s","references":["a"]}\n```'
        )
        assert parsed["executive_summary"] == "s"
        assert parsed["references"] == ["a"]

    def test_parse_step_outputs_tolerates_control_chars_in_fenced_json(self):
        """Fenced JSON with literal newlines inside string values must parse.

        Regression: gemini-2.5-flash emitted a well-formed fenced JSON
        architecture payload whose string values contained bare newlines.
        Strict json.loads rejects those ("Invalid control character"), which
        left only raw_response populated and nulled every downstream
        ``${steps.design_architecture.outputs.*}`` reference.
        """
        from agentic_v2.langchain import graph as graph_module

        response = (
            '```json\n{\n  "api_design": {"style": "REST"},\n'
            '  "database_schema": "CREATE TABLE todos (\n    id SERIAL\n  );"\n}\n```'
        )
        parsed = graph_module._parse_step_outputs(
            response,
            expected_output_keys=["api_design", "database_schema"],
        )
        assert parsed["api_design"] == {"style": "REST"}
        assert "CREATE TABLE todos" in parsed["database_schema"]

    def test_parse_step_outputs_extracts_sentinel_artifacts(self):
        """<<<ARTIFACT>>> blocks (coder.md prompt format) map to declared keys.

        Regression: the langchain path only attempted JSON extraction, so
        coder-agent responses using the sentinel protocol produced
        raw_response-only outputs and downstream steps received nulls. The
        native engine already parsed these via parse_sentinel_output.
        """
        from agentic_v2.langchain import graph as graph_module

        response = (
            "<<<ARTIFACT backend_code>>>\n"
            "FILE: src/main.py\n"
            "print('hi')\n"
            "ENDFILE\n"
            "<<<ENDARTIFACT>>>"
        )
        parsed = graph_module._parse_step_outputs(
            response, expected_output_keys=["backend_code"]
        )
        assert "FILE: src/main.py" in parsed["backend_code"]
        assert parsed["backend_code_files"] == {"src/main.py": "print('hi')\n"}

    def test_parse_step_outputs_salvages_expected_keys_from_truncated_json(self):
        """Declared keys are salvaged individually from truncated JSON."""
        from agentic_v2.langchain import graph as graph_module

        truncated = (
            '{"api_spec": {"endpoints": ["GET /todos"]}, "db_schema": "CREATE TAB'
        )
        parsed = graph_module._parse_step_outputs(
            truncated, expected_output_keys=["api_spec", "db_schema"]
        )
        assert parsed["api_spec"] == {"endpoints": ["GET /todos"]}
        assert "db_schema" not in parsed  # unparseable value stays absent

    def test_parse_json_dict_from_text_midtext_fence_with_braces_in_prose(self):
        """Prose containing braces around a fenced payload still parses."""
        from agentic_v2.langchain import graph as graph_module

        text = 'Context {unbalanced.\n```json\n{"key": "value"}\n```\nDone.'
        assert graph_module._parse_json_dict_from_text(text) == {"key": "value"}

    def test_parse_step_outputs_prose_only_warns_on_missing_declared_keys(self, caplog):
        """Non-JSON prose keeps raw_response only and warns about missing keys."""
        import logging

        from agentic_v2.langchain import graph as graph_module

        with caplog.at_level(
            logging.WARNING, logger="agentic_v2.langchain.graph_wiring"
        ):
            parsed = graph_module._parse_step_outputs(
                "I need a value for the `schema` argument.",
                expected_output_keys=["migrations"],
            )
        assert set(parsed.keys()) == {"raw_response"}
        assert any("migrations" in rec.message for rec in caplog.records)

    async def test_llm_step_maps_outputs_when_model_emits_control_chars(
        self, monkeypatch
    ):
        """End-to-end node: control-char fenced JSON still maps to context."""
        from langchain_core.messages import AIMessage

        from agentic_v2.langchain import graph as graph_module

        class _DummyAgent:
            def invoke(self, payload):
                return {
                    "messages": [
                        AIMessage(
                            content='```json\n{"api_design": "GET /todos\nPOST /todos"}\n```'
                        )
                    ]
                }

        def _fake_create_agent(*args, **kwargs):
            return _DummyAgent()

        monkeypatch.setattr(graph_module, "create_agent", _fake_create_agent)

        step = StepConfig(
            name="design_architecture",
            agent="tier3_architect",
            description="test",
            outputs={"api_design": "api_design"},
        )
        wf = WorkflowConfig(name="wf_ctrl_chars", steps=[step])
        node = graph_module._make_step_node(step, wf)
        state = initial_state(workflow_inputs={})
        state["context"]["inputs"] = {}

        updated = await node(state)
        assert (
            updated["steps"]["design_architecture"]["outputs"]["api_design"]
            == "GET /todos\nPOST /todos"
        )
        assert updated["context"]["api_design"] == "GET /todos\nPOST /todos"

    async def test_llm_step_maps_outputs_from_list_content(self, monkeypatch):
        from langchain_core.messages import AIMessage

        from agentic_v2.langchain import graph as graph_module

        class _DummyAgent:
            def invoke(self, payload):
                return {
                    "messages": [
                        AIMessage(
                            content=[
                                {
                                    "type": "text",
                                    "text": '```json\n{"scoped_goal":"mapped"}\n```',
                                }
                            ]
                        )
                    ]
                }

        def _fake_create_agent(*args, **kwargs):
            return _DummyAgent()

        monkeypatch.setattr(graph_module, "create_agent", _fake_create_agent)

        step = StepConfig(
            name="intake_scope",
            agent="tier3_planner",
            description="test",
            outputs={"scoped_goal": "scoped_goal"},
        )
        wf = WorkflowConfig(name="wf_parse", steps=[step])
        node = graph_module._make_step_node(step, wf)
        state = initial_state(workflow_inputs={})
        state["context"]["inputs"] = {}

        updated = await node(state)
        assert updated["context"]["scoped_goal"] == "mapped"
        assert updated["steps"]["intake_scope"]["outputs"]["scoped_goal"] == "mapped"

    async def test_llm_step_retries_with_fallback_model(self, monkeypatch):
        from langchain_core.messages import AIMessage

        from agentic_v2.langchain import graph as graph_module

        created_models: list[str] = []

        class _FailingAgent:
            def invoke(self, payload):
                raise Exception("429 Too Many Requests")

        class _PassingAgent:
            def invoke(self, payload):
                return {"messages": [AIMessage(content='{"report":"ok"}')]}

        def _fake_get_candidates(*args, **kwargs):
            return ["gemini:primary", "gh:openai/gpt-4o-mini"]

        def _fake_create_agent(
            agent_name,
            *,
            tool_names=None,
            prompt_file=None,
            model_override=None,
        ):
            created_models.append(model_override or "")
            if model_override == "gemini:primary":
                return _FailingAgent()
            return _PassingAgent()

        monkeypatch.setattr(
            graph_module,
            "get_model_candidates_for_tier",
            _fake_get_candidates,
        )
        monkeypatch.setattr(graph_module, "create_agent", _fake_create_agent)

        step = StepConfig(
            name="review_code",
            agent="tier3_reviewer",
            description="test fallback",
            outputs={"report": "report_ctx"},
        )
        wf = WorkflowConfig(name="wf_failover", steps=[step])
        node = graph_module._make_step_node(step, wf)

        state = initial_state(workflow_inputs={})
        state["context"]["inputs"] = {}
        updated = await node(state)

        assert created_models == ["gemini:primary", "gh:openai/gpt-4o-mini"]
        assert updated["context"]["report_ctx"] == "ok"
        assert updated["steps"]["review_code"]["status"] == "success"
        assert updated["metadata"]["attempted_models"] == [
            "gemini:primary",
            "gh:openai/gpt-4o-mini",
        ]
        assert updated["metadata"]["attempt_errors"][0]["retryable"] is True
