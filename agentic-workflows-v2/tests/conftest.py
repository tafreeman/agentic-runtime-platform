"""Shared test fixtures.

Ensures the global LLM client is reset before each test so that
unit tests get a backend-less client (placeholder mode) unless they
explicitly configure one.

The fixture pre-creates a backend-less client so that even calls to
``get_client(auto_configure=True)`` inside agent_resolver return the
placeholder client rather than probing for Ollama/cloud backends.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml
from agentic_v2.langchain.config import load_workflow_config
from agentic_v2.models.client import get_client, reset_client


@pytest.fixture(autouse=True)
def clear_workflow_cache():
    """Clear the load_workflow_config LRU cache before and after each test."""
    load_workflow_config.cache_clear()
    yield
    load_workflow_config.cache_clear()


@pytest.fixture(autouse=True)
def _reset_llm_client():
    """Pre-create a backend-less global client for each test."""
    reset_client()
    # Eagerly create a backend-less client; subsequent get_client() calls
    # will return this instance because _client is no longer None.
    get_client(auto_configure=False)
    yield
    reset_client()


@pytest.fixture(autouse=True)
def _default_shell_allowlist(monkeypatch: pytest.MonkeyPatch):
    """Keep legacy shell tests runnable while production remains fail-closed."""
    if "AGENTIC_SHELL_ALLOWED_COMMANDS" not in os.environ:
        monkeypatch.setenv("AGENTIC_SHELL_ALLOWED_COMMANDS", "echo,python")
    yield


from agentic_v2.adapters.registry import AdapterRegistry, get_registry
from agentic_v2.adapters.native import NativeEngine


def _register_builtin_adapters() -> None:
    """Re-register built-in adapters after a registry reset."""
    get_registry().register("native", NativeEngine)
    # Langchain adapter is optional — only registered when its dependency
    # tree (langchain-core, langgraph, etc.) is installed.
    try:
        from agentic_v2.adapters.langchain.engine import LangChainEngine

        get_registry().register("langchain", LangChainEngine)
    except ImportError:
        pass


@pytest.fixture(autouse=True)
def _reset_adapter_registry():
    """Snapshot and restore AdapterRegistry state around every test.

    Prevents adapter registrations made inside a test from leaking into
    subsequent tests, which is critical under pytest-xdist -n auto where
    test order is non-deterministic across workers.

    Built-in adapters (native) are re-registered after each reset so that
    tests that need them can use them without explicit setup.
    """
    AdapterRegistry.reset_for_tests()
    _register_builtin_adapters()
    yield
    AdapterRegistry.reset_for_tests()
    _register_builtin_adapters()


@pytest.fixture
def mock_backend() -> MagicMock:
    """Return a mock LLM backend that echoes its prompt."""
    backend = MagicMock()
    backend.generate.side_effect = lambda prompt, **_kw: f"mock: {prompt[:50]}"
    return backend


@pytest.fixture
def workflow_dir(tmp_path: Path) -> Path:
    """Temporary directory pre-configured for workflow YAML files."""
    return tmp_path


@pytest.fixture
def simple_workflow_yaml(workflow_dir: Path) -> Path:
    """A minimal single-step workflow YAML for use in tests."""
    data = {
        "name": "test-workflow",
        "description": "Minimal workflow for tests",
        "steps": [
            {
                "name": "step-one",
                "agent": "tier1",
                "description": "First step",
                "depends_on": [],
                "inputs": {"prompt": "hello"},
                "outputs": ["result"],
            }
        ],
    }
    path = workflow_dir / "test_workflow.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")
    return path


@pytest.fixture
def agent_config() -> dict[str, Any]:
    """Default agent configuration dict for tests."""
    return {
        "tier": "tier1",
        "model": "placeholder",
        "temperature": 0.0,
        "max_tokens": 512,
    }
