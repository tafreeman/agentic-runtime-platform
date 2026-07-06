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


def test_block_private_ips_default_on(monkeypatch):
    """SSRF guard is ON by default (P1 #13 — default flipped from False to True)."""
    monkeypatch.delenv("AGENTIC_BLOCK_PRIVATE_IPS", raising=False)

    import agentic_v2.settings as settings_mod

    settings_mod.get_settings.cache_clear()
    try:
        assert settings_mod.get_settings().agentic_block_private_ips is True
    finally:
        settings_mod.get_settings.cache_clear()


def test_block_private_ips_can_be_opted_out(monkeypatch):
    """Setting AGENTIC_BLOCK_PRIVATE_IPS=0 disables the guard (opt-out path)."""
    monkeypatch.setenv("AGENTIC_BLOCK_PRIVATE_IPS", "0")

    import agentic_v2.settings as settings_mod

    settings_mod.get_settings.cache_clear()
    try:
        assert settings_mod.get_settings().agentic_block_private_ips is False
    finally:
        settings_mod.get_settings.cache_clear()


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


def test_require_tool_approval_default_off(monkeypatch):
    """Global human-approval override is OFF by default (P1 #12)."""
    monkeypatch.delenv("AGENTIC_REQUIRE_TOOL_APPROVAL", raising=False)

    from agentic_v2.settings import Settings

    s = Settings()
    assert s.agentic_require_tool_approval is False
    assert s.agentic_approval_required_tools == ""


def test_require_tool_approval_parses_from_env(monkeypatch):
    """The global approval override and per-name list parse from env vars."""
    monkeypatch.setenv("AGENTIC_REQUIRE_TOOL_APPROVAL", "1")
    monkeypatch.setenv("AGENTIC_APPROVAL_REQUIRED_TOOLS", "git_commit, deploy")

    from agentic_v2.settings import Settings

    s = Settings()
    assert s.agentic_require_tool_approval is True
    assert s.agentic_approval_required_tools == "git_commit, deploy"


def test_replay_store_retention_default(monkeypatch):
    """replay_store_retention_seconds defaults to 3600s (1 hour) unset."""
    monkeypatch.delenv("REPLAY_STORE_RETENTION_SECONDS", raising=False)

    from agentic_v2.settings import Settings

    s = Settings()
    assert s.replay_store_retention_seconds == 3600


def test_replay_store_retention_reads_from_env(monkeypatch):
    """replay_store_retention_seconds parses from REPLAY_STORE_RETENTION_SECONDS."""
    monkeypatch.setenv("REPLAY_STORE_RETENTION_SECONDS", "120")

    from agentic_v2.settings import Settings

    s = Settings()
    assert s.replay_store_retention_seconds == 120


def test_replay_sqlite_path_defaults_to_empty_string(monkeypatch):
    """replay_sqlite_path defaults to "" unset.

    Resolved to an absolute path downstream by
    replay_store._resolve_absolute_sqlite_path — not a bare CWD-relative
    filename.
    """
    monkeypatch.delenv("REPLAY_SQLITE_PATH", raising=False)

    from agentic_v2.settings import Settings

    s = Settings()
    assert s.replay_sqlite_path == ""
