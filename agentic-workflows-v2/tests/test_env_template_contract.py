"""Contract tests for the root environment template."""
from __future__ import annotations

from pathlib import Path

REQUIRED_ENV_EXAMPLE_KEYS = {
    "AGENTIC_API_KEY",
    "AGENTIC_CORS_ORIGINS",
    "AGENTIC_NO_LLM",
    "AGENTIC_TOKEN_BUDGET",
    "AGENTIC_EXTERNAL_AGENTS_DIR",
    "SHELL",
    "AGENTIC_FILE_BASE_DIR",
    "AGENTIC_SHELL_ALLOWED_COMMANDS",
    "AGENTIC_BLOCK_PRIVATE_IPS",
    "AGENTIC_MEMORY_PATH",
    # Local model discovery (ADR-037/038) — operators wire these to surface
    # their local libraries in the model-router probe.
    "OLLAMA_BASE_URL",
    "LMSTUDIO_HOST",
    "ONNX_MODEL_DIR",
}


def test_root_env_example_contains_runtime_settings():
    """Root .env.example documents every runtime setting operators need."""
    repo_root = Path(__file__).resolve().parents[2]
    env_example = (repo_root / ".env.example").read_text(encoding="utf-8")

    missing = [
        key for key in sorted(REQUIRED_ENV_EXAMPLE_KEYS) if f"{key}=" not in env_example
    ]

    assert missing == []
