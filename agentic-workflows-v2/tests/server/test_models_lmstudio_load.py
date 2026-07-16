"""LM Studio model-load route contracts."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from agentic_v2.models.local_discovery import (
    LmStudioLoadError,
    LmStudioUnavailableError,
    LocalModelInfo,
)
from agentic_v2.server.routes import models as model_routes


@pytest.mark.asyncio
async def test_load_lmstudio_loads_one_discovered_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        model_routes,
        "discover_lmstudio_models",
        lambda: [LocalModelInfo(id="lmstudio:google/gemma-3-4b")],
    )
    captured: list[str] = []

    def _load(model_key: str):
        captured.append(model_key)
        return {
            "status": "loaded",
            "instance_id": "gemma-instance",
            "load_time_seconds": 2.5,
        }

    monkeypatch.setattr(model_routes, "load_lmstudio_model", _load)

    result = await model_routes.load_lmstudio(
        model_routes.LmStudioLoadRequest(model="lmstudio:google/gemma-3-4b")
    )

    assert captured == ["google/gemma-3-4b"]
    assert result.model == "lmstudio:google/gemma-3-4b"
    assert result.status == "loaded"
    assert result.instance_id == "gemma-instance"
    assert result.load_time_seconds == 2.5
    assert result.running is True


@pytest.mark.asyncio
async def test_load_lmstudio_is_idempotent_for_running_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        model_routes,
        "discover_lmstudio_models",
        lambda: [LocalModelInfo(id="lmstudio:google/gemma-3-4b", running=True)],
    )
    monkeypatch.setattr(
        model_routes,
        "load_lmstudio_model",
        lambda _model: pytest.fail("already-loaded model must not be loaded again"),
    )

    result = await model_routes.load_lmstudio(
        model_routes.LmStudioLoadRequest(model="google/gemma-3-4b")
    )

    assert result.status == "already_loaded"
    assert result.running is True


@pytest.mark.asyncio
async def test_load_lmstudio_rejects_models_outside_discovered_chat_library(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_routes, "discover_lmstudio_models", lambda: [])

    with pytest.raises(HTTPException) as exc_info:
        await model_routes.load_lmstudio(
            model_routes.LmStudioLoadRequest(model="lmstudio:not-downloaded")
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (LmStudioUnavailableError("server unavailable"), 503),
        (LmStudioLoadError("load rejected"), 502),
    ],
)
async def test_load_lmstudio_maps_upstream_errors(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status_code: int,
) -> None:
    monkeypatch.setattr(
        model_routes,
        "discover_lmstudio_models",
        lambda: [LocalModelInfo(id="lmstudio:google/gemma-3-4b")],
    )

    def _raise(_model: str) -> None:
        raise error

    monkeypatch.setattr(model_routes, "load_lmstudio_model", _raise)

    with pytest.raises(HTTPException) as exc_info:
        await model_routes.load_lmstudio(
            model_routes.LmStudioLoadRequest(model="google/gemma-3-4b")
        )

    assert exc_info.value.status_code == status_code


def test_load_lmstudio_request_rejects_control_characters() -> None:
    with pytest.raises(ValidationError, match="control characters"):
        model_routes.LmStudioLoadRequest(model="google/gemma\n3-4b")
