"""LLM backend implementations.

Provides concrete backends for:
- GitHub Models API (gh:* models)
- OpenAI API (openai:* models)
- Anthropic Claude API (anthropic:* models)
- Google Gemini API (gemini:* models)
- Azure OpenAI Service (azure:* models)
- Azure AI Foundry (azure-foundry:* models)
- Ollama local models (ollama:* / local:* models)
- ONNX local runtime (onnx:* models, via onnxruntime-genai)
- Multi-backend dispatcher (routes by model prefix)
- Mock backend for testing

Cloud backends are defined in backends_cloud.py.
Local backends are defined in backends_local.py.
The ABC is defined in backends_base.py.

Implementation classes live in submodules; this module re-exports
everything so that ``from agentic_v2.models.backends import X`` keeps
working unchanged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable

# Shared placeholder string used by both the native MockBackend path
# (agentic_v2.models.client.get_client) and the LangChain path
# (agentic_v2.langchain.model_builders.build_placeholder_model).  Kept
# here so the two engines cannot drift out of sync (Sprint B #5 review
# finding P6).
PLACEHOLDER_RESPONSE_TEXT = (
    "[AGENTIC_NO_LLM placeholder] Set AGENTIC_NO_LLM=0 and a provider key "
    "to get real output."
)

from .backends_base import LLMBackend
from .backends_cloud import (
    AnthropicBackend,
    AzureFoundryBackend,
    AzureOpenAIBackend,
    GeminiBackend,
    GitHubModelsBackend,
    NvidiaBackend,
    OpenAIBackend,
    OpenRouterBackend,
)
from .backends_local import OllamaBackend, OnnxBackend
from .secrets import SecretProvider, get_first_secret, get_secret

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Multi-backend dispatcher
# ---------------------------------------------------------------------------

# Map model prefix -> backend provider name
PREFIX_MAP: dict[str, str] = {
    "gh:": "github",
    "openai:": "openai",
    "nvidia:": "nvidia",
    "openrouter:": "openrouter",
    "anthropic:": "anthropic",
    "gemini:": "gemini",
    "azure:": "azure",
    "azure-foundry:": "azure_foundry",
    "ollama:": "ollama",
    "local:": "ollama",  # local: models route through Ollama
    "onnx:": "onnx",  # onnx: models run on the local onnxruntime-genai backend
}


@dataclass
class MultiBackend(LLMBackend):
    """Dispatches to the correct backend based on model prefix.

    This allows the router to suggest models from any provider and have
    them automatically handled by the right backend.
    """

    backends: dict[str, LLMBackend] = field(default_factory=dict)

    def _get_backend(self, model: str) -> LLMBackend:
        for prefix, provider in PREFIX_MAP.items():
            if model.startswith(prefix):
                backend = self.backends.get(provider)
                if backend is None:
                    raise RuntimeError(
                        f"No backend configured for provider '{provider}' "
                        f"(model: {model})"
                    )
                return backend

        # No prefix -- try OpenAI as default (bare model names like "gpt-4o")
        if "openai" in self.backends:
            return self.backends["openai"]

        raise RuntimeError(
            f"Cannot determine backend for model '{model}'. "
            f"Available backends: {list(self.backends.keys())}"
        )

    async def complete(
        self,
        model: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        return await self._get_backend(model).complete(
            model, prompt, max_tokens, temperature, **kwargs
        )

    async def complete_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return await self._get_backend(model).complete_chat(
            model, messages, max_tokens, temperature, tools, **kwargs
        )

    async def complete_stream(
        self, model: str, prompt: str, **kwargs: Any
    ) -> AsyncIterator[str]:
        async for chunk in self._get_backend(model).complete_stream(
            model, prompt, **kwargs
        ):
            yield chunk

    async def close(self) -> None:
        for backend in self.backends.values():
            if hasattr(backend, "close"):
                await backend.close()


@dataclass
class MockBackend(LLMBackend):
    """Mock backend for testing.

    Returns configurable responses without making real API calls.
    """

    default_response: str = "This is a mock response."
    responses: dict[str, str] = field(default_factory=dict)
    call_history: list[dict[str, Any]] = field(default_factory=list)

    def set_response(self, pattern: str, response: str) -> None:
        """Set a canned response for prompts containing pattern."""
        self.responses[pattern] = response

    async def complete(
        self,
        model: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        """Return mock response."""
        self.call_history.append(
            {
                "method": "complete",
                "model": model,
                "prompt": prompt,
                "kwargs": kwargs,
            }
        )

        # Check for pattern matches
        for pattern, response in self.responses.items():
            if pattern.lower() in prompt.lower():
                return response

        return self.default_response

    async def complete_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Return mock chat response."""
        self.call_history.append(
            {
                "method": "complete_chat",
                "model": model,
                "messages": messages,
                "tools": tools,
                "kwargs": kwargs,
            }
        )

        # Get last user message for pattern matching
        last_user = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user = msg.get("content", "")
                break

        # Check for pattern matches
        for pattern, response in self.responses.items():
            if pattern.lower() in last_user.lower():
                return {"content": response, "tool_calls": None}

        return {"content": self.default_response, "tool_calls": None}


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


def _onnx_runtime_available() -> bool:
    """Return True when onnxruntime-genai can be imported on this host."""
    import importlib.util

    return importlib.util.find_spec("onnxruntime_genai") is not None


def _required_secret(name: str, *, secret_provider: SecretProvider | None) -> str:
    """Resolve a single named secret, coalescing absence to an empty string."""
    return get_secret(name, default="", provider=secret_provider) or ""


def _build_cloud_backend(
    provider: str, secret_provider: SecretProvider | None
) -> LLMBackend | None:
    """Construct a cloud backend for ``provider``, or None if not cloud.

    Handles the credentialed providers (GitHub, OpenAI, Anthropic,
    Gemini, Azure OpenAI, Azure AI Foundry). Returns None for non-cloud
    providers so the caller can handle local/mock backends.
    """
    if provider == "github":
        token = (
            get_first_secret(
                "GITHUB_TOKEN",
                "GH_TOKEN",
                default="",
                provider=secret_provider,
            )
            or ""
        )
        return GitHubModelsBackend(token=token)
    if provider == "openai":
        return OpenAIBackend(
            api_key=_required_secret("OPENAI_API_KEY", secret_provider=secret_provider)
        )
    if provider == "openrouter":
        return OpenRouterBackend(
            api_key=_required_secret(
                "OPENROUTER_API_KEY", secret_provider=secret_provider
            )
        )
    if provider == "anthropic":
        return AnthropicBackend(
            api_key=_required_secret(
                "ANTHROPIC_API_KEY", secret_provider=secret_provider
            )
        )
    if provider == "gemini":
        return GeminiBackend(
            api_key=_required_secret("GEMINI_API_KEY", secret_provider=secret_provider)
        )
    if provider == "azure":
        return AzureOpenAIBackend(
            api_key=_required_secret(
                "AZURE_OPENAI_API_KEY", secret_provider=secret_provider
            ),
            endpoint=_required_secret(
                "AZURE_OPENAI_ENDPOINT", secret_provider=secret_provider
            ),
        )
    if provider == "azure_foundry":
        return AzureFoundryBackend(
            api_key=_required_secret(
                "AZURE_FOUNDRY_API_KEY", secret_provider=secret_provider
            ),
            endpoint=_required_secret(
                "AZURE_FOUNDRY_ENDPOINT", secret_provider=secret_provider
            ),
        )
    return None


def get_backend(
    provider: str = "github",
    *,
    secret_provider: SecretProvider | None = None,
) -> LLMBackend:
    """Factory function to get a single LLM backend.

    Args:
        provider: One of 'github', 'openai', 'anthropic', 'gemini', 'azure',
            'azure_foundry', 'ollama', 'onnx', 'mock'

    Returns:
        Configured LLM backend
    """
    provider = provider.lower()
    cloud_backend = _build_cloud_backend(provider, secret_provider)
    if cloud_backend is not None:
        return cloud_backend
    if provider == "ollama":
        return OllamaBackend()
    if provider == "onnx":
        return OnnxBackend()
    if provider == "mock":
        return MockBackend()
    raise ValueError(f"Unknown provider: {provider}")


def _try_register_backend(
    backends: dict[str, LLMBackend],
    key: str,
    factory: Callable[[], LLMBackend],
    log_message: str,
) -> None:
    """Register ``factory()`` under ``key`` unless construction raises ValueError.

    A no-op when the backend cannot be constructed (mirrors the original
    per-provider ``try/except ValueError: pass`` guards).
    """
    try:
        backends[key] = factory()
        logger.info(log_message)
    except ValueError:
        pass


def _register_cloud_backends(
    backends: dict[str, LLMBackend],
    active_provider: SecretProvider | None,
) -> None:
    """Probe credentials in priority order and register available backends."""
    # OpenAI -- most common, check first
    openai_api_key = get_secret("OPENAI_API_KEY", provider=active_provider)
    if openai_api_key:
        _try_register_backend(
            backends,
            "openai",
            lambda: OpenAIBackend(api_key=openai_api_key),
            "Registered OpenAI backend",
        )

    # NVIDIA NIM — cloud needs NVIDIA_API_KEY; a self-hosted NIM needs only
    # NVIDIA_BASE_URL (it does not validate the key). Register when either is set
    # so a discovered ``nvidia:`` id is actually runnable, not just advertised.
    nvidia_api_key = get_secret("NVIDIA_API_KEY", provider=active_provider)
    nvidia_base_url = get_secret("NVIDIA_BASE_URL", provider=active_provider)
    if nvidia_api_key or nvidia_base_url:
        _try_register_backend(
            backends,
            "nvidia",
            lambda: NvidiaBackend(api_key=nvidia_api_key or ""),
            "Registered NVIDIA NIM backend",
        )

    # OpenRouter — aggregator over an OpenAI-compatible surface; always
    # authenticated (no keyless self-hosted mode, unlike NIM).
    openrouter_api_key = get_secret("OPENROUTER_API_KEY", provider=active_provider)
    if openrouter_api_key:
        _try_register_backend(
            backends,
            "openrouter",
            lambda: OpenRouterBackend(api_key=openrouter_api_key),
            "Registered OpenRouter backend",
        )

    # Anthropic
    anthropic_api_key = get_secret("ANTHROPIC_API_KEY", provider=active_provider)
    if anthropic_api_key:
        _try_register_backend(
            backends,
            "anthropic",
            lambda: AnthropicBackend(api_key=anthropic_api_key),
            "Registered Anthropic backend",
        )

    # GitHub Models (check both GITHUB_TOKEN and GH_TOKEN)
    github_token = get_first_secret(
        "GITHUB_TOKEN",
        "GH_TOKEN",
        provider=active_provider,
    )
    if github_token:
        _try_register_backend(
            backends,
            "github",
            lambda: GitHubModelsBackend(token=github_token),
            "Registered GitHub Models backend",
        )

    # Gemini
    gemini_api_key = get_secret("GEMINI_API_KEY", provider=active_provider)
    if gemini_api_key:
        _try_register_backend(
            backends,
            "gemini",
            lambda: GeminiBackend(api_key=gemini_api_key),
            "Registered Gemini backend",
        )

    # Azure OpenAI (needs both key and endpoint)
    azure_key = get_secret("AZURE_OPENAI_API_KEY", provider=active_provider)
    azure_endpoint = get_secret("AZURE_OPENAI_ENDPOINT", provider=active_provider)
    if azure_key and azure_endpoint:
        _try_register_backend(
            backends,
            "azure",
            lambda: AzureOpenAIBackend(api_key=azure_key, endpoint=azure_endpoint),
            "Registered Azure OpenAI backend",
        )

    # Azure AI Foundry (needs both key and endpoint)
    foundry_key = get_secret("AZURE_FOUNDRY_API_KEY", provider=active_provider)
    foundry_endpoint = get_secret("AZURE_FOUNDRY_ENDPOINT", provider=active_provider)
    if foundry_key and foundry_endpoint:
        _try_register_backend(
            backends,
            "azure_foundry",
            lambda: AzureFoundryBackend(api_key=foundry_key, endpoint=foundry_endpoint),
            "Registered Azure AI Foundry backend",
        )


def auto_configure_backend(
    *,
    secret_provider: SecretProvider | None = None,
) -> LLMBackend:
    """Auto-detect available API keys and build a MultiBackend.

    Probes env vars in priority order and registers all available
    backends. Returns a MultiBackend that dispatches based on model
    prefix.

    Returns an Ollama-only backend when no cloud API keys are configured.
    Higher-level routing layers remain responsible for raising
    ``NoProviderConfiguredError`` when they truly have no usable models.
    """
    backends: dict[str, LLMBackend] = {}
    active_provider = secret_provider

    _register_cloud_backends(backends, active_provider)

    # Ollama (always register -- it's local and free)
    backends["ollama"] = OllamaBackend()

    # ONNX (register when the native onnxruntime-genai runtime is importable;
    # the model files themselves are resolved lazily at call time).
    if _onnx_runtime_available():
        backends["onnx"] = OnnxBackend()
        logger.info("Registered ONNX (onnxruntime-genai) backend")

    # Detect no-cloud-key situation. Ollama is always present, so return the
    # local-only MultiBackend and let higher-level callers decide whether that
    # is sufficient for the requested workload.
    cloud_keys = {k for k in backends if k not in ("ollama", "onnx")}
    if not cloud_keys:
        logger.warning(
            "No cloud LLM provider credentials configured; returning Ollama-only backend."
        )

    logger.info("Auto-configured backends: %s", ", ".join(sorted(backends.keys())))
    return MultiBackend(backends=backends)


# ---------------------------------------------------------------------------
# Re-exports for backward compatibility
# ---------------------------------------------------------------------------
# All names that were previously importable from this module remain available.

__all__ = [
    "LLMBackend",
    "GitHubModelsBackend",
    "OpenAIBackend",
    "NvidiaBackend",
    "OpenRouterBackend",
    "AnthropicBackend",
    "GeminiBackend",
    "AzureOpenAIBackend",
    "AzureFoundryBackend",
    "OllamaBackend",
    "OnnxBackend",
    "MultiBackend",
    "MockBackend",
    "PREFIX_MAP",
    "get_backend",
    "auto_configure_backend",
]
