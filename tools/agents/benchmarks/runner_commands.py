"""CLI subcommand handler functions for the benchmark runner.

Each ``cmd_*`` function maps to a CLI subcommand dispatched from
:func:`tools.agents.benchmarks.runner.main`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.agents.benchmarks.datasets import BENCHMARK_DEFINITIONS
from tools.agents.benchmarks.registry import (
    PRESET_CONFIGS,
    BenchmarkConfig,
    BenchmarkRegistry,
)
from tools.agents.benchmarks.runner_ui import (
    colorize,
    get_available_models_by_provider,
    print_header,
    print_table,
)


def cmd_list_benchmarks(args: argparse.Namespace) -> None:
    """List available benchmarks."""
    print_header("AVAILABLE BENCHMARKS")

    headers = ["ID", "Name", "Type", "Size", "Source"]
    widths = [20, 25, 20, 10, 15]
    rows = []

    for bid, bdef in BENCHMARK_DEFINITIONS.items():
        rows.append(
            [
                bid,
                bdef.name,
                bdef.benchmark_type.value,
                f"~{bdef.size}",
                bdef.source.value,
            ]
        )

    print_table(headers, rows, widths)

    print(f"\nTotal: {len(BENCHMARK_DEFINITIONS)} benchmarks")
    print("\nUse --benchmark <id> to run a specific benchmark")


def cmd_list_presets(args: argparse.Namespace) -> None:
    """List preset configurations."""
    print_header("PRESET CONFIGURATIONS")

    for name, cfg in PRESET_CONFIGS.items():
        print(f"\n  {colorize(name, 'cyan')}:")
        print(f"    Benchmark: {cfg.benchmark_id}")
        print(f"    Model:     {cfg.model}")
        print(f"    Workflow:  {cfg.workflow}")
        print(f"    Limit:     {cfg.limit or 'all'}")


def cmd_info(args: argparse.Namespace) -> None:
    """Show detailed info about a benchmark."""
    benchmark = BENCHMARK_DEFINITIONS.get(args.benchmark)
    if not benchmark:
        print(f"Unknown benchmark: {args.benchmark}")
        return

    print_header(f"BENCHMARK: {benchmark.name}")
    print(f"\n  ID:          {benchmark.id}")
    print(f"  Type:        {benchmark.benchmark_type.value}")
    print(f"  Size:        ~{benchmark.size} tasks")
    print(f"  Source:      {benchmark.source.value}")
    print(f"  URL:         {benchmark.source_url}")
    print(f"  Languages:   {', '.join(benchmark.languages)}")
    print("\n  Description:")
    print(f"    {benchmark.description}")
    print(f"\n  Metrics:     {', '.join(benchmark.metrics)}")
    print(f"  Evaluation:  {benchmark.evaluation_method}")

    if benchmark.paper_url:
        print(f"\n  Paper:       {benchmark.paper_url}")
    if benchmark.leaderboard_url:
        print(f"  Leaderboard: {benchmark.leaderboard_url}")


def cmd_clear_cache(args: argparse.Namespace) -> None:
    """Clear benchmark cache."""
    from tools.agents.benchmarks.loader import clear_cache

    deleted = clear_cache(args.benchmark if hasattr(args, "benchmark") else None)
    print(f"Cleared {deleted} cached files")


def cmd_list_models(args: argparse.Namespace) -> None:
    """List all available models from discovery."""
    print_header("AVAILABLE MODELS")

    providers = get_available_models_by_provider()

    if not providers:
        print("  No models discovered.")
        print("  Run: python -m tools.agents.benchmarks.runner --discover")
        return

    total = 0
    for provider_name, models in sorted(providers.items()):
        print(f"\n  {colorize(provider_name.upper(), 'cyan')} ({len(models)} models)")
        total += len(models)
        for model in sorted(models)[:10]:
            print(f"    {model}")
        if len(models) > 10:
            print(f"    ... +{len(models) - 10} more")

    print(f"\n  {colorize(f'Total: {total} models available', 'green')}")


def cmd_discover_models(args: argparse.Namespace) -> None:
    """Run model discovery and save results."""
    print_header("MODEL DISCOVERY")
    print("  Discovering available models...\n")

    try:
        from tools.llm.model_probe import discover_all_models

        results = discover_all_models(verbose=True)

        # Save to discovery_results.json
        output_file = Path(__file__).parents[3] / "discovery_results.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        print(f"\n  Results saved to: {output_file}")

        # Show summary
        summary = results.get("summary", {})
        print(f"  Total models: {summary.get('total_available', 0)}")
        print(f"  Providers: {summary.get('providers_configured', 0)}")

    except ImportError as e:
        print(f"  Error: Could not import model_probe: {e}")
    except Exception as e:
        print(f"  Error during discovery: {e}")


def cmd_run(args: argparse.Namespace) -> None:
    """Run benchmark with given configuration."""
    # Import here to avoid circular dependency (runner imports runner_commands)
    from tools.agents.benchmarks.runner import run_benchmark

    # Build config from args
    config = BenchmarkConfig(
        benchmark_id=args.benchmark,
        model=args.model,
        workflow=args.workflow,
        limit=args.limit,
        verbose=args.verbose,
        timeout_seconds=args.timeout,
    )

    # Validate
    errors = BenchmarkRegistry.validate_config(config)
    if errors:
        print("Configuration errors:")
        for err in errors:
            print(f"  - {err}")
        return

    # Run
    results = run_benchmark(config)

    # Save results
    if args.output:
        output_path = Path(args.output)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to: {output_path}")
