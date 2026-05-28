#!/usr/bin/env python3
"""Run local CPU+GPU inference concurrently and compare vs sequential execution."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)


def _repo_root() -> Path:
    # prompts/tools/llm/run_local_concurrency.py -> prompts/
    return Path(__file__).resolve().parents[2]


def _ensure_import_path() -> None:
    root = _repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(key, value)


_LOCAL_RUNNERS: dict[str, Any] = {}
_LOCAL_RUNNERS_LOCK = Lock()


def _get_local_runner(model: str) -> Any:
    """Get or create a cached LocalModel instance for a local:* model."""
    from tools.llm.llm_client import LLMClient
    from tools.llm.local_model import LocalModel

    with _LOCAL_RUNNERS_LOCK:
        cached = _LOCAL_RUNNERS.get(model)
        if cached is not None:
            return cached

        model_key = model.split(":", 1)[1] if ":" in model else model
        model_path_obj = LLMClient._resolve_local_model_path(model_key)
        model_path = str(model_path_obj) if model_path_obj else None
        runner = {
            "lock": Lock(),
            "model": LocalModel(
                model_path=model_path, model_key=model_key, verbose=False
            ),
        }
        _LOCAL_RUNNERS[model] = runner
        return runner


def _run_one(
    model: str, prompt: str, temperature: float, max_tokens: int
) -> dict[str, Any]:
    from tools.llm.llm_client import LLMClient

    started = time.perf_counter()
    text = ""
    error = None
    try:
        system_instruction = (
            "You are a concise engineering assistant. Answer directly in 4-8 bullets."
        )
        if model.lower().startswith("local:"):
            runner = _get_local_runner(model)
            local_prompt = f"System: {system_instruction}\n\nUser: {prompt}"
            with runner["lock"]:
                text = runner["model"].generate(
                    local_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
        else:
            text = LLMClient.generate_text(
                model_name=model,
                prompt=prompt,
                system_instruction=system_instruction,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        if isinstance(text, str) and text.lower().startswith("local model error:"):
            error = text
    except Exception as exc:
        error = str(exc)
    elapsed = time.perf_counter() - started
    return {
        "model": model,
        "ok": error is None,
        "elapsed_s": round(elapsed, 3),
        "error": error,
        "preview": text[:400],
    }


def _run_sequential(
    cpu_model: str,
    gpu_model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    wall_start = time.perf_counter()
    cpu = _run_one(cpu_model, prompt, temperature, max_tokens)
    gpu = _run_one(gpu_model, prompt, temperature, max_tokens)
    wall = time.perf_counter() - wall_start
    return {
        "mode": "sequential",
        "wall_s": round(wall, 3),
        "cpu": cpu,
        "gpu": gpu,
    }


def _run_parallel(
    cpu_model: str,
    gpu_model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    wall_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2) as pool:
        cpu_fut = pool.submit(_run_one, cpu_model, prompt, temperature, max_tokens)
        gpu_fut = pool.submit(_run_one, gpu_model, prompt, temperature, max_tokens)
        cpu = cpu_fut.result()
        gpu = gpu_fut.result()
    wall = time.perf_counter() - wall_start
    return {
        "mode": "parallel",
        "wall_s": round(wall, 3),
        "cpu": cpu,
        "gpu": gpu,
    }


def _write_report(payload: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    out_path = out_dir / f"local_concurrency_{stamp}.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(
        description="Compare local CPU+GPU model runs in sequential vs parallel mode."
    )
    parser.add_argument("--cpu-model", default="local:phi4-cpu")
    parser.add_argument("--gpu-model", default="local:phi4-gpu")
    parser.add_argument(
        "--prompt",
        default=(
            "Research agentic AI workflow architecture for enterprise software teams. "
            "Cover when to use ToT, ReAct, and CoVe, and include verification gates."
        ),
    )
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--max-tokens", type=int, default=300)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument(
        "--out-dir",
        default="reports/model-bakeoff",
        help="Directory for JSON output report",
    )
    parser.add_argument(
        "--skip-sequential",
        action="store_true",
        help="Only run parallel mode.",
    )
    parser.add_argument(
        "--parallel-only",
        action="store_true",
        help="Alias for --skip-sequential.",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Fast sanity run: parallel only, one round, lower token budget.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print selected config and exit.",
    )
    args = parser.parse_args(argv)
    if args.parallel_only:
        args.skip_sequential = True
    if args.fast:
        args.skip_sequential = True
        args.rounds = 1
        if args.max_tokens == 300:
            args.max_tokens = 120

    _ensure_import_path()
    _load_dotenv(_repo_root() / ".env")

    if args.dry_run:
        logger.info("Dry run configuration:")
        logger.info(json.dumps(vars(args), indent=2))
        return 0

    rounds = max(1, args.rounds)
    records: list[dict[str, Any]] = []

    for i in range(rounds):
        round_rec: dict[str, Any] = {"round": i + 1}
        if not args.skip_sequential:
            round_rec["sequential"] = _run_sequential(
                args.cpu_model,
                args.gpu_model,
                args.prompt,
                args.temperature,
                args.max_tokens,
            )
        round_rec["parallel"] = _run_parallel(
            args.cpu_model,
            args.gpu_model,
            args.prompt,
            args.temperature,
            args.max_tokens,
        )
        records.append(round_rec)

    seq_times = [
        r["sequential"]["wall_s"]
        for r in records
        if isinstance(r.get("sequential"), dict)
    ]
    par_times = [
        r["parallel"]["wall_s"] for r in records if isinstance(r.get("parallel"), dict)
    ]
    call_records: list[dict[str, Any]] = []
    for rec in records:
        for mode in ("sequential", "parallel"):
            mode_data = rec.get(mode)
            if not isinstance(mode_data, dict):
                continue
            cpu = mode_data.get("cpu")
            gpu = mode_data.get("gpu")
            if isinstance(cpu, dict):
                call_records.append(cpu)
            if isinstance(gpu, dict):
                call_records.append(gpu)
    success_count = sum(1 for call in call_records if bool(call.get("ok")))
    failed_count = len(call_records) - success_count

    summary: dict[str, Any] = {
        "cpu_model": args.cpu_model,
        "gpu_model": args.gpu_model,
        "rounds": rounds,
        "avg_parallel_wall_s": (
            round(sum(par_times) / len(par_times), 3) if par_times else None
        ),
        "total_calls": len(call_records),
        "successful_calls": success_count,
        "failed_calls": failed_count,
        "success_rate": (
            round(success_count / len(call_records), 3) if call_records else None
        ),
    }
    if seq_times:
        avg_seq = sum(seq_times) / len(seq_times)
        avg_par = sum(par_times) / len(par_times)
        speedup = (avg_seq / avg_par) if avg_par > 0 else None
        summary["avg_sequential_wall_s"] = round(avg_seq, 3)
        summary["parallel_speedup_vs_sequential"] = (
            round(speedup, 3) if speedup else None
        )

    payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "records": records,
    }

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = _repo_root() / out_dir
    out_path = _write_report(payload, out_dir)

    logger.info("Local concurrency test complete")
    logger.info(f"CPU model: {args.cpu_model}")
    logger.info(f"GPU model: {args.gpu_model}")
    if summary.get("avg_sequential_wall_s") is not None:
        logger.info(f"Avg sequential wall time: {summary['avg_sequential_wall_s']}s")
    logger.info(f"Avg parallel wall time: {summary['avg_parallel_wall_s']}s")
    if summary.get("parallel_speedup_vs_sequential") is not None:
        logger.info(f"Parallel speedup: {summary['parallel_speedup_vs_sequential']}x")
    logger.info(
        f"Calls: {summary['successful_calls']}/{summary['total_calls']} successful "
        f"(failed={summary['failed_calls']})"
    )
    if summary["failed_calls"] > 0:
        logger.warning(
            "One or more model calls failed; latency comparison may be invalid."
        )
    logger.info(f"Report: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
