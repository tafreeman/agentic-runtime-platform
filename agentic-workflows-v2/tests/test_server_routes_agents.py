"""Tests for agent listing API routes."""

from __future__ import annotations

from pathlib import Path

import agentic_v2.server.routes.agents as agents_module
import pytest
import yaml
from agentic_v2.server.routes.agents import _discover_agents


class TestDiscoverAgents:
    """Tests for _discover_agents internal function."""

    def test_missing_config_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """When agents.yaml doesn't exist, returns empty list."""
        nonexistent = tmp_path / "nonexistent" / "agents.yaml"
        monkeypatch.setattr(agents_module, "_AGENTS_CONFIG_PATH", nonexistent)

        result = _discover_agents()
        assert result == []

    def test_valid_config_returns_agents(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Valid YAML config returns agent list."""
        config = {
            "agents": {
                "coder": {
                    "name": "Coder Agent",
                    "description": "Writes code",
                    "tier": "1",
                },
                "reviewer": {
                    "name": "Reviewer",
                    "description": "Reviews code",
                    "tier": "2",
                },
            }
        }
        config_file = tmp_path / "agents.yaml"
        config_file.write_text(yaml.dump(config))
        monkeypatch.setattr(agents_module, "_AGENTS_CONFIG_PATH", config_file)

        result = _discover_agents()
        assert len(result) == 2
        names = [a.name for a in result]
        assert "Coder Agent" in names
        assert "Reviewer" in names

    def test_invalid_yaml_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Malformed YAML returns empty list without crashing."""
        config_file = tmp_path / "agents.yaml"
        config_file.write_text("{{{{not: valid: yaml::::")
        monkeypatch.setattr(agents_module, "_AGENTS_CONFIG_PATH", config_file)

        result = _discover_agents()
        assert result == []

    def test_non_dict_agents_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """When 'agents' key is not a dict, returns empty list."""
        config = {"agents": ["not", "a", "dict"]}
        config_file = tmp_path / "agents.yaml"
        config_file.write_text(yaml.dump(config))
        monkeypatch.setattr(agents_module, "_AGENTS_CONFIG_PATH", config_file)

        result = _discover_agents()
        assert result == []

    def test_agent_defaults_for_missing_fields(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Agent with missing fields uses defaults."""
        config = {"agents": {"minimal": {}}}
        config_file = tmp_path / "agents.yaml"
        config_file.write_text(yaml.dump(config))
        monkeypatch.setattr(agents_module, "_AGENTS_CONFIG_PATH", config_file)

        result = _discover_agents()
        assert len(result) == 1
        assert result[0].name == "minimal"  # Falls back to agent_id
        assert result[0].description == ""
        assert result[0].tier == "2"
