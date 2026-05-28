"""
Benchmark System for Multi-Agent Orchestrator
==============================================

Supports multiple industry-standard benchmarks for evaluating multi-agent
coding workflows. Data is fetched on-demand from official sources.

Supported Benchmarks:
- SWE-bench (Full, Verified, Lite) - Real GitHub issues
- HumanEval - Function-level coding
- MBPP - Python programming basics
- CodeClash - Goal-oriented development
- Custom - User-defined tasks

Usage:
    from tools.agents.benchmarks import BenchmarkRegistry, load_benchmark

    # List available benchmarks
    for name, info in BenchmarkRegistry.list_benchmarks().items():
        print(f"{name}: {info['description']}")

    # Load tasks from a benchmark
    tasks = load_benchmark("swe-bench-lite", limit=10)
"""

from __future__ import annotations

from .datasets import BENCHMARK_DEFINITIONS
from .loader import fetch_task, load_benchmark
from .registry import BenchmarkConfig, BenchmarkRegistry

__all__ = [
    "BENCHMARK_DEFINITIONS",
    "BenchmarkConfig",
    "BenchmarkRegistry",
    "fetch_task",
    "load_benchmark",
]
