"""Tests for centralised Settings class."""
from __future__ import annotations


def test_settings_defaults_load_without_env(monkeypatch):
    """All optional settings load with defaults when env vars are absent."""
    monkeypatch.delenv("AGENTIC_TRACING", raising=False)
    monkeypatch.delenv("AGENTIC_FILE_BASE_DIR", raising=False)
    monkeypatch.delenv("AGENTIC_BLOCK_PRIVATE_IPS", raising=False)
    # Clear SHELL so Git Bash on Windows doesn't override the default value.
    monkeypatch.delenv("SHELL", raising=False)

    from agentic_v2.settings import Settings

    s = Settings()
    assert s.agentic_tracing is False
    assert s.agentic_file_base_dir is None
    assert s.shell == "/bin/bash"


def test_settings_reads_env_vars(monkeypatch):
    """Settings picks up values from environment variables."""
    monkeypatch.setenv("AGENTIC_TRACING", "1")
    monkeypatch.setenv("AGENTIC_FILE_BASE_DIR", "/tmp/files")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "my-svc")

    # Settings() reads os.environ at construction, so no importlib.reload is
    # needed — and reloading agentic_v2.settings creates a split-brain
    # get_settings cache that pollutes later tests (see test_ek_default_on).
    from agentic_v2.settings import Settings

    s = Settings()
    assert s.agentic_tracing is True
    assert s.agentic_file_base_dir == "/tmp/files"
    assert s.otel_service_name == "my-svc"


def test_get_settings_returns_singleton():
    """get_settings() returns the same object on repeated calls."""
    from agentic_v2.settings import get_settings

    a = get_settings()
    b = get_settings()
    assert a is b
