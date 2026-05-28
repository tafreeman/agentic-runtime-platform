"""Task specifications and discovery helpers for the model bakeoff.

Contains:
- TaskSpec dataclass
- DEFAULT_TASKS list
- Provider/model utility helpers used during candidate discovery
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TaskSpec:
    task_id: str
    title: str
    prompt: str
    expect_json: bool
    required_keys: list[str]
    required_terms: list[str]
    weight: float


TASKS: list[TaskSpec] = [
    TaskSpec(
        task_id="workflow_strategy",
        title="Workflow Pattern Selection",
        prompt=(
            "You are advising engineers on agentic AI workflow design.\n"
            "Choose among ToT, ReAct, CoVe, and iterative review loops for a deep "
            "research system. Return JSON with keys:\n"
            "recommended_workflow, when_to_use, when_not_to_use, quality_gates.\n"
            "Keep it concise and practical."
        ),
        expect_json=True,
        required_keys=[
            "recommended_workflow",
            "when_to_use",
            "when_not_to_use",
            "quality_gates",
        ],
        required_terms=["tot", "react", "cove", "confidence", "verification"],
        weight=1.0,
    ),
    TaskSpec(
        task_id="architecture",
        title="Architecture Plan",
        prompt=(
            "Design an architecture for a multi-agent deep research platform used "
            "by software engineers and architects. Include source governance, "
            "verification, and RAG packaging. Return JSON with keys:\n"
            "components, data_flow, observability, failure_modes, mitigations."
        ),
        expect_json=True,
        required_keys=[
            "components",
            "data_flow",
            "observability",
            "failure_modes",
            "mitigations",
        ],
        required_terms=["rag", "cit", "source", "policy", "guardrail"],
        weight=1.1,
    ),
    TaskSpec(
        task_id="implementation_plan",
        title="Implementation Plan",
        prompt=(
            "Produce an implementation plan for the architecture. Include testing "
            "strategy for unit, integration, and end-to-end. Return JSON with keys:\n"
            "phases, tests, rollback, risks, owners."
        ),
        expect_json=True,
        required_keys=["phases", "tests", "rollback", "risks", "owners"],
        required_terms=["unit", "integration", "end-to-end", "rollback", "adr"],
        weight=1.0,
    ),
    TaskSpec(
        task_id="code_task",
        title="Coding Practicality",
        prompt=(
            "Write Python code for a function `rank_sources(sources)` that sorts "
            "research sources by trust score and recency. Include a minimal pytest "
            "unit test snippet."
        ),
        expect_json=False,
        required_keys=[],
        required_terms=["def rank_sources", "pytest", "assert"],
        weight=0.9,
    ),
]


def _repo_root() -> Path:
    # tools/llm/bakeoff_tasks.py -> repo root
    return Path(__file__).resolve().parents[2]


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
    import sys

    root = _repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _provider_of(model_id: str) -> str:
    if ":" not in model_id:
        return "ollama"
    return model_id.split(":", 1)[0].lower()


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _is_local_openai_base(base_url: str | None) -> bool:
    if not base_url:
        return False
    text = base_url.lower()
    return any(host in text for host in ["localhost", "127.0.0.1", "::1"])


def _discover_openai_compatible_models(base_url: str) -> list[str]:
    base = base_url.rstrip("/")
    url = f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []

    models: list[str] = []
    if isinstance(data, dict):
        for item in data.get("data", []):
            if isinstance(item, dict):
                model_id = str(item.get("id", "")).strip()
                if model_id:
                    models.append(f"openai:{model_id}")
    return models


def _parse_json_from_text(text: str) -> dict[str, Any] | None:
    raw = text.strip()
    if not raw:
        return None

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    for candidate in fenced:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(raw[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    return None
