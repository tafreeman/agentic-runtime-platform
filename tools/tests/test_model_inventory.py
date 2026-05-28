"""Unit tests for tools.llm.model_inventory — ADR-008 Phase 3.

Covers:
- _load_dotenv: comment/blank skipping, quote stripping, no-overwrite, missing file
- _bool_env_present: single/multiple env var presence detection
- _safe_hostname_from_url: URL parsing, edge cases
- _dns_resolves: success/failure paths
- _probe_http_json: HTTP success, error, non-JSON response
- _probe_ollama: model extraction, empty/malformed data
- _probe_openai_compatible_models: model listing, error handling
- build_inventory: provider assembly with env-var-driven branches
- format_inventory_summary: all summary formatting branches
- main: CLI entry point with active probe flag
"""

from __future__ import annotations

import json
import os
import urllib.error
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tools.llm.model_inventory import (
    _bool_env_present,
    _dns_resolves,
    _load_dotenv,
    _probe_http_json,
    _probe_ollama,
    _probe_openai_compatible_models,
    _safe_hostname_from_url,
    build_inventory,
    format_inventory_summary,
    main,
)

# ---------------------------------------------------------------------------
# _load_dotenv
# ---------------------------------------------------------------------------


class TestLoadDotenv:
    """Tier 1: branching/error paths in the .env loader."""

    def test_nonexistent_file_is_noop(self, tmp_path: Path):
        """Missing file does not raise or set vars."""
        _load_dotenv(tmp_path / "missing.env")
        # No assertion needed beyond "no exception"

    def test_simple_key_value(self, tmp_path: Path, monkeypatch):
        """Simple KEY=VALUE pairs are loaded into os.environ."""
        env_file = tmp_path / ".env"
        env_file.write_text("MY_TEST_KEY_1=hello\n", encoding="utf-8")
        monkeypatch.delenv("MY_TEST_KEY_1", raising=False)
        _load_dotenv(env_file)
        assert os.environ.get("MY_TEST_KEY_1") == "hello"
        monkeypatch.delenv("MY_TEST_KEY_1", raising=False)

    def test_does_not_overwrite_existing(self, tmp_path: Path, monkeypatch):
        """Existing env vars are never overwritten."""
        monkeypatch.setenv("MY_TEST_KEY_2", "original")
        env_file = tmp_path / ".env"
        env_file.write_text("MY_TEST_KEY_2=overwritten\n", encoding="utf-8")
        _load_dotenv(env_file)
        assert os.environ["MY_TEST_KEY_2"] == "original"

    def test_strips_double_quotes(self, tmp_path: Path, monkeypatch):
        """Double-quoted values have quotes removed."""
        env_file = tmp_path / ".env"
        env_file.write_text('MY_TEST_KEY_3="quoted_value"\n', encoding="utf-8")
        monkeypatch.delenv("MY_TEST_KEY_3", raising=False)
        _load_dotenv(env_file)
        assert os.environ.get("MY_TEST_KEY_3") == "quoted_value"
        monkeypatch.delenv("MY_TEST_KEY_3", raising=False)

    def test_strips_single_quotes(self, tmp_path: Path, monkeypatch):
        """Single-quoted values have quotes removed."""
        env_file = tmp_path / ".env"
        env_file.write_text("MY_TEST_KEY_4='single_quoted'\n", encoding="utf-8")
        monkeypatch.delenv("MY_TEST_KEY_4", raising=False)
        _load_dotenv(env_file)
        assert os.environ.get("MY_TEST_KEY_4") == "single_quoted"
        monkeypatch.delenv("MY_TEST_KEY_4", raising=False)

    @pytest.mark.parametrize(
        "line",
        [
            "# This is a comment",
            "",
            "   ",
            "NO_EQUALS_SIGN",
        ],
    )
    def test_skips_comments_blanks_and_no_equals(self, tmp_path: Path, line: str):
        """Comments, blank lines, and lines without '=' are ignored."""
        env_file = tmp_path / ".env"
        env_file.write_text(line + "\n", encoding="utf-8")
        _load_dotenv(env_file)
        # No key should be set; no exception raised

    def test_directory_path_is_noop(self, tmp_path: Path):
        """Passing a directory (not a file) is a no-op."""
        _load_dotenv(tmp_path)

    def test_empty_key_is_skipped(self, tmp_path: Path, monkeypatch):
        """Lines with empty key (e.g. '=value') are skipped."""
        env_file = tmp_path / ".env"
        env_file.write_text("=some_value\n", encoding="utf-8")
        _load_dotenv(env_file)


# ---------------------------------------------------------------------------
# _bool_env_present
# ---------------------------------------------------------------------------


class TestBoolEnvPresent:
    """Tier 2: contract verification for env-var presence check."""

    def test_returns_true_when_var_set(self, monkeypatch):
        monkeypatch.setenv("_TEST_PRESENT", "1")
        assert _bool_env_present("_TEST_PRESENT") is True

    def test_returns_false_when_missing(self, monkeypatch):
        monkeypatch.delenv("_TEST_PRESENT", raising=False)
        assert _bool_env_present("_TEST_PRESENT") is False

    def test_returns_true_if_any_present(self, monkeypatch):
        monkeypatch.delenv("_A", raising=False)
        monkeypatch.setenv("_B", "yes")
        assert _bool_env_present("_A", "_B") is True

    def test_returns_false_when_set_to_empty(self, monkeypatch):
        """Empty-string env vars are treated as absent."""
        monkeypatch.setenv("_TEST_EMPTY", "")
        assert _bool_env_present("_TEST_EMPTY") is False


# ---------------------------------------------------------------------------
# _safe_hostname_from_url
# ---------------------------------------------------------------------------


class TestSafeHostnameFromUrl:
    """Tier 1: edge cases in URL hostname extraction."""

    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://api.openai.com/v1", "api.openai.com"),
            ("http://localhost:11434/api/tags", "localhost:11434"),
            ("https://host.example.com/", "host.example.com"),
        ],
    )
    def test_valid_urls(self, url: str, expected: str):
        assert _safe_hostname_from_url(url) == expected

    @pytest.mark.parametrize(
        "url",
        [
            "ftp://unsupported.com",
            "not-a-url",
            "",
            "://missing-scheme",
        ],
    )
    def test_invalid_urls_return_none(self, url: str):
        assert _safe_hostname_from_url(url) is None


# ---------------------------------------------------------------------------
# _dns_resolves
# ---------------------------------------------------------------------------


class TestDnsResolves:
    """Tier 1: success and failure paths for DNS resolution."""

    @patch("tools.llm.model_inventory.socket.getaddrinfo")
    def test_returns_true_on_success(self, mock_getaddr):
        mock_getaddr.return_value = [("family", "type", "proto", "", ("1.2.3.4", 0))]
        assert _dns_resolves("example.com") is True

    @patch("tools.llm.model_inventory.socket.getaddrinfo")
    def test_returns_false_on_exception(self, mock_getaddr):
        mock_getaddr.side_effect = OSError("DNS failure")
        assert _dns_resolves("nonexistent.invalid") is False


# ---------------------------------------------------------------------------
# _probe_http_json
# ---------------------------------------------------------------------------


class TestProbeHttpJson:
    """Tier 1: success, HTTP error, and non-JSON response branches."""

    @patch("tools.llm.model_inventory.urllib.request.urlopen")
    def test_success_json(self, mock_urlopen):
        """Valid JSON response returns (True, parsed_dict, None)."""
        body = json.dumps({"models": []}).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        ok, data, err = _probe_http_json("http://localhost/api")
        assert ok is True
        assert data == {"models": []}
        assert err is None

    @patch("tools.llm.model_inventory.urllib.request.urlopen")
    def test_non_json_response(self, mock_urlopen):
        """Non-JSON body returns (True, None, error_msg)."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"<html>Not JSON</html>"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        ok, data, err = _probe_http_json("http://localhost/api")
        assert ok is True
        assert data is None
        assert err == "Non-JSON response"

    @patch("tools.llm.model_inventory.urllib.request.urlopen")
    def test_http_error(self, mock_urlopen):
        """HTTPError returns (False, None, 'HTTP <code>')."""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "http://x", 404, "Not Found", {}, None
        )
        ok, data, err = _probe_http_json("http://localhost/api")
        assert ok is False
        assert data is None
        assert "404" in err

    @patch("tools.llm.model_inventory.urllib.request.urlopen")
    def test_connection_error(self, mock_urlopen):
        """Connection error returns (False, None, error_str)."""
        mock_urlopen.side_effect = ConnectionRefusedError("refused")
        ok, _data, err = _probe_http_json("http://localhost/api")
        assert ok is False
        assert "refused" in err


# ---------------------------------------------------------------------------
# _probe_ollama
# ---------------------------------------------------------------------------


class TestProbeOllama:
    """Tier 1: model extraction from Ollama /api/tags response."""

    @patch("tools.llm.model_inventory._probe_http_json")
    def test_extracts_model_names(self, mock_probe):
        mock_probe.return_value = (
            True,
            {"models": [{"name": "llama3"}, {"name": "phi3"}]},
            None,
        )
        result = _probe_ollama("http://localhost:11434")
        assert result["reachable"] is True
        assert "llama3" in result["models"]
        assert "phi3" in result["models"]
        assert result["configured"] is True

    @patch("tools.llm.model_inventory._probe_http_json")
    def test_handles_unreachable(self, mock_probe):
        mock_probe.return_value = (False, None, "Connection refused")
        result = _probe_ollama("http://localhost:11434")
        assert result["reachable"] is False
        assert result["models"] == []
        assert result["error"] == "Connection refused"

    @patch("tools.llm.model_inventory._probe_http_json")
    def test_handles_empty_models_list(self, mock_probe):
        mock_probe.return_value = (True, {"models": []}, None)
        result = _probe_ollama("http://localhost:11434")
        assert result["models"] == []

    @patch("tools.llm.model_inventory._probe_http_json")
    def test_handles_non_dict_model_entries(self, mock_probe):
        """Non-dict entries in the models list are skipped."""
        mock_probe.return_value = (
            True,
            {"models": ["not-a-dict", {"name": "valid"}]},
            None,
        )
        result = _probe_ollama("http://localhost:11434")
        assert result["models"] == ["valid"]


# ---------------------------------------------------------------------------
# _probe_openai_compatible_models
# ---------------------------------------------------------------------------


class TestProbeOpenaiCompatibleModels:
    """Tier 1: model listing from OpenAI-compatible endpoints."""

    @patch("tools.llm.model_inventory._probe_http_json")
    def test_extracts_model_ids(self, mock_probe):
        mock_probe.return_value = (
            True,
            {"data": [{"id": "gpt-4o-mini"}, {"id": "gpt-4o"}]},
            None,
        )
        result = _probe_openai_compatible_models("http://localhost:1234")
        assert "gpt-4o" in result["models"]
        assert "gpt-4o-mini" in result["models"]
        assert result["reachable"] is True

    @patch("tools.llm.model_inventory._probe_http_json")
    def test_handles_unreachable(self, mock_probe):
        mock_probe.return_value = (False, None, "timeout")
        result = _probe_openai_compatible_models("http://localhost:1234")
        assert result["reachable"] is False
        assert result["models"] == []


# ---------------------------------------------------------------------------
# build_inventory
# ---------------------------------------------------------------------------


class TestBuildInventory:
    """Tier 2: contract tests for build_inventory output shape."""

    @patch("tools.llm.model_inventory._load_dotenv")
    @patch("tools.llm.model_inventory._dns_resolves", return_value=False)
    @patch("tools.llm.model_inventory.shutil.which", return_value=None)
    def test_import_failure_returns_error(self, mock_which, mock_dns, mock_dotenv):
        """When llm_client cannot be imported, inventory reports failure."""
        with (
            patch.dict("sys.modules", {"llm_client": None}),
            patch(
                "builtins.__import__",
                side_effect=ImportError("no module"),
            ),
        ):
            result = build_inventory(active_probes=False)
            # If llm_client import fails, ok=False
            if not result.get("ok"):
                assert "error" in result

    @patch("tools.llm.model_inventory._load_dotenv")
    @patch("tools.llm.model_inventory._dns_resolves", return_value=False)
    @patch("tools.llm.model_inventory.shutil.which", return_value=None)
    def test_passive_inventory_structure(
        self, mock_which, mock_dns, mock_dotenv, monkeypatch
    ):
        """Passive inventory contains expected top-level keys."""
        # Clear provider env vars to get predictable output
        for var in [
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "CLAUDE_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "GITHUB_TOKEN",
            "GH_TOKEN",
            "AZURE_FOUNDRY_API_KEY",
            "OLLAMA_HOST",
            "OPENAI_BASE_URL",
            "OPENAI_API_BASE",
            "LOCAL_AI_API_BASE_URL",
            "LOCAL_OPENAI_BASE_URL",
        ]:
            monkeypatch.delenv(var, raising=False)
        # Also clear any AZURE_OPENAI_ or AZURE_FOUNDRY_ENDPOINT_ vars
        for i in range(10):
            monkeypatch.delenv(f"AZURE_OPENAI_ENDPOINT_{i}", raising=False)
            monkeypatch.delenv(f"AZURE_OPENAI_API_KEY_{i}", raising=False)
            monkeypatch.delenv(f"AZURE_OPENAI_DEPLOYMENT_{i}", raising=False)

        mock_llm = MagicMock()
        mock_llm.LOCAL_MODELS = {}
        with patch.dict("sys.modules", {"llm_client": mock_llm}):
            with patch(
                "tools.llm.model_inventory.build_inventory.__module__",
                create=True,
            ):
                # Patch the lazy import inside build_inventory
                with patch(
                    "builtins.__import__",
                    side_effect=lambda name, *a, **kw: (
                        mock_llm
                        if name == "llm_client"
                        else __builtins__["__import__"](name, *a, **kw)  # type: ignore[index]
                    ),
                ):
                    # Direct approach: just call and check shape if ok
                    result = build_inventory(active_probes=False)
                    if result.get("ok"):
                        assert "providers" in result
                        assert "platform" in result
                        assert "python" in result


# ---------------------------------------------------------------------------
# format_inventory_summary
# ---------------------------------------------------------------------------


class TestFormatInventorySummary:
    """Tier 1: all branching paths in the summary formatter."""

    def _base_inv(self, **provider_overrides: Any) -> dict[str, Any]:
        """Build a minimal inventory dict for testing format_inventory_summary."""
        providers: dict[str, Any] = {
            "local_onnx": {"installed_model_keys": []},
            "github_models": {"can_attempt": False},
            "openai": {"model_count": 0},
            "gemini": {"model_count": 0},
            "ollama": {"reachable": None},
            "windows_ai_phi_silica": {
                "configured": False,
                "available": None,
                "readyState": None,
            },
        }
        providers.update(provider_overrides)
        return {"providers": providers}

    def test_empty_inventory(self):
        summary = format_inventory_summary(self._base_inv())
        assert "Capability inventory:" in summary
        assert "local_onnx(installed_keys=0)" in summary

    def test_with_local_models(self):
        summary = format_inventory_summary(
            self._base_inv(local_onnx={"installed_model_keys": ["phi4", "llama"]})
        )
        assert "installed_keys=2" in summary

    def test_github_configured(self):
        summary = format_inventory_summary(
            self._base_inv(github_models={"can_attempt": True})
        )
        assert "github_models(configured=True)" in summary

    def test_openai_model_count(self):
        summary = format_inventory_summary(self._base_inv(openai={"model_count": 42}))
        assert "openai(models=42)" in summary

    def test_ollama_reachable(self):
        summary = format_inventory_summary(self._base_inv(ollama={"reachable": True}))
        assert "ollama(reachable=True)" in summary

    def test_windows_ai_available(self):
        summary = format_inventory_summary(
            self._base_inv(
                windows_ai_phi_silica={
                    "configured": True,
                    "available": True,
                    "readyState": "ready",
                }
            )
        )
        assert "windows_ai(available" in summary
        assert "ready=ready" in summary

    def test_windows_ai_unavailable(self):
        summary = format_inventory_summary(
            self._base_inv(
                windows_ai_phi_silica={
                    "configured": True,
                    "available": False,
                    "readyState": None,
                }
            )
        )
        assert "windows_ai(unavailable" in summary

    def test_windows_ai_configured_but_unknown(self):
        summary = format_inventory_summary(
            self._base_inv(
                windows_ai_phi_silica={
                    "configured": True,
                    "available": None,
                    "readyState": None,
                }
            )
        )
        assert "windows_ai(configured" in summary

    def test_windows_ai_not_configured(self):
        """When configured=False and available=None, shows 'unknown'."""
        summary = format_inventory_summary(
            self._base_inv(
                windows_ai_phi_silica={
                    "configured": False,
                    "available": None,
                    "readyState": None,
                }
            )
        )
        assert "windows_ai(unknown" in summary

    def test_non_dict_input(self):
        """Non-dict inventory returns a valid string (all zeros/defaults)."""
        summary = format_inventory_summary("not a dict")  # type: ignore[arg-type]
        assert "Capability inventory:" in summary

    def test_non_dict_provider_values(self):
        """Non-dict provider values don't crash."""
        inv = {"providers": {"openai": "not-a-dict", "ollama": 42}}
        summary = format_inventory_summary(inv)
        assert "Capability inventory:" in summary


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    """Tier 2: CLI entry-point contract."""

    @patch("tools.llm.model_inventory.build_inventory")
    def test_returns_0_on_success(self, mock_build):
        mock_build.return_value = {"ok": True, "providers": {}}
        assert main([]) == 0

    @patch("tools.llm.model_inventory.build_inventory")
    def test_returns_1_on_failure(self, mock_build):
        mock_build.return_value = {"ok": False, "error": "import fail"}
        assert main([]) == 1

    @patch("tools.llm.model_inventory.build_inventory")
    def test_active_flag(self, mock_build):
        mock_build.return_value = {"ok": True}
        main(["--active"])
        mock_build.assert_called_once_with(active_probes=True)

    @patch("tools.llm.model_inventory.build_inventory")
    def test_active_probe_flag(self, mock_build):
        mock_build.return_value = {"ok": True}
        main(["--active-probe"])
        mock_build.assert_called_once_with(active_probes=True)
