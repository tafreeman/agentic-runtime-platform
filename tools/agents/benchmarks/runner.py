#!/usr/bin/env python3
"""
Benchmark Runner - Interactive CLI
==================================

Interactive command-line interface for running multi-agent benchmarks.
Supports dataset, model, and workflow selection.

Usage:
    # Interactive mode
    python -m tools.agents.benchmarks.runner

    # Direct mode with arguments
    python -m tools.agents.benchmarks.runner --benchmark humaneval --model gh:gpt-4o-mini --limit 5

    # Use preset configuration
    python -m tools.agents.benchmarks.runner --preset quick-test

CLI subcommand handlers (cmd_* functions) live in :mod:`runner_commands`.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parents[3]))

from tools.agents.benchmarks.evaluation_pipeline import (
    evaluate_task_output_llm,
)
from tools.agents.benchmarks.loader import load_benchmark
from tools.agents.benchmarks.registry import (
    PRESET_CONFIGS,
    BenchmarkConfig,
)

# ---------------------------------------------------------------------------
# Re-exports for backward compatibility
# ---------------------------------------------------------------------------
from tools.agents.benchmarks.runner_commands import (
    cmd_clear_cache,
    cmd_discover_models,
    cmd_info,
    cmd_list_benchmarks,
    cmd_list_models,
    cmd_list_presets,
    cmd_run,
)
from tools.agents.benchmarks.runner_ui import (
    interactive_mode,
    print_header,
    prompt_input,
    prompt_yes_no,
)
from tools.agents.benchmarks.workflow_pipeline import (
    extract_workflow_data,
    save_workflow_phases_md,
)

# =============================================================================
# CORE RUNNER
# =============================================================================


def _create_output_dir(config: BenchmarkConfig) -> Path:
    """Create and return the timestamped output directory for this run."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = (
        Path(__file__).parents[3]
        / "results"
        / "benchmark_runs"
        / f"{config.benchmark_id}_{timestamp}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"  Output directory: {output_dir}")
    return output_dir


def _create_orchestrator(config: BenchmarkConfig) -> Any:
    """Return a workflow orchestrator, or ``None`` for direct execution mode."""
    if config.workflow == "multi-agent":
        from tools.agents.multi_agent_orchestrator import MultiAgentOrchestrator

        return MultiAgentOrchestrator(
            model=config.model,
            verbose=config.verbose,
        )

    # Placeholder for other workflows
    print(f"⚠ Workflow '{config.workflow}' not yet implemented")
    print("  Using direct execution mode")
    return None


def _generate_task_output(
    config: BenchmarkConfig,
    orchestrator: Any,
    task: Any,
) -> tuple[str, bool, dict[str, Any] | None]:
    """Run a single task, returning (output, success flag, workflow_data)."""
    if orchestrator:
        # Multi-agent execution
        result = orchestrator.run(task.prompt)
        output = result.final_output
        task_success = result.metadata.get("successful_tasks", 0) > 0

        # Capture full workflow data for all phases WITH per-agent evaluation
        print("  Evaluating individual agent outputs...")
        workflow_data = extract_workflow_data(
            result,
            evaluate_phases=True,
            model=config.model,
            benchmark_id=config.benchmark_id,
            original_prompt=task.prompt,
            verbose=config.verbose,
        )
        return output, task_success, workflow_data

    # Direct LLM call (placeholder)
    from tools.llm.llm_client import LLMClient

    output = LLMClient.generate_text(config.model, task.prompt)
    return output, bool(output), None


def _save_workflow_data(
    workflow_data: dict[str, Any],
    task: Any,
    output_dir: Path,
    task_result: dict[str, Any],
) -> None:
    """Persist workflow JSON + per-phase Markdown for a task."""
    task_result["workflow"] = workflow_data
    # Save detailed workflow file
    workflow_file = output_dir / f"task_{task.task_id}_workflow.json"
    with open(workflow_file, "w", encoding="utf-8") as f:
        json.dump(workflow_data, f, indent=2, default=str)
    print(f"  Workflow saved: {workflow_file.name}")

    # Save each phase output as markdown for readability
    save_workflow_phases_md(workflow_data, task.task_id, output_dir)


def _evaluate_and_record(
    config: BenchmarkConfig,
    task: Any,
    output: str,
    output_dir: Path,
    task_result: dict[str, Any],
) -> None:
    """Run LLM evaluation for *output* and merge scores into *task_result*."""
    eval_result = evaluate_task_output_llm(
        task=task,
        output=output,
        model=config.model,
        benchmark_id=config.benchmark_id,
        verbose=config.verbose,
        output_dir=output_dir,
        evaluator_model=config.model,  # Use same model for eval
    )
    if eval_result:
        task_result["evaluation"] = eval_result
        # Score is now 0-10, convert display
        task_result["score"] = eval_result.get("overall_score", 0)
        task_result["grade"] = eval_result.get("grade", "N/A")


def _run_single_task(
    config: BenchmarkConfig,
    orchestrator: Any,
    task: Any,
    output_dir: Path,
) -> tuple[dict[str, Any], bool]:
    """Execute one task and return its result dict plus success flag."""
    start_time = datetime.now()
    output, task_success, workflow_data = _generate_task_output(
        config, orchestrator, task
    )

    duration = (datetime.now() - start_time).total_seconds()

    task_result: dict[str, Any] = {
        "task_id": task.task_id,
        "success": task_success,
        "duration_seconds": duration,
        "output_length": len(output) if output else 0,
    }

    # Save workflow phases data (all agent outputs)
    if workflow_data:
        _save_workflow_data(workflow_data, task, output_dir, task_result)

    # Save generated output to file
    if output:
        output_file = output_dir / f"task_{task.task_id}_output.md"
        output_file.write_text(output, encoding="utf-8")
        task_result["output_file"] = str(output_file)
        print(f"  Output saved: {output_file.name}")

    # LLM-based evaluation (new default)
    if output:
        _evaluate_and_record(config, task, output, output_dir, task_result)

    if config.save_intermediate:
        task_result["output"] = output

    return task_result, task_success


def _print_task_header(task: Any, index: int, total: int, verbose: bool) -> None:
    """Print the separator banner (and optional prompt preview) for a task."""
    print(f"\n{'─' * 60}")
    print(f"Task {index}/{total}: {task.task_id}")
    print(f"{'─' * 60}")

    if verbose:
        prompt_preview = (
            task.prompt[:200] + "..." if len(task.prompt) > 200 else task.prompt
        )
        print(f"\nPrompt: {prompt_preview}\n")


def _execute_all_tasks(
    config: BenchmarkConfig,
    orchestrator: Any,
    tasks: list[Any],
    output_dir: Path,
    results: dict[str, Any],
) -> tuple[int, int]:
    """Run every task, appending results; return (successful, failed) counts."""
    successful = 0
    failed = 0

    for i, task in enumerate(tasks, 1):
        _print_task_header(task, i, len(tasks), config.verbose)

        try:
            task_result, task_success = _run_single_task(
                config, orchestrator, task, output_dir
            )
            results["tasks"].append(task_result)

            if task_success:
                successful += 1
                print(f"✓ Completed in {task_result['duration_seconds']:.1f}s")
            else:
                failed += 1
                print(f"✗ Failed in {task_result['duration_seconds']:.1f}s")

        except Exception as e:
            failed += 1
            results["tasks"].append(
                {
                    "task_id": task.task_id,
                    "success": False,
                    "error": str(e),
                }
            )
            print(f"✗ Error: {e}")

    return successful, failed


def _summarize_results(
    results: dict[str, Any],
    tasks: list[Any],
    successful: int,
    failed: int,
) -> None:
    """Compute and print the run summary, mutating ``results['summary']``."""
    results["completed_at"] = datetime.now().isoformat()
    results["summary"] = {
        "total_tasks": len(tasks),
        "successful": successful,
        "failed": failed,
        "success_rate": successful / len(tasks) if tasks else 0,
    }

    # Calculate average score if evaluations exist
    scores = [t.get("score", 0) for t in results["tasks"] if "score" in t]
    avg_score = 0.0
    grade_counts: dict[str, int] = {}
    if scores:
        avg_score = sum(scores) / len(scores)
        results["summary"]["average_score"] = avg_score
        results["summary"]["evaluated_tasks"] = len(scores)

        # Grade distribution
        grades = [t.get("grade", "N/A") for t in results["tasks"] if "grade" in t]
        grade_counts = {g: grades.count(g) for g in set(grades)}
        results["summary"]["grade_distribution"] = grade_counts

    print_header("RESULTS SUMMARY")
    print(f"  Total:     {len(tasks)}")
    print(f"  Successful: {successful} ({results['summary']['success_rate']:.1%})")
    print(f"  Failed:    {failed}")

    # Show evaluation summary
    if scores:
        print("\n  EVALUATION SCORES (0.0-10.0 scale)")
        print(f"  Average Score: {avg_score:.2f}/10.0")
        print("  Grade Distribution:")
        for grade in ["A", "B", "C", "D", "F"]:
            if grade in grade_counts:
                print(f"    {grade}: {grade_counts[grade]}")


def run_benchmark(config: BenchmarkConfig) -> dict[str, Any]:
    """Execute benchmark with given configuration.

    Returns results dictionary.
    """
    print_header("RUNNING BENCHMARK")

    # Create output directory for this run
    output_dir = _create_output_dir(config)

    # Load tasks
    tasks = load_benchmark(
        config.benchmark_id,
        limit=config.limit,
        use_cache=config.use_cache,
    )

    if not tasks:
        print("⚠ No tasks loaded!")
        return {"error": "No tasks loaded", "tasks_run": 0}

    print(f"\n✓ Loaded {len(tasks)} tasks")

    # Initialize orchestrator based on workflow
    results: dict[str, Any] = {
        "config": config.to_dict(),
        "started_at": datetime.now().isoformat(),
        "tasks": [],
        "summary": {},
    }

    orchestrator = _create_orchestrator(config)

    # Run each task
    successful, failed = _execute_all_tasks(
        config, orchestrator, tasks, output_dir, results
    )

    # Summary
    _summarize_results(results, tasks, successful, failed)

    # Save results summary
    results["output_directory"] = str(output_dir)
    results_file = output_dir / "results_summary.json"
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Results saved to: {results_file}")

    return results


# =============================================================================
# MAIN
# =============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-Agent Benchmark Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Interactive mode:
    python -m tools.agents.benchmarks.runner

  Run HumanEval with GPT-4o-mini:
    python -m tools.agents.benchmarks.runner --benchmark humaneval --model gh:gpt-4o-mini --limit 5

  Use a preset:
    python -m tools.agents.benchmarks.runner --preset quick-test

  List available benchmarks:
    python -m tools.agents.benchmarks.runner --list
        """,
    )

    # Mode selection
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Interactive configuration mode",
    )
    parser.add_argument(
        "--list",
        "-l",
        action="store_true",
        help="List available benchmarks",
    )
    parser.add_argument(
        "--presets",
        action="store_true",
        help="List preset configurations",
    )
    parser.add_argument(
        "--info",
        metavar="BENCHMARK",
        help="Show detailed info about a benchmark",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Clear benchmark data cache",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List all available models from discovery",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Run model discovery and update discovery_results.json",
    )

    # Run configuration
    parser.add_argument(
        "--benchmark",
        "-b",
        type=str,
        default="custom-local",
        help="Benchmark ID to run",
    )
    parser.add_argument(
        "--model",
        "-m",
        type=str,
        default="gh:gpt-4o-mini",
        help="Model to use",
    )
    parser.add_argument(
        "--workflow",
        "-w",
        type=str,
        default="multi-agent",
        choices=["multi-agent", "single-agent", "chain-of-thought", "react"],
        help="Agent workflow",
    )
    parser.add_argument(
        "--limit",
        "-n",
        type=int,
        help="Max tasks to run",
    )
    parser.add_argument(
        "--preset",
        "-p",
        type=str,
        help="Use a preset configuration",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Timeout per task (seconds)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        help="Output file for results (JSON)",
    )

    args = parser.parse_args()

    try:
        # Handle info commands (each returns True if it handled the request)
        if _handle_info_command(args):
            return

        # Handle preset
        if args.preset:
            _handle_preset_run(args)
            return

        # Interactive mode (default if no benchmark specified via CLI)
        if args.interactive or (len(sys.argv) == 1):
            _handle_interactive_run()
            return

        # Direct run mode
        cmd_run(args)

    except KeyboardInterrupt:
        print("\n\nCancelled by user.")
        sys.exit(1)


def _handle_info_command(args: argparse.Namespace) -> bool:
    """Dispatch read-only info subcommands; return True if one was handled."""
    if args.list:
        cmd_list_benchmarks(args)
        return True

    if args.presets:
        cmd_list_presets(args)
        return True

    if args.info:
        args.benchmark = args.info
        cmd_info(args)
        return True

    if args.clear_cache:
        cmd_clear_cache(args)
        return True

    if args.list_models:
        cmd_list_models(args)
        return True

    if args.discover:
        cmd_discover_models(args)
        return True

    return False


def _apply_preset_overrides(
    preset: BenchmarkConfig, args: argparse.Namespace
) -> BenchmarkConfig:
    """Apply CLI overrides onto a preset config in place and return it."""
    config = preset
    if args.benchmark != "custom-local":
        config.benchmark_id = args.benchmark
    if args.model != "gh:gpt-4o-mini":
        config.model = args.model
    if args.limit:
        config.limit = args.limit
    config.verbose = args.verbose or config.verbose
    return config


def _handle_preset_run(args: argparse.Namespace) -> None:
    """Resolve a preset, apply overrides, run it, and optionally save results."""
    preset = PRESET_CONFIGS.get(args.preset)
    if not preset:
        print(f"Unknown preset: {args.preset}")
        print(f"Available: {list(PRESET_CONFIGS.keys())}")
        return

    config = _apply_preset_overrides(preset, args)
    results = run_benchmark(config)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)


def _handle_interactive_run() -> None:
    """Run the interactive configuration flow, then optionally save results."""
    config = interactive_mode()
    if not config:
        return

    results = run_benchmark(config)

    # Optionally save
    if prompt_yes_no("\nSave results to file?", False):
        output_path = prompt_input("Output file", "benchmark_results.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"Saved to: {output_path}")


if __name__ == "__main__":
    main()
