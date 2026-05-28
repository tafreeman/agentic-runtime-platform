"""Local model LLM backend implementations.

Concrete backends for locally-hosted model servers:

- ``OllamaBackend`` — Ollama local model server (http://localhost:11434)

Ollama supports a wide variety of open-weight models including reasoning
models (qwen3, deepseek-r1, phi4-reasoning) whose chain-of-thought output
appears in the ``thinking`` field rather than ``response``/``content``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from .backends_base import LLMBackend

# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------


@dataclass
class OllamaBackend(LLMBackend):
    """Backend for Ollama local models."""

    base_url: str = "http://localhost:11434"
    timeout: float = 300.0  # Local models can be slower
    _client: httpx.AsyncClient | None = field(default=None, repr=False)

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
        """Send completion request to Ollama."""
        client = await self._get_client()

        # Strip provider prefix if present
        model_name = model.replace("ollama:", "")

        payload = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }

        response = await client.post("/api/generate", json=payload)
        response.raise_for_status()

        data = response.json()
        # Reasoning models (qwen3, deepseek-r1, phi4-reasoning) put their
        # chain-of-thought in a "thinking" field and may leave "response"
        # empty.  Fall back to "thinking" content when "response" is blank.
        text = data.get("response", "")
        if not text.strip():
            text = data.get("thinking", "")
        return text

    async def complete_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send chat completion request to Ollama."""
        client = await self._get_client()

        # Strip provider prefix if present
        model_name = model.replace("ollama:", "")

        payload: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }

        # Ollama supports tools for some models
        if tools:
            payload["tools"] = tools

        response = await client.post("/api/chat", json=payload)
        response.raise_for_status()

        data = response.json()
        message = data.get("message", {})

        # Reasoning models may return content in "thinking" with empty "content"
        content = message.get("content", "")
        if not content.strip():
            content = message.get("thinking", "")

        return {
            "content": content,
            "tool_calls": message.get("tool_calls"),
            "finish_reason": "stop",
            "model": model_name,
        }

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()


__all__ = ["OllamaBackend"]
