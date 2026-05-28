"""Performance metrics for evaluation.

Provides functions for measuring execution performance including time,
memory, and throughput metrics.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

T = TypeVar("T")


@dataclass
class PerformanceResult:
    """Result of a performance measurement."""

    execution_time: float  # seconds
    memory_delta: float | None = None  # bytes, if measured
    result: Any = None  # The actual return value


def execution_time_score(
    time_seconds: float,
    threshold: float = 1.0,
    penalty_factor: float = 2.0,
) -> float:
    """Calculate score based on execution time (lower is better).

    Args:
        time_seconds: Execution time in seconds.
        threshold: Target threshold in seconds (default: 1.0).
            Times at or below threshold get score 1.0.
        penalty_factor: How quickly score drops above threshold.
            Higher = steeper penalty.

    Returns:
        Performance score between 0.0 and 1.0.

    Example:
        >>> execution_time_score(0.5)  # Under threshold
        1.0
        >>> execution_time_score(2.0)  # Over threshold
        0.5
    """
    if time_seconds <= 0:
        return 1.0

    if time_seconds <= threshold:
        return 1.0

    # Exponential decay above threshold
    ratio = threshold / time_seconds
    score: float = min(1.0, ratio ** (1 / penalty_factor))
    return score


def memory_usage_score(
    memory_bytes: float,
    threshold_mb: float = 100.0,
) -> float:
    """Calculate score based on memory usage (lower is better).

    Args:
        memory_bytes: Memory usage in bytes.
        threshold_mb: Target threshold in megabytes (default: 100 MB).

    Returns:
        Performance score between 0.0 and 1.0.

    Example:
        >>> memory_usage_score(50 * 1024 * 1024)  # 50 MB
        1.0
    """
    threshold_bytes = threshold_mb * 1024 * 1024

    if memory_bytes <= 0:
        return 1.0

    if memory_bytes <= threshold_bytes:
        return 1.0

    # Linear decay above threshold
    ratio = threshold_bytes / memory_bytes
    return max(0.0, ratio)


def throughput_score(
    items_per_second: float,
    target_throughput: float = 100.0,
) -> float:
    """Calculate score based on throughput (higher is better).

    Args:
        items_per_second: Processing rate.
        target_throughput: Target items/second (default: 100).

    Returns:
        Performance score between 0.0 and 1.0.

    Example:
        >>> throughput_score(150.0, target_throughput=100.0)
        1.0
        >>> throughput_score(50.0, target_throughput=100.0)
        0.5
    """
    if target_throughput <= 0:
        return 1.0 if items_per_second > 0 else 0.0

    ratio = items_per_second / target_throughput
    return min(1.0, ratio)


@contextmanager
def measure_time() -> Generator[dict[str, float], None, None]:
    """Context manager to measure execution time.

    Yields:
        Dict that will be populated with 'elapsed' key after context exits.

    Example:
        >>> with measure_time() as timing:
        ...     expensive_operation()
        >>> print(timing['elapsed'])
        0.123
    """
    result: dict[str, float] = {}
    start = time.perf_counter()
    try:
        yield result
    finally:
        result["elapsed"] = time.perf_counter() - start


def benchmark(
    func: Callable[..., T],
    *args: Any,
    iterations: int = 10,
    warmup: int = 2,
    **kwargs: Any,
) -> tuple[T, dict[str, float]]:
    """Benchmark a function with multiple iterations.

    Args:
        func: Function to benchmark.
        *args: Positional arguments to pass to func.
        iterations: Number of timed iterations (default: 10).
        warmup: Number of warmup iterations (default: 2).
        **kwargs: Keyword arguments to pass to func.

    Returns:
        Tuple of (last result, stats dict with min/max/mean/median times).

    Example:
        >>> result, stats = benchmark(sorted, [3, 1, 2], iterations=100)
        >>> print(stats['mean'])
        0.0001
    """
    # Warmup
    for _ in range(warmup):
        func(*args, **kwargs)

    # Timed runs
    times: list[float] = []
    result: T = None  # type: ignore

    for _ in range(iterations):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = time.perf_counter() - start
        times.append(elapsed)

    times.sort()
    stats = {
        "min": times[0],
        "max": times[-1],
        "mean": sum(times) / len(times),
        "median": times[len(times) // 2],
        "iterations": float(iterations),
    }

    return result, stats


def latency_percentiles(
    latencies: list[float],
    percentiles: list[int] | None = None,
) -> dict[str, float]:
    """Calculate latency percentiles.

    Args:
        latencies: List of latency measurements.
        percentiles: List of percentiles to calculate (default: p50, p90, p95, p99).

    Returns:
        Dict mapping percentile names to values.

    Example:
        >>> latency_percentiles([0.1, 0.2, 0.3, 0.4, 0.5])
        {'p50': 0.3, 'p90': 0.5, 'p95': 0.5, 'p99': 0.5}
    """
    if percentiles is None:
        percentiles = [50, 90, 95, 99]

    if not latencies:
        return {f"p{p}": 0.0 for p in percentiles}

    sorted_latencies = sorted(latencies)
    n = len(sorted_latencies)

    result = {}
    for p in percentiles:
        idx = int((p / 100) * n)
        idx = min(idx, n - 1)
        result[f"p{p}"] = sorted_latencies[idx]

    return result
