"""Tests for agent_resolver -- agent name resolution, tier inference, and step function
generation.

Covers:
- Tier inference from agent name prefixes
- Tier-0 deterministic step resolution (TIER0_REGISTRY)
- LLM-backed step generation for higher tiers
- resolve_agent() with various StepDefinition configurations
- Error handling for missing agent names
- _parse_code_step deterministic implementation
- _noop_step fallback
- Edge cases: empty metadata, pre-assigned func, None inputs
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentic_v2.engine.agent_resolver import (
    TIER0_REGISTRY,
    _infer_tier,
    _make_llm_step,
    _noop_step,
    _parse_code_step,
    resolve_agent,
)
from agentic_v2.engine.context import ExecutionContext
from agentic_v2.engine.step import StepDefinition
from agentic_v2.models.router import ModelTier

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def make_context(tmp_path):
    """Create a minimal ExecutionContext for testing."""

    def _factory(**variables: Any) -> ExecutionContext:
        ctx = ExecutionContext()
        for k, v in variables.items():
            ctx.set_sync(k, v)
        return ctx

    return _factory


@pytest.fixture()
def make_step() -> Any:
    """Create a StepDefinition with sensible defaults."""

    def _factory(
        name: str = "test_step",
        agent: str | None = None,
        description: str = "A test step",
        func: Any = None,
        output_mapping: dict[str, str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StepDefinition:
        meta = metadata or {}
        if agent is not None:
            meta["agent"] = agent
        return StepDefinition(
            name=name,
            description=description,
            func=func,
            output_mapping=output_mapping or {},
            metadata=meta,
        )

    return _factory


# ---------------------------------------------------------------------------
# _infer_tier
# ---------------------------------------------------------------------------


class TestInferTier:
    """Tests for tier inference from agent name convention."""

    @pytest.mark.parametrize(
        "agent_name,expected_tier",
        [
            ("tier0_parser", ModelTier.TIER_0),
            ("tier1_helper", ModelTier.TIER_1),
            ("tier2_coder", ModelTier.TIER_2),
            ("tier3_architect", ModelTier.TIER_3),
            ("tier4_reviewer", ModelTier.TIER_4),
            ("tier5_premium", ModelTier.TIER_5),
        ],
    )
    def test_explicit_tier_prefix(self, agent_name: str, expected_tier: ModelTier):
        """Each tier{N}_ prefix maps to the correct ModelTier."""
        assert _infer_tier(agent_name) == expected_tier

    def test_default_tier_when_no_prefix(self):
        """Agent names without a tier prefix default to TIER_2."""
        assert _infer_tier("custom_agent") == ModelTier.TIER_2

    def test_default_tier_empty_string(self):
        """Empty string should default to TIER_2."""
        assert _infer_tier("") == ModelTier.TIER_2

    def test_partial_prefix_not_matched(self):
        """Partial prefix like 'tier' without a digit defaults to TIER_2."""
        assert _infer_tier("tier_agent") == ModelTier.TIER_2

    def test_tier_prefix_case_sensitive(self):
        """Tier prefix is case-sensitive -- 'TIER0_' should default to TIER_2."""
        assert _infer_tier("TIER0_parser") == ModelTier.TIER_2


# ---------------------------------------------------------------------------
# TIER0_REGISTRY
# ---------------------------------------------------------------------------


class TestTier0Registry:
    """Tests for the tier-0 deterministic step registry."""

    def test_tier0_parser_registered(self):
        """tier0_parser should be in the registry."""
        assert "tier0_parser" in TIER0_REGISTRY

    def test_registry_functions_are_callable(self):
        """All registry entries must be callable."""
        for name, func in TIER0_REGISTRY.items():
            assert callable(func), f"{name} is not callable"


# ---------------------------------------------------------------------------
# _parse_code_step
# ---------------------------------------------------------------------------


class TestParseCodeStep:
    """Tests for the tier-0 deterministic code parser."""

    async def test_parse_valid_python_file(self, tmp_path, make_context):
        """Should extract functions, classes, and imports from a Python file."""
        source = tmp_path / "example.py"
        source.write_text("import os\n\nclass Foo:\n    pass\n\ndef bar():\n    pass\n")
        ctx = make_context(file_path=str(source))
        result = await _parse_code_step(ctx)

        assert "parsed_ast" in result
        assert "code_metrics" in result
        assert result["parsed_ast"]["language"] == "python"
        assert "Foo" in result["parsed_ast"]["classes"]
        assert "bar" in result["parsed_ast"]["functions"]

    async def test_parse_nonexistent_file_uses_inline(self, make_context):
        """When file_path doesn't exist on disk, raw string is used as source."""
        ctx = make_context(file_path="def hello(): pass")
        result = await _parse_code_step(ctx)

        assert "parsed_ast" in result
        # Inline code treated as Python if it parses
        assert "hello" in result["parsed_ast"].get("functions", [])

    async def test_parse_non_python_source(self, make_context):
        """Non-Python source sets language to 'unknown' and notes parse error."""
        ctx = make_context(file_path="function hello() { return 42; }")
        result = await _parse_code_step(ctx)

        assert result["parsed_ast"]["language"] == "unknown"
        assert "parse_error" in result["parsed_ast"]

    async def test_parse_empty_context(self):
        """With no file_path in context, should return metrics for empty source."""
        ctx = ExecutionContext()
        result = await _parse_code_step(ctx)

        assert result["code_metrics"]["lines"] == 0
        assert result["code_metrics"]["chars"] == 0

    async def test_parse_via_code_file_key(self, tmp_path, make_context):
        """Should also accept 'code_file' context key as fallback."""
        source = tmp_path / "alt.py"
        source.write_text("x = 1\n")
        ctx = make_context(code_file=str(source))
        result = await _parse_code_step(ctx)

        assert result["code_metrics"]["lines"] == 1


# ---------------------------------------------------------------------------
# _noop_step
# ---------------------------------------------------------------------------


class TestNoopStep:
    """Tests for the no-op fallback step."""

    async def test_returns_empty_dict(self):
        """_noop_step always returns an empty dict."""
        ctx = ExecutionContext()
        result = await _noop_step(ctx)
        assert result == {}


# ---------------------------------------------------------------------------
# _make_llm_step
# ---------------------------------------------------------------------------


class TestMakeLlmStep:
    """Tests for the LLM step factory function."""

    @patch(
        "agentic_v2.engine.agent_resolver.load_agent_system_prompt", return_value=None
    )
    def test_returns_callable(self, mock_prompt):
        """_make_llm_step returns an async callable."""
        step_fn = _make_llm_step(
            agent_name="tier2_coder",
            description="Write code",
            tier=ModelTier.TIER_2,
        )
        assert callable(step_fn)

    @patch(
        "agentic_v2.engine.agent_resolver.load_agent_system_prompt", return_value=None
    )
    def test_qualname_contains_agent_name(self, mock_prompt):
        """The generated function's qualname identifies the agent."""
        step_fn = _make_llm_step(
            agent_name="tier3_architect",
            description="Design system",
            tier=ModelTier.TIER_3,
        )
        assert "tier3_architect" in step_fn.__qualname__

    @patch(
        "agentic_v2.engine.agent_resolver.load_agent_system_prompt", return_value=None
    )
    @patch(
        "agentic_v2.engine.agent_resolver.build_tool_contracts",
        return_value=([], {}, "auto"),
    )
    @patch(
        "agentic_v2.engine.agent_resolver.build_system_prompt",
        return_value="test prompt",
    )
    async def test_llm_unavailable_returns_placeholder(
        self, mock_build, mock_tools, mock_prompt
    ):
        """When no LLM client is available, step returns placeholder dict."""
        step_fn = _make_llm_step(
            agent_name="tier2_coder",
            description="Write code",
            tier=ModelTier.TIER_2,
        )
        ctx = ExecutionContext()
        # Force the "no LLM configured" path deterministically. The closure does
        # `from ..models.client import get_client` at call time, so patch it to
        # raise (matching this test's intent). Without this, a leaked
        # AGENTIC_NO_LLM=1 makes get_client return a placeholder MockBackend
        # instead of raising, so the step never reaches the llm_unavailable
        # branch and the result has no 'status' key (order-dependent failure).
        with patch(
            "agentic_v2.models.client.get_client",
            side_effect=RuntimeError("No LLM backend configured"),
        ):
            result = await step_fn(ctx)
        assert result["status"] == "llm_unavailable"
        assert result["agent"] == "tier2_coder"

    @patch(
        "agentic_v2.engine.agent_resolver.load_agent_system_prompt",
        return_value="You are a coder.",
    )
    @patch(
        "agentic_v2.engine.agent_resolver.build_tool_contracts",
        return_value=([], {}, "auto"),
    )
    @patch(
        "agentic_v2.engine.agent_resolver.build_system_prompt",
        return_value="test prompt",
    )
    @patch("agentic_v2.engine.agent_resolver.complete_chat_with_fallback")
    async def test_successful_llm_call_parses_output(
        self, mock_chat, mock_build, mock_tools, mock_prompt
    ):
        """When LLM responds, result is parsed and includes _meta."""
        mock_chat.return_value = (
            {
                "content": '<<<ARTIFACT review>>>\n{"status": "ok"}\n<<<ENDARTIFACT>>>',
                "tool_calls": None,
            },
            "gpt-4o-mini",
            150,
        )

        step_fn = _make_llm_step(
            agent_name="tier2_coder",
            description="Write code",
            tier=ModelTier.TIER_2,
            expected_output_keys=["review"],
        )

        # Patch get_client at the import location inside the closure
        # The closure does `from ..models.client import get_client` at call time
        mock_client_module = MagicMock()
        mock_client_module.get_client.return_value = MagicMock()
        with patch.dict(
            "sys.modules", {"agentic_v2.models.client": mock_client_module}
        ):
            ctx = ExecutionContext()
            result = await step_fn(ctx)

        assert "_meta" in result
        assert result["_meta"]["model_used"] == "gpt-4o-mini"
        assert result["_meta"]["tokens_used"] == 150


# ---------------------------------------------------------------------------
# resolve_agent
# ---------------------------------------------------------------------------


class TestResolveAgent:
    """Tests for the main resolve_agent function."""

    def test_already_has_func_is_noop(self, make_step):
        """If step_def.func is already set, resolve_agent returns it unchanged."""
        existing_func = AsyncMock()
        step = make_step(func=existing_func, agent="tier2_coder")
        resolved = resolve_agent(step)
        assert resolved.func is existing_func

    def test_tier0_agent_uses_registry(self, make_step):
        """Tier-0 agent names are resolved from TIER0_REGISTRY."""
        step = make_step(agent="tier0_parser")
        resolved = resolve_agent(step)
        assert resolved.func is TIER0_REGISTRY["tier0_parser"]
        assert resolved.tier == ModelTier.TIER_0

    @patch(
        "agentic_v2.engine.agent_resolver.load_agent_system_prompt", return_value=None
    )
    def test_tier2_agent_generates_llm_step(self, mock_prompt, make_step):
        """Tier-2 agent generates an LLM-backed step function."""
        step = make_step(agent="tier2_coder", output_mapping={"code": "result_code"})
        resolved = resolve_agent(step)
        assert resolved.func is not None
        assert resolved.tier == ModelTier.TIER_2
        assert callable(resolved.func)

    def test_missing_agent_raises_value_error(self, make_step):
        """Step with no agent and no func raises ValueError."""
        step = make_step()  # no agent, no func
        with pytest.raises(ValueError, match="has no agent and no func"):
            resolve_agent(step)

    @patch(
        "agentic_v2.engine.agent_resolver.load_agent_system_prompt", return_value=None
    )
    def test_tier_is_set_on_step(self, mock_prompt, make_step):
        """resolve_agent sets the tier field on the step definition."""
        step = make_step(agent="tier3_architect")
        resolve_agent(step)
        assert step.tier == ModelTier.TIER_3

    @patch(
        "agentic_v2.engine.agent_resolver.load_agent_system_prompt", return_value=None
    )
    def test_unknown_tier0_agent_falls_to_llm(self, mock_prompt, make_step):
        """A tier0_ agent not in TIER0_REGISTRY still generates an LLM step."""
        step = make_step(agent="tier0_unknown_agent")
        resolved = resolve_agent(step)
        # Not in TIER0_REGISTRY, but tier is TIER_0; falls through to _make_llm_step
        assert resolved.func is not None
        assert resolved.tier == ModelTier.TIER_0
        assert resolved.func is not TIER0_REGISTRY.get("tier0_unknown_agent")

    @patch(
        "agentic_v2.engine.agent_resolver.load_agent_system_prompt", return_value=None
    )
    def test_prompt_file_override_passed_through(self, mock_prompt, make_step):
        """prompt_file metadata is forwarded to _make_llm_step."""
        step = make_step(
            agent="tier2_coder",
            metadata={"agent": "tier2_coder", "prompt_file": "custom_coder.md"},
        )
        resolve_agent(step)
        # The load_agent_system_prompt should have been called with the override
        mock_prompt.assert_called_once_with("tier2_coder", "custom_coder.md")

    @patch(
        "agentic_v2.engine.agent_resolver.load_agent_system_prompt", return_value=None
    )
    def test_tools_metadata_passed_through(self, mock_prompt, make_step):
        """Tools metadata is forwarded to _make_llm_step."""
        step = make_step(
            agent="tier2_coder",
            metadata={"agent": "tier2_coder", "tools": ["file_read", "file_write"]},
        )
        resolved = resolve_agent(step)
        assert resolved.func is not None


# ---------------------------------------------------------------------------
# Backward-compatibility aliases
# ---------------------------------------------------------------------------


class TestBackwardCompatAliases:
    """Verify re-exported aliases still resolve."""

    def test_sentinel_instructions_alias(self):
        """_SENTINEL_OUTPUT_INSTRUCTIONS alias matches canonical constant."""
        from agentic_v2.engine.agent_resolver import (
            _SENTINEL_OUTPUT_INSTRUCTIONS,
            SENTINEL_OUTPUT_INSTRUCTIONS,
        )

        assert _SENTINEL_OUTPUT_INSTRUCTIONS is SENTINEL_OUTPUT_INSTRUCTIONS

    def test_max_tool_rounds_alias(self):
        """_MAX_TOOL_ROUNDS alias matches canonical constant."""
        from agentic_v2.engine.agent_resolver import (
            _MAX_TOOL_ROUNDS,
            MAX_TOOL_ROUNDS,
        )

        assert _MAX_TOOL_ROUNDS == MAX_TOOL_ROUNDS

    def test_tier_max_tokens_has_all_tiers(self):
        """_TIER_MAX_TOKENS covers all ModelTier values."""
        from agentic_v2.engine.agent_resolver import _TIER_MAX_TOKENS

        for tier in ModelTier:
            assert tier in _TIER_MAX_TOKENS, f"Missing tier {tier.name}"
