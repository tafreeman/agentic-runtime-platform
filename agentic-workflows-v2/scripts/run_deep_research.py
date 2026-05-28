#!/usr/bin/env python3
"""Run the LangChain deep_research workflow and persist run artifacts."""

# PowerShell users: Do NOT use backslash (\) for line continuation.
# Use backtick (`) or run the command as a single line.
# Example (single line):
#   python .\agentic-workflows-v2\scripts\run_deep_research.py --small-model "gemini:gemini-2.0-flash-lite" --heavy-model "gemini:gemini-2.5-flash"
# Example (PowerShell multiline):
#   python .\agentic-workflows-v2\scripts\run_deep_research.py `
#     --small-model "gemini:gemini-2.0-flash-lite" `
#     --heavy-model "gemini:gemini-2.5-flash"

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    # agentic-workflows-v2/scripts/run_deep_research.py -> prompts/
    return Path(__file__).resolve().parents[2]


def _project_root() -> Path:
    # agentic-workflows-v2/scripts/run_deep_research.py -> agentic-workflows-v2/
    return Path(__file__).resolve().parents[1]


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


def _ensure_import_path() -> None:
    repo_root = _repo_root()
    project_root = _project_root()
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


def _to_markdown(payload: dict[str, Any]) -> str:
    cfg = payload["input"]
    topic = payload.get("topic")
    outputs = payload.get("outputs", {})
    confidence = outputs.get("confidence_report") or {}

    lines: list[str] = []
    lines.append("# Deep Research Report")
    lines.append("")
    lines.append(f"- Run ID: `{payload['run_id']}`")
    lines.append(f"- Workflow Status: `{payload['status']}`")
    lines.append(f"- Elapsed: `{payload['elapsed_seconds']:.2f}s`")
    lines.append(f"- Timestamp (UTC): `{payload['timestamp_utc']}`")
    lines.append("")
    lines.append("## Input")
    lines.append("")
    if topic:
        lines.append(f"- Topic: {topic}")
    lines.append(f"- Goal: {cfg['goal']}")
    lines.append(f"- Domain: `{cfg['domain']}`")
    lines.append(f"- Minimum CI: `{cfg['min_ci']}`")
    lines.append(f"- Maximum Rounds: `{cfg['max_rounds']}`")
    lines.append(
        f"- Recency Gate: `{cfg['min_recent_sources']}` sources in last `{cfg['recency_window_days']}` days"
    )
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(
        str(outputs.get("executive_summary", "_No executive summary generated._"))
    )
    lines.append("")
    lines.append("## Detailed Analysis")
    lines.append("")
    lines.append(
        str(outputs.get("detailed_analysis", "_No detailed analysis generated._"))
    )
    lines.append("")
    lines.append("## Best Practices")
    lines.append("")
    lines.append(str(outputs.get("best_practices", "_No best practices generated._")))
    lines.append("")
    lines.append("## Confidence Report")
    lines.append("")
    if isinstance(confidence, dict) and confidence:
        for key, value in confidence.items():
            lines.append(f"- {key}: `{value}`")
    else:
        lines.append("_No confidence report generated._")
    lines.append("")
    lines.append("## Limitations")
    lines.append("")
    lines.append(str(outputs.get("limitations", "_No limitations generated._")))
    lines.append("")
    lines.append("## Next Search Actions")
    lines.append("")
    lines.append(
        str(outputs.get("next_search_actions", "_No next actions generated._"))
    )
    lines.append("")
    lines.append("## References")
    lines.append("")
    refs = outputs.get("references")
    if isinstance(refs, list):
        if refs:
            for item in refs:
                lines.append(f"- {item}")
        else:
            lines.append("_No references returned._")
    else:
        lines.append(str(refs or "_No references returned._"))
    lines.append("")
    lines.append("## RAG Artifacts")
    lines.append("")
    lines.append(f"- rag_manifest: `{type(outputs.get('rag_manifest')).__name__}`")
    lines.append(f"- rag_chunks: `{type(outputs.get('rag_chunks')).__name__}`")
    lines.append(f"- claim_graph: `{type(outputs.get('claim_graph')).__name__}`")
    lines.append("")
    return "\n".join(lines)


def _build_goal_from_topic(topic: str) -> str:
    topic = topic.strip()
    return (
        f"Deep research into {topic}. "
        "Produce an implementation-oriented report covering workflow patterns "
        "(ToT, ReAct, CoVe, planner-executor, reviewer loops), when to use each, "
        "system architecture trade-offs, reliability guardrails, evaluation strategy, "
        "and practical rollout recommendations for enterprise teams."
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Run deep_research workflow for a configurable research topic."
    )
    parser.add_argument(
        "--topic",
        default=("agentic AI for software engineers and architects"),
        help="Research topic. Used to build the default goal prompt.",
    )
    parser.add_argument(
        "--goal",
        default="",
        help=(
            "Optional full goal override. If omitted, goal is generated from --topic."
        ),
    )
    parser.add_argument("--domain", default="ai_software")
    parser.add_argument("--min-ci", type=float, default=0.80)
    parser.add_argument("--max-rounds", type=int, default=4)
    parser.add_argument("--min-recent-sources", type=int, default=10)
    parser.add_argument("--recency-window-days", type=int, default=183)
    parser.add_argument(
        "--seed-url",
        action="append",
        default=[],
        help="Optional seed URL (can be passed multiple times).",
    )
    parser.add_argument(
        "--out-dir",
        default="reports/deep-research",
        help="Directory where run artifacts are written.",
    )
    parser.add_argument(
        "--run-id",
        default="",
        help="Optional run id (defaults to generated UUID).",
    )
    parser.add_argument(
        "--small-model",
        default="",
        help="Optional DEEP_RESEARCH_SMALL_MODEL override for this run.",
    )
    parser.add_argument(
        "--heavy-model",
        default="",
        help="Optional DEEP_RESEARCH_HEAVY_MODEL override for this run.",
    )
    args = parser.parse_args(argv)

    _ensure_import_path()
    _load_dotenv(_repo_root() / ".env")
    _load_dotenv(_project_root() / ".env")

    if args.small_model:
        os.environ["DEEP_RESEARCH_SMALL_MODEL"] = args.small_model.strip()
    if args.heavy_model:
        os.environ["DEEP_RESEARCH_HEAVY_MODEL"] = args.heavy_model.strip()

    # Dependency check for pydantic (and optionally others)
    try:
        import pydantic  # noqa: F401
    except ImportError:
        print("\nERROR: Required dependency 'pydantic' is not installed.")
        print("To fix: activate your virtual environment and run:")
        print("    python -m pip install -e ./agentic-workflows-v2/")
        print("Or, if you prefer, just: python -m pip install pydantic\n")
        return 1

    try:
        from agentic_v2.langchain.runner import WorkflowRunner
    except ImportError as e:
        print(f"\nERROR: {e}\n")
        print("Make sure all dependencies are installed. Try:")
        print("    python -m pip install -e ./agentic-workflows-v2/\n")
        return 1

    topic = args.topic.strip()
    goal = args.goal.strip() if args.goal.strip() else _build_goal_from_topic(topic)

    workflow_inputs = {
        "topic": topic,
        "goal": goal,
        "domain": args.domain,
        "min_ci": float(args.min_ci),
        "max_rounds": int(args.max_rounds),
        "min_recent_sources": int(args.min_recent_sources),
        "recency_window_days": int(args.recency_window_days),
        "seed_urls": list(args.seed_url or []),
    }

    run_id = args.run_id.strip() or f"deep-research-{uuid.uuid4()}"
    runner = WorkflowRunner()
    result = runner.invoke("deep_research", thread_id=run_id, **workflow_inputs)

    timestamp_utc = datetime.now(timezone.utc).isoformat()
    metadata = result.metadata or {}
    payload = {
        "run_id": run_id,
        "timestamp_utc": timestamp_utc,
        "status": result.overall_status.value,
        "errors": metadata.get("errors", []),
        "elapsed_seconds": metadata.get("elapsed_seconds", 0.0),
        "topic": topic,
        "input": workflow_inputs,
        "model_overrides": {
            "DEEP_RESEARCH_SMALL_MODEL": os.getenv("DEEP_RESEARCH_SMALL_MODEL", ""),
            "DEEP_RESEARCH_HEAVY_MODEL": os.getenv("DEEP_RESEARCH_HEAVY_MODEL", ""),
            "AGENTIC_MODEL_TIER_2": os.getenv("AGENTIC_MODEL_TIER_2", ""),
            "AGENTIC_MODEL_TIER_3": os.getenv("AGENTIC_MODEL_TIER_3", ""),
            "AGENTIC_MODEL_TIER_4": os.getenv("AGENTIC_MODEL_TIER_4", ""),
        },
        "outputs": result.final_output,
        "steps": {s.step_name: s.model_dump() for s in result.steps},
    }

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = _repo_root() / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    json_path = out_dir / f"deep_research_{stamp}.json"
    md_path = out_dir / f"deep_research_{stamp}.md"
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md_path.write_text(_to_markdown(payload), encoding="utf-8")

    print("Workflow: deep_research")
    print(f"Run ID: {run_id}")
    print(f"Status: {result.overall_status.value}")
    elapsed = metadata.get("elapsed_seconds", 0.0)
    print(f"Elapsed: {elapsed:.2f}s")
    print(f"JSON: {json_path}")
    print(f"Markdown: {md_path}")

    errors = metadata.get("errors", [])
    if errors:
        print("Errors:")
        for err in errors:
            print(f"- {err}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
