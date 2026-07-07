"""Route tests for the catalog endpoints (personas / tools / observers)."""

from __future__ import annotations


class TestPersonasRoute:
    def test_lists_precanned_personas(self, client):
        response = client.get("/api/personas")

        assert response.status_code == 200
        personas = response.json()["personas"]
        ids = [p["id"] for p in personas]
        assert "winston_architect" in ids
        assert "architect" in ids

        winston = next(p for p in personas if p["id"] == "winston_architect")
        assert winston["name"] == "Winston"
        assert winston["role"] == "architect"
        assert "Winston" in winston["prompt_preview"]

    def test_prompt_file_personas_resolve_previews(self, client):
        personas = client.get("/api/personas").json()["personas"]
        architect = next(p for p in personas if p["id"] == "architect")
        assert architect["prompt_preview"]  # resolved from prompts/architect.md


class TestToolsRoute:
    def test_lists_tools_with_tier_membership(self, client):
        response = client.get("/api/tools")

        assert response.status_code == 200
        tools = {t["name"]: t for t in response.json()["tools"]}
        assert "file_read" in tools
        assert "web_search" in tools
        # file_read is in every tier's default set
        assert 0 in tools["file_read"]["tiers"]
        # shell_run only enters the default set at tier 2+
        assert min(tools["shell_run"]["tiers"]) >= 2
        assert tools["file_read"]["description"]


class TestObserversRoute:
    def test_lists_known_observer_channels(self, client):
        response = client.get("/api/observers")

        assert response.status_code == 200
        observers = {o["id"]: o["description"] for o in response.json()["observers"]}
        assert set(observers) == {"trace", "websocket", "scoring"}
        assert all(observers.values())
