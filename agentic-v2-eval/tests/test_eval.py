"""Unit tests for the agentic-v2-eval package."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from agentic_v2_eval.__main__ import main
from agentic_v2_eval.metrics.accuracy import (
    calculate_accuracy,
    calculate_f1_score,
    calculate_precision_recall,
)
from agentic_v2_eval.metrics.performance import (
    benchmark,
    execution_time_score,
    latency_percentiles,
)
from agentic_v2_eval.metrics.quality import (
    code_quality_score,
    complexity_score,
    lint_score,
)
from agentic_v2_eval.reporters.html import HtmlReporter, generate_html_report
from agentic_v2_eval.reporters.json import JsonReporter, generate_json_report
from agentic_v2_eval.reporters.markdown import (
    MarkdownReporter,
    generate_markdown_report,
)
from agentic_v2_eval.runners.batch import BatchRunner, run_batch_evaluation
from agentic_v2_eval.runners.streaming import (
    AsyncStreamingRunner,
    StreamingRunner,
    run_streaming_evaluation,
)
from agentic_v2_eval.scorer import Scorer, ScoringResult

# === Accuracy Metrics Tests ===


def test_calculate_accuracy():
    """Test basic accuracy calculation."""
    predictions = [1, 0, 1, 1]
    ground_truth = [1, 0, 0, 1]
    accuracy = calculate_accuracy(predictions, ground_truth)
    assert accuracy == 0.75, f"Expected 0.75, got {accuracy}"


def test_calculate_accuracy_empty():
    """Test accuracy with empty lists."""
    accuracy = calculate_accuracy([], [])
    assert accuracy == 0.0


def test_calculate_f1_score():
    """Test F1 score calculation."""
    # All correct: F1 = 1.0
    f1 = calculate_f1_score([1, 1, 0, 0], [1, 1, 0, 0])
    assert f1 == 1.0

    # 50% correct
    f1 = calculate_f1_score([1, 1], [1, 0])
    assert 0.0 < f1 < 1.0


def test_calculate_precision_recall():
    """Test precision and recall."""
    predictions = [1, 1, 0, 1]
    ground_truth = [1, 0, 0, 1]

    precision, recall = calculate_precision_recall(predictions, ground_truth)

    # 2 true positives, 1 false positive, 0 false negatives
    assert precision == pytest.approx(2 / 3, rel=0.01)
    assert recall == 1.0


# === Quality Metrics Tests ===


def test_code_quality_score_valid():
    """Test code quality with valid code."""
    score = code_quality_score("def foo():\n    return 42")
    assert 0.0 <= score <= 1.0
    assert score > 0.0


def test_code_quality_score_empty():
    """Test code quality with empty string."""
    score = code_quality_score("")
    assert score == 0.0


def test_lint_score():
    """Test lint scoring."""
    score, issues = lint_score("def foo(): pass")
    assert isinstance(score, float)
    assert isinstance(issues, list)
    assert 0.0 <= score <= 1.0


def test_complexity_score():
    """Test complexity scoring."""
    code = "def foo():\n    return 1"
    score = complexity_score(code)
    assert 0.0 <= score <= 1.0


# === Performance Metrics Tests ===


def test_execution_time_score():
    """Test execution time scoring."""
    # Fast execution should score high
    assert execution_time_score(0.1) > 0.9

    # Slow execution should score lower
    assert execution_time_score(5.0) < execution_time_score(0.5)

    # Very slow execution
    assert execution_time_score(10.0) < 0.5


def test_benchmark():
    """Test benchmark utility."""

    def fast_func():
        return sum(range(100))

    result, stats = benchmark(fast_func, iterations=5, warmup=1)

    assert result == sum(range(100))
    assert "mean" in stats
    assert "median" in stats
    assert "min" in stats
    assert "max" in stats
    assert stats["iterations"] == 5


def test_latency_percentiles():
    """Test latency percentile calculation."""
    latencies = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]

    percentiles = latency_percentiles(latencies)

    assert "p50" in percentiles
    assert "p90" in percentiles
    assert "p99" in percentiles
    assert percentiles["p50"] <= percentiles["p90"] <= percentiles["p99"]


# === Scorer Tests ===


def test_scorer(tmp_path: Path):
    """Test scorer with rubric file."""
    # Create a test rubric
    rubric_content = """
name: Test Rubric
version: "1.0"
criteria:
  - name: Accuracy
    weight: 2.0
  - name: Completeness
    weight: 1.0
  - name: Efficiency
    weight: 1.0
"""
    rubric_path = tmp_path / "test_rubric.yaml"
    rubric_path.write_text(rubric_content)

    scorer = Scorer(rubric_path)
    results = {"Accuracy": 0.8, "Completeness": 0.9, "Efficiency": 0.7}

    score = scorer.score(results)

    assert isinstance(score, ScoringResult)
    assert 0.0 <= score.weighted_score <= 1.0
    assert len(score.missing_criteria) == 0


def test_scorer_missing_rubric():
    """Test scorer with non-existent rubric."""
    with pytest.raises(FileNotFoundError):
        Scorer("nonexistent.yaml")


def test_scorer_missing_criteria(tmp_path: Path):
    """Test scorer with missing criteria in results."""
    rubric_content = """
criteria:
  - name: Accuracy
    weight: 1.0
  - name: Missing
    weight: 1.0
"""
    rubric_path = tmp_path / "test_rubric.yaml"
    rubric_path.write_text(rubric_content)

    scorer = Scorer(rubric_path)
    score = scorer.score({"Accuracy": 0.8})

    assert "Missing" in score.missing_criteria


# === Runner Tests ===


def test_batch_runner():
    """Test BatchRunner class."""
    runner = BatchRunner(evaluator=lambda x: x * 2)
    result = runner.run([1, 2, 3])

    assert result.total == 3
    assert result.successful == 3
    assert result.failed == 0
    assert result.results == [2, 4, 6]


def test_batch_runner_with_errors():
    """Test BatchRunner with errors."""

    def failing_evaluator(x):
        if x == 2:
            raise ValueError("Test error")
        return x * 2

    runner = BatchRunner(evaluator=failing_evaluator, continue_on_error=True)
    result = runner.run([1, 2, 3])

    assert result.total == 3
    assert result.successful == 2
    assert result.failed == 1
    assert len(result.errors) == 1


def test_run_batch_evaluation():
    """Test run_batch_evaluation function."""

    def dummy_evaluator(tc):
        return {"result": tc}

    test_cases = [1, 2, 3]
    results = run_batch_evaluation(test_cases, dummy_evaluator)

    assert results == [{"result": 1}, {"result": 2}, {"result": 3}]


def test_streaming_runner():
    """Test StreamingRunner class."""
    collected = []

    runner = StreamingRunner(
        evaluator=lambda x: x * 2,
        on_result=lambda r: collected.append(r),
    )
    stats = runner.run([1, 2, 3])

    assert stats.processed == 3
    assert stats.successful == 3
    assert collected == [2, 4, 6]


def test_run_streaming_evaluation():
    """Test run_streaming_evaluation function."""
    test_cases = [1, 2]
    collected = []

    def dummy_evaluator(tc):
        return {"result": tc}

    def callback(result):
        collected.append(result)

    run_streaming_evaluation(test_cases, dummy_evaluator, callback)

    assert collected == [{"result": 1}, {"result": 2}]


def test_scorer_from_dict():
    """Scorer should accept an in-memory rubric dict."""
    rubric = {
        "name": "Dict Rubric",
        "version": "1.0",
        "criteria": [
            {"name": "Accuracy", "weight": 1.0},
            {"name": "Completeness", "weight": 1.0},
        ],
    }
    scorer = Scorer(rubric)
    score = scorer.score({"Accuracy": 1.0, "Completeness": 0.0})
    assert 0.0 <= score.weighted_score <= 1.0


def test_async_streaming_runner_supports_async_iterables_and_awaitables():
    """AsyncStreamingRunner should handle async iterables and awaitable return
    values."""

    async def _gen(n: int):
        for i in range(n):
            yield i

    async def _async_double(x: int) -> int:
        await asyncio.sleep(0)
        return x * 2

    # evaluator returns a coroutine object but is not itself an async def
    def evaluator(x: int):
        return _async_double(x)

    runner = AsyncStreamingRunner(evaluator=evaluator, max_concurrency=2)

    async def _collect() -> list[int]:
        out: list[int] = []
        async for r in runner.iter_results(_gen(5)):
            out.append(r)
        return out

    results = asyncio.run(_collect())
    assert sorted(results) == [0, 2, 4, 6, 8]


def test_async_streaming_runner_respects_max_concurrency():
    """max_concurrency should bound concurrent evaluator executions."""
    current = 0
    max_seen = 0

    async def evaluator(x: int) -> int:
        nonlocal current, max_seen
        current += 1
        max_seen = max(max_seen, current)
        await asyncio.sleep(0.01)
        current -= 1
        return x

    runner = AsyncStreamingRunner(evaluator=evaluator, max_concurrency=3)

    async def _collect() -> list[int]:
        out: list[int] = []
        async for r in runner.iter_results(list(range(10))):
            out.append(r)
        return out

    results = asyncio.run(_collect())
    assert sorted(results) == list(range(10))
    assert max_seen <= 3


def test_cli_evaluate_defaults_to_packaged_rubric(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """CLI should run evaluate without an explicit --rubric."""
    results_path = tmp_path / "results.json"
    out_path = tmp_path / "scored.json"

    results_path.write_text(
        json.dumps(
            {
                "Accuracy": 0.9,
                "Completeness": 0.8,
                "Efficiency": 0.7,
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(["evaluate", str(results_path), "--output", str(out_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert out_path.exists()
    assert "Average Score" in captured.out

    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["rubric"] == "<builtin:default>"
    assert "results" in data


# === Reporter Tests ===


def test_json_reporter(tmp_path: Path):
    """Test JsonReporter class."""
    reporter = JsonReporter()
    results = [{"Accuracy": 0.9, "name": "test1"}]

    out_file = tmp_path / "report.json"
    reporter.generate(results, out_file)

    assert out_file.exists()
    content = out_file.read_text()
    assert "Accuracy" in content
    assert "summary" in content


def test_generate_json_report(tmp_path: Path):
    """Test generate_json_report function."""
    results = [{"Accuracy": 0.9}]
    out_file = tmp_path / "report.json"

    generate_json_report(results, str(out_file))

    assert out_file.exists()


def test_markdown_reporter(tmp_path: Path):
    """Test MarkdownReporter class."""
    reporter = MarkdownReporter()
    results = [{"Accuracy": 0.9, "name": "test1"}]

    out_file = tmp_path / "report.md"
    reporter.generate(results, out_file)

    assert out_file.exists()
    content = out_file.read_text()
    assert "# Evaluation Results" in content
    assert "Accuracy" in content


def test_generate_markdown_report(tmp_path: Path):
    """Test generate_markdown_report function."""
    results = [{"Accuracy": 0.9}]
    out_file = tmp_path / "report.md"

    generate_markdown_report(results, str(out_file))

    assert out_file.exists()


def test_html_reporter(tmp_path: Path):
    """Test HtmlReporter class."""
    reporter = HtmlReporter()
    results = [{"Accuracy": 0.9, "name": "test1"}]

    out_file = tmp_path / "report.html"
    reporter.generate(results, out_file)

    assert out_file.exists()
    content = out_file.read_text()
    assert "<html" in content
    assert "Accuracy" in content


def test_generate_html_report(tmp_path: Path):
    """Test generate_html_report function."""
    results = [{"Accuracy": 0.9}]
    out_file = tmp_path / "report.html"

    generate_html_report(results, str(out_file))

    assert out_file.exists()
