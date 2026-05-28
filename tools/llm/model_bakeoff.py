#!/usr/bin/env python3
"""Model bakeoff + alignment helper for local and hosted model endpoints.

Purpose
-------
Run a lightweight, repeatable capability comparison across discovered models and
recommend model alignment values for deep research workflows:

- ``DEEP_RESEARCH_SMALL_MODEL``
- ``DEEP_RESEARCH_HEAVY_MODEL``

Designed to run from Windows PowerShell outside WSL as requested.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.llm.bakeoff_reporting import _recommend_alignment, _write_reports
from tools.llm.bakeoff_tasks import (
    TASKS,
    TaskSpec,
    _dedupe_keep_order,
    _discover_openai_compatible_models,
    _ensure_import_path,
    _is_local_openai_base,
    _load_dotenv,
    _parse_json_from_text,
    _provider_of,
    _repo_root,
)

logger = logging.getLogger(__name__)


def _score_task(
    task: TaskSpec, response_text: str, elapsed_s: float, error: str | None
) -> dict[str, Any]:
    checks: dict[str, Any] = {
        "has_content": bool(response_text.strip()),
        "json_ok": False,
        "required_key_ratio": 0.0,
        "required_term_ratio": 0.0,
        "error": error,
    }

    if error:
        return {"score": 0.0, "checks": checks}

    score = 0.0
    text_lower = response_text.lower()

    if checks["has_content"]:
        score += 20.0

    parsed_json = None
    if task.expect_json:
        parsed_json = _parse_json_from_text(response_text)
        checks["json_ok"] = parsed_json is not None
        if checks["json_ok"]:
            score += 30.0
        if task.required_keys:
            present = sum(
                1
                for key in task.required_keys
                if isinstance(parsed_json, dict) and key in parsed_json
            )
            ratio = present / len(task.required_keys)
            checks["required_key_ratio"] = ratio
            score += ratio * 30.0

    if task.required_terms:
        present_terms = sum(
            1 for term in task.required_terms if term.lower() in text_lower
        )
        term_ratio = present_terms / len(task.required_terms)
        checks["required_term_ratio"] = term_ratio
        score += term_ratio * 20.0

    # Latency penalty to reward usable responsiveness for interactive workflows.
    score -= min(elapsed_s, 120.0) * 0.15
    score = max(0.0, min(score, 100.0))

    return {"score": round(score, 2), "checks": checks}


def _discover_candidates(
    providers: list[str],
    max_per_provider: int,
    explicit_models: list[str],
    include_openai_local: bool,
    force_probe: bool,
    verbose: bool,
) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
    from tools.llm.model_probe import ModelProbe, discover_all_models

    discovered = discover_all_models(verbose=verbose)
    candidates: list[str] = []

    if explicit_models:
        candidates.extend(explicit_models)
    else:
        for provider in providers:
            available = (
                discovered.get("providers", {}).get(provider, {}).get("available", [])
            )
            if isinstance(available, list):
                candidates.extend([str(m) for m in available[:max_per_provider]])

        if include_openai_local:
            base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE")
            if _is_local_openai_base(base_url):
                candidates.extend(_discover_openai_compatible_models(base_url))

    candidates = _dedupe_keep_order([m for m in candidates if m.strip()])

    probe = ModelProbe(verbose=verbose)
    runnable = probe.filter_runnable(candidates, force_probe=force_probe)
    report = probe.get_probe_report(candidates)
    return runnable, discovered, report


def _run_bakeoff(
    models: list[str],
    tasks: list[TaskSpec],
    temperature: float,
    max_tokens: int,
) -> list[dict[str, Any]]:
    from tools.llm.llm_client import LLMClient

    model_results: list[dict[str, Any]] = []
    system_prompt = (
        "You are a pragmatic senior AI/software architect. Provide concise, "
        "technically precise outputs."
    )

    for model in models:
        task_results: list[dict[str, Any]] = []
        for task in tasks:
            started = time.perf_counter()
            error = None
            response = ""
            try:
                response = LLMClient.generate_text(
                    model_name=model,
                    prompt=task.prompt,
                    system_instruction=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                error = str(exc)
            elapsed = time.perf_counter() - started
            scored = _score_task(task, response, elapsed, error)
            task_results.append(
                {
                    "task_id": task.task_id,
                    "title": task.title,
                    "elapsed_s": round(elapsed, 3),
                    "score": scored["score"],
                    "checks": scored["checks"],
                    "error": error,
                    "response_preview": response[:1200],
                }
            )

        successful = [t for t in task_results if not t["error"]]
        avg_latency = (
            statistics.mean(t["elapsed_s"] for t in task_results)
            if task_results
            else 0.0
        )
        weighted_score = 0.0
        total_weight = 0.0
        for task, result in zip(tasks, task_results, strict=False):
            weighted_score += float(result["score"]) * task.weight
            total_weight += task.weight
        task_score = (weighted_score / total_weight) if total_weight else 0.0
        success_rate = (len(successful) / len(task_results)) if task_results else 0.0
        overall_score = max(
            0.0, min(task_score + (success_rate * 10.0) - (avg_latency * 0.2), 100.0)
        )

        model_results.append(
            {
                "model": model,
                "provider": _provider_of(model),
                "overall_score": round(overall_score, 2),
                "task_score": round(task_score, 2),
                "success_rate": round(success_rate, 3),
                "avg_latency_s": round(avg_latency, 3),
                "tasks": task_results,
            }
        )

    model_results.sort(
        key=lambda r: (
            r["overall_score"],
            r["task_score"],
            r["success_rate"],
            -r["avg_latency_s"],
        ),
        reverse=True,
    )
    return model_results


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Run a lightweight model bakeoff and suggest alignment values."
    )
    parser.add_argument(
        "--providers",
        default="local_onnx,ollama,ai_toolkit,openai",
        help=(
            "Comma-separated providers from model_probe discovery "
            "(default: local_onnx,ollama,ai_toolkit,openai)"
        ),
    )
    parser.add_argument(
        "--models",
        nargs="*",
        default=[],
        help="Explicit model IDs (skips discovery selection).",
    )
    parser.add_argument(
        "--max-models-per-provider",
        type=int,
        default=6,
        help="Limit models selected per provider during discovery (default: 6).",
    )
    parser.add_argument(
        "--max-models",
        type=int,
        default=24,
        help="Global cap on runnable models tested (default: 24).",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.1,
        help="Generation temperature for bakeoff prompts (default: 0.1).",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=900,
        help="Max tokens per prompt call (default: 900).",
    )
    parser.add_argument(
        "--out-dir",
        default="reports/model-bakeoff",
        help="Output directory for JSON/Markdown reports.",
    )
    parser.add_argument(
        "--write-env",
        default="",
        help="Optional env file path to write recommended model alignment values.",
    )
    parser.add_argument(
        "--force-probe",
        action="store_true",
        help="Force fresh model probe checks (ignore cache).",
    )
    parser.add_argument(
        "--include-openai-local",
        action="store_true",
        help="Include models from OPENAI_BASE_URL /v1/models when local endpoint is set.",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="Set PROMPTEVAL_ALLOW_REMOTE=1 for openai/gemini/claude providers.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Probe/select models and print alignment without running prompts.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose discovery/probe logs.",
    )
    args = parser.parse_args(argv)

    _ensure_import_path()
    _load_dotenv(_repo_root() / ".env")

    if args.allow_remote:
        os.environ.setdefault("PROMPTEVAL_ALLOW_REMOTE", "1")

    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    explicit_models = _dedupe_keep_order([m.strip() for m in args.models if m.strip()])

    runnable, discovered, probe_report = _discover_candidates(
        providers=providers,
        max_per_provider=max(1, args.max_models_per_provider),
        explicit_models=explicit_models,
        include_openai_local=bool(args.include_openai_local),
        force_probe=bool(args.force_probe),
        verbose=bool(args.verbose),
    )

    runnable = runnable[: max(1, args.max_models)]
    if not runnable:
        logger.warning("No runnable models found for the selected discovery settings.")
        return 1

    if args.dry_run:
        preview_alignment = {
            "small": runnable[0] if runnable else None,
            "heavy": runnable[0] if runnable else None,
        }
        logger.info("Runnable models:")
        for model in runnable:
            logger.info(f"- {model}")
        logger.info("\nPreview alignment:")
        logger.info(json.dumps(preview_alignment, indent=2))
        return 0

    results = _run_bakeoff(
        models=runnable,
        tasks=TASKS,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )
    alignment = _recommend_alignment(results)

    now_utc = datetime.now(timezone.utc).isoformat()
    payload = {
        "timestamp_utc": now_utc,
        "config": {
            "providers": providers,
            "explicit_models": explicit_models,
            "max_models_per_provider": args.max_models_per_provider,
            "max_models": args.max_models,
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
            "allow_remote": args.allow_remote,
            "include_openai_local": args.include_openai_local,
        },
        "summary": {
            "tested_models": len(results),
            "runnable_models": len(runnable),
        },
        "alignment": alignment,
        "probe_report": probe_report,
        "discovery_snapshot": discovered,
        "results": results,
    }

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = _repo_root() / out_dir

    write_env_path = Path(args.write_env) if args.write_env else None
    if write_env_path and not write_env_path.is_absolute():
        write_env_path = _repo_root() / write_env_path

    json_path, md_path = _write_reports(
        out_dir=out_dir,
        payload=payload,
        alignment=alignment,
        write_env=write_env_path,
    )

    logger.info("\nModel bakeoff complete.")
    logger.info(f"- JSON report: {json_path}")
    logger.info(f"- Markdown report: {md_path}")
    logger.info("- Recommended alignment:")
    logger.info(f"  DEEP_RESEARCH_SMALL_MODEL={alignment.get('small') or ''}")
    logger.info(f"  DEEP_RESEARCH_HEAVY_MODEL={alignment.get('heavy') or ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
