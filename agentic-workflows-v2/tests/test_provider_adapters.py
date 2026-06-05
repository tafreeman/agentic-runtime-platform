"""Focused unit tests for tools.llm.provider_adapters.

Tests the adapter functions extracted during the refactoring described
in REFACTORING_PLAN.md.  Network calls are patched out with monkeypatch
or pytest fixtures so no live endpoints are required.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# call_ollama
# ---------------------------------------------------------------------------


class TestCallOllama:
    """Tests for the Ollama REST adapter."""

    def _make_successful_response(self, text: str = "Paris") -> MagicMock:
        """Build a mock HTTP response object that returns *text*."""
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps({"response": text}).encode("utf-8")
        return mock_resp

    def test_basic_call_returns_response(self) -> None:
        from tools.llm.provider_adapters import call_ollama

        mock_resp = self._make_successful_response("Paris")

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = call_ollama(
                "ollama:llama3", "What is the capital of France?", None
            )

        assert result == "Paris"

    def test_system_instruction_prepended(self) -> None:
        from tools.llm.provider_adapters import call_ollama

        captured: dict[str, Any] = {}

        def fake_urlopen(req, *, timeout):
            body = json.loads(req.data.decode("utf-8"))
            captured["prompt"] = body["prompt"]
            mock_resp = self._make_successful_response("ok")
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            call_ollama("ollama:llama3", "Hello", "You are helpful.")

        assert "System:" in captured["prompt"]
        assert "You are helpful." in captured["prompt"]

    def test_http_error_raises_runtime_error(self) -> None:
        from tools.llm.provider_adapters import call_ollama

        http_err = urllib.error.HTTPError(
            url="http://localhost:11434/api/generate",
            code=500,
            msg="Internal Server Error",
            hdrs=None,  # type: ignore[arg-type]
            fp=None,
        )

        with patch("urllib.request.urlopen", side_effect=http_err):
            with pytest.raises(RuntimeError, match="Ollama API error"):
                call_ollama("ollama:llama3", "prompt", None)

    def test_connection_error_raises_runtime_error(self) -> None:
        from tools.llm.provider_adapters import call_ollama

        url_err = urllib.error.URLError("Connection refused")

        with patch("urllib.request.urlopen", side_effect=url_err):
            with pytest.raises(RuntimeError, match="Ollama connection error"):
                call_ollama("ollama:llama3", "prompt", None)

    def test_uses_custom_ollama_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tools.llm.provider_adapters import call_ollama

        monkeypatch.setenv("OLLAMA_HOST", "http://myserver:8080")
        captured: dict[str, Any] = {}

        def fake_urlopen(req, *, timeout):
            captured["url"] = req.full_url
            mock_resp = self._make_successful_response("ok")
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            call_ollama("ollama:llama3", "prompt", None)

        assert "myserver:8080" in captured["url"]


# ---------------------------------------------------------------------------
# call_azure_openai – configuration guard tests (no live network needed)
# ---------------------------------------------------------------------------


class TestCallAzureOpenAI:
    """Tests for the Azure OpenAI adapter configuration logic."""

    def test_raises_when_endpoint_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tools.llm.provider_adapters import call_azure_openai

        # Remove all endpoint / key env vars to trigger the guard
        for var in [
            "AZURE_OPENAI_ENDPOINT",
            "AZURE_OPENAI_ENDPOINT_0",
            "AZURE_OPENAI_API_KEY",
            "AZURE_OPENAI_API_KEY_0",
        ]:
            monkeypatch.delenv(var, raising=False)

        with pytest.raises(ValueError, match="AZURE_OPENAI_ENDPOINT"):
            call_azure_openai("azure-openai:my-deployment", "prompt", None)

    def test_raises_when_key_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tools.llm.provider_adapters import call_azure_openai

        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
        for var in ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_API_KEY_0"]:
            monkeypatch.delenv(var, raising=False)

        with pytest.raises(ValueError, match="AZURE_OPENAI_API_KEY"):
            call_azure_openai("azure-openai:my-deployment", "prompt", None)

    def test_raises_when_deployment_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tools.llm.provider_adapters import call_azure_openai

        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")

        with pytest.raises(ValueError, match="deployment"):
            # "azure-openai" with no deployment suffix results in empty deployment
            call_azure_openai("azure-openai:", "prompt", None)


# ---------------------------------------------------------------------------
# resolve_local_model_path
# ---------------------------------------------------------------------------


class TestResolveLocalModelPath:
    """Tests for the local model path resolver."""

    def test_returns_none_for_unknown_key(self) -> None:
        from tools.llm.provider_adapters import resolve_local_model_path

        result = resolve_local_model_path(
            "unknown_model", local_models={"phi4": "some/path"}
        )
        assert result is None

    def test_returns_none_when_local_models_empty(self) -> None:
        from tools.llm.provider_adapters import resolve_local_model_path

        result = resolve_local_model_path("phi4", local_models={})
        assert result is None

    def test_resolves_known_key_to_path_or_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tools.llm.provider_adapters import resolve_local_model_path

        # Isolate the test from any real ~/.cache/aigallery on the machine.
        # The resolver uses Path.home() / ".cache" / "aigallery" as its scan
        # root; pointing home() at tmp_path ensures that directory is always
        # empty (it won't exist under tmp_path).
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

        # When the key is in local_models but the path doesn't exist on disk,
        # resolve_local_model_path should return None (not raise).
        result = resolve_local_model_path(
            "phi4", local_models={"phi4": str(tmp_path / "nonexistent" / "cpu")}
        )
        assert result is None
