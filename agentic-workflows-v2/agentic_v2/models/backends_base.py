"""Abstract base class and shared types for LLM backends.

Defines the ``LLMBackend`` ABC that all concrete backend implementations
must satisfy.  Kept intentionally minimal so that cloud and local backend
modules can import from here without pulling in provider-specific deps.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator


class LLMBackend(ABC):
    """Abstract base class for LLM backends."""

    @abstractmethod
    async def complete(
        self,
        model: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        """Send completion request."""
        ...

    @abstractmethod
    async def complete_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send chat completion request with tool support."""
        ...

    async def complete_stream(
        self, model: str, prompt: str, **kwargs: Any
    ) -> AsyncIterator[str]:
        """Send streaming completion request.

        Default: non-streaming fallback.
        """
        result = await self.complete(model, prompt, **kwargs)
        yield result

    def count_tokens(self, text: str, model: str) -> int:
        """Estimate token count.

        Default: simple word-based estimate (1 token ≈ 4 chars).
        """
        return len(text) // 4 + 1


__all__ = ["LLMBackend"]
