"""Tests for NoProviderConfiguredError in SmartModelRouter.get_model_for_tier().

When zero providers are available AND AGENTIC_NO_LLM is not set, the router
must raise NoProviderConfiguredError instead of silently returning None.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from agentic_v2.core.errors import NoProviderConfiguredError, _NO_PROVIDER_MSG
from agentic_v2.models import (
    ModelTier,
    SmartModelRouter,
    reset_smart_router,
)

EXPECTED_NO_PROVIDER_MESSAGE = """No LLM provider configured.

To fix this, do ONE of the following:
  1. Set an API key:
      export OPENAI_API_KEY=sk-...
      export ANTHROPIC_API_KEY=sk-ant-...
      export GEMINI_API_KEY=...
      (See docs/ONBOARDING.md for the full list.)

  2. Use no-LLM mode:
      export AGENTIC_NO_LLM=1
      (Returns deterministic placeholder output - good for flow testing.)

More details: docs/NO_LLM_MODE.md"""


@pytest.fixture(autouse=True)
def _reset_router() -> Iterator[None]:
    """Ensure global router state is clean between tests."""
    reset_smart_router()
    yield
    reset_smart_router()


def test_raises_no_provider_error_when_no_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_model_for_tier() raises NoProviderConfiguredError when all models are
    unavailable and AGENTIC_NO_LLM is not set.
    """
    monkeypatch.delenv("AGENTIC_NO_LLM", raising=False)

    router = SmartModelRouter()
    # Mark every model in every tier unavailable so cross-tier fallback also exhausts.
    for tier in ModelTier:
        for model in router.get_chain(tier):
            router.mark_unavailable(model)

    with pytest.raises(NoProviderConfiguredError, match="AGENTIC_NO_LLM=1"):
        router.get_model_for_tier(ModelTier.TIER_2, allow_cross_tier=True)


def test_returns_none_silently_when_no_llm_flag_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When AGENTIC_NO_LLM=1 and no models are available, get_model_for_tier()
    returns None (caller handles no-LLM path).
    """
    monkeypatch.setenv("AGENTIC_NO_LLM", "1")

    router = SmartModelRouter()
    for tier in ModelTier:
        for model in router.get_chain(tier):
            router.mark_unavailable(model)

    result = router.get_model_for_tier(ModelTier.TIER_2, allow_cross_tier=True)
    assert result is None


def test_no_error_when_model_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_model_for_tier() must not raise when a healthy model is available."""
    monkeypatch.delenv("AGENTIC_NO_LLM", raising=False)

    router = SmartModelRouter()
    # Default: no models are explicitly unavailable, first chain model is healthy.
    result = router.get_model_for_tier(ModelTier.TIER_2)
    assert result is not None
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# E7-3: Core error type is single source of truth
# ---------------------------------------------------------------------------


def test_router_raises_core_error_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """Router must raise the core NoProviderConfiguredError, not a local subclass."""
    monkeypatch.delenv("AGENTIC_NO_LLM", raising=False)

    router = SmartModelRouter()
    for tier in ModelTier:
        for model in router.get_chain(tier):
            router.mark_unavailable(model)

    with pytest.raises(NoProviderConfiguredError):
        router.get_model_for_tier(ModelTier.TIER_2, allow_cross_tier=True)


def test_router_error_uses_core_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """Router error message must match the core error's default guidance text."""
    monkeypatch.delenv("AGENTIC_NO_LLM", raising=False)

    router = SmartModelRouter()
    for tier in ModelTier:
        for model in router.get_chain(tier):
            router.mark_unavailable(model)

    with pytest.raises(NoProviderConfiguredError) as exc_info:
        router.get_model_for_tier(ModelTier.TIER_2, allow_cross_tier=True)

    assert str(exc_info.value) == _NO_PROVIDER_MSG


# ---------------------------------------------------------------------------
# E7-3: CLI graceful handling with Rich Panel (no traceback)
# ---------------------------------------------------------------------------


def test_cli_catches_no_provider_error_gracefully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI must catch NoProviderConfiguredError and render Rich Panel without traceback."""
    monkeypatch.delenv("AGENTIC_NO_LLM", raising=False)

    cli_main = importlib.import_module("agentic_v2.cli.main")

    runner = CliRunner()
    fake_workflow = SimpleNamespace(name="test_no_provider", description="Test workflow")

    with (
        patch.object(cli_main, "load_workflow_config", return_value=fake_workflow, create=True),
        patch.object(
            cli_main,
            "_run_via_adapter",
            side_effect=NoProviderConfiguredError(),
        ),
    ):
        result = runner.invoke(
            cli_main.app,
            ["run", "test_no_provider", "--adapter", "native"],
        )

    assert result.exit_code == 1
    assert "Configuration Error" in result.output
    assert "No LLM provider configured." in result.output
    assert "OPENAI_API_KEY" in result.output
    assert "ANTHROPIC_API_KEY" in result.output
    assert "GEMINI_API_KEY" in result.output
    assert "AGENTIC_NO_LLM=1" in result.output
    assert "docs/ONBOARDING.md" in result.output
    assert "docs/NO_LLM_MODE.md" in result.output
    assert "Traceback" not in result.output


def test_server_maps_no_provider_to_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """FastAPI app must map NoProviderConfiguredError to HTTP 503 guidance JSON."""
    monkeypatch.delenv("AGENTIC_NO_LLM", raising=False)
    monkeypatch.delenv("AGENTIC_API_KEY", raising=False)

    from agentic_v2.server.app import create_app
    from fastapi.routing import APIRoute

    app = create_app()

    async def _raise_no_provider() -> None:
        raise NoProviderConfiguredError()

    # Insert test route at the beginning to avoid catch-all
    app.routes.insert(0, APIRoute("/_tests/no-provider", _raise_no_provider, methods=["GET"]))

    with TestClient(app) as client:
        response = client.get("/_tests/no-provider")

    assert response.status_code == 503
    payload = response.json()
    assert payload["detail"] == _NO_PROVIDER_MSG
