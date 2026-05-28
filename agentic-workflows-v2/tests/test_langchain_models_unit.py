"""Tests for LangChain model helper functions (pure/config functions only)."""

from __future__ import annotations

import pytest
from agentic_v2.langchain.models import (
    _dedupe_keep_order,
    _is_provider_available,
    _provider_prefix,
    _resolve_model_override,
    get_model_candidates_for_tier,
    is_retryable_model_error,
)


class TestProviderPrefix:
    """Tests for _provider_prefix."""

    def test_extracts_prefix(self) -> None:
        """'gh:openai/gpt-4o' -> 'gh'."""
        assert _provider_prefix("gh:openai/gpt-4o") == "gh"

    def test_anthropic_prefix(self) -> None:
        """'anthropic:claude-sonnet-4-6-20260219' -> 'anthropic'."""
        assert _provider_prefix("anthropic:claude-sonnet-4-6-20260219") == "anthropic"

    def test_bare_name_defaults_to_ollama(self) -> None:
        """'phi4' -> 'ollama'."""
        assert _provider_prefix("phi4") == "ollama"

    def test_gemini_prefix(self) -> None:
        """'gemini:gemini-2.0-flash' -> 'gemini'."""
        assert _provider_prefix("gemini:gemini-2.0-flash") == "gemini"


class TestIsProviderAvailable:
    """Tests for _is_provider_available."""

    def test_ollama_always_available(self) -> None:
        """Ollama has no env key requirement."""
        assert _is_provider_available("ollama") is True

    def test_local_always_available(self) -> None:
        """Local ONNX has no env key requirement."""
        assert _is_provider_available("local") is True

    def test_gemini_requires_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Gemini needs GOOGLE_API_KEY or GEMINI_API_KEY."""
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        assert _is_provider_available("gemini") is False

    def test_gemini_available_with_google_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Gemini available when GOOGLE_API_KEY is set."""
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
        assert _is_provider_available("gemini") is True

    def test_anthropic_requires_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Anthropic needs ANTHROPIC_API_KEY."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert _is_provider_available("anthropic") is False

    def test_anthropic_available_with_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Anthropic available when ANTHROPIC_API_KEY is set."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        assert _is_provider_available("anthropic") is True

    def test_unknown_provider_available(self) -> None:
        """Unknown provider defaults to available (no keys required)."""
        assert _is_provider_available("unknown_provider") is True


class TestResolveModelOverride:
    """Tests for _resolve_model_override."""

    def test_direct_model_id(self) -> None:
        """Non-env: prefix returns the model ID directly."""
        assert _resolve_model_override("gh:openai/gpt-4o") == "gh:openai/gpt-4o"

    def test_bare_model_id(self) -> None:
        """Bare model name returns as-is."""
        assert _resolve_model_override("ollama:qwen3:8b") == "ollama:qwen3:8b"

    def test_env_var_resolved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """env:MY_VAR resolves from environment."""
        monkeypatch.setenv("MY_MODEL_VAR", "gh:openai/gpt-4o-mini")
        result = _resolve_model_override("env:MY_MODEL_VAR")
        assert result == "gh:openai/gpt-4o-mini"

    def test_env_var_with_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """env:MY_VAR|gh:openai/gpt-4o uses fallback when var is unset."""
        monkeypatch.delenv("MISSING_VAR", raising=False)
        result = _resolve_model_override("env:MISSING_VAR|gh:openai/gpt-4o")
        assert result == "gh:openai/gpt-4o"

    def test_env_empty_var_name_raises(self) -> None:
        """env: (empty) raises ValueError."""
        with pytest.raises(ValueError, match="missing variable name"):
            _resolve_model_override("env:")

    def test_env_missing_var_no_fallback_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Env:NONEXISTENT raises ValueError."""
        monkeypatch.delenv("NONEXISTENT_MODEL_VAR", raising=False)
        with pytest.raises(ValueError, match="not set"):
            _resolve_model_override("env:NONEXISTENT_MODEL_VAR")


class TestIsRetryableModelError:
    """Tests for is_retryable_model_error."""

    def test_rate_limit_status_code_is_retryable(self) -> None:
        """Exception with 429 status_code is retryable."""

        class RateLimitError(Exception):
            status_code = 429

        assert is_retryable_model_error(RateLimitError("rate limited")) is True

    def test_server_error_is_retryable(self) -> None:
        """Exception with 503 status_code is retryable."""

        class ServerError(Exception):
            status_code = 503

        assert is_retryable_model_error(ServerError("down")) is True

    def test_timeout_class_is_retryable(self) -> None:
        """TimeoutError class name triggers retryable."""

        class TimeoutError(Exception):
            pass

        assert is_retryable_model_error(TimeoutError("timeout")) is True

    def test_generic_error_is_not_retryable(self) -> None:
        """ValueError is not retryable."""
        assert is_retryable_model_error(ValueError("bad input")) is False

    def test_connection_error_in_message_is_retryable(self) -> None:
        """'connection error' in message is retryable."""
        assert is_retryable_model_error(Exception("connection error occurred")) is True

    def test_400_not_retryable(self) -> None:
        """Exception with 400 status_code is not retryable."""

        class BadRequest(Exception):
            status_code = 400

        assert is_retryable_model_error(BadRequest("bad request")) is False

    def test_rate_limit_in_message_is_retryable(self) -> None:
        """'rate limit' in message is retryable."""
        assert is_retryable_model_error(Exception("rate limit exceeded")) is True


class TestDedupeKeepOrder:
    """Tests for _dedupe_keep_order."""

    def test_removes_duplicates(self) -> None:
        """Duplicates removed, first occurrence kept."""
        result = _dedupe_keep_order(["a", "b", "a", "c", "b"])
        assert result == ["a", "b", "c"]

    def test_strips_whitespace(self) -> None:
        """Whitespace-only items are removed."""
        result = _dedupe_keep_order(["a", " ", "", "b", None])  # type: ignore[list-item]
        assert result == ["a", "b"]

    def test_preserves_order(self) -> None:
        """Order of first occurrence is preserved."""
        result = _dedupe_keep_order(["c", "a", "b"])
        assert result == ["c", "a", "b"]

    def test_empty_list(self) -> None:
        """Empty list returns empty list."""
        assert _dedupe_keep_order([]) == []


class TestGetModelCandidatesForTier:
    """Tests for get_model_candidates_for_tier."""

    def test_returns_list(self) -> None:
        """Returns a non-empty list for valid tier."""
        result = get_model_candidates_for_tier(2)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_override_takes_precedence(self) -> None:
        """Per-step model_override appears first in the list."""
        result = get_model_candidates_for_tier(2, model_override="ollama:test-model")
        assert result[0] == "ollama:test-model"

    def test_env_override_included(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AGENTIC_MODEL_TIER_2 is included in candidates."""
        monkeypatch.setenv("AGENTIC_MODEL_TIER_2", "openai:gpt-test")
        result = get_model_candidates_for_tier(2)
        assert "openai:gpt-test" in result

    def test_no_duplicates(self) -> None:
        """Returned list has no duplicates."""
        result = get_model_candidates_for_tier(2, include_unavailable=True)
        assert len(result) == len(set(result))
