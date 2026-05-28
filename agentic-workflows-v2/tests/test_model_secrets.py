"""Tests for provider-agnostic secret resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentic_v2.models.secrets import (
    ChainedSecretProvider,
    EnvSecretProvider,
    MappingSecretProvider,
    get_first_secret,
    get_secret,
    reset_default_secret_provider,
    set_default_secret_provider,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestMappingSecretProvider:
    """Direct mapping-backed secret lookups."""

    def test_returns_normalized_secret(self) -> None:
        provider = MappingSecretProvider({"OPENAI_API_KEY": "  abc123  "})
        assert provider.get("OPENAI_API_KEY") == "abc123"

    def test_returns_default_when_missing(self) -> None:
        provider = MappingSecretProvider({})
        assert provider.get("MISSING", "fallback") == "fallback"


class TestEnvSecretProvider:
    """Environment-backed secret lookups with refresh support."""

    def test_reads_from_process_environment(self, monkeypatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "env-key")
        provider = EnvSecretProvider(load_dotenv=False)
        assert provider.get("OPENAI_API_KEY") == "env-key"

    def test_refresh_reloads_dotenv_search(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.chdir(tmp_path)
        env_file = tmp_path / ".env"
        env_file.write_text("OPENAI_API_KEY=first\n", encoding="utf-8")

        provider = EnvSecretProvider(search_roots=[tmp_path])
        assert provider.get("OPENAI_API_KEY") == "first"

        env_file.write_text("OPENAI_API_KEY=rotated\n", encoding="utf-8")
        provider.refresh()
        assert provider.get("OPENAI_API_KEY") == "rotated"


class TestGlobalSecretProviderHelpers:
    """Process-wide secret provider overrides used by runtime code."""

    def teardown_method(self) -> None:
        reset_default_secret_provider()

    def test_get_secret_uses_overridden_provider(self) -> None:
        set_default_secret_provider(
            MappingSecretProvider({"AGENTIC_API_KEY": "shared"})
        )
        assert get_secret("AGENTIC_API_KEY") == "shared"

    def test_get_first_secret_uses_first_present_name(self) -> None:
        provider = ChainedSecretProvider(
            [MappingSecretProvider({"GH_TOKEN": "token-from-gh"})]
        )
        assert (
            get_first_secret("GITHUB_TOKEN", "GH_TOKEN", provider=provider)
            == "token-from-gh"
        )
