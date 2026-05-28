"""Unit tests for tools.llm.llm_client — no real LLM calls made."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tools.llm.llm_client import LLMClient, LLMClientError


class TestLLMClientError:
    def test_message_includes_model(self):
        err = LLMClientError("gpt-4o", "something failed")
        assert "gpt-4o" in str(err)
        assert "something failed" in str(err)

    def test_original_error_stored(self):
        original = ValueError("root cause")
        err = LLMClientError("gpt-4o", "wrapper", original_error=original)
        assert err.original_error is original

    def test_no_original_error(self):
        err = LLMClientError("claude-3", "msg")
        assert err.original_error is None

    def test_is_runtime_error(self):
        err = LLMClientError("model", "msg")
        assert isinstance(err, RuntimeError)


class TestPickPreferredModel:
    def test_returns_first_match(self):
        result = LLMClient._pick_preferred_model(
            available=["gpt-4o", "gpt-4o-mini", "claude-3"],
            preferred=["gpt-4o-mini", "gpt-4o"],
        )
        assert result == "gpt-4o-mini"

    def test_returns_none_when_no_match(self):
        result = LLMClient._pick_preferred_model(
            available=["gpt-4o"],
            preferred=["claude-3", "gemini-pro"],
        )
        assert result is None

    def test_empty_available(self):
        result = LLMClient._pick_preferred_model(available=[], preferred=["gpt-4o"])
        assert result is None

    def test_empty_preferred(self):
        result = LLMClient._pick_preferred_model(available=["gpt-4o"], preferred=[])
        assert result is None

    def test_exact_match_required(self):
        result = LLMClient._pick_preferred_model(
            available=["gpt-4o-mini"],
            preferred=["gpt-4o"],  # no trailing -mini
        )
        assert result is None


class TestRemoteProviderGating:
    """Remote providers must be blocked unless PROMPTEVAL_ALLOW_REMOTE=1."""

    @pytest.mark.parametrize(
        "model_name",
        [
            "gpt-4o",
            "gpt-4o-mini",
            "claude-3-haiku",
            "gemini-1.5-pro",
            "openai:gpt-4o",
            "gemini:gemini-1.5-pro",
            "claude:claude-3-haiku",
            "azure-foundry:phi4mini",
            "azure-openai:gpt-4o",
        ],
    )
    def test_remote_blocked_by_default(
        self, model_name: str, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("PROMPTEVAL_ALLOW_REMOTE", raising=False)
        with pytest.raises(RuntimeError, match="Remote provider disabled"):
            LLMClient.generate_text(model_name, "hello")

    @pytest.mark.parametrize(
        "model_name",
        [
            "gh:gpt-4o-mini",
            "ollama:llama3",
        ],
    )
    def test_allowed_providers_bypass_gate(
        self, model_name: str, monkeypatch: pytest.MonkeyPatch
    ):
        """gh: and ollama: are allowed without the env flag — they reach the provider call."""
        monkeypatch.delenv("PROMPTEVAL_ALLOW_REMOTE", raising=False)
        monkeypatch.setenv("PROMPTS_CACHE_ENABLED", "0")
        # Mock the provider adapter so we don't make real calls
        mock_fn = MagicMock(return_value="mocked response")
        adapter_path = (
            "tools.llm.provider_adapters.call_github_models"
            if model_name.startswith("gh:")
            else "tools.llm.provider_adapters.call_ollama"
        )
        with patch(adapter_path, mock_fn):
            result = LLMClient.generate_text(model_name, "hello")
        assert result == "mocked response"


class TestGenerateTextRouting:
    """Verify routing dispatches to the right provider adapter."""

    def _make_call(
        self, model_name: str, adapter_path: str, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("PROMPTEVAL_ALLOW_REMOTE", "1")
        monkeypatch.setenv("PROMPTS_CACHE_ENABLED", "0")
        mock_fn = MagicMock(return_value="ok")
        with patch(adapter_path, mock_fn):
            result = LLMClient.generate_text(model_name, "prompt")
        assert result == "ok"
        return mock_fn

    def test_routes_gh_to_github_models(self, monkeypatch: pytest.MonkeyPatch):
        mock = self._make_call(
            "gh:gpt-4o-mini",
            "tools.llm.provider_adapters.call_github_models",
            monkeypatch,
        )
        mock.assert_called_once()

    def test_routes_gemini_prefix_to_gemini(self, monkeypatch: pytest.MonkeyPatch):
        mock = self._make_call(
            "gemini:gemini-1.5-pro",
            "tools.llm.provider_adapters.call_gemini",
            monkeypatch,
        )
        mock.assert_called_once()

    def test_routes_claude_prefix_to_claude(self, monkeypatch: pytest.MonkeyPatch):
        mock = self._make_call(
            "claude:claude-3-haiku",
            "tools.llm.provider_adapters.call_claude",
            monkeypatch,
        )
        mock.assert_called_once()

    def test_routes_openai_prefix_to_openai(self, monkeypatch: pytest.MonkeyPatch):
        mock = self._make_call(
            "openai:gpt-4o",
            "tools.llm.provider_adapters.call_openai",
            monkeypatch,
        )
        mock.assert_called_once()

    def test_routes_bare_gpt_to_openai(self, monkeypatch: pytest.MonkeyPatch):
        mock = self._make_call(
            "gpt-4o-mini",
            "tools.llm.provider_adapters.call_openai",
            monkeypatch,
        )
        mock.assert_called_once()

    def test_unknown_model_raises_llm_client_error(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("PROMPTEVAL_ALLOW_REMOTE", "1")
        monkeypatch.setenv("PROMPTS_CACHE_ENABLED", "0")
        with pytest.raises(LLMClientError, match="Unknown model"):
            LLMClient.generate_text("totally-unknown-model-xyz", "prompt")

    def test_provider_exception_wrapped_as_llm_client_error(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("PROMPTEVAL_ALLOW_REMOTE", "1")
        monkeypatch.setenv("PROMPTS_CACHE_ENABLED", "0")
        with (
            patch(
                "tools.llm.provider_adapters.call_github_models",
                side_effect=ConnectionError("network down"),
            ),
            pytest.raises(LLMClientError) as exc_info,
        ):
            LLMClient.generate_text("gh:gpt-4o-mini", "prompt")
        assert isinstance(exc_info.value.original_error, ConnectionError)
