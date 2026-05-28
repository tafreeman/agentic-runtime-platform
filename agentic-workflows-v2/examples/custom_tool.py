"""Custom tool implementation and registration example.

Demonstrates how to:
1. Implement a tool by extending BaseTool
2. Register it with the ToolRegistry
3. Call the tool programmatically
4. Verify it satisfies the ToolProtocol

Run with: python examples/custom_tool.py

No API keys required — the tool is deterministic (tier 0).
"""

import asyncio
import logging
from typing import Any

from agentic_v2.core.protocols import ToolProtocol
from agentic_v2.tools.base import BaseTool, ToolResult
from agentic_v2.tools.registry import ToolRegistry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)s  %(levelname)s  %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Define a custom tool by extending BaseTool
# ---------------------------------------------------------------------------


class WordCountTool(BaseTool):
    """Count words, lines, and characters in a text string.

    A tier-0 (deterministic, no LLM) tool that demonstrates the
    BaseTool interface: name, description, parameters, and execute().
    """

    @property
    def name(self) -> str:
        return "word_count"

    @property
    def description(self) -> str:
        return "Count words, lines, and characters in text"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "text": {
                "type": "string",
                "description": "The text to analyze",
                "required": True,
            },
        }

    @property
    def returns(self) -> str:
        return "ToolResult with word_count, line_count, and char_count"

    async def execute(self, **kwargs: Any) -> ToolResult:
        text = kwargs.get("text", "")
        if not isinstance(text, str):
            return ToolResult(
                success=False,
                error=f"Expected string, got {type(text).__name__}",
            )

        words = text.split()
        lines = text.splitlines()
        return ToolResult(
            success=True,
            data={
                "word_count": len(words),
                "line_count": len(lines),
                "char_count": len(text),
                "avg_word_length": (
                    round(sum(len(w) for w in words) / len(words), 1) if words else 0.0
                ),
            },
        )


async def main() -> None:
    """Register the tool, verify protocol conformance, and call it."""

    tool = WordCountTool()

    # ── Protocol check ────────────────────────────────────────
    assert isinstance(tool, ToolProtocol), "WordCountTool must satisfy ToolProtocol"
    logger.info("WordCountTool satisfies ToolProtocol: True")

    # ── Register with ToolRegistry ────────────────────────────
    registry = ToolRegistry()
    registry.register(tool)

    retrieved = registry.get("word_count")
    assert retrieved is not None
    logger.info("Tool registered and retrieved: %s", retrieved.name)

    # ── Schema generation ─────────────────────────────────────
    schema = tool.get_schema()
    logger.info(
        "Schema: name=%s, tier=%d, params=%s",
        schema.name,
        schema.tier,
        list(schema.parameters.keys()),
    )

    # ── Execute the tool ──────────────────────────────────────
    sample_text = (
        "The quick brown fox jumps over the lazy dog.\n"
        "Pack my box with five dozen liquor jugs.\n"
        "How vexingly quick daft zebras jump.\n"
    )

    # Use __call__ to get automatic timing and tool_name metadata
    result = await tool(text=sample_text)
    logger.info("Result: success=%s", result.success)
    logger.info("  Data: %s", result.data)
    logger.info("  Execution time: %.2f ms", result.execution_time_ms)

    # ── Error handling ────────────────────────────────────────
    bad_result = await tool(text=42)  # type: ignore[arg-type]
    logger.info(
        "Bad input result: success=%s, error=%s", bad_result.success, bad_result.error
    )


if __name__ == "__main__":
    asyncio.run(main())
