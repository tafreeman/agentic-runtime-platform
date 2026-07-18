"""Route tests for provider and tier settings endpoints."""

from __future__ import annotations

import json

import httpx
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
            {
                "id": "gh-box",
                "type": "gh",
                "api_key_env": "ghp_" + "a1B2" * 6,  # pragma: allowlist secret
            }
        ]
        response = client.put("/api/settings/providers", json={"providers": providers})
        assert response.status_code == 422
        assert "never the credential itself" in response.json()["detail"]

    def test_put_accepts_legit_env_var_names(self, client):
        providers = [
            {
                "id": "team-ollama",
                "type": "ollama",
                "api_key_env": "OLLAMA_API_KEY",  # pragma: allowlist secret
            },
            {
                "id": "lab",
                "type": "custom",
                "api_key_env": "_MY_LAB_KEY",  # pragma: allowlist secret
            },
        ]
        response = client.put("/api/settings/providers", json={"providers": providers})
        assert response.status_code == 200
        saved = response.json()["providers"]
        assert saved[0]["api_key_env"] == "OLLAMA_API_KEY"  # pragma: allowlist secret
        assert saved[1]["api_key_env"] == "_MY_LAB_KEY"  # pragma: allowlist secret

    def test_put_rejects_unsafe_or_credentialed_base_urls(self, client):
        for base_url in (
            "ftp://models.example.test",
            "https://user:pass@example.test",  # pragma: allowlist secret
        ):
            response = client.put(
                "/api/settings/providers",
                json={
                    "providers": [
                        {"id": "unsafe", "type": "custom", "base_url": base_url}
                    ]
                },
            )
            assert response.status_code == 422

    def test_probe_calls_saved_discovery_endpoint_without_redirects(
        self, client, monkeypatch
    ):
        import agentic_v2.server.routes.settings_routes as settings_routes

        client.put(
            "/api/settings/providers",
            json={
                "providers": [
                    {
                        "id": "lab",
                        "type": "custom",
                        "base_url": "https://models.example.test/v1",
                        "api_key_env": "LAB_API_KEY",  # pragma: allowlist secret
                    }
                ]
            },
        )
        monkeypatch.setenv("LAB_API_KEY", "test-credential")  # pragma: allowlist secret
        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["authorization"] = request.headers.get("authorization")
            return httpx.Response(200, json={"data": [{"id": "model-a"}]})

        real_client = httpx.AsyncClient

        def mock_client(**kwargs):
            seen["follow_redirects"] = kwargs.get("follow_redirects")
            return real_client(transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(settings_routes.httpx, "AsyncClient", mock_client)

        response = client.post("/api/settings/providers/lab/probe")

        assert response.status_code == 200
        assert response.json()["status"] == "available"
        assert response.json()["discovered_model_count"] == 1
        assert seen == {
            "follow_redirects": False,
            "url": "https://models.example.test/v1/models",
            "authorization": "Bearer test-credential",
        }

    def test_probe_blocks_cloud_metadata_endpoints(self, client, monkeypatch):
        """The probe applies the shared SSRF guard before any request is sent."""
        import agentic_v2.server.routes.settings_routes as settings_routes

        client.put(
            "/api/settings/providers",
            json={
                "providers": [
                    {
                        "id": "aws-md",
                        "type": "custom",
                        "base_url": "http://169.254.169.254/latest",
                    },
                    {
                        "id": "gcp-md",
                        "type": "custom",
                        "base_url": "http://metadata.google.internal/computeMetadata",
                    },
                ]
            },
        )

        def forbid_client(**kwargs):
            raise AssertionError("blocked URLs must never reach the network")

        monkeypatch.setattr(settings_routes.httpx, "AsyncClient", forbid_client)

        for provider_id in ("aws-md", "gcp-md"):
            response = client.post(f"/api/settings/providers/{provider_id}/probe")
            assert response.status_code == 200
            payload = response.json()
            assert payload["status"] == "error"
            assert "blocked" in payload["detail"]

    def test_probe_still_allows_localhost_and_lan_endpoints(self, client, monkeypatch):
        """Private/LAN base URLs stay probe-able (local Ollama, LM Studio)."""
        import agentic_v2.server.routes.settings_routes as settings_routes

        client.put(
            "/api/settings/providers",
            json={
                "providers": [
                    {
                        "id": "local-ollama",
                        "type": "ollama",
                        "base_url": "http://localhost:11434",
                    },
                    {
                        "id": "lan-box",
                        "type": "custom",
                        "base_url": "http://10.0.0.5:1234/v1",
                    },
                ]
            },
        )
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, json={"models": [{"name": "m"}]})

        real_client = httpx.AsyncClient

        def mock_client(**kwargs):
            return real_client(transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(settings_routes.httpx, "AsyncClient", mock_client)

        for provider_id in ("local-ollama", "lan-box"):
            response = client.post(f"/api/settings/providers/{provider_id}/probe")
            assert response.status_code == 200
            assert response.json()["status"] == "available"
        assert seen == [
            "http://localhost:11434/api/tags",
            "http://10.0.0.5:1234/v1/models",
        ]

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


class TestModelPacks:
    def test_create_version_validate_and_export_are_immutable(self, client):
        created = client.post(
            "/api/settings/model-packs",
            json={
                "id": "review-stable",
                "name": "Review stable",
                "description": "Pinned review routing",
                "source": "defaults",
            },
        )
        assert created.status_code == 201
        version_one = created.json()
        assert version_one["version"] == 1
        assert version_one["tier_chains"]

        versioned = client.put(
            "/api/settings/model-packs/review-stable",
            json={"description": "Second immutable snapshot"},
        )
        assert versioned.status_code == 200
        assert versioned.json()["version"] == 2

        listed = client.get("/api/settings/model-packs").json()["packs"]
        assert [(pack["id"], pack["version"]) for pack in listed] == [
            ("review-stable", 2),
            ("review-stable", 1),
        ]
        assert listed[1]["description"] == "Pinned review routing"

        validation = client.post(
            "/api/settings/model-packs/review-stable/validate?version=2"
        )
        assert validation.status_code == 200
        assert validation.json()["valid"] is True

        exported = client.get(
            "/api/settings/model-packs/review-stable/export?version=1"
        )
        assert exported.status_code == 200
        assert exported.json()["schema_version"] == 1
        assert exported.json()["pack"]["version"] == 1

    def test_activate_duplicate_import_and_dependency_guard(self, client):
        source = client.post(
            "/api/settings/model-packs",
            json={"id": "source-pack", "name": "Source pack", "source": "defaults"},
        ).json()
        activated = client.post(
            "/api/settings/model-packs/source-pack/activate?version=1"
        )
        assert activated.status_code == 200
        assert activated.json()["active"] == {"id": "source-pack", "version": 1}

        blocked = client.post("/api/settings/model-packs/source-pack/archive?version=1")
        assert blocked.status_code == 409

        duplicate = client.post(
            "/api/settings/model-packs/source-pack/duplicate?version=1",
            json={
                "source": {"id": "source-pack", "version": 1},
                "new_id": "source-copy",
                "name": "Source copy",
            },
        )
        assert duplicate.status_code == 201
        assert duplicate.json()["source"] == "duplicate"

        imported = client.post(
            "/api/settings/model-packs/import",
            json={
                "schema_version": 1,
                "pack": {
                    "id": "imported-pack",
                    "name": "Imported pack",
                    "tier_chains": source["tier_chains"],
                    "allowed_providers": source["allowed_providers"],
                },
            },
        )
        assert imported.status_code == 201
        assert imported.json()["source"] == "imported"

        dependencies = client.get(
            "/api/settings/model-packs/source-pack/dependencies?version=1"
        ).json()
        assert dependencies["globally_active"] is True
        assert dependencies["workflows"] == []

    def test_validate_flags_unsatisfiable_capability_requirements(self, client):
        """A tier requiring a capability no chain model provides must not activate."""
        created = client.post(
            "/api/settings/model-packs",
            json={
                "id": "vision-pack",
                "name": "Vision pack",
                "tier_chains": {"2": ["ollama:text-only"]},
                "capability_requirements": {"2": ["vision"]},
                "model_capabilities": {"ollama:text-only": ["fast"]},
            },
        )
        assert created.status_code == 201

        validation = client.post(
            "/api/settings/model-packs/vision-pack/validate?version=1"
        )
        assert validation.status_code == 200
        payload = validation.json()
        assert payload["valid"] is False
        assert any(
            issue["code"] == "capability_unsatisfied" and issue["tier"] == 2
            for issue in payload["issues"]
        )

        activation = client.post(
            "/api/settings/model-packs/vision-pack/activate?version=1"
        )
        assert activation.status_code == 409

    def test_validate_counts_unknown_models_as_not_satisfying(self, client):
        """A model absent from pack, settings, and registry satisfies nothing."""
        client.post(
            "/api/settings/model-packs",
            json={
                "id": "mystery-pack",
                "name": "Mystery pack",
                "tier_chains": {"1": ["ollama:mystery-model"]},
                "capability_requirements": {"1": ["vision"]},
            },
        )

        validation = client.post(
            "/api/settings/model-packs/mystery-pack/validate?version=1"
        )

        payload = validation.json()
        assert payload["valid"] is False
        assert any(
            issue["code"] == "capability_unsatisfied" for issue in payload["issues"]
        )

    def test_validate_warns_on_partially_satisfying_chain(self, client):
        """One satisfying candidate keeps the pack valid; the rest get warnings."""
        client.post(
            "/api/settings/model-packs",
            json={
                "id": "mixed-pack",
                "name": "Mixed pack",
                "tier_chains": {"2": ["ollama:llava", "ollama:text-only"]},
                "capability_requirements": {"2": ["vision"]},
                "model_capabilities": {
                    "ollama:llava": ["vision", "local"],
                    "ollama:text-only": ["fast"],
                },
            },
        )

        validation = client.post(
            "/api/settings/model-packs/mixed-pack/validate?version=1"
        )

        payload = validation.json()
        assert payload["valid"] is True
        partial = [i for i in payload["issues"] if i["code"] == "capability_partial"]
        assert [issue["model"] for issue in partial] == ["ollama:text-only"]

        activation = client.post(
            "/api/settings/model-packs/mixed-pack/activate?version=1"
        )
        assert activation.status_code == 200

    def test_validate_uses_global_capability_overrides_as_fallback(self, client):
        """Global settings capabilities apply when the pack has no override."""
        client.put(
            "/api/settings/tiers",
            json={"model_capabilities": {"ollama:llava": ["vision"]}},
        )
        client.post(
            "/api/settings/model-packs",
            json={
                "id": "global-caps",
                "name": "Global caps",
                "tier_chains": {"2": ["ollama:llava"]},
                "capability_requirements": {"2": ["vision"]},
            },
        )

        validation = client.post(
            "/api/settings/model-packs/global-caps/validate?version=1"
        )

        assert validation.json()["valid"] is True

    def test_deactivate_clears_global_activation_and_unblocks_archive(self, client):
        """DELETE /model-packs/active restores default routing and frees archive."""
        client.post(
            "/api/settings/model-packs",
            json={"id": "temp-pack", "name": "Temp pack", "source": "defaults"},
        )
        client.post("/api/settings/model-packs/temp-pack/activate?version=1")

        response = client.delete("/api/settings/model-packs/active")

        assert response.status_code == 200
        assert response.json()["active"] is None

        archived = client.post("/api/settings/model-packs/temp-pack/archive?version=1")
        assert archived.status_code == 200
        assert archived.json()["archived"] is True

    def test_deactivate_is_idempotent_when_nothing_is_active(self, client):
        response = client.delete("/api/settings/model-packs/active")

        assert response.status_code == 200
        assert response.json()["active"] is None
