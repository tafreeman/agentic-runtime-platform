"""Probe configuration, constants, types, cache management, and retry logic.

This module contains all the shared configuration and data types used by
the model probing subsystem: environment variable names, provider prefixes,
timeout values, the ``ProbeResult`` dataclass, persistent cache I/O, and
the ``with_retry`` decorator.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from tools.core.errors import ErrorCode, classify_error

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load .env so provider API keys are available via os.getenv().
# We search upward from this file to find the nearest .env, which covers both
# the repo root (d:\source\agentic-workflows\.env) and any nested package roots.
# ---------------------------------------------------------------------------


def _load_dotenv() -> None:
    """Load the nearest .env file into os.environ (idempotent)."""
    try:
        from dotenv import load_dotenv  # type: ignore[import-untyped]
    except ImportError:
        # python-dotenv not installed — fall back to manual parse
        _load_dotenv_manual()
        return

    # Walk up from this file's directory to find .env
    search = Path(__file__).resolve().parent
    for _ in range(10):
        candidate = search / ".env"
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            return
        if search.parent == search:
            break
        search = search.parent


def _load_dotenv_manual() -> None:
    """Minimal .env loader when python-dotenv is not installed."""
    search = Path(__file__).resolve().parent
    for _ in range(10):
        candidate = search / ".env"
        if candidate.is_file():
            for line in candidate.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if not key or key.startswith(" "):
                    continue
                # Only set if not already present (don't override real env)
                if key not in os.environ:
                    # Strip surrounding quotes (python-dotenv does this automatically)
                    if (
                        len(value) >= 2
                        and value[0] == value[-1]
                        and value[0] in ('"', "'")
                    ):
                        value = value[1:-1]
                    os.environ[key] = value
            return
        if search.parent == search:
            break
        search = search.parent


_load_dotenv()

# Re-export for consumers that previously imported from model_probe
__all__ = [
    "ErrorCode",
    "ProbeResult",
    "classify_error",
    "get_cache_dir",
    "get_cache_file",
    "load_cache",
    "save_cache",
    "with_retry",
]

# =============================================================================
# CONSTANTS - Path, Provider, Environment, URL, and Timeout Configuration
# =============================================================================

# Cache paths and configuration
CACHE_BASE_DIR = ".cache"
CACHE_APP_DIR = "prompts-eval"
CACHE_PROBES_DIR = "model-probes"
CACHE_FILE_NAME = "probe_cache.json"
CACHE_VERSION = "1.0.0"

# AI Gallery and AI Toolkit paths
AI_GALLERY_CACHE_DIR = "aigallery"
AITK_HOME_DIR = ".aitk"
AITK_MODELS_DIR = "models"
AITK_MODELINFO_FILE = "foundry.modelinfo.json"
AITK_MODELS_TASK_TYPE = "chat-completion"

# Model provider prefixes
PREFIX_LOCAL = "local:"
PREFIX_GITHUB = "gh:"
PREFIX_GITHUB_ALT = "github:"
PREFIX_OLLAMA = "ollama:"
PREFIX_OPENAI = "openai:"
PREFIX_GPT = "gpt"
PREFIX_AZURE_FOUNDRY = "azure-foundry:"
PREFIX_AZURE_OPENAI = "azure-openai:"
PREFIX_WINDOWS_AI = "windows-ai:"
PREFIX_AITK = "aitk:"
PREFIX_AITK_ALT = "ai-toolkit:"
PREFIX_GEMINI = "gemini:"
PREFIX_CLAUDE = "claude:"
PREFIX_LMSTUDIO = "lmstudio:"
PREFIX_LMSTUDIO_ALT = "lm-studio:"
PREFIX_LOCAL_API = "local-api:"

# Environment variable names
ENV_GITHUB_TOKEN = "GITHUB_TOKEN"
ENV_GH_TOKEN = "GH_TOKEN"
ENV_OLLAMA_HOST = "OLLAMA_HOST"
ENV_OLLAMA_API_KEY = "OLLAMA_API_KEY"
ENV_OPENAI_API_KEY = "OPENAI_API_KEY"
ENV_OPENAI_BASE_URL = "OPENAI_BASE_URL"
ENV_OPENAI_API_BASE = "OPENAI_API_BASE"
ENV_AZURE_FOUNDRY_API_KEY = "AZURE_FOUNDRY_API_KEY"
ENV_AZURE_FOUNDRY_ENDPOINT_PREFIX = "AZURE_FOUNDRY_ENDPOINT"
ENV_AZURE_OPENAI_ENDPOINT = "AZURE_OPENAI_ENDPOINT"
ENV_AZURE_OPENAI_API_KEY = "AZURE_OPENAI_API_KEY"
ENV_AZURE_OPENAI_DEPLOYMENT = "AZURE_OPENAI_DEPLOYMENT"
ENV_GEMINI_API_KEY = "GEMINI_API_KEY"
ENV_GOOGLE_API_KEY = "GOOGLE_API_KEY"
ENV_ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"
ENV_LMSTUDIO_HOST = "LMSTUDIO_HOST"
ENV_LM_STUDIO_HOST = "LM_STUDIO_HOST"  # alias used in some .env setups
ENV_LOCAL_AI_API_BASE_URL = "LOCAL_AI_API_BASE_URL"
ENV_LOCAL_OPENAI_BASE_URL = "LOCAL_OPENAI_BASE_URL"
ENV_NVIDIA_NIM_HOST = "NVIDIA_NIM_HOST"
ENV_NVIDIA_NIM_API_KEY = "NVIDIA_NIM_API_KEY"
NVIDIA_NIM_TOKEN_SLOT_RANGE = 10  # Check NVIDIA_NIM_API_KEY_0 .. NVIDIA_NIM_API_KEY_9
ENV_ANTHROPIC_BASE_URL = "ANTHROPIC_URI"  # custom base URL override for Anthropic

# Canonical base URL for real OpenAI API — always use this, never rely on env var override
OPENAI_CANONICAL_BASE_URL = "https://api.openai.com/v1"

# Cloud API hostnames to EXCLUDE from local/generic OpenAI-compatible probing.
# These have their own dedicated probe functions; picking them up in
# _probe_local_openai_compatible causes misidentification and double-counting.
CLOUD_API_HOSTS_SKIPLIST: frozenset[str] = frozenset({
    "api.openai.com",
    "integrate.api.nvidia.com",
    "api.anthropic.com",
    "models.inference.ai.azure.com",
    "github.models.ai",
    "generativelanguage.googleapis.com",
    "openai.azure.com",
})

# URLs and API endpoints
OLLAMA_DEFAULT_HOST = "http://localhost:11434"
OLLAMA_API_TAGS_ENDPOINT = "/api/tags"
LMSTUDIO_DEFAULT_HOST = "http://127.0.0.1:12340"
LOCAL_SERVER_COMMON_PORTS = [12340, 1234, 5000, 5001, 8080, 8081]

# Windows AI bridge
WINDOWS_AI_BRIDGE_DIR = "windows_ai_bridge"
WINDOWS_AI_BRIDGE_PROJECT = "PhiSilicaBridge.csproj"

# AI Toolkit model directories
AITK_MS_SUBDIR = "Microsoft"

# Timeout values (seconds)
TIMEOUT_GH_AUTH = 10
TIMEOUT_GH_MODELS_LIST = 30
TIMEOUT_GH_MODELS_RUN = 30
TIMEOUT_WINDOWS_AI_BRIDGE = 60
TIMEOUT_OLLAMA_HTTP = 3
TIMEOUT_CLOUD_HTTP = 10  # Remote cloud APIs (Gemini, Anthropic) — higher latency

# Cache key and string truncation lengths
CACHE_KEY_MD5_LENGTH = 12
GH_CLI_OUTPUT_MODELS_LIMIT = 5
ENDPOINT_TRUNCATION_LENGTH = 50
ERROR_BRIEF_LENGTH = 200
ERROR_STANDARD_LENGTH = 500
ERROR_DISPLAY_LENGTH = 60

# GitHub Models HTTP API
GITHUB_MODELS_API_BASE = "https://models.inference.ai.azure.com"
GITHUB_TOKEN_SLOT_RANGE = 10

# GitHub CLI and model probing
GH_CLI_PROBE_TEST_MESSAGE = "Hi"
GH_CLI_PROBE_MAX_TOKENS = "1"
GH_CLI_ARG_MAX_TOKENS = "--max-tokens"

# Windows AI and dotnet
DOTNET_CLI_ARG_PROJECT = "--project"
WINDOWS_AI_CLI_ARG_INFO = "--info"

# Path separators and delimiters
PATH_SEPARATOR = "/"
TAB_SEPARATOR = "\t"
OLLAMA_MODEL_TAG_SUFFIX = ":latest"

# AI Toolkit model name cleanup suffixes
AITK_SUFFIX_GENERIC_CPU = "-generic-cpu"
AITK_SUFFIX_GENERIC_GPU = "-generic-gpu"
AITK_SUFFIX_CPU = "-cpu"
AITK_SUFFIX_GPU = "-gpu"
AITK_TRAILING_CHARS = "0123456789-"

# Azure deployment slot range
AZURE_SLOT_RANGE = 10

# Exponential backoff configuration
BACKOFF_BASE = 2
JITTER_LOWER = 0.8
JITTER_RANGE = 0.4

# Windows AI specific constants
WINDOWS_AI_MODEL_ID = "windows-ai:phi-silica"

# Platform check
PLATFORM_WINDOWS = "win32"


# =============================================================================
# PROBE RESULT
# =============================================================================


@dataclass
class ProbeResult:
    """Result of probing a model's availability."""

    model: str
    provider: str
    usable: bool
    error_code: str | None = None
    error_message: str | None = None
    should_retry: bool = False
    probe_time: str = ""
    duration_ms: int = 0
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# =============================================================================
# CACHE MANAGEMENT
# =============================================================================


def get_cache_dir() -> Path:
    """Get the directory for probe cache files."""
    cache_dir = Path.home() / CACHE_BASE_DIR / CACHE_APP_DIR / CACHE_PROBES_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_cache_file() -> Path:
    """Get the main probe cache file."""
    return get_cache_dir() / CACHE_FILE_NAME


def load_cache() -> dict[str, Any]:
    """Load the probe cache from disk."""
    cache_file = get_cache_file()
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"version": CACHE_VERSION, "probes": {}, "last_updated": None}


def save_cache(cache: dict[str, Any]) -> None:
    """Save the probe cache to disk."""
    cache["last_updated"] = datetime.now().isoformat()
    cache_file = get_cache_file()
    cache_file.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def cache_key(model: str) -> str:
    """Generate cache key for a model."""
    return hashlib.md5(model.encode()).hexdigest()[:CACHE_KEY_MD5_LENGTH]


# =============================================================================
# RETRY DECORATOR
# =============================================================================


def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential: bool = True,
) -> Callable:
    """Decorator for retrying functions with exponential backoff.

    Only retries on transient errors (rate limit, timeout, network).

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay cap
        exponential: Use exponential backoff
    """

    def decorator(func: Callable) -> Callable:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error = None
            last_code = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    error_str = str(e)
                    code, should_retry = classify_error(error_str)
                    last_error = error_str
                    last_code = code

                    if not should_retry or attempt >= max_retries:
                        # Don't retry permanent errors or if we've exhausted retries
                        raise

                    # Calculate delay
                    if exponential:
                        delay = min(base_delay * (2**attempt), max_delay)
                    else:
                        delay = base_delay

                    # Add jitter (+-20%)
                    import random

                    delay = delay * (JITTER_LOWER + random.random() * JITTER_RANGE)

                    logger.debug(
                        f"[Retry] {code.value}: attempt {attempt + 1}/{max_retries}, waiting {delay:.1f}s"
                    )
                    time.sleep(delay)

            # Should not reach here, but just in case
            raise RuntimeError(f"Exhausted retries: {last_code} - {last_error}")

        return wrapper

    return decorator
