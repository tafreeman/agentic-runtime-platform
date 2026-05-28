"""Tests for benchmark pipelines -- evaluation_pipeline and workflow_pipeline.

Covers:
- evaluation_pipeline: evaluate_task_output_llm, get_gold_standard_for_task,
  evaluate_task_output_legacy, print_mismatch_analysis, save_evaluation_report_legacy
- workflow_pipeline: get_agent_expectations, evaluate_agent_output,
  extract_workflow_data, save_workflow_phases_md
- Error propagation through pipeline stages
- Input/output contracts between stages
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tools.agents.benchmarks.evaluator_models import (
    DimensionScore,
    EvaluationResult,
)
from tools.agents.benchmarks.loader import BenchmarkTask

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_task() -> BenchmarkTask:
    """Create a minimal BenchmarkTask for testing."""
    return BenchmarkTask(
        task_id="task_001",
        benchmark_id="test_bench",
        prompt="Write a REST API for user management",
        expected_output="A complete REST API implementation",
        test_cases=[{"input": "GET /users", "expected": "200 OK"}],
    )


@pytest.fixture()
def sample_eval_result() -> EvaluationResult:
    """Create a sample EvaluationResult for testing."""
    return EvaluationResult(
        task_id="task_001",
        model="gpt-4o-mini",
        benchmark_id="test_bench",
        timestamp=datetime.now().isoformat(),
        dimension_scores={
            "completeness": DimensionScore(
                dimension="completeness",
                score=8.0,
                reasoning="Good",
                weight=0.25,
            ),
            "correctness": DimensionScore(
                dimension="correctness",
                score=7.0,
                reasoning="Ok",
                weight=0.25,
            ),
        },
        overall_score=7.5,
        grade="C",
        strengths=["clear structure"],
        weaknesses=["missing tests"],
    )


# ===========================================================================
# evaluation_pipeline tests
# ===========================================================================


class TestEvaluateTaskOutputLlm:
    """Tests for evaluate_task_output_llm."""

    @patch("tools.agents.benchmarks.evaluation_pipeline.HAS_LLM_EVALUATOR", True)
    @patch("tools.agents.benchmarks.evaluation_pipeline.evaluate_with_llm")
    @patch("tools.agents.benchmarks.evaluation_pipeline.get_gold_standard_for_task")
    @patch("tools.agents.benchmarks.evaluation_pipeline.print_evaluation_report")
    def test_successful_evaluation(
        self, mock_print, mock_gold, mock_eval, sample_task, sample_eval_result
    ):
        """Successful LLM evaluation returns result dict."""
        mock_gold.return_value = {"expected_output": "some output"}
        mock_eval.return_value = sample_eval_result

        from tools.agents.benchmarks.evaluation_pipeline import evaluate_task_output_llm

        result = evaluate_task_output_llm(
            task=sample_task,
            output="Generated API code",
            model="gpt-4o-mini",
            benchmark_id="test",
            verbose=True,
        )

        assert result is not None
        assert result["overall_score"] == 7.5
        mock_eval.assert_called_once()

    @patch("tools.agents.benchmarks.evaluation_pipeline.HAS_LLM_EVALUATOR", False)
    @patch("tools.agents.benchmarks.evaluation_pipeline.HAS_GOLD_STANDARD", False)
    def test_fallback_when_no_evaluator(self, sample_task):
        """Falls back to legacy when LLM evaluator unavailable."""
        from tools.agents.benchmarks.evaluation_pipeline import evaluate_task_output_llm

        result = evaluate_task_output_llm(
            task=sample_task,
            output="output",
            model="gpt-4o-mini",
            benchmark_id="test",
        )
        # Legacy also unavailable, so returns None
        assert result is None

    @patch("tools.agents.benchmarks.evaluation_pipeline.HAS_LLM_EVALUATOR", True)
    @patch("tools.agents.benchmarks.evaluation_pipeline.evaluate_with_llm")
    @patch("tools.agents.benchmarks.evaluation_pipeline.get_gold_standard_for_task")
    @patch("tools.agents.benchmarks.evaluation_pipeline.print_evaluation_report")
    @patch("tools.agents.benchmarks.evaluation_pipeline.save_evaluation_report")
    def test_saves_report_when_output_dir(
        self,
        mock_save,
        mock_print,
        mock_gold,
        mock_eval,
        sample_task,
        sample_eval_result,
        tmp_path,
    ):
        """When output_dir is provided, report is saved."""
        mock_gold.return_value = {}
        mock_eval.return_value = sample_eval_result

        from tools.agents.benchmarks.evaluation_pipeline import evaluate_task_output_llm

        evaluate_task_output_llm(
            task=sample_task,
            output="output",
            model="gpt-4o-mini",
            benchmark_id="test",
            output_dir=tmp_path,
        )
        mock_save.assert_called_once()

    @patch("tools.agents.benchmarks.evaluation_pipeline.HAS_LLM_EVALUATOR", True)
    @patch("tools.agents.benchmarks.evaluation_pipeline.evaluate_with_llm")
    @patch("tools.agents.benchmarks.evaluation_pipeline.get_gold_standard_for_task")
    @patch("tools.agents.benchmarks.evaluation_pipeline.print_evaluation_report")
    def test_creates_minimal_gold_when_none_found(
        self,
        mock_print,
        mock_gold,
        mock_eval,
        sample_task,
        sample_eval_result,
    ):
        """When no gold standard found, creates minimal one from task data."""
        mock_gold.return_value = None
        mock_eval.return_value = sample_eval_result

        from tools.agents.benchmarks.evaluation_pipeline import evaluate_task_output_llm

        evaluate_task_output_llm(
            task=sample_task,
            output="output",
            model="gpt-4o-mini",
            benchmark_id="test",
            verbose=True,
        )

        # evaluate_with_llm should have been called with a gold_standard dict
        call_kwargs = mock_eval.call_args
        gold = call_kwargs[1]["gold_standard"] if call_kwargs[1] else call_kwargs[0][3]
        assert "expected_output" in gold


class TestGetGoldStandardForTask:
    """Tests for get_gold_standard_for_task."""

    @patch("tools.agents.benchmarks.evaluation_pipeline.HAS_GOLD_STANDARD", False)
    def test_returns_none_when_unavailable(self, sample_task):
        """Returns None when gold standard module is not available."""
        from tools.agents.benchmarks.evaluation_pipeline import (
            get_gold_standard_for_task,
        )

        assert get_gold_standard_for_task(sample_task) is None


class TestPrintMismatchAnalysis:
    """Tests for print_mismatch_analysis."""

    def test_no_issues(self, capsys):
        """When all criteria met, prints success message."""
        from tools.agents.benchmarks.evaluation_pipeline import print_mismatch_analysis

        eval_result: dict[str, Any] = {}
        print_mismatch_analysis(eval_result, {}, "output")
        captured = capsys.readouterr()
        assert "All gold standard criteria met" in captured.out

    def test_missing_components_printed(self, capsys):
        """Missing components are listed."""
        from tools.agents.benchmarks.evaluation_pipeline import print_mismatch_analysis

        eval_result = {"components": {"missing": ["auth module", "database layer"]}}
        print_mismatch_analysis(eval_result, {}, "some output text")
        captured = capsys.readouterr()
        assert "MISSING COMPONENTS" in captured.out
        assert "auth module" in captured.out

    def test_missing_patterns_printed(self, capsys):
        """Missing patterns are listed."""
        from tools.agents.benchmarks.evaluation_pipeline import print_mismatch_analysis

        eval_result = {"patterns": {"missing": [r"def \w+\("]}}
        print_mismatch_analysis(eval_result, {}, "output")
        captured = capsys.readouterr()
        assert "MISSING PATTERNS" in captured.out


class TestSaveEvaluationReportLegacy:
    """Tests for save_evaluation_report_legacy."""

    def test_creates_markdown_file(self, tmp_path):
        """Legacy report is saved as a Markdown file."""
        from tools.agents.benchmarks.evaluation_pipeline import (
            save_evaluation_report_legacy,
        )

        eval_result = {
            "overall_score": 75.0,
            "grade": "C",
            "components": {"score": 80, "matched": ["auth"], "missing": ["db"]},
            "patterns": {"score": 70, "matched": [], "missing": []},
            "decisions": {"score": 60, "matched": [], "missing": []},
            "endpoints": {"score": 50, "matched": [], "missing": []},
            "tables": {"score": 90, "matched": [], "missing": []},
        }
        gold_data = {
            "required_components": ["auth"],
            "required_patterns": [],
            "key_decisions": [],
            "api_endpoints": [{"method": "GET", "path": "/api/test"}],
            "database_tables": [],
        }

        save_evaluation_report_legacy(
            "001", eval_result, gold_data, "output text", tmp_path
        )

        report_file = tmp_path / "task_001_evaluation.md"
        assert report_file.exists()
        content = report_file.read_text()
        assert "Evaluation Report" in content
        assert "75.0" in content


# ===========================================================================
# workflow_pipeline tests
# ===========================================================================


class TestGetAgentExpectations:
    """Tests for get_agent_expectations."""

    def test_known_agent_type(self):
        """Known agent types return specific expectations."""
        from tools.agents.benchmarks.workflow_pipeline import get_agent_expectations

        result = get_agent_expectations("analyst")
        assert "Deep analysis" in result["key_qualities"]
        assert "KEY FINDINGS" in result["expected_sections"]

    @pytest.mark.parametrize(
        "agent_type",
        ["analyst", "researcher", "strategist", "implementer", "validator"],
    )
    def test_all_known_agents_have_expectations(self, agent_type: str):
        """All defined agent types have expectations with required keys."""
        from tools.agents.benchmarks.workflow_pipeline import get_agent_expectations

        result = get_agent_expectations(agent_type)
        assert "key_qualities" in result
        assert "expected_sections" in result
        assert "success_criteria" in result

    def test_unknown_agent_returns_defaults(self):
        """Unknown agent types fall back to default expectations."""
        from tools.agents.benchmarks.workflow_pipeline import get_agent_expectations

        result = get_agent_expectations("unknown_agent")
        assert "Clear, relevant" in result["key_qualities"]


class TestEvaluateAgentOutput:
    """Tests for evaluate_agent_output."""

    @patch("tools.agents.benchmarks.workflow_pipeline.HAS_LLM_EVALUATOR", False)
    def test_returns_none_without_evaluator(self):
        """Returns None when LLM evaluator is not available."""
        from tools.agents.benchmarks.workflow_pipeline import evaluate_agent_output

        result = evaluate_agent_output(
            agent_task_id="t1",
            agent_type="analyst",
            task_description="Analyze data",
            agent_output="analysis results",
            original_prompt="Analyze this",
            model="gpt-4o",
            benchmark_id="test",
        )
        assert result is None

    @patch("tools.agents.benchmarks.workflow_pipeline.HAS_LLM_EVALUATOR", True)
    def test_short_output_returns_failure(self):
        """Very short output returns immediate F grade."""
        from tools.agents.benchmarks.workflow_pipeline import evaluate_agent_output

        result = evaluate_agent_output(
            agent_task_id="t1",
            agent_type="analyst",
            task_description="Analyze data",
            agent_output="short",
            original_prompt="prompt",
            model="m",
            benchmark_id="b",
        )
        assert result["score"] == 0.0
        assert result["grade"] == "F"
        assert "too short" in result["reason"]

    @patch("tools.agents.benchmarks.workflow_pipeline.HAS_LLM_EVALUATOR", True)
    def test_empty_output_returns_failure(self):
        """Empty output returns immediate F grade."""
        from tools.agents.benchmarks.workflow_pipeline import evaluate_agent_output

        result = evaluate_agent_output(
            agent_task_id="t1",
            agent_type="analyst",
            task_description="Analyze data",
            agent_output="",
            original_prompt="prompt",
            model="m",
            benchmark_id="b",
        )
        assert result["score"] == 0.0

    @patch("tools.agents.benchmarks.workflow_pipeline.HAS_LLM_EVALUATOR", True)
    @patch("tools.agents.benchmarks.workflow_pipeline.evaluate_with_llm")
    def test_successful_agent_evaluation(self, mock_eval, sample_eval_result):
        """Successful evaluation returns compact result dict."""
        mock_eval.return_value = sample_eval_result

        from tools.agents.benchmarks.workflow_pipeline import evaluate_agent_output

        result = evaluate_agent_output(
            agent_task_id="t1",
            agent_type="analyst",
            task_description="Analyze data",
            agent_output="A detailed analysis of the data showing patterns and trends across multiple dimensions.",
            original_prompt="prompt",
            model="m",
            benchmark_id="b",
        )

        assert result["score"] == 7.5
        assert result["grade"] == "C"
        assert "dimension_scores" in result

    @patch("tools.agents.benchmarks.workflow_pipeline.HAS_LLM_EVALUATOR", True)
    @patch("tools.agents.benchmarks.workflow_pipeline.evaluate_with_llm")
    def test_evaluation_error_returns_failure(self, mock_eval):
        """When evaluate_with_llm raises, returns error dict."""
        mock_eval.side_effect = RuntimeError("LLM unavailable")

        from tools.agents.benchmarks.workflow_pipeline import evaluate_agent_output

        result = evaluate_agent_output(
            agent_task_id="t1",
            agent_type="analyst",
            task_description="Analyze data",
            agent_output="A detailed analysis covering many aspects of the problem domain and solution space.",
            original_prompt="prompt",
            model="m",
            benchmark_id="b",
        )

        assert result["score"] == 0.0
        assert "LLM unavailable" in result["reason"]


class TestExtractWorkflowData:
    """Tests for extract_workflow_data."""

    def _make_mock_result(
        self, with_plan: bool = True, with_agents: bool = True
    ) -> MagicMock:
        """Create a mock OrchestratorResult."""
        result = MagicMock()
        result.task_description = "Design a microservices architecture"
        result.total_duration_seconds = 45.2
        result.metadata = {"model": "gpt-4o-mini"}

        if with_plan:
            task_mock = MagicMock()
            task_mock.id = "t1"
            task_mock.description = "Analyze requirements"
            task_mock.agent_type.value = "analyst"
            task_mock.status.value = "completed"
            task_mock.priority.value = "high"
            task_mock.dependencies = []
            task_mock.expected_output = "analysis report"
            task_mock.inputs = {}
            result.plan.phases = [[task_mock]]
            result.plan.integration_strategy = "sequential"
        else:
            result.plan = None

        if with_agents:
            agent_task = MagicMock()
            agent_task.id = "t1"
            agent_task.description = "Analyze requirements"
            agent_task.agent_type.value = "analyst"
            agent_task.status.value = "completed"
            agent_task.result = "Detailed analysis output"
            agent_task.confidence = 0.85
            agent_task.error = None
            agent_task.duration_seconds = 12.3
            agent_task.started_at = datetime(2025, 1, 1, 10, 0, 0)
            agent_task.completed_at = datetime(2025, 1, 1, 10, 0, 12)
            result.agent_results = {"t1": agent_task}
        else:
            result.agent_results = {}

        return result

    def test_basic_extraction(self):
        """Extracts workflow data with correct structure."""
        from tools.agents.benchmarks.workflow_pipeline import extract_workflow_data

        mock_result = self._make_mock_result()
        data = extract_workflow_data(mock_result)

        assert data["task_description"] == "Design a microservices architecture"
        assert data["total_duration_seconds"] == 45.2
        assert len(data["phases"]) == 1
        assert len(data["agent_results"]) == 1
        assert "t1" in data["agent_results"]

    def test_no_plan(self):
        """Works when result has no plan."""
        from tools.agents.benchmarks.workflow_pipeline import extract_workflow_data

        mock_result = self._make_mock_result(with_plan=False)
        data = extract_workflow_data(mock_result)

        assert data["phases"] == []
        assert "integration_strategy" not in data

    def test_no_agent_results(self):
        """Works when result has no agent results."""
        from tools.agents.benchmarks.workflow_pipeline import extract_workflow_data

        mock_result = self._make_mock_result(with_agents=False)
        data = extract_workflow_data(mock_result)

        assert data["agent_results"] == {}
        assert data["phase_evaluations"] == {}


class TestSaveWorkflowPhasesMd:
    """Tests for save_workflow_phases_md."""

    def test_creates_markdown_file(self, tmp_path):
        """Saves workflow phases as a Markdown file."""
        from tools.agents.benchmarks.workflow_pipeline import save_workflow_phases_md

        workflow_data = {
            "total_duration_seconds": 30.0,
            "integration_strategy": "parallel",
            "phases": [
                {
                    "phase_number": 1,
                    "tasks": [
                        {
                            "task_id": "t1",
                            "agent_type": "analyst",
                            "status": "completed",
                            "description": "Analyze data",
                        }
                    ],
                }
            ],
            "agent_results": {
                "t1": {"output": "analysis result", "duration_seconds": 10.5}
            },
            "phase_evaluations": {},
            "metadata": {"model": "gpt-4o"},
        }

        save_workflow_phases_md(workflow_data, "001", tmp_path)

        phases_file = tmp_path / "task_001_phases.md"
        assert phases_file.exists()
        content = phases_file.read_text()
        assert "Workflow Phases" in content
        assert "Phase 1" in content
        assert "30.0s" in content

    def test_includes_evaluation_summary(self, tmp_path):
        """Phase summary section is included when evaluations exist."""
        from tools.agents.benchmarks.workflow_pipeline import save_workflow_phases_md

        workflow_data = {
            "total_duration_seconds": 30.0,
            "integration_strategy": "sequential",
            "phases": [],
            "agent_results": {},
            "phase_evaluations": {"t1": {"score": 8.0, "grade": "B"}},
            "phase_summary": {
                "total_agents": 1,
                "average_score": 8.0,
                "min_score": 8.0,
                "max_score": 8.0,
                "scores_by_agent": {"t1": 8.0},
            },
            "metadata": {},
        }

        save_workflow_phases_md(workflow_data, "002", tmp_path)

        content = (tmp_path / "task_002_phases.md").read_text()
        assert "Phase Evaluation Summary" in content
        assert "8.0" in content

    def test_truncates_long_output(self, tmp_path):
        """Long agent output is truncated to 3000 chars."""
        from tools.agents.benchmarks.workflow_pipeline import save_workflow_phases_md

        long_output = "x" * 5000
        workflow_data = {
            "total_duration_seconds": 10.0,
            "phases": [
                {
                    "phase_number": 1,
                    "tasks": [
                        {
                            "task_id": "t1",
                            "agent_type": "analyst",
                            "status": "completed",
                            "description": "Task",
                        }
                    ],
                }
            ],
            "agent_results": {"t1": {"output": long_output}},
            "phase_evaluations": {},
            "metadata": {},
        }

        save_workflow_phases_md(workflow_data, "003", tmp_path)

        content = (tmp_path / "task_003_phases.md").read_text()
        assert "truncated" in content
