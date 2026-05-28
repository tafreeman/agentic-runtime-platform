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

logger = logging.getLogger(__name__)


def main() -> None:
    """CLI entry point for the local ONNX model runner."""
    from tools.llm.local_model import LocalModel
    from tools.llm.local_model_discovery import get_model_info

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

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    # Check mode
    if args.check:
        info = get_model_info()
        logger.info(json.dumps(info, indent=2))
        sys.exit(0 if info["available"] else 1)

    # Evaluate mode
    if args.evaluate:
        prompt_path = Path(args.evaluate)
        if not prompt_path.exists():
            logger.error(f"File not found: {prompt_path}")
            sys.exit(1)

        try:
            model = LocalModel(model_path=args.model_path, verbose=args.verbose)
            content = prompt_path.read_text(encoding="utf-8")
            result = model.evaluate_prompt(content)
            logger.info(json.dumps(result, indent=2))
        except Exception as e:
            logger.error(f"Error: {e}")
            sys.exit(1)

        sys.exit(0)

    # Batch evaluate mode: accepts a JSON file listing prompt file paths
    if args.batch_evaluate:
        batch_file = Path(args.batch_evaluate)
        if not batch_file.exists():
            logger.error(f"Batch file not found: {batch_file}")
            sys.exit(1)

        try:
            paths = json.loads(batch_file.read_text(encoding="utf-8"))
            if not isinstance(paths, list):
                logger.error("batch file must contain a JSON array of file paths")
                sys.exit(1)

            model = LocalModel(model_path=args.model_path, verbose=args.verbose)
            results = []
            for p in paths:
                try:
                    prompt_path = Path(p)
                    if not prompt_path.exists():
                        results.append({"file": str(p), "error": "file not found"})
                        continue
                    content = prompt_path.read_text(encoding="utf-8")
                    res = model.evaluate_prompt(content)
                    out = {
                        "file": str(prompt_path),
                        "result": res,
                    }
                    results.append(out)
                except Exception as e:
                    results.append({"file": str(p), "error": str(e)})

            logger.info(json.dumps({"results": results}, indent=2))
            sys.exit(0)
        except Exception as e:
            logger.error(f"Error during batch evaluation: {e}")
            sys.exit(1)

    # Interactive mode
    if not args.prompt:
        parser.print_help()
        sys.exit(1)

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
        sys.exit(1)


if __name__ == "__main__":
    main()
