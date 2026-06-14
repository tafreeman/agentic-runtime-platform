"""Tests for ARP-3: structured human-escalation handoff on fallback exhaustion."""

from __future__ import annotations


from agentic_v2.governance import (
    FailureType,
    HandoffSummary,
    route_handoff,
    set_escalation_sink,
)


class TestHandoffSummary:
    """The structured handoff payload shape."""

    def test_from_exhausted_chain_all_agents(self) -> None:
        handoff = HandoffSummary.from_exhausted_chain(
            subtask_id="t1",
            attempted_agents=["coder", "reviewer"],
            partial_results={"coder": "ValueError: boom", "reviewer": "timeout"},
        )
        assert handoff.failure_type is FailureType.ALL_AGENTS_EXHAUSTED
        assert handoff.attempted_agents == ["coder", "reviewer"]
        assert handoff.suggested_next_action
        d = handoff.to_dict()
        assert d["handoff"] is True
        assert set(d) == {
            "handoff",
            "subtask_id",
            "failure_type",
            "attempted_agents",
            "partial_results",
            "suggested_next_action",
        }

    def test_no_agent_available_when_none_attempted(self) -> None:
        handoff = HandoffSummary.from_exhausted_chain(
            subtask_id="t2", attempted_agents=[]
        )
        assert handoff.failure_type is FailureType.NO_AGENT_AVAILABLE
        assert "No agent" in handoff.suggested_next_action

    def test_partial_results_are_truncated(self) -> None:
        big = "x" * 5000
        handoff = HandoffSummary.from_exhausted_chain(
            subtask_id="t3",
            attempted_agents=["a"],
            partial_results={"a": big},
        )
        assert len(handoff.partial_results["a"]) < len(big)
        assert handoff.partial_results["a"].endswith("...[truncated]")


class TestRouteHandoff:
    """route_handoff delivers to the registered sink and is failure-safe."""

    async def test_routes_to_registered_sink(self) -> None:
        received: list[HandoffSummary] = []

        class _Sink:
            async def handle_handoff(self, handoff: HandoffSummary) -> None:
                received.append(handoff)

        set_escalation_sink(_Sink())
        try:
            handoff = HandoffSummary.from_exhausted_chain("t1", ["a"])
            returned = await route_handoff(handoff)
        finally:
            set_escalation_sink(None)

        assert returned is handoff
        assert received == [handoff]

    async def test_sink_failure_does_not_propagate(self) -> None:
        class _BadSink:
            async def handle_handoff(self, handoff: HandoffSummary) -> None:
                raise RuntimeError("sink exploded")

        set_escalation_sink(_BadSink())
        try:
            handoff = HandoffSummary.from_exhausted_chain("t1", ["a"])
            # Must not raise — escalation cannot mask the original failure.
            returned = await route_handoff(handoff)
        finally:
            set_escalation_sink(None)
        assert returned is handoff

    async def test_no_sink_still_returns_handoff(self) -> None:
        set_escalation_sink(None)
        handoff = HandoffSummary.from_exhausted_chain("t1", ["a"])
        assert await route_handoff(handoff) is handoff


class TestOrchestratorEmitsHandoff:
    """The orchestrator routes the handoff to a registered sink on exhaustion."""

    async def test_exhaustion_reaches_sink(self) -> None:
        from agentic_v2.agents.capabilities import CapabilitySet, CapabilityType
        from agentic_v2.agents.orchestrator import OrchestratorAgent, SubTask
        from agentic_v2.contracts import StepStatus

        # Reuse the stub helper from the behavior test module.
        from tests.test_orchestrator_behavior import _make_stub

        received: list[HandoffSummary] = []

        class _Sink:
            async def handle_handoff(self, handoff: HandoffSummary) -> None:
                received.append(handoff)

        orch = OrchestratorAgent()
        cap = CapabilitySet.from_types(CapabilityType.CODE_GENERATION)
        stub = _make_stub("only_agent", cap, raises=True)
        orch._agents["only_agent"] = stub
        orch._agent_capabilities["only_agent"] = cap

        st = SubTask(
            id="hard_task",
            description="Generate some code that always fails to complete",
            required_capabilities=[CapabilityType.CODE_GENERATION],
        )
        st.assigned_agent = "only_agent"
        orch._fallback_chains["hard_task"] = []

        set_escalation_sink(_Sink())
        try:
            _, result = await orch._execute_subtask_with_fallback(st)
        finally:
            set_escalation_sink(None)

        assert st.status == StepStatus.FAILED
        assert result["handoff"] is True
        assert len(received) == 1
        assert received[0].subtask_id == "hard_task"
        assert received[0].attempted_agents == ["only_agent"]
