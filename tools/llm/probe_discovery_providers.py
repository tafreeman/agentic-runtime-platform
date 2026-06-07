"""Per-provider probe functions for model discovery.

Each function probes one provider and returns a result dict suitable for
insertion into ``discovered["providers"][key]``.  All functions are
pure (no side-effects on shared state) so they can be called
independently or tested in isolation.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

from tools.llm.llm_client import LLMClient
from tools.llm.probe_config import (
    AI_GALLERY_CACHE_DIR,
    AITK_HOME_DIR,
    AITK_MODELINFO_FILE,
    AITK_MODELS_DIR,
    AITK_MODELS_TASK_TYPE,
    AITK_MS_SUBDIR,
    AITK_SUFFIX_CPU,
    AITK_SUFFIX_GENERIC_CPU,
    AITK_SUFFIX_GENERIC_GPU,
    AITK_SUFFIX_GPU,
    AITK_TRAILING_CHARS,
    AZURE_SLOT_RANGE,
    CACHE_BASE_DIR,
    CLOUD_API_HOSTS_SKIPLIST,
    DOTNET_CLI_ARG_PROJECT,
    ENDPOINT_TRUNCATION_LENGTH,
    ENV_ANTHROPIC_API_KEY,
    ENV_ANTHROPIC_BASE_URL,
    ENV_AZURE_FOUNDRY_API_KEY,
    ENV_AZURE_FOUNDRY_ENDPOINT_PREFIX,
    ENV_AZURE_OPENAI_API_KEY,
    ENV_AZURE_OPENAI_DEPLOYMENT,
    ENV_AZURE_OPENAI_ENDPOINT,
    ENV_GEMINI_API_KEY,
    ENV_GH_TOKEN,
    ENV_GITHUB_TOKEN,
    ENV_GOOGLE_API_KEY,
    ENV_LM_STUDIO_HOST,
    ENV_LMSTUDIO_HOST,
    ENV_LOCAL_AI_API_BASE_URL,
    ENV_LOCAL_OPENAI_BASE_URL,
    ENV_NVIDIA_NIM_API_KEY,
    ENV_NVIDIA_NIM_HOST,
    ENV_OLLAMA_HOST,
    ENV_OPENAI_API_BASE,
    ENV_OPENAI_API_KEY,
    ENV_OPENAI_BASE_URL,
    ERROR_BRIEF_LENGTH,
    GH_CLI_OUTPUT_MODELS_LIMIT,
    GITHUB_MODELS_API_BASE,
    GITHUB_TOKEN_SLOT_RANGE,
    LMSTUDIO_DEFAULT_HOST,
    LOCAL_SERVER_COMMON_PORTS,
    NVIDIA_NIM_TOKEN_SLOT_RANGE,
    OLLAMA_API_TAGS_ENDPOINT,
    OLLAMA_DEFAULT_HOST,
    PATH_SEPARATOR,
    PLATFORM_WINDOWS,
    PREFIX_AITK,
    PREFIX_CLAUDE,
    PREFIX_GEMINI,
    PREFIX_GITHUB,
    PREFIX_LMSTUDIO,
    PREFIX_LOCAL,
    PREFIX_LOCAL_API,
    PREFIX_OLLAMA,
    PREFIX_OPENAI,
    TIMEOUT_CLOUD_HTTP,
    TIMEOUT_OLLAMA_HTTP,
    TIMEOUT_WINDOWS_AI_BRIDGE,
    WINDOWS_AI_BRIDGE_DIR,
    WINDOWS_AI_BRIDGE_PROJECT,
    WINDOWS_AI_CLI_ARG_INFO,
    WINDOWS_AI_MODEL_ID,
)

logger = logging.getLogger(__name__)

CONTENT_TYPE_JSON = "application/json"


def _probe_local_onnx(verbose: bool = False) -> dict[str, Any]:
    """Probe local ONNX models from the AI Gallery cache."""

    ai_gallery = Path.home() / CACHE_BASE_DIR / AI_GALLERY_CACHE_DIR
    local_models: list[str] = []
    local_missing: list[str] = []

    try:
        from tools.llm.llm_client import LLMClient

        for key, model_path in LLMClient.LOCAL_MODELS.items():
            top_dir = str(model_path).split(PATH_SEPARATOR)[0]
            if ai_gallery.exists() and (ai_gallery / top_dir).exists():
                local_models.append(f"{PREFIX_LOCAL}{key}")
            else:
                local_missing.append(f"{PREFIX_LOCAL}{key}")
    except Exception as e:
        if verbose:
            logger.error("  Error: %s", e)

    return {
        "available": local_models,
        "missing": local_missing,
        "count": len(local_models),
        "path": str(ai_gallery),
    }


def _probe_github_models() -> dict[str, Any]:
    """Probe GitHub Models via HTTP API using GITHUB_TOKEN / GITHUB_TOKEN_0..N."""
    gh_models: list[str] = []
    gh_error = None
    rotation_keys: list[str] = []

    # Collect all configured tokens (primary + numbered slots)
    tokens: list[tuple[str, str]] = []  # (label, token)
    primary = os.getenv(ENV_GITHUB_TOKEN) or os.getenv(ENV_GH_TOKEN)
    if primary:
        tokens.append((ENV_GITHUB_TOKEN, primary))
    for i in range(GITHUB_TOKEN_SLOT_RANGE):
        slot_key = f"{ENV_GITHUB_TOKEN}_{i}"
        slot_val = os.getenv(slot_key)
        if slot_val:
            tokens.append((slot_key, slot_val))
            rotation_keys.append(slot_key)

    if not tokens:
        return {
            "available": gh_models,
            "count": 0,
            "rotation_keys": rotation_keys,
            "error": "No GITHUB_TOKEN or GITHUB_TOKEN_N configured",
        }

    # Use the first available token to fetch the model catalog
    _, token = tokens[0]
    try:
        req = urllib.request.Request(
            f"{GITHUB_MODELS_API_BASE}/models",
            headers={"Authorization": f"Bearer {token}", "Accept": CONTENT_TYPE_JSON},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_CLOUD_HTTP) as resp:
            catalog = json.loads(resp.read().decode("utf-8"))
            for m in catalog:
                raw_id = m.get("id", "")
                # Extract short name from azureml:// registry paths
                if raw_id.startswith("azureml://"):
                    parts = raw_id.split("/")
                    model_id = parts[-3] if len(parts) >= 3 else raw_id
                else:
                    model_id = raw_id
                if model_id:
                    gh_models.append(f"{PREFIX_GITHUB}{model_id}")
    except Exception as e:
        gh_error = str(e)[:ERROR_BRIEF_LENGTH]

    return {
        "available": gh_models,
        "count": len(gh_models),
        "token_accounts": len(tokens),
        "rotation_keys": rotation_keys,
        "error": gh_error,
    }


def _probe_ollama() -> dict[str, Any]:
    """Probe Ollama for locally running models."""
    ollama_host = os.getenv(ENV_OLLAMA_HOST, OLLAMA_DEFAULT_HOST)
    ollama_models: list[str] = []
    ollama_error = None

    try:
        req = urllib.request.Request(
            f"{ollama_host}{OLLAMA_API_TAGS_ENDPOINT}",
            headers={"Accept": CONTENT_TYPE_JSON},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_OLLAMA_HTTP) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            ollama_models = [
                f"{PREFIX_OLLAMA}{m.get('name', '')}" for m in data.get("models", [])
            ]
    except Exception:
        ollama_error = f"Ollama not reachable at {ollama_host}"

    return {
        "available": ollama_models,
        "count": len(ollama_models),
        "host": ollama_host,
        "error": ollama_error,
    }


def _probe_azure_foundry() -> dict[str, Any]:
    """Probe Azure Foundry configuration."""
    foundry_configured = bool(os.getenv(ENV_AZURE_FOUNDRY_API_KEY))
    foundry_endpoints: list[str] = []
    for k, v in os.environ.items():
        if k.startswith(ENV_AZURE_FOUNDRY_ENDPOINT_PREFIX) and v:
            foundry_endpoints.append(v)

    return {
        "configured": foundry_configured and bool(foundry_endpoints),
        "endpoints": foundry_endpoints,
        "notes": "Azure Foundry models require explicit model IDs (azure-foundry:model-name)",
    }


def _probe_azure_openai() -> dict[str, Any]:
    """Probe Azure OpenAI slot configuration."""
    azure_slots: list[dict[str, Any]] = []
    for i in range(AZURE_SLOT_RANGE):
        ep = os.getenv(f"{ENV_AZURE_OPENAI_ENDPOINT}_{i}")
        key = os.getenv(f"{ENV_AZURE_OPENAI_API_KEY}_{i}")
        deployment = os.getenv(f"{ENV_AZURE_OPENAI_DEPLOYMENT}_{i}")
        if ep and key:
            azure_slots.append(
                {
                    "slot": i,
                    "endpoint": (
                        ep[:ENDPOINT_TRUNCATION_LENGTH] + "..."
                        if len(ep) > ENDPOINT_TRUNCATION_LENGTH
                        else ep
                    ),
                    "deployment": deployment,
                }
            )

    if os.getenv(ENV_AZURE_OPENAI_ENDPOINT) and os.getenv(ENV_AZURE_OPENAI_API_KEY):
        azure_slots.append(
            {
                "slot": "default",
                "endpoint": os.getenv(ENV_AZURE_OPENAI_ENDPOINT, "")[
                    :ENDPOINT_TRUNCATION_LENGTH
                ],
                "deployment": os.getenv(ENV_AZURE_OPENAI_DEPLOYMENT),
            }
        )

    return {
        "configured": bool(azure_slots),
        "slots": azure_slots,
        "notes": "Use azure-openai:deployment-name to specify model",
    }


def _probe_openai() -> dict[str, Any]:
    """Probe OpenAI direct API for available models."""
    openai_configured = bool(os.getenv(ENV_OPENAI_API_KEY))
    openai_models: list[str] = []

    if openai_configured:
        try:
            openai_models = [
                f"{PREFIX_OPENAI}{m}" for m in LLMClient.list_openai_models()[:20]
            ]
        except Exception:
            openai_models = [
                f"{PREFIX_OPENAI}gpt-4o",
                f"{PREFIX_OPENAI}gpt-4o-mini",
                f"{PREFIX_OPENAI}gpt-4-turbo",
            ]

    return {
        "configured": openai_configured,
        "available": openai_models,
        "count": len(openai_models),
    }


def _probe_gemini() -> dict[str, Any]:
    """Probe Google Gemini API for available models."""
    gemini_key = os.getenv(ENV_GEMINI_API_KEY) or os.getenv(ENV_GOOGLE_API_KEY)
    gemini_configured = bool(gemini_key)
    gemini_models: list[str] = []
    gemini_error = None

    if gemini_configured:
        try:
            url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=50"
            req = urllib.request.Request(
                url,
                headers={"Accept": CONTENT_TYPE_JSON, "x-goog-api-key": gemini_key},
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT_CLOUD_HTTP) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for m in data.get("models", []):
                    name = m.get("name", "")
                    if name.startswith("models/"):
                        short = name.replace("models/", "")
                        gemini_models.append(f"{PREFIX_GEMINI}{short}")
        except Exception as e:
            gemini_error = str(e)[:ERROR_BRIEF_LENGTH]
            gemini_models = [
                f"{PREFIX_GEMINI}gemini-2.5-flash",
                f"{PREFIX_GEMINI}gemini-2.0-flash",
                f"{PREFIX_GEMINI}gemini-2.0-flash-lite",
            ]
    else:
        gemini_error = "No GEMINI_API_KEY or GOOGLE_API_KEY environment variable"

    gemini_keys_found: list[str] = []
    for i in range(10):
        k = os.getenv(f"GEMINI_API_KEY_{i}")
        if k:
            gemini_keys_found.append(f"GEMINI_API_KEY_{i}")

    return {
        "configured": gemini_configured,
        "available": gemini_models,
        "count": len(gemini_models),
        "rotation_keys": gemini_keys_found,
        "error": gemini_error,
    }


def _probe_anthropic() -> dict[str, Any]:
    """Probe Anthropic Claude API for available models."""
    anthropic_key = os.getenv(ENV_ANTHROPIC_API_KEY)
    anthropic_configured = bool(anthropic_key)
    anthropic_models: list[str] = []
    anthropic_error = None
    # Respect ANTHROPIC_URI if set (custom endpoint override)
    anthropic_base = (os.getenv(ENV_ANTHROPIC_BASE_URL) or "https://api.anthropic.com").rstrip("/")

    if anthropic_configured:
        try:
            url = f"{anthropic_base}/v1/models?limit=50"
            req = urllib.request.Request(
                url,
                headers={
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "Accept": CONTENT_TYPE_JSON,
                },
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT_CLOUD_HTTP) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for m in data.get("data", []):
                    model_id = m.get("id", "")
                    if model_id:
                        anthropic_models.append(f"{PREFIX_CLAUDE}{model_id}")
        except Exception as e:
            anthropic_error = str(e)[:ERROR_BRIEF_LENGTH]
            anthropic_models = [
                f"{PREFIX_CLAUDE}claude-sonnet-4-20250514",
                f"{PREFIX_CLAUDE}claude-haiku-4-20250414",
            ]
    else:
        anthropic_error = "No ANTHROPIC_API_KEY environment variable"

    anthropic_keys_found: list[str] = []
    for i in range(10):
        k = os.getenv(f"ANTHROPIC_API_KEY_{i}")
        if k:
            anthropic_keys_found.append(f"ANTHROPIC_API_KEY_{i}")

    return {
        "configured": anthropic_configured,
        "available": anthropic_models,
        "count": len(anthropic_models),
        "rotation_keys": anthropic_keys_found,
        "error": anthropic_error,
    }


def _probe_windows_ai(bridge_dir: Path) -> dict[str, Any]:
    """Probe Windows AI (Phi Silica) via the .NET bridge project."""
    import shutil

    windows_ai_available = False
    windows_ai_error = None
    windows_ai_ready_state = None

    if sys.platform == PLATFORM_WINDOWS and shutil.which("dotnet"):
        bridge_proj = bridge_dir / WINDOWS_AI_BRIDGE_DIR / WINDOWS_AI_BRIDGE_PROJECT
        if bridge_proj.exists():
            try:
                result = subprocess.run(
                    [
                        "dotnet",
                        "run",
                        DOTNET_CLI_ARG_PROJECT,
                        str(bridge_proj),
                        "--",
                        WINDOWS_AI_CLI_ARG_INFO,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=TIMEOUT_WINDOWS_AI_BRIDGE,
                    cwd=str(bridge_proj.parent),
                )
                stdout = (result.stdout or "").strip()
                stderr = (result.stderr or "").strip()

                info = None
                if stdout:
                    try:
                        info = json.loads(stdout)
                    except Exception:
                        info = None

                if isinstance(info, dict):
                    windows_ai_available = bool(info.get("available", False))
                    windows_ai_ready_state = info.get("readyState")
                    if not windows_ai_available:
                        windows_ai_error = info.get("error") or stderr or "Unknown"
                else:
                    windows_ai_error = stderr or stdout or "Bridge did not return JSON"
            except Exception as e:
                windows_ai_error = str(e)
        else:
            windows_ai_error = "Bridge project not found"
    else:
        windows_ai_error = "Windows only / dotnet not available"

    return {
        "available": windows_ai_available,
        "readyState": windows_ai_ready_state,
        "models": [WINDOWS_AI_MODEL_ID] if windows_ai_available else [],
        "error": windows_ai_error,
    }


def _probe_aitk() -> dict[str, Any]:
    """Probe AI Toolkit local ONNX models from VS Code AI Toolkit."""
    aitk_base = Path.home() / AITK_HOME_DIR
    aitk_models_dir = aitk_base / AITK_MODELS_DIR
    aitk_modelinfo = aitk_models_dir / AITK_MODELINFO_FILE

    aitk_models: list[str] = []
    aitk_catalog: list[str] = []
    aitk_error = None

    if not aitk_base.exists():
        aitk_error = "AI Toolkit not installed (run: code --install-extension ms-windows-ai-studio.windows-ai-studio)"
    elif not aitk_models_dir.exists():
        aitk_error = "No AI Toolkit models downloaded"
    else:
        downloaded: list[str] = []
        for subdir in aitk_models_dir.iterdir():
            if subdir.is_dir() and subdir.name != AITK_MS_SUBDIR:
                downloaded.append(subdir.name)
        ms_dir = aitk_models_dir / AITK_MS_SUBDIR
        if ms_dir.exists():
            for subdir in ms_dir.iterdir():
                if subdir.is_dir():
                    downloaded.append(subdir.name)

        for d in downloaded:
            simple_name = d.lower()
            for suffix in [
                AITK_SUFFIX_GENERIC_CPU,
                AITK_SUFFIX_GENERIC_GPU,
                AITK_SUFFIX_CPU,
                AITK_SUFFIX_GPU,
            ]:
                if suffix in simple_name:
                    simple_name = simple_name.split(suffix)[0]
            while simple_name and simple_name[-1].isdigit():
                simple_name = simple_name.rstrip(AITK_TRAILING_CHARS)
            aitk_models.append(f"{PREFIX_AITK}{simple_name}")

        aitk_models = list(dict.fromkeys(aitk_models))

        if aitk_modelinfo.exists():
            try:
                info = json.loads(aitk_modelinfo.read_text(encoding="utf-8"))
                for m in info.get("models", []):
                    if m.get("task") == AITK_MODELS_TASK_TYPE:
                        alias = m.get("alias", "")
                        if alias:
                            catalog_id = f"{PREFIX_AITK}{alias}"
                            if catalog_id not in aitk_models:
                                aitk_catalog.append(catalog_id)
            except Exception:
                pass

    return {
        "available": aitk_models,
        "count": len(aitk_models),
        "catalog": aitk_catalog[:GH_CLI_OUTPUT_MODELS_LIMIT],
        "path": str(aitk_models_dir) if aitk_models_dir.exists() else None,
        "error": aitk_error,
        "notes": "FREE local ONNX models via VS Code AI Toolkit (NOT cloud/paid)",
    }


def _probe_nvidia() -> dict[str, Any]:
    """Probe NVIDIA NIM OpenAI-compatible inference endpoint."""
    nvidia_host = os.getenv(ENV_NVIDIA_NIM_HOST, "")
    nvidia_models: list[str] = []
    nvidia_error = None
    nvidia_reachable = False

    # Collect all configured keys (primary + numbered slots)
    nvidia_keys: list[tuple[str, str]] = []
    primary_key = os.getenv(ENV_NVIDIA_NIM_API_KEY, "")
    if primary_key:
        nvidia_keys.append((ENV_NVIDIA_NIM_API_KEY, primary_key))
    for i in range(NVIDIA_NIM_TOKEN_SLOT_RANGE):
        slot_var = f"{ENV_NVIDIA_NIM_API_KEY}_{i}"
        slot_val = os.getenv(slot_var, "")
        if slot_val:
            nvidia_keys.append((slot_var, slot_val))
    rotation_keys = [k for k, _ in nvidia_keys[1:]]

    if not nvidia_host:
        return {
            "configured": False,
            "host": None,
            "reachable": False,
            "available": [],
            "count": 0,
            "key_accounts": len(nvidia_keys),
            "rotation_keys": rotation_keys,
            "error": "NVIDIA_NIM_HOST not set",
        }

    # Strip chat/completions path segment — we need the base /v1/models endpoint
    base = nvidia_host.rstrip("/")
    for tail in ["/chat/completions", "/completions", "/chat"]:
        if base.endswith(tail):
            base = base[: -len(tail)]
            break

    # Use first available key for model listing
    active_key = nvidia_keys[0][1] if nvidia_keys else ""

    try:
        models_url = f"{base.rstrip('/')}/models"
        headers = {"Accept": CONTENT_TYPE_JSON}
        if active_key:
            headers["Authorization"] = f"Bearer {active_key}"
        req = urllib.request.Request(models_url, headers=headers)
        with urllib.request.urlopen(req, timeout=TIMEOUT_CLOUD_HTTP) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for m in data.get("data", []):
                mid = m.get("id", "") if isinstance(m, dict) else ""
                if mid:
                    nvidia_models.append(f"nvidia:{mid}")
            nvidia_reachable = True
    except Exception as e:
        nvidia_error = f"NVIDIA NIM not reachable at {base}: {str(e)[:100]}"

    return {
        "configured": bool(nvidia_host),
        "host": base,
        "reachable": nvidia_reachable,
        "available": nvidia_models,
        "count": len(nvidia_models),
        "key_accounts": len(nvidia_keys),
        "rotation_keys": rotation_keys,
        "error": nvidia_error,
    }


def _probe_lmstudio() -> dict[str, Any]:
    """Probe LM Studio OpenAI-compatible local server."""
    # Accept both LMSTUDIO_HOST and LM_STUDIO_HOST; strip trailing path segments
    raw_host = os.getenv(ENV_LMSTUDIO_HOST) or os.getenv(ENV_LM_STUDIO_HOST, LMSTUDIO_DEFAULT_HOST)
    # Strip /v1/... or /chat/completions suffixes so we get a clean base URL
    for tail in ["/v1/chat/completions", "/chat/completions", "/v1"]:
        if raw_host.rstrip("/").endswith(tail.rstrip("/")):
            raw_host = raw_host.rstrip("/")[: -len(tail)]
            break
    lmstudio_host = raw_host
    lmstudio_models: list[str] = []
    lmstudio_error = None
    lmstudio_reachable = False

    try:
        lm_url = f"{lmstudio_host.rstrip('/')}/v1/models"
        req = urllib.request.Request(lm_url, headers={"Accept": CONTENT_TYPE_JSON})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for m in data.get("data", []):
                mid = m.get("id", "") if isinstance(m, dict) else ""
                if mid:
                    lmstudio_models.append(f"{PREFIX_LMSTUDIO}{mid}")
            lmstudio_reachable = True
    except Exception as e:
        lmstudio_error = f"LM Studio not reachable at {lmstudio_host}: {str(e)[:100]}"

    return {
        "configured": lmstudio_reachable,
        "host": lmstudio_host,
        "reachable": lmstudio_reachable,
        "available": lmstudio_models,
        "count": len(lmstudio_models),
        "error": lmstudio_error,
        "notes": (
            "Queries OpenAI-compatible API (/v1/models) since native REST "
            "(/api/v1/chat) lacks Custom Tool support. Override host with "
            "LMSTUDIO_HOST."
        ),
    }


def _probe_local_openai_compatible(lmstudio_host: str = "") -> dict[str, Any]:
    """Probe generic OpenAI-compatible local servers (LocalAI, text-gen-webui, etc.)."""
    local_api_base = (
        os.getenv(ENV_OPENAI_BASE_URL)
        or os.getenv(ENV_OPENAI_API_BASE)
        or os.getenv(ENV_LOCAL_AI_API_BASE_URL)
        or os.getenv(ENV_LOCAL_OPENAI_BASE_URL)
    )

    # Skip if the configured URL points at a well-known cloud API — those have
    # their own dedicated probe functions and must not be double-counted here.
    if local_api_base:
        from urllib.parse import urlparse
        hostname = urlparse(local_api_base).hostname or ""
        if any(hostname.endswith(h) for h in CLOUD_API_HOSTS_SKIPLIST):
            return {
                "configured": False,
                "host": local_api_base,
                "reachable": False,
                "available": [],
                "count": 0,
                "error": f"Skipped: {hostname} is a cloud API (handled by its own probe)",
                "notes": "Any OpenAI-compatible local server (LocalAI, AMD ROCm, text-gen-webui, etc.)",
            }

    local_api_models: list[str] = []
    local_api_error = None
    local_api_host: str | None = local_api_base
    local_api_reachable = False

    if local_api_base:
        try:
            la_url = f"{local_api_base.rstrip('/')}/v1/models"
            req = urllib.request.Request(la_url, headers={"Accept": CONTENT_TYPE_JSON})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for m in data.get("data", []):
                    mid = m.get("id", "") if isinstance(m, dict) else ""
                    if mid:
                        local_api_models.append(f"{PREFIX_LOCAL_API}{mid}")
                local_api_reachable = True
        except Exception as e:
            local_api_error = (
                f"Local API not reachable at {local_api_base}: {str(e)[:100]}"
            )
    else:
        for port in LOCAL_SERVER_COMMON_PORTS:
            if lmstudio_host and f":{port}" in lmstudio_host:
                continue
            try:
                scan_url = f"http://localhost:{port}/v1/models"
                req = urllib.request.Request(
                    scan_url, headers={"Accept": CONTENT_TYPE_JSON}
                )
                with urllib.request.urlopen(req, timeout=1) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    for m in data.get("data", []):
                        mid = m.get("id", "") if isinstance(m, dict) else ""
                        if mid:
                            local_api_models.append(f"{PREFIX_LOCAL_API}{mid}")
                    if local_api_models:
                        local_api_host = f"http://localhost:{port}"
                        local_api_reachable = True
                        break
            except Exception:
                continue
        if not local_api_reachable:
            local_api_error = "No local API server found (set OPENAI_BASE_URL or LOCAL_AI_API_BASE_URL)"

    return {
        "configured": local_api_reachable,
        "host": local_api_host,
        "reachable": local_api_reachable,
        "available": local_api_models,
        "count": len(local_api_models),
        "error": local_api_error,
        "notes": "Any OpenAI-compatible local server (LocalAI, AMD ROCm, text-gen-webui, etc.)",
    }
