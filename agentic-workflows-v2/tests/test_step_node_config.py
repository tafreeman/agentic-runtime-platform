"""Tests for per-step node configuration: model_params, persona, observers.

Covers YAML parsing/validation (langchain.config), the persona registry,
sampling-parameter threading through the agent factory, media-input
summarization in task prompts, and per-step observer gating.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentic_v2.langchain import agents as agents_module
from agentic_v2.langchain.config import (
    ModelParamsConfig,
    StepConfig,
    WorkflowConfig,
    validate_workflow_document,
)
from agentic_v2.langchain.graph_wiring import (
    build_task_description,
    summarize_media_value,
)
from agentic_v2.langchain.models import apply_model_params
from agentic_v2.langchain.personas import (
    get_persona,
    list_personas,
    resolve_persona_prompt,
)

# ---------------------------------------------------------------------------
# YAML parsing + validation
# ---------------------------------------------------------------------------


def _document(step_extra: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": "wf",
        "steps": [{"name": "s1", "agent": "tier2_reviewer", **step_extra}],
    }


class TestStepConfigParsing:
    def test_parses_model_params_persona_and_observers(self):
        config = validate_workflow_document(
            _document(
                {
                    "persona": "winston_architect",
                    "observers": ["trace", "websocket"],
                    "model_params": {
                        "temperature": 0.7,
                        "top_p": 0.9,
                        "max_tokens": 2048,
                    },
                }
            )
        )
        step = config.steps[0]
        assert step.persona == "winston_architect"
        assert step.observers == ["trace", "websocket"]
        assert step.model_params == ModelParamsConfig(
            temperature=0.7, top_p=0.9, max_tokens=2048
        )

    def test_defaults_are_none(self):
        step = validate_workflow_document(_document({})).steps[0]
        assert step.persona is None
        assert step.observers is None
        assert step.model_params is None

    def test_partial_model_params_keep_unset_fields_none(self):
        step = validate_workflow_document(
            _document({"model_params": {"temperature": 1.0}})
        ).steps[0]
        assert step.model_params == ModelParamsConfig(temperature=1.0)

    def test_parse_tolerates_invalid_values_on_load_path(self):
        """Hand-edited YAML with junk params must not fail workflow load.

        The validation path (editor save) rejects these; the parse-only path
        (load_workflow_config) drops them with a warning instead.
        """
        from agentic_v2.langchain.config import _parse_model_params

        assert (
            _parse_model_params(
                {"temperature": "hot", "top_p": None, "max_tokens": "many"}
            )
            is None
        )
        params = _parse_model_params({"temperature": "not-a-number", "top_p": 0.5})
        assert params == ModelParamsConfig(top_p=0.5)


class TestStepConfigValidation:
    @pytest.mark.parametrize(
        "params, message",
        [
            ({"temperature": 2.5}, "temperature"),
            ({"temperature": -0.1}, "temperature"),
            ({"top_p": 0}, "top_p"),
            ({"top_p": 1.5}, "top_p"),
            ({"max_tokens": 0}, "max_tokens"),
            ({"max_tokens": "lots"}, "max_tokens"),
        ],
    )
    def test_rejects_out_of_range_model_params(self, params, message):
        with pytest.raises(ValueError, match=message):
            validate_workflow_document(_document({"model_params": params}))

    def test_rejects_non_mapping_model_params(self):
        with pytest.raises(ValueError, match="model_params"):
            validate_workflow_document(_document({"model_params": [0.7]}))

    def test_rejects_unknown_observers(self):
        with pytest.raises(ValueError, match="unknown observers"):
            validate_workflow_document(_document({"observers": ["telemetry"]}))

    def test_rejects_non_list_observers(self):
        with pytest.raises(ValueError, match="observers"):
            validate_workflow_document(_document({"observers": "trace"}))

    def test_accepts_empty_observers_list(self):
        config = validate_workflow_document(_document({"observers": []}))
        assert config.steps[0].observers == []


# ---------------------------------------------------------------------------
# Persona registry
# ---------------------------------------------------------------------------


class TestPersonaRegistry:
    def test_lists_precanned_personas(self):
        ids = [p.id for p in list_personas()]
        assert "winston_architect" in ids
        assert "quinn_qa" in ids

    def test_inline_prompt_resolves(self):
        prompt = resolve_persona_prompt("winston_architect")
        assert prompt is not None
        assert "Winston" in prompt

    def test_prompt_file_persona_resolves_from_prompts_dir(self):
        prompt = resolve_persona_prompt("reviewer")
        assert prompt  # prompts/reviewer.md exists and is non-empty

    def test_unknown_persona_returns_none(self):
        assert resolve_persona_prompt("nonexistent_persona") is None
        assert get_persona("nonexistent_persona") is None

    def test_blank_personas_key_yields_empty_registry(self, tmp_path):
        from agentic_v2.langchain.personas import _load_personas

        registry_path = tmp_path / "personas.yaml"
        registry_path.write_text("personas:\n", encoding="utf-8")
        assert _load_personas(str(registry_path)) == ()


class TestSystemPromptResolution:
    def test_persona_wins_over_prompt_file_and_role(self):
        prompt = agents_module._load_system_prompt(
            "tier2_reviewer",
            prompt_file_override="reviewer.md",
            persona="winston_architect",
        )
        assert "Winston" in prompt

    def test_unknown_persona_falls_back_to_role_prompt(self):
        with_persona = agents_module._load_system_prompt(
            "tier2_reviewer", persona="nonexistent_persona"
        )
        without = agents_module._load_system_prompt("tier2_reviewer")
        assert with_persona == without


# ---------------------------------------------------------------------------
# Sampling params threading
# ---------------------------------------------------------------------------


class _FakeChatModel:
    """Duck-typed pydantic-ish model exposing model_fields + model_copy."""

    model_fields = {"temperature": None, "top_p": None, "num_predict": None}

    def __init__(self, **values: Any):
        self.values = values

    def model_copy(self, update: dict[str, Any]):
        merged = {**self.values, **update}
        return _FakeChatModel(**merged)


class TestApplyModelParams:
    def test_maps_max_tokens_to_provider_field_name(self):
        model = _FakeChatModel()
        updated = apply_model_params(model, {"top_p": 0.9, "max_tokens": 128})
        assert updated.values == {"top_p": 0.9, "num_predict": 128}

    def test_skips_unsupported_params_and_none_values(self):
        model = _FakeChatModel()
        updated = apply_model_params(model, {"top_p": None, "unknown": 1})
        assert updated is model

    def test_noop_on_object_without_model_fields(self):
        sentinel = object()
        assert apply_model_params(sentinel, {"top_p": 0.5}) is sentinel

    def test_noop_on_empty_params(self):
        sentinel = object()
        assert apply_model_params(sentinel, None) is sentinel


class TestCreateAgentThreading:
    def test_temperature_threads_into_model_resolution(self, monkeypatch):
        captured: dict[str, Any] = {}

        def _fake_get_model_for_tier(tier, override=None, *, temperature=0.0):
            captured["tier"] = tier
            captured["temperature"] = temperature
            return _FakeChatModel(temperature=temperature)

        monkeypatch.setattr(
            agents_module, "get_model_for_tier", _fake_get_model_for_tier
        )
        monkeypatch.setattr(
            agents_module,
            "create_react_agent",
            lambda model=None, tools=None, prompt=None: {
                "model": model,
                "prompt": prompt,
            },
        )

        agent = agents_module.create_agent(
            "tier2_reviewer",
            model_params=ModelParamsConfig(temperature=0.8, top_p=0.95, max_tokens=512),
            persona="winston_architect",
        )

        assert captured["temperature"] == 0.8
        assert agent["model"].values["top_p"] == 0.95
        assert agent["model"].values["num_predict"] == 512
        assert "Winston" in agent["prompt"]

    def test_defaults_keep_zero_temperature(self, monkeypatch):
        captured: dict[str, Any] = {}

        def _fake_get_model_for_tier(tier, override=None, *, temperature=0.0):
            captured["temperature"] = temperature
            return _FakeChatModel()

        monkeypatch.setattr(
            agents_module, "get_model_for_tier", _fake_get_model_for_tier
        )
        monkeypatch.setattr(
            agents_module,
            "create_react_agent",
            lambda model=None, tools=None, prompt=None: object(),
        )

        agents_module.create_agent("tier2_reviewer")
        assert captured["temperature"] == 0.0


# ---------------------------------------------------------------------------
# Media input summarization
# ---------------------------------------------------------------------------


class TestMediaSummarization:
    def test_large_data_url_is_summarized(self):
        payload = "data:image/png;base64," + "A" * 4096
        summarized = summarize_media_value({"screenshot": payload})
        assert summarized["screenshot"].startswith("<media image/png")
        assert "KB attached" in summarized["screenshot"]

    def test_small_data_url_and_plain_strings_pass_through(self):
        assert summarize_media_value("data:,hello") == "data:,hello"
        assert summarize_media_value("plain text") == "plain text"

    def test_nested_structures_are_walked(self):
        payload = {"files": ["data:audio/wav;base64," + "B" * 2048, "note"]}
        summarized = summarize_media_value(payload)
        assert summarized["files"][0].startswith("<media audio/wav")
        assert summarized["files"][1] == "note"

    def test_task_description_never_embeds_base64(self):
        step = StepConfig(name="describe", agent="tier2_reviewer")
        blob = "data:image/jpeg;base64," + "C" * 100_000
        description = build_task_description(step, {"photo": blob})
        assert "C" * 64 not in description
        assert "<media image/jpeg" in description


# ---------------------------------------------------------------------------
# Per-step observer gating (engine trace channel)
# ---------------------------------------------------------------------------


class _RecordingTrace:
    def __init__(self):
        self.events: list[str] = []

    def emit_step_start(self, *args: Any, **kwargs: Any) -> None:
        self.events.append("step_start")

    def emit_step_complete(self, *args: Any, **kwargs: Any) -> None:
        self.events.append("step_complete")

    def emit_workflow_start(self, *args: Any, **kwargs: Any) -> None:
        self.events.append("workflow_start")

    def emit_workflow_end(self, *args: Any, **kwargs: Any) -> None:
        self.events.append("workflow_end")


class TestObserverTraceGating:
    def _run_node(self, observers: list[str] | None) -> _RecordingTrace:
        from agentic_v2.langchain import graph_wiring

        trace = _RecordingTrace()
        step = StepConfig(
            name="t0",
            agent="tier0_transform",
            observers=observers,
            outputs={},
        )
        workflow = WorkflowConfig(name="wf", steps=[step])
        node = graph_wiring.make_step_node(step, workflow, trace_adapter=trace)
        node(
            {
                "inputs": {},
                "context": {},
                "steps": {},
                "messages": [],
                "errors": [],
                "outputs": {},
                "current_step": "",
            }
        )
        return trace

    def test_default_observers_emit_trace(self):
        trace = self._run_node(observers=None)
        assert "step_start" in trace.events

    def test_observers_without_trace_suppress_emission(self):
        trace = self._run_node(observers=["websocket"])
        assert trace.events == []

    def test_observers_with_trace_emit(self):
        trace = self._run_node(observers=["trace"])
        assert "step_start" in trace.events
