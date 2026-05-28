"""Tests for JSON structured logging configuration (S2-6).

Covers:
- configure_logging("json") produces valid JSON output with expected fields.
- configure_logging("text") produces human-readable (non-JSON) output.
- LOG_FORMAT env var is picked up by Settings.
- ImportError fallback when python-json-logger is unavailable.
"""

from __future__ import annotations

import importlib
import json
import logging
import sys
from io import StringIO
from unittest.mock import patch

import pytest

from agentic_v2.logging_config import configure_logging
from agentic_v2.settings import Settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _capture_log_output(log_format: str, message: str = "test message") -> str:
    """Run configure_logging, emit one log record, return captured stdout text."""
    buf = StringIO()
    with patch("agentic_v2.logging_config.sys") as mock_sys:
        mock_sys.stdout = buf
        configure_logging(log_format=log_format, level=logging.DEBUG)
        log = logging.getLogger("test_json_logging_capture")
        log.info(message)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# JSON format tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_json_format_produces_valid_json() -> None:
    """configure_logging('json') should produce parseable JSON on each line."""
    buf = StringIO()
    with patch("agentic_v2.logging_config.sys") as mock_sys:
        mock_sys.stdout = buf
        configure_logging(log_format="json", level=logging.DEBUG)
        logging.getLogger("test_json_valid").info("hello json")

    output = buf.getvalue().strip()
    assert output, "Expected non-empty log output"

    # Each line must be valid JSON
    for line in output.splitlines():
        record = json.loads(line)  # raises if invalid
        assert isinstance(record, dict)


@pytest.mark.unit
def test_json_format_contains_expected_fields() -> None:
    """JSON log records should contain the required structured fields."""
    buf = StringIO()
    with patch("agentic_v2.logging_config.sys") as mock_sys:
        mock_sys.stdout = buf
        configure_logging(log_format="json", level=logging.DEBUG)
        logging.getLogger("test_json_fields").warning("field check")

    output = buf.getvalue().strip()
    assert output

    record = json.loads(output.splitlines()[-1])
    assert "message" in record
    assert "name" in record
    assert "service" in record
    assert record["service"] == "agentic-workflows-v2"
    assert record["message"] == "field check"
    assert record["name"] == "test_json_fields"


@pytest.mark.unit
def test_json_format_includes_level_field() -> None:
    """JSON log records should include a level/severity field."""
    buf = StringIO()
    with patch("agentic_v2.logging_config.sys") as mock_sys:
        mock_sys.stdout = buf
        configure_logging(log_format="json", level=logging.DEBUG)
        logging.getLogger("test_json_level").error("level field test")

    output = buf.getvalue().strip()
    assert output

    record = json.loads(output.splitlines()[-1])
    # python-json-logger emits 'levelname' or renames to 'level' via rename_fields
    level_value = record.get("level") or record.get("levelname") or ""
    assert "ERROR" in level_value.upper() or level_value.upper() == "ERROR"


# ---------------------------------------------------------------------------
# Text format tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_text_format_is_not_json() -> None:
    """configure_logging('text') should produce human-readable, non-JSON output."""
    buf = StringIO()
    with patch("agentic_v2.logging_config.sys") as mock_sys:
        mock_sys.stdout = buf
        configure_logging(log_format="text", level=logging.DEBUG)
        logging.getLogger("test_text_format").info("plain text message")

    output = buf.getvalue().strip()
    assert output, "Expected non-empty log output"

    for line in output.splitlines():
        with pytest.raises(json.JSONDecodeError):
            json.loads(line)


@pytest.mark.unit
def test_text_format_contains_message() -> None:
    """Text log output should contain the original log message."""
    buf = StringIO()
    with patch("agentic_v2.logging_config.sys") as mock_sys:
        mock_sys.stdout = buf
        configure_logging(log_format="text", level=logging.DEBUG)
        logging.getLogger("test_text_contains").info("unique-text-message-xyz")

    output = buf.getvalue()
    assert "unique-text-message-xyz" in output


# ---------------------------------------------------------------------------
# Settings / env var tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_settings_log_format_default_is_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings.log_format should default to 'text'."""
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    settings = Settings()
    assert settings.log_format == "text"


@pytest.mark.unit
def test_settings_log_format_json_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """LOG_FORMAT=json env var should be picked up by Settings."""
    monkeypatch.setenv("LOG_FORMAT", "json")
    settings = Settings()
    assert settings.log_format == "json"


@pytest.mark.unit
def test_settings_log_format_text_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """LOG_FORMAT=text env var should produce 'text'."""
    monkeypatch.setenv("LOG_FORMAT", "text")
    settings = Settings()
    assert settings.log_format == "text"


@pytest.mark.unit
def test_settings_log_format_invalid_falls_back_to_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unrecognised LOG_FORMAT value should fall back to 'text'."""
    monkeypatch.setenv("LOG_FORMAT", "yaml")
    settings = Settings()
    assert settings.log_format == "text"


@pytest.mark.unit
def test_settings_log_format_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    """LOG_FORMAT should be normalised to lowercase."""
    monkeypatch.setenv("LOG_FORMAT", "JSON")
    settings = Settings()
    assert settings.log_format == "json"


# ---------------------------------------------------------------------------
# ImportError fallback test
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fallback_to_text_when_pythonjsonlogger_missing() -> None:
    """When python-json-logger is unavailable, JSON format should fall back to text."""
    buf = StringIO()

    # Temporarily hide the pythonjsonlogger package from the import system
    original_modules = sys.modules.copy()
    # Remove the module from cache and block it
    for key in list(sys.modules.keys()):
        if "pythonjsonlogger" in key:
            del sys.modules[key]

    with patch.dict(sys.modules, {"pythonjsonlogger": None, "pythonjsonlogger.json": None}):
        # Reload logging_config so it re-evaluates the import
        import agentic_v2.logging_config as lc_module

        importlib.reload(lc_module)

        with patch.object(lc_module, "sys") as mock_sys:
            mock_sys.stdout = buf
            lc_module.configure_logging(log_format="json", level=logging.DEBUG)
            logging.getLogger("test_fallback").info("fallback message")

    output = buf.getvalue().strip()
    assert output, "Expected non-empty log output from fallback path"

    # Output should NOT be valid JSON — it should be the text format
    for line in output.splitlines():
        with pytest.raises(json.JSONDecodeError):
            json.loads(line)

    # Restore the module state
    importlib.reload(lc_module)
