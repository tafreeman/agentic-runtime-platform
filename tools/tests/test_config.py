"""Unit tests for tools.core.config."""

from __future__ import annotations

import pytest

from tools.core.config import Config, ModelConfig, PathConfig


class TestModelConfig:
    def test_defaults(self):
        cfg = ModelConfig()
        assert cfg.generator_model == "gpt-4o-mini"
        assert cfg.reviewer_model == "gpt-4o-mini"
        assert cfg.refiner_model == "gpt-4o-mini"
        assert cfg.generator_temp == 0.7
        assert cfg.reviewer_temp == 0.0
        assert cfg.refiner_temp == 0.5

    def test_custom_values(self):
        cfg = ModelConfig(generator_model="claude-3-haiku", generator_temp=0.3)
        assert cfg.generator_model == "claude-3-haiku"
        assert cfg.generator_temp == 0.3
        # Other fields remain default
        assert cfg.reviewer_model == "gpt-4o-mini"


class TestPathConfig:
    def test_defaults(self):
        cfg = PathConfig()
        assert cfg.templates_dir == "prompts/"
        assert cfg.instructions_dir == "instructions/"
        assert "rubrics" in cfg.rubric_path


class TestConfig:
    def test_default_construction(self):
        cfg = Config()
        assert cfg.models is not None
        assert cfg.paths is not None

    def test_env_override_gen_model(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GEN_MODEL", "claude-3-5-sonnet")
        cfg = Config()
        assert cfg.models.generator_model == "claude-3-5-sonnet"

    def test_env_override_rev_model(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("REV_MODEL", "gemini-1.5-pro")
        cfg = Config()
        assert cfg.models.reviewer_model == "gemini-1.5-pro"

    def test_env_override_ref_model(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("REF_MODEL", "gpt-4o")
        cfg = Config()
        assert cfg.models.refiner_model == "gpt-4o"

    def test_missing_env_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("GEN_MODEL", raising=False)
        cfg = Config()
        assert cfg.models.generator_model == "gpt-4o-mini"
