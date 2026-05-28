"""Tests for accuracy and performance metrics."""

from __future__ import annotations

import time

import pytest
from agentic_v2_eval.metrics.accuracy import (
    calculate_accuracy,
    calculate_confusion_matrix,
    calculate_f1_score,
    calculate_precision_recall,
)
from agentic_v2_eval.metrics.performance import (
    benchmark,
    execution_time_score,
    latency_percentiles,
    measure_time,
    memory_usage_score,
    throughput_score,
)


class TestAccuracy:
    """Tests for calculate_accuracy."""

    def test_perfect_accuracy(self) -> None:
        """All correct predictions -> 1.0."""
        assert calculate_accuracy([1, 0, 1, 0], [1, 0, 1, 0]) == 1.0

    def test_zero_accuracy(self) -> None:
        """All wrong predictions -> 0.0."""
        assert calculate_accuracy([1, 1, 1], [0, 0, 0]) == 0.0

    def test_partial_accuracy(self) -> None:
        """[1,0,1,1] vs [1,0,0,1] -> 0.75."""
        assert calculate_accuracy([1, 0, 1, 1], [1, 0, 0, 1]) == 0.75

    def test_length_mismatch_raises(self) -> None:
        """Different lengths raise ValueError."""
        with pytest.raises(ValueError, match="Length mismatch"):
            calculate_accuracy([1, 0], [1])

    def test_empty_returns_zero(self) -> None:
        """Empty sequences -> 0.0."""
        assert calculate_accuracy([], []) == 0.0

    def test_string_labels(self) -> None:
        """Works with string labels."""
        assert calculate_accuracy(["a", "b"], ["a", "b"]) == 1.0


class TestPrecisionRecall:
    """Tests for calculate_precision_recall."""

    def test_perfect_precision_recall(self) -> None:
        """All correct positive predictions -> (1.0, 1.0)."""
        precision, recall = calculate_precision_recall([1, 0, 1], [1, 0, 1])
        assert precision == 1.0
        assert recall == 1.0

    def test_no_predicted_positives(self) -> None:
        """No positive predictions -> precision 0.0."""
        precision, recall = calculate_precision_recall([0, 0, 0], [1, 1, 0])
        assert precision == 0.0

    def test_no_actual_positives(self) -> None:
        """No actual positives -> recall 0.0."""
        precision, recall = calculate_precision_recall([1, 0], [0, 0])
        assert recall == 0.0

    def test_mixed(self) -> None:
        """Mixed predictions give expected values."""
        # Predictions: [1, 1, 0, 1], Truth: [1, 0, 0, 1]
        # TP=2, FP=1, FN=0 -> precision=2/3, recall=2/2=1.0
        precision, recall = calculate_precision_recall([1, 1, 0, 1], [1, 0, 0, 1])
        assert abs(precision - 2 / 3) < 1e-6
        assert recall == 1.0

    def test_length_mismatch_raises(self) -> None:
        """Different lengths raise ValueError."""
        with pytest.raises(ValueError):
            calculate_precision_recall([1], [1, 0])


class TestF1Score:
    """Tests for calculate_f1_score."""

    def test_perfect_f1(self) -> None:
        """Perfect predictions -> 1.0."""
        assert calculate_f1_score([1, 0, 1], [1, 0, 1]) == 1.0

    def test_zero_f1(self) -> None:
        """No overlap -> 0.0."""
        assert calculate_f1_score([0, 0, 0], [1, 1, 1]) == 0.0

    def test_intermediate_f1(self) -> None:
        """Partial match gives expected F1."""
        # precision=2/3, recall=1.0 -> F1 = 2*(2/3*1)/(2/3+1) = 0.8
        f1 = calculate_f1_score([1, 1, 0, 1], [1, 0, 0, 1])
        assert abs(f1 - 0.8) < 1e-6


class TestConfusionMatrix:
    """Tests for calculate_confusion_matrix."""

    def test_binary_matrix(self) -> None:
        """2-class confusion matrix correct."""
        matrix = calculate_confusion_matrix([1, 0, 1, 0], [1, 0, 0, 0])
        # actual=1, pred=1 -> 1; actual=0, pred=0 -> 2; actual=0, pred=1 -> 1
        assert matrix["1"]["1"] == 1
        assert matrix["0"]["0"] == 2
        assert matrix["0"]["1"] == 1

    def test_multiclass_matrix(self) -> None:
        """3-class confusion matrix correct."""
        matrix = calculate_confusion_matrix(["a", "b", "c", "a"], ["a", "b", "b", "a"])
        assert matrix["a"]["a"] == 2
        assert matrix["b"]["b"] == 1
        assert matrix["b"]["c"] == 1

    def test_custom_labels(self) -> None:
        """Custom label list used."""
        matrix = calculate_confusion_matrix([1, 0], [1, 0], labels=[0, 1, 2])
        assert "2" in matrix
        assert matrix["2"]["0"] == 0


class TestExecutionTimeScore:
    """Tests for execution_time_score."""

    def test_under_threshold(self) -> None:
        """Time under threshold -> 1.0."""
        assert execution_time_score(0.5, threshold=1.0) == 1.0

    def test_at_threshold(self) -> None:
        """Time at threshold -> 1.0."""
        assert execution_time_score(1.0, threshold=1.0) == 1.0

    def test_over_threshold(self) -> None:
        """Time over threshold -> decayed score < 1.0."""
        score = execution_time_score(2.0, threshold=1.0)
        assert 0.0 < score < 1.0

    def test_zero_time(self) -> None:
        """Zero or negative time -> 1.0."""
        assert execution_time_score(0.0) == 1.0


class TestMemoryUsageScore:
    """Tests for memory_usage_score."""

    def test_under_threshold(self) -> None:
        """Memory under threshold -> 1.0."""
        assert memory_usage_score(50 * 1024 * 1024, threshold_mb=100.0) == 1.0

    def test_over_threshold(self) -> None:
        """Memory over threshold -> proportional score."""
        score = memory_usage_score(200 * 1024 * 1024, threshold_mb=100.0)
        assert abs(score - 0.5) < 1e-6

    def test_zero_memory(self) -> None:
        """Zero memory -> 1.0."""
        assert memory_usage_score(0.0) == 1.0


class TestThroughputScore:
    """Tests for throughput_score."""

    def test_at_target(self) -> None:
        """Items/sec >= target -> 1.0."""
        assert throughput_score(150.0, target_throughput=100.0) == 1.0

    def test_below_target(self) -> None:
        """Items/sec < target -> proportional score."""
        score = throughput_score(50.0, target_throughput=100.0)
        assert abs(score - 0.5) < 1e-6

    def test_zero_target(self) -> None:
        """Zero target with positive throughput -> 1.0."""
        assert throughput_score(50.0, target_throughput=0.0) == 1.0


class TestMeasureTime:
    """Tests for measure_time context manager."""

    def test_context_manager_records_elapsed(self) -> None:
        """measure_time() populates 'elapsed' key."""
        with measure_time() as timing:
            time.sleep(0.01)  # Brief sleep to ensure measurable time
        assert "elapsed" in timing
        assert timing["elapsed"] > 0

    def test_elapsed_is_reasonable(self) -> None:
        """Elapsed time is in a reasonable range."""
        with measure_time() as timing:
            pass  # No-op
        assert timing["elapsed"] < 1.0  # Should be nearly instant


class TestBenchmark:
    """Tests for benchmark function."""

    def test_returns_stats_dict(self) -> None:
        """Benchmark() returns result and stats with min/max/mean/median."""
        result, stats = benchmark(sorted, [3, 1, 2], iterations=5, warmup=1)
        assert result == [1, 2, 3]
        assert "min" in stats
        assert "max" in stats
        assert "mean" in stats
        assert "median" in stats
        assert stats["min"] <= stats["mean"] <= stats["max"]

    def test_iterations_count(self) -> None:
        """Stats reflect the correct number of iterations."""
        _, stats = benchmark(lambda: None, iterations=10, warmup=0)
        assert stats["iterations"] == 10.0


class TestLatencyPercentiles:
    """Tests for latency_percentiles."""

    def test_default_percentiles(self) -> None:
        """Default p50/p90/p95/p99 calculated."""
        latencies = list(range(1, 101))  # 1 to 100
        result = latency_percentiles([float(x) for x in latencies])
        assert "p50" in result
        assert "p90" in result
        assert "p95" in result
        assert "p99" in result
        assert result["p50"] <= result["p90"] <= result["p99"]

    def test_empty_list(self) -> None:
        """Empty latencies return 0.0 for all percentiles."""
        result = latency_percentiles([])
        assert result["p50"] == 0.0
        assert result["p90"] == 0.0
        assert result["p95"] == 0.0
        assert result["p99"] == 0.0

    def test_custom_percentiles(self) -> None:
        """Custom percentile list works."""
        result = latency_percentiles([1.0, 2.0, 3.0], percentiles=[50, 75])
        assert "p50" in result
        assert "p75" in result
        assert "p90" not in result
