"""Multi-provider LLM client with automatic provider dispatch.

This module provides ``LLMClient``, a static-method-based facade that routes
text-generation requests to the correct backend based on a model name prefix
(e.g. ``local:``, ``gh:``, ``ollama:``, ``gemini:``).  Response caching and
a remote-provider gate (``PROMPTEVAL_ALLOW_REMOTE``) are applied transparently.

Typical usage::

    from tools.llm.llm_client import LLMClient

    text = LLMClient.generate_text("gh:gpt-4o-mini", "Explain quicksort.")

Raises:
    LLMClientError: On any provider failure (wraps the original exception).
"""

from __future__ import annotations

import logging
import os
import sys
from typing import TYPE_CHECKING

from tools.llm import provider_adapters
from tools.llm.local_models import LOCAL_MODELS

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# =============================================================================
# WINDOWS CONSOLE ENCODING FIX - Use shared module
# =============================================================================
try:
    from tools.core._encoding import setup_encoding

    setup_encoding()
except ImportError:
    # Fallback if running as standalone script
    import io

    if sys.platform == "win32":
        os.environ["PYTHONIOENCODING"] = "utf-8"
        try:
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding="utf-8", errors="replace"
            )
            sys.stderr = io.TextIOWrapper(
                sys.stderr.buffer, encoding="utf-8", errors="replace"
            )
        except (OSError, AttributeError):
            pass


class LLMClientError(RuntimeError):
    """Raised when an LLM provider call fails.

    Wraps the underlying exception so callers can inspect both the
    high-level context and the original cause.

    Attributes:
        model: The model identifier that was requested (e.g. ``"gh:gpt-4o"``).
        original_error: The upstream exception, if any.
    """

    def __init__(
        self, model: str, message: str, original_error: Exception | None = None
    ):
        super().__init__(f"[{model}] {message}")
        self.model = model
        self.original_error = original_error


class LLMClient:
    """Unified, stateless facade for multi-provider LLM text generation.

    All public methods are ``@staticmethod``; no instance state is required.
    The ``generate_text`` method inspects the ``model_name`` prefix to select
    the correct provider adapter, applies optional response caching, and
    enforces a remote-provider gate controlled by the
    ``PROMPTEVAL_ALLOW_REMOTE`` environment variable.

    Supported provider prefixes:
        local:*
            Local ONNX models (phi4mini, phi3, mistral-7b, etc.).
        ollama:*
            Local Ollama server via its REST API.
        windows-ai:*
            Windows Copilot Runtime / Phi Silica (NPU-accelerated).
        azure-foundry:*
            Azure AI Foundry endpoint.
        azure-openai:*
            Azure OpenAI Service (deployment-based).
        gh:*
            GitHub Models API.
        openai:*
            OpenAI hosted API (explicit prefix).
        gemini:*
            Google Gemini API (explicit prefix).
        claude:*
            Anthropic Claude API (explicit prefix).
        gemini / claude / gpt (bare substring)
            Inferred provider from model name substring.

    Attributes:
        LOCAL_MODELS: Mapping of local model keys to their ONNX paths.
    """

    LOCAL_MODELS = dict(LOCAL_MODELS)

    @staticmethod
    def _pick_preferred_model(
        available: list[str],
        preferred: list[str],
    ) -> str | None:
        """Pick the first model in preferred that is present in available.

        Matching is exact; callers should normalize names if needed.
        """
        available_set = set(available)
        for m in preferred:
            if m in available_set:
                return m
        return None

    @staticmethod
    def list_openai_models() -> list[str]:
        """Return model IDs available to the current OPENAI_API_KEY.

        Uses the OpenAI API. Returns an empty list if not configured.
        """
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return []

        try:
            from openai import OpenAI
        except ImportError:
            return []

        client = OpenAI(api_key=api_key, base_url="https://api.openai.com/v1")
        try:
            # openai>=1.x returns an object with .data
            models = client.models.list()
            ids: list[str] = []
            for m in models.data:
                mid = getattr(m, "id", None)
                if mid:
                    ids.append(mid)
            return sorted(ids)
        except Exception:
            return []

    @staticmethod
    def list_gemini_models() -> list[str]:
        """Return the list of Gemini model IDs usable for generateContent.

        Uses google-generativeai's model listing when available. Returns
        an empty list if not configured.
        """
        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not api_key:
            return []

        try:
            import google.generativeai as genai
        except ImportError:
            return []

        genai.configure(api_key=api_key)
        models_out: list[str] = []
        try:
            for m in genai.list_models():
                name = getattr(m, "name", None)
                if not name:
                    continue
                # names commonly come back like "models/gemini-1.5-pro"
                model_id = name.split("/", 1)[1] if "/" in name else name
                methods = getattr(m, "supported_generation_methods", None) or []
                # Only include models that can generate content.
                if "generateContent" in methods or "generate_content" in methods:
                    models_out.append(model_id)
        except Exception:
            return []

        return sorted(set(models_out))

    @staticmethod
    def _enforce_remote_gate(model_name: str) -> None:
        """Raise unless the model's provider is allowed by default or remotes enabled.

        Safe-by-default: only allow local + GitHub Models unless explicitly
        enabled via PROMPTEVAL_ALLOW_REMOTE. GitHub Models are remote but
        explicitly allowed here.
        """

        def _remote_allowed() -> bool:
            v = (os.getenv("PROMPTEVAL_ALLOW_REMOTE") or "").strip().lower()
            return v in {"1", "true", "yes", "y", "on"}

        lower = (model_name or "").lower()
        default_allowed = (
            "local:",
            "gh:",
            "windows-ai:",
            "ollama:",
            "aitk:",
            "ai-toolkit:",
        )
        if lower.startswith(default_allowed):
            return

        remote_patterns = (
            "azure-foundry:",
            "azure-openai:",
            "openai:",
            "gemini:",
            "claude:",
        )
        if (
            lower.startswith(remote_patterns)
            or ("gpt" in lower)
            or ("gemini" in lower)
            or ("claude" in lower)
        ) and not _remote_allowed():
            raise RuntimeError(
                f"Remote provider disabled by default: '{model_name}'. "
                "Set PROMPTEVAL_ALLOW_REMOTE=1 to enable remote providers."
            )

    @staticmethod
    def _dispatch_provider(
        model_name: str,
        prompt: str,
        system_instruction: str | None,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Route the request to the provider adapter matching the model prefix."""
        lower = model_name.lower()
        if lower.startswith("local:"):
            return LLMClient._call_local(
                model_name, prompt, system_instruction, temperature, max_tokens
            )
        if lower.startswith("ollama:"):
            return LLMClient._call_ollama(model_name, prompt, system_instruction)
        if lower.startswith("windows-ai:"):
            return LLMClient._call_windows_ai(
                model_name, prompt, system_instruction, temperature, max_tokens
            )
        if lower.startswith("azure-foundry:"):
            return LLMClient._call_azure_foundry(
                model_name, prompt, system_instruction, temperature, max_tokens
            )
        if lower.startswith("azure-openai:"):
            return LLMClient._call_azure_openai(
                model_name, prompt, system_instruction, temperature, max_tokens
            )
        if lower.startswith("gh:"):
            return LLMClient._call_github_models(
                model_name, prompt, system_instruction
            )
        if lower.startswith("openai:"):
            # Explicit prefix for OpenAI hosted models
            model_id = model_name.split(":", 1)[1]
            return LLMClient._call_openai(
                model_id, prompt, system_instruction, temperature, max_tokens
            )
        if lower.startswith("gemini:"):
            model_id = model_name.split(":", 1)[1]
            return LLMClient._call_gemini(model_id, prompt, system_instruction)
        if lower.startswith("claude:"):
            model_id = model_name.split(":", 1)[1]
            return LLMClient._call_claude(model_id, prompt, system_instruction)
        if "gemini" in lower:
            return LLMClient._call_gemini(model_name, prompt, system_instruction)
        if "claude" in lower:
            return LLMClient._call_claude(model_name, prompt, system_instruction)
        if "gpt" in lower:
            return LLMClient._call_openai(
                model_name, prompt, system_instruction, temperature, max_tokens
            )
        raise LLMClientError(
            model_name,
            "Unknown model. Use local:, ollama:, windows-ai:, azure-foundry:, "
            "azure-openai:, gh:, openai:, gemini:, claude:, or a plain model name containing gemini/claude/gpt",
        )

    @staticmethod
    def generate_text(
        model_name: str,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """Dispatches the request to the appropriate provider based on model_name.

        Args:
            model_name: Model identifier (e.g., "local:phi4mini", "azure-foundry:phi4mini")
            prompt: The user prompt
            system_instruction: Optional system prompt
            temperature: Sampling temperature (0.0-2.0, default: 0.7)
            max_tokens: Maximum tokens to generate (default: 4096)

        Supported model name patterns:
          - local:* -> Local ONNX models (e.g., "local:phi4mini", "local:mistral-7b")
          - windows-ai:* -> Windows AI APIs / Phi Silica (NPU-accelerated, local)
          - azure-foundry:* -> Azure Foundry API (e.g., "azure-foundry:phi4mini")
          - gh:* -> GitHub Models (e.g., "gh:gpt-4o-mini", "gh:llama-3.3-70b")
          - gemini* -> Google Gemini API
          - claude* -> Anthropic Claude API
          - gpt* -> OpenAI API

        Caching:
          - Set PROMPTS_CACHE_ENABLED=0 to disable response caching
          - Use tools/cache.py to manage cache manually
        """
        # Check cache first (if enabled)
        # Check env var at runtime to allow tests to disable caching
        cache_enabled = os.environ.get("PROMPTS_CACHE_ENABLED", "1").lower() in (
            "1",
            "true",
            "yes",
        )
        cache_response_func = None
        try:
            from cache import cache_response as cache_response_func
            from cache import get_cached_response

            if cache_enabled:
                cached = get_cached_response(
                    model_name,
                    prompt,
                    system_instruction,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                if cached is not None:
                    logger.debug(f"[{model_name}] Cache hit")
                    return cached
        except ImportError:
            cache_enabled = False

        LLMClient._enforce_remote_gate(model_name)

        logger.debug(f"[{model_name}] Processing request...")

        try:
            result = LLMClient._dispatch_provider(
                model_name, prompt, system_instruction, temperature, max_tokens
            )

            # Cache successful response
            if result and cache_enabled and cache_response_func:
                try:
                    cache_response_func(
                        model_name,
                        prompt,
                        result,
                        system_instruction,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                except Exception:
                    pass  # Don't fail on cache errors

            return result
        except LLMClientError:
            raise
        except Exception as e:
            raise LLMClientError(model_name, str(e), original_error=e) from e

    @staticmethod
    def _call_ollama(
        model_name: str, prompt: str, system_instruction: str | None
    ) -> str:
        """Call a local Ollama server using its REST API."""
        return provider_adapters.call_ollama(model_name, prompt, system_instruction)

    @staticmethod
    def _call_azure_openai(
        model_name: str,
        prompt: str,
        system_instruction: str | None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """Call Azure OpenAI Service via provider adapter."""
        return provider_adapters.call_azure_openai(
            model_name,
            prompt,
            system_instruction,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    @staticmethod
    def _call_local(
        model_name: str,
        prompt: str,
        system_instruction: str | None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> str:
        """Call a local ONNX model via provider adapter."""
        try:
            return provider_adapters.call_local(
                model_name,
                prompt,
                system_instruction,
                local_models=LLMClient.LOCAL_MODELS,
                resolve_model_path=LLMClient._resolve_local_model_path,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except RuntimeError as exc:
            raise LLMClientError(model_name, str(exc), original_error=exc) from exc

    @staticmethod
    def _resolve_local_model_path(model_key: str) -> Path | None:
        """Resolve local model key to the best ONNX directory."""
        return provider_adapters.resolve_local_model_path(
            model_key,
            local_models=LLMClient.LOCAL_MODELS,
        )

    @staticmethod
    def _call_windows_ai(
        model_name: str,
        prompt: str,
        system_instruction: str | None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> str:
        """Call Windows AI APIs (Phi Silica via Windows Copilot Runtime)."""
        try:
            return provider_adapters.call_windows_ai(
                prompt,
                system_instruction,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            raise LLMClientError("windows-ai", str(exc), original_error=exc) from exc

    @staticmethod
    def _call_github_models(
        model_name: str, prompt: str, system_instruction: str | None
    ) -> str:
        """Call GitHub Models via provider adapter."""
        return provider_adapters.call_github_models(
            model_name,
            prompt,
            system_instruction,
        )

    @staticmethod
    def _call_azure_foundry(
        model_name: str,
        prompt: str,
        system_instruction: str | None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """Call Azure Foundry API via provider adapter."""
        return provider_adapters.call_azure_foundry(
            model_name,
            prompt,
            system_instruction,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    @staticmethod
    def _call_gemini(
        model_name: str, prompt: str, system_instruction: str | None
    ) -> str:
        return provider_adapters.call_gemini(model_name, prompt, system_instruction)

    @staticmethod
    def _call_claude(
        model_name: str, prompt: str, system_instruction: str | None
    ) -> str:
        return provider_adapters.call_claude(model_name, prompt, system_instruction)

    @staticmethod
    def _call_openai(
        model_name: str,
        prompt: str,
        system_instruction: str | None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        return provider_adapters.call_openai(
            model_name,
            prompt,
            system_instruction,
            temperature=temperature,
            max_tokens=max_tokens,
        )
