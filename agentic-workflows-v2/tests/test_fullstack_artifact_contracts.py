"""Regression coverage for fullstack backend artifact handoffs."""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage

from agentic_v2.artifact_contracts import ArtifactContract, ArtifactContractError
from agentic_v2.langchain import graph as graph_module
from agentic_v2.langchain.config import (
    StepConfig,
    WorkflowConfig,
    _parse,
    load_workflow_config,
)
from agentic_v2.langchain.expressions import resolve_expression
from agentic_v2.langchain.graph_wiring import (
    build_task_description,
    resolve_inputs_into_context,
)
from agentic_v2.langchain.state import initial_state
from agentic_v2.workflows.loader import WorkflowLoader, WorkflowLoadError

_CAPTURED_PLACEHOLDER = (
    "OpenAPI spec not generated here; see backend_code for implementation"
)
_BACKEND = {
    "Program.cs": "var builder = WebApplication.CreateBuilder(args);",
    "Todo.cs": "public sealed record Todo(int Id, string Title);",
    "AppDbContext.cs": "public sealed class AppDbContext : DbContext {}",
}


def _code_contract(*, aliases: tuple[str, ...] = ()) -> ArtifactContract:
    return ArtifactContract(kind="code_artifact", aliases=aliases)


def test_fullstack_yaml_declares_canonical_outputs_and_contracts() -> None:
    native = WorkflowLoader().load("fullstack_generation")
    native_generate = native.dag.steps["generate_api"]
    langchain = load_workflow_config("fullstack_generation")
    langchain_generate = next(
        step for step in langchain.steps if step.name == "generate_api"
    )

    assert list(native_generate.output_mapping) == ["backend_code", "backend_tests"]
    assert native_generate.output_contracts["backend_code"].aliases == ("api_code",)
    assert list(langchain_generate.outputs) == ["backend_code", "backend_tests"]
    assert langchain_generate.output_contracts["backend_tests"].aliases == (
        "api_tests",
    )

    prompt = build_task_description(langchain_generate, {})
    assert "backend_code" in prompt
    assert "backend_tests" in prompt
    assert "api_code" not in prompt
    assert "api_tests" not in prompt


def test_captured_backend_shape_reaches_every_real_yaml_consumer() -> None:
    config = load_workflow_config("fullstack_generation")
    native = WorkflowLoader().load("fullstack_generation")
    state = initial_state()
    state["steps"]["generate_api"] = {
        "status": "success",
        "outputs": {
            "api_code": _CAPTURED_PLACEHOLDER,
            "backend_code": _BACKEND,
        },
    }

    consumers = {
        "generate_integration_tests",
        "review_code",
        "developer_rework",
        "assemble_feature",
    }
    encountered: set[str] = set()
    for step in config.steps:
        if step.name not in consumers:
            continue
        encountered.add(step.name)
        _ctx, resolved = resolve_inputs_into_context(step, state)
        assert resolved["backend"] == _BACKEND
        native_mapping = native.dag.steps[step.name].input_mapping["backend"]
        assert native_mapping.index("backend_code") < native_mapping.index("api_code")

    assert encountered == consumers
    all_code = resolve_expression(config.outputs["all_code"].from_expr, state)
    assert all_code["backend"] == _BACKEND
    native_all_code = native.outputs["all_code"].from_expr["backend"]
    assert native_all_code.index("backend_code") < native_all_code.index("api_code")


def test_all_real_yaml_consumers_reject_invalid_backend() -> None:
    config = load_workflow_config("fullstack_generation")
    state = initial_state()
    state["steps"]["generate_api"] = {
        "status": "success",
        "outputs": {
            "backend_code": _CAPTURED_PLACEHOLDER,
            "api_code": _CAPTURED_PLACEHOLDER,
        },
    }

    rejected: set[str] = set()
    consumers = {
        "generate_integration_tests",
        "review_code",
        "developer_rework",
        "assemble_feature",
    }
    for step in config.steps:
        if step.name not in consumers:
            continue
        try:
            resolve_inputs_into_context(step, state)
        except ArtifactContractError:
            rejected.add(step.name)

    assert rejected == consumers


def test_real_yaml_consumers_accept_legacy_checkpoint_when_canonical_missing() -> None:
    config = load_workflow_config("fullstack_generation")
    review = next(step for step in config.steps if step.name == "review_code")
    state = initial_state()
    state["steps"]["generate_api"] = {
        "status": "success",
        "outputs": {"api_code": _BACKEND},
    }

    _ctx, resolved = resolve_inputs_into_context(review, state)

    assert resolved["backend"] == _BACKEND


class _ReplyAgent:
    def __init__(self, reply: str | Exception) -> None:
        self.reply = reply

    def invoke(self, _payload: object) -> dict[str, object]:
        if isinstance(self.reply, Exception):
            raise self.reply
        return {"messages": [AIMessage(content=self.reply)]}


class _RecordingTrace:
    def __init__(self) -> None:
        self.starts: list[dict[str, object]] = []
        self.completions: list[dict[str, object]] = []

    def emit_step_start(self, _name, _run_id, inputs) -> None:
        self.starts.append(inputs)

    def emit_step_complete(self, _name, _run_id, _status, outputs) -> None:
        self.completions.append(outputs)


def _wire_contract_node(
    monkeypatch,
    replies: dict[str, str | Exception],
    *,
    candidates: list[str],
    trace=None,
):
    created: list[str] = []

    def get_candidates(*_args, **_kwargs):
        return candidates

    def create_agent(
        _agent_name,
        *,
        tool_names=None,
        prompt_file=None,
        model_override=None,
    ):
        del tool_names, prompt_file
        created.append(model_override)
        return _ReplyAgent(replies[model_override])

    monkeypatch.setattr(
        graph_module,
        "get_model_candidates_for_tier",
        get_candidates,
    )
    monkeypatch.setattr(graph_module, "create_agent", create_agent)

    step = StepConfig(
        name="generate_api",
        agent="tier2_coder",
        outputs={"backend_code": "backend_code"},
        output_contracts={
            "backend_code": _code_contract(aliases=("api_code",)),
        },
    )
    workflow = WorkflowConfig(name="artifact_failover", steps=[step])
    return graph_module._make_step_node(step, workflow, trace_adapter=trace), created


async def test_langchain_contract_fails_over_from_placeholder_to_valid_code(
    monkeypatch,
) -> None:
    monkeypatch.delenv("AGENTIC_NO_LLM", raising=False)
    node, created = _wire_contract_node(
        monkeypatch,
        {
            "weak": json.dumps({"api_code": _CAPTURED_PLACEHOLDER}),
            "strong": json.dumps({"backend_code": _BACKEND}),
        },
        candidates=["weak", "strong"],
    )

    updated = await node(initial_state())

    assert created == ["weak", "strong"]
    assert updated["steps"]["generate_api"]["status"] == "success"
    assert updated["context"]["backend_code"] == _BACKEND
    assert len(updated["metadata"]["attempt_errors"]) == 1


async def test_langchain_contract_rejects_invalid_last_candidate(
    monkeypatch,
) -> None:
    monkeypatch.delenv("AGENTIC_NO_LLM", raising=False)
    trace = _RecordingTrace()
    node, created = _wire_contract_node(
        monkeypatch,
        {
            "weak": json.dumps({"api_code": _CAPTURED_PLACEHOLDER}),
            "also-weak": json.dumps({"backend_code": "not generated"}),
        },
        candidates=["weak", "also-weak"],
        trace=trace,
    )

    updated = await node(initial_state())

    assert created == ["weak", "also-weak"]
    assert updated["steps"]["generate_api"]["status"] == "failed"
    assert "backend_code" not in updated["context"]
    assert len(updated["steps"]["generate_api"]["outputs"]) == 0
    diagnostics = updated["steps"]["generate_api"]["metadata"]["contract_diagnostics"]
    assert diagnostics[0]["field"] == "backend_code"
    assert trace.completions[-1]["attempt_errors"][-1]["retryable"] is False


async def test_terminal_provider_error_does_not_keep_prior_contract_diagnostics(
    monkeypatch,
) -> None:
    monkeypatch.delenv("AGENTIC_NO_LLM", raising=False)
    node, _created = _wire_contract_node(
        monkeypatch,
        {
            "weak": json.dumps({"api_code": _CAPTURED_PLACEHOLDER}),
            "provider-error": RuntimeError("provider unavailable"),
        },
        candidates=["weak", "provider-error"],
    )

    updated = await node(initial_state())

    assert updated["steps"]["generate_api"]["status"] == "failed"
    assert "metadata" not in updated["steps"]["generate_api"]


async def test_pre_invocation_contract_failure_emits_start_then_complete(
    monkeypatch,
) -> None:
    trace = _RecordingTrace()
    step = StepConfig(
        name="review_code",
        agent="tier3_reviewer",
        inputs={"backend": "${steps.generate_api.outputs.backend_code}"},
        input_contracts={"backend": _code_contract()},
    )
    workflow = WorkflowConfig(name="input_contract", steps=[step])
    node = graph_module._make_step_node(step, workflow, trace_adapter=trace)
    state = initial_state()
    state["steps"]["generate_api"] = {
        "status": "success",
        "outputs": {"backend_code": _CAPTURED_PLACEHOLDER},
    }

    updated = await node(state)

    assert updated["steps"]["review_code"]["status"] == "failed"
    assert trace.starts == [{}]
    assert len(trace.completions) == 1


async def test_no_llm_placeholder_is_explicitly_unsuccessful(monkeypatch) -> None:
    monkeypatch.setenv("AGENTIC_NO_LLM", "1")
    node, created = _wire_contract_node(
        monkeypatch,
        {"placeholder": _CAPTURED_PLACEHOLDER},
        candidates=["placeholder"],
    )

    updated = await node(initial_state())

    assert created == ["placeholder"]
    assert updated["steps"]["generate_api"]["status"] == "failed"
    assert updated["errors"]


def test_native_loader_rejects_unbound_contract(tmp_path) -> None:
    (tmp_path / "unbound.yaml").write_text(
        """
name: unbound
steps:
  - name: generate
    agent: tier2_coder
    outputs:
      backend_code: backend_code
    output_contracts:
      missing: code_artifact
""",
        encoding="utf-8",
    )

    with pytest.raises(WorkflowLoadError, match="corresponding mapping"):
        WorkflowLoader(definitions_dir=tmp_path).load("unbound")


def test_langchain_config_rejects_unbound_contract() -> None:
    with pytest.raises(ValueError, match="corresponding mapping"):
        _parse(
            {
                "name": "unbound",
                "steps": [
                    {
                        "name": "review",
                        "agent": "tier3_reviewer",
                        "inputs": {"backend": "${inputs.backend}"},
                        "input_contracts": {"missing": "code_artifact"},
                    }
                ],
            },
            "unbound",
        )
