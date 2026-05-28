"""Static metadata definitions for supported coding benchmarks.

Each ``BenchmarkDefinition`` describes a benchmark's source, size, metrics,
and evaluation method without fetching any data.  Actual task data is loaded
on demand by :mod:`tools.agents.benchmarks.loader`.

The ``BENCHMARK_DEFINITIONS`` dict is the single source of truth for
benchmark discovery across the repository.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class BenchmarkType(Enum):
    """Category of coding benchmark by task granularity."""

    SOFTWARE_ENGINEERING = "software_engineering"  # End-to-end issue resolution
    FUNCTION_LEVEL = "function_level"  # Single function completion
    BASIC_PROGRAMMING = "basic_programming"  # Simple coding tasks
    GOAL_ORIENTED = "goal_oriented"  # Real-world development goals
    CUSTOM = "custom"  # User-defined tasks


class DataSource(Enum):
    """Transport / origin type for benchmark task data."""

    HUGGINGFACE = "huggingface"  # HuggingFace datasets
    GITHUB = "github"  # GitHub repositories
    LOCAL = "local"  # Local JSON files
    API = "api"  # REST API endpoints


@dataclass
class BenchmarkDefinition:
    """Immutable metadata describing a single benchmark dataset.

    Contains no task data; actual tasks are fetched on demand via
    :func:`tools.agents.benchmarks.loader.load_benchmark`.

    Attributes:
        id: Unique identifier (e.g. ``"humaneval"``).
        name: Human-readable display name.
        description: One-sentence summary of what the benchmark tests.
        benchmark_type: Category (software engineering, function-level, etc.).
        size: Approximate number of tasks.
        source: Where task data is fetched from (HuggingFace, GitHub, local).
        source_url: URL or path passed to the loader.
        source_config: Loader-specific options (split, branch, etc.).
        metrics: Names of metrics produced (e.g. ``["pass@1"]``).
        evaluation_method: How results are judged (``"unit_tests"``, ``"execution"``).
        paper_url: URL of the benchmark's research paper.
        leaderboard_url: URL of the public leaderboard.
        license: Data license identifier.
        citation: BibTeX or inline citation string.
        languages: Programming languages covered.
        difficulty_range: Optional ``(min, max)`` difficulty tuple.
        tags: Free-form tags for filtering.
    """

    id: str  # Unique identifier
    name: str  # Display name
    description: str  # What this benchmark tests
    benchmark_type: BenchmarkType  # Category
    size: int  # Number of tasks (approximate)

    # Data source configuration
    source: DataSource  # Where to fetch from
    source_url: str  # URL/path to dataset
    source_config: dict[str, Any] = field(
        default_factory=dict
    )  # Source-specific config

    # Evaluation info
    metrics: list[str] = field(default_factory=list)  # How results are measured
    evaluation_method: str = "pass@1"  # Default evaluation approach

    # Metadata
    paper_url: str | None = None  # Research paper
    leaderboard_url: str | None = None  # Public leaderboard
    license: str = "unknown"  # Data license
    citation: str | None = None  # How to cite

    # Filtering options
    languages: list[str] = field(default_factory=lambda: ["python"])
    difficulty_range: tuple | None = None  # (min, max) if applicable
    tags: list[str] = field(default_factory=list)


# =============================================================================
# BENCHMARK DEFINITIONS
# =============================================================================

BENCHMARK_DEFINITIONS: dict[str, BenchmarkDefinition] = {
    # -------------------------------------------------------------------------
    # SWE-bench Family - Software Engineering
    # -------------------------------------------------------------------------
    "swe-bench": BenchmarkDefinition(
        id="swe-bench",
        name="SWE-bench",
        description="Real GitHub issues requiring code patches. Tests end-to-end software engineering ability.",
        benchmark_type=BenchmarkType.SOFTWARE_ENGINEERING,
        size=2294,
        source=DataSource.HUGGINGFACE,
        source_url="princeton-nlp/SWE-bench",
        source_config={
            "split": "test",
            "subset": None,
        },
        metrics=["resolved_rate", "patch_apply_rate"],
        evaluation_method="execution",
        paper_url="https://arxiv.org/abs/2310.06770",
        leaderboard_url="https://www.swebench.com/",
        license="MIT",
        citation="@article{jimenez2024swebench, title={SWE-bench: Can Language Models Resolve Real-World GitHub Issues?}}",
        languages=["python"],
        tags=["github", "issues", "patches", "real-world"],
    ),
    "swe-bench-verified": BenchmarkDefinition(
        id="swe-bench-verified",
        name="SWE-bench Verified",
        description="Human-validated subset of SWE-bench with confirmed solvable issues.",
        benchmark_type=BenchmarkType.SOFTWARE_ENGINEERING,
        size=500,
        source=DataSource.HUGGINGFACE,
        source_url="princeton-nlp/SWE-bench_Verified",
        source_config={
            "split": "test",
        },
        metrics=["resolved_rate"],
        evaluation_method="execution",
        paper_url="https://arxiv.org/abs/2310.06770",
        leaderboard_url="https://www.swebench.com/",
        license="MIT",
        languages=["python"],
        tags=["github", "verified", "reliable"],
    ),
    "swe-bench-lite": BenchmarkDefinition(
        id="swe-bench-lite",
        name="SWE-bench Lite",
        description="Smaller subset for faster evaluation and iteration.",
        benchmark_type=BenchmarkType.SOFTWARE_ENGINEERING,
        size=300,
        source=DataSource.HUGGINGFACE,
        source_url="princeton-nlp/SWE-bench_Lite",
        source_config={
            "split": "test",
        },
        metrics=["resolved_rate"],
        evaluation_method="execution",
        paper_url="https://arxiv.org/abs/2310.06770",
        leaderboard_url="https://www.swebench.com/",
        license="MIT",
        languages=["python"],
        tags=["github", "lite", "fast"],
    ),
    # -------------------------------------------------------------------------
    # HumanEval - Function-Level Coding
    # -------------------------------------------------------------------------
    "humaneval": BenchmarkDefinition(
        id="humaneval",
        name="HumanEval",
        description="Hand-written Python programming problems with unit tests. Tests function-level code generation.",
        benchmark_type=BenchmarkType.FUNCTION_LEVEL,
        size=164,
        source=DataSource.HUGGINGFACE,
        source_url="openai/openai_humaneval",
        source_config={
            "split": "test",
        },
        metrics=["pass@1", "pass@10", "pass@100"],
        evaluation_method="unit_tests",
        paper_url="https://arxiv.org/abs/2107.03374",
        leaderboard_url="https://paperswithcode.com/sota/code-generation-on-humaneval",
        license="MIT",
        citation="@article{chen2021evaluating, title={Evaluating Large Language Models Trained on Code}}",
        languages=["python"],
        tags=["functions", "unit-tests", "canonical"],
    ),
    "humaneval-plus": BenchmarkDefinition(
        id="humaneval-plus",
        name="HumanEval+",
        description="Extended HumanEval with 80x more test cases per problem.",
        benchmark_type=BenchmarkType.FUNCTION_LEVEL,
        size=164,
        source=DataSource.HUGGINGFACE,
        source_url="evalplus/humanevalplus",
        source_config={
            "split": "test",
        },
        metrics=["pass@1"],
        evaluation_method="unit_tests",
        paper_url="https://arxiv.org/abs/2305.01210",
        license="Apache-2.0",
        languages=["python"],
        tags=["functions", "extended-tests", "rigorous"],
    ),
    # -------------------------------------------------------------------------
    # MBPP - Basic Python Programming
    # -------------------------------------------------------------------------
    "mbpp": BenchmarkDefinition(
        id="mbpp",
        name="MBPP",
        description="Mostly Basic Python Problems. Entry-level programming tasks with test cases.",
        benchmark_type=BenchmarkType.BASIC_PROGRAMMING,
        size=974,
        source=DataSource.HUGGINGFACE,
        source_url="google-research-datasets/mbpp",
        source_config={
            "split": "test",
        },
        metrics=["pass@1", "pass@80"],
        evaluation_method="unit_tests",
        paper_url="https://arxiv.org/abs/2108.07732",
        leaderboard_url="https://paperswithcode.com/sota/code-generation-on-mbpp",
        license="CC-BY-4.0",
        citation="@article{austin2021program, title={Program Synthesis with Large Language Models}}",
        languages=["python"],
        tags=["basic", "entry-level", "crowd-sourced"],
    ),
    "mbpp-sanitized": BenchmarkDefinition(
        id="mbpp-sanitized",
        name="MBPP Sanitized",
        description="Cleaned subset of MBPP with verified solutions.",
        benchmark_type=BenchmarkType.BASIC_PROGRAMMING,
        size=427,
        source=DataSource.HUGGINGFACE,
        source_url="google-research-datasets/mbpp",
        source_config={
            "split": "test",
            "sanitized": True,
        },
        metrics=["pass@1"],
        evaluation_method="unit_tests",
        paper_url="https://arxiv.org/abs/2108.07732",
        license="CC-BY-4.0",
        languages=["python"],
        tags=["basic", "sanitized", "verified"],
    ),
    # -------------------------------------------------------------------------
    # CodeClash - Goal-Oriented Development (Newer)
    # -------------------------------------------------------------------------
    "codeclash": BenchmarkDefinition(
        id="codeclash",
        name="CodeClash",
        description="Goal-oriented development tasks simulating real-world software projects.",
        benchmark_type=BenchmarkType.GOAL_ORIENTED,
        size=100,  # Varies
        source=DataSource.GITHUB,
        source_url="codeclash-eval/codeclash",
        source_config={
            "branch": "main",
            "tasks_path": "tasks/",
        },
        metrics=["goal_completion", "code_quality", "test_coverage"],
        evaluation_method="goal_verification",
        license="Apache-2.0",
        languages=["python", "javascript", "typescript"],
        tags=["goals", "real-world", "multi-file"],
    ),
    # -------------------------------------------------------------------------
    # Custom/Local Benchmarks
    # -------------------------------------------------------------------------
    "custom-local": BenchmarkDefinition(
        id="custom-local",
        name="Custom Local Tasks",
        description="User-defined tasks stored in the local gold_standards directory.",
        benchmark_type=BenchmarkType.CUSTOM,
        size=10,
        source=DataSource.LOCAL,
        source_url="gold_standards/",
        source_config={
            "pattern": "task_*.json",
        },
        metrics=["component_coverage", "pattern_matching", "decision_coverage"],
        evaluation_method="heuristic",
        license="proprietary",
        languages=["python", "any"],
        tags=["custom", "local", "curated"],
    ),
}


def get_benchmark(benchmark_id: str) -> BenchmarkDefinition | None:
    """Get a benchmark definition by ID."""
    return BENCHMARK_DEFINITIONS.get(benchmark_id)


def list_benchmarks(
    benchmark_type: BenchmarkType | None = None,
    language: str | None = None,
) -> dict[str, BenchmarkDefinition]:
    """List available benchmarks with optional filtering.

    Args:
        benchmark_type: Filter by type (e.g., SOFTWARE_ENGINEERING)
        language: Filter by supported language

    Returns:
        Dict of matching benchmarks
    """
    result = {}
    for bid, bdef in BENCHMARK_DEFINITIONS.items():
        if benchmark_type and bdef.benchmark_type != benchmark_type:
            continue
        if language and language not in bdef.languages:
            continue
        result[bid] = bdef
    return result
