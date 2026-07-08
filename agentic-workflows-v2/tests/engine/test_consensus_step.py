"""Integration tests for the tier0_consensus aggregator step and its YAML.

Exercises the step through real ``resolve_agent`` + ``StepExecutor`` machinery
(no LLM), an end-to-end mini-DAG of stub reviewers feeding the vote, and a load
of the shipped ``consensus_review.yaml`` definition.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_v2.core.errors import ConfigurationError
from agentic_v2.engine import RetryConfig, StepDefinition, StepExecutor
from agentic_v2.engine.agent_resolver import (
    TIER0_REGISTRY,
    _consensus_step,
    resolve_agent,
)
from agentic_v2.engine.context import ExecutionContext
from agentic_v2.models import ModelTier


class TestConsensusStepResolution:
    """Resolution and direct execution of the tier0_consensus step."""

    def test_registered_in_tier0_registry(self):
        """The aggregator is registered as a deterministic tier-0 step."""
        assert "tier0_consensus" in TIER0_REGISTRY

    def test_resolves_to_tier0(self):
        """resolve_agent binds a tier-0 func for tier0_consensus."""
        step = StepDefinition(name="vote", metadata={"agent": "tier0_consensus"})
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
        """Approve/approve/reject reviewers -> winner 'approve', agreement 2/3."""
        ctx = ExecutionContext()
        executor = StepExecutor()

        verdicts = {
            "reviewer_a": "approve",
            "reviewer_b": "approve",
            "reviewer_c": "reject",
        }
        for name, verdict in verdicts.items():
            stub = StepDefinition(name=name, func=_make_stub(verdict)).with_output(
                verdict="_ignored"
            )
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


class TestConsensusMinAgreementFailClosed:
    """min_agreement resolution fails closed on bad config (A4).

    The documented ``0.0`` default only applies when the threshold is genuinely
    absent; a present-but-malformed value must not be silently coerced to 0.0
    (which would make ``meets_threshold`` always true — fail-open).
    """

    @pytest.mark.asyncio
    async def test_absent_min_agreement_uses_documented_default(self):
        """Absent threshold → documented 0.0 default (no gate), no raise."""
        ctx = ExecutionContext()
        await ctx.set("samples", ["approve", "approve", "reject"])

        result = await _consensus_step(ctx)

        # 0.0 default means the threshold is met (no gate was requested).
        assert result["meets_threshold"] is True
        assert result["winner"] == "approve"

    @pytest.mark.asyncio
    async def test_unparseable_min_agreement_raises(self):
        """A present-but-unparseable threshold is a config error (fail-closed)."""
        ctx = ExecutionContext()
        await ctx.set("samples", ["approve", "reject"])
        await ctx.set("min_agreement", "high")

        with pytest.raises(ConfigurationError):
            await _consensus_step(ctx)

    @pytest.mark.asyncio
    async def test_out_of_range_min_agreement_raises(self):
        """A negative threshold would be fail-open (agreement >= -x); reject it."""
        ctx = ExecutionContext()
        await ctx.set("samples", ["approve", "reject"])
        await ctx.set("min_agreement", -0.5)

        with pytest.raises(ConfigurationError):
            await _consensus_step(ctx)

    @pytest.mark.asyncio
    async def test_malformed_config_fails_the_step_closed(self):
        """Through StepExecutor a malformed threshold yields a failed step.

        A failed vote step means the downstream ``when: meets_threshold`` gate
        never fires — fail-closed end to end, not a silent pass.
        """
        # max_retries=0: a ConfigurationError is deterministic, so retrying it
        # only adds ~7s of exponential backoff before the same failure — the
        # step must fail immediately (matches sibling failure-path tests).
        step = StepDefinition(
            name="vote",
            metadata={"agent": "tier0_consensus"},
            retry=RetryConfig(max_retries=0),
        ).with_input(samples="raw_samples", min_agreement="threshold")
        resolve_agent(step)

        ctx = ExecutionContext()
        await ctx.set("raw_samples", ["a", "b"])
        await ctx.set("threshold", "not-a-number")

        result = await StepExecutor().execute(step, ctx)

        assert not result.is_success


def _make_stub(verdict: str):
    """Build a stub async step func that emits a fixed verdict."""

    async def _stub(_ctx: ExecutionContext) -> dict[str, object]:
        return {"verdict": verdict}

    return _stub
