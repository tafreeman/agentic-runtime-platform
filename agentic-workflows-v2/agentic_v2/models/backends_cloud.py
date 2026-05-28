"""Cloud provider LLM backend implementations.

Concrete backends for cloud-hosted model APIs:

- ``GitHubModelsBackend`` — GitHub Models (Azure AI Inference endpoint)
- ``OpenAIBackend``        — OpenAI API
- ``AnthropicBackend``     — Anthropic Claude API
- ``GeminiBackend``        — Google Gemini API

Each backend is a ``@dataclass`` that reads its credentials from environment
variables and communicates with the provider over ``httpx.AsyncClient``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from .backends_base import LLMBackend
from .secrets import get_first_secret, get_secret

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
                    "Content-Type": "application/json",
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
            payload["tool_choice"] = "auto"

        response = await client.post("/chat/completions", json=payload)
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
                    "Content-Type": "application/json",
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
        **kwargs: Any,
    ) -> dict[str, Any]:
        client = await self._get_client()

        model_name = model.removeprefix("openai:")

        payload: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            **kwargs,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        response = await client.post("/chat/completions", json=payload)
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
                    "Content-Type": "application/json",
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

        response = await client.post("/v1/messages", json=payload)
        response.raise_for_status()

        data = response.json()
        content_blocks = data.get("content", [])

        # Extract text from content blocks
        text_parts = []
        tool_calls = []
        for block in content_blocks:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(block)

        return {
            "content": "\n".join(text_parts),
            "tool_calls": tool_calls or None,
            "finish_reason": data.get("stop_reason", "end_turn"),
            "model": data.get("model"),
            "usage": data.get("usage", {}),
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

        return {
            "content": "\n".join(text_parts),
            "tool_calls": None,
            "finish_reason": candidates[0].get("finishReason", "STOP"),
            "model": model_name,
            "usage": data.get("usageMetadata", {}),
        }

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


__all__ = [
    "AnthropicBackend",
    "GeminiBackend",
    "GitHubModelsBackend",
    "OpenAIBackend",
]
