"""Task evaluation pipeline for the benchmark runner.

Provides LLM-based and legacy pattern-matching evaluation of benchmark
task outputs. This module contains the evaluation logic extracted from
runner.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.agents.benchmarks.loader import BenchmarkTask

# ---------------------------------------------------------------------------
# Optional dependency: legacy gold-standard evaluator
# ---------------------------------------------------------------------------
try:
    from tools.agents.test_tasks import (
        TEST_TASKS,
        evaluate_against_gold_standard,
        print_gold_standard_report,
    )

    HAS_GOLD_STANDARD = True
except ImportError:
    HAS_GOLD_STANDARD = False
    TEST_TASKS = []  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Optional dependency: LLM-based evaluator
# ---------------------------------------------------------------------------
try:
    from tools.agents.benchmarks.llm_evaluator import (
        EvaluationResult,
        evaluate_with_llm,
        print_evaluation_report,
        save_evaluation_report,
        summarize_batch_results,
    )

    HAS_LLM_EVALUATOR = True
except ImportError:
    HAS_LLM_EVALUATOR = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate_task_output_llm(
    task: BenchmarkTask,
    output: str,
    model: str,
    benchmark_id: str,
    verbose: bool = False,
    output_dir: Path | None = None,
    evaluator_model: str | None = None,
) -> dict[str, Any] | None:
    """Evaluate task output using LLM-based evaluation.

    Uses structured rubric scoring (0.0-10.0) with detailed reasoning.
    Falls back to legacy pattern-matching when the LLM evaluator is
    unavailable.
    """
    if not HAS_LLM_EVALUATOR:
        if verbose:
            print("  [!] LLM evaluator not available, falling back to pattern matching")
        return evaluate_task_output_legacy(task, output, verbose, output_dir)

    task_id = str(task.task_id)

    # Get gold standard data
    gold_data = get_gold_standard_for_task(task)
    if not gold_data:
        if verbose:
            print(f"  [!] No gold standard found for task: {task_id}")
        # Create minimal gold standard from task data
        gold_data = {
            "expected_output": task.expected_output or "",
            "test_cases": task.test_cases or [],
        }

    # Run LLM evaluation
    eval_result = evaluate_with_llm(
        task_id=task_id,
        task_prompt=task.prompt,
        generated_output=output,
        gold_standard=gold_data,
        model=model,
        benchmark_id=benchmark_id,
        evaluator_model=evaluator_model,
        verbose=verbose,
    )

    # Print report
    if verbose:
        print_evaluation_report(eval_result, verbose=True)
    else:
        print(
            f"  Score: {eval_result.overall_score:.1f}/10.0 (Grade: {eval_result.grade})"
        )

    # Save reports
    if output_dir:
        save_evaluation_report(eval_result, output_dir)
        print(f"  Evaluation saved: task_{task_id}_eval.md")

    # Return as dict for compatibility
    return eval_result.to_dict()


def get_gold_standard_for_task(task: BenchmarkTask) -> dict[str, Any] | None:
    """Return the gold-standard data dict for *task*, or ``None`` if unavailable."""
    if not HAS_GOLD_STANDARD:
        return None

    task_id = str(task.task_id)

    for tt in TEST_TASKS:
        tt_id_str = str(tt.id)
        if task_id == tt_id_str or task_id == f"task_{tt.id:03d}":
            return tt.get_gold_standard()
        try:
            if int(task_id) == tt.id:
                return tt.get_gold_standard()
        except ValueError:
            pass

    return None


def evaluate_task_output_legacy(
    task: BenchmarkTask,
    output: str,
    verbose: bool = False,
    output_dir: Path | None = None,
) -> dict[str, Any] | None:
    """Legacy pattern-matching evaluation (fallback when LLM evaluator is absent)."""
    if not HAS_GOLD_STANDARD:
        return None

    task_id = str(task.task_id)

    # Try to find matching gold standard
    gold_task = None
    for tt in TEST_TASKS:
        tt_id_str = str(tt.id)
        if task_id == tt_id_str or task_id == f"task_{tt.id:03d}":
            gold_task = tt
            break
        try:
            if int(task_id) == tt.id:
                gold_task = tt
                break
        except ValueError:
            pass

    if not gold_task:
        if verbose:
            print(f"  [!] No gold standard found for task: {task_id}")
        return None

    gold_data = gold_task.get_gold_standard()
    if not gold_data:
        if verbose:
            print(f"  [!] Could not load gold standard for task: {task_id}")
        return None

    eval_result = evaluate_against_gold_standard(output, gold_data)

    if verbose:
        print_gold_standard_report(eval_result, verbose=True)
        print_mismatch_analysis(eval_result, gold_data, output)
    else:
        score = eval_result.get("overall_score", 0)
        grade = eval_result.get("grade", "N/A")
        print(f"  Score: {score:.1f}/100 (Grade: {grade})")

    if output_dir:
        save_evaluation_report_legacy(
            task_id, eval_result, gold_data, output, output_dir
        )

    return eval_result


def print_mismatch_analysis(
    eval_result: dict[str, Any],
    gold_data: dict[str, Any],
    output: str,
) -> None:
    """Print a detailed analysis of why items did not match the gold standard."""
    print("\n" + "-" * 60)
    print("DETAILED MISMATCH ANALYSIS")
    print("-" * 60)

    has_issues = False

    # Components
    missing_components = eval_result.get("components", {}).get("missing", [])
    if missing_components:
        has_issues = True
        print("\n[!] MISSING COMPONENTS:")
        for comp in missing_components:
            print(f"    Expected: '{comp}'")
            comp_lower = comp.lower()
            for line in output.split("\n"):
                line_lower = line.lower()
                words = comp_lower.split()
                if any(word in line_lower for word in words if len(word) > 3):
                    print(f"    Similar:  '{line.strip()[:80]}'")
                    break

    # Patterns
    missing_patterns = eval_result.get("patterns", {}).get("missing", [])
    if missing_patterns:
        has_issues = True
        print("\n[!] MISSING PATTERNS:")
        for pattern in missing_patterns:
            print(f"    Expected regex: {pattern}")

    # Key Decisions
    missing_decisions = eval_result.get("decisions", {}).get("missing", [])
    if missing_decisions:
        has_issues = True
        print("\n[!] MISSING KEY DECISIONS:")
        for decision in missing_decisions:
            print(f"    Expected mention of: '{decision}'")
            keywords = [w for w in decision.lower().split() if len(w) > 3]
            print(f"    Keywords checked: {keywords}")

    # Endpoints
    missing_endpoints = eval_result.get("endpoints", {}).get("missing", [])
    if missing_endpoints:
        has_issues = True
        print("\n[!] MISSING API ENDPOINTS:")
        for ep in missing_endpoints:
            print(f"    Expected: '{ep}'")

    # Tables
    missing_tables = eval_result.get("tables", {}).get("missing", [])
    if missing_tables:
        has_issues = True
        print("\n[!] MISSING DATABASE TABLES:")
        for table in missing_tables:
            print(f"    Expected: '{table}'")

    if not has_issues:
        print("\n  [+] All gold standard criteria met!")
    else:
        print("\n  TIP: Review the output file and gold standard to understand gaps.")


def save_evaluation_report_legacy(
    task_id: str,
    eval_result: dict[str, Any],
    gold_data: dict[str, Any],
    output: str,
    output_dir: Path,
) -> None:
    """Persist a legacy pattern-matching evaluation report as Markdown."""
    report_file = output_dir / f"task_{task_id}_evaluation.md"

    lines = [
        f"# Evaluation Report: Task {task_id}",
        "",
        f"**Score:** {eval_result.get('overall_score', 0):.1f}/100",
        f"**Grade:** {eval_result.get('grade', 'N/A')}",
        "",
        "## Category Scores",
        "",
    ]

    for category in ["components", "patterns", "decisions", "endpoints", "tables"]:
        cat_data = eval_result.get(category, {})
        score = cat_data.get("score", 0)
        matched = cat_data.get("matched", [])
        missing = cat_data.get("missing", [])

        lines.append(f"### {category.title()}: {score:.0f}%")
        lines.append("")

        if matched:
            lines.append("**Matched:**")
            for item in matched:
                lines.append(f"- [x] {item}")
            lines.append("")

        if missing:
            lines.append("**Missing:**")
            for item in missing:
                lines.append(f"- [ ] {item}")
            lines.append("")

    api_endpoints = gold_data.get("api_endpoints", [])
    endpoints_str = [f"{e['method']} {e['path']}" for e in api_endpoints]

    lines.extend(
        [
            "## Gold Standard Reference",
            "",
            f"**Required Components:** {gold_data.get('required_components', [])}",
            "",
            f"**Required Patterns:** {gold_data.get('required_patterns', [])}",
            "",
            f"**Key Decisions:** {gold_data.get('key_decisions', [])}",
            "",
            f"**API Endpoints:** {endpoints_str}",
            "",
            f"**Database Tables:** {gold_data.get('database_tables', [])}",
            "",
            "## Output Preview (first 2000 chars)",
            "",
            "```",
            output[:2000],
            "```",
        ]
    )

    report_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Evaluation report: {report_file.name}")
