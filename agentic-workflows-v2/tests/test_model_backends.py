"""ADR-008 Phase 2: tests for models/backends.py

Comprehensive tests for MultiBackend dispatcher, MockBackend,
get_backend factory, auto_configure_backend, and PREFIX_MAP.

Tier 1: logic branches, error paths, edge cases.
Tier 2: happy-path contracts, integration boundaries.
"""

from __future__ import annotations

import sys
from typing import Any, AsyncIterator
from unittest.mock import patch

import pytest
from agentic_v2.models.backends import (
    PREFIX_MAP,
    AnthropicBackend,
    GeminiBackend,
    GitHubModelsBackend,
    MockBackend,
    MultiBackend,
    OllamaBackend,
    OpenAIBackend,
    auto_configure_backend,
    get_backend,
)
from agentic_v2.models.backends_base import LLMBackend
from agentic_v2.models.secrets import MappingSecretProvider

# Env vars cleared in auto_configure tests
_PROVIDER_ENV_VARS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GEMINI_API_KEY",
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class StubBackend(LLMBackend):
    """Minimal concrete backend for testing MultiBackend delegation."""

    def __init__(self, name: str = "stub") -> None:
        self.name = name
        self.complete_calls: list[dict[str, Any]] = []
        self.chat_calls: list[dict[str, Any]] = []
        self.closed = False

    async def complete(
        self,
        model: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        self.complete_calls.append(
            {"model": model, "prompt": prompt, "max_tokens": max_tokens, **kwargs}
        )
        return f"{self.name}:{model}:{prompt}"

    async def complete_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.chat_calls.append({"model": model, "messages": messages, "tools": tools})
        return {"content": f"{self.name}_chat:{model}", "tool_calls": None}

    async def complete_stream(
        self, model: str, prompt: str, **kwargs: Any
    ) -> AsyncIterator[str]:
        yield f"chunk1:{self.name}:{model}"
        yield f"chunk2:{self.name}:{model}"

    async def close(self) -> None:
        self.closed = True


class StubBackendNoClose(LLMBackend):
    """Backend without a close method -- tests the hasattr guard in
    MultiBackend.close."""

    async def complete(
        self,
        model: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        return "no-close"

    async def complete_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return {"content": "no-close", "tool_calls": None}


# ---------------------------------------------------------------------------
# PREFIX_MAP
# ---------------------------------------------------------------------------


class TestPrefixMap:
    """Verify PREFIX_MAP is complete and correct."""

    def test_contains_all_expected_prefixes(self) -> None:
        expected = {"gh:", "openai:", "anthropic:", "gemini:", "ollama:", "local:"}
        assert set(PREFIX_MAP.keys()) == expected

    def test_local_prefix_routes_through_ollama(self) -> None:
        """local: models should be served by the same Ollama backend."""
        assert PREFIX_MAP["local:"] == "ollama"

    @pytest.mark.parametrize(
        "prefix,provider",
        [
            ("gh:", "github"),
            ("openai:", "openai"),
            ("anthropic:", "anthropic"),
            ("gemini:", "gemini"),
            ("ollama:", "ollama"),
        ],
    )
    def test_prefix_maps_to_correct_provider(self, prefix: str, provider: str) -> None:
        assert PREFIX_MAP[prefix] == provider


# ---------------------------------------------------------------------------
# MultiBackend._get_backend  (routing logic)
# ---------------------------------------------------------------------------


class TestMultiBackendRouting:
    """Tests for MultiBackend prefix-based routing logic."""

    @pytest.mark.parametrize(
        "model,provider_key",
        [
            ("gh:openai/gpt-4o", "github"),
            ("openai:gpt-4o", "openai"),
            ("anthropic:claude-3-opus", "anthropic"),
            ("gemini:gemini-1.5-pro", "gemini"),
            ("ollama:llama3", "ollama"),
            ("local:phi3", "ollama"),
        ],
    )
    def test_routes_prefixed_model_to_correct_backend(
        self, model: str, provider_key: str
    ) -> None:
        """Each prefix in PREFIX_MAP resolves to the corresponding backend."""
        backend = StubBackend(provider_key)
        multi = MultiBackend(backends={provider_key: backend})
        assert multi._get_backend(model) is backend

    def test_bare_model_name_falls_back_to_openai(self) -> None:
        """Models without a prefix (e.g. 'gpt-4o') default to OpenAI."""
        openai = StubBackend("openai")
        multi = MultiBackend(backends={"openai": openai, "github": StubBackend("gh")})
        assert multi._get_backend("gpt-4o") is openai

    def test_raises_when_matched_provider_not_configured(self) -> None:
        """Error when prefix matches but that provider's backend is absent."""
        multi = MultiBackend(backends={"openai": StubBackend("openai")})
        with pytest.raises(
            RuntimeError, match="No backend configured for provider 'github'"
        ):
            multi._get_backend("gh:gpt-4o")

    def test_raises_when_no_prefix_and_no_openai_fallback(self) -> None:
        """Error when bare model name used and OpenAI backend absent."""
        multi = MultiBackend(backends={"github": StubBackend("github")})
        with pytest.raises(RuntimeError, match="Cannot determine backend"):
            multi._get_backend("gpt-4o")

    def test_error_lists_available_backends(self) -> None:
        """RuntimeError message includes available backend names."""
        multi = MultiBackend(backends={"github": StubBackend("gh")})
        with pytest.raises(RuntimeError, match="github"):
            multi._get_backend("bare-model")


# ---------------------------------------------------------------------------
# MultiBackend delegation (complete, complete_chat, complete_stream, close)
# ---------------------------------------------------------------------------


class TestMultiBackendDelegation:
    """Tests that MultiBackend delegates calls to the resolved backend."""

    async def test_complete_delegates_and_returns_result(self) -> None:
        stub = StubBackend("openai")
        multi = MultiBackend(backends={"openai": stub})
        result = await multi.complete("openai:gpt-4o", "hello")
        assert result == "openai:openai:gpt-4o:hello"
        assert len(stub.complete_calls) == 1

    async def test_complete_forwards_kwargs(self) -> None:
        stub = StubBackend("openai")
        multi = MultiBackend(backends={"openai": stub})
        await multi.complete("openai:gpt-4o", "p", extra="val")
        assert stub.complete_calls[0]["extra"] == "val"

    async def test_complete_chat_delegates_and_returns_result(self) -> None:
        stub = StubBackend("anthropic")
        multi = MultiBackend(backends={"anthropic": stub})
        msgs = [{"role": "user", "content": "hi"}]
        result = await multi.complete_chat("anthropic:claude-3", msgs)
        assert result["content"] == "anthropic_chat:anthropic:claude-3"
        assert len(stub.chat_calls) == 1

    async def test_complete_stream_yields_all_chunks(self) -> None:
        stub = StubBackend("openai")
        multi = MultiBackend(backends={"openai": stub})
        chunks = [c async for c in multi.complete_stream("openai:gpt-4o", "prompt")]
        assert len(chunks) == 2
        assert all("openai" in c for c in chunks)

    async def test_close_closes_all_backends_with_close_method(self) -> None:
        s1 = StubBackend("a")
        s2 = StubBackend("b")
        multi = MultiBackend(backends={"openai": s1, "github": s2})
        await multi.close()
        assert s1.closed is True
        assert s2.closed is True

    async def test_close_skips_backends_without_close_method(self) -> None:
        """Backends that lack a close() method should not cause errors."""
        no_close = StubBackendNoClose()
        with_close = StubBackend("closeable")
        multi = MultiBackend(backends={"a": no_close, "b": with_close})
        await multi.close()  # should not raise
        assert with_close.closed is True


# ---------------------------------------------------------------------------
# MockBackend
# ---------------------------------------------------------------------------


class TestMockBackend:
    """Tests for the MockBackend used in testing."""

    async def test_complete_returns_default_response(self) -> None:
        mock = MockBackend()
        result = await mock.complete("test-model", "any prompt")
        assert result == "This is a mock response."

    async def test_complete_returns_pattern_matched_response(self) -> None:
        mock = MockBackend()
        mock.set_response("capital", "Paris")
        result = await mock.complete("m", "What is the capital of France?")
        assert result == "Paris"

    async def test_pattern_matching_is_case_insensitive(self) -> None:
        mock = MockBackend()
        mock.set_response("HELLO", "world")
        result = await mock.complete("m", "hello there")
        assert result == "world"

    async def test_first_matching_pattern_wins(self) -> None:
        """When multiple patterns match, the first-inserted one wins."""
        mock = MockBackend()
        mock.set_response("hello", "first")
        mock.set_response("hello world", "second")
        result = await mock.complete("m", "hello world")
        assert result == "first"

    async def test_complete_records_call_history(self) -> None:
        mock = MockBackend()
        await mock.complete("model-x", "prompt-y", extra_key="ev")
        assert len(mock.call_history) == 1
        entry = mock.call_history[0]
        assert entry["method"] == "complete"
        assert entry["model"] == "model-x"
        assert entry["prompt"] == "prompt-y"
        assert entry["kwargs"] == {"extra_key": "ev"}

    async def test_complete_chat_returns_default_with_correct_structure(self) -> None:
        mock = MockBackend()
        msgs = [{"role": "user", "content": "hi"}]
        result = await mock.complete_chat("m", msgs)
        assert result["content"] == "This is a mock response."
        assert result["tool_calls"] is None

    async def test_complete_chat_matches_last_user_message(self) -> None:
        mock = MockBackend()
        mock.set_response("weather", "sunny")
        msgs = [
            {"role": "system", "content": "system msg"},
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "what's the weather?"},
        ]
        result = await mock.complete_chat("m", msgs)
        assert result["content"] == "sunny"

    async def test_complete_chat_no_user_messages_returns_default(self) -> None:
        """When no user message exists, pattern matching gets empty string."""
        mock = MockBackend()
        mock.set_response("nope", "should not match")
        msgs = [{"role": "system", "content": "sys"}]
        result = await mock.complete_chat("m", msgs)
        assert result["content"] == "This is a mock response."

    async def test_complete_chat_records_call_history(self) -> None:
        mock = MockBackend()
        tools = [{"type": "function", "function": {"name": "t"}}]
        msgs = [{"role": "user", "content": "q"}]
        await mock.complete_chat("model-z", msgs, tools=tools, extra="v")
        assert len(mock.call_history) == 1
        entry = mock.call_history[0]
        assert entry["method"] == "complete_chat"
        assert entry["tools"] == tools
        assert entry["kwargs"] == {"extra": "v"}


# ---------------------------------------------------------------------------
# get_backend factory
# ---------------------------------------------------------------------------


class TestGetBackendFactory:
    """Tests for the get_backend() factory function."""

    @pytest.mark.parametrize(
        "provider,env_vars,expected_type",
        [
            ("github", {"GITHUB_TOKEN": "test-tok"}, GitHubModelsBackend),
            ("openai", {"OPENAI_API_KEY": "test-key"}, OpenAIBackend),
            ("anthropic", {"ANTHROPIC_API_KEY": "test-key"}, AnthropicBackend),
            ("gemini", {"GEMINI_API_KEY": "test-key"}, GeminiBackend),
            ("ollama", {}, OllamaBackend),
            ("mock", {}, MockBackend),
        ],
    )
    def test_returns_correct_backend_type(
        self,
        provider: str,
        env_vars: dict[str, str],
        expected_type: type,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        for key, val in env_vars.items():
            monkeypatch.setenv(key, val)
        result = get_backend(provider)
        assert isinstance(result, expected_type)

    def test_unknown_provider_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown provider: nope"):
            get_backend("nope")

    def test_supports_explicit_secret_provider(self) -> None:
        provider = MappingSecretProvider({"OPENAI_API_KEY": "provider-key"})
        result = get_backend("openai", secret_provider=provider)
        assert isinstance(result, OpenAIBackend)
        assert result.api_key == "provider-key"


# ---------------------------------------------------------------------------
# auto_configure_backend
# ---------------------------------------------------------------------------


class TestAutoConfigureBackend:
    """Tests for the auto_configure_backend() factory."""

    @pytest.fixture(autouse=True)
    def _clean_provider_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Remove all provider env vars to start with a clean slate."""
        for var in _PROVIDER_ENV_VARS:
            monkeypatch.delenv(var, raising=False)

    def _call(self) -> MultiBackend:
        """Call auto_configure_backend with dotenv loading disabled."""
        with patch.dict(sys.modules, {"dotenv": None}):
            return auto_configure_backend()

    def test_always_includes_ollama(self) -> None:
        """Ollama is unconditionally registered (local, no key needed)."""
        result = self._call()
        assert isinstance(result, MultiBackend)
        assert "ollama" in result.backends
        assert isinstance(result.backends["ollama"], OllamaBackend)

    def test_registers_openai_when_key_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
        result = self._call()
        assert "openai" in result.backends
        assert isinstance(result.backends["openai"], OpenAIBackend)

    def test_registers_anthropic_when_key_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
        result = self._call()
        assert "anthropic" in result.backends
        assert isinstance(result.backends["anthropic"], AnthropicBackend)

    def test_registers_github_when_token_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "test-gh-token")
        result = self._call()
        assert "github" in result.backends
        assert isinstance(result.backends["github"], GitHubModelsBackend)

    def test_registers_github_via_gh_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GH_TOKEN is an alternative to GITHUB_TOKEN."""
        monkeypatch.setenv("GH_TOKEN", "alt-token")
        result = self._call()
        assert "github" in result.backends

    def test_registers_gemini_when_key_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
        result = self._call()
        assert "gemini" in result.backends
        assert isinstance(result.backends["gemini"], GeminiBackend)

    def test_registers_multiple_providers_simultaneously(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Multiple providers can coexist in a single MultiBackend."""
        monkeypatch.setenv("OPENAI_API_KEY", "k1")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k2")
        result = self._call()
        assert "openai" in result.backends
        assert "anthropic" in result.backends
        assert "ollama" in result.backends

    def test_skips_provider_when_constructor_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If a backend constructor raises ValueError, it is silently skipped."""
        monkeypatch.setenv("OPENAI_API_KEY", "present-but-broken")
        with (
            patch.dict(sys.modules, {"dotenv": None}),
            patch(
                "agentic_v2.models.backends.OpenAIBackend",
                side_effect=ValueError("boom"),
            ),
        ):
            result = auto_configure_backend()
        assert "openai" not in result.backends
        assert "ollama" in result.backends  # still registered

    def test_dotenv_import_error_is_handled(self) -> None:
        """auto_configure_backend works even without python-dotenv installed."""
        with patch.dict(sys.modules, {"dotenv": None}):
            result = auto_configure_backend()
        assert isinstance(result, MultiBackend)

    def test_uses_explicit_secret_provider_without_env(self) -> None:
        provider = MappingSecretProvider(
            {
                "OPENAI_API_KEY": "provider-openai",
                "GH_TOKEN": "provider-gh",
            }
        )

        result = auto_configure_backend(secret_provider=provider)

        assert "openai" in result.backends
        assert "github" in result.backends
        assert result.backends["openai"].api_key == "provider-openai"
        assert result.backends["github"].token == "provider-gh"
