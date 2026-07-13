"""Route tests for provider and tier settings endpoints."""

from __future__ import annotations

import json

import pytest


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    """Point the UI settings store at a per-test temp file."""
    monkeypatch.setenv("AGENTIC_UI_SETTINGS_PATH", str(tmp_path / "ui_settings.json"))


class TestProviderSettings:
    def test_get_returns_defaults_and_provider_types(self, client):
        response = client.get("/api/settings/providers")

        assert response.status_code == 200
        payload = response.json()
        assert payload["providers"] == []
        assert set(payload["provider_types"]) == {
            "openai",
            "anthropic",
            "gh",
            "ollama",
            "foundry_local",
            "custom",
        }
        # Keyless-local providers are always env-configured.
        assert "ollama" in payload["env_configured_providers"]

    def test_put_persists_and_get_roundtrips(self, client):
        providers = [
            {
                "id": "team-ollama",
                "type": "ollama",
                "label": "Team Ollama box",
                "base_url": "http://10.0.0.5:11434",
                "default_model": "ollama:qwen3:8b",
                "enabled": True,
                "options": {"num_ctx": 16384},
            },
            {
                "id": "foundry",
                "type": "foundry_local",
                "label": "Foundry Local",
                "base_url": "http://localhost:5273/v1",
                "api_key_env": "FOUNDRY_LOCAL_API_KEY",
            },
        ]
        put = client.put("/api/settings/providers", json={"providers": providers})
        assert put.status_code == 200
        assert [p["id"] for p in put.json()["providers"]] == ["team-ollama", "foundry"]

        get = client.get("/api/settings/providers")
        assert get.json()["providers"][0]["base_url"] == "http://10.0.0.5:11434"

    def test_put_rejects_duplicate_ids(self, client):
        providers = [
            {"id": "dup", "type": "openai"},
            {"id": "dup", "type": "custom"},
        ]
        response = client.put("/api/settings/providers", json={"providers": providers})
        assert response.status_code == 422

    def test_put_rejects_raw_credentials_in_options(self, client):
        providers = [{"id": "leaky", "type": "custom", "options": {"api_key": "sk-x"}}]
        response = client.put("/api/settings/providers", json={"providers": providers})
        assert response.status_code == 422

    def test_put_rejects_raw_key_shaped_api_key_env(self, client):
        providers = [
            {
                "id": "leaky",
                "type": "custom",
                "api_key_env": "sk-abc123def456ghi789jkl",  # pragma: allowlist secret
            }
        ]
        response = client.put("/api/settings/providers", json={"providers": providers})
        assert response.status_code == 422
        assert "environment variable NAME" in response.json()["detail"]
        # Nothing was persisted — a follow-up GET stays empty.
        assert client.get("/api/settings/providers").json()["providers"] == []

    def test_put_rejects_github_token_shaped_api_key_env(self, client):
        # ghp_ tokens are valid shell identifiers, but still credentials.
        providers = [
            {"id": "gh-box", "type": "gh", "api_key_env": "ghp_" + "a1B2" * 6}
        ]
        response = client.put("/api/settings/providers", json={"providers": providers})
        assert response.status_code == 422
        assert "never the credential itself" in response.json()["detail"]

    def test_put_accepts_legit_env_var_names(self, client):
        providers = [
            {"id": "team-ollama", "type": "ollama", "api_key_env": "OLLAMA_API_KEY"},
            {"id": "lab", "type": "custom", "api_key_env": "_MY_LAB_KEY"},
        ]
        response = client.put("/api/settings/providers", json={"providers": providers})
        assert response.status_code == 200
        saved = response.json()["providers"]
        assert saved[0]["api_key_env"] == "OLLAMA_API_KEY"
        assert saved[1]["api_key_env"] == "_MY_LAB_KEY"

    def test_get_nulls_raw_key_persisted_by_older_versions(self, client, tmp_path):
        # Legacy store written before write-side hardening: the raw key must
        # be cleared on read, never echoed back through the API.
        store = tmp_path / "ui_settings.json"
        store.write_text(
            json.dumps(
                {
                    "version": 1,
                    "providers": [
                        {
                            "id": "legacy",
                            "type": "custom",
                            "api_key_env": "sk-legacy123456789abcdef",  # pragma: allowlist secret
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        response = client.get("/api/settings/providers")

        assert response.status_code == 200
        provider = response.json()["providers"][0]
        assert provider["id"] == "legacy"
        assert provider["api_key_env"] is None


class TestTierSettings:
    def test_get_returns_six_tiers_with_registry_chains(self, client):
        response = client.get("/api/settings/tiers")

        assert response.status_code == 200
        payload = response.json()
        assert [t["tier"] for t in payload["tiers"]] == [0, 1, 2, 3, 4, 5]
        tier2 = payload["tiers"][2]
        assert tier2["default_chain"]  # registry requires tiers 1-5 be non-empty
        assert tier2["override"] == []
        assert tier2["effective"] == tier2["default_chain"]
        assert payload["models"]
        assert "reasoning" in payload["known_capabilities"]

    def test_put_reranks_a_tier_and_effective_reflects_it(self, client):
        tiers = client.get("/api/settings/tiers").json()["tiers"]
        chain = tiers[2]["default_chain"]
        reranked = list(reversed(chain))

        response = client.put(
            "/api/settings/tiers", json={"tier_overrides": {"2": reranked}}
        )

        assert response.status_code == 200
        tier2 = response.json()["tiers"][2]
        assert tier2["override"] == reranked
        assert tier2["effective"][: len(reranked)] == reranked

    def test_put_empty_list_clears_override(self, client):
        client.put(
            "/api/settings/tiers",
            json={"tier_overrides": {"2": ["gh:openai/gpt-4o-mini"]}},
        )
        response = client.put("/api/settings/tiers", json={"tier_overrides": {"2": []}})
        assert response.status_code == 200
        assert response.json()["tiers"][2]["override"] == []

    def test_put_updates_model_capabilities(self, client):
        models = client.get("/api/settings/tiers").json()["models"]
        target = models[0]["id"]

        response = client.put(
            "/api/settings/tiers",
            json={"model_capabilities": {target: ["fast", "vision"]}},
        )

        assert response.status_code == 200
        updated = next(m for m in response.json()["models"] if m["id"] == target)
        assert updated["capabilities"] == ["fast", "vision"]
        assert updated["capability_overridden"] is True

    def test_put_rejects_unknown_capability(self, client):
        models = client.get("/api/settings/tiers").json()["models"]
        target = models[0]["id"]

        response = client.put(
            "/api/settings/tiers",
            json={"model_capabilities": {target: ["quantum"]}},
        )

        assert response.status_code == 422
        assert "Unknown capabilities" in response.json()["detail"]

    def test_tier_override_feeds_model_candidates(self, client):
        """The routing layer must consume the persisted rerank."""
        from agentic_v2.langchain.models import get_model_candidates_for_tier

        client.put(
            "/api/settings/tiers",
            json={"tier_overrides": {"2": ["gh:openai/gpt-4o-mini"]}},
        )
        candidates = get_model_candidates_for_tier(2, include_unavailable=True)
        assert candidates[0] == "gh:openai/gpt-4o-mini"
