"""Tests for adaptive decomposition (ARP-9).

Covers the three-phase adaptive decomposition the orchestrator performs:

1. **Investigate** — discover the files a task touches.
2. **Per-file** — derive one local analysis subtask per discovered file
   (the findings-driven branch).
3. **Cross-file** — a single integration pass depending on every per-file pass.

Also verifies that the previous hardcoded ``generate``/``review`` ``_call_model``
stub is gone: the no-backend decomposition is now derived from the task text, so
capability-scored selection is operational.

All tests are deterministic and key-free: no backend is configured, so the
adaptive path runs through the no-LLM fallbacks. Async tests need no decorator
(``asyncio_mode = "auto"``).
"""

from __future__ import annotations

import pytest

from agentic_v2.agents.capabilities import CapabilitySet, CapabilityType
from agentic_v2.agents.config import AgentConfig
from agentic_v2.agents.orchestrator import (
    _CROSS_FILE_TASK_ID,
    AdaptiveDecomposition,
    InvestigationFindings,
    OrchestratorAgent,
    _extract_file_tokens,
    _intent_decomposition,
    _latest_user_text,
)
from agentic_v2.contracts import StepStatus, TaskOutput


class TestLatestUserTextMultimodal:
    """``_latest_user_text`` must extract text from multimodal block lists.

    Regression for a refactor-review finding: ``str(content)`` on a content-block
    list leaked a serialized ``[{...}]`` repr into intent parsing.
    """

    def test_plain_string_content(self) -> None:
        assert _latest_user_text([{"role": "user", "content": "review auth.py"}]) == (
            "review auth.py"
        )

    def test_text_block_list_is_concatenated(self) -> None:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "review "},
                    {"type": "image", "source": {}},
                    {"type": "text", "text": "auth.py"},
                ],
            }
        ]
        assert _latest_user_text(messages) == "review auth.py"

    def test_string_blocks_in_list(self) -> None:
        assert _latest_user_text([{"role": "user", "content": ["a", "b"]}]) == "ab"

    def test_latest_user_message_wins(self) -> None:
        messages = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "ack"},
            {"role": "user", "content": [{"type": "text", "text": "second"}]},
        ]
        assert _latest_user_text(messages) == "second"


class _MinimalOutput(TaskOutput):
    """Minimal concrete TaskOutput for stub agents."""


def _make_analyzer_stub(name: str, call_log: list[str]):
    """Fabricate a static-analysis stub agent that records its invocations.

    Mirrors the stub pattern in ``test_orchestrator_behavior`` but self-contained
    so this module has no cross-test-module import. The orchestrator only needs
    ``config.name``/``config.description`` and an async ``run``; capabilities are
    attached via ``_stub_capability_set`` for the patched ``get_agent_capabilities``.
    """
    from unittest.mock import MagicMock

    stub = MagicMock()
    stub.config = AgentConfig(name=name, description=f"stub:{name}")

    async def _run_ok(task):
        call_log.append(name)
        return _MinimalOutput(success=True, output="analyzed")

    stub.run = _run_ok
    stub._stub_capability_set = CapabilitySet.from_types(CapabilityType.STATIC_ANALYSIS)
    return stub


def _orch_with_analyzer(name: str, call_log: list[str]) -> OrchestratorAgent:
    """Build an orchestrator whose capability lookup honors stub capability sets."""
    import agentic_v2.agents.orchestrator as _orch_module

    orch = OrchestratorAgent()
    original_get_caps = _orch_module.get_agent_capabilities

    def _patched_get_caps(agent):
        if hasattr(agent, "_stub_capability_set"):
            return agent._stub_capability_set
        return original_get_caps(agent)

    _orch_module.get_agent_capabilities = _patched_get_caps
    try:
        orch.register_agent(name, _make_analyzer_stub(name, call_log))
    finally:
        _orch_module.get_agent_capabilities = original_get_caps
    return orch


# ---------------------------------------------------------------------------
# The stub is gone: _call_model derives the plan from the task text
# ---------------------------------------------------------------------------


class TestStubReplacement:
    """The frozen generate/review constant is replaced by intent decomposition."""

    def test_review_task_yields_review_capability(self):
        """A 'review' task produces a code_review subtask (not a fixed plan)."""
        plan = _intent_decomposition("Please review the authentication module")
        caps = {c for st in plan["subtasks"] for c in st["capabilities"]}
        assert CapabilityType.CODE_REVIEW.value in caps
        # Not the old frozen plan: a pure-review task must NOT emit a 'generate'.
        ids = {st["id"] for st in plan["subtasks"]}
        assert CapabilityType.CODE_GENERATION.value not in ids

    def test_test_task_yields_test_generation(self):
        """A 'write tests' task produces a test_generation subtask."""
        plan = _intent_decomposition("Write pytest tests for the parser")
        caps = {c for st in plan["subtasks"] for c in st["capabilities"]}
        assert CapabilityType.TEST_GENERATION.value in caps

    def test_generate_and_review_chains_dependencies(self):
        """'Generate and review' yields two subtasks, review after generate."""
        plan = _intent_decomposition("Generate and review the new endpoint")
        by_id = {st["id"]: st for st in plan["subtasks"]}
        gen = CapabilityType.CODE_GENERATION.value
        rev = CapabilityType.CODE_REVIEW.value
        assert gen in by_id and rev in by_id
        # Review depends on generate (chained in declaration order).
        assert by_id[rev]["dependencies"] == [gen]

    def test_unmatched_task_falls_back_to_single_subtask(self):
        """A task with no intent keywords still produces a plan (no empty plan)."""
        plan = _intent_decomposition("xyzzy plugh frobnicate")
        assert len(plan["subtasks"]) == 1
        assert plan["subtasks"][0]["capabilities"] == [
            CapabilityType.CODE_GENERATION.value
        ]

    async def test_no_backend_decompose_task_reflects_task_text(self):
        """decompose_task on a backend-less orchestrator is content-driven."""
        orch = OrchestratorAgent()
        subtasks = await orch.decompose_task("Review and test the billing service")
        caps = {c for st in subtasks for c in st.get("capabilities", [])}
        assert CapabilityType.CODE_REVIEW.value in caps
        assert CapabilityType.TEST_GENERATION.value in caps


# ---------------------------------------------------------------------------
# File-token extraction rejects numbers/abbreviations (no phantom subtasks)
# ---------------------------------------------------------------------------


class TestExtractFileTokens:
    """_extract_file_tokens distinguishes real paths from prose/numbers."""

    @pytest.mark.parametrize(
        "text",
        [
            "the latency dropped to 3.11 seconds",
            "the price was 4.50 dollars",
            "uptime held at 99.9 percent",
            "consider the inputs, e.g. the config",
            "validate the schema, i.e. the contract",
        ],
    )
    def test_rejects_numbers_and_abbreviations(self, text: str) -> None:
        """Version numbers, decimals, and Latin abbreviations are not files."""
        assert _extract_file_tokens(text) == []

    def test_accepts_real_file_paths(self) -> None:
        """Genuine path/extension tokens are still discovered."""
        tokens = _extract_file_tokens("audit main.py and src/app/util.ts for issues")
        assert "main.py" in tokens
        assert "src/app/util.ts" in tokens

    def test_mixed_text_keeps_files_drops_noise(self) -> None:
        """Files survive even when numbers/abbreviations share the sentence."""
        tokens = _extract_file_tokens(
            "bump to 2.0 (e.g. in config.yaml) and patch a/b.py"
        )
        assert tokens == ["config.yaml", "a/b.py"]


# ---------------------------------------------------------------------------
# Investigation phase
# ---------------------------------------------------------------------------


class TestInvestigation:
    """The initial investigation discovers files from the task."""

    async def test_investigate_discovers_files_from_task_text(self):
        """File-like tokens in the task become discovered files."""
        orch = OrchestratorAgent()
        findings = await orch._investigate(
            "Audit src/auth/login.py and src/auth/session.py for issues"
        )
        assert isinstance(findings, InvestigationFindings)
        assert "src/auth/login.py" in findings.files
        assert "src/auth/session.py" in findings.files

    async def test_investigate_no_files_returns_empty(self):
        """A task naming no files yields empty findings, not invented paths."""
        orch = OrchestratorAgent()
        findings = await orch._investigate("Improve overall performance")
        assert findings.files == ()

    async def test_investigate_deduplicates_files(self):
        """The same file mentioned twice is discovered once."""
        orch = OrchestratorAgent()
        findings = await orch._investigate("Compare app.py against app.py for drift")
        assert findings.files.count("app.py") == 1


# ---------------------------------------------------------------------------
# Findings-driven per-file branch + distinct cross-file pass
# ---------------------------------------------------------------------------


class TestAdaptiveDecomposition:
    """Per-file passes are derived from findings; cross-file is distinct."""

    async def test_per_file_subtask_per_discovered_file(self):
        """One local analysis subtask is generated per discovered file."""
        orch = OrchestratorAgent()
        decomposition = await orch.decompose_adaptive(
            "Analyze a.py, b.py and c.py and reconcile them"
        )

        assert isinstance(decomposition, AdaptiveDecomposition)
        # Three files discovered -> three per-file passes.
        assert len(decomposition.per_file) == 3
        per_file_files = {st["file"] for st in decomposition.per_file}
        assert per_file_files == {"a.py", "b.py", "c.py"}
        # Every per-file pass requires static analysis and has no deps.
        for st in decomposition.per_file:
            assert st["capabilities"] == [CapabilityType.STATIC_ANALYSIS.value]
            assert st["dependencies"] == []

    async def test_cross_file_pass_is_distinct_and_depends_on_all_per_file(self):
        """A separate cross-file pass depends on every per-file pass."""
        orch = OrchestratorAgent()
        decomposition = await orch.decompose_adaptive(
            "Reconcile module_x.py and module_y.py"
        )

        cross = decomposition.cross_file
        assert cross is not None, "a cross-file integration pass must exist"
        assert cross["id"] == _CROSS_FILE_TASK_ID
        # Distinct from the per-file passes.
        per_file_ids = {st["id"] for st in decomposition.per_file}
        assert cross["id"] not in per_file_ids
        # Depends on ALL per-file passes (integration gate).
        assert set(cross["dependencies"]) == per_file_ids
        assert len(cross["dependencies"]) == 2

    async def test_no_files_means_no_cross_file_pass(self):
        """With nothing to analyze locally, there is no cross-file pass."""
        orch = OrchestratorAgent()
        decomposition = await orch.decompose_adaptive("Make the system faster")
        assert decomposition.per_file == ()
        assert decomposition.cross_file is None
        assert decomposition.subtasks == []

    async def test_run_adaptive_no_files_reports_failure(self):
        """An empty plan is a no-op, not a success — run_adaptive must fail it.

        A task naming no files yields zero subtasks; surfacing success=True there
        would mask a silent no-op (D1).
        """
        orch = OrchestratorAgent()
        result = await orch.run_adaptive("Make the system faster")
        assert result.success is False
        assert result.subtasks == []
        assert "no subtasks" in (result.error or "").lower()

    async def test_decompose_adaptive_registers_subtasks_with_dependencies(self):
        """The generated plan is installed into the orchestrator's registry."""
        orch = OrchestratorAgent()
        await orch.decompose_adaptive("Inspect one.py and two.py together")

        # Registered subtasks: 2 per-file + 1 cross-file = 3.
        assert len(orch._subtasks) == 3
        cross = orch._subtasks[_CROSS_FILE_TASK_ID]
        # Cross-file subtask gates on both per-file passes.
        assert set(cross.dependencies) == {"per_file_0", "per_file_1"}

    async def test_re_decompose_clears_prior_plan(self):
        """A second adaptive decomposition does not accumulate stale subtasks."""
        orch = OrchestratorAgent()
        await orch.decompose_adaptive("Look at first.py, second.py, third.py")
        assert len(orch._subtasks) == 4  # 3 per-file + 1 cross-file

        await orch.decompose_adaptive("Look at only.py")
        assert len(orch._subtasks) == 2  # 1 per-file + 1 cross-file
        assert "per_file_2" not in orch._subtasks


# ---------------------------------------------------------------------------
# End-to-end adaptive run: per-file in parallel, cross-file strictly after
# ---------------------------------------------------------------------------


class TestRunAdaptiveExecution:
    """run_adaptive assigns and executes the findings-derived plan."""

    def _analysis_orch(self, call_log: list[str]) -> OrchestratorAgent:
        """Orchestrator with one static-analysis agent that records calls."""
        return _orch_with_analyzer("analyzer", call_log)

    async def test_per_file_and_cross_file_assigned_to_capable_agent(self):
        """Capability scoring assigns the static-analysis agent to every pass."""
        call_log: list[str] = []
        orch = self._analysis_orch(call_log)

        result = await orch.run_adaptive("Reconcile p.py and q.py")

        assert result.success
        # 2 per-file + 1 cross-file subtasks, all assigned to the analyzer.
        assert len(result.subtasks) == 3
        assert set(result.agent_assignments.values()) == {"analyzer"}

    async def test_cross_file_runs_after_all_per_file_passes(self):
        """The cross-file subtask only becomes ready after per-file completion."""
        call_log: list[str] = []
        orch = self._analysis_orch(call_log)

        await orch.run_adaptive("Reconcile alpha.py and beta.py")

        # All three subtasks reached SUCCESS through the analyzer.
        statuses = {st.id: st.status for st in orch._subtasks.values()}
        assert statuses[_CROSS_FILE_TASK_ID] == StepStatus.SUCCESS
        for st_id, status in statuses.items():
            assert status == StepStatus.SUCCESS, f"{st_id} not successful"

        # Dependency gating: cross-file cannot be ready until both per-file done.
        ready_initial = {st.id for st in orch._find_ready_subtasks(set())}
        assert _CROSS_FILE_TASK_ID not in ready_initial
        ready_after_one = {st.id for st in orch._find_ready_subtasks({"per_file_0"})}
        assert _CROSS_FILE_TASK_ID not in ready_after_one
        ready_after_both = {
            st.id for st in orch._find_ready_subtasks({"per_file_0", "per_file_1"})
        }
        assert _CROSS_FILE_TASK_ID in ready_after_both

    async def test_run_adaptive_attaches_investigation_findings_to_trace(self):
        """The investigation findings are surfaced in the execution trace."""
        call_log: list[str] = []
        orch = self._analysis_orch(call_log)

        result = await orch.run_adaptive("Reconcile only_one.py")

        investigation = [
            entry
            for entry in result.execution_trace
            if entry.get("phase") == "investigation"
        ]
        assert investigation, "investigation phase must be recorded in the trace"
        assert "only_one.py" in investigation[0]["findings"]["files"]
