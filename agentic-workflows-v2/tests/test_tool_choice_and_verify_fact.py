"""ARP-5: forced/``any``/``auto`` ``tool_choice`` + the cross-role ``verify_fact`` tool.

Covers:

* ``normalize_tool_choice`` for every accepted input shape (Tier 1: branches).
* ``build_tool_contracts`` returning the validated 3-tuple and failing fast on a
  forced tool that is not in the resolved set (Tier 1: error path).
* The four cloud backends forwarding ``tool_choice`` into their request payloads,
  including the OpenAI→Anthropic shape mapping (Tier 2: integration boundary).
* The native tool loop forcing a tool on turn 1 and reverting to ``auto`` after,
  so a forced choice cannot spin forever (Tier 1: the load-bearing edge case).
* ``verify_fact`` registration, tier-0 cross-role availability, and each
  verification mode (Tier 1/2: happy path + unsupported edge).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from agentic_v2.engine import agent_resolver
from agentic_v2.engine.tool_execution import (
    build_tool_contracts,
    complete_chat_with_fallback,
    normalize_tool_choice,
)
from agentic_v2.models.backends_cloud import (
    AnthropicBackend,
    AzureFoundryBackend,
    AzureOpenAIBackend,
    GitHubModelsBackend,
    OpenAIBackend,
    _to_anthropic_tool_choice,
)
from agentic_v2.models.router import ModelTier
from agentic_v2.tools import get_registry
from agentic_v2.tools.builtin.verify_fact import (
    VERDICT_SUPPORTED,
    VERDICT_UNSUPPORTED,
    VerifyFactTool,
)

_TIER = ModelTier.TIER_2
_SHARED_TOOLS = ["verify_fact", "search"]


def _mock_client(handler: Any, **kwargs: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)


# ---------------------------------------------------------------------------
# normalize_tool_choice
# ---------------------------------------------------------------------------


class TestNormalizeToolChoice:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, "auto"),
            ("auto", "auto"),
            ("", "auto"),
            ("any", "required"),
            ("required", "required"),
            ("none", "none"),
            ("ANY", "required"),  # case-insensitive
        ],
    )
    def test_bare_modes(self, value: Any, expected: str) -> None:
        assert normalize_tool_choice(value) == expected

    def test_tool_name_becomes_forced_openai_dict(self) -> None:
        assert normalize_tool_choice("verify_fact") == {
            "type": "function",
            "function": {"name": "verify_fact"},
        }

    def test_anthropic_forced_dict_normalizes_to_openai(self) -> None:
        assert normalize_tool_choice({"type": "tool", "name": "search"}) == {
            "type": "function",
            "function": {"name": "search"},
        }

    def test_openai_forced_dict_passthrough(self) -> None:
        choice = {"type": "function", "function": {"name": "search"}}
        assert normalize_tool_choice(choice) == choice

    def test_bare_mode_dict_normalizes_via_type(self) -> None:
        assert normalize_tool_choice({"type": "any"}) == "required"
        assert normalize_tool_choice({"type": "auto"}) == "auto"

    def test_forced_name_validated_against_available_set(self) -> None:
        # Allowed when present.
        assert normalize_tool_choice("verify_fact", {"verify_fact", "search"}) == {
            "type": "function",
            "function": {"name": "verify_fact"},
        }
        # Rejected when absent.
        with pytest.raises(ValueError, match="not in the available tool set"):
            normalize_tool_choice("ghost", {"verify_fact"})

    def test_unsupported_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported tool_choice"):
            normalize_tool_choice(123)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# build_tool_contracts — 3-tuple + validation
# ---------------------------------------------------------------------------


class TestBuildToolContractsChoice:
    def test_returns_three_tuple_with_normalized_choice(self) -> None:
        schemas, bound, choice = build_tool_contracts(_TIER, _SHARED_TOOLS, "auto")
        assert isinstance(schemas, list)
        assert "verify_fact" in bound and "search" in bound
        assert choice == "auto"

    @pytest.mark.parametrize(
        ("requested", "expected"),
        [
            ("any", "required"),
            ("required", "required"),
            ("none", "none"),
            ("verify_fact", {"type": "function", "function": {"name": "verify_fact"}}),
            (
                {"type": "tool", "name": "verify_fact"},
                {"type": "function", "function": {"name": "verify_fact"}},
            ),
        ],
    )
    def test_choice_forms_round_trip(self, requested: Any, expected: Any) -> None:
        _, _, choice = build_tool_contracts(_TIER, _SHARED_TOOLS, requested)
        assert choice == expected

    def test_forcing_unselected_tool_raises(self) -> None:
        # 'verify_fact' is excluded from the allowlist, so forcing it must fail.
        with pytest.raises(ValueError, match="not in the available tool set"):
            build_tool_contracts(_TIER, ["search"], "verify_fact")

    def test_default_choice_is_auto(self) -> None:
        _, _, choice = build_tool_contracts(_TIER, _SHARED_TOOLS)
        assert choice == "auto"


# ---------------------------------------------------------------------------
# Cloud backend payload threading
# ---------------------------------------------------------------------------


_OPENAI_RESPONSE = {
    "choices": [
        {"message": {"content": "ok", "tool_calls": None}, "finish_reason": "stop"}
    ],
    "model": "m",
    "usage": {"total_tokens": 3},
}
_FORCED = {"type": "function", "function": {"name": "verify_fact"}}
_TOOLS = [
    {
        "type": "function",
        "function": {"name": "verify_fact", "description": "", "parameters": {}},
    }
]


def _capture_handler(seen: dict[str, Any], response: dict[str, Any]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=response)

    return handler


class TestCloudBackendToolChoice:
    async def test_openai_forwards_forced_choice(self) -> None:
        seen: dict[str, Any] = {}
        backend = OpenAIBackend(api_key="k")
        backend._client = _mock_client(
            _capture_handler(seen, _OPENAI_RESPONSE),
            base_url="https://api.openai.com/v1",
        )
        await backend.complete_chat(
            "openai:gpt-4o",
            [{"role": "user", "content": "hi"}],
            tools=_TOOLS,
            tool_choice=_FORCED,
        )
        assert seen["body"]["tool_choice"] == _FORCED
        await backend.close()

    async def test_openai_defaults_to_auto(self) -> None:
        seen: dict[str, Any] = {}
        backend = OpenAIBackend(api_key="k")
        backend._client = _mock_client(
            _capture_handler(seen, _OPENAI_RESPONSE),
            base_url="https://api.openai.com/v1",
        )
        await backend.complete_chat(
            "openai:gpt-4o", [{"role": "user", "content": "hi"}], tools=_TOOLS
        )
        assert seen["body"]["tool_choice"] == "auto"
        await backend.close()

    async def test_github_forwards_required(self) -> None:
        seen: dict[str, Any] = {}
        backend = GitHubModelsBackend(token="t")
        backend._client = _mock_client(
            _capture_handler(seen, _OPENAI_RESPONSE),
            base_url="https://models.inference.ai.azure.com",
        )
        await backend.complete_chat(
            "gh:openai/gpt-4o-mini",
            [{"role": "user", "content": "hi"}],
            tools=_TOOLS,
            tool_choice="required",
        )
        assert seen["body"]["tool_choice"] == "required"
        await backend.close()

    async def test_azure_openai_forwards_forced_choice(self) -> None:
        seen: dict[str, Any] = {}
        backend = AzureOpenAIBackend(api_key="k", endpoint="https://r.openai.azure.com")
        backend._client = _mock_client(
            _capture_handler(seen, _OPENAI_RESPONSE),
            base_url="https://r.openai.azure.com",
        )
        await backend.complete_chat(
            "azure:gpt-4o",
            [{"role": "user", "content": "hi"}],
            tools=_TOOLS,
            tool_choice=_FORCED,
        )
        assert seen["body"]["tool_choice"] == _FORCED
        await backend.close()

    async def test_azure_foundry_forwards_forced_choice(self) -> None:
        seen: dict[str, Any] = {}
        backend = AzureFoundryBackend(
            api_key="k", endpoint="https://r.services.ai.azure.com/models"
        )
        backend._client = _mock_client(
            _capture_handler(seen, _OPENAI_RESPONSE),
            base_url="https://r.services.ai.azure.com/models",
        )
        await backend.complete_chat(
            "azure-foundry:phi4",
            [{"role": "user", "content": "hi"}],
            tools=_TOOLS,
            tool_choice=_FORCED,
        )
        assert seen["body"]["tool_choice"] == _FORCED
        await backend.close()


class TestAnthropicToolChoiceMapping:
    @pytest.mark.parametrize(
        ("openai_choice", "expected"),
        [
            ("auto", None),
            ("required", {"type": "any"}),
            ("any", {"type": "any"}),
            ("none", {"type": "none"}),
            (_FORCED, {"type": "tool", "name": "verify_fact"}),
            ({"type": "tool", "name": "search"}, {"type": "tool", "name": "search"}),
        ],
    )
    def test_mapping(self, openai_choice: Any, expected: Any) -> None:
        assert _to_anthropic_tool_choice(openai_choice) == expected

    async def test_anthropic_payload_forced(self) -> None:
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": "ok"}],
                    "stop_reason": "end_turn",
                    "model": "claude",
                    "usage": {},
                },
            )

        backend = AnthropicBackend(api_key="k")
        backend._client = _mock_client(handler, base_url="https://api.anthropic.com")
        await backend.complete_chat(
            "anthropic:claude",
            [{"role": "user", "content": "hi"}],
            tools=_TOOLS,
            tool_choice=_FORCED,
        )
        assert seen["body"]["tool_choice"] == {"type": "tool", "name": "verify_fact"}
        await backend.close()

    async def test_anthropic_payload_omits_choice_on_auto(self) -> None:
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": "ok"}],
                    "stop_reason": "end_turn",
                    "model": "claude",
                    "usage": {},
                },
            )

        backend = AnthropicBackend(api_key="k")
        backend._client = _mock_client(handler, base_url="https://api.anthropic.com")
        await backend.complete_chat(
            "anthropic:claude", [{"role": "user", "content": "hi"}], tools=_TOOLS
        )
        # Preserves the prior payload: no tool_choice key in the default path.
        assert "tool_choice" not in seen["body"]
        await backend.close()


# ---------------------------------------------------------------------------
# Native tool loop — forced on turn 1, auto after
# ---------------------------------------------------------------------------


class _RecordingClient:
    """Captures the tool_choice passed on each turn; ends the loop after one call."""

    def __init__(self) -> None:
        self.router = object()
        self.backend = object()
        self.budget = None
        self.choices: list[Any] = []

    async def complete_chat(self, **kwargs: Any) -> tuple[dict[str, Any], str, int]:
        self.choices.append(kwargs.get("tool_choice"))
        # First turn requests a tool call; later turns answer (terminate loop).
        if len(self.choices) == 1:
            return (
                {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "verify_fact", "arguments": "{}"},
                        }
                    ],
                },
                "model-x",
                7,
            )
        return ({"content": "done", "tool_calls": None}, "model-x", 5)


class _NoopTool:
    name = "verify_fact"

    def validate_parameters(self, **_kwargs: Any) -> tuple[bool, None]:
        return True, None

    async def execute(self, **_kwargs: Any) -> Any:
        from agentic_v2.tools import ToolResult

        return ToolResult(success=True, data={"verdict": "supported"})


async def test_native_loop_forces_first_turn_then_auto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Skip the approval gate for the in-loop tool execution.
    async def _allow(**_kwargs: Any) -> Any:
        class _Decision:
            allowed = True

        return _Decision()

    monkeypatch.setattr("agentic_v2.governance.approval.evaluate_tool_approval", _allow)

    client = _RecordingClient()
    forced = {"type": "function", "function": {"name": "verify_fact"}}
    (
        response,
        model_used,
        _tokens,
        tool_calls,
    ) = await agent_resolver._run_native_tool_loop(
        client=client,
        agent_name="tier2_reviewer",
        tier=_TIER,
        messages=[{"role": "user", "content": "verify"}],
        tool_schemas=_TOOLS,
        bound_tools={"verify_fact": _NoopTool()},
        max_tokens=128,
        tool_choice=forced,
    )

    assert response == "done"
    assert model_used == "model-x"
    assert tool_calls == 1
    # Forced on turn 1, auto on turn 2 — never forces forever.
    assert client.choices[0] == forced
    assert client.choices[1] == "auto"


# ---------------------------------------------------------------------------
# EK provider path: a forced tool_choice must RAISE, 'auto' passes through
# ---------------------------------------------------------------------------


class _FakeClient:
    """Client whose complete_chat records the forwarded tool_choice."""

    def __init__(self) -> None:
        self.backend = object()
        self.router = object()
        self.budget = None
        self.seen: list[Any] = []

    async def complete_chat(self, **kwargs: Any) -> tuple[dict[str, Any], str, int]:
        self.seen.append(kwargs.get("tool_choice"))
        return ({"content": "ok", "tool_calls": None}, "model-x", 3)


def _enable_ek_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn the EK completion path on via the real settings (env + cache reset).

    Avoids replacing ``get_settings`` itself (the autouse conftest fixture calls
    ``get_settings.cache_clear()`` on teardown, so a bare lambda would break it).
    Instead set the env flag and clear the cache so the genuine ``Settings``
    object reports ``agentic_ek_provider=True``.
    """
    from agentic_v2 import settings as settings_module

    monkeypatch.setenv("AGENTIC_EK_PROVIDER", "1")
    settings_module.get_settings.cache_clear()
    assert settings_module.get_settings().agentic_ek_provider is True


_FORCED_CHOICES: list[Any] = [
    "required",
    "any",
    {"type": "tool", "name": "verify_fact"},
    {"type": "function", "function": {"name": "verify_fact"}},
]


class TestEKProviderForcedToolChoice:
    """The opt-in EK completion path cannot honor a forced tool_choice."""

    @pytest.mark.parametrize("forced", _FORCED_CHOICES)
    async def test_forced_choice_raises_under_ek_provider(
        self, forced: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _enable_ek_provider(monkeypatch)
        client = _FakeClient()
        with pytest.raises(NotImplementedError, match="forces tool selection"):
            await complete_chat_with_fallback(
                client=client,
                tier=_TIER,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=64,
                tools=_TOOLS,
                tool_choice=forced,
            )

    @pytest.mark.parametrize("relaxed", ["auto", None, "none"])
    async def test_auto_passes_through_under_ek_provider(
        self, relaxed: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # An unforced choice must NOT raise the forced-choice error. With
        # executionkit absent the EK delegation import fails instead — which
        # proves 'auto'/'none'/None got PAST the forced-choice guard.
        _enable_ek_provider(monkeypatch)
        client = _FakeClient()
        try:
            await complete_chat_with_fallback(
                client=client,
                tier=_TIER,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=64,
                tools=_TOOLS,
                tool_choice=relaxed,
            )
        except NotImplementedError as exc:  # pragma: no cover - defensive
            pytest.fail(f"unforced choice {relaxed!r} must not raise: {exc}")
        except ImportError:
            # executionkit not installed: the guard was passed (expected) and the
            # EK delegation import is what failed — that is the pass-through path.
            pass

    async def test_forced_choice_without_tools_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No tools → tool_choice is irrelevant; the forced-choice guard is scoped
        # to ``tools`` being present, so a forced choice without tools must not
        # raise the NotImplementedError.
        _enable_ek_provider(monkeypatch)
        client = _FakeClient()
        try:
            await complete_chat_with_fallback(
                client=client,
                tier=_TIER,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=64,
                tools=None,
                tool_choice="required",
            )
        except NotImplementedError as exc:  # pragma: no cover - defensive
            pytest.fail(f"forced choice without tools must not raise: {exc}")
        except ImportError:
            pass


# ---------------------------------------------------------------------------
# verify_fact tool
# ---------------------------------------------------------------------------


class TestVerifyFactTool:
    def test_registered_and_tier_zero(self) -> None:
        tool = get_registry().get("verify_fact")
        assert isinstance(tool, VerifyFactTool)
        assert tool.tier == 0

    @pytest.mark.parametrize(
        "tier",
        [ModelTier.TIER_0, ModelTier.TIER_2, ModelTier.TIER_5],
    )
    def test_available_across_tiers(self, tier: ModelTier) -> None:
        _, bound, _ = build_tool_contracts(tier, ["verify_fact"], "auto")
        assert "verify_fact" in bound

    async def test_substring_supported(self) -> None:
        result = await VerifyFactTool().execute(
            claim="Q3 2026", evidence="Release is planned for Q3 2026."
        )
        assert result.success
        assert result.data["verdict"] == VERDICT_SUPPORTED
        assert result.data["matched_span"] == "Q3 2026"

    async def test_substring_unsupported(self) -> None:
        result = await VerifyFactTool().execute(
            claim="ships in Q1", evidence="Release is planned for Q3 2026."
        )
        assert result.data["verdict"] == VERDICT_UNSUPPORTED
        assert result.data["supported"] is False

    async def test_numeric_supported_and_unsupported(self) -> None:
        ok = await VerifyFactTool().execute(
            claim="latency is 42ms", evidence="measured 42ms p99", mode="numeric"
        )
        assert ok.data["supported"] is True

        bad = await VerifyFactTool().execute(
            claim="99.99% uptime", evidence="we saw 99.9% uptime", mode="numeric"
        )
        assert bad.data["supported"] is False
        assert bad.data["missing_numbers"] == ["99.99"]

    @pytest.mark.parametrize(
        ("claim", "evidence"),
        [
            ("the count is 100", "we recorded 100.0 events"),
            ("the count is 100.0", "we recorded 100 events"),
            ("total of 1,000 rows", "scanned 1000 rows"),
            ("total of 1000 rows", "scanned 1,000 rows"),
            ("ratio is .5", "the ratio was 0.5"),
            ("ratio is 0.5", "the ratio was .5"),
        ],
    )
    async def test_numeric_compares_values_not_strings(
        self, claim: str, evidence: str
    ) -> None:
        """Equal numbers written differently are treated as matching."""
        result = await VerifyFactTool().execute(
            claim=claim, evidence=evidence, mode="numeric"
        )
        assert result.data["supported"] is True
        assert result.data["missing_numbers"] == []

    async def test_exact_mode_matches_normalized_line(self) -> None:
        ok = await VerifyFactTool().execute(
            claim="status: green",
            evidence="header\n  status: green  \nfooter",
            mode="exact",
        )
        assert ok.data["supported"] is True

    async def test_unknown_mode_is_an_error(self) -> None:
        result = await VerifyFactTool().execute(
            claim="x", evidence="x", mode="semantic"
        )
        assert result.success is False
        assert "Unknown mode" in (result.error or "")
