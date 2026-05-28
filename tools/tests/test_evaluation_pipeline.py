"""Tests for evaluation_pipeline -- task evaluation routing, gold standard lookup,
legacy fallback, mismatch analysis, and report persistence.

Follows ADR-008 Test Value Taxonomy:
  Tier 1: Branching logic, error paths, state transitions, ID matching strategies
  Tier 2: Contract validation, boundary conditions, output formatting

Covers:
- evaluate_task_output_llm fallback to legacy when LLM evaluator unavailable
- evaluate_task_output_llm gold data creation, report saving, verbose/compact output
- get_gold_standard_for_task with string, formatted, int, and non-numeric IDs
- evaluate_task_output_legacy guard checks, matching, report saving
- print_mismatch_analysis for each issue type and clean-pass scenario
- save_evaluation_report_legacy markdown structure and api_endpoints formatting
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

import tools.agents.benchmarks.evaluation_pipeline as pipeline
from tools.agents.benchmarks.loader import BenchmarkTask

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task(
    task_id: str = "1",
    prompt: str = "Do the thing",
    expected_output: str | None = None,
    test_cases: list[dict[str, Any]] | None = None,
) -> BenchmarkTask:
    """Create a minimal BenchmarkTask for testing."""
    return BenchmarkTask(
        task_id=task_id,
        benchmark_id="test_bench",
        prompt=prompt,
        expected_output=expected_output,
        test_cases=test_cases or [],
    )


@dataclass
class _FakeTestTask:
    """Minimal stand-in for the gold-standard TEST_TASKS entry."""

    id: int
    _gold: dict[str, Any] = field(default_factory=dict)

    def get_gold_standard(self) -> dict[str, Any] | None:
        return self._gold or None


def _make_eval_result(**overrides: Any) -> MagicMock:
    """Return a mock EvaluationResult with sensible defaults."""
    result = MagicMock()
    result.overall_score = overrides.get("overall_score", 7.5)
    result.grade = overrides.get("grade", "C")
    result.to_dict.return_value = {
        "task_id": overrides.get("task_id", "1"),
        "overall_score": result.overall_score,
        "grade": result.grade,
    }
    return result


# ===========================================================================
# get_gold_standard_for_task
# ===========================================================================


class TestGetGoldStandardForTask:
    """Tier 1: branching logic in gold-standard lookup."""

    def test_returns_none_when_gold_standard_module_unavailable(self):
        """When HAS_GOLD_STANDARD is False, return None immediately."""
        with patch.object(pipeline, "HAS_GOLD_STANDARD", False):
            result = pipeline.get_gold_standard_for_task(_make_task("42"))
        assert result is None

    def test_matches_by_string_id(self):
        """Direct string match: task.task_id == str(tt.id)."""
        gold = {"expected_output": "fib code"}
        fake_tt = _FakeTestTask(id=7, _gold=gold)
        with (
            patch.object(pipeline, "HAS_GOLD_STANDARD", True),
            patch.object(pipeline, "TEST_TASKS", [fake_tt]),
        ):
            result = pipeline.get_gold_standard_for_task(_make_task("7"))
        assert result == gold

    def test_matches_by_formatted_id(self):
        """Formatted match: task_id == f'task_{tt.id:03d}'."""
        gold = {"expected_output": "formatted"}
        fake_tt = _FakeTestTask(id=3, _gold=gold)
        with (
            patch.object(pipeline, "HAS_GOLD_STANDARD", True),
            patch.object(pipeline, "TEST_TASKS", [fake_tt]),
        ):
            result = pipeline.get_gold_standard_for_task(_make_task("task_003"))
        assert result == gold

    def test_matches_by_int_conversion(self):
        """Integer fallback: int(task_id) == tt.id."""
        gold = {"expected_output": "int-matched"}
        fake_tt = _FakeTestTask(id=42, _gold=gold)
        # task_id "42" should match via int conversion (also matches string,
        # but the branch is still exercised)
        with (
            patch.object(pipeline, "HAS_GOLD_STANDARD", True),
            patch.object(pipeline, "TEST_TASKS", [fake_tt]),
        ):
            result = pipeline.get_gold_standard_for_task(_make_task("42"))
        assert result == gold

    def test_handles_non_numeric_task_id_gracefully(self):
        """Non-numeric task_id does not raise -- ValueError is caught."""
        fake_tt = _FakeTestTask(id=1, _gold={"k": "v"})
        with (
            patch.object(pipeline, "HAS_GOLD_STANDARD", True),
            patch.object(pipeline, "TEST_TASKS", [fake_tt]),
        ):
            # "alpha" cannot be int(), but should not raise
            result = pipeline.get_gold_standard_for_task(_make_task("alpha"))
        assert result is None

    def test_returns_none_when_no_task_matches(self):
        """No TEST_TASKS entry matches the task_id."""
        fake_tt = _FakeTestTask(id=999, _gold={"k": "v"})
        with (
            patch.object(pipeline, "HAS_GOLD_STANDARD", True),
            patch.object(pipeline, "TEST_TASKS", [fake_tt]),
        ):
            result = pipeline.get_gold_standard_for_task(_make_task("1"))
        assert result is None

    def test_iterates_multiple_tasks(self):
        """Correct task is returned when multiple TEST_TASKS exist."""
        gold_a = {"expected_output": "A"}
        gold_b = {"expected_output": "B"}
        tasks = [_FakeTestTask(id=1, _gold=gold_a), _FakeTestTask(id=2, _gold=gold_b)]
        with (
            patch.object(pipeline, "HAS_GOLD_STANDARD", True),
            patch.object(pipeline, "TEST_TASKS", tasks),
        ):
            result = pipeline.get_gold_standard_for_task(_make_task("2"))
        assert result == gold_b


# ===========================================================================
# evaluate_task_output_llm
# ===========================================================================


class TestEvaluateTaskOutputLlm:
    """Tier 1/2: main entry point routing and state transitions."""

    def test_falls_back_to_legacy_when_llm_unavailable(self):
        """When HAS_LLM_EVALUATOR is False, delegates to legacy evaluator."""
        with (
            patch.object(pipeline, "HAS_LLM_EVALUATOR", False),
            patch.object(
                pipeline, "evaluate_task_output_legacy", return_value={"score": 80}
            ) as mock_legacy,
        ):
            result = pipeline.evaluate_task_output_llm(
                task=_make_task(),
                output="some output",
                model="m",
                benchmark_id="b",
            )
        mock_legacy.assert_called_once()
        assert result == {"score": 80}

    def test_falls_back_verbose_prints_warning(self, capsys):
        """Verbose fallback prints a warning about unavailability."""
        with (
            patch.object(pipeline, "HAS_LLM_EVALUATOR", False),
            patch.object(pipeline, "evaluate_task_output_legacy", return_value=None),
        ):
            pipeline.evaluate_task_output_llm(
                task=_make_task(),
                output="x",
                model="m",
                benchmark_id="b",
                verbose=True,
            )
        captured = capsys.readouterr()
        assert "LLM evaluator not available" in captured.out

    def test_creates_minimal_gold_data_when_none_found(self):
        """When get_gold_standard_for_task returns None, minimal dict is built from
        task.expected_output and task.test_cases."""
        eval_result = _make_eval_result()

        with (
            patch.object(pipeline, "HAS_LLM_EVALUATOR", True),
            patch.object(pipeline, "get_gold_standard_for_task", return_value=None),
            patch.object(
                pipeline, "evaluate_with_llm", return_value=eval_result
            ) as mock_eval,
            patch.object(pipeline, "print_evaluation_report"),
        ):
            pipeline.evaluate_task_output_llm(
                task=_make_task(expected_output="expected", test_cases=[{"a": 1}]),
                output="out",
                model="m",
                benchmark_id="b",
            )

        # The gold_standard kwarg passed to evaluate_with_llm should be
        # the minimal dict derived from task fields.
        call_kwargs = mock_eval.call_args
        gold_passed = call_kwargs.kwargs.get(
            "gold_standard", call_kwargs[1].get("gold_standard")
        )
        assert gold_passed == {"expected_output": "expected", "test_cases": [{"a": 1}]}

    def test_uses_existing_gold_data_when_found(self):
        """When get_gold_standard_for_task returns data, it is passed through."""
        existing_gold = {"required_components": ["auth"]}
        eval_result = _make_eval_result()

        with (
            patch.object(pipeline, "HAS_LLM_EVALUATOR", True),
            patch.object(
                pipeline, "get_gold_standard_for_task", return_value=existing_gold
            ),
            patch.object(
                pipeline, "evaluate_with_llm", return_value=eval_result
            ) as mock_eval,
            patch.object(pipeline, "print_evaluation_report"),
        ):
            pipeline.evaluate_task_output_llm(
                task=_make_task(),
                output="out",
                model="m",
                benchmark_id="b",
            )

        call_kwargs = mock_eval.call_args
        gold_passed = call_kwargs.kwargs.get(
            "gold_standard", call_kwargs[1].get("gold_standard")
        )
        assert gold_passed == existing_gold

    def test_returns_eval_dict(self):
        """Successful evaluation returns EvaluationResult.to_dict()."""
        eval_result = _make_eval_result(overall_score=8.5, grade="B")

        with (
            patch.object(pipeline, "HAS_LLM_EVALUATOR", True),
            patch.object(
                pipeline,
                "get_gold_standard_for_task",
                return_value={"expected_output": "x"},
            ),
            patch.object(pipeline, "evaluate_with_llm", return_value=eval_result),
            patch.object(pipeline, "print_evaluation_report"),
        ):
            result = pipeline.evaluate_task_output_llm(
                task=_make_task(),
                output="out",
                model="m",
                benchmark_id="b",
            )

        assert result["overall_score"] == 8.5
        assert result["grade"] == "B"

    def test_saves_report_when_output_dir_given(self, tmp_path, capsys):
        """When output_dir is provided, save_evaluation_report is called."""
        eval_result = _make_eval_result()

        with (
            patch.object(pipeline, "HAS_LLM_EVALUATOR", True),
            patch.object(
                pipeline,
                "get_gold_standard_for_task",
                return_value={"expected_output": "x"},
            ),
            patch.object(pipeline, "evaluate_with_llm", return_value=eval_result),
            patch.object(pipeline, "print_evaluation_report"),
            patch.object(pipeline, "save_evaluation_report") as mock_save,
        ):
            pipeline.evaluate_task_output_llm(
                task=_make_task(),
                output="out",
                model="m",
                benchmark_id="b",
                output_dir=tmp_path,
            )

        mock_save.assert_called_once_with(eval_result, tmp_path)
        captured = capsys.readouterr()
        assert "Evaluation saved" in captured.out

    def test_does_not_save_report_when_output_dir_none(self):
        """When output_dir is None, save_evaluation_report is NOT called."""
        eval_result = _make_eval_result()

        with (
            patch.object(pipeline, "HAS_LLM_EVALUATOR", True),
            patch.object(
                pipeline,
                "get_gold_standard_for_task",
                return_value={"expected_output": "x"},
            ),
            patch.object(pipeline, "evaluate_with_llm", return_value=eval_result),
            patch.object(pipeline, "print_evaluation_report"),
            patch.object(pipeline, "save_evaluation_report") as mock_save,
        ):
            pipeline.evaluate_task_output_llm(
                task=_make_task(),
                output="out",
                model="m",
                benchmark_id="b",
                output_dir=None,
            )

        mock_save.assert_not_called()

    def test_verbose_calls_print_evaluation_report(self):
        """Verbose=True routes to print_evaluation_report(verbose=True)."""
        eval_result = _make_eval_result()

        with (
            patch.object(pipeline, "HAS_LLM_EVALUATOR", True),
            patch.object(
                pipeline,
                "get_gold_standard_for_task",
                return_value={"expected_output": "x"},
            ),
            patch.object(pipeline, "evaluate_with_llm", return_value=eval_result),
            patch.object(pipeline, "print_evaluation_report") as mock_print,
        ):
            pipeline.evaluate_task_output_llm(
                task=_make_task(),
                output="out",
                model="m",
                benchmark_id="b",
                verbose=True,
            )

        mock_print.assert_called_once_with(eval_result, verbose=True)

    def test_compact_output_prints_score_line(self, capsys):
        """Non-verbose mode prints a single score/grade line."""
        eval_result = _make_eval_result(overall_score=7.5, grade="C")

        with (
            patch.object(pipeline, "HAS_LLM_EVALUATOR", True),
            patch.object(
                pipeline,
                "get_gold_standard_for_task",
                return_value={"expected_output": "x"},
            ),
            patch.object(pipeline, "evaluate_with_llm", return_value=eval_result),
        ):
            pipeline.evaluate_task_output_llm(
                task=_make_task(),
                output="out",
                model="m",
                benchmark_id="b",
                verbose=False,
            )

        captured = capsys.readouterr()
        assert "7.5" in captured.out
        assert "C" in captured.out

    def test_passes_evaluator_model_to_evaluate_with_llm(self):
        """evaluator_model kwarg is forwarded to the LLM evaluator."""
        eval_result = _make_eval_result()

        with (
            patch.object(pipeline, "HAS_LLM_EVALUATOR", True),
            patch.object(
                pipeline,
                "get_gold_standard_for_task",
                return_value={"expected_output": "x"},
            ),
            patch.object(
                pipeline, "evaluate_with_llm", return_value=eval_result
            ) as mock_eval,
            patch.object(pipeline, "print_evaluation_report"),
        ):
            pipeline.evaluate_task_output_llm(
                task=_make_task(),
                output="out",
                model="gpt-4o-mini",
                benchmark_id="b",
                evaluator_model="gpt-4o",
            )

        call_kwargs = mock_eval.call_args
        assert (
            call_kwargs.kwargs.get(
                "evaluator_model", call_kwargs[1].get("evaluator_model")
            )
            == "gpt-4o"
        )


# ===========================================================================
# evaluate_task_output_legacy
# ===========================================================================


class TestEvaluateTaskOutputLegacy:
    """Tier 1: guard checks and matching in legacy evaluator."""

    def test_returns_none_when_gold_standard_unavailable(self):
        """When HAS_GOLD_STANDARD is False, return None immediately."""
        with patch.object(pipeline, "HAS_GOLD_STANDARD", False):
            result = pipeline.evaluate_task_output_legacy(_make_task(), "out")
        assert result is None

    def test_returns_none_when_no_matching_task(self):
        """No TEST_TASKS entry matches -> None."""
        fake_tt = _FakeTestTask(id=999, _gold={"k": "v"})
        with (
            patch.object(pipeline, "HAS_GOLD_STANDARD", True),
            patch.object(pipeline, "TEST_TASKS", [fake_tt]),
        ):
            result = pipeline.evaluate_task_output_legacy(_make_task("1"), "out")
        assert result is None

    def test_returns_none_when_gold_data_empty(self):
        """Matching task found but get_gold_standard() returns None -> None."""
        fake_tt = _FakeTestTask(id=1, _gold={})  # get_gold_standard returns None
        with (
            patch.object(pipeline, "HAS_GOLD_STANDARD", True),
            patch.object(pipeline, "TEST_TASKS", [fake_tt]),
        ):
            result = pipeline.evaluate_task_output_legacy(_make_task("1"), "out")
        assert result is None

    def test_returns_eval_result_on_successful_match(self):
        """Matching task with valid gold data returns evaluation dict."""
        gold = {"expected_output": "correct", "required_components": ["auth"]}
        fake_tt = _FakeTestTask(id=1, _gold=gold)
        eval_dict = {"overall_score": 85, "grade": "B"}

        with (
            patch.object(pipeline, "HAS_GOLD_STANDARD", True),
            patch.object(pipeline, "TEST_TASKS", [fake_tt]),
            patch.object(
                pipeline,
                "evaluate_against_gold_standard",
                return_value=eval_dict,
                create=True,
            ),
            patch.object(pipeline, "print_gold_standard_report", create=True),
        ):
            result = pipeline.evaluate_task_output_legacy(
                _make_task("1"), "some output", verbose=True
            )

        assert result == eval_dict

    def test_legacy_saves_report_when_output_dir_given(self, tmp_path):
        """When output_dir is provided, save_evaluation_report_legacy is called."""
        gold = {"expected_output": "correct"}
        fake_tt = _FakeTestTask(id=1, _gold=gold)
        eval_dict = {"overall_score": 90, "grade": "A"}

        with (
            patch.object(pipeline, "HAS_GOLD_STANDARD", True),
            patch.object(pipeline, "TEST_TASKS", [fake_tt]),
            patch.object(
                pipeline,
                "evaluate_against_gold_standard",
                return_value=eval_dict,
                create=True,
            ),
            patch.object(pipeline, "save_evaluation_report_legacy") as mock_save,
        ):
            pipeline.evaluate_task_output_legacy(
                _make_task("1"), "output text", output_dir=tmp_path
            )

        mock_save.assert_called_once_with("1", eval_dict, gold, "output text", tmp_path)

    def test_legacy_verbose_prints_mismatch_analysis(self):
        """Verbose legacy evaluation calls print_mismatch_analysis."""
        gold = {"expected_output": "correct"}
        fake_tt = _FakeTestTask(id=1, _gold=gold)
        eval_dict = {"overall_score": 70, "grade": "C"}

        with (
            patch.object(pipeline, "HAS_GOLD_STANDARD", True),
            patch.object(pipeline, "TEST_TASKS", [fake_tt]),
            patch.object(
                pipeline,
                "evaluate_against_gold_standard",
                return_value=eval_dict,
                create=True,
            ),
            patch.object(pipeline, "print_gold_standard_report", create=True),
            patch.object(pipeline, "print_mismatch_analysis") as mock_mismatch,
        ):
            pipeline.evaluate_task_output_legacy(
                _make_task("1"), "output text", verbose=True
            )

        mock_mismatch.assert_called_once_with(eval_dict, gold, "output text")

    @pytest.mark.parametrize(
        "task_id, tt_id",
        [
            ("5", 5),  # string match
            ("task_005", 5),  # formatted match
        ],
    )
    def test_legacy_id_matching_strategies(self, task_id: str, tt_id: int):
        """Legacy evaluator uses the same multi-strategy ID matching."""
        gold = {"expected_output": "match"}
        fake_tt = _FakeTestTask(id=tt_id, _gold=gold)
        eval_dict = {"overall_score": 80, "grade": "B"}

        with (
            patch.object(pipeline, "HAS_GOLD_STANDARD", True),
            patch.object(pipeline, "TEST_TASKS", [fake_tt]),
            patch.object(
                pipeline,
                "evaluate_against_gold_standard",
                return_value=eval_dict,
                create=True,
            ),
        ):
            result = pipeline.evaluate_task_output_legacy(_make_task(task_id), "output")

        assert result is not None


# ===========================================================================
# print_mismatch_analysis
# ===========================================================================


class TestPrintMismatchAnalysis:
    """Tier 1: branching across issue categories."""

    def test_reports_no_issues_when_all_criteria_met(self, capsys):
        """When no missing items exist, the 'all met' message is printed."""
        eval_result: dict[str, Any] = {
            "components": {"missing": []},
            "patterns": {"missing": []},
            "decisions": {"missing": []},
            "endpoints": {"missing": []},
            "tables": {"missing": []},
        }
        pipeline.print_mismatch_analysis(eval_result, {}, "output")
        captured = capsys.readouterr()
        assert "All gold standard criteria met" in captured.out

    def test_reports_missing_components_with_similar_lines(self, capsys):
        """Missing components are listed and similar output lines shown."""
        eval_result: dict[str, Any] = {
            "components": {"missing": ["authentication module"]},
            "patterns": {"missing": []},
            "decisions": {"missing": []},
            "endpoints": {"missing": []},
            "tables": {"missing": []},
        }
        output = "We built an authentication layer\nand a database layer"
        pipeline.print_mismatch_analysis(eval_result, {}, output)
        captured = capsys.readouterr()
        assert "MISSING COMPONENTS" in captured.out
        assert "authentication module" in captured.out
        # Should find a similar line containing "authentication"
        assert "Similar:" in captured.out

    def test_reports_missing_patterns(self, capsys):
        """Missing regex patterns are listed."""
        eval_result: dict[str, Any] = {
            "components": {"missing": []},
            "patterns": {"missing": [r"class \w+Repository"]},
            "decisions": {"missing": []},
            "endpoints": {"missing": []},
            "tables": {"missing": []},
        }
        pipeline.print_mismatch_analysis(eval_result, {}, "output")
        captured = capsys.readouterr()
        assert "MISSING PATTERNS" in captured.out
        assert r"class \w+Repository" in captured.out

    def test_reports_missing_decisions(self, capsys):
        """Missing key decisions are listed with keywords."""
        eval_result: dict[str, Any] = {
            "components": {"missing": []},
            "patterns": {"missing": []},
            "decisions": {"missing": ["Use PostgreSQL for persistence"]},
            "endpoints": {"missing": []},
            "tables": {"missing": []},
        }
        pipeline.print_mismatch_analysis(eval_result, {}, "output")
        captured = capsys.readouterr()
        assert "MISSING KEY DECISIONS" in captured.out
        assert "PostgreSQL" in captured.out

    def test_reports_missing_endpoints(self, capsys):
        """Missing API endpoints are listed."""
        eval_result: dict[str, Any] = {
            "components": {"missing": []},
            "patterns": {"missing": []},
            "decisions": {"missing": []},
            "endpoints": {"missing": ["POST /api/users"]},
            "tables": {"missing": []},
        }
        pipeline.print_mismatch_analysis(eval_result, {}, "output")
        captured = capsys.readouterr()
        assert "MISSING API ENDPOINTS" in captured.out
        assert "POST /api/users" in captured.out

    def test_reports_missing_tables(self, capsys):
        """Missing database tables are listed."""
        eval_result: dict[str, Any] = {
            "components": {"missing": []},
            "patterns": {"missing": []},
            "decisions": {"missing": []},
            "endpoints": {"missing": []},
            "tables": {"missing": ["users", "sessions"]},
        }
        pipeline.print_mismatch_analysis(eval_result, {}, "output")
        captured = capsys.readouterr()
        assert "MISSING DATABASE TABLES" in captured.out
        assert "users" in captured.out
        assert "sessions" in captured.out

    def test_prints_tip_when_issues_found(self, capsys):
        """When any issues exist, the TIP message is printed."""
        eval_result: dict[str, Any] = {
            "components": {"missing": ["something"]},
            "patterns": {"missing": []},
            "decisions": {"missing": []},
            "endpoints": {"missing": []},
            "tables": {"missing": []},
        }
        pipeline.print_mismatch_analysis(eval_result, {}, "output")
        captured = capsys.readouterr()
        assert "TIP:" in captured.out

    def test_handles_empty_eval_result_gracefully(self, capsys):
        """Empty eval_result (no category keys) produces 'all met' message."""
        pipeline.print_mismatch_analysis({}, {}, "output")
        captured = capsys.readouterr()
        assert "All gold standard criteria met" in captured.out


# ===========================================================================
# save_evaluation_report_legacy
# ===========================================================================


class TestSaveEvaluationReportLegacy:
    """Tier 1/2: file output structure and formatting."""

    def test_writes_markdown_file(self, tmp_path):
        """Report file is created at the expected path."""
        eval_result = {"overall_score": 85.0, "grade": "B"}
        gold_data: dict[str, Any] = {"api_endpoints": []}

        pipeline.save_evaluation_report_legacy(
            "42", eval_result, gold_data, "my output", tmp_path
        )

        report = tmp_path / "task_42_evaluation.md"
        assert report.exists()
        content = report.read_text(encoding="utf-8")
        assert "# Evaluation Report: Task 42" in content
        assert "85.0" in content
        assert "**Grade:** B" in content

    def test_includes_category_scores(self, tmp_path):
        """Each category section appears with matched/missing items."""
        eval_result = {
            "overall_score": 70.0,
            "grade": "C",
            "components": {
                "score": 80,
                "matched": ["auth"],
                "missing": ["db"],
            },
            "patterns": {"score": 100, "matched": ["repo"], "missing": []},
            "decisions": {"score": 0, "matched": [], "missing": []},
            "endpoints": {"score": 0, "matched": [], "missing": []},
            "tables": {"score": 0, "matched": [], "missing": []},
        }
        gold_data: dict[str, Any] = {"api_endpoints": []}

        pipeline.save_evaluation_report_legacy(
            "1", eval_result, gold_data, "output", tmp_path
        )

        content = (tmp_path / "task_1_evaluation.md").read_text(encoding="utf-8")
        assert "### Components: 80%" in content
        assert "- [x] auth" in content
        assert "- [ ] db" in content
        assert "### Patterns: 100%" in content

    def test_formats_api_endpoints(self, tmp_path):
        """API endpoints from gold_data are formatted as 'METHOD path'."""
        eval_result = {"overall_score": 90.0, "grade": "A"}
        gold_data = {
            "api_endpoints": [
                {"method": "GET", "path": "/api/users"},
                {"method": "POST", "path": "/api/users"},
            ],
        }

        pipeline.save_evaluation_report_legacy(
            "1", eval_result, gold_data, "output", tmp_path
        )

        content = (tmp_path / "task_1_evaluation.md").read_text(encoding="utf-8")
        assert "GET /api/users" in content
        assert "POST /api/users" in content

    def test_truncates_output_preview_to_2000_chars(self, tmp_path):
        """Output preview is capped at 2000 characters."""
        long_output = "x" * 5000
        eval_result = {"overall_score": 50.0, "grade": "F"}
        gold_data: dict[str, Any] = {"api_endpoints": []}

        pipeline.save_evaluation_report_legacy(
            "1", eval_result, gold_data, long_output, tmp_path
        )

        content = (tmp_path / "task_1_evaluation.md").read_text(encoding="utf-8")
        # The code block should contain exactly 2000 x's
        assert "x" * 2000 in content
        assert "x" * 2001 not in content

    def test_includes_gold_standard_reference_fields(self, tmp_path):
        """Gold standard reference section contains all expected fields."""
        eval_result = {"overall_score": 80.0, "grade": "B"}
        gold_data = {
            "required_components": ["auth", "db"],
            "required_patterns": ["repository"],
            "key_decisions": ["Use PostgreSQL"],
            "api_endpoints": [],
            "database_tables": ["users"],
        }

        pipeline.save_evaluation_report_legacy(
            "1", eval_result, gold_data, "output", tmp_path
        )

        content = (tmp_path / "task_1_evaluation.md").read_text(encoding="utf-8")
        assert "Gold Standard Reference" in content
        assert "auth" in content
        assert "repository" in content
        assert "PostgreSQL" in content
        assert "users" in content
