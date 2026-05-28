"""05 — Score a workflow output using the agentic-v2-eval framework.

Demonstrates:
    - Creating a :class:`Scorer` with an inline rubric definition.
    - Scoring a set of evaluation metrics against the rubric.
    - Inspecting :class:`ScoringResult` (weighted scores, per-criterion
      breakdown, missing criteria).
    - Using :func:`load_rubric` and :func:`list_rubrics` to discover
      built-in rubrics.
    - Using :class:`StandardEvaluator` concepts (shown as a rubric-only
      demo since LLM-as-judge requires API keys).

No API keys are required.  The scorer operates on pre-computed metrics.

Usage:
    python examples/05_evaluation.py
"""

from __future__ import annotations

import logging
import sys

# ---- Eval framework imports -----------------------------------------------
from agentic_v2_eval import Scorer, ScoringResult
from agentic_v2_eval.rubrics import list_rubrics, load_rubric

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


def demo_inline_rubric() -> None:
    """Score metrics against an inline rubric definition."""
    print("=" * 60)
    print("1. Scoring with an Inline Rubric")
    print("=" * 60)

    # Define a rubric as a Python dict (same schema as YAML files).
    # Criteria have names, weights, and valid ranges.
    rubric = {
        "name": "Code Review Quality",
        "version": "1.0",
        "criteria": [
            {
                "name": "Accuracy",
                "weight": 2.0,
                "description": "Correctness of findings relative to actual code issues",
                "min_value": 0.0,
                "max_value": 1.0,
            },
            {
                "name": "Completeness",
                "weight": 1.5,
                "description": "Coverage of all relevant code quality dimensions",
                "min_value": 0.0,
                "max_value": 1.0,
            },
            {
                "name": "Actionability",
                "weight": 1.0,
                "description": "Clarity and usefulness of suggested improvements",
                "min_value": 0.0,
                "max_value": 1.0,
            },
            {
                "name": "Efficiency",
                "weight": 0.5,
                "description": "Time and resource usage during review",
                "min_value": 0.0,
                "max_value": 1.0,
            },
        ],
    }

    # Create a Scorer from the rubric dict
    scorer = Scorer(rubric)
    print(f"  Rubric: {scorer.name} v{scorer.version}")
    print(f"  Criteria: {len(scorer.criteria)}")
    for c in scorer.criteria:
        print(
            f"    - {c.name} (weight={c.weight}, range=[{c.min_value}, {c.max_value}])"
        )

    # Simulate evaluation metrics from a workflow run
    metrics = {
        "Accuracy": 0.85,
        "Completeness": 0.72,
        "Actionability": 0.90,
        "Efficiency": 0.65,
    }

    print(f"\n  Input metrics: {metrics}")

    # Score the metrics
    result: ScoringResult = scorer.score(metrics)

    print("\n  Results:")
    print(f"    Weighted score: {result.weighted_score:.3f}")
    print(f"    Total score   : {result.total_score:.3f}")
    print("    Per-criterion :")
    for name, value in result.criterion_scores.items():
        print(f"      {name}: {value:.2f}")
    if result.missing_criteria:
        print(f"    Missing criteria: {result.missing_criteria}")


def demo_missing_criteria() -> None:
    """Show how the scorer handles missing criteria gracefully."""
    print("\n" + "=" * 60)
    print("2. Handling Missing Criteria")
    print("=" * 60)

    rubric = {
        "name": "Agent Evaluation",
        "criteria": [
            {"name": "Task_Completion", "weight": 2.0},
            {"name": "Response_Quality", "weight": 1.5},
            {"name": "Safety", "weight": 3.0},
            {"name": "Latency", "weight": 0.5},
        ],
    }

    scorer = Scorer(rubric)

    # Only provide some metrics (missing Safety and Latency)
    partial_metrics = {
        "Task_Completion": 0.95,
        "Response_Quality": 0.80,
    }

    # Validate before scoring
    missing = scorer.validate_results(partial_metrics)
    print(f"  Missing criteria: {missing}")

    # Score still works — missing criteria are reported but don't crash
    result = scorer.score(partial_metrics)
    print(f"  Weighted score (partial): {result.weighted_score:.3f}")
    print(f"  Missing in result: {result.missing_criteria}")


def demo_built_in_rubrics() -> None:
    """Discover and inspect built-in rubric files."""
    print("\n" + "=" * 60)
    print("3. Built-in Rubrics")
    print("=" * 60)

    available = list_rubrics()
    print(f"  Available rubrics: {available}")

    # Load and inspect the default rubric
    if "default" in available:
        default_rubric = load_rubric("default")
        print("\n  Default rubric:")
        print(f"    Name: {default_rubric.get('name', 'N/A')}")
        criteria = default_rubric.get("criteria", [])
        print(f"    Criteria count: {len(criteria)}")
        for c in criteria[:5]:  # Show first 5
            print(f"      - {c.get('name', 'unnamed')} (weight={c.get('weight', 1.0)})")

    # Load and inspect the code rubric if available
    if "code" in available:
        code_rubric = load_rubric("code")
        print("\n  Code rubric:")
        print(f"    Name: {code_rubric.get('name', 'N/A')}")
        criteria = code_rubric.get("criteria", [])
        print(f"    Criteria count: {len(criteria)}")
        for c in criteria[:5]:
            print(f"      - {c.get('name', 'unnamed')} (weight={c.get('weight', 1.0)})")


def demo_scoring_comparison() -> None:
    """Compare two workflow runs using the same rubric."""
    print("\n" + "=" * 60)
    print("4. Comparing Workflow Runs")
    print("=" * 60)

    rubric = {
        "name": "Workflow Comparison",
        "criteria": [
            {"name": "Accuracy", "weight": 2.0},
            {"name": "Speed", "weight": 1.0},
            {"name": "Cost", "weight": 1.5},
        ],
    }

    scorer = Scorer(rubric)

    # Run A: High accuracy, slow, expensive
    run_a = {"Accuracy": 0.95, "Speed": 0.40, "Cost": 0.30}
    result_a = scorer.score(run_a)

    # Run B: Good accuracy, fast, cheap
    run_b = {"Accuracy": 0.82, "Speed": 0.90, "Cost": 0.85}
    result_b = scorer.score(run_b)

    print(f"  Run A (high accuracy): weighted={result_a.weighted_score:.3f}")
    print(f"    {run_a}")
    print(f"  Run B (balanced):      weighted={result_b.weighted_score:.3f}")
    print(f"    {run_b}")

    winner = "A" if result_a.weighted_score > result_b.weighted_score else "B"
    print(f"\n  Winner: Run {winner}")
    print("  (Because Accuracy has weight=2.0, it dominates the score)")


def main() -> None:
    """Run all evaluation demonstrations."""
    demo_inline_rubric()
    demo_missing_criteria()
    demo_built_in_rubrics()
    demo_scoring_comparison()

    print("\n" + "=" * 60)
    print("All evaluation demos complete.")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
