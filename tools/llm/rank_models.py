#!/usr/bin/env python3
"""Generates a ranked model list combining probe data and provider limit checks.

Includes ALL available models.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Repo root is 2 levels up from this file (tools/llm/rank_models.py)
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_DEFAULT_PROBE_FILE = str(_REPO_ROOT / "tools" / "llm" / "output44.json")
_DEFAULT_LIMITS_FILE = str(_REPO_ROOT / "runs" / "provider_limits.json")
_DEFAULT_OUTPUT_FILE = str(_REPO_ROOT / "runs" / "model_ranking.json")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    p = argparse.ArgumentParser(description="Rank models from probe and limits data")
    p.add_argument(
        "--probe-file", default=_DEFAULT_PROBE_FILE, help="Model probe JSON file"
    )
    p.add_argument(
        "--limits-file", default=_DEFAULT_LIMITS_FILE, help="Provider limits JSON file"
    )
    p.add_argument(
        "--out", default=_DEFAULT_OUTPUT_FILE, help="Output ranking JSON file"
    )
    args = p.parse_args(argv)

    PROBE_FILE = args.probe_file
    LIMITS_FILE = args.limits_file
    OUTPUT_FILE = args.out
    # Load data
    try:
        with open(PROBE_FILE, encoding="utf-8") as f:
            probe = json.load(f)
    except Exception as e:
        logger.error(f"Error loading {PROBE_FILE}: {e}")
        return 2

    try:
        with open(LIMITS_FILE, encoding="utf-8") as f:
            limits = json.load(f)
    except Exception as e:
        logger.warning(f"Could not load {LIMITS_FILE}: {e}")
        limits = {"checked": {}}

    ranked_providers = {}

    # 1. Local ONNX
    if "local_onnx" in probe["providers"]:
        p = probe["providers"]["local_onnx"]
        ranked_providers["local_onnx"] = {
            "score": 100,
            "rank": 1,
            "reason": "Local models available on disk; no external quota or billing; highest throughput.",
            "available_count": p.get("count", 0),
            "models": p.get("available", []),
        }

    # 2. LM Studio
    if "lmstudio" in probe["providers"]:
        p = probe["providers"]["lmstudio"]
        # Check limits/status
        check = limits["checked"].get("lmstudio", {})
        is_ok = check.get("ok", False) or p.get("reachable", False)

        if is_ok:
            # Prefer list from limits check if available, else probe
            models = p.get("available", [])
            if check.get("json") and "data" in check["json"]:
                models = [m["id"] for m in check["json"]["data"]]

            ranked_providers["lmstudio"] = {
                "score": 90,
                "rank": 2,
                "reason": "LM Studio reachable locally exposing OpenAI-compatible models.",
                "available_count": len(models),
                "models": models,
            }

    # 3. OpenAI
    # Probe might say 0 if it didn't use a key, but limits check might have succeeded
    openai_check = limits["checked"].get("openai", {})
    openai_models = []
    if openai_check.get("ok"):
        if "short" in openai_check and "data" in openai_check["short"]:
            openai_models = [m["id"] for m in openai_check["short"]["data"]]

    if not openai_models and "openai" in probe["providers"]:
        openai_models = probe["providers"]["openai"].get("available", [])

    if openai_models:
        ranked_providers["openai"] = {
            "score": 80,
            "rank": 3,
            "reason": "OpenAI API validated and returning models. Billable usage.",
            "available_count": len(openai_models),
            "models": openai_models,
            "evidence": {"models_returned": True},
        }

    # 4. GitHub Models
    if "github_models" in probe["providers"]:
        p = probe["providers"]["github_models"]
        gh_check = limits["checked"].get("github", {})

        evidence = {}
        if gh_check.get("ok") and "json" in gh_check:
            res = gh_check["json"].get("resources", {}).get("core", {})
            evidence = {
                "rate_core_limit": res.get("limit"),
                "rate_core_remaining": res.get("remaining"),
            }

        ranked_providers["github_models"] = {
            "score": 70,
            "rank": 4,
            "reason": "GitHub token valid. Good fallback for gh: models.",
            "available_count": p.get("count", 0),
            "models": p.get("available", []),
            "evidence": evidence,
        }

    # 5. Anthropic
    if "anthropic" in probe["providers"]:
        p = probe["providers"]["anthropic"]
        anth_check = limits["checked"].get("anthropic", {})

        # Even if check failed (400), we know keys are present
        ranked_providers["anthropic"] = {
            "score": 60,
            "rank": 5,
            "reason": "Anthropic keys present. Probe lists models.",
            "available_count": p.get("count", 0),
            "models": p.get("available", []),
            "evidence": {
                "http_status": anth_check.get("status_code"),
                "error": anth_check.get("json") if not anth_check.get("ok") else None,
            },
        }

    # 6. Gemini
    if "gemini" in probe["providers"]:
        p = probe["providers"]["gemini"]
        ranked_providers["gemini"] = {
            "score": 50,
            "rank": 6,
            "reason": "API keys present. Quota check requires GCP Console.",
            "available_count": p.get("count", 0),
            "models": p.get("available", []),
            "rotation_keys": p.get("rotation_keys", []),
        }

    # 7. AI Toolkit (Local)
    if "ai_toolkit" in probe["providers"]:
        p = probe["providers"]["ai_toolkit"]
        if p.get("count", 0) > 0:
            ranked_providers["ai_toolkit"] = {
                "score": 95,  # High score if available locally
                "rank": 1.5,
                "reason": "VS Code AI Toolkit local models available.",
                "available_count": p.get("count", 0),
                "models": p.get("available", []),
            }

    # 8. Ollama
    if "ollama" in probe["providers"]:
        p = probe["providers"]["ollama"]
        oll_check = limits["checked"].get("ollama", {})
        is_ok = oll_check.get("ok", False)

        # If check ok, use check models, else probe
        models = p.get("available", [])
        if is_ok and oll_check.get("json") and "models" in oll_check["json"]:
            models = [m["name"] for m in oll_check["json"]["models"]]

        ranked_providers["ollama"] = {
            "score": 30 if not is_ok else 85,
            "rank": 7 if not is_ok else 2.5,
            "reason": (
                "Ollama host returned 404" if not is_ok else "Ollama running locally."
            ),
            "available_count": len(models),
            "models": models,
            "evidence": {"http_status": oll_check.get("status_code")},
        }

    # Construct final output
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_probe": PROBE_FILE,
        "source_checks": LIMITS_FILE,
        "summary": {
            "total_available": sum(
                len(p.get("models", [])) for p in ranked_providers.values()
            ),
            "providers_configured": len(ranked_providers),
            "note": "Scoring favors local availability, reachable local APIs, then authenticated cloud providers.",
        },
        "providers": ranked_providers,
        "recommended_use_cases": {
            "high_throughput_low_cost": (
                "local_onnx" if "local_onnx" in ranked_providers else "github_models"
            ),
            "local_api_with_compat": (
                "lmstudio" if "lmstudio" in ranked_providers else "ollama"
            ),
            "best_capability_paid": "openai",
            "fallback_catalog": "github_models",
        },
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    logger.info(
        f"Generated {OUTPUT_FILE} with {output['summary']['total_available']} total models."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
