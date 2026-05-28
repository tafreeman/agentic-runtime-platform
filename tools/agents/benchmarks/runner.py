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

from tools.agents.benchmarks.datasets import BENCHMARK_DEFINITIONS
from tools.agents.benchmarks.evaluation_pipeline import (
    evaluate_task_output_llm,
)
from tools.agents.benchmarks.loader import clear_cache, load_benchmark
from tools.agents.benchmarks.registry import (
    PRESET_CONFIGS,
    BenchmarkConfig,
    BenchmarkRegistry,
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
    colorize,
    get_available_models_by_provider,
    interactive_mode,
    print_header,
    print_table,
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


def run_benchmark(config: BenchmarkConfig) -> dict[str, Any]:
    """Execute benchmark with given configuration.

    Returns results dictionary.
    """
    print_header("RUNNING BENCHMARK")

    # Create output directory for this run
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = (
        Path(__file__).parents[3]
        / "results"
        / "benchmark_runs"
        / f"{config.benchmark_id}_{timestamp}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"  Output directory: {output_dir}")

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
    results = {
        "config": config.to_dict(),
        "started_at": datetime.now().isoformat(),
        "tasks": [],
        "summary": {},
    }

    if config.workflow == "multi-agent":
        from tools.agents.multi_agent_orchestrator import MultiAgentOrchestrator

        orchestrator = MultiAgentOrchestrator(
            model=config.model,
            verbose=config.verbose,
        )
    else:
        # Placeholder for other workflows
        orchestrator = None
        print(f"⚠ Workflow '{config.workflow}' not yet implemented")
        print("  Using direct execution mode")

    # Run each task
    successful = 0
    failed = 0

    for i, task in enumerate(tasks, 1):
        print(f"\n{'─' * 60}")
        print(f"Task {i}/{len(tasks)}: {task.task_id}")
        print(f"{'─' * 60}")

        if config.verbose:
            prompt_preview = (
                task.prompt[:200] + "..." if len(task.prompt) > 200 else task.prompt
            )
            print(f"\nPrompt: {prompt_preview}\n")

        try:
            start_time = datetime.now()
            workflow_data = None  # Track multi-agent workflow details

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
            else:
                # Direct LLM call (placeholder)
                from tools.llm.llm_client import LLMClient

                output = LLMClient.generate_text(config.model, task.prompt)
                task_success = bool(output)

            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            task_result = {
                "task_id": task.task_id,
                "success": task_success,
                "duration_seconds": duration,
                "output_length": len(output) if output else 0,
            }

            # Save workflow phases data (all agent outputs)
            if workflow_data:
                task_result["workflow"] = workflow_data
                # Save detailed workflow file
                workflow_file = output_dir / f"task_{task.task_id}_workflow.json"
                with open(workflow_file, "w", encoding="utf-8") as f:
                    json.dump(workflow_data, f, indent=2, default=str)
                print(f"  Workflow saved: {workflow_file.name}")

                # Save each phase output as markdown for readability
                save_workflow_phases_md(workflow_data, task.task_id, output_dir)

            # Save generated output to file
            if output:
                output_file = output_dir / f"task_{task.task_id}_output.md"
                output_file.write_text(output, encoding="utf-8")
                task_result["output_file"] = str(output_file)
                print(f"  Output saved: {output_file.name}")

            # LLM-based evaluation (new default)
            if output:
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

            if config.save_intermediate:
                task_result["output"] = output

            results["tasks"].append(task_result)

            if task_success:
                successful += 1
                print(f"✓ Completed in {duration:.1f}s")
            else:
                failed += 1
                print(f"✗ Failed in {duration:.1f}s")

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

    # Summary
    results["completed_at"] = datetime.now().isoformat()
    results["summary"] = {
        "total_tasks": len(tasks),
        "successful": successful,
        "failed": failed,
        "success_rate": successful / len(tasks) if tasks else 0,
    }

    # Calculate average score if evaluations exist
    scores = [t.get("score", 0) for t in results["tasks"] if "score" in t]
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
        # Handle info commands
        if args.list:
            cmd_list_benchmarks(args)
            return

        if args.presets:
            cmd_list_presets(args)
            return

        if args.info:
            args.benchmark = args.info
            cmd_info(args)
            return

        if args.clear_cache:
            cmd_clear_cache(args)
            return

        if args.list_models:
            cmd_list_models(args)
            return

        if args.discover:
            cmd_discover_models(args)
            return

        # Handle preset
        if args.preset:
            preset = PRESET_CONFIGS.get(args.preset)
            if not preset:
                print(f"Unknown preset: {args.preset}")
                print(f"Available: {list(PRESET_CONFIGS.keys())}")
                return

            # Apply preset but allow overrides
            config = preset
            if args.benchmark != "custom-local":
                config.benchmark_id = args.benchmark
            if args.model != "gh:gpt-4o-mini":
                config.model = args.model
            if args.limit:
                config.limit = args.limit
            config.verbose = args.verbose or config.verbose

            results = run_benchmark(config)

            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    json.dump(results, f, indent=2)
            return

        # Interactive mode (default if no benchmark specified via CLI)
        if args.interactive or (len(sys.argv) == 1):
            config = interactive_mode()
            if config:
                results = run_benchmark(config)

                # Optionally save
                if prompt_yes_no("\nSave results to file?", False):
                    output_path = prompt_input("Output file", "benchmark_results.json")
                    with open(output_path, "w", encoding="utf-8") as f:
                        json.dump(results, f, indent=2)
                    print(f"Saved to: {output_path}")
            return

        # Direct run mode
        cmd_run(args)

    except KeyboardInterrupt:
        print("\n\nCancelled by user.")
        sys.exit(1)


if __name__ == "__main__":
    main()
