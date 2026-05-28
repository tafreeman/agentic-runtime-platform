#!/usr/bin/env python3
"""Model capability inventory for the prompts toolchain.

Goal
----
Provide a single, startup-time, *best-effort* inventory of which model
providers and models are usable in the current environment.

This is intentionally conservative:
- It never prints secrets.
- It favors "passive" checks (env vars present, local files exist).
- When `active_probes=True`, it performs a few lightweight network calls which
    may incur cost/quotas (OpenAI/Gemini listing; Ollama tags; optional gh
    check).

The returned dict is JSON-serializable.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)


def _repo_root() -> Path:
    # prompts/tools/model_inventory.py -> prompts/
    return Path(__file__).resolve().parents[1]


def _load_dotenv(dotenv_path: Path) -> None:
    """Best-effort .env loader (no external dependency).

    - Ignores comments/blank lines
    - Supports KEY=VALUE and quoted values
    - Does not overwrite existing environment variables
    """
    if not dotenv_path.exists() or not dotenv_path.is_file():
        return

    try:
        text = dotenv_path.read_text(encoding="utf-8")
    except Exception:
        return

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = k.strip()
        value = v.strip()
        if not key or key in os.environ:
            continue
        # Strip optional quotes.
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        os.environ[key] = value


def _bool_env_present(*names: str) -> bool:
    return any(bool(os.getenv(n)) for n in names)


def _safe_hostname_from_url(url: str) -> str | None:
    # Very small URL parser, good enough for https://host/... and
    # http://host/...
    m = re.match(r"^https?://([^/]+)/?", url.strip())
    return m.group(1) if m else None


def _dns_resolves(hostname: str) -> bool:
    try:
        # getaddrinfo can be slow but is generally OK for a startup-time
        # best-effort check
        socket.getaddrinfo(hostname, None)
        return True
    except Exception:
        return False


def _probe_http_json(
    url: str,
    timeout_s: int = 3,
) -> tuple[bool, dict[str, Any] | None, str | None]:
    try:
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return True, json.loads(body), None
            except Exception:
                return True, None, "Non-JSON response"
    except urllib.error.HTTPError as e:
        return False, None, f"HTTP {e.code}"
    except Exception as e:
        return False, None, str(e)


def _probe_ollama(host: str) -> dict[str, Any]:
    base = host.rstrip("/")
    ok, data, err = _probe_http_json(f"{base}/api/tags", timeout_s=3)
    models: list[str] = []
    if ok and isinstance(data, dict):
        for m in data.get("models", []) or []:
            name = m.get("name") if isinstance(m, dict) else None
            if name:
                models.append(name)
    return {
        "configured": True,
        "host": host,
        "reachable": ok,
        "models": sorted(set(models)),
        "error": err,
    }


def _probe_openai_compatible_models(base_url: str) -> dict[str, Any]:
    # OpenAI-compatible servers typically support GET /v1/models
    base = base_url.rstrip("/")
    ok, data, err = _probe_http_json(f"{base}/v1/models", timeout_s=3)
    models: list[str] = []
    if ok and isinstance(data, dict):
        for m in data.get("data", []) or []:
            mid = m.get("id") if isinstance(m, dict) else None
            if mid:
                models.append(mid)
    return {
        "configured": True,
        "base_url": base_url,
        "reachable": ok,
        "models": sorted(set(models)),
        "error": err,
    }


def build_inventory(active_probes: bool = False) -> dict[str, Any]:
    """Build a JSON-serializable capability inventory."""

    root = _repo_root()
    _load_dotenv(root / ".env")

    # Import lazily to avoid heavy import chains.
    try:
        from llm_client import LLMClient
    except Exception as e:
        return {
            "ok": False,
            "error": f"Failed to import llm_client: {e}",
            "root": str(root),
        }

    inv: dict[str, Any] = {
        "ok": True,
        "root": str(root),
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "active_probes": active_probes,
        "providers": {},
    }

    providers: dict[str, Any] = {}

    # ---------------------------------------------------------------------
    # Local ONNX (AI Dev Gallery cache)
    # ---------------------------------------------------------------------
    ai_gallery = Path.home() / ".cache" / "aigallery"
    local_models_installed: list[str] = []
    local_models_missing: list[str] = []
    if ai_gallery.exists():
        for key, model_dir in LLMClient.LOCAL_MODELS.items():
            # model_dir may include nested subpaths; the top folder is enough
            # to detect install.
            top = str(model_dir).split("/", 1)[0]
            if (ai_gallery / top).exists():
                local_models_installed.append(key)
            else:
                local_models_missing.append(key)

    providers["local_onnx"] = {
        "configured": True,
        "aigallery_path": str(ai_gallery),
        "aigallery_exists": ai_gallery.exists(),
        "installed_model_keys": sorted(set(local_models_installed)),
        "missing_model_keys": (
            sorted(set(local_models_missing)) if ai_gallery.exists() else []
        ),
        "notes": "Model keys correspond to llm_client.LLMClient.LOCAL_MODELS",
    }

    # ---------------------------------------------------------------------
    # GitHub Models (gh models)
    # ---------------------------------------------------------------------
    gh_path = shutil.which("gh")
    gh_token_present = _bool_env_present("GITHUB_TOKEN", "GH_TOKEN")

    gh_info: dict[str, Any] = {
        "configured": gh_token_present,
        "gh_cli_on_path": bool(gh_path),
        "can_attempt": bool(gh_path) and gh_token_present,
        "models": [],
    }

    if active_probes and gh_info["can_attempt"]:
        try:
            # This is a pragmatic probe: we just ensure the subcommand exists.
            r = subprocess.run(
                ["gh", "models", "--help"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            gh_info["reachable"] = r.returncode == 0
            if r.returncode != 0:
                gh_info["error"] = (r.stderr or r.stdout).strip()[:500]
        except Exception as e:
            gh_info["reachable"] = False
            gh_info["error"] = str(e)

    providers["github_models"] = gh_info

    # ---------------------------------------------------------------------
    # OpenAI (hosted)
    # ---------------------------------------------------------------------
    openai_configured = _bool_env_present("OPENAI_API_KEY")
    openai_models: list[str] = []
    openai_error: str | None = None

    if active_probes and openai_configured:
        try:
            openai_models = LLMClient.list_openai_models()
        except Exception as e:
            openai_error = str(e)

    providers["openai"] = {
        "configured": openai_configured,
        "models": openai_models,
        "model_count": len(openai_models),
        "error": openai_error,
        "notes": "Use model IDs directly with LLMClient (e.g., gpt-4o-mini)",
    }

    # ---------------------------------------------------------------------
    # Gemini
    # ---------------------------------------------------------------------
    gemini_configured = _bool_env_present("GEMINI_API_KEY", "GOOGLE_API_KEY")
    gemini_models: list[str] = []
    gemini_error: str | None = None

    if active_probes and gemini_configured:
        try:
            gemini_models = LLMClient.list_gemini_models()
        except Exception as e:
            gemini_error = str(e)

    providers["gemini"] = {
        "configured": gemini_configured,
        "models": gemini_models,
        "model_count": len(gemini_models),
        "error": gemini_error,
        "notes": ("Model IDs are the part after 'models/' in the Gemini list API"),
    }

    # ---------------------------------------------------------------------
    # Anthropic Claude
    # ---------------------------------------------------------------------
    claude_configured = _bool_env_present(
        "ANTHROPIC_API_KEY",
        "CLAUDE_API_KEY",
    )
    providers["claude"] = {
        "configured": claude_configured,
        "notes": (
            "Anthropic does not provide a public list-models endpoint via "
            "this toolchain; configure a model explicitly."
        ),
    }

    # ---------------------------------------------------------------------
    # Azure Foundry (OpenAI-compatible data-plane endpoints)
    # ---------------------------------------------------------------------
    foundry_api_key_present = _bool_env_present("AZURE_FOUNDRY_API_KEY")
    foundry_endpoints: list[str] = []
    for k, v in os.environ.items():
        if k.startswith("AZURE_FOUNDRY_ENDPOINT_") and v:
            foundry_endpoints.append(v)

    foundry_endpoint_hosts = []
    for ep in foundry_endpoints:
        host = _safe_hostname_from_url(ep)
        foundry_endpoint_hosts.append(
            {
                "endpoint": ep,
                "host": host,
                "dns_resolves": _dns_resolves(host) if host else False,
            }
        )

    providers["azure_foundry"] = {
        "configured": foundry_api_key_present and bool(foundry_endpoints),
        "api_key_present": foundry_api_key_present,
        "endpoints": foundry_endpoint_hosts,
        "notes": (
            "Foundry typically uses https://<resource>.services.ai.azure.com/"
            ".../chat/completions?api-version=..."
        ),
    }

    # ---------------------------------------------------------------------
    # Azure OpenAI (resource endpoints)
    # ---------------------------------------------------------------------
    azure_slots: list[dict[str, Any]] = []
    for i in range(0, 10):
        ep = os.getenv(f"AZURE_OPENAI_ENDPOINT_{i}")
        key = os.getenv(f"AZURE_OPENAI_API_KEY_{i}")
        if not ep and not key:
            continue

        host = _safe_hostname_from_url(ep) if ep else None
        azure_slots.append(
            {
                "slot": i,
                "endpoint_present": bool(ep),
                "api_key_present": bool(key),
                "host": host,
                "dns_resolves": _dns_resolves(host) if host else False,
                "deployment": os.getenv(f"AZURE_OPENAI_DEPLOYMENT_{i}") or None,
            }
        )

    providers["azure_openai"] = {
        "configured": any(
            s.get("endpoint_present") and s.get("api_key_present") for s in azure_slots
        ),
        "slots": azure_slots,
        "api_version": os.getenv("AZURE_OPENAI_API_VERSION") or None,
        "notes": (
            "Deployments are required for chat completions (data plane cannot "
            "list deployments)."
        ),
    }

    # ---------------------------------------------------------------------
    # Local AI API (OpenAI-compatible) + Ollama
    # ---------------------------------------------------------------------
    # 1) Ollama
    ollama_host = os.getenv("OLLAMA_HOST") or "http://localhost:11434"
    providers["ollama"] = (
        _probe_ollama(ollama_host)
        if active_probes
        else {
            "configured": True,
            "host": ollama_host,
            "reachable": None,
            "models": [],
            "notes": ("Set OLLAMA_HOST to override (default http://localhost:11434)."),
        }
    )

    # 2) Generic OpenAI-compatible server
    local_openai_base = (
        os.getenv("OPENAI_BASE_URL")
        or os.getenv("OPENAI_API_BASE")
        or os.getenv("LOCAL_AI_API_BASE_URL")
        or os.getenv("LOCAL_OPENAI_BASE_URL")
    )

    if local_openai_base:
        providers["local_openai_compatible"] = (
            _probe_openai_compatible_models(local_openai_base)
            if active_probes
            else {
                "configured": True,
                "base_url": local_openai_base,
                "reachable": None,
                "models": [],
            }
        )
    else:
        providers["local_openai_compatible"] = {
            "configured": False,
            "notes": (
                "Set OPENAI_BASE_URL (or OPENAI_API_BASE) to probe an OpenAI-"
                "compatible local server."
            ),
        }

    # ---------------------------------------------------------------------
    # Windows AI / Phi Silica
    # ---------------------------------------------------------------------
    # We do not attempt to import WinRT from Python here; instead we can
    # optionally ask the .NET bridge for info.
    bridge_proj = root / "tools" / "windows_ai_bridge" / "PhiSilicaBridge.csproj"
    dotnet_on_path = bool(shutil.which("dotnet"))

    windows_ai_info: dict[str, Any] = {
        "configured": sys.platform == "win32",
        "dotnet_on_path": dotnet_on_path,
        "bridge_project_exists": bridge_proj.exists(),
        "laf_env_present": _bool_env_present(
            "PHI_SILICA_LAF_FEATURE_ID",
            "PHI_SILICA_LAF_TOKEN",
            "PHI_SILICA_LAF_ATTESTATION",
        ),
        "available": None,
        "readyState": None,
    }

    if (
        active_probes
        and sys.platform == "win32"
        and dotnet_on_path
        and bridge_proj.exists()
    ):
        try:
            r = subprocess.run(
                [
                    "dotnet",
                    "run",
                    "--project",
                    str(bridge_proj),
                    "--",
                    "--info",
                ],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(bridge_proj.parent),
            )
            windows_ai_info["bridge_exit_code"] = r.returncode
            stdout = (r.stdout or "").strip()
            stderr = (r.stderr or "").strip()
            if stdout:
                try:
                    parsed = json.loads(stdout)
                    windows_ai_info["info"] = parsed
                    if isinstance(parsed, dict):
                        windows_ai_info["available"] = parsed.get("available")
                        windows_ai_info["readyState"] = parsed.get("readyState")
                        if parsed.get("error"):
                            windows_ai_info["error"] = str(parsed.get("error"))[:2000]
                except Exception:
                    windows_ai_info["info_raw"] = stdout[:2000]

            # If the bridge didn't provide a structured error, fall back to stderr.
            if r.returncode != 0 and stderr and not windows_ai_info.get("error"):
                windows_ai_info["error"] = stderr[:2000]
        except Exception as e:
            windows_ai_info["error"] = str(e)

    providers["windows_ai_phi_silica"] = windows_ai_info

    inv["providers"] = providers
    return inv


def format_inventory_summary(inv: dict[str, Any]) -> str:
    p = inv.get("providers", {}) if isinstance(inv, dict) else {}

    local = p.get("local_onnx", {})
    if isinstance(local, dict):
        local_installed = local.get("installed_model_keys", [])
    else:
        local_installed = []

    gh = p.get("github_models", {})
    gh_ok = bool(gh.get("can_attempt"))

    openai = p.get("openai", {})
    openai_count = (
        int(openai.get("model_count") or 0) if isinstance(openai, dict) else 0
    )

    gemini = p.get("gemini", {})
    gemini_count = (
        int(gemini.get("model_count") or 0) if isinstance(gemini, dict) else 0
    )

    ollama = p.get("ollama", {})
    ollama_reachable = ollama.get("reachable") if isinstance(ollama, dict) else None

    windows_ai = p.get("windows_ai_phi_silica", {})
    windows_available = windows_ai.get("available")
    windows_ready = windows_ai.get("readyState")

    windows_summary = "unknown"
    if windows_available is True:
        windows_summary = "available"
    elif windows_available is False:
        windows_summary = "unavailable"
    elif bool(windows_ai.get("configured")):
        windows_summary = "configured"

    return (
        "Capability inventory: "
        f"local_onnx(installed_keys={len(local_installed)}), "
        f"github_models(configured={gh_ok}), "
        f"openai(models={openai_count}), "
        f"gemini(models={gemini_count}), "
        f"ollama(reachable={ollama_reachable}), "
        f"windows_ai({windows_summary}{', ready=' + str(windows_ready) if windows_ready else ''})"
    )


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    active = "--active" in argv or "--active-probe" in argv
    inv = build_inventory(active_probes=active)
    logger.info(json.dumps(inv, indent=2, default=str))
    return 0 if inv.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
