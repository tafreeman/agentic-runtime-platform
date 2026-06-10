"""Integration tests for the tier0_consensus aggregator step and its YAML.

Exercises the step through real ``resolve_agent`` + ``StepExecutor`` machinery
(no LLM), an end-to-end mini-DAG of stub reviewers feeding the vote, and a load
of the shipped ``consensus_review.yaml`` definition.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_v2.engine import StepDefinition, StepExecutor
from agentic_v2.engine.agent_resolver import TIER0_REGISTRY, resolve_agent
from agentic_v2.engine.context import ExecutionContext
from agentic_v2.models import ModelTier


class TestConsensusStepResolution:
    """Resolution and direct execution of the tier0_consensus step."""

    def test_registered_in_tier0_registry(self):
        """The aggregator is registered as a deterministic tier-0 step."""
        assert "tier0_consensus" in TIER0_REGISTRY

    def test_resolves_to_tier0(self):
        """resolve_agent binds a tier-0 func for tier0_consensus."""
        step = StepDefinition(
            name="vote", metadata={"agent": "tier0_consensus"}
        )
        resolve_agent(step)

        assert step.func is not None
        assert step.tier == ModelTier.TIER_0

    @pytest.mark.asyncio
    async def test_executes_majority_vote_from_literal_samples(self):
        """A literal samples list votes to the modal winner via StepExecutor."""
        step = StepDefinition(
            name="vote", metadata={"agent": "tier0_consensus"}
        ).with_input(samples="raw_samples")
        resolve_agent(step)

        ctx = ExecutionContext()
        await ctx.set("raw_samples", ["approve", "approve", "reject"])

        result = await StepExecutor().execute(step, ctx)

        assert result.is_success
        assert result.output_data["winner"] == "approve"
        assert result.output_data["agreement"] == pytest.approx(2 / 3)
        assert result.output_data["total_samples"] == 3

    @pytest.mark.asyncio
    async def test_meets_threshold_gate(self):
        """min_agreement input drives the meets_threshold output."""
        step = StepDefinition(
            name="vote", metadata={"agent": "tier0_consensus"}
        ).with_input(samples="raw_samples", min_agreement="threshold")
        resolve_agent(step)

        ctx = ExecutionContext()
        await ctx.set("raw_samples", ["a", "b", "c"])
        await ctx.set("threshold", 0.6)

        result = await StepExecutor().execute(step, ctx)

        assert result.is_success
        assert result.output_data["meets_threshold"] is False


class TestConsensusMiniDag:
    """End-to-end: three stub reviewers feed the consensus step."""

    @pytest.mark.asyncio
    async def test_three_stub_steps_into_vote(self):
        """approve/approve/reject reviewers -> winner 'approve', agreement 2/3."""
        ctx = ExecutionContext()
        executor = StepExecutor()

        verdicts = {
            "reviewer_a": "approve",
            "reviewer_b": "approve",
            "reviewer_c": "reject",
        }
        for name, verdict in verdicts.items():
            stub = StepDefinition(
                name=name, func=_make_stub(verdict)
            ).with_output(verdict="_ignored")
            stub_result = await executor.execute(stub, ctx)
            assert stub_result.is_success

        # The vote step resolves each reviewer's output via ${steps...} exprs.
        vote = StepDefinition(
            name="vote", metadata={"agent": "tier0_consensus"}
        ).with_input(
            samples=[
                "${steps.reviewer_a.outputs.verdict}",
                "${steps.reviewer_b.outputs.verdict}",
                "${steps.reviewer_c.outputs.verdict}",
            ]
        )
        resolve_agent(vote)

        result = await executor.execute(vote, ctx)

        assert result.is_success
        assert result.output_data["winner"] == "approve"
        assert result.output_data["agreement"] == pytest.approx(2 / 3)
        assert result.output_data["votes"] == {"approve": 2, "reject": 1}


class TestConsensusYamlLoads:
    """The shipped consensus_review.yaml loads and builds a valid DAG."""

    def test_consensus_review_yaml_loads_and_validates(self):
        from agentic_v2.workflows.loader import WorkflowLoader

        definitions_dir = (
            Path(__file__).resolve().parents[2]
            / "agentic_v2"
            / "workflows"
            / "definitions"
        )
        loader = WorkflowLoader(definitions_dir=definitions_dir)
        workflow = loader.load("consensus_review")

        step_names = set(workflow.dag.steps)
        assert {"reviewer_a", "reviewer_b", "reviewer_c", "vote", "summarize"} <= (
            step_names
        )

        vote_step = workflow.dag.steps["vote"]
        assert vote_step.func is not None  # resolved to the tier0 aggregator
        assert vote_step.tier == ModelTier.TIER_0
        assert vote_step.depends_on == ["reviewer_a", "reviewer_b", "reviewer_c"]

        # The summarize step is gated on the vote's threshold result.
        summarize_step = workflow.dag.steps["summarize"]
        assert summarize_step.when is not None


def _make_stub(verdict: str):
    """Build a stub async step func that emits a fixed verdict."""

    async def _stub(_ctx: ExecutionContext) -> dict[str, object]:
        return {"verdict": verdict}

    return _stub
