"""Output formatting and batch reporting for LLM-as-judge evaluation results.

Provides console report printing, file-based report saving (JSON +
Markdown), and batch summarisation helpers.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from tools.agents.benchmarks.evaluator_models import (
    BatchEvaluationSummary,
    EvaluationResult,
)

# =============================================================================
# CONSOLE REPORTING
# =============================================================================


def print_evaluation_report(result: EvaluationResult, verbose: bool = True) -> None:
    """Print formatted evaluation report to console."""
    print("\n" + "=" * 70)
    print("LLM EVALUATION REPORT")
    print("=" * 70)

    print(f"\nTask: {result.task_id}")
    print(f"Model: {result.model}")
    print(f"Evaluator: {result.evaluator_model}")
    print(f"Benchmark: {result.benchmark_id}")

    print(f"\n{'─' * 50}")
    print(f"OVERALL SCORE: {result.overall_score:.1f}/10.0 (Grade: {result.grade})")
    print(f"{'─' * 50}")

    # Dimension scores
    print("\nDIMENSION SCORES:")
    for name, dim in sorted(result.dimension_scores.items()):
        bar = "█" * int(dim.score) + "░" * (10 - int(dim.score))
        print(f"  {name:15} {bar} {dim.score:.1f}/10 (w={dim.weight})")
        if verbose and dim.reasoning:
            # Wrap reasoning text
            reason_lines = [
                dim.reasoning[i : i + 55] for i in range(0, len(dim.reasoning), 55)
            ]
            for line in reason_lines[:2]:  # Limit to 2 lines
                print(f"                  {line}")

    # Strengths
    if result.strengths:
        print("\n[+] STRENGTHS:")
        for s in result.strengths[:5]:
            print(f"    - {s}")

    # Weaknesses
    if result.weaknesses:
        print("\n[-] WEAKNESSES:")
        for w in result.weaknesses[:5]:
            print(f"    - {w}")

    # Suggestions
    if result.improvement_suggestions and verbose:
        print("\n[>] SUGGESTIONS:")
        for s in result.improvement_suggestions[:3]:
            print(f"    - {s}")

    # Key findings
    if result.key_findings and verbose:
        print("\n[!] KEY FINDINGS:")
        for f in result.key_findings[:3]:
            print(f"    - {f}")


# =============================================================================
# FILE REPORTING
# =============================================================================


def save_evaluation_report(result: EvaluationResult, output_dir: Path) -> Path:
    """Save detailed evaluation report to files."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save JSON report
    json_file = output_dir / f"task_{result.task_id}_eval.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2)

    # Save Markdown report
    md_file = output_dir / f"task_{result.task_id}_eval.md"

    md_content = [
        f"# Evaluation Report: Task {result.task_id}",
        "",
        f"**Model:** {result.model}",
        f"**Evaluator:** {result.evaluator_model}",
        f"**Benchmark:** {result.benchmark_id}",
        f"**Timestamp:** {result.timestamp}",
        f"**Duration:** {result.duration_seconds:.1f}s",
        "",
        f"## Overall Score: {result.overall_score:.1f}/10.0 (Grade: {result.grade})",
        "",
        "## Dimension Scores",
        "",
        "| Dimension | Score | Weight | Weighted |",
        "|-----------|-------|--------|----------|",
    ]

    for name, dim in sorted(result.dimension_scores.items()):
        md_content.append(
            f"| {name.title()} | {dim.score:.1f} | {dim.weight} | {dim.weighted_score:.2f} |"
        )

    md_content.extend(
        [
            "",
            "### Detailed Reasoning",
            "",
        ]
    )

    for name, dim in sorted(result.dimension_scores.items()):
        md_content.extend(
            [
                f"#### {name.title()} ({dim.score:.1f}/10)",
                "",
                dim.reasoning,
                "",
            ]
        )
        if dim.evidence:
            md_content.append("**Evidence:**")
            for e in dim.evidence:
                md_content.append(f"- {e}")
            md_content.append("")

    # Strengths and weaknesses
    md_content.extend(
        [
            "## Strengths",
            "",
        ]
    )
    for s in result.strengths:
        md_content.append(f"- {s}")

    md_content.extend(
        [
            "",
            "## Weaknesses",
            "",
        ]
    )
    for w in result.weaknesses:
        md_content.append(f"- {w}")

    md_content.extend(
        [
            "",
            "## Improvement Suggestions",
            "",
        ]
    )
    for s in result.improvement_suggestions:
        md_content.append(f"- {s}")

    md_content.extend(
        [
            "",
            "## Key Findings",
            "",
        ]
    )
    for f in result.key_findings:
        md_content.append(f"- {f}")

    # Gold standard reference
    md_content.extend(
        [
            "",
            "## Gold Standard Reference",
            "",
            "```json",
            result.gold_standard_summary,
            "```",
            "",
            "## Generated Output Preview",
            "",
            "```",
            result.generated_output[:3000],
            "```" if len(result.generated_output) <= 3000 else "... (truncated)",
        ]
    )

    md_file.write_text("\n".join(md_content), encoding="utf-8")

    return md_file


# =============================================================================
# BATCH SUMMARISATION
# =============================================================================


def summarize_batch_results(results: list[EvaluationResult]) -> BatchEvaluationSummary:
    """Summarize batch evaluation results."""
    if not results:
        return BatchEvaluationSummary(
            benchmark_id="",
            model="",
            evaluator_model="",
            timestamp=datetime.now().isoformat(),
            output_directory="",
        )

    first = results[0]

    # Calculate averages
    scores = [r.overall_score for r in results]
    avg_score = sum(scores) / len(scores)

    # Grade distribution
    grades = [r.grade for r in results]
    grade_dist = {g: grades.count(g) for g in set(grades)}

    # Dimension averages
    dim_totals: dict[str, list[float]] = {}
    for r in results:
        for dim_name, dim_score in r.dimension_scores.items():
            if dim_name not in dim_totals:
                dim_totals[dim_name] = []
            dim_totals[dim_name].append(dim_score.score)

    dim_avgs = {name: sum(vals) / len(vals) for name, vals in dim_totals.items()}

    # Collect all strengths/weaknesses
    all_strengths: list[str] = []
    all_weaknesses: list[str] = []
    for r in results:
        all_strengths.extend(r.strengths)
        all_weaknesses.extend(r.weaknesses)

    top_strengths = [s for s, _ in Counter(all_strengths).most_common(5)]
    common_weaknesses = [w for w, _ in Counter(all_weaknesses).most_common(5)]

    return BatchEvaluationSummary(
        benchmark_id=first.benchmark_id,
        model=first.model,
        evaluator_model=first.evaluator_model,
        timestamp=datetime.now().isoformat(),
        output_directory="",
        total_tasks=len(results),
        evaluated_tasks=len(results),
        average_score=avg_score,
        grade_distribution=grade_dist,
        dimension_averages=dim_avgs,
        top_strengths=top_strengths,
        common_weaknesses=common_weaknesses,
    )
