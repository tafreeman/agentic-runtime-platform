"""Tests for workflow_pipeline -- data extraction, agent evaluation, and MD reporting.

ADR-008 Test Value Taxonomy:
- Tier 1 (High Value): Branching logic, error handling, state transitions, edge cases
- Tier 2 (Moderate): Contract validation, boundary conditions, schema correctness
- No Tier 3/4: No constructor-only, isinstance-only, or tautology tests

Covers:
- get_agent_expectations: known agent lookup vs. fallback to defaults
- evaluate_agent_output: LLM unavailable, short output, successful eval, exception path
- extract_workflow_data: plan/phase extraction, enum vs. string attrs, agent results,
  evaluation triggering, phase summary aggregation
- save_workflow_phases_md: file creation, output truncation, grade table, metadata section
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tools.agents.benchmarks.workflow_pipeline import (
    _AGENT_EXPECTATIONS,
    _DEFAULT_EXPECTATIONS,
    evaluate_agent_output,
    extract_workflow_data,
    get_agent_expectations,
    save_workflow_phases_md,
)

# ---------------------------------------------------------------------------
# Helpers — lightweight stubs for OrchestratorResult-like objects
# ---------------------------------------------------------------------------


@dataclass
class _FakeTask:
    """Minimal stub for a plan task with enum-like attributes."""

    id: str
    description: str
    agent_type: Any  # Can be enum-like or plain string
    status: Any
    priority: Any
    dependencies: list[str] = field(default_factory=list)
    expected_output: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)


@dataclass
class _FakeAgentResult:
    """Minimal stub for an agent result record."""

    id: str
    description: str
    agent_type: Any
    status: Any
    result: str | None = None
    confidence: float = 0.0
    error: str | None = None
    duration_seconds: float | None = None
    started_at: Any = None
    completed_at: Any = None


@dataclass
class _FakePlan:
    """Minimal stub for a workflow plan."""

    phases: list[list[_FakeTask]] = field(default_factory=list)
    integration_strategy: str = "sequential"


@dataclass
class _FakeOrchestratorResult:
    """Minimal stub for an OrchestratorResult."""

    task_description: str = "Test task"
    total_duration_seconds: float = 10.0
    metadata: dict[str, Any] = field(default_factory=dict)
    plan: _FakePlan | None = None
    agent_results: dict[str, _FakeAgentResult] | None = None


class _EnumLike:
    """Simple object with a .value attribute to simulate enums."""

    def __init__(self, value: str) -> None:
        self.value = value


# ---------------------------------------------------------------------------
# get_agent_expectations
# ---------------------------------------------------------------------------


class TestGetAgentExpectations:
    """Tests for agent expectations lookup and fallback."""

    @pytest.mark.parametrize("agent_type", list(_AGENT_EXPECTATIONS.keys()))
    def test_known_agent_returns_specific_expectations(self, agent_type: str):
        """Each catalogued agent type returns its own expectation dict."""
        result = get_agent_expectations(agent_type)
        assert result is _AGENT_EXPECTATIONS[agent_type]
        assert "key_qualities" in result
        assert "expected_sections" in result
        assert "success_criteria" in result

    def test_unknown_agent_falls_back_to_defaults(self):
        """An unrecognised agent type returns the generic defaults."""
        result = get_agent_expectations("unknown_agent_xyz")
        assert result is _DEFAULT_EXPECTATIONS
        assert "key_qualities" in result


# ---------------------------------------------------------------------------
# evaluate_agent_output
# ---------------------------------------------------------------------------


class TestEvaluateAgentOutput:
    """Tests for single-agent LLM evaluation wrapper."""

    def test_returns_none_when_evaluator_unavailable(self):
        """When HAS_LLM_EVALUATOR is False, returns None immediately."""
        with patch(
            "tools.agents.benchmarks.workflow_pipeline.HAS_LLM_EVALUATOR", False
        ):
            result = evaluate_agent_output(
                agent_task_id="t1",
                agent_type="analyst",
                task_description="Analyze data",
                agent_output="A" * 100,
                original_prompt="prompt",
                model="gpt-4o",
                benchmark_id="bench",
            )
        assert result is None

    @pytest.mark.parametrize(
        "output,reason_fragment",
        [
            ("", "too short or empty"),
            ("   ", "too short or empty"),
            ("short", "too short or empty"),
            ("x" * 49, "too short or empty"),
        ],
        ids=["empty", "whitespace", "very_short", "just_under_50"],
    )
    def test_short_output_returns_f_grade(self, output: str, reason_fragment: str):
        """Output shorter than 50 chars (after strip) gets score 0 / grade F."""
        with patch("tools.agents.benchmarks.workflow_pipeline.HAS_LLM_EVALUATOR", True):
            result = evaluate_agent_output(
                agent_task_id="t1",
                agent_type="analyst",
                task_description="Analyze",
                agent_output=output,
                original_prompt="prompt",
                model="gpt-4o",
                benchmark_id="bench",
            )
        assert result is not None
        assert result["score"] == 0.0
        assert result["grade"] == "F"
        assert reason_fragment in result["reason"].lower()

    def test_output_exactly_50_chars_is_not_short(self):
        """Output of exactly 50 non-whitespace chars passes the length gate."""
        mock_eval_result = MagicMock()
        mock_eval_result.overall_score = 7.5
        mock_eval_result.grade = "C"
        mock_eval_result.dimension_scores = {}
        mock_eval_result.strengths = ["good"]
        mock_eval_result.weaknesses = ["bad"]

        with (
            patch("tools.agents.benchmarks.workflow_pipeline.HAS_LLM_EVALUATOR", True),
            patch(
                "tools.agents.benchmarks.workflow_pipeline.evaluate_with_llm",
                return_value=mock_eval_result,
            ),
        ):
            result = evaluate_agent_output(
                agent_task_id="t1",
                agent_type="analyst",
                task_description="Analyze",
                agent_output="x" * 50,
                original_prompt="prompt",
                model="gpt-4o",
                benchmark_id="bench",
            )
        # Should NOT be the short-output F result
        assert result is not None
        assert result["score"] == 7.5

    def test_successful_evaluation_returns_formatted_dict(self):
        """Successful LLM eval returns score, grade, dimensions, strengths,
        weaknesses."""
        mock_dim = MagicMock()
        mock_dim.score = 8.5

        mock_eval_result = MagicMock()
        mock_eval_result.overall_score = 8.5
        mock_eval_result.grade = "B"
        mock_eval_result.dimension_scores = {"completeness": mock_dim}
        mock_eval_result.strengths = ["clear", "thorough", "extra"]
        mock_eval_result.weaknesses = ["verbose", "redundant", "extra2"]

        with (
            patch("tools.agents.benchmarks.workflow_pipeline.HAS_LLM_EVALUATOR", True),
            patch(
                "tools.agents.benchmarks.workflow_pipeline.evaluate_with_llm",
                return_value=mock_eval_result,
            ),
        ):
            result = evaluate_agent_output(
                agent_task_id="t1",
                agent_type="analyst",
                task_description="Analyze data",
                agent_output="A" * 100,
                original_prompt="prompt",
                model="gpt-4o",
                benchmark_id="bench",
            )

        assert result["score"] == 8.5
        assert result["grade"] == "B"
        assert result["dimension_scores"] == {"completeness": 8.5}
        # Strengths/weaknesses are capped at 2
        assert len(result["strengths"]) == 2
        assert len(result["weaknesses"]) == 2

    def test_evaluation_exception_returns_error_dict(self):
        """When evaluate_with_llm raises, returns F grade with error reason."""
        with (
            patch("tools.agents.benchmarks.workflow_pipeline.HAS_LLM_EVALUATOR", True),
            patch(
                "tools.agents.benchmarks.workflow_pipeline.evaluate_with_llm",
                side_effect=RuntimeError("API timeout"),
            ),
        ):
            result = evaluate_agent_output(
                agent_task_id="t1",
                agent_type="analyst",
                task_description="Analyze",
                agent_output="A" * 100,
                original_prompt="prompt",
                model="gpt-4o",
                benchmark_id="bench",
            )

        assert result["score"] == 0.0
        assert result["grade"] == "F"
        assert "API timeout" in result["reason"]

    def test_evaluation_exception_verbose_prints(self, capsys):
        """In verbose mode, evaluation exceptions are printed."""
        with (
            patch("tools.agents.benchmarks.workflow_pipeline.HAS_LLM_EVALUATOR", True),
            patch(
                "tools.agents.benchmarks.workflow_pipeline.evaluate_with_llm",
                side_effect=ValueError("bad data"),
            ),
        ):
            evaluate_agent_output(
                agent_task_id="t1",
                agent_type="analyst",
                task_description="Analyze",
                agent_output="A" * 100,
                original_prompt="prompt",
                model="gpt-4o",
                benchmark_id="bench",
                verbose=True,
            )
        captured = capsys.readouterr()
        assert "bad data" in captured.out

    def test_original_prompt_truncated_to_500_chars(self):
        """The original_prompt passed to evaluate_with_llm is capped at 500 chars."""
        long_prompt = "Z" * 1000
        mock_eval_result = MagicMock()
        mock_eval_result.overall_score = 5.0
        mock_eval_result.grade = "F"
        mock_eval_result.dimension_scores = {}
        mock_eval_result.strengths = []
        mock_eval_result.weaknesses = []

        with (
            patch("tools.agents.benchmarks.workflow_pipeline.HAS_LLM_EVALUATOR", True),
            patch(
                "tools.agents.benchmarks.workflow_pipeline.evaluate_with_llm",
                return_value=mock_eval_result,
            ) as mock_eval,
        ):
            evaluate_agent_output(
                agent_task_id="t1",
                agent_type="analyst",
                task_description="Analyze",
                agent_output="A" * 100,
                original_prompt=long_prompt,
                model="gpt-4o",
                benchmark_id="bench",
            )
        # The task_prompt arg should contain at most 500 chars of original_prompt
        call_kwargs = mock_eval.call_args[1]
        assert len(call_kwargs["task_prompt"]) < len(long_prompt)
        assert "Z" * 500 in call_kwargs["task_prompt"]
        assert "Z" * 501 not in call_kwargs["task_prompt"]


# ---------------------------------------------------------------------------
# extract_workflow_data
# ---------------------------------------------------------------------------


class TestExtractWorkflowData:
    """Tests for OrchestratorResult data extraction."""

    def test_minimal_result_no_plan_no_agents(self):
        """Result with no plan and no agent_results produces empty collections."""
        result = _FakeOrchestratorResult()
        data = extract_workflow_data(result)

        assert data["task_description"] == "Test task"
        assert data["total_duration_seconds"] == 10.0
        assert data["phases"] == []
        assert data["agent_results"] == {}
        assert data["phase_evaluations"] == {}
        assert "phase_summary" not in data

    def test_plan_phases_extracted_with_enum_values(self):
        """Phase tasks with enum-like agent_type/status/priority use .value."""
        task = _FakeTask(
            id="task-1",
            description="Do analysis",
            agent_type=_EnumLike("analyst"),
            status=_EnumLike("completed"),
            priority=_EnumLike("high"),
            dependencies=["task-0"],
            expected_output="analysis report",
            inputs={"data": "input.csv"},
        )
        plan = _FakePlan(phases=[[task]], integration_strategy="parallel")
        result = _FakeOrchestratorResult(plan=plan)

        data = extract_workflow_data(result)

        assert len(data["phases"]) == 1
        phase = data["phases"][0]
        assert phase["phase_number"] == 1
        assert len(phase["tasks"]) == 1

        task_data = phase["tasks"][0]
        assert task_data["task_id"] == "task-1"
        assert task_data["agent_type"] == "analyst"
        assert task_data["status"] == "completed"
        assert task_data["priority"] == "high"
        assert task_data["dependencies"] == ["task-0"]
        assert data["integration_strategy"] == "parallel"

    def test_plan_phases_extracted_with_plain_strings(self):
        """Phase tasks with plain string attrs (no .value) use str()."""
        task = _FakeTask(
            id="task-2",
            description="Do research",
            agent_type="researcher",
            status="pending",
            priority="medium",
        )
        plan = _FakePlan(phases=[[task]])
        result = _FakeOrchestratorResult(plan=plan)

        data = extract_workflow_data(result)
        task_data = data["phases"][0]["tasks"][0]
        assert task_data["agent_type"] == "researcher"
        assert task_data["status"] == "pending"
        assert task_data["priority"] == "medium"

    def test_multiple_phases_and_tasks(self):
        """Multiple phases with multiple tasks are all extracted."""
        t1 = _FakeTask("t1", "Step 1", "analyst", "done", "high")
        t2 = _FakeTask("t2", "Step 2", "researcher", "done", "medium")
        t3 = _FakeTask("t3", "Step 3", "strategist", "pending", "low")
        plan = _FakePlan(phases=[[t1, t2], [t3]])
        result = _FakeOrchestratorResult(plan=plan)

        data = extract_workflow_data(result)
        assert len(data["phases"]) == 2
        assert len(data["phases"][0]["tasks"]) == 2
        assert len(data["phases"][1]["tasks"]) == 1
        assert data["phases"][1]["phase_number"] == 2

    def test_agent_results_with_timestamps(self):
        """Agent results include ISO-formatted timestamps when present."""
        from datetime import datetime

        started = datetime(2025, 1, 15, 10, 0, 0)
        completed = datetime(2025, 1, 15, 10, 5, 0)
        agent = _FakeAgentResult(
            id="t1",
            description="Analyze",
            agent_type=_EnumLike("analyst"),
            status=_EnumLike("completed"),
            result="Analysis output here",
            confidence=0.95,
            duration_seconds=300.0,
            started_at=started,
            completed_at=completed,
        )
        result = _FakeOrchestratorResult(
            agent_results={"t1": agent},
        )

        data = extract_workflow_data(result)
        agent_data = data["agent_results"]["t1"]
        assert agent_data["started_at"] == "2025-01-15T10:00:00"
        assert agent_data["completed_at"] == "2025-01-15T10:05:00"
        assert agent_data["confidence"] == 0.95
        assert agent_data["duration_seconds"] == 300.0

    def test_agent_results_with_none_timestamps(self):
        """Agent results handle None timestamps gracefully."""
        agent = _FakeAgentResult(
            id="t1",
            description="Analyze",
            agent_type="analyst",
            status="completed",
        )
        result = _FakeOrchestratorResult(agent_results={"t1": agent})

        data = extract_workflow_data(result)
        agent_data = data["agent_results"]["t1"]
        assert agent_data["started_at"] is None
        assert agent_data["completed_at"] is None

    def test_agent_result_with_none_result_field(self):
        """Agent with result=None gets output as empty string."""
        agent = _FakeAgentResult(
            id="t1",
            description="Analyze",
            agent_type="analyst",
            status="failed",
            result=None,
            error="Timeout",
        )
        result = _FakeOrchestratorResult(agent_results={"t1": agent})

        data = extract_workflow_data(result)
        agent_data = data["agent_results"]["t1"]
        assert agent_data["output"] == ""
        assert agent_data["error"] == "Timeout"

    def test_evaluate_phases_triggers_evaluation(self):
        """With evaluate_phases=True, agent outputs are scored."""
        agent = _FakeAgentResult(
            id="t1",
            description="Analyze data",
            agent_type="analyst",
            status="completed",
            result="A" * 100,
        )
        result = _FakeOrchestratorResult(agent_results={"t1": agent})

        mock_eval = {"score": 8.0, "grade": "B"}
        with patch(
            "tools.agents.benchmarks.workflow_pipeline.evaluate_agent_output",
            return_value=mock_eval,
        ):
            data = extract_workflow_data(
                result,
                evaluate_phases=True,
                model="gpt-4o",
                benchmark_id="bench",
                original_prompt="prompt",
            )

        assert data["phase_evaluations"]["t1"] == mock_eval
        assert data["agent_results"]["t1"]["evaluation"] == mock_eval

    def test_evaluate_phases_skipped_without_model(self):
        """evaluate_phases=True but model=None skips evaluation."""
        agent = _FakeAgentResult(
            id="t1",
            description="Analyze",
            agent_type="analyst",
            status="completed",
            result="A" * 100,
        )
        result = _FakeOrchestratorResult(agent_results={"t1": agent})

        with patch(
            "tools.agents.benchmarks.workflow_pipeline.evaluate_agent_output",
        ) as mock_fn:
            data = extract_workflow_data(
                result,
                evaluate_phases=True,
                model=None,
            )
        mock_fn.assert_not_called()
        assert data["phase_evaluations"] == {}

    def test_evaluate_phases_skipped_for_empty_output(self):
        """evaluate_phases=True but empty agent output skips evaluation."""
        agent = _FakeAgentResult(
            id="t1",
            description="Analyze",
            agent_type="analyst",
            status="failed",
            result=None,
        )
        result = _FakeOrchestratorResult(agent_results={"t1": agent})

        with patch(
            "tools.agents.benchmarks.workflow_pipeline.evaluate_agent_output",
        ) as mock_fn:
            extract_workflow_data(
                result,
                evaluate_phases=True,
                model="gpt-4o",
            )
        mock_fn.assert_not_called()

    def test_phase_summary_computed_from_evaluations(self):
        """Phase summary aggregates scores correctly across agents."""
        agents = {
            "t1": _FakeAgentResult("t1", "A", "analyst", "done", result="A" * 100),
            "t2": _FakeAgentResult("t2", "B", "researcher", "done", result="B" * 100),
        }
        result = _FakeOrchestratorResult(agent_results=agents)

        evals = {
            "t1": {"score": 9.0, "grade": "A"},
            "t2": {"score": 7.0, "grade": "C"},
        }

        with patch(
            "tools.agents.benchmarks.workflow_pipeline.evaluate_agent_output",
            side_effect=lambda **kw: evals.get(kw["agent_task_id"]),
        ):
            data = extract_workflow_data(
                result,
                evaluate_phases=True,
                model="gpt-4o",
                benchmark_id="bench",
            )

        summary = data["phase_summary"]
        assert summary["total_agents"] == 2
        assert summary["average_score"] == pytest.approx(8.0)
        assert summary["min_score"] == pytest.approx(7.0)
        assert summary["max_score"] == pytest.approx(9.0)
        assert summary["scores_by_agent"]["t1"] == 9.0
        assert summary["scores_by_agent"]["t2"] == 7.0

    def test_original_prompt_falls_back_to_task_description(self):
        """When original_prompt is None, task_description is used as fallback."""
        agent = _FakeAgentResult(
            id="t1",
            description="Analyze",
            agent_type="analyst",
            status="completed",
            result="A" * 100,
        )
        result = _FakeOrchestratorResult(
            task_description="Fallback description",
            agent_results={"t1": agent},
        )

        with patch(
            "tools.agents.benchmarks.workflow_pipeline.evaluate_agent_output",
            return_value={"score": 5.0, "grade": "F"},
        ) as mock_fn:
            extract_workflow_data(
                result,
                evaluate_phases=True,
                model="gpt-4o",
                benchmark_id="bench",
                original_prompt=None,
            )

        call_kwargs = mock_fn.call_args[1]
        assert call_kwargs["original_prompt"] == "Fallback description"


# ---------------------------------------------------------------------------
# save_workflow_phases_md
# ---------------------------------------------------------------------------


class TestSaveWorkflowPhasesMd:
    """Tests for Markdown report generation and persistence."""

    def test_creates_file_with_correct_name(self, tmp_path: Path):
        """Output file is named task_<id>_phases.md in the given directory."""
        data: dict[str, Any] = {
            "total_duration_seconds": 5.0,
            "integration_strategy": "sequential",
            "phases": [],
            "agent_results": {},
            "phase_evaluations": {},
            "metadata": {},
        }
        save_workflow_phases_md(data, "my_task", tmp_path)
        expected = tmp_path / "task_my_task_phases.md"
        assert expected.exists()

    def test_header_contains_task_id_and_duration(self, tmp_path: Path):
        """The Markdown header includes the task ID and duration."""
        data: dict[str, Any] = {
            "total_duration_seconds": 42.7,
            "integration_strategy": "parallel",
            "phases": [],
            "agent_results": {},
            "phase_evaluations": {},
            "metadata": {},
        }
        save_workflow_phases_md(data, "abc123", tmp_path)
        content = (tmp_path / "task_abc123_phases.md").read_text(encoding="utf-8")
        assert "# Workflow Phases: Task abc123" in content
        assert "42.7s" in content
        assert "parallel" in content

    def test_phase_tasks_rendered(self, tmp_path: Path):
        """Phase tasks are rendered with task ID, agent type, status, description."""
        data: dict[str, Any] = {
            "total_duration_seconds": 1.0,
            "phases": [
                {
                    "phase_number": 1,
                    "tasks": [
                        {
                            "task_id": "step-1",
                            "agent_type": "analyst",
                            "status": "completed",
                            "description": "Analyze the data thoroughly",
                        }
                    ],
                }
            ],
            "agent_results": {},
            "phase_evaluations": {},
            "metadata": {},
        }
        save_workflow_phases_md(data, "t1", tmp_path)
        content = (tmp_path / "task_t1_phases.md").read_text(encoding="utf-8")
        assert "## Phase 1" in content
        assert "step-1" in content
        assert "analyst" in content
        assert "completed" in content
        assert "Analyze the data thoroughly" in content

    def test_agent_output_included(self, tmp_path: Path):
        """Agent output is rendered in a code block."""
        data: dict[str, Any] = {
            "total_duration_seconds": 1.0,
            "phases": [
                {
                    "phase_number": 1,
                    "tasks": [
                        {
                            "task_id": "t1",
                            "agent_type": "a",
                            "status": "done",
                            "description": "d",
                        }
                    ],
                }
            ],
            "agent_results": {
                "t1": {"output": "Here is my analysis", "duration_seconds": 5.2}
            },
            "phase_evaluations": {},
            "metadata": {},
        }
        save_workflow_phases_md(data, "t1", tmp_path)
        content = (tmp_path / "task_t1_phases.md").read_text(encoding="utf-8")
        assert "Here is my analysis" in content
        assert "5.2s" in content

    def test_output_truncated_at_3000_chars(self, tmp_path: Path):
        """Output longer than 3000 chars is truncated with a notice."""
        long_output = "X" * 5000
        data: dict[str, Any] = {
            "total_duration_seconds": 1.0,
            "phases": [
                {
                    "phase_number": 1,
                    "tasks": [
                        {
                            "task_id": "t1",
                            "agent_type": "a",
                            "status": "done",
                            "description": "d",
                        }
                    ],
                }
            ],
            "agent_results": {"t1": {"output": long_output}},
            "phase_evaluations": {},
            "metadata": {},
        }
        save_workflow_phases_md(data, "t1", tmp_path)
        content = (tmp_path / "task_t1_phases.md").read_text(encoding="utf-8")
        assert "truncated" in content.lower()
        assert "5000 chars total" in content
        # The full 5000-char string should NOT appear
        assert long_output not in content

    def test_no_output_shows_none_label(self, tmp_path: Path):
        """When agent has no output, '(none)' is displayed."""
        data: dict[str, Any] = {
            "total_duration_seconds": 1.0,
            "phases": [
                {
                    "phase_number": 1,
                    "tasks": [
                        {
                            "task_id": "t1",
                            "agent_type": "a",
                            "status": "done",
                            "description": "d",
                        }
                    ],
                }
            ],
            "agent_results": {"t1": {"output": ""}},
            "phase_evaluations": {},
            "metadata": {},
        }
        save_workflow_phases_md(data, "t1", tmp_path)
        content = (tmp_path / "task_t1_phases.md").read_text(encoding="utf-8")
        assert "(none)" in content

    def test_phase_evaluation_rendered(self, tmp_path: Path):
        """Phase evaluations with dimensions, strengths, weaknesses appear in output."""
        data: dict[str, Any] = {
            "total_duration_seconds": 1.0,
            "phases": [
                {
                    "phase_number": 1,
                    "tasks": [
                        {
                            "task_id": "t1",
                            "agent_type": "analyst",
                            "status": "done",
                            "description": "d",
                        }
                    ],
                }
            ],
            "agent_results": {"t1": {"output": "analysis here"}},
            "phase_evaluations": {
                "t1": {
                    "score": 8.5,
                    "grade": "B",
                    "dimension_scores": {"completeness": 9.0, "quality": 8.0},
                    "strengths": ["clear", "thorough"],
                    "weaknesses": ["verbose"],
                }
            },
            "metadata": {},
        }
        save_workflow_phases_md(data, "t1", tmp_path)
        content = (tmp_path / "task_t1_phases.md").read_text(encoding="utf-8")
        assert "8.5/10" in content
        assert "Grade: B" in content
        assert "completeness: 9.0" in content
        assert "quality: 8.0" in content
        assert "clear" in content
        assert "verbose" in content

    @pytest.mark.parametrize(
        "score,expected_grade",
        [
            (9.5, "A"),
            (9.0, "A"),
            (8.5, "B"),
            (8.0, "B"),
            (7.5, "C"),
            (7.0, "C"),
            (6.5, "D"),
            (6.0, "D"),
            (5.0, "F"),
            (3.0, "F"),
        ],
    )
    def test_summary_grade_table_thresholds(
        self, tmp_path: Path, score: float, expected_grade: str
    ):
        """Phase summary grade table assigns correct letter grades per threshold."""
        data: dict[str, Any] = {
            "total_duration_seconds": 1.0,
            "phases": [],
            "agent_results": {},
            "phase_evaluations": {},
            "phase_summary": {
                "total_agents": 1,
                "average_score": score,
                "min_score": score,
                "max_score": score,
                "scores_by_agent": {"agent-1": score},
            },
            "metadata": {},
        }
        save_workflow_phases_md(data, "t1", tmp_path)
        content = (tmp_path / "task_t1_phases.md").read_text(encoding="utf-8")
        assert "Phase Evaluation Summary" in content
        assert f"| agent-1 | {score:.1f} | {expected_grade} |" in content

    def test_metadata_section_rendered_as_json(self, tmp_path: Path):
        """Metadata dict is rendered as a JSON code block."""
        data: dict[str, Any] = {
            "total_duration_seconds": 1.0,
            "phases": [],
            "agent_results": {},
            "phase_evaluations": {},
            "metadata": {"model": "gpt-4o", "version": "1.0"},
        }
        save_workflow_phases_md(data, "t1", tmp_path)
        content = (tmp_path / "task_t1_phases.md").read_text(encoding="utf-8")
        assert "## Workflow Metadata" in content
        assert '"model": "gpt-4o"' in content
        assert '"version": "1.0"' in content

    def test_empty_metadata_omits_section(self, tmp_path: Path):
        """Empty metadata dict means no Workflow Metadata section."""
        data: dict[str, Any] = {
            "total_duration_seconds": 1.0,
            "phases": [],
            "agent_results": {},
            "phase_evaluations": {},
            "metadata": {},
        }
        save_workflow_phases_md(data, "t1", tmp_path)
        content = (tmp_path / "task_t1_phases.md").read_text(encoding="utf-8")
        assert "Workflow Metadata" not in content

    def test_no_phase_summary_omits_summary_section(self, tmp_path: Path):
        """When no phase_summary key exists, the summary section is skipped."""
        data: dict[str, Any] = {
            "total_duration_seconds": 1.0,
            "phases": [],
            "agent_results": {},
            "phase_evaluations": {},
            "metadata": {},
        }
        save_workflow_phases_md(data, "t1", tmp_path)
        content = (tmp_path / "task_t1_phases.md").read_text(encoding="utf-8")
        assert "Phase Evaluation Summary" not in content
