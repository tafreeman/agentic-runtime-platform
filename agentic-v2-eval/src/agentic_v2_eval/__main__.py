"""CLI entry point for agentic-v2-eval.

Supports running evaluations from the command line.

Usage:
    python -m agentic_v2_eval --help
    python -m agentic_v2_eval evaluate results.json [--rubric rubrics/default.yaml]
    python -m agentic_v2_eval report results.json --format html --output report.html
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .rubrics import load_rubric
from .scorer import Scorer


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="agentic-v2-eval",
        description="Evaluation framework for Agentic Workflows v2.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Evaluate command
    eval_parser = subparsers.add_parser(
        "evaluate",
        help="Evaluate results using a rubric",
    )
    eval_parser.add_argument(
        "results",
        type=Path,
        help="Path to results JSON file",
    )
    eval_parser.add_argument(
        "--rubric",
        type=Path,
        required=False,
        help="Path to rubric YAML file (defaults to packaged 'default' rubric)",
    )
    eval_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Output file for scored results (optional)",
    )

    # Report command
    report_parser = subparsers.add_parser(
        "report",
        help="Generate a report from results",
    )
    report_parser.add_argument(
        "results",
        type=Path,
        help="Path to results JSON file",
    )
    report_parser.add_argument(
        "--format",
        "-f",
        choices=["json", "markdown", "html"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    report_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        required=True,
        help="Output file path",
    )

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "evaluate":
        return cmd_evaluate(args)
    elif args.command == "report":
        return cmd_report(args)

    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    """Execute evaluate command."""
    try:
        # Load results
        with args.results.open("r", encoding="utf-8") as f:
            data = json.load(f)

        # Get results dict
        if isinstance(data, dict) and "results" in data:
            results_list = data["results"]
        elif isinstance(data, list):
            results_list = data
        else:
            results_list = [data]

        # Load scorer
        rubric_source = str(args.rubric) if args.rubric else "<builtin:default>"
        scorer = Scorer(args.rubric if args.rubric else load_rubric("default"))

        # Score each result
        scored_results: list[dict[str, Any]] = []

        for idx, result in enumerate(results_list):
            if isinstance(result, dict):
                score_result = scorer.score(result)
                scored_results.append(
                    {
                        "index": idx,
                        "weighted_score": score_result.weighted_score,
                        "total_score": score_result.total_score,
                        "criterion_scores": score_result.criterion_scores,
                        "missing_criteria": score_result.missing_criteria,
                    }
                )
                print(f"Result {idx}: {score_result.weighted_score:.4f}")

        # Summary
        if scored_results:
            avg_score = sum(r["weighted_score"] for r in scored_results) / len(
                scored_results
            )
            print(f"\nAverage Score: {avg_score:.4f}")

        # Output if requested
        if args.output:
            output_data = {
                "rubric": rubric_source,
                "results": scored_results,
            }
            with args.output.open("w", encoding="utf-8") as f:
                json.dump(output_data, f, indent=2)
            print(f"\nScored results written to: {args.output}")

        return 0

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_report(args: argparse.Namespace) -> int:
    """Execute report command."""
    try:
        # Load results
        with args.results.open("r", encoding="utf-8") as f:
            data = json.load(f)

        # Get results list
        if isinstance(data, dict) and "results" in data:
            results = data["results"]
        elif isinstance(data, list):
            results = data
        else:
            results = [data]

        # Generate report
        if args.format == "json":
            from .reporters import generate_json_report

            generate_json_report(results, args.output)
        elif args.format == "markdown":
            from .reporters import generate_markdown_report

            generate_markdown_report(results, args.output)
        elif args.format == "html":
            from .reporters import generate_html_report

            generate_html_report(results, args.output)

        print(f"Report generated: {args.output}")
        return 0

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
