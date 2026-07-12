"""Behavioral tests for multi-agent orchestration correctness.

Tests three critical properties:
1. Assignment correctness — capability scoring drives the right agent selection.
2. Dependency ordering — DAG-level and orchestrator-level ordering is respected.
3. Fallback recovery — failures cascade through the fallback chain correctly.

All tests use stub agents (no network, no LLM calls) registered via
OrchestratorAgent.register_agent().
"""

from __future__ import annotations

import pytest

from agentic_v2.agents.capabilities import (
    Capability,
    CapabilitySet,
    CapabilityType,
)
from agentic_v2.agents.orchestrator import (
    OrchestratorAgent,
    SubTask,
)
from agentic_v2.contracts import StepStatus, TaskInput, TaskOutput
from agentic_v2.engine.dag import DAG, CycleDetectedError
from agentic_v2.engine.step import StepDefinition

# ---------------------------------------------------------------------------
# Stub agent helpers
# ---------------------------------------------------------------------------


class _MinimalOutput(TaskOutput):
    """Minimal concrete TaskOutput for stubs."""

    pass


class _MinimalInput(TaskInput):
    """Minimal concrete TaskInput for stubs."""

    pass


def _make_stub(
    name: str,
    capabilities: CapabilitySet,
    *,
    raises: bool = False,
    return_value: dict | None = None,
    call_log: list[str] | None = None,
):
    """Fabricate a stub agent with fixed capabilities and configurable behavior.

    The returned object is *not* a full BaseAgent subclass — the orchestrator
    only needs:
      - ``config.name``
      - ``config.description``
      - ``run(task_input)``
    And we register capabilities via ``register_agent(name, stub)`` which calls
    ``get_agent_capabilities(stub)`` — so we monkey-patch that lookup instead of
    deriving from a mixin.
    """
    from unittest.mock import MagicMock

    from agentic_v2.agents.config import AgentConfig

    stub = MagicMock()
    stub.config = AgentConfig(name=name, description=f"stub:{name}")

    if raises:

        async def _run_fail(task):
            if call_log is not None:
                call_log.append(name)
            raise RuntimeError(f"Intentional failure in {name}")

        stub.run = _run_fail
    else:
        result_payload = return_value if return_value is not None else {"output": name}

        async def _run_ok(task):
            if call_log is not None:
                call_log.append(name)
            return _MinimalOutput(success=True, **result_payload)

        stub.run = _run_ok

    # Store capabilities for get_agent_capabilities() patching below
    stub._stub_capability_set = capabilities
    return stub


def _build_orchestrator_with_stubs(
    stubs: list[tuple[str, object]],
) -> OrchestratorAgent:
    """Create an OrchestratorAgent with stub agents.

    Patches ``get_agent_capabilities`` so that the orchestrator's
    ``_assign_agents`` scores each stub by its declared CapabilitySet.
    """
    import agentic_v2.agents.orchestrator as _orch_module

    orch = OrchestratorAgent()

    original_get_caps = _orch_module.get_agent_capabilities

    def _patched_get_caps(agent):
        if hasattr(agent, "_stub_capability_set"):
            return agent._stub_capability_set
        return original_get_caps(agent)

    _orch_module.get_agent_capabilities = _patched_get_caps

    for name, stub in stubs:
        orch.register_agent(name, stub)

    # Restore the real function so later tests are not affected
    # We yield-back via the fixture; here just return for simplicity — each
    # test that uses this helper will undo the patch at teardown automatically
    # because the orchestrator instance holds its own dict.
    # Restore immediately — the caps are already cached in _agent_capabilities.
    _orch_module.get_agent_capabilities = original_get_caps

    return orch


def _populate_subtask(
    orch: OrchestratorAgent,
    task_id: str,
    cap_types: list[CapabilityType],
    dependencies: list[str] | None = None,
) -> SubTask:
    """Insert a SubTask directly into the orchestrator's internal registry."""
    st = SubTask(
        id=task_id,
        description=f"Stub subtask {task_id}",
        required_capabilities=cap_types,
        dependencies=dependencies or [],
    )
    orch._subtasks[task_id] = st
    return st


# ---------------------------------------------------------------------------
# Test 1-4: Capability-scored assignment
# ---------------------------------------------------------------------------


class TestCapabilityScoredAssignment:
    """Tests that _assign_agents picks and orders agents by capability score."""

    @pytest.mark.asyncio
    async def test_disjoint_capabilities_correct_agent_selected(self):
        """Test 1: Two agents with disjoint capabilities; subtask needs CODE_GENERATION.

        The CODE_GENERATION agent must be assigned — not the CODE_REVIEW agent.
        """
        gen_caps = CapabilitySet.from_types(CapabilityType.CODE_GENERATION)
        review_caps = CapabilitySet.from_types(CapabilityType.CODE_REVIEW)

        gen_stub = _make_stub("code_gen_agent", gen_caps)
        review_stub = _make_stub("code_review_agent", review_caps)

        orch = _build_orchestrator_with_stubs(
            [("code_gen_agent", gen_stub), ("code_review_agent", review_stub)]
        )
        _populate_subtask(orch, "task_codegen", [CapabilityType.CODE_GENERATION])

        assignments = await orch._assign_agents()

        assert assignments.get("task_codegen") == "code_gen_agent", (
            "Orchestrator assigned wrong agent: expected code_gen_agent, "
            f"got {assignments.get('task_codegen')}"
        )
        # The review agent must NOT be assigned to this subtask
        assert orch._subtasks["task_codegen"].assigned_agent == "code_gen_agent"

    @pytest.mark.asyncio
    async def test_higher_proficiency_wins(self):
        """Test 2: Two agents share the required capability; higher proficiency wins."""
        low_caps = CapabilitySet()
        low_caps.add(Capability(type=CapabilityType.CODE_GENERATION, proficiency=0.4))

        high_caps = CapabilitySet()
        high_caps.add(Capability(type=CapabilityType.CODE_GENERATION, proficiency=0.9))

        low_stub = _make_stub("low_prof_agent", low_caps)
        high_stub = _make_stub("high_prof_agent", high_caps)

        orch = _build_orchestrator_with_stubs(
            [("low_prof_agent", low_stub), ("high_prof_agent", high_stub)]
        )
        _populate_subtask(orch, "task_x", [CapabilityType.CODE_GENERATION])

        assignments = await orch._assign_agents()

        assert assignments.get("task_x") == "high_prof_agent", (
            "Expected high_prof_agent (proficiency 0.9) to beat low_prof_agent (0.4); "
            f"actual assignment: {assignments.get('task_x')}"
        )

    @pytest.mark.asyncio
    async def test_fallback_chain_ordering_descending_score(self):
        """Test 3: Three candidate agents — fallback chain is in descending score order.

        With proficiencies 0.3, 0.7, 1.0 the fallback chain after the best (1.0)
        should be [mid (0.7), low (0.3)].
        """
        low_caps = CapabilitySet()
        low_caps.add(Capability(type=CapabilityType.TEST_GENERATION, proficiency=0.3))

        mid_caps = CapabilitySet()
        mid_caps.add(Capability(type=CapabilityType.TEST_GENERATION, proficiency=0.7))

        top_caps = CapabilitySet()
        top_caps.add(Capability(type=CapabilityType.TEST_GENERATION, proficiency=1.0))

        orch = _build_orchestrator_with_stubs(
            [
                ("low_agent", _make_stub("low_agent", low_caps)),
                ("mid_agent", _make_stub("mid_agent", mid_caps)),
                ("top_agent", _make_stub("top_agent", top_caps)),
            ]
        )
        _populate_subtask(orch, "test_task", [CapabilityType.TEST_GENERATION])

        await orch._assign_agents()

        primary = orch._subtasks["test_task"].assigned_agent
        fallbacks = orch._fallback_chains.get("test_task", [])

        assert primary == "top_agent", f"Expected top_agent as primary; got {primary}"
        assert fallbacks == [
            "mid_agent",
            "low_agent",
        ], (
            f"Fallback chain should be [mid_agent, low_agent] (descending score); "
            f"got {fallbacks}"
        )

    @pytest.mark.asyncio
    async def test_no_matching_agent_leaves_subtask_unassigned(self):
        """Test 4: No agent matches the required capability → assigned_agent stays None.

        This documents the actual behavior: the subtask is left unassigned and
        absent from the assignments dict. The orchestrator does NOT raise.
        """
        # Agent only has CODE_REVIEW; subtask requires SECURITY_ANALYSIS
        review_caps = CapabilitySet.from_types(CapabilityType.CODE_REVIEW)
        orch = _build_orchestrator_with_stubs(
            [("review_only", _make_stub("review_only", review_caps))]
        )
        _populate_subtask(orch, "sec_task", [CapabilityType.SECURITY_ANALYSIS])

        assignments = await orch._assign_agents()

        # No assignment created
        assert "sec_task" not in assignments, (
            "Expected sec_task to be absent from assignments when no agent matches; "
            f"assignments = {assignments}"
        )
        assert (
            orch._subtasks["sec_task"].assigned_agent is None
        ), "assigned_agent should remain None when no capable agent is registered"


# ---------------------------------------------------------------------------
# Test 5-8: Dependency ordering
# ---------------------------------------------------------------------------


class TestDependencyOrdering:
    """Tests that DAG topological ordering and orchestrator ready-step logic are
    correct."""

    def _make_dag_step(self, name: str, deps: list[str]) -> StepDefinition:
        async def _noop(ctx):
            return {}

        step = StepDefinition(name=name, func=_noop, depends_on=deps)
        return step

    def test_linear_chain_execution_order(self):
        """Test 5: Linear chain A→B→C produces exactly [A, B, C]."""
        dag = DAG(name="linear")
        dag.add(self._make_dag_step("A", []))
        dag.add(self._make_dag_step("B", ["A"]))
        dag.add(self._make_dag_step("C", ["B"]))

        order = dag.get_execution_order()

        assert order == [
            "A",
            "B",
            "C",
        ], f"Linear chain A→B→C must yield [A, B, C]; got {order}"

    def test_diamond_ordering_constraints(self):
        """Test 6: Diamond A→(B,C)→D: A first, D last, B and C after A and before D."""
        dag = DAG(name="diamond")
        dag.add(self._make_dag_step("A", []))
        dag.add(self._make_dag_step("B", ["A"]))
        dag.add(self._make_dag_step("C", ["A"]))
        dag.add(self._make_dag_step("D", ["B", "C"]))

        order = dag.get_execution_order()

        assert order[0] == "A", f"A must be first; got {order}"
        assert order[-1] == "D", f"D must be last; got {order}"
        assert order.index("B") > order.index("A"), "B must come after A"
        assert order.index("C") > order.index("A"), "C must come after A"
        assert order.index("B") < order.index("D"), "B must come before D"
        assert order.index("C") < order.index("D"), "C must come before D"

    def test_cycle_raises_cycle_detected_error(self):
        """Test 7: A→B→C→A cycle raises CycleDetectedError on validate()."""
        dag = DAG(name="cycle")
        dag.add(self._make_dag_step("A", ["C"]))
        dag.add(self._make_dag_step("B", ["A"]))
        dag.add(self._make_dag_step("C", ["B"]))

        with pytest.raises(CycleDetectedError):
            dag.validate()

    def test_find_ready_subtasks_respects_dependency_completion(self):
        """Test 8: _find_ready_subtasks gates B on A's completion.

        Before A executes: only A is ready.
        After A executes: B becomes ready.
        """
        orch = OrchestratorAgent()
        _populate_subtask(orch, "A", [], dependencies=[])
        _populate_subtask(orch, "B", [], dependencies=["A"])

        # Nothing executed yet
        ready_before = {st.id for st in orch._find_ready_subtasks(set())}
        assert ready_before == {
            "A"
        }, f"Before any execution only A should be ready; got {ready_before}"

        # After A completes
        ready_after = {st.id for st in orch._find_ready_subtasks({"A"})}
        assert ready_after == {
            "B"
        }, f"After A completes only B should be ready; got {ready_after}"


# ---------------------------------------------------------------------------
# Test 9-12: Fallback chain recovery
# ---------------------------------------------------------------------------


class TestFallbackChainRecovery:
    """Tests for _execute_subtask_with_fallback behavior.

    These are the highest-value tests: zero existing coverage before this file.
    """

    def _setup_orch_with_fallbacks(
        self,
        candidates: list[tuple[str, bool]],
        call_log: list[str],
    ) -> tuple[OrchestratorAgent, SubTask]:
        """Build an orchestrator with agents listed in (name, raises) order.

        The first candidate becomes the assigned_agent; the rest go into
        _fallback_chains.  All agents share the same capability so
        scoring gives them equal weight, but we force ordering by
        injecting directly.
        """
        orch = OrchestratorAgent()
        cap = CapabilitySet.from_types(CapabilityType.CODE_GENERATION)

        for name, raises in candidates:
            stub = _make_stub(name, cap, raises=raises, call_log=call_log)
            # Register without scoring to preserve explicit order
            orch._agents[name] = stub
            orch._agent_capabilities[name] = cap

        # Build the subtask manually
        st = SubTask(
            id="fallback_task",
            description="A task that exercises fallback",
            required_capabilities=[CapabilityType.CODE_GENERATION],
        )
        orch._subtasks["fallback_task"] = st

        # Wire the explicit assignment + fallback chain
        agent_names = [name for name, _ in candidates]
        st.assigned_agent = agent_names[0]
        orch._fallback_chains["fallback_task"] = agent_names[1:]

        return orch, st

    @pytest.mark.asyncio
    async def test_fallback_invoked_when_primary_fails(self):
        """Test 9: Primary raises → fallback succeeds → status SUCCESS, correct output.

        Also verifies the fallback was actually invoked (call recording).
        """
        call_log: list[str] = []
        orch, st = self._setup_orch_with_fallbacks(
            [("primary", True), ("fallback1", False)],
            call_log,
        )

        task_id, result = await orch._execute_subtask_with_fallback(st)

        assert task_id == "fallback_task"
        assert (
            st.status == StepStatus.SUCCESS
        ), f"Expected SUCCESS after fallback recovered; got {st.status}"
        assert "primary" in call_log, "Primary agent should have been attempted"
        assert "fallback1" in call_log, "Fallback agent should have been invoked"

    @pytest.mark.asyncio
    async def test_fallback_order_respected(self):
        """Test 10: primary fails, fb1 fails, fb2 succeeds → invocation order [primary, fb1, fb2]."""
        call_log: list[str] = []
        orch, st = self._setup_orch_with_fallbacks(
            [("primary", True), ("fb1", True), ("fb2", False)],
            call_log,
        )

        _, result = await orch._execute_subtask_with_fallback(st)

        assert call_log == [
            "primary",
            "fb1",
            "fb2",
        ], f"Agents must be tried in primary→fb1→fb2 order; invocations were: {call_log}"
        assert st.status == StepStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_all_agents_fail_produces_structured_handoff(self):
        """Test 11: All candidates raise → FAILED status + structured handoff.

        ARP-3: exhaustion emits a structured handoff (failure_type,
        attempted_agents, partial_results, suggested_next_action) routed to the
        escalation gate, not a bare ``{"error": ...}``.
        """
        call_log: list[str] = []
        orch, st = self._setup_orch_with_fallbacks(
            [("a1", True), ("a2", True), ("a3", True)],
            call_log,
        )

        task_id, result = await orch._execute_subtask_with_fallback(st)

        assert task_id == "fallback_task"
        assert (
            st.status == StepStatus.FAILED
        ), f"All agents failed; expected FAILED status; got {st.status}"
        # Structured handoff shape (no bare 'error' key).
        assert (
            result.get("handoff") is True
        ), f"Exhaustion must emit a structured handoff; got {result}"
        assert result["subtask_id"] == "fallback_task"
        assert result["failure_type"] == "all_agents_exhausted"
        assert result["attempted_agents"] == ["a1", "a2", "a3"]
        # Each attempted agent's failure captured as a partial result.
        assert set(result["partial_results"]) == {"a1", "a2", "a3"}
        assert result["suggested_next_action"], "must suggest a next action"
        assert "fallback_task" in result["suggested_next_action"]
        # All three agents attempted
        assert call_log == [
            "a1",
            "a2",
            "a3",
        ], f"All agents should be tried before giving up; log={call_log}"

    @pytest.mark.asyncio
    async def test_failed_subtask_does_not_poison_independent_sibling(self):
        """Test 12: One subtask exhausts all agents (FAILED) while an independent
        sibling succeeds → plan-level results reflect both accurately.
        """
        orch = OrchestratorAgent()
        cap = CapabilitySet.from_types(CapabilityType.CODE_GENERATION)

        call_log: list[str] = []
        fail_stub = _make_stub("fail_agent", cap, raises=True, call_log=call_log)
        ok_stub = _make_stub(
            "ok_agent",
            cap,
            raises=False,
            return_value={"output": "sibling_result"},
            call_log=call_log,
        )

        orch._agents["fail_agent"] = fail_stub
        orch._agent_capabilities["fail_agent"] = cap
        orch._agents["ok_agent"] = ok_stub
        orch._agent_capabilities["ok_agent"] = cap

        # Two independent subtasks (no dependencies between them)
        # Note: descriptions must be >=10 chars to pass CodeGenerationInput validation
        # so _resolve_task_input does not throw before run() is reached.
        failing_st = SubTask(
            id="failing_task",
            description="Generate some code that will intentionally fail",
            required_capabilities=[CapabilityType.CODE_GENERATION],
            dependencies=[],
        )
        failing_st.assigned_agent = "fail_agent"
        orch._subtasks["failing_task"] = failing_st
        orch._fallback_chains["failing_task"] = []  # No fallbacks

        sibling_st = SubTask(
            id="sibling_task",
            description="Generate some code for the sibling task that succeeds",
            required_capabilities=[CapabilityType.CODE_GENERATION],
            dependencies=[],
        )
        sibling_st.assigned_agent = "ok_agent"
        orch._subtasks["sibling_task"] = sibling_st
        orch._fallback_chains["sibling_task"] = []

        from agentic_v2.agents.orchestrator import OrchestratorInput

        plan_result = await orch._execute_plan(
            OrchestratorInput(task="test", max_parallel=5)
        )

        # failing_task should be recorded as a structured handoff (ARP-3)
        assert "failing_task" in plan_result, "failing_task must appear in plan results"
        assert plan_result["failing_task"].get("handoff") is True, (
            f"failing_task should carry a structured handoff; "
            f"got {plan_result['failing_task']}"
        )

        # sibling_task should have succeeded independently
        assert "sibling_task" in plan_result, "sibling_task must appear in plan results"
        sibling_result = plan_result["sibling_task"]
        assert not (
            isinstance(sibling_result, dict) and sibling_result.get("handoff")
        ), f"sibling_task should NOT have escalated; got {sibling_result}"
        # Both tasks attempted (order may vary due to asyncio.gather)
        assert "fail_agent" in call_log
        assert "ok_agent" in call_log

        # Verify status flags on the subtask objects
        assert failing_st.status == StepStatus.FAILED
        assert sibling_st.status == StepStatus.SUCCESS


# ---------------------------------------------------------------------------
# Batch-merge robustness: a bare gathered exception must not abort the merge
# ---------------------------------------------------------------------------


class TestRecordBatchResultsResilience:
    """_record_batch_results tolerates bare exceptions from asyncio.gather.

    ``_execute_plan`` gathers with ``return_exceptions=True``; if a subtask
    coroutine raises before returning its ``(id, result)`` tuple, the gathered
    list contains a bare ``BaseException``. The merge must record it as a failed
    subtask and still merge the rest, never aborting on a tuple-unpack error.
    """

    def test_bare_exception_does_not_abort_merge(self) -> None:
        orch = OrchestratorAgent()
        batch = [
            SubTask(
                id="t_raised",
                description="raised before returning",
                required_capabilities=[CapabilityType.CODE_GENERATION],
            ),
            SubTask(
                id="t_ok",
                description="returned normally",
                required_capabilities=[CapabilityType.CODE_GENERATION],
            ),
        ]
        # First element is a bare exception (coroutine raised); second is a
        # normal (task_id, result) tuple.
        batch_results = [
            RuntimeError("boom inside coroutine"),
            ("t_ok", {"output": "done"}),
        ]
        results: dict[str, object] = {}
        executed: set[str] = set()

        orch._record_batch_results(batch_results, results, executed, batch)

        # The healthy result is merged.
        assert results["t_ok"] == {"output": "done"}
        assert "t_ok" in executed
        # The raised subtask is recorded as a failure under its real id, not lost.
        assert "t_raised" in executed
        assert "boom inside coroutine" in results["t_raised"]["error"]

    def test_bare_exception_without_batch_uses_positional_fallback(self) -> None:
        orch = OrchestratorAgent()
        batch_results = [ValueError("no batch metadata")]
        results: dict[str, object] = {}
        executed: set[str] = set()

        # Without the batch arg the id cannot be recovered, but the merge must
        # still not raise and must record the failure under a synthetic id.
        orch._record_batch_results(batch_results, results, executed)

        assert len(results) == 1
        (only_id,) = results
        assert "no batch metadata" in results[only_id]["error"]
        assert only_id in executed
