"""CLI entry point for running prompts through a local ONNX model.

Usage:
    python -m tools.llm.local_model_cli "Evaluate this prompt for clarity"
    python tools/llm/local_model_cli.py --check
    python tools/llm/local_model_cli.py --evaluate path/to/prompt.md
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _build_arg_parser() -> argparse.ArgumentParser:
    """Construct the argument parser for the local model CLI."""
    parser = argparse.ArgumentParser(description="Run prompts through local ONNX model")
    parser.add_argument("prompt", nargs="?", help="Prompt to send to the model")
    parser.add_argument("--model-path", "-m", help="Path to ONNX model directory")
    parser.add_argument(
        "--max-tokens", "-t", type=int, default=1024, help="Maximum tokens to generate"
    )
    parser.add_argument(
        "--temperature", type=float, default=0.7, help="Sampling temperature"
    )
    parser.add_argument(
        "--check", action="store_true", help="Check if local model is available"
    )
    parser.add_argument(
        "--evaluate", "-e", type=str, help="Path to prompt file to evaluate"
    )
    parser.add_argument(
        "--batch-evaluate",
        type=str,
        help="Path to a JSON file containing a list of prompt file paths to evaluate in batch (loads model once)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    return parser


def _run_check_mode() -> int:
    """Report local model availability; return process exit code."""
    from tools.llm.local_model_discovery import get_model_info

    info = get_model_info()
    logger.info(json.dumps(info, indent=2))
    return 0 if info["available"] else 1


def _run_evaluate_mode(args: argparse.Namespace) -> int:
    """Evaluate a single prompt file; return process exit code."""
    from tools.llm.local_model import LocalModel

    prompt_path = Path(args.evaluate)
    if not prompt_path.exists():
        logger.error(f"File not found: {prompt_path}")
        return 1

    try:
        model = LocalModel(model_path=args.model_path, verbose=args.verbose)
        content = prompt_path.read_text(encoding="utf-8")
        result = model.evaluate_prompt(content)
        logger.info(json.dumps(result, indent=2))
    except Exception as e:
        logger.error(f"Error: {e}")
        return 1

    return 0


def _evaluate_batch_paths(model: Any, paths: list) -> list[dict]:
    """Evaluate each prompt file path, collecting per-file results or errors."""
    results = []
    for p in paths:
        try:
            prompt_path = Path(p)
            if not prompt_path.exists():
                results.append({"file": str(p), "error": "file not found"})
                continue
            content = prompt_path.read_text(encoding="utf-8")
            res = model.evaluate_prompt(content)
            results.append({"file": str(prompt_path), "result": res})
        except Exception as e:
            results.append({"file": str(p), "error": str(e)})
    return results


def _run_batch_evaluate_mode(args: argparse.Namespace) -> int:
    """Evaluate a JSON list of prompt file paths; return process exit code."""
    from tools.llm.local_model import LocalModel

    batch_file = Path(args.batch_evaluate)
    if not batch_file.exists():
        logger.error(f"Batch file not found: {batch_file}")
        return 1

    try:
        paths = json.loads(batch_file.read_text(encoding="utf-8"))
        if not isinstance(paths, list):
            logger.error("batch file must contain a JSON array of file paths")
            return 1

        model = LocalModel(model_path=args.model_path, verbose=args.verbose)
        results = _evaluate_batch_paths(model, paths)
        logger.info(json.dumps({"results": results}, indent=2))
        return 0
    except Exception as e:
        logger.error(f"Error during batch evaluation: {e}")
        return 1


def _run_interactive_mode(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Generate a response for a single prompt; return process exit code."""
    from tools.llm.local_model import LocalModel

    if not args.prompt:
        parser.print_help()
        return 1

    try:
        model = LocalModel(args.model_path, verbose=args.verbose)
        response = model.generate(
            args.prompt,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
        )
        logger.info(response)
    except Exception as e:
        logger.error(f"Error: {e}")
        return 1
    return 0


def main() -> None:
    """CLI entry point for the local ONNX model runner."""
    parser = _build_arg_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    if args.check:
        sys.exit(_run_check_mode())
    if args.evaluate:
        sys.exit(_run_evaluate_mode(args))
    if args.batch_evaluate:
        sys.exit(_run_batch_evaluate_mode(args))
    sys.exit(_run_interactive_mode(args, parser))


if __name__ == "__main__":
    main()
