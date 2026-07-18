#!/usr/bin/env python3
"""Lightweight provider rate-limit checker.

Usage:
  python check_provider_limits.py --probe-file filename.json --out limits.json

This script reads a model probe JSON (like `filename.json`) and performs
lightweight API checks for providers when corresponding environment keys
or hosts are present. It reports response headers or small status fields
that help infer rate-limit quotas.

NOTE: Keep your API keys secret. This script expects keys to be available
in the process environment (or load them from a `.env` file using
python-dotenv if installed).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any

logger = logging.getLogger(__name__)

try:
    import requests
except Exception:
    logger.error("Please install 'requests' (pip install requests) to run this script.")
    sys.exit(1)

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    # dotenv is optional; env may already be set by the shell
    pass


COMMON_ENV_KEYS = {
    "github": ["GITHUB_TOKEN", "GH_TOKEN"],
    "openai": [
        "OPENAI_API_KEY",
        "OPENAI_API_BASE",
        "OPENAI_BASE_URL",
        "OPENAI_API_BASE_URL",
    ],
    "anthropic": ["ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY_0"],
    "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
    "lmstudio": ["LMSTUDIO_HOST", "LMSTUDIO_URL"],
    "ollama": ["OLLAMA_HOST", "OLLAMA_URL"],
    "local_openai": ["LOCAL_AI_API_BASE_URL", "OPENAI_BASE_URL"],
    "azure": ["AZURE_OPENAI_API_KEY_0", "AZURE_OPENAI_ENDPOINT_0"],
}


def detect_env_keys() -> dict[str, dict[str, bool]]:
    """Return a mapping of provider -> {env_var: is_set} for common keys (never exposes
    values)."""
    found: dict[str, dict[str, bool]] = {}
    for provider, keys in COMMON_ENV_KEYS.items():
        provider_map: dict[str, bool] = {}
        for k in keys:
            provider_map[k] = bool(os.getenv(k))
        found[provider] = provider_map
    return found


def mask(val: str | None) -> str | None:
    if val is None:
        return None
    if len(val) <= 8:
        return "****"
    return val[:4] + "..." + val[-4:]


def check_github(token: str) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    url = "https://api.github.com/rate_limit"
    r = requests.get(url, headers=headers, timeout=10)
    return {
        "status_code": r.status_code,
        "ok": r.ok,
        "json": r.json() if r.ok else r.text,
    }


def check_openai(key: str, base: str | None = None) -> dict[str, Any]:
    base = base or "https://api.openai.com"
    url = f"{base.rstrip('/')}/v1/models"
    headers = {"Authorization": f"Bearer {key}"}
    r = requests.get(url, headers=headers, timeout=10)
    return {
        "status_code": r.status_code,
        "ok": r.ok,
        "headers": {
            k: v
            for k, v in r.headers.items()
            if "rate" in k.lower() or "limit" in k.lower()
        },
        "short": (
            r.json()
            if r.ok and r.headers.get("content-type", "").startswith("application/json")
            else r.text
        ),
    }


def check_anthropic(key: str) -> dict[str, Any]:
    url = "https://api.anthropic.com/v1/models"
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "Accept": "application/json",
    }
    r = requests.get(url, headers=headers, timeout=10)
    return {
        "status_code": r.status_code,
        "ok": r.ok,
        "count": len((r.json() if r.ok else {}).get("data", [])),
    }


def check_lmstudio(host: str) -> dict[str, Any]:
    url = f"{host.rstrip('/')}/api/v1/models"
    token = os.getenv("LM_API_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else None
    r = requests.get(url, headers=headers, timeout=6)
    return {
        "status_code": r.status_code,
        "ok": r.ok,
        "json": (r.json() if r.ok else r.text),
    }


def check_ollama(host: str) -> dict[str, Any]:
    url = f"{host.rstrip('/')}/api/tags"
    r = requests.get(url, timeout=6)
    return {
        "status_code": r.status_code,
        "ok": r.ok,
        "json": (r.json() if r.ok else r.text),
    }


def check_local_openai(host: str) -> dict[str, Any]:
    url = f"{host.rstrip('/')}/v1/models"
    r = requests.get(url, timeout=6)
    return {
        "status_code": r.status_code,
        "ok": r.ok,
        "json": (r.json() if r.ok else r.text),
    }


def _run_check(out: dict[str, Any], name: str, func: Any, *args: Any) -> None:
    """Run a provider check, storing the result (or error) under ``name``."""
    try:
        out["checked"][name] = func(*args)
    except Exception as e:
        out["checked"][name] = {"error": str(e)}


def _collect_checks(out: dict[str, Any]) -> None:
    """Run all configured provider checks and populate ``out['checked']``."""
    # GitHub
    gh = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if gh:
        _run_check(out, "github", check_github, gh)

    # OpenAI
    openai_key = os.getenv("OPENAI_API_KEY")
    openai_base = os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE")
    if openai_key:
        _run_check(out, "openai", check_openai, openai_key, openai_base)

    # Anthropic
    anth = os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY_0")
    if anth:
        _run_check(out, "anthropic", check_anthropic, anth)

    # Gemini - best effort (Google API variations exist)
    gem = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if gem:
        out["checked"]["gemini"] = {
            "note": "API key present; please verify quotas in Google Cloud Console or run provider-specific checks"
        }

    # LM Studio
    lm = os.getenv("LMSTUDIO_HOST")
    if lm:
        _run_check(out, "lmstudio", check_lmstudio, lm)

    # Ollama
    oll = os.getenv("OLLAMA_HOST")
    if oll:
        _run_check(out, "ollama", check_ollama, oll)

    # Local OpenAI-compatible
    local_openai = os.getenv("LOCAL_AI_API_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    if local_openai:
        _run_check(out, "local_openai", check_local_openai, local_openai)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument(
        "--probe-file", default="filename.json", help="Model probe JSON file"
    )
    p.add_argument("--out", default=None, help="Optional output JSON file for results")
    args = p.parse_args(argv)

    try:
        with open(args.probe_file, encoding="utf-8") as f:
            probe = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load probe file: {e}")
        return 2

    out: dict[str, Any] = {"checked": {}, "probe_summary": probe.get("summary")}

    _collect_checks(out)

    # Save output or print
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(json.dumps(out, indent=2))
        logger.info(f"Saved check results to: {args.out}")
    else:
        logger.info(json.dumps(out, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
