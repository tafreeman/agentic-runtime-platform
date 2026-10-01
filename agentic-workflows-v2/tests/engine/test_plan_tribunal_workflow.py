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


def test_votes_are_tier0_and_synthesis_is_gated(workflow):
    steps = workflow.dag.steps
    verdicts = [f"verdict_{k}" for k in _JUDGES]
    for name in ("vote_pick", "vote_stance"):
        assert steps[name].tier == ModelTier.TIER_0
        assert steps[name].depends_on == verdicts
    assert steps["synthesis"].when is not None


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
