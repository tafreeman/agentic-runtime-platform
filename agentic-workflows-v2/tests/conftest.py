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

import agentic_v2.settings as _settings_module
from agentic_v2.langchain.config import load_workflow_config
from agentic_v2.models.client import get_client, reset_client


@pytest.fixture(autouse=True)
def _snapshot_os_environ():
    """Snapshot ``os.environ`` before each test and restore it afterwards.

    Defined FIRST so it is set up first and torn down LAST (outermost). This
    is the suite's backstop against env-var leakage: a test that writes to
    ``os.environ`` directly (instead of via ``monkeypatch``) — or a module-level
    ``os.environ.setdefault`` evaluated at import time — would otherwise leak
    that variable into every later test and make the suite order-dependent.
    ``monkeypatch`` changes are already undone by its own teardown (which runs
    before this one), so restoring here only reverts the unmanaged writes.

    This neutralises the whole class of "ambient flag leaked session-wide"
    polluters (``AGENTIC_NO_LLM``, ``AGENTIC_EK_PROVIDER``, provider keys, …)
    that previously masked or unmasked failures depending on collection order.
    """
    saved = dict(os.environ)
    yield
    if os.environ != saved:
        os.environ.clear()
        os.environ.update(saved)


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """Bracket every test with a ``get_settings()`` cache reset (ADR-023 B-1).

    ``get_settings`` is ``lru_cache(maxsize=1)``-d, so any test that mutates an
    env var feeding ``Settings`` (``AGENTIC_EK_PROVIDER``, ``AGENTIC_NO_LLM``,
    ``AGENTIC_OIDC_*``, …) can leave a stale singleton cached for later tests.
    Per-fixture clears were racy: a fixture's post-yield ``cache_clear()`` runs
    *before* the ``monkeypatch`` it depends on restores the env, so nothing
    guarantees a clean cache once the env is back to baseline.

    We clear via the LIVE module attribute (``_settings_module.get_settings``)
    rather than a name bound at import time: if any test ever rebinds the
    settings module's ``get_settings`` (e.g. via ``importlib.reload``), the live
    attribute is the function the production code under test actually calls, so
    we always clear the cache that matters and avoid a split-brain where the
    code reads a stale cached ``Settings`` that no test could clear.

    Ordered after ``_snapshot_os_environ`` so its setup clear runs once the env
    is at the per-test baseline and the next test always re-reads fresh settings.
    """
    _settings_module.get_settings.cache_clear()
    yield
    _settings_module.get_settings.cache_clear()


@pytest.fixture(autouse=True)
def clear_workflow_cache():
    """Clear the load_workflow_config LRU cache before and after each test."""
    load_workflow_config.cache_clear()
    yield
    load_workflow_config.cache_clear()


@pytest.fixture(autouse=True)
def _reset_global_routers():
    """Reset the module-global router singletons around every test.

    ``smart_router._smart_router`` and ``router._default_router`` are process
    globals that accumulate circuit-breaker / model-stats state. Left unreset,
    that state leaks across tests (a test that opens breakers can make a later
    test see "sick" models), contributing to order-dependent failures. Reset is
    best-effort: the helpers are imported lazily so this fixture stays usable
    even if a module is monkeypatched out of ``sys.modules`` mid-test.
    """

    def _reset() -> None:
        try:
            from agentic_v2.models.smart_router import reset_smart_router

            reset_smart_router()
        except (ImportError, AttributeError):
            pass
        try:
            import agentic_v2.models.router as _router_mod

            _router_mod._default_router = None
        except (ImportError, AttributeError):
            pass

    _reset()
    yield
    _reset()


@pytest.fixture(autouse=True)
def _reset_approval_provider():
    """Snapshot and restore the process-global approval provider around every test.

    ``governance.approval`` binds the human-approval policy to a module global
    (an application-level posture, set once at process start in production). In
    the test suite that global is mutated by approval-gate tests; a leaked
    provider (or a leaked ``None`` where a test primed one) makes later tests'
    tool dispatch order-dependent. Import is lazy and best-effort, mirroring
    ``_reset_global_routers``.
    """

    try:
        from agentic_v2.governance import approval as _approval_mod

        saved = _approval_mod.get_approval_provider()
    except (ImportError, AttributeError):
        saved = None
        _approval_mod = None  # type: ignore[assignment]
    yield
    if _approval_mod is not None:
        try:
            _approval_mod.set_approval_provider(saved)
        except (ImportError, AttributeError):
            pass


@pytest.fixture(autouse=True)
def _reset_llm_client():
    """Pre-create a backend-less global client for each test.

    IMPORTANT: ``get_client()`` reads ``get_settings().agentic_no_llm`` and thus
    *populates* the settings ``lru_cache`` with the current (baseline) env. If
    left populated, code under test that reads the LIVE
    ``agentic_v2.settings.get_settings`` (``get_client``, ``LLMClientWrapper.complete``,
    ``langchain.get_chat_model`` — all import it at call time) would see that
    stale cached ``Settings`` even after a test sets ``AGENTIC_NO_LLM`` /
    ``AGENTIC_EK_PROVIDER`` and clears its *own* (module-bound) ``get_settings``
    reference. Under the full suite those two references can diverge (a settings
    reload elsewhere rebinds the live attribute), producing a split-brain where
    the test reads the flag as True but the callee reads the stale False.

    Clearing the LIVE cache here — as the last thing this fixture does at setup —
    guarantees an empty cache at the start of every test body, so the first read
    of the live ``get_settings`` re-reads the environment the test just set. This
    is the order-independence backstop for the flag-driven hot paths.
    """
    reset_client()
    # Eagerly create a backend-less client; subsequent get_client() calls
    # will return this instance because _client is no longer None.
    get_client(auto_configure=False)
    # Drop the Settings the line above just cached so the live cache is empty
    # when the test body runs (see docstring).
    _settings_module.get_settings.cache_clear()
    yield
    reset_client()
    _settings_module.get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _default_shell_allowlist(monkeypatch: pytest.MonkeyPatch):
    """Keep legacy shell tests runnable while production remains fail-closed."""
    if not os.environ.get("AGENTIC_SHELL_ALLOWED_COMMANDS"):
        monkeypatch.setenv("AGENTIC_SHELL_ALLOWED_COMMANDS", "echo,python")
    yield


from agentic_v2.adapters.native import NativeEngine
from agentic_v2.adapters.registry import AdapterRegistry, get_registry


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
