"""Cloud provider LLM backend implementations.

Concrete backends for cloud-hosted model APIs:

- ``GitHubModelsBackend`` — GitHub Models (Azure AI Inference endpoint)
- ``OpenAIBackend``        — OpenAI API
- ``NvidiaBackend``        — NVIDIA NIM (OpenAI-compatible cloud + on-prem)
- ``OpenRouterBackend``    — OpenRouter aggregator (OpenAI-compatible)
- ``AnthropicBackend``     — Anthropic Claude API
- ``GeminiBackend``        — Google Gemini API

Each backend is a ``@dataclass`` that reads its credentials from environment
variables and communicates with the provider over ``httpx.AsyncClient``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, ClassVar

import httpx

from .backends_base import LLMBackend
from .secrets import get_first_secret, get_secret

# ---------------------------------------------------------------------------
# String constants (extracted to satisfy python:S1192 — define once, reuse)
# ---------------------------------------------------------------------------

CONTENT_TYPE_JSON = "application/json"
CHAT_COMPLETIONS_PATH = "/chat/completions"

# Non-secret placeholder for self-hosted NVIDIA NIM, which does not validate the
# API key. A non-empty value is still required so the Bearer header is well-formed.
_LOCAL_NIM_PLACEHOLDER_KEY = "not-needed-for-local-nim"


def _to_anthropic_tool_choice(
    tool_choice: str | dict[str, Any],
) -> dict[str, Any] | None:
    """Map an OpenAI-normalized ``tool_choice`` to Anthropic's wire shape.

    The engine normalizes choices to OpenAI form via
    :func:`agentic_v2.engine.tool_execution.normalize_tool_choice` before they
    reach a backend, so the inputs here are: ``"auto"`` / ``"required"`` /
    ``"none"`` (bare strings) or a forced ``{"type": "function", "function":
    {"name": ...}}`` dict.

    Returns the Anthropic ``tool_choice`` dict, or ``None`` for plain ``"auto"``
    so the default path leaves the payload untouched (preserving prior
    behavior where Anthropic was never sent an explicit ``tool_choice``).
    """
    if isinstance(tool_choice, str):
        lowered = tool_choice.strip().lower()
        if lowered in ("required", "any"):
            return {"type": "any"}
        if lowered == "none":
            return {"type": "none"}
        # "auto" / "" / unknown → omit (Anthropic defaults to auto).
        return None

    func = tool_choice.get("function")
    if isinstance(func, dict) and func.get("name"):
        return {"type": "tool", "name": str(func["name"])}
    # Already-Anthropic-shaped forced dict {"type": "tool", "name": ...}.
    name = tool_choice.get("name")
    if tool_choice.get("type") == "tool" and name:
        return {"type": "tool", "name": str(name)}
    return None


# ---------------------------------------------------------------------------
# GitHub Models
# ---------------------------------------------------------------------------


@dataclass
class GitHubModelsBackend(LLMBackend):
    """Backend for GitHub Models API.

    Uses the Azure AI Inference endpoint via GitHub token.
    """

    token: str = field(
        default_factory=lambda: (
            get_first_secret("GITHUB_TOKEN", "GH_TOKEN", default="") or ""
        ),
        repr=False,
    )
    base_url: str = "https://models.inference.ai.azure.com"
    timeout: float = 120.0
    _client: httpx.AsyncClient | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.token:
            raise ValueError(
                "GITHUB_TOKEN or GH_TOKEN environment variable required for GitHub Models"
            )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": CONTENT_TYPE_JSON,
                },
            )
        return self._client

    async def complete(
        self,
        model: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        """Send completion as a chat message."""
        messages = [{"role": "user", "content": prompt}]
        result = await self.complete_chat(
            model, messages, max_tokens, temperature, **kwargs
        )
        return result.get("content", "")

    async def complete_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] = "auto",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send chat completion request."""
        client = await self._get_client()

        # Strip provider prefix and org prefix (e.g. "gh:openai/gpt-4o-mini" -> "gpt-4o-mini")
        model_name = model.removeprefix("gh:")
        if "/" in model_name:
            model_name = model_name.split("/", 1)[1]

        payload: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            **kwargs,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        response = await client.post(CHAT_COMPLETIONS_PATH, json=payload)
        response.raise_for_status()

        data = response.json()
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})

        return {
            "content": message.get("content", ""),
            "tool_calls": message.get("tool_calls"),
            "finish_reason": choice.get("finish_reason"),
            "model": data.get("model"),
            "usage": data.get("usage", {}),
        }

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


@dataclass
class OpenAIBackend(LLMBackend):
    """Backend for OpenAI API."""

    # Prefix stripped from the model id before it hits the wire. Subclasses for
    # other OpenAI-compatible providers (e.g. NVIDIA NIM) override this.
    _provider_prefix: ClassVar[str] = "openai:"

    api_key: str = field(
        default_factory=lambda: get_secret("OPENAI_API_KEY", default="") or "",
        repr=False,
    )
    base_url: str = "https://api.openai.com/v1"
    timeout: float = 120.0
    _client: httpx.AsyncClient | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY environment variable required")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": CONTENT_TYPE_JSON,
                },
            )
        return self._client

    async def complete(
        self,
        model: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        messages = [{"role": "user", "content": prompt}]
        result = await self.complete_chat(
            model, messages, max_tokens, temperature, **kwargs
        )
        return result.get("content", "")

    async def complete_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] = "auto",
        **kwargs: Any,
    ) -> dict[str, Any]:
        client = await self._get_client()

        model_name = model.removeprefix(self._provider_prefix)

        payload: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            **kwargs,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        response = await client.post(CHAT_COMPLETIONS_PATH, json=payload)
        response.raise_for_status()

        data = response.json()
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})

        return {
            "content": message.get("content", ""),
            "tool_calls": message.get("tool_calls"),
            "finish_reason": choice.get("finish_reason"),
            "model": data.get("model"),
            "usage": data.get("usage", {}),
        }

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# ---------------------------------------------------------------------------
# NVIDIA NIM
# ---------------------------------------------------------------------------


@dataclass
class NvidiaBackend(OpenAIBackend):
    """Backend for NVIDIA NIM (OpenAI-compatible ``/v1`` surface).

    NIM speaks the OpenAI wire protocol for both the public cloud
    (``integrate.api.nvidia.com``) and self-hosted containers, so this is just
    :class:`OpenAIBackend` with NVIDIA credentials and base-URL resolution.

    Two NVIDIA-specific behaviors:

    - Model ids keep their ``publisher/model`` form (e.g.
      ``meta/llama-3.3-70b-instruct``); only the ``nvidia:`` prefix is stripped,
      never the publisher segment, so a discovered id round-trips unchanged.
    - The cloud endpoint requires ``NVIDIA_API_KEY``; a self-hosted NIM selected
      via ``NVIDIA_BASE_URL`` does not validate the key, so a non-secret
      placeholder is substituted there rather than raising.
    """

    _provider_prefix: ClassVar[str] = "nvidia:"

    api_key: str = field(
        default_factory=lambda: get_secret("NVIDIA_API_KEY", default="") or "",
        repr=False,
    )
    # Resolved in __post_init__ via the shared discovery helper so backend and
    # probe always target the same host.
    base_url: str = ""

    def __post_init__(self) -> None:
        from .cloud_discovery import resolve_nvidia_base_url

        if not self.base_url:
            self.base_url = resolve_nvidia_base_url()
        if not self.api_key:
            if not os.environ.get("NVIDIA_BASE_URL"):
                raise ValueError(
                    "NVIDIA_API_KEY environment variable required for NVIDIA NIM cloud"
                )
            # Self-hosted NIM ignores the key; a non-empty value keeps the header valid.
            self.api_key = _LOCAL_NIM_PLACEHOLDER_KEY


# ---------------------------------------------------------------------------
# OpenRouter
# ---------------------------------------------------------------------------


@dataclass
class OpenRouterBackend(OpenAIBackend):
    """Backend for the OpenRouter aggregator (OpenAI-compatible ``/v1`` surface).

    OpenRouter speaks the OpenAI wire protocol for every model it fronts, so
    this is just :class:`OpenAIBackend` with OpenRouter credentials and
    base-URL resolution (shared with discovery via
    :func:`agentic_v2.models.cloud_discovery.resolve_openrouter_base_url`).

    Model ids keep their ``publisher/model`` form and free-tier ids append
    ``:free`` (e.g. ``meta-llama/llama-3.1-8b-instruct:free``); only the
    ``openrouter:`` prefix is stripped — never the publisher segment or the
    ``:free`` suffix — so a discovered id round-trips unchanged. Unlike NIM
    there is no keyless self-hosted mode: ``OPENROUTER_API_KEY`` is always
    required.
    """

    _provider_prefix: ClassVar[str] = "openrouter:"

    api_key: str = field(
        default_factory=lambda: get_secret("OPENROUTER_API_KEY", default="") or "",
        repr=False,
    )
    # Resolved in __post_init__ via the shared discovery helper so backend and
    # probe always target the same host.
    base_url: str = ""

    def __post_init__(self) -> None:
        from .cloud_discovery import resolve_openrouter_base_url

        if not self.base_url:
            self.base_url = resolve_openrouter_base_url()
        if not self.api_key:
            raise ValueError(
                "OPENROUTER_API_KEY environment variable required for OpenRouter"
            )


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


@dataclass
class AnthropicBackend(LLMBackend):
    """Backend for Anthropic Claude API."""

    api_key: str = field(
        default_factory=lambda: get_secret("ANTHROPIC_API_KEY", default="") or "",
        repr=False,
    )
    base_url: str = "https://api.anthropic.com"
    timeout: float = 120.0
    api_version: str = "2023-06-01"
    _client: httpx.AsyncClient | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable required")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": self.api_version,
                    "Content-Type": CONTENT_TYPE_JSON,
                },
            )
        return self._client

    async def complete(
        self,
        model: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        messages = [{"role": "user", "content": prompt}]
        result = await self.complete_chat(
            model, messages, max_tokens, temperature, **kwargs
        )
        return result.get("content", "")

    async def complete_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] = "auto",
        **kwargs: Any,
    ) -> dict[str, Any]:
        client = await self._get_client()

        model_name = model.removeprefix("anthropic:")

        payload: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            **kwargs,
        }

        if tools:
            # Convert OpenAI tool format to Anthropic format
            anthropic_tools = []
            for tool in tools:
                func = tool.get("function", tool)
                anthropic_tools.append(
                    {
                        "name": func.get("name", ""),
                        "description": func.get("description", ""),
                        "input_schema": func.get("parameters", {}),
                    }
                )
            payload["tools"] = anthropic_tools
            anthropic_choice = _to_anthropic_tool_choice(tool_choice)
            if anthropic_choice is not None:
                payload["tool_choice"] = anthropic_choice

        response = await client.post("/v1/messages", json=payload)
        response.raise_for_status()

        data = response.json()
        content_blocks = data.get("content", [])

        # Extract text from content blocks
        text_parts = []
        raw_tool_use_blocks: list[dict[str, Any]] = []
        for block in content_blocks:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                raw_tool_use_blocks.append(block)

        # ADR-023 Phase 3: canonicalize to OpenAI-flavoured dict shape.
        # Map Anthropic tool_use content blocks -> OpenAI tool_calls shape.
        canonical_tool_calls: list[dict[str, Any]] | None
        if raw_tool_use_blocks:
            canonical_tool_calls = [
                {
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {})),
                    },
                }
                for block in raw_tool_use_blocks
            ]
        else:
            canonical_tool_calls = None

        # Map Anthropic stop_reason -> OpenAI finish_reason.
        raw_stop_reason = data.get("stop_reason", "end_turn")
        _stop_reason_map = {
            "end_turn": "stop",
            "max_tokens": "length",
            "tool_use": "tool_calls",
            "stop_sequence": "stop",
        }
        canonical_finish_reason = _stop_reason_map.get(raw_stop_reason, raw_stop_reason)

        return {
            "content": "\n".join(text_parts),
            "tool_calls": canonical_tool_calls,
            "finish_reason": canonical_finish_reason,
            "model": data.get("model"),
            "usage": data.get("usage", {}),
            "_raw_anthropic": data,
        }

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# ---------------------------------------------------------------------------
# Google Gemini
# ---------------------------------------------------------------------------


@dataclass
class GeminiBackend(LLMBackend):
    """Backend for Google Gemini API."""

    api_key: str = field(
        default_factory=lambda: get_secret("GEMINI_API_KEY", default="") or "",
        repr=False,
    )
    base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    timeout: float = 120.0
    _client: httpx.AsyncClient | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable required")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._client

    async def complete(
        self,
        model: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        messages = [{"role": "user", "content": prompt}]
        result = await self.complete_chat(
            model, messages, max_tokens, temperature, **kwargs
        )
        return result.get("content", "")

    async def complete_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        client = await self._get_client()

        model_name = model.removeprefix("gemini:")

        # Convert chat messages to Gemini format
        contents = []
        for msg in messages:
            role = msg.get("role", "user")
            # Gemini uses "user" and "model" roles
            gemini_role = "model" if role == "assistant" else "user"
            contents.append(
                {
                    "role": gemini_role,
                    "parts": [{"text": msg.get("content", "")}],
                }
            )

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }

        url = f"/models/{model_name}:generateContent"
        headers = {"x-goog-api-key": self.api_key}
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()

        data = response.json()
        candidates = data.get("candidates", [{}])
        if not candidates:
            return {"content": "", "tool_calls": None, "finish_reason": "error"}

        parts = candidates[0].get("content", {}).get("parts", [])
        text_parts = [p.get("text", "") for p in parts if "text" in p]

        # ADR-023 Phase 3: canonicalize Gemini dict shape to OpenAI-flavoured
        # fields. The raw Gemini response stays available under
        # ``_raw_gemini`` for downstream consumers that still need vendor
        # specifics (telemetry, debugging).
        raw_finish_reason = candidates[0].get("finishReason", "STOP")
        _GEMINI_FINISH_REASON_MAP = {
            "STOP": "stop",
            "MAX_TOKENS": "length",
            "SAFETY": "content_filter",
            "RECITATION": "content_filter",
            "OTHER": "stop",
        }
        finish_reason = _GEMINI_FINISH_REASON_MAP.get(
            raw_finish_reason, raw_finish_reason.lower()
        )

        raw_usage = data.get("usageMetadata", {}) or {}
        usage = {
            "prompt_tokens": raw_usage.get("promptTokenCount", 0),
            "completion_tokens": raw_usage.get("candidatesTokenCount", 0),
            "total_tokens": raw_usage.get("totalTokenCount", 0),
        }

        return {
            "content": "\n".join(text_parts),
            "tool_calls": None,
            "finish_reason": finish_reason,
            "model": model_name,
            "usage": usage,
            "_raw_gemini": data,
        }

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# ---------------------------------------------------------------------------
# Azure OpenAI / Azure AI Foundry
# ---------------------------------------------------------------------------


def _extract_openai_chat(data: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize an OpenAI-shaped ``chat/completions`` response.

    Azure OpenAI and Azure AI Foundry both return the OpenAI
    ``choices[0].message`` envelope, so the extraction is shared between
    their backends rather than duplicated.
    """
    choices = data.get("choices")
    choice = choices[0] if choices else {}
    message = choice.get("message") or {}
    return {
        "content": message.get("content") or "",
        "tool_calls": message.get("tool_calls"),
        "finish_reason": choice.get("finish_reason"),
        "model": data.get("model"),
        "usage": data.get("usage") or {},
    }


@dataclass
class AzureOpenAIBackend(LLMBackend):
    """Backend for the Azure OpenAI Service.

    Differs from :class:`OpenAIBackend` in three ways: authentication uses
    the ``api-key`` header (not a Bearer token), the *deployment* name is
    carried in the URL path rather than the request body, and every request
    is pinned to an ``api-version``. Model strings are ``azure:<deployment>``.
    """

    api_key: str = field(
        default_factory=lambda: get_secret("AZURE_OPENAI_API_KEY", default="") or "",
        repr=False,
    )
    endpoint: str = field(
        default_factory=lambda: get_secret("AZURE_OPENAI_ENDPOINT", default="") or "",
    )
    api_version: str = field(
        default_factory=lambda: (
            get_secret("AZURE_OPENAI_API_VERSION", default="2024-10-21") or "2024-10-21"
        ),
    )
    timeout: float = 120.0
    _client: httpx.AsyncClient | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.api_key:
            raise ValueError("AZURE_OPENAI_API_KEY environment variable required")
        if not self.endpoint:
            raise ValueError("AZURE_OPENAI_ENDPOINT environment variable required")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.endpoint.rstrip("/"),
                timeout=self.timeout,
                headers={
                    "api-key": self.api_key,
                    "Content-Type": CONTENT_TYPE_JSON,
                },
            )
        return self._client

    async def complete(
        self,
        model: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        messages = [{"role": "user", "content": prompt}]
        result = await self.complete_chat(
            model, messages, max_tokens, temperature, **kwargs
        )
        return result.get("content", "")

    async def complete_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] = "auto",
        **kwargs: Any,
    ) -> dict[str, Any]:
        client = await self._get_client()

        # Azure carries the deployment name in the path, not the body.
        deployment = model.removeprefix("azure:")

        payload: dict[str, Any] = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            **kwargs,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        response = await client.post(
            f"/openai/deployments/{deployment}/chat/completions",
            params={"api-version": self.api_version},
            json=payload,
        )
        response.raise_for_status()
        return _extract_openai_chat(response.json())

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


@dataclass
class AzureFoundryBackend(LLMBackend):
    """Backend for Azure AI Foundry model deployments.

    Targets the unified Azure AI Inference endpoint (OpenAI-compatible
    ``/chat/completions``), which serves catalog models such as Phi-4,
    Mistral, and Llama from a single resource. Unlike Azure OpenAI the
    model name travels in the request body. Model strings are
    ``azure-foundry:<model>``.
    """

    api_key: str = field(
        default_factory=lambda: get_secret("AZURE_FOUNDRY_API_KEY", default="") or "",
        repr=False,
    )
    endpoint: str = field(
        default_factory=lambda: get_secret("AZURE_FOUNDRY_ENDPOINT", default="") or "",
    )
    api_version: str = field(
        default_factory=lambda: (
            get_secret("AZURE_FOUNDRY_API_VERSION", default="2024-05-01-preview")
            or "2024-05-01-preview"
        ),
    )
    timeout: float = 120.0
    _client: httpx.AsyncClient | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.api_key:
            raise ValueError("AZURE_FOUNDRY_API_KEY environment variable required")
        if not self.endpoint:
            raise ValueError("AZURE_FOUNDRY_ENDPOINT environment variable required")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.endpoint.rstrip("/"),
                timeout=self.timeout,
                headers={
                    "api-key": self.api_key,
                    "Content-Type": CONTENT_TYPE_JSON,
                },
            )
        return self._client

    async def complete(
        self,
        model: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        messages = [{"role": "user", "content": prompt}]
        result = await self.complete_chat(
            model, messages, max_tokens, temperature, **kwargs
        )
        return result.get("content", "")

    async def complete_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] = "auto",
        **kwargs: Any,
    ) -> dict[str, Any]:
        client = await self._get_client()

        model_name = model.removeprefix("azure-foundry:")

        payload: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            **kwargs,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        response = await client.post(
            CHAT_COMPLETIONS_PATH,
            params={"api-version": self.api_version},
            json=payload,
        )
        response.raise_for_status()
        return _extract_openai_chat(response.json())

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


__all__ = [
    "AnthropicBackend",
    "AzureFoundryBackend",
    "AzureOpenAIBackend",
    "GeminiBackend",
    "GitHubModelsBackend",
    "OpenAIBackend",
    "OpenRouterBackend",
]
