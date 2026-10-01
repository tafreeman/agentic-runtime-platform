"""Structural tests for the shipped plan_tribunal.yaml multi-judge workflow.

No LLM: these load the definition, check the DAG shape and persona wiring, and
exercise the two tier-0 vote steps with stubbed judge outputs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_v2.engine import StepDefinition, StepExecutor
from agentic_v2.engine.agent_resolver import resolve_agent
from agentic_v2.engine.context import ExecutionContext
from agentic_v2.models import ModelTier
from agentic_v2.workflows.loader import WorkflowLoader

_PKG = Path(__file__).resolve().parents[2] / "agentic_v2"
_JUDGES = ("verification", "concurrency", "pragmatist", "governance", "adversary")


@pytest.fixture(scope="module")
def workflow():
    return WorkflowLoader(definitions_dir=_PKG / "workflows" / "definitions").load(
        "plan_tribunal"
    )


def test_every_judge_has_research_then_verdict(workflow):
    steps = workflow.dag.steps
    for key in _JUDGES:
        assert steps[f"research_{key}"].depends_on == ["brief"]
        assert steps[f"verdict_{key}"].depends_on == [f"research_{key}"]


def test_judge_personas_exist_and_share_baseline(workflow):
    steps = workflow.dag.steps
    for key in _JUDGES:
        for phase in ("research", "verdict"):
            prompt_file = steps[f"{phase}_{key}"].metadata["prompt_file"]
            text = (_PKG / "prompts" / prompt_file).read_text(encoding="utf-8")
            assert "Shared domain baseline" in text
            assert "legal trace" in text


def test_research_steps_have_tools_and_verdicts_do_not(workflow):
    steps = workflow.dag.steps
    for key in _JUDGES:
        tools = steps[f"research_{key}"].metadata["tools"]
        assert "web_search" in tools and "file_read" in tools
        assert steps[f"verdict_{key}"].metadata["tools"] == []


def test_votes_are_tier0_and_downstream_steps_are_gated(workflow):
    steps = workflow.dag.steps
    verdicts = [f"verdict_{k}" for k in _JUDGES]
    ratifications = [f"ratify_{k}" for k in _JUDGES]
    assert steps["vote_pick"].tier == ModelTier.TIER_0
    assert steps["vote_pick"].depends_on == verdicts
    assert steps["vote_stance"].tier == ModelTier.TIER_0
    assert steps["vote_stance"].depends_on == ratifications
    for name in [*ratifications, "vote_stance", "synthesis"]:
        assert steps[name].when is not None, name


def test_stance_is_ruled_on_the_panels_pick_not_each_judges_own(workflow):
    """Each judge rules on ``vote_pick``'s winner after the pick vote."""
    steps = workflow.dag.steps
    for key in _JUDGES:
        ratify = steps[f"ratify_{key}"]
        assert ratify.depends_on == ["vote_pick"]
        assert ratify.input_mapping["first_candidate"] == (
            "${steps.vote_pick.outputs.winner}"
        )
        assert "stance" not in steps[f"verdict_{key}"].output_mapping


def test_focus_reaches_every_judging_and_synthesis_step(workflow):
    steps = workflow.dag.steps
    names = ["brief", "synthesis"] + [
        f"{phase}_{key}"
        for key in _JUDGES
        for phase in ("research", "verdict", "ratify")
    ]
    for name in names:
        assert steps[name].input_mapping["focus"] == "${inputs.focus}", name


def test_synthesis_sees_whether_approval_was_reached(workflow):
    mapping = workflow.dag.steps["synthesis"].input_mapping
    assert mapping["approval_met"] == "${steps.vote_stance.outputs.meets_threshold}"
    assert "approval_met" in workflow.outputs


def test_new_alternative_ids_are_namespaced_by_judge(workflow):
    for key in _JUDGES:
        text = workflow.dag.steps[f"verdict_{key}"].description
        assert f"NEW-{key}-1" in text


def test_role_model_overrides_are_optional_env_vars(workflow):
    """``env:VAR|`` leaves tier routing alone when the variable is unset."""
    for step in workflow.dag.steps.values():
        override = step.metadata.get("model_override")
        if override is None:
            continue
        assert override.startswith("env:TRIBUNAL_MODEL_"), step.name
        assert override.endswith("|"), step.name


@pytest.mark.asyncio
async def test_vote_pick_majority_and_threshold():
    step = StepDefinition(
        name="vote_pick", metadata={"agent": "tier0_consensus"}
    ).with_input(samples="picks", min_agreement="threshold")
    resolve_agent(step)
    ctx = ExecutionContext()
    await ctx.set("picks", ["P3", "P3", "P3", "P1", "NEW-1"])
    await ctx.set("threshold", 0.6)

    result = await StepExecutor().execute(step, ctx)

    assert result.is_success
    assert result.output_data["winner"] == "P3"
    assert result.output_data["meets_threshold"] is True


@pytest.mark.asyncio
async def test_split_panel_does_not_clear_gate():
    step = StepDefinition(
        name="vote_pick", metadata={"agent": "tier0_consensus"}
    ).with_input(samples="picks", min_agreement="threshold")
    resolve_agent(step)
    ctx = ExecutionContext()
    await ctx.set("picks", ["P1", "P2", "P3", "P4", "P5"])
    await ctx.set("threshold", 0.6)

    result = await StepExecutor().execute(step, ctx)

    assert result.output_data["meets_threshold"] is False


def test_optional_env_override_resolves_to_no_override(monkeypatch):
    from agentic_v2.langchain.model_utils import resolve_model_override

    monkeypatch.delenv("TRIBUNAL_TEST_MODEL", raising=False)
    assert resolve_model_override("env:TRIBUNAL_TEST_MODEL|") == ""
    monkeypatch.setenv("TRIBUNAL_TEST_MODEL", "ollama:glm-5.3")
    assert resolve_model_override("env:TRIBUNAL_TEST_MODEL|") == "ollama:glm-5.3"


def test_required_and_inline_fallback_overrides_are_unchanged(monkeypatch):
    from agentic_v2.langchain.model_utils import resolve_model_override

    monkeypatch.delenv("TRIBUNAL_TEST_MODEL", raising=False)
    with pytest.raises(ValueError, match="requires environment variable"):
        resolve_model_override("env:TRIBUNAL_TEST_MODEL")
    assert resolve_model_override("env:TRIBUNAL_TEST_MODEL|gh:openai/gpt-4o") == (
        "gh:openai/gpt-4o"
    )


def test_unset_optional_override_does_not_pin_a_model(monkeypatch):
    """The candidate list is the tier's own routing, with no extra pinned id."""
    from agentic_v2.langchain.models import get_model_candidates_for_tier

    monkeypatch.delenv("TRIBUNAL_TEST_MODEL", raising=False)
    monkeypatch.delenv("AGENTIC_MODEL_TIER_2", raising=False)
    plain = get_model_candidates_for_tier(2, None, include_unavailable=True)
    optional = get_model_candidates_for_tier(
        2, "env:TRIBUNAL_TEST_MODEL|", include_unavailable=True
    )
    assert optional == plain
    monkeypatch.setenv("TRIBUNAL_TEST_MODEL", "ollama:glm-5.3")
    pinned = get_model_candidates_for_tier(
        2, "env:TRIBUNAL_TEST_MODEL|", include_unavailable=True
    )
    assert pinned[0] == "ollama:glm-5.3"
