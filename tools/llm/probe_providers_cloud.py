"""Cloud provider model probing functions.

Probe functions for remote/cloud providers: GitHub Models, OpenAI,
Google Gemini, Anthropic Claude, Azure Foundry, Azure OpenAI, and a
shared OpenAI-compatible endpoint helper.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime
from typing import Any, Callable

from tools.core.errors import ErrorCode, classify_error
from tools.llm.probe_config import (
    AZURE_SLOT_RANGE,
    ENV_ANTHROPIC_API_KEY,
    ENV_AZURE_FOUNDRY_API_KEY,
    ENV_AZURE_FOUNDRY_ENDPOINT_PREFIX,
    ENV_AZURE_OPENAI_API_KEY,
    ENV_AZURE_OPENAI_ENDPOINT,
    ENV_GEMINI_API_KEY,
    ENV_GH_TOKEN,
    ENV_GITHUB_TOKEN,
    ENV_GOOGLE_API_KEY,
    ENV_OPENAI_API_KEY,
    ERROR_STANDARD_LENGTH,
    GH_CLI_ARG_MAX_TOKENS,
    GH_CLI_PROBE_MAX_TOKENS,
    GH_CLI_PROBE_TEST_MESSAGE,
    PREFIX_AZURE_FOUNDRY,
    PREFIX_AZURE_OPENAI,
    PREFIX_GITHUB,
    PREFIX_GITHUB_ALT,
    PREFIX_OPENAI,
    TAB_SEPARATOR,
    TIMEOUT_CLOUD_HTTP,
    TIMEOUT_GH_AUTH,
    TIMEOUT_GH_MODELS_LIST,
    TIMEOUT_GH_MODELS_RUN,
    TIMEOUT_OLLAMA_HTTP,
    ProbeResult,
)

# Type alias for optional logging callback
LogFn = Callable[[str], None] | None


def probe_github(model: str, log: LogFn = None) -> ProbeResult:
    """Probe a GitHub Models model with a lightweight test."""
    start = time.time()
    model_id = model.replace(PREFIX_GITHUB, "").replace(PREFIX_GITHUB_ALT, "")

    # Check if gh CLI is available
    import shutil

    if not shutil.which("gh"):
        return ProbeResult(
            model=model,
            provider="github",
            usable=False,
            error_code=ErrorCode.UNAVAILABLE_MODEL.value,
            error_message="GitHub CLI (gh) not found on PATH",
            probe_time=datetime.now().isoformat(),
            duration_ms=int((time.time() - start) * 1000),
        )

    # Check for authentication (env var OR gh auth)
    gh_authenticated = bool(os.getenv(ENV_GITHUB_TOKEN) or os.getenv(ENV_GH_TOKEN))

    if not gh_authenticated:
        # Check if logged in via gh auth
        try:
            auth_check = subprocess.run(
                ["gh", "auth", "status"],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_GH_AUTH,
            )
            gh_authenticated = auth_check.returncode == 0
        except Exception:
            pass

    if not gh_authenticated:
        return ProbeResult(
            model=model,
            provider="github",
            usable=False,
            error_code=ErrorCode.PERMISSION_DENIED.value,
            error_message="Not authenticated (run: gh auth login or set GITHUB_TOKEN)",
            probe_time=datetime.now().isoformat(),
            duration_ms=int((time.time() - start) * 1000),
        )

    # If model_id doesn't have a slash, resolve from gh models list
    if "/" not in model_id:
        try:
            result = subprocess.run(
                ["gh", "models", "list"],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_GH_MODELS_LIST,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if line.strip():
                        parts = line.split(TAB_SEPARATOR)
                        if parts:
                            full_id = parts[0].strip()
                            if full_id.endswith(f"/{model_id}") or full_id == model_id:
                                model_id = full_id
                                break
        except Exception:
            pass  # Continue with original model_id

    try:
        # Do a minimal probe - just ask for a single token response
        result = subprocess.run(
            [
                "gh",
                "models",
                "run",
                model_id,
                GH_CLI_PROBE_TEST_MESSAGE,
                GH_CLI_ARG_MAX_TOKENS,
                GH_CLI_PROBE_MAX_TOKENS,
            ],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_GH_MODELS_RUN,
        )

        duration_ms = int((time.time() - start) * 1000)

        if result.returncode == 0:
            return ProbeResult(
                model=model,
                provider="github",
                usable=True,
                probe_time=datetime.now().isoformat(),
                duration_ms=duration_ms,
            )
        else:
            error_text = result.stderr or result.stdout
            code, retry = classify_error(error_text, result.returncode)
            return ProbeResult(
                model=model,
                provider="github",
                usable=False,
                error_code=code.value,
                error_message=error_text[:500],
                should_retry=retry,
                probe_time=datetime.now().isoformat(),
                duration_ms=duration_ms,
            )

    except subprocess.TimeoutExpired:
        return ProbeResult(
            model=model,
            provider="github",
            usable=False,
            error_code=ErrorCode.TIMEOUT.value,
            error_message="Probe timed out after 30s",
            should_retry=True,
            probe_time=datetime.now().isoformat(),
            duration_ms=int((time.time() - start) * 1000),
        )
    except Exception as e:
        code, retry = classify_error(str(e))
        return ProbeResult(
            model=model,
            provider="github",
            usable=False,
            error_code=code.value,
            error_message=str(e),
            should_retry=retry,
            probe_time=datetime.now().isoformat(),
            duration_ms=int((time.time() - start) * 1000),
        )


def probe_azure_foundry(model: str, log: LogFn = None) -> ProbeResult:
    """Probe an Azure Foundry model."""
    start = time.time()
    _ = model.replace(PREFIX_AZURE_FOUNDRY, "")

    # Check for API key
    api_key = os.getenv(ENV_AZURE_FOUNDRY_API_KEY)
    if not api_key:
        return ProbeResult(
            model=model,
            provider="azure_foundry",
            usable=False,
            error_code=ErrorCode.PERMISSION_DENIED.value,
            error_message="No AZURE_FOUNDRY_API_KEY environment variable",
            probe_time=datetime.now().isoformat(),
            duration_ms=int((time.time() - start) * 1000),
        )

    # Check for endpoint
    endpoint = None
    for k, v in os.environ.items():
        if k.startswith(ENV_AZURE_FOUNDRY_ENDPOINT_PREFIX) and v:
            endpoint = v
            break

    if not endpoint:
        return ProbeResult(
            model=model,
            provider="azure_foundry",
            usable=False,
            error_code=ErrorCode.INVALID_INPUT.value,
            error_message="No AZURE_FOUNDRY_ENDPOINT_* environment variable",
            probe_time=datetime.now().isoformat(),
            duration_ms=int((time.time() - start) * 1000),
        )

    # Assume configured = usable (actual probe would require API call)
    return ProbeResult(
        model=model,
        provider="azure_foundry",
        usable=True,
        probe_time=datetime.now().isoformat(),
        duration_ms=int((time.time() - start) * 1000),
    )


def probe_azure_openai(model: str, log: LogFn = None) -> ProbeResult:
    """Probe an Azure OpenAI model."""
    start = time.time()
    _ = model.replace(PREFIX_AZURE_OPENAI, "")

    # Check for endpoint and key (check slots 0-9)
    configured = False
    for i in range(AZURE_SLOT_RANGE):
        ep = os.getenv(f"{ENV_AZURE_OPENAI_ENDPOINT}_{i}")
        key = os.getenv(f"{ENV_AZURE_OPENAI_API_KEY}_{i}")
        if ep and key:
            configured = True
            break

    if not configured:
        # Also check default (non-numbered) env vars
        if os.getenv(ENV_AZURE_OPENAI_ENDPOINT) and os.getenv(ENV_AZURE_OPENAI_API_KEY):
            configured = True

    if not configured:
        return ProbeResult(
            model=model,
            provider="azure_openai",
            usable=False,
            error_code=ErrorCode.PERMISSION_DENIED.value,
            error_message="No AZURE_OPENAI_ENDPOINT/API_KEY environment variables",
            probe_time=datetime.now().isoformat(),
            duration_ms=int((time.time() - start) * 1000),
        )

    return ProbeResult(
        model=model,
        provider="azure_openai",
        usable=True,
        probe_time=datetime.now().isoformat(),
        duration_ms=int((time.time() - start) * 1000),
    )


def probe_openai(model: str, log: LogFn = None) -> ProbeResult:
    """Probe an OpenAI model."""
    start = time.time()
    _ = model.replace(PREFIX_OPENAI, "")

    api_key = os.getenv(ENV_OPENAI_API_KEY)
    if not api_key:
        return ProbeResult(
            model=model,
            provider="openai",
            usable=False,
            error_code=ErrorCode.PERMISSION_DENIED.value,
            error_message="No OPENAI_API_KEY environment variable",
            probe_time=datetime.now().isoformat(),
            duration_ms=int((time.time() - start) * 1000),
        )

    return ProbeResult(
        model=model,
        provider="openai",
        usable=True,
        probe_time=datetime.now().isoformat(),
        duration_ms=int((time.time() - start) * 1000),
    )


def probe_gemini(model: str, log: LogFn = None) -> ProbeResult:
    """Probe a Google Gemini model.

    Checks for GEMINI_API_KEY or GOOGLE_API_KEY, then optionally hits
    the Gemini models.list endpoint to confirm reachability.
    """
    start = time.time()

    api_key = os.getenv(ENV_GEMINI_API_KEY) or os.getenv(ENV_GOOGLE_API_KEY)
    if not api_key:
        return ProbeResult(
            model=model,
            provider="gemini",
            usable=False,
            error_code=ErrorCode.PERMISSION_DENIED.value,
            error_message="No GEMINI_API_KEY or GOOGLE_API_KEY environment variable",
            probe_time=datetime.now().isoformat(),
            duration_ms=int((time.time() - start) * 1000),
        )

    # Lightweight connectivity check -- list models endpoint
    import urllib.error
    import urllib.request

    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1"
        req = urllib.request.Request(
            url, headers={"Accept": "application/json", "x-goog-api-key": api_key}
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_CLOUD_HTTP) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("models"):
                return ProbeResult(
                    model=model,
                    provider="gemini",
                    usable=True,
                    probe_time=datetime.now().isoformat(),
                    duration_ms=int((time.time() - start) * 1000),
                )
            return ProbeResult(
                model=model,
                provider="gemini",
                usable=False,
                error_code=ErrorCode.UNAVAILABLE_MODEL.value,
                error_message="Gemini API returned no models",
                probe_time=datetime.now().isoformat(),
                duration_ms=int((time.time() - start) * 1000),
            )
    except urllib.error.HTTPError as e:
        code_val = (
            ErrorCode.PERMISSION_DENIED.value
            if e.code in (401, 403)
            else ErrorCode.NETWORK_ERROR.value
        )
        return ProbeResult(
            model=model,
            provider="gemini",
            usable=False,
            error_code=code_val,
            error_message=f"Gemini API HTTP {e.code}: {str(e.reason)[:200]}",
            should_retry=e.code not in (401, 403),
            probe_time=datetime.now().isoformat(),
            duration_ms=int((time.time() - start) * 1000),
        )
    except Exception as e:
        code, retry = classify_error(str(e))
        return ProbeResult(
            model=model,
            provider="gemini",
            usable=False,
            error_code=code.value,
            error_message=str(e)[:ERROR_STANDARD_LENGTH],
            should_retry=retry,
            probe_time=datetime.now().isoformat(),
            duration_ms=int((time.time() - start) * 1000),
        )


def probe_claude(model: str, log: LogFn = None) -> ProbeResult:
    """Probe an Anthropic Claude model.

    Checks for ANTHROPIC_API_KEY, then hits the Anthropic models
    endpoint to confirm the key is valid and reachable.
    """
    start = time.time()

    api_key = os.getenv(ENV_ANTHROPIC_API_KEY)
    if not api_key:
        return ProbeResult(
            model=model,
            provider="claude",
            usable=False,
            error_code=ErrorCode.PERMISSION_DENIED.value,
            error_message="No ANTHROPIC_API_KEY environment variable",
            probe_time=datetime.now().isoformat(),
            duration_ms=int((time.time() - start) * 1000),
        )

    # Lightweight connectivity check -- list models endpoint
    import urllib.error
    import urllib.request

    try:
        url = "https://api.anthropic.com/v1/models?limit=1"
        req = urllib.request.Request(
            url,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_CLOUD_HTTP) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("data"):
                return ProbeResult(
                    model=model,
                    provider="claude",
                    usable=True,
                    probe_time=datetime.now().isoformat(),
                    duration_ms=int((time.time() - start) * 1000),
                )
            # Key accepted but no models listed -- still usable
            return ProbeResult(
                model=model,
                provider="claude",
                usable=True,
                probe_time=datetime.now().isoformat(),
                duration_ms=int((time.time() - start) * 1000),
            )
    except urllib.error.HTTPError as e:
        code_val = (
            ErrorCode.PERMISSION_DENIED.value
            if e.code in (401, 403)
            else ErrorCode.NETWORK_ERROR.value
        )
        return ProbeResult(
            model=model,
            provider="claude",
            usable=False,
            error_code=code_val,
            error_message=f"Anthropic API HTTP {e.code}: {str(e.reason)[:200]}",
            should_retry=e.code not in (401, 403),
            probe_time=datetime.now().isoformat(),
            duration_ms=int((time.time() - start) * 1000),
        )
    except Exception as e:
        code, retry = classify_error(str(e))
        return ProbeResult(
            model=model,
            provider="claude",
            usable=False,
            error_code=code.value,
            error_message=str(e)[:ERROR_STANDARD_LENGTH],
            should_retry=retry,
            probe_time=datetime.now().isoformat(),
            duration_ms=int((time.time() - start) * 1000),
        )


def probe_openai_compatible_endpoint(
    base_url: str, model: str, provider: str
) -> ProbeResult:
    """Shared probe for any OpenAI-compatible server (LM Studio, LocalAI, etc.).

    Hits GET /v1/models to list available models.
    """
    import urllib.error
    import urllib.request

    start = time.time()
    base = base_url.rstrip("/")

    try:
        url = f"{base}/v1/models"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_OLLAMA_HTTP) as resp:
            raw = resp.read()
            # Verify the response is a valid OpenAI-compatible model list
            content_type = resp.headers.get("Content-Type", "")
            if "json" not in content_type and not raw.lstrip().startswith(b"{"):
                return ProbeResult(
                    model=model,
                    provider=provider,
                    usable=False,
                    error_code=ErrorCode.UNAVAILABLE_MODEL.value,
                    error_message=f"Unexpected response from {base}: not a JSON model list",
                    probe_time=datetime.now().isoformat(),
                    duration_ms=int((time.time() - start) * 1000),
                )
            return ProbeResult(
                model=model,
                provider=provider,
                usable=True,
                probe_time=datetime.now().isoformat(),
                duration_ms=int((time.time() - start) * 1000),
            )
    except urllib.error.URLError:
        return ProbeResult(
            model=model,
            provider=provider,
            usable=False,
            error_code=ErrorCode.NETWORK_ERROR.value,
            error_message=f"Server not reachable at {base}",
            should_retry=True,
            probe_time=datetime.now().isoformat(),
            duration_ms=int((time.time() - start) * 1000),
        )
    except Exception as e:
        code, retry = classify_error(str(e))
        return ProbeResult(
            model=model,
            provider=provider,
            usable=False,
            error_code=code.value,
            error_message=str(e)[:ERROR_STANDARD_LENGTH],
            should_retry=retry,
            probe_time=datetime.now().isoformat(),
            duration_ms=int((time.time() - start) * 1000),
        )
