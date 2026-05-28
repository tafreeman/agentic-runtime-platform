"""Tier 0 context utilities.

These are deterministic helpers for managing large text inputs before sending
prompts to an LLM.

Notes:
- Token counting is heuristic (~4 chars/token) unless you inject a real counter
  elsewhere.
- Trimming is character-based using the same heuristic to stay fast and
  dependency-free.
"""

from __future__ import annotations

from typing import Any

from ..base import BaseTool, ToolResult


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


class TokenEstimateTool(BaseTool):
    """Heuristic token-count estimator for plain text strings."""

    @property
    def name(self) -> str:
        """Return the tool name."""
        return "token_estimate"

    @property
    def description(self) -> str:
        """Return a human-readable description of what the tool does."""
        return "Estimate token count for a text string (heuristic)."

    @property
    def parameters(self) -> dict[str, Any]:
        """Return the JSON-schema parameter definition."""
        return {
            "text": {
                "type": "string",
                "description": "Text to estimate",
                "required": True,
            },
        }

    @property
    def examples(self) -> list[str]:
        """Return example invocation strings."""
        return ["token_estimate(text='hello world') → ~2"]

    async def execute(self, text: str) -> ToolResult:
        """Estimate the token count for *text* and return the result."""
        try:
            # Heuristic: ~4 chars per token for English text
            tokens = max(1, len(text) // 4)
            return ToolResult(
                success=True,
                data={"tokens": tokens, "chars": len(text)},
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class ContextTrimTool(BaseTool):
    """Trim long text to fit within a token budget, preserving head and tail."""

    @property
    def name(self) -> str:
        """Return the tool name."""
        return "context_trim"

    @property
    def description(self) -> str:
        """Return a human-readable description of what the tool does."""
        return "Trim long text to fit a token budget, preserving head and tail."

    @property
    def parameters(self) -> dict[str, Any]:
        """Return the JSON-schema parameter definition."""
        return {
            "text": {"type": "string", "description": "Text to trim", "required": True},
            "max_tokens": {
                "type": "integer",
                "description": "Target maximum tokens",
                "required": True,
            },
            "head_tokens": {
                "type": "integer",
                "description": "Tokens to preserve from the start (default 256)",
                "required": False,
            },
            "tail_tokens": {
                "type": "integer",
                "description": "Tokens to preserve from the end (default: max_tokens - head_tokens)",
                "required": False,
            },
            "marker": {
                "type": "string",
                "description": "Marker inserted between head and tail",
                "required": False,
            },
        }

    @property
    def examples(self) -> list[str]:
        """Return example invocation strings."""
        return [
            "context_trim(text=BIG, max_tokens=2000, head_tokens=200, tail_tokens=300)",
        ]

    async def execute(
        self,
        text: str,
        max_tokens: int,
        head_tokens: int = 256,
        tail_tokens: int | None = None,
        marker: str = "\n\n[... truncated to fit token budget ...]\n\n",
    ) -> ToolResult:
        """Trim *text* to fit *max_tokens*, preserving head and tail sections."""
        try:
            max_tokens = int(max_tokens)
            if max_tokens <= 0:
                return ToolResult(success=False, error="max_tokens must be > 0")

            head_tokens = int(head_tokens)
            if head_tokens < 0:
                return ToolResult(success=False, error="head_tokens must be >= 0")

            if tail_tokens is None:
                tail_tokens = max(0, max_tokens - head_tokens)
            else:
                tail_tokens = int(tail_tokens)
                if tail_tokens < 0:
                    return ToolResult(success=False, error="tail_tokens must be >= 0")

            max_chars = max_tokens * 4
            if len(text) <= max_chars:
                return ToolResult(
                    success=True,
                    data={
                        "text": text,
                        "trimmed": False,
                        "estimated_tokens": _estimate_tokens(text),
                        "max_tokens": max_tokens,
                    },
                )

            head_chars = min(len(text), head_tokens * 4)
            tail_chars = min(len(text) - head_chars, tail_tokens * 4)

            head = text[:head_chars]
            tail = text[-tail_chars:] if tail_chars > 0 else ""

            truncated_chars = max(0, len(text) - (len(head) + len(tail)))
            out = head + marker + tail

            return ToolResult(
                success=True,
                data={
                    "text": out,
                    "trimmed": True,
                    "truncated_chars": truncated_chars,
                    "estimated_tokens": _estimate_tokens(out),
                    "max_tokens": max_tokens,
                    "head_tokens": head_tokens,
                    "tail_tokens": tail_tokens,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
