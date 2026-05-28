"""Local provider model probing functions.

Probe functions for local/on-device providers: local ONNX (AI Gallery),
Windows AI (Phi Silica), Ollama, LM Studio, generic OpenAI-compatible
local servers, and AI Toolkit.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from tools.core.errors import ErrorCode, classify_error
from tools.llm.probe_config import (
    AI_GALLERY_CACHE_DIR,
    AITK_HOME_DIR,
    AITK_MODELINFO_FILE,
    AITK_MODELS_DIR,
    AITK_MODELS_TASK_TYPE,
    AITK_MS_SUBDIR,
    CACHE_BASE_DIR,
    DOTNET_CLI_ARG_PROJECT,
    ENV_LMSTUDIO_HOST,
    ENV_LOCAL_AI_API_BASE_URL,
    ENV_LOCAL_OPENAI_BASE_URL,
    ENV_OLLAMA_HOST,
    ENV_OPENAI_API_BASE,
    ENV_OPENAI_BASE_URL,
    ERROR_STANDARD_LENGTH,
    GH_CLI_OUTPUT_MODELS_LIMIT,
    LMSTUDIO_DEFAULT_HOST,
    LOCAL_SERVER_COMMON_PORTS,
    OLLAMA_API_TAGS_ENDPOINT,
    OLLAMA_DEFAULT_HOST,
    OLLAMA_MODEL_TAG_SUFFIX,
    PATH_SEPARATOR,
    PLATFORM_WINDOWS,
    PREFIX_AITK,
    PREFIX_AITK_ALT,
    PREFIX_LOCAL,
    PREFIX_OLLAMA,
    TIMEOUT_OLLAMA_HTTP,
    TIMEOUT_WINDOWS_AI_BRIDGE,
    WINDOWS_AI_BRIDGE_DIR,
    WINDOWS_AI_BRIDGE_PROJECT,
    WINDOWS_AI_CLI_ARG_INFO,
    ProbeResult,
)
from tools.llm.probe_providers_cloud import probe_openai_compatible_endpoint

# Type alias for optional logging callback
LogFn = Callable[[str], None] | None


def _noop_log(msg: str) -> None:
    """No-op logger used when no log callback is provided."""


def probe_local(model: str, log: LogFn = None) -> ProbeResult:
    """Probe a local ONNX model."""
    start = time.time()
    model_key = model.replace(PREFIX_LOCAL, "")

    try:
        # Check if model exists in AI Gallery cache
        ai_gallery = Path.home() / CACHE_BASE_DIR / AI_GALLERY_CACHE_DIR

        # Import LLMClient to get model paths
        from tools.llm.llm_client import LLMClient

        model_path = LLMClient.LOCAL_MODELS.get(model_key)
        if not model_path:
            return ProbeResult(
                model=model,
                provider="local",
                usable=False,
                error_code=ErrorCode.UNAVAILABLE_MODEL.value,
                error_message=f"Unknown local model key: {model_key}",
                probe_time=datetime.now().isoformat(),
                duration_ms=int((time.time() - start) * 1000),
            )

        # Check if the model directory exists
        top_dir = str(model_path).split(PATH_SEPARATOR)[0]
        if not (ai_gallery / top_dir).exists():
            return ProbeResult(
                model=model,
                provider="local",
                usable=False,
                error_code=ErrorCode.UNAVAILABLE_MODEL.value,
                error_message=f"Model not installed: {top_dir}",
                probe_time=datetime.now().isoformat(),
                duration_ms=int((time.time() - start) * 1000),
            )

        return ProbeResult(
            model=model,
            provider="local",
            usable=True,
            probe_time=datetime.now().isoformat(),
            duration_ms=int((time.time() - start) * 1000),
        )

    except Exception as e:
        code, retry = classify_error(str(e))
        return ProbeResult(
            model=model,
            provider="local",
            usable=False,
            error_code=code.value,
            error_message=str(e),
            should_retry=retry,
            probe_time=datetime.now().isoformat(),
            duration_ms=int((time.time() - start) * 1000),
        )


def probe_windows_ai(model: str, log: LogFn = None) -> ProbeResult:
    """Probe Windows AI (Phi Silica) via the .NET bridge --info."""
    start = time.time()

    if sys.platform != PLATFORM_WINDOWS:
        return ProbeResult(
            model=model,
            provider="windows_ai",
            usable=False,
            error_code=ErrorCode.UNAVAILABLE_MODEL.value,
            error_message="Windows AI is only available on Windows",
            probe_time=datetime.now().isoformat(),
            duration_ms=int((time.time() - start) * 1000),
        )

    import shutil

    if not shutil.which("dotnet"):
        return ProbeResult(
            model=model,
            provider="windows_ai",
            usable=False,
            error_code=ErrorCode.UNAVAILABLE_MODEL.value,
            error_message="dotnet not found on PATH (install .NET SDK)",
            probe_time=datetime.now().isoformat(),
            duration_ms=int((time.time() - start) * 1000),
        )

    bridge_proj = (
        Path(__file__).parent / WINDOWS_AI_BRIDGE_DIR / WINDOWS_AI_BRIDGE_PROJECT
    )
    if not bridge_proj.exists():
        return ProbeResult(
            model=model,
            provider="windows_ai",
            usable=False,
            error_code=ErrorCode.FILE_NOT_FOUND.value,
            error_message="Bridge project not found (tools/windows_ai_bridge/PhiSilicaBridge.csproj)",
            probe_time=datetime.now().isoformat(),
            duration_ms=int((time.time() - start) * 1000),
        )

    try:
        r = subprocess.run(
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

        stdout = (r.stdout or "").strip()
        stderr = (r.stderr or "").strip()
        duration_ms = int((time.time() - start) * 1000)

        info: dict[str, Any] = {}
        if stdout:
            try:
                info = json.loads(stdout)
            except Exception:
                info = {}

        available = bool(info.get("available")) if info else False
        if available:
            return ProbeResult(
                model=model,
                provider="windows_ai",
                usable=True,
                probe_time=datetime.now().isoformat(),
                duration_ms=duration_ms,
            )

        err_msg = None
        if info:
            err_msg = info.get("error")
        err_msg = err_msg or stderr or stdout or "Windows AI not available"

        # Add context for common Phi Silica failures.
        msg_lower = str(err_msg).lower()
        if "limited access feature" in msg_lower or "unauthorized" in msg_lower:
            err_msg = (
                f"{err_msg} | Phi Silica may require a Limited Access Feature (LAF) token "
                f"and/or package identity + systemAIModels capability. "
                f"See: https://learn.microsoft.com/windows/ai/apis/troubleshooting "
                f"(unlock: https://aka.ms/phi-silica-unlock)"
            )
        code, retry = classify_error(str(err_msg), r.returncode)
        return ProbeResult(
            model=model,
            provider="windows_ai",
            usable=False,
            error_code=code.value,
            error_message=str(err_msg)[:500],
            should_retry=retry,
            probe_time=datetime.now().isoformat(),
            duration_ms=duration_ms,
        )

    except subprocess.TimeoutExpired:
        return ProbeResult(
            model=model,
            provider="windows_ai",
            usable=False,
            error_code=ErrorCode.TIMEOUT.value,
            error_message="Bridge probe timed out after 60s",
            should_retry=True,
            probe_time=datetime.now().isoformat(),
            duration_ms=int((time.time() - start) * 1000),
        )
    except Exception as e:
        code, retry = classify_error(str(e))
        return ProbeResult(
            model=model,
            provider="windows_ai",
            usable=False,
            error_code=code.value,
            error_message=str(e),
            should_retry=retry,
            probe_time=datetime.now().isoformat(),
            duration_ms=int((time.time() - start) * 1000),
        )


def probe_ollama(model: str, log: LogFn = None) -> ProbeResult:
    """Probe an Ollama model."""
    import urllib.error
    import urllib.request

    start = time.time()
    model_id = model.replace(PREFIX_OLLAMA, "")

    ollama_host = os.getenv(ENV_OLLAMA_HOST, OLLAMA_DEFAULT_HOST)

    try:
        # Check if Ollama is running
        req = urllib.request.Request(
            f"{ollama_host}{OLLAMA_API_TAGS_ENDPOINT}",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_OLLAMA_HTTP) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name", "") for m in data.get("models", [])]

            # Check if specific model is available
            if (
                model_id
                and model_id not in models
                and f"{model_id}{OLLAMA_MODEL_TAG_SUFFIX}" not in models
            ):
                return ProbeResult(
                    model=model,
                    provider="ollama",
                    usable=False,
                    error_code=ErrorCode.UNAVAILABLE_MODEL.value,
                    error_message=f"Model '{model_id}' not found. Available: {', '.join(models[:GH_CLI_OUTPUT_MODELS_LIMIT])}",
                    probe_time=datetime.now().isoformat(),
                    duration_ms=int((time.time() - start) * 1000),
                )

            return ProbeResult(
                model=model,
                provider="ollama",
                usable=True,
                probe_time=datetime.now().isoformat(),
                duration_ms=int((time.time() - start) * 1000),
            )

    except urllib.error.URLError as e:
        return ProbeResult(
            model=model,
            provider="ollama",
            usable=False,
            error_code=ErrorCode.NETWORK_ERROR.value,
            error_message=f"Ollama not reachable at {ollama_host}: {e}",
            should_retry=True,
            probe_time=datetime.now().isoformat(),
            duration_ms=int((time.time() - start) * 1000),
        )
    except Exception as e:
        code, retry = classify_error(str(e))
        return ProbeResult(
            model=model,
            provider="ollama",
            usable=False,
            error_code=code.value,
            error_message=str(e),
            should_retry=retry,
            probe_time=datetime.now().isoformat(),
            duration_ms=int((time.time() - start) * 1000),
        )


def probe_lmstudio(model: str, log: LogFn = None) -> ProbeResult:
    """Probe LM Studio via its OpenAI-compatible API.

    LM Studio serves on http://localhost:1234 by default.
    Override with LMSTUDIO_HOST env var.
    """
    host = os.getenv(ENV_LMSTUDIO_HOST, LMSTUDIO_DEFAULT_HOST)
    return probe_openai_compatible_endpoint(host, model, "lmstudio")


def probe_local_api(model: str, log: LogFn = None) -> ProbeResult:
    """Probe a generic OpenAI-compatible local server.

    Checks OPENAI_BASE_URL, OPENAI_API_BASE, LOCAL_AI_API_BASE_URL,
    LOCAL_OPENAI_BASE_URL env vars for the endpoint. If none set, scans
    common local ports (1234, 5000, 5001, 8080, 8081).
    """
    import urllib.request

    _log = log or _noop_log

    base_url = (
        os.getenv(ENV_OPENAI_BASE_URL)
        or os.getenv(ENV_OPENAI_API_BASE)
        or os.getenv(ENV_LOCAL_AI_API_BASE_URL)
        or os.getenv(ENV_LOCAL_OPENAI_BASE_URL)
    )

    if base_url:
        return probe_openai_compatible_endpoint(base_url, model, "local_api")

    # No env var -- scan common ports
    start = time.time()
    for port in LOCAL_SERVER_COMMON_PORTS:
        try:
            url = f"http://localhost:{port}/v1/models"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=1) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("data"):
                    _log(f"Found local API server on port {port}")
                    return ProbeResult(
                        model=model,
                        provider="local_api",
                        usable=True,
                        probe_time=datetime.now().isoformat(),
                        duration_ms=int((time.time() - start) * 1000),
                    )
        except Exception:
            continue

    return ProbeResult(
        model=model,
        provider="local_api",
        usable=False,
        error_code=ErrorCode.NETWORK_ERROR.value,
        error_message=(
            "No local API server found. Set OPENAI_BASE_URL, LOCAL_AI_API_BASE_URL, "
            f"or start a server on ports {LOCAL_SERVER_COMMON_PORTS}"
        ),
        probe_time=datetime.now().isoformat(),
        duration_ms=int((time.time() - start) * 1000),
    )


def probe_ai_toolkit(model: str, log: LogFn = None) -> ProbeResult:
    """Probe an AI Toolkit local model.

    AI Toolkit stores downloaded models in ~/.aitk/models/ with metadata
    in ~/.aitk/models/foundry.modelinfo.json (these are FREE local ONNX models,
    NOT paid cloud Foundry models).

    Model format: aitk:<model-alias> or aitk:<full-model-name>
    Examples: aitk:phi-4-mini, aitk:qwen2.5-coder-7b
    """
    start = time.time()
    model_id = model.replace(PREFIX_AITK, "").replace(PREFIX_AITK_ALT, "")

    aitk_base = Path.home() / AITK_HOME_DIR
    models_dir = aitk_base / AITK_MODELS_DIR
    modelinfo_file = models_dir / AITK_MODELINFO_FILE

    # Check if AI Toolkit is installed
    if not aitk_base.exists():
        return ProbeResult(
            model=model,
            provider="ai_toolkit",
            usable=False,
            error_code=ErrorCode.FILE_NOT_FOUND.value,
            error_message="AI Toolkit not installed (~/.aitk not found)",
            probe_time=datetime.now().isoformat(),
            duration_ms=int((time.time() - start) * 1000),
        )

    # Check if models directory exists
    if not models_dir.exists():
        return ProbeResult(
            model=model,
            provider="ai_toolkit",
            usable=False,
            error_code=ErrorCode.FILE_NOT_FOUND.value,
            error_message="No AI Toolkit models downloaded (~/.aitk/models not found)",
            probe_time=datetime.now().isoformat(),
            duration_ms=int((time.time() - start) * 1000),
        )

    # Load model info to check available models
    available_aliases = []
    available_names = []

    if modelinfo_file.exists():
        try:
            info = json.loads(modelinfo_file.read_text(encoding="utf-8"))
            for m in info.get("models", []):
                if m.get("task") == AITK_MODELS_TASK_TYPE:  # Only chat models
                    alias = m.get("alias", "")
                    name = m.get("name", "")
                    if alias:
                        available_aliases.append(alias)
                    if name:
                        available_names.append(name)
        except Exception:
            pass

    # Check downloaded models in the models directory
    downloaded = []
    if models_dir.exists():
        for subdir in models_dir.iterdir():
            if subdir.is_dir() and subdir.name != AITK_MS_SUBDIR:
                downloaded.append(subdir.name)
        # Also check Microsoft subdir
        ms_dir = models_dir / AITK_MS_SUBDIR
        if ms_dir.exists():
            for subdir in ms_dir.iterdir():
                if subdir.is_dir():
                    downloaded.append(subdir.name)

    # Match model_id against available aliases, names, and downloaded folders
    model_lower = model_id.lower()

    # Direct match against aliases
    if model_lower in [a.lower() for a in available_aliases]:
        for d in downloaded:
            if model_lower in d.lower():
                return ProbeResult(
                    model=model,
                    provider="ai_toolkit",
                    usable=True,
                    probe_time=datetime.now().isoformat(),
                    duration_ms=int((time.time() - start) * 1000),
                )

    # Fuzzy match against downloaded models
    for d in downloaded:
        d_lower = d.lower()
        if model_lower in d_lower or d_lower.startswith(model_lower.replace("-", "")):
            return ProbeResult(
                model=model,
                provider="ai_toolkit",
                usable=True,
                probe_time=datetime.now().isoformat(),
                duration_ms=int((time.time() - start) * 1000),
            )

    # Model not found
    return ProbeResult(
        model=model,
        provider="ai_toolkit",
        usable=False,
        error_code=ErrorCode.UNAVAILABLE_MODEL.value,
        error_message=f"Model '{model_id}' not downloaded. Available: {', '.join(downloaded[:GH_CLI_OUTPUT_MODELS_LIMIT])}",
        probe_time=datetime.now().isoformat(),
        duration_ms=int((time.time() - start) * 1000),
    )
