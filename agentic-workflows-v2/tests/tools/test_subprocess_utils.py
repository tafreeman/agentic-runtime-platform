"""Tests that minimal_subprocess_env() excludes API keys and secrets."""

from __future__ import annotations

import os
from unittest.mock import patch

from agentic_v2.tools.subprocess_utils import minimal_subprocess_env

_SECRET_KEYS = [
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GITHUB_TOKEN",
    "AZURE_OPENAI_API_KEY_0",
    "GEMINI_API_KEY",
    "DATABASE_URL",
    "SECRET_KEY",
]


def test_api_keys_excluded():
    """API keys must never appear in the subprocess environment."""
    fake_secrets = {k: "sk-fake-value-1234" for k in _SECRET_KEYS}
    with patch.dict(os.environ, fake_secrets):
        env = minimal_subprocess_env()
    for key in _SECRET_KEYS:
        assert key not in env, f"Secret key {key!r} leaked into subprocess env"


def test_path_present():
    """PATH must be present so executables can be found."""
    env = minimal_subprocess_env()
    assert any(k.upper() == "PATH" for k in env), "PATH missing from sparse env"


def test_pythondontwritebytecode_set():
    env = minimal_subprocess_env()
    assert env.get("PYTHONDONTWRITEBYTECODE") == "1"


def test_sparse_is_subset_of_full():
    """Every key returned must exist in os.environ or be our injected key."""
    env = minimal_subprocess_env()
    full = {k.upper() for k in os.environ}
    for key in env:
        if key == "PYTHONDONTWRITEBYTECODE":
            continue
        assert key.upper() in full, f"Phantom key {key!r} injected into sparse env"
