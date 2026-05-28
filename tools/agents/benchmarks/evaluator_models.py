"""Data models and rubric constants for LLM-as-judge evaluation.

Defines the scoring rubric, evaluation dimensions, and the core dataclasses
(:class:`DimensionScore`, :class:`EvaluationResult`) used throughout the
benchmark evaluation pipeline.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

# =============================================================================
# SCORING RUBRIC (0.0 - 10.0 Scale)
# =============================================================================

SCORE_RUBRIC = {
    10.0: "Perfect - Flawless execution, all requirements met, exceeds expectations",
    9.0: "Excellent - Near-perfect, trivial gaps only, production-ready",
    8.0: "Very Good - Strong output, 1-2 minor issues, high quality",
    7.0: "Good - Solid work, meets most requirements, some improvements possible",
    6.0: "Adequate - Acceptable output, notable gaps but fundamentally correct",
    5.0: "Fair - Partially correct, significant gaps, needs improvement",
    4.0: "Below Average - Multiple issues, incomplete, misses key requirements",
    3.0: "Poor - Major deficiencies, barely usable",
    2.0: "Very Poor - Fundamental problems, largely incorrect",
    1.0: "Extremely Poor - Minimal effort, almost unusable",
    0.0: "Failed - Did not produce relevant output or completely wrong",
}

# Evaluation dimensions (generic, applicable to all task types)
EVALUATION_DIMENSIONS = {
    "completeness": {
        "description": "Does the output address all requirements from the task?",
        "weight": 0.25,
    },
    "correctness": {
        "description": "Is the output technically correct and follows best practices?",
        "weight": 0.25,
    },
    "quality": {
        "description": "Is the output well-structured, clear, and maintainable?",
        "weight": 0.20,
    },
    "specificity": {
        "description": "Does the output provide specific, actionable details rather than generic advice?",
        "weight": 0.15,
    },
    "alignment": {
        "description": "Does the output align with the gold standard expectations?",
        "weight": 0.15,
    },
}


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class DimensionScore:
    """Score for a single evaluation dimension on a 0.0--10.0 scale.

    Attributes:
        dimension: Dimension name (e.g. ``"completeness"``).
        score: Raw score in ``[0.0, 10.0]``.
        reasoning: Free-text explanation from the LLM judge.
        evidence: Specific quotes or examples supporting the score.
        weight: Relative weight used when computing the overall score.
    """

    dimension: str
    score: float  # 0.0 - 10.0
    reasoning: str
    evidence: list[str] = field(default_factory=list)  # Specific quotes/examples
    weight: float = 0.2

    @property
    def weighted_score(self) -> float:
        return self.score * self.weight


@dataclass
class EvaluationResult:
    """Complete evaluation result for a single benchmark task.

    Aggregates per-dimension scores, overall weighted score, letter grade,
    qualitative analysis (strengths / weaknesses / suggestions), and
    timing metadata.

    Attributes:
        task_id: Unique task identifier within the benchmark.
        model: Model that produced the generated output.
        benchmark_id: Benchmark the task belongs to.
        timestamp: ISO-8601 timestamp of the evaluation.
        dimension_scores: Per-dimension :class:`DimensionScore` mapping.
        overall_score: Weighted aggregate score (0.0--10.0).
        grade: Letter grade derived from ``overall_score``.
        task_prompt: The original task prompt text.
        generated_output: The model-generated output that was evaluated.
        gold_standard_summary: Truncated JSON representation of the gold standard.
        duration_seconds: Wall-clock seconds the evaluation took.
        evaluator_model: Model used as the LLM judge.
        strengths: Judge-identified strengths.
        weaknesses: Judge-identified weaknesses.
        improvement_suggestions: Actionable improvement suggestions.
        key_findings: High-level findings from the evaluation.
    """

    task_id: str
    model: str
    benchmark_id: str
    timestamp: str

    # Scores
    dimension_scores: dict[str, DimensionScore] = field(default_factory=dict)
    overall_score: float = 0.0
    grade: str = "F"

    # Content
    task_prompt: str = ""
    generated_output: str = ""
    gold_standard_summary: str = ""

    # Metadata
    duration_seconds: float = 0.0
    evaluator_model: str = ""

    # Analysis
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    improvement_suggestions: list[str] = field(default_factory=list)
    key_findings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        # Convert DimensionScore to dict
        result["dimension_scores"] = {
            k: asdict(v) for k, v in self.dimension_scores.items()
        }
        return result

    @staticmethod
    def grade_from_score(score: float) -> str:
        """Convert 0-10 score to letter grade."""
        if score >= 9.0:
            return "A"
        elif score >= 8.0:
            return "B"
        elif score >= 7.0:
            return "C"
        elif score >= 6.0:
            return "D"
        else:
            return "F"


# =============================================================================
# BATCH SUMMARY MODEL
# =============================================================================


@dataclass
class BatchEvaluationSummary:
    """Aggregate statistics across a batch of :class:`EvaluationResult` objects.

    Attributes:
        benchmark_id: Benchmark that was evaluated.
        model: Model that generated the outputs.
        evaluator_model: Model used as LLM judge.
        timestamp: ISO-8601 timestamp of the summary.
        output_directory: Directory where per-task reports were saved.
        total_tasks: Total number of tasks in the batch.
        evaluated_tasks: Number successfully evaluated.
        average_score: Mean overall score across tasks.
        grade_distribution: Mapping of letter grade to count.
        dimension_averages: Mean score per evaluation dimension.
        top_strengths: Most frequently cited strengths.
        common_weaknesses: Most frequently cited weaknesses.
    """

    benchmark_id: str
    model: str
    evaluator_model: str
    timestamp: str
    output_directory: str

    total_tasks: int = 0
    evaluated_tasks: int = 0
    average_score: float = 0.0
    grade_distribution: dict[str, int] = field(default_factory=dict)
    dimension_averages: dict[str, float] = field(default_factory=dict)

    top_strengths: list[str] = field(default_factory=list)
    common_weaknesses: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
