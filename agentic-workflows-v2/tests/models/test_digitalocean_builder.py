"""Tests for the DigitalOcean Serverless Inference model builder.

A ``digitalocean:<model>`` id must dispatch to :func:`build_digitalocean_model`
on the LangChain path, and the builder must point ``ChatOpenAI`` at
DigitalOcean's OpenAI-compatible ``/v1`` surface with the caller's token — the
same shape as the OpenRouter builder it mirrors. The NVIDIA suite exists
because a discovered id once fell through to Ollama silently; these tests lock
the new prefix in at every registration point so that cannot recur here.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest

from agentic_v2.langchain.model_builders import build_digitalocean_model
from agentic_v2.langchain.model_utils import PROVIDER_ENV_KEYS, is_provider_available
from agentic_v2.langchain.models import _KNOWN_PREFIXES, _PREFIX_BUILDERS

_DO_BASE = "https://inference.do-ai.run/v1"
_MODEL = "deepseek-v4-flash-0731"


class TestDigitalOceanDispatch:
    """digitalocean: must be a known prefix with a builder, not a fall-through."""

    def test_prefix_is_registered(self) -> None:
        assert "digitalocean:" in _KNOWN_PREFIXES
        assert ("digitalocean:", build_digitalocean_model) in _PREFIX_BUILDERS

    def test_provider_is_gated_on_its_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert PROVIDER_ENV_KEYS["digitalocean"] == ["DIGITALOCEAN_TOKEN"]
        monkeypatch.delenv("DIGITALOCEAN_TOKEN", raising=False)
        assert is_provider_available("digitalocean") is False
        monkeypatch.setenv("DIGITALOCEAN_TOKEN", "dop_v1_test")
        assert is_provider_available("digitalocean") is True


class TestDigitalOceanModelBuilder:
    """build_digitalocean_model wires ChatOpenAI at the right host/key/model."""

    @staticmethod
    def _capture_chat_openai(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        langchain_openai = pytest.importorskip("langchain_openai")
        captured: dict[str, Any] = {}

        class _StubChatOpenAI:
            def __init__(self, **kwargs: Any) -> None:
                captured.update(kwargs)

        monkeypatch.setattr(langchain_openai, "ChatOpenAI", _StubChatOpenAI)
        return captured

    def test_builds_against_do_endpoint_with_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = self._capture_chat_openai(monkeypatch)
        monkeypatch.setenv("DIGITALOCEAN_TOKEN", "dop_v1_test")

        build_digitalocean_model(_MODEL, 0.2)

        # The bare catalog id goes on the wire unchanged — no publisher segment.
        assert captured["model"] == _MODEL
        assert captured["base_url"] == _DO_BASE
        assert captured["api_key"] == "dop_v1_test"
        assert captured["temperature"] == 0.2

    def test_missing_token_raises_value_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._capture_chat_openai(monkeypatch)
        monkeypatch.delenv("DIGITALOCEAN_TOKEN", raising=False)

        with pytest.raises(ValueError, match="DIGITALOCEAN_TOKEN"):
            build_digitalocean_model(_MODEL, 0.0)

    def test_empty_token_is_treated_as_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._capture_chat_openai(monkeypatch)
        monkeypatch.setenv("DIGITALOCEAN_TOKEN", "")

        with pytest.raises(ValueError, match="DIGITALOCEAN_TOKEN"):
            build_digitalocean_model(_MODEL, 0.0)

    def test_missing_langchain_openai_raises_import_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DIGITALOCEAN_TOKEN", "dop_v1_test")
        monkeypatch.setitem(sys.modules, "langchain_openai", None)

        with pytest.raises(ImportError, match="langchain-openai"):
            build_digitalocean_model(_MODEL, 0.0)
