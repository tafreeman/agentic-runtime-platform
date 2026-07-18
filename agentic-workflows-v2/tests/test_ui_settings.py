"""Tests for the runtime-mutable UI settings store (agentic_v2.ui_settings)."""

from __future__ import annotations

import json
import logging

import pytest
from pydantic import ValidationError

from agentic_v2.ui_settings import (
    ModelPack,
    ModelPackRef,
    ProviderConfig,
    UiSettings,
    is_valid_api_key_env,
    load_ui_settings,
    model_pack_routing,
    resolve_model_pack,
    save_ui_settings,
    tier_override_models,
)


def _settings_path(tmp_path):
    return tmp_path / "ui_settings.json"


class TestProviderConfig:
    def test_accepts_a_full_provider_entry(self):
        provider = ProviderConfig(
            id="my-ollama",
            type="ollama",
            label="Local Ollama",
            base_url="http://localhost:11434",
            default_model="ollama:qwen3:8b",
            options={"num_ctx": 8192},
        )
        assert provider.enabled is True
        assert provider.base_url == "http://localhost:11434"

    def test_rejects_invalid_slug_id(self):
        with pytest.raises(ValidationError, match="slug"):
            ProviderConfig(id="Bad Id!", type="openai")

    def test_rejects_unknown_provider_type(self):
        with pytest.raises(ValidationError):
            ProviderConfig(id="x", type="definitely-not-a-provider")

    def test_rejects_credential_smuggling_in_options(self):
        with pytest.raises(ValidationError, match="credentials"):
            ProviderConfig(id="x", type="custom", options={"api_key": "sk-123"})

    def test_api_key_env_holds_a_name_not_a_secret(self):
        provider = ProviderConfig(id="x", type="anthropic", api_key_env="MY_KEY_VAR")
        assert provider.api_key_env == "MY_KEY_VAR"


class TestUiSettingsValidation:
    def test_rejects_duplicate_provider_ids(self):
        with pytest.raises(ValidationError, match="Duplicate provider id"):
            UiSettings(
                providers=[
                    ProviderConfig(id="dup", type="openai"),
                    ProviderConfig(id="dup", type="ollama"),
                ]
            )

    def test_rejects_out_of_range_tier(self):
        with pytest.raises(ValidationError, match="between 0 and 5"):
            UiSettings(tier_overrides={9: ["gh:openai/gpt-4o"]})

    def test_rejects_empty_model_id_in_override(self):
        with pytest.raises(ValidationError, match="empty model id"):
            UiSettings(tier_overrides={2: [""]})


class TestStoreRoundtrip:
    def test_load_returns_defaults_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTIC_UI_SETTINGS_PATH", str(_settings_path(tmp_path)))
        settings = load_ui_settings()
        assert settings.providers == []
        assert settings.tier_overrides == {}

    def test_save_then_load_roundtrips(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTIC_UI_SETTINGS_PATH", str(_settings_path(tmp_path)))
        original = UiSettings(
            providers=[ProviderConfig(id="lab", type="custom", base_url="http://x")],
            tier_overrides={2: ["ollama:qwen3:8b", "gh:openai/gpt-4o"]},
            model_capabilities={"ollama:qwen3:8b": ["fast", "local"]},
        )
        path = save_ui_settings(original)
        assert path == _settings_path(tmp_path)

        loaded = load_ui_settings()
        assert loaded == original

    def test_corrupt_file_degrades_to_defaults(self, tmp_path, monkeypatch):
        path = _settings_path(tmp_path)
        path.write_text("{not json", encoding="utf-8")
        monkeypatch.setenv("AGENTIC_UI_SETTINGS_PATH", str(path))
        assert load_ui_settings() == UiSettings()

    def test_saved_file_is_valid_json_without_secrets_fields(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("AGENTIC_UI_SETTINGS_PATH", str(_settings_path(tmp_path)))
        save_ui_settings(
            UiSettings(
                providers=[
                    ProviderConfig(id="a", type="openai", api_key_env="OPENAI_API_KEY")
                ]
            )
        )
        on_disk = json.loads(_settings_path(tmp_path).read_text(encoding="utf-8"))
        assert on_disk["providers"][0]["api_key_env"] == "OPENAI_API_KEY"
        assert "api_key" not in on_disk["providers"][0]


class TestApiKeyEnvHardening:
    """Reads are lenient (null + warn); the predicate is shared with writes."""

    @staticmethod
    def _write_store(path, api_key_env: str) -> None:
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "providers": [
                        {"id": "legacy", "type": "custom", "api_key_env": api_key_env}
                    ],
                }
            ),
            encoding="utf-8",
        )

    def test_loading_raw_key_nulls_it_with_warning(self, tmp_path, monkeypatch, caplog):
        path = _settings_path(tmp_path)
        raw_key = "sk-proj-abc123def456ghi789"  # pragma: allowlist secret
        self._write_store(path, raw_key)
        monkeypatch.setenv("AGENTIC_UI_SETTINGS_PATH", str(path))

        with caplog.at_level(logging.WARNING, logger="agentic_v2.ui_settings"):
            settings = load_ui_settings()

        assert settings.providers[0].api_key_env is None
        assert "api_key_env" in caplog.text
        assert "legacy" in caplog.text
        # The credential itself must never reach the log.
        assert raw_key not in caplog.text

    def test_loading_github_token_shape_is_nulled(self, tmp_path, monkeypatch):
        # A ghp_ token passes the env-var-name regex but is still a secret.
        path = _settings_path(tmp_path)
        self._write_store(path, "ghp_" + "a1B2c3D4" * 3)  # pragma: allowlist secret
        monkeypatch.setenv("AGENTIC_UI_SETTINGS_PATH", str(path))

        settings = load_ui_settings()

        assert settings.providers[0].api_key_env is None

    def test_loading_huggingface_token_shape_is_nulled(self, tmp_path, monkeypatch):
        # hf_ tokens are valid shell identifiers too (PR #199/#201 review).
        path = _settings_path(tmp_path)
        self._write_store(path, "hf_" + "A1b2C3d4" * 5)  # pragma: allowlist secret
        monkeypatch.setenv("AGENTIC_UI_SETTINGS_PATH", str(path))

        settings = load_ui_settings()

        assert settings.providers[0].api_key_env is None

    def test_loading_valid_env_name_is_untouched(self, tmp_path, monkeypatch):
        path = _settings_path(tmp_path)
        self._write_store(path, "OLLAMA_API_KEY")  # pragma: allowlist secret
        monkeypatch.setenv("AGENTIC_UI_SETTINGS_PATH", str(path))

        settings = load_ui_settings()

        expected_env = "OLLAMA_API_KEY"  # pragma: allowlist secret
        assert settings.providers[0].api_key_env == expected_env

    def test_is_valid_api_key_env_predicate(self):
        assert is_valid_api_key_env("OLLAMA_API_KEY")  # pragma: allowlist secret
        assert is_valid_api_key_env("_PRIVATE_KEY_VAR")  # pragma: allowlist secret
        assert is_valid_api_key_env("x")
        # Shape violations.
        assert not is_valid_api_key_env(
            "sk-abc123def456ghi"
        )  # pragma: allowlist secret
        assert not is_valid_api_key_env("has space")
        assert not is_valid_api_key_env("1STARTS_WITH_DIGIT")
        assert not is_valid_api_key_env("")
        assert not is_valid_api_key_env("X" * 129)
        # Secret shapes that happen to be valid identifiers.
        assert not is_valid_api_key_env(
            "ghp_" + "a1B2c3D4" * 3
        )  # pragma: allowlist secret
        assert not is_valid_api_key_env(
            "github_pat_" + "A0" * 12
        )  # pragma: allowlist secret
        assert not is_valid_api_key_env(
            "hf_" + "A1b2C3d4" * 5
        )  # pragma: allowlist secret
        assert not is_valid_api_key_env("deadbeef" * 4)  # pragma: allowlist secret


class TestTierOverrideAccessor:
    def test_returns_override_for_tier(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTIC_UI_SETTINGS_PATH", str(_settings_path(tmp_path)))
        save_ui_settings(UiSettings(tier_overrides={3: ["anthropic:claude-x"]}))
        assert tier_override_models(3) == ["anthropic:claude-x"]

    def test_returns_empty_for_unset_tier(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENTIC_UI_SETTINGS_PATH", str(_settings_path(tmp_path)))
        assert tier_override_models(4) == []

    def test_request_context_pack_overrides_persisted_tier_order(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("AGENTIC_UI_SETTINGS_PATH", str(_settings_path(tmp_path)))
        save_ui_settings(UiSettings(tier_overrides={2: ["ollama:default"]}))
        pack = ModelPack(
            id="run-pack",
            name="Run pack",
            tier_chains={2: ["openai:gpt-4o", "anthropic:sonnet"]},
        )

        with model_pack_routing(pack):
            assert tier_override_models(2) == [
                "openai:gpt-4o",
                "anthropic:sonnet",
            ]
        assert tier_override_models(2) == ["ollama:default"]


class TestModelPackResolution:
    def test_precedence_is_run_then_workflow_then_global(self):
        run = ModelPack(id="run", name="Run", tier_chains={1: ["openai:a"]})
        workflow = ModelPack(
            id="workflow", name="Workflow", tier_chains={1: ["openai:b"]}
        )
        global_pack = ModelPack(
            id="global", name="Global", tier_chains={1: ["openai:c"]}
        )
        settings = UiSettings(
            model_packs=[run, workflow, global_pack],
            active_model_pack=ModelPackRef(id="global", version=1),
            workflow_model_packs={"review": ModelPackRef(id="workflow", version=1)},
        )

        assert (
            resolve_model_pack(
                workflow_name="review",
                requested=ModelPackRef(id="run", version=1),
                settings=settings,
            )[1]
            == "run"
        )
        assert (
            resolve_model_pack(workflow_name="review", settings=settings)[0] == workflow
        )
        assert (
            resolve_model_pack(workflow_name="other", settings=settings)[0]
            == global_pack
        )

    def test_archived_requested_pack_is_rejected(self):
        archived = ModelPack(
            id="old", name="Old", tier_chains={1: ["openai:a"]}, archived=True
        )
        settings = UiSettings(model_packs=[archived])

        with pytest.raises(ValueError, match="archived"):
            resolve_model_pack(
                workflow_name="review",
                requested=ModelPackRef(id="old", version=1),
                settings=settings,
            )
