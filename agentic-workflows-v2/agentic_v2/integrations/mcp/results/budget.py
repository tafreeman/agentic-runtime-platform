"""
Context Budget Guard - protects LLM context from oversized MCP outputs.

Implements token counting and truncation to prevent context window overflow.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Default max output tokens (configurable via env)
DEFAULT_MAX_MCP_OUTPUT_TOKENS = 25000


def get_max_mcp_output_tokens() -> int:
    """
    Get the maximum allowed tokens for MCP output.

    Checks environment variable MAX_MCP_OUTPUT_TOKENS first,
    falls back to default.

    Returns:
        Maximum tokens allowed
    """
    from ....settings import get_settings
    _max = get_settings().max_mcp_output_tokens
    env_value = str(_max) if _max is not None else None
    if env_value:
        try:
            parsed = int(env_value)
            if parsed > 0:
                return parsed
        except ValueError:
            logger.warning(
                f"Invalid MAX_MCP_OUTPUT_TOKENS value: {env_value}, using default"
            )

    return DEFAULT_MAX_MCP_OUTPUT_TOKENS


def estimate_token_count(text: str) -> int:
    """
    Estimate token count for text.

    Uses rough 4-char-per-token heuristic. For more accurate counting,
    integrate with tiktoken or your framework's token counter.

    Args:
        text: Text to estimate

    Returns:
        Estimated token count
    """
    # Rough estimate: ~4 characters per token for English text
    return len(text) // 4


def estimate_content_blocks_tokens(content_blocks: list[dict[str, Any]]) -> int:
    """
    Estimate total tokens across multiple content blocks.

    Args:
        content_blocks: List of MCP content blocks

    Returns:
        Total estimated tokens
    """
    total = 0

    for block in content_blocks:
        block_type = block.get("type")

        if block_type == "text":
            text = block.get("text", "")
            total += estimate_token_count(text)

        elif block_type == "image":
            # Image blocks: rough estimate (Claude uses ~1600 tokens per image)
            total += 1600

        elif block_type == "resource":
            # Resource references are small
            total += 50

        else:
            # Unknown type: conservative estimate
            total += 100

    return total


class ContextBudgetGuard:
    """
    Guards LLM context window from oversized MCP outputs.

    Features:
    - Token counting for text content
    - Truncation with clear messaging
    - Binary content detection
    - Integration with McpOutputStorage for overflow
    """

    def __init__(
        self,
        max_tokens: int | None = None,
        truncation_message_template: str | None = None,
    ) -> None:
        """
        Initialize context budget guard.

        Args:
            max_tokens: Maximum tokens allowed (default: from env or 25000)
            truncation_message_template: Custom truncation message
        """
        self.max_tokens = max_tokens or get_max_mcp_output_tokens()
        self.truncation_message = truncation_message_template or (
            "\n\n[OUTPUT TRUNCATED - exceeded {max_tokens} token limit]\n\n"
            "The output was truncated. Use pagination or filtering if available. "
            "If this was a resource/tool output, it may have been saved to disk - "
            "check for file location in the response."
        )

    def check_and_truncate_text(
        self,
        text: str,
        server_name: str,
        tool_name: str,
    ) -> tuple[str, bool]:
        """
        Check text content and truncate if needed.

        Args:
            text: Text to check
            server_name: Server that produced the output
            tool_name: Tool that produced the output

        Returns:
            Tuple of (possibly_truncated_text, was_truncated)
        """
        token_count = estimate_token_count(text)

        if token_count <= self.max_tokens:
            return text, False

        # Calculate truncation point (chars)
        max_chars = self.max_tokens * 4  # Reverse the 4-char-per-token estimate
        truncated_text = text[:max_chars]

        # Add truncation message
        message = self.truncation_message.format(
            max_tokens=self.max_tokens,
            actual_tokens=token_count,
            server_name=server_name,
            tool_name=tool_name,
        )
        result = truncated_text + message

        logger.warning(
            f"Truncated output from {server_name}/{tool_name}: "
            f"{token_count} tokens → {self.max_tokens} tokens"
        )

        return result, True

    def _append_block_within_budget(
        self,
        block: dict[str, Any],
        result_blocks: list[dict[str, Any]],
        current_tokens: int,
    ) -> tuple[int, bool]:
        """Try to append a single block while respecting the token budget.

        Returns:
            Tuple of (updated_current_tokens, stop) where ``stop`` is True when
            the budget is exhausted and iteration should halt (truncation).
        """
        block_type = block.get("type")

        if block_type == "text":
            return self._append_text_block_within_budget(
                block, result_blocks, current_tokens
            )

        block_tokens = 1600 if block_type == "image" else 100
        if current_tokens + block_tokens > self.max_tokens:
            return current_tokens, True

        result_blocks.append(block)
        return current_tokens + block_tokens, False

    def _append_text_block_within_budget(
        self,
        block: dict[str, Any],
        result_blocks: list[dict[str, Any]],
        current_tokens: int,
    ) -> tuple[int, bool]:
        """Append a text block, truncating it if it exceeds the remaining budget."""
        text = block.get("text", "")
        block_tokens = estimate_token_count(text)

        if current_tokens + block_tokens <= self.max_tokens:
            result_blocks.append(block)
            return current_tokens + block_tokens, False

        # This block pushes us over - truncate it
        remaining_tokens = self.max_tokens - current_tokens
        if remaining_tokens > 100:  # Only include if meaningful space left
            remaining_chars = remaining_tokens * 4
            truncated_text = text[:remaining_chars]
            result_blocks.append({"type": "text", "text": truncated_text})
            current_tokens += remaining_tokens
        return current_tokens, True

    def check_and_truncate_content_blocks(
        self,
        content_blocks: list[dict[str, Any]],
        server_name: str,
        tool_name: str,
    ) -> tuple[list[dict[str, Any]], bool]:
        """
        Check content blocks and truncate if needed.

        Args:
            content_blocks: List of content blocks
            server_name: Server that produced output
            tool_name: Tool that produced output

        Returns:
            Tuple of (possibly_truncated_blocks, was_truncated)
        """
        total_tokens = estimate_content_blocks_tokens(content_blocks)

        if total_tokens <= self.max_tokens:
            return content_blocks, False

        # Truncate block by block until under budget
        result_blocks: list[dict[str, Any]] = []
        current_tokens = 0
        was_truncated = False

        for block in content_blocks:
            current_tokens, stop = self._append_block_within_budget(
                block, result_blocks, current_tokens
            )
            if stop:
                was_truncated = True
                break

        if was_truncated:
            # Add truncation notice as final text block
            message = self.truncation_message.format(
                max_tokens=self.max_tokens,
                actual_tokens=total_tokens,
                server_name=server_name,
                tool_name=tool_name,
            )
            result_blocks.append({"type": "text", "text": message})

            logger.warning(
                f"Truncated content blocks from {server_name}/{tool_name}: "
                f"{total_tokens} tokens → {self.max_tokens} tokens"
            )

        return result_blocks, was_truncated

    def is_oversized(self, text: str) -> bool:
        """
        Check if text exceeds token budget.

        Args:
            text: Text to check

        Returns:
            True if oversized
        """
        return estimate_token_count(text) > self.max_tokens

    def get_budget_summary(self, text: str) -> dict[str, Any]:
        """
        Get budget usage summary for text.

        Args:
            text: Text to analyze

        Returns:
            Dict with token counts and budget status
        """
        token_count = estimate_token_count(text)
        return {
            "tokens": token_count,
            "max_tokens": self.max_tokens,
            "percentage_used": (token_count / self.max_tokens) * 100,
            "is_oversized": token_count > self.max_tokens,
            "chars": len(text),
        }
