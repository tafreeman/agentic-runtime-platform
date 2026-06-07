"""Provider adapter functions used by ``tools.llm.llm_client``."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

ONNX_GLOB_PATTERN = "*.onnx"


def call_ollama(
    model_name: str,
    prompt: str,
    system_instruction: str | None,
) -> str:
    """Call a local Ollama server using its REST API."""
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    model = model_name.split(":", 1)[1] if ":" in model_name else "llama3"

    full_prompt = prompt
    if system_instruction:
        full_prompt = f"System: {system_instruction}\n\nUser: {prompt}"

    payload = json.dumps(
        {
            "model": model,
            "prompt": full_prompt,
            "stream": False,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        f"{host}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    timeout_s = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("response", "")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8") if exc.fp else str(exc)
        raise RuntimeError(f"Ollama API error ({exc.code}): {error_body}")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama connection error: {exc}")


def call_azure_openai(
    model_name: str,
    prompt: str,
    system_instruction: str | None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> str:
    """Call Azure OpenAI Service via the OpenAI Python SDK."""
    parts = model_name.split(":")
    slot: int | None = None
    deployment: str | None = None

    if len(parts) == 2:
        deployment = parts[1]
    elif len(parts) >= 3:
        try:
            slot = int(parts[1])
            deployment = ":".join(parts[2:])
        except ValueError:
            deployment = ":".join(parts[1:])

    if not deployment:
        raise ValueError(
            "Azure OpenAI deployment name not provided (azure-openai:<deployment>)"
        )

    if slot is not None:
        endpoint = os.getenv(f"AZURE_OPENAI_ENDPOINT_{slot}")
        api_key = os.getenv(f"AZURE_OPENAI_API_KEY_{slot}")
    else:
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT") or os.getenv(
            "AZURE_OPENAI_ENDPOINT_0"
        )
        api_key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv(
            "AZURE_OPENAI_API_KEY_0"
        )

    if not endpoint:
        raise ValueError("AZURE_OPENAI_ENDPOINT(_<n>) environment variable not set")
    if not api_key:
        raise ValueError("AZURE_OPENAI_API_KEY(_<n>) environment variable not set")

    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

    try:
        from openai import AzureOpenAI
    except ImportError:
        raise ImportError("openai package not installed. Run: pip install openai")

    client = AzureOpenAI(
        api_key=api_key,
        azure_endpoint=endpoint,
        api_version=api_version,
    )

    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(
        model=deployment,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content


def _dir_has_onnx(path: Path) -> bool:
    """Return True if the directory contains at least one ONNX file."""
    if not path.is_dir():
        return False
    try:
        return any(path.glob(ONNX_GLOB_PATTERN))
    except OSError:
        return False


def _collect_onnx_candidates(top_dir: Path) -> list[Path]:
    """Recursively collect subdirectories of ``top_dir`` that contain ONNX files."""
    candidates: list[Path] = []
    for subdir in top_dir.rglob("*"):
        if not subdir.is_dir():
            continue
        try:
            if any(subdir.glob(ONNX_GLOB_PATTERN)):
                candidates.append(subdir)
        except OSError:
            continue
    return candidates


def _pick_preferred_candidate(
    candidates: list[Path], model_key: str, spec_norm: str
) -> Path:
    """Choose the best ONNX candidate by CPU/GPU hint, then spec suffix, else first."""
    candidates.sort(key=lambda path: str(path).lower())
    variant_hint = model_key.lower()
    preferred_tokens: list[str] = []
    if any(token in variant_hint for token in ["gpu", "dml", "directml"]):
        preferred_tokens = ["directml", "gpu"]
    elif "cpu" in variant_hint:
        preferred_tokens = ["cpu"]

    for token in preferred_tokens:
        for candidate in candidates:
            if token in str(candidate).lower():
                return candidate

    if "/" in spec_norm:
        wanted_suffix = spec_norm.split("/", 1)[1].lower()
        for candidate in candidates:
            if str(candidate).replace("\\", "/").lower().endswith(wanted_suffix):
                return candidate

    return candidates[0]


def resolve_local_model_path(
    model_key: str,
    *,
    local_models: dict[str, str],
) -> Path | None:
    """Resolve local model key to the best ONNX directory."""
    spec = local_models.get(model_key.lower())
    if not spec:
        return None

    ai_gallery_root = Path.home() / ".cache" / "aigallery"
    explicit_path = Path(spec).expanduser()
    if explicit_path.is_absolute():
        return explicit_path if _dir_has_onnx(explicit_path) else None

    spec_norm = str(spec).replace("\\", "/").strip("/")
    direct_path = ai_gallery_root / spec_norm
    if _dir_has_onnx(direct_path):
        return direct_path

    top_dir_name = spec_norm.split("/", 1)[0]
    top_dir = ai_gallery_root / top_dir_name
    if not top_dir.exists():
        return None

    candidates = _collect_onnx_candidates(top_dir)
    if not candidates:
        return None

    return _pick_preferred_candidate(candidates, model_key, spec_norm)


def call_local(
    model_name: str,
    prompt: str,
    system_instruction: str | None,
    *,
    local_models: dict[str, str],
    resolve_model_path: Callable[[str], Path | None],
    temperature: float = 0.7,
    max_tokens: int = 2000,
) -> str:
    """Call a local ONNX model using ``tools.llm.local_model.LocalModel``."""
    try:
        from tools.llm.local_model import LocalModel
    except ImportError as exc:
        raise RuntimeError(
            "local_model.py not found or onnxruntime-genai not installed"
        ) from exc

    model_key = model_name.split(":", 1)[1] if ":" in model_name else "phi4mini"
    if model_key.lower() not in local_models:
        raise RuntimeError(f"Unknown local model key: {model_key!r}")

    model_path_obj = resolve_model_path(model_key)
    model_path = str(model_path_obj) if model_path_obj else None

    if model_path_obj is not None:
        _verify_local_model_weights(model_path_obj)

    try:
        from tools.llm.model_locks import create_model_lock

        create_model_lock(model_key)
    except Exception:
        pass

    try:
        local_model = LocalModel(
            model_path=model_path, model_key=model_key, verbose=False
        )
        full_prompt = prompt
        if system_instruction:
            full_prompt = f"System: {system_instruction}\n\nUser: {prompt}"
        return local_model.generate(
            full_prompt, max_tokens=max_tokens, temperature=temperature
        )
    except Exception as exc:
        raise RuntimeError(f"Local model inference failed: {exc}") from exc


def _verify_local_model_weights(model_path: Path) -> None:
    """Run optional local model weight verification before loading weights."""
    try:
        from agentic_v2.models.weight_integrity import (
            ModelWeightVerificationError,
            verify_model_weights,
        )
    except Exception as exc:
        if os.getenv("AGENTIC_STRICT_MODEL_VERIFY", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
            "on",
        }:
            raise RuntimeError(
                f"Local model weight verifier unavailable in strict mode: {exc}"
            ) from exc
        logger.debug("Local model weight verifier unavailable: %s", exc)
        return

    try:
        result = verify_model_weights(model_path)
    except ModelWeightVerificationError as exc:
        raise RuntimeError(f"Local model weight verification failed: {exc}") from exc
    except Exception as exc:
        logger.warning("Local model weight verification skipped: %s", exc)
        return

    for warning in result.warnings:
        logger.warning("Local model weight verification warning: %s", warning)


def call_windows_ai(
    prompt: str,
    system_instruction: str | None,
    temperature: float = 0.7,
    max_tokens: int = 2000,
) -> str:
    """Call Windows AI APIs (Phi Silica via Windows Copilot Runtime)."""
    try:
        from windows_ai import WindowsAIModel

        model = WindowsAIModel(verbose=False)
        return model.generate(
            prompt,
            system_instruction=system_instruction,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except ImportError as exc:
        raise RuntimeError(
            "Windows AI integration not available. "
            "Requires Windows 11 with NPU (Copilot+ PC), "
            "Windows App SDK 1.7+, and pip install winrt-runtime"
        ) from exc


_GH_MODEL_MAP = {
    "gpt-4o-mini": "openai/gpt-4o-mini",
    "gpt-4o": "openai/gpt-4o",
    "gpt-4.1": "openai/gpt-4.1",
    "gpt-4.1-mini": "openai/gpt-4.1-mini",
    "gpt-5": "openai/gpt-5",
    "gpt-5-mini": "openai/gpt-5-mini",
    "llama-3.3-70b": "meta/llama-3.3-70b-instruct",
    "llama-4-scout": "meta/llama-4-scout-17b-16e-instruct",
    "llama-4-maverick": "meta/llama-4-maverick-17b-128e-instruct-fp8",
    "mistral-small": "mistral-ai/mistral-small-2503",
    "mistral-medium": "mistral-ai/mistral-medium-2505",
    "codestral": "mistral-ai/codestral-2501",
    "deepseek-r1": "deepseek/deepseek-r1",
    "deepseek-v3": "deepseek/deepseek-v3-0324",
    "phi-4": "microsoft/phi-4",
    "phi-4-reasoning": "microsoft/phi-4-reasoning",
    "grok-3": "xai/grok-3",
    "grok-3-mini": "xai/grok-3-mini",
}

_GH_RATE_LIMIT_MARKERS = ["rate limit", "too many requests", "429", "quota"]


def _gh_int_env(name: str, default: int) -> int:
    """Read a positive integer env var, falling back to ``default``."""
    try:
        value = int((os.getenv(name) or "").strip() or str(default))
        return max(1, value)
    except Exception:
        return default


def _classify_gh_run_failure(
    result: Any,
    full_model: str,
    attempt: int,
    max_retries: int,
    rate_limit_strategy: str,
    base_delay: int,
) -> str | None:
    """Classify a non-zero gh run result.

    Returns a final error string, or ``None`` to signal the caller should
    wait and retry the request.
    """
    import time

    error_msg = result.stderr.lower()
    if any(marker in error_msg for marker in _GH_RATE_LIMIT_MARKERS):
        if rate_limit_strategy == "wait" and attempt < max_retries - 1:
            wait_time = min(base_delay * (2**attempt), 60)
            logger.info(
                f"[gh] Rate limited, waiting {wait_time}s (attempt {attempt + 1}/{max_retries})..."
            )
            time.sleep(wait_time)
            return None
        return f"gh models error: Rate limited after {attempt + 1} attempt(s)"

    if "no_access" in error_msg or "no access" in error_msg:
        return f"gh models error: No access to model {full_model}"

    return f"gh models error: {result.stderr}"


def _attempt_gh_run(
    full_model: str,
    full_prompt: str,
    clean_env: dict[str, str],
    attempt: int,
    max_retries: int,
    rate_limit_strategy: str,
    base_delay: int,
) -> str | None:
    """Run a single gh models attempt.

    Returns the final output/error string, or ``None`` to signal a retry.
    """
    import subprocess
    import time

    try:
        result = subprocess.run(
            ["gh", "models", "run", full_model],
            input=full_prompt,
            capture_output=True,
            text=True,
            timeout=300,
            encoding="utf-8",
            errors="replace",
            env=clean_env,
        )
        if result.returncode == 0:
            return result.stdout

        return _classify_gh_run_failure(
            result,
            full_model,
            attempt,
            max_retries,
            rate_limit_strategy,
            base_delay,
        )

    except FileNotFoundError:
        return "gh models error: gh CLI not found. Install with: winget install GitHub.cli"
    except subprocess.TimeoutExpired:
        if attempt < max_retries - 1:
            logger.info(
                f"[gh] Timeout, retrying (attempt {attempt + 1}/{max_retries})..."
            )
            time.sleep(base_delay)
            return None
        return "gh models error: request timed out"


def call_github_models(
    model_name: str,
    prompt: str,
    system_instruction: str | None,
) -> str:
    """Call GitHub Models via gh CLI with rate limit handling."""
    model = (
        model_name.split(":", 1)[1]
        if ":" in model_name
        else "meta/llama-3.3-70b-instruct"
    )
    full_model = _GH_MODEL_MAP.get(model, model)

    if system_instruction:
        full_prompt = f"System: {system_instruction}\n\nUser: {prompt}"
    else:
        full_prompt = prompt

    rate_limit_strategy = (
        (os.getenv("PROMPTS_GH_RATE_LIMIT_STRATEGY") or "fallback").strip().lower()
    )
    max_retries = _gh_int_env("PROMPTS_GH_MAX_RETRIES", 1)
    base_delay = _gh_int_env("PROMPTS_GH_BASE_DELAY_SECONDS", 2)

    clean_env = {
        key: value for key, value in os.environ.items() if key != "GITHUB_TOKEN"
    }
    for attempt in range(max_retries):
        outcome = _attempt_gh_run(
            full_model,
            full_prompt,
            clean_env,
            attempt,
            max_retries,
            rate_limit_strategy,
            base_delay,
        )
        if outcome is not None:
            return outcome

    return "gh models error: max retries exceeded"


def call_azure_foundry(
    model_name: str,
    prompt: str,
    system_instruction: str | None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> str:
    """Call Azure Foundry API using Azure OpenAI-compatible REST endpoint."""
    api_key = os.getenv("AZURE_FOUNDRY_API_KEY")
    if not api_key:
        raise ValueError("AZURE_FOUNDRY_API_KEY environment variable not set")

    model_part = model_name.split(":", 1)[1] if ":" in model_name else "1"
    if model_part in ("1", "phi4mini", "phi4", "phi"):
        endpoint = os.getenv("AZURE_FOUNDRY_ENDPOINT_1")
    elif model_part in ("2", "mistral"):
        endpoint = os.getenv("AZURE_FOUNDRY_ENDPOINT_2")
    else:
        endpoint = os.getenv(f"AZURE_FOUNDRY_ENDPOINT_{model_part}")
        if not endpoint:
            endpoint = os.getenv("AZURE_FOUNDRY_ENDPOINT_1")

    if not endpoint:
        raise ValueError(f"Azure Foundry endpoint not configured for '{model_part}'")

    if not endpoint.endswith("/chat/completions"):
        endpoint = endpoint.rstrip("/") + "/chat/completions"
    if "api-version" not in endpoint:
        endpoint += "?api-version=2024-02-15-preview"

    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})

    payload = json.dumps(
        {"messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    ).encode("utf-8")

    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json", "api-key": api_key},
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8") if exc.fp else str(exc)
        raise RuntimeError(f"Azure Foundry API error ({exc.code}): {error_body}")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Azure Foundry connection error: {exc}")


def call_gemini(
    model_name: str,
    prompt: str,
    system_instruction: str | None,
) -> str:
    try:
        import google.generativeai as genai

        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError(
                "GOOGLE_API_KEY or GEMINI_API_KEY environment variable not set"
            )

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)

        full_prompt = prompt
        if system_instruction:
            full_prompt = f"System Instruction: {system_instruction}\n\n{prompt}"

        response = model.generate_content(full_prompt)
        return response.text
    except ImportError:
        raise ImportError(
            "google-generativeai package not installed. Run: pip install google-generativeai"
        )


def call_claude(
    model_name: str,
    prompt: str,
    system_instruction: str | None,
) -> str:
    try:
        from anthropic import Anthropic

        api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY or CLAUDE_API_KEY environment variable not set"
            )

        client = Anthropic(api_key=api_key)
        messages = [{"role": "user", "content": prompt}]
        kwargs = {"model": model_name, "max_tokens": 4096, "messages": messages}
        if system_instruction:
            kwargs["system"] = system_instruction

        response = client.messages.create(**kwargs)
        return response.content[0].text
    except ImportError:
        raise ImportError("anthropic package not installed. Run: pip install anthropic")


def call_openai(
    model_name: str,
    prompt: str,
    system_instruction: str | None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> str:
    try:
        from openai import OpenAI

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")

        client = OpenAI(api_key=api_key)
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content
    except ImportError:
        raise ImportError("openai package not installed. Run: pip install openai")
