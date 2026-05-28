"""Tests for tools/builtin/context_ops.py — ADR-008 Phase 3.

Covers _estimate_tokens, TokenEstimateTool, and ContextTrimTool.

Test tiers (per ADR-008):   Tier 1 — error paths, branching, boundary
conditions   Tier 2 — happy-path contracts
"""

from __future__ import annotations

import pytest
from agentic_v2.tools.builtin.context_ops import (
    ContextTrimTool,
    TokenEstimateTool,
    _estimate_tokens,
)

# ===================================================================
# _estimate_tokens — unit tests
# ===================================================================


class TestEstimateTokens:
    """Tier 1/2: heuristic token estimator."""

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("", 0),
            ("hi", 1),  # 2 chars // 4 = 0, but max(1, 0) = 1
            ("a" * 4, 1),
            ("a" * 8, 2),
            ("a" * 100, 25),
        ],
        ids=["empty", "short-min-1", "exactly-4", "exactly-8", "hundred"],
    )
    def test_estimate_tokens_values(self, text: str, expected: int) -> None:
        """Tier 2: verify heuristic at key boundary values."""
        assert _estimate_tokens(text) == expected


# ===================================================================
# TokenEstimateTool — async execute()
# ===================================================================


class TestTokenEstimateTool:
    """Tier 2: token estimate tool contract."""

    async def test_execute_returns_token_and_char_count(self) -> None:
        """Tier 2: execute returns both tokens and chars."""
        tool = TokenEstimateTool()
        text = "hello world"  # 11 chars -> max(1, 11//4) = 2
        result = await tool.execute(text=text)
        assert result.success is True
        assert result.data["chars"] == 11
        assert result.data["tokens"] == 2

    async def test_execute_empty_string(self) -> None:
        """Tier 1: empty string yields tokens=1 (min clamp inside execute)."""
        tool = TokenEstimateTool()
        result = await tool.execute(text="")
        assert result.success is True
        # Inside execute: max(1, 0//4) = 1
        assert result.data["tokens"] == 1

    async def test_name_and_description(self) -> None:
        """Tier 2: tool metadata is correct."""
        tool = TokenEstimateTool()
        assert tool.name == "token_estimate"
        assert "token" in tool.description.lower()


# ===================================================================
# ContextTrimTool — async execute()
# ===================================================================


class TestContextTrimToolNoTrim:
    """Tier 2: text that fits within the budget is returned untouched."""

    async def test_short_text_not_trimmed(self) -> None:
        """Tier 2: text within budget returns trimmed=False."""
        tool = ContextTrimTool()
        text = "short"  # 5 chars, fits in max_tokens=100 (400 chars budget)
        result = await tool.execute(text=text, max_tokens=100)
        assert result.success is True
        assert result.data["trimmed"] is False
        assert result.data["text"] == text

    async def test_exact_boundary_not_trimmed(self) -> None:
        """Tier 1: text exactly at the char budget is not trimmed."""
        tool = ContextTrimTool()
        text = "x" * 400  # max_tokens=100 -> max_chars=400
        result = await tool.execute(text=text, max_tokens=100)
        assert result.success is True
        assert result.data["trimmed"] is False


class TestContextTrimToolTrims:
    """Tier 1: text exceeding budget is trimmed with head/tail/marker."""

    async def test_basic_trim(self) -> None:
        """Tier 2: long text is trimmed; head + marker + tail returned."""
        tool = ContextTrimTool()
        text = "A" * 2000  # well over max_tokens=50 (200 chars)
        result = await tool.execute(
            text=text, max_tokens=50, head_tokens=10, tail_tokens=10
        )
        assert result.success is True
        data = result.data
        assert data["trimmed"] is True
        assert data["text"].startswith("A" * 40)  # head_tokens=10 * 4 = 40 chars
        assert data["text"].endswith("A" * 40)  # tail_tokens=10 * 4 = 40 chars
        assert "truncated" in data["text"]  # marker present

    async def test_custom_marker(self) -> None:
        """Tier 2: custom marker string is used."""
        tool = ContextTrimTool()
        text = "B" * 2000
        marker = "<<SNIP>>"
        result = await tool.execute(
            text=text, max_tokens=50, head_tokens=10, tail_tokens=10, marker=marker
        )
        assert result.success is True
        assert marker in result.data["text"]

    async def test_tail_tokens_default_fills_remaining_budget(self) -> None:
        """Tier 1: when tail_tokens is omitted, it fills max_tokens - head_tokens."""
        tool = ContextTrimTool()
        text = "C" * 2000
        result = await tool.execute(text=text, max_tokens=100, head_tokens=30)
        assert result.success is True
        data = result.data
        assert data["trimmed"] is True
        # tail_tokens should be max(0, 100 - 30) = 70
        assert data["tail_tokens"] == 70

    async def test_zero_tail_tokens_no_tail(self) -> None:
        """Tier 1: tail_tokens=0 produces no tail section."""
        tool = ContextTrimTool()
        text = "D" * 2000
        result = await tool.execute(
            text=text, max_tokens=50, head_tokens=10, tail_tokens=0
        )
        assert result.success is True
        # The text should be head + marker (no tail content)
        assert result.data["tail_tokens"] == 0


class TestContextTrimToolErrors:
    """Tier 1: error-path validation."""

    @pytest.mark.parametrize(
        "kwargs, error_fragment",
        [
            ({"text": "x", "max_tokens": 0}, "max_tokens must be > 0"),
            ({"text": "x", "max_tokens": -5}, "max_tokens must be > 0"),
            (
                {"text": "x", "max_tokens": 10, "head_tokens": -1},
                "head_tokens must be >= 0",
            ),
            (
                {"text": "x", "max_tokens": 10, "tail_tokens": -1},
                "tail_tokens must be >= 0",
            ),
        ],
        ids=["zero-max", "neg-max", "neg-head", "neg-tail"],
    )
    async def test_invalid_params_return_failure(
        self, kwargs: dict, error_fragment: str
    ) -> None:
        """Tier 1: invalid parameters return success=False with descriptive error."""
        tool = ContextTrimTool()
        result = await tool.execute(**kwargs)
        assert result.success is False
        assert error_fragment in result.error
