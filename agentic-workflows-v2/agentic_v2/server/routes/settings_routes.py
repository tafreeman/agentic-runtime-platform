"""Runtime settings routes: provider endpoints and model tier configuration.

* ``GET/PUT /api/settings/providers`` -- user-managed provider endpoint
  entries (OpenAI, Anthropic, GitHub Models, Ollama, Foundry Local, custom
  OpenAI-compatible endpoints). Secrets are referenced by environment
  variable name only; the credential itself is never accepted or returned.
* ``GET/PUT /api/settings/tiers`` -- model tier reranking overrides and
  model capability tags, layered over ``model_registry.yaml``.

State persists in the JSON store managed by :mod:`agentic_v2.ui_settings`.
"""

from __future__ import annotations

import logging
from typing import get_args

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from ...ui_settings import (
    KNOWN_MODEL_CAPABILITIES,
    ProviderType,
    UiSettings,
    load_ui_settings,
    save_ui_settings,
)
from ..models_settings import (
    ProviderSettingsResponse,
    ProviderSettingsUpdateRequest,
    TierChainModel,
    TierModelInfo,
    TierSettingsResponse,
    TierSettingsUpdateRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["settings"])


def _env_configured_providers() -> list[str]:
    """Providers currently usable through environment credentials."""
    from ...langchain.model_utils import PROVIDER_ENV_KEYS, is_provider_available

    return sorted(
        provider for provider in PROVIDER_ENV_KEYS if is_provider_available(provider)
    )


@router.get("/settings/providers", response_model=ProviderSettingsResponse)
async def get_provider_settings() -> ProviderSettingsResponse:
    """Return user-configured provider endpoints and known provider types."""
    settings = load_ui_settings()
    return ProviderSettingsResponse(
        providers=settings.providers,
        provider_types=list(get_args(ProviderType)),
        env_configured_providers=_env_configured_providers(),
    )


@router.put(
    "/settings/providers",
    response_model=ProviderSettingsResponse,
    responses={
        422: {"description": "Invalid provider configuration"},
        503: {"description": "Settings store is not writable"},
    },
)
async def put_provider_settings(
    request: ProviderSettingsUpdateRequest,
) -> ProviderSettingsResponse:
    """Replace the provider endpoint list."""
    current = load_ui_settings()
    try:
        updated = UiSettings(
            version=current.version,
            providers=request.providers,
            tier_overrides=current.tier_overrides,
            model_capabilities=current.model_capabilities,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _save_or_503(updated)
    return ProviderSettingsResponse(
        providers=updated.providers,
        provider_types=list(get_args(ProviderType)),
        env_configured_providers=_env_configured_providers(),
    )


def _tier_settings_response(settings: UiSettings) -> TierSettingsResponse:
    """Assemble the tier configuration view from registry + overrides."""
    from ...models.model_registry import load_registry

    registry = load_registry()
    tiers: list[TierChainModel] = []
    for tier in range(6):
        default_chain = list(registry.tiers.get(tier, ()))
        override = list(settings.tier_overrides.get(tier, []))
        effective = override + [m for m in default_chain if m not in override]
        tiers.append(
            TierChainModel(
                tier=tier,
                default_chain=default_chain,
                override=override,
                effective=effective,
            )
        )

    models: list[TierModelInfo] = []
    for model in registry.models:
        override_caps = settings.model_capabilities.get(model.id)
        models.append(
            TierModelInfo(
                id=model.id,
                provider=model.provider,
                capabilities=(
                    list(override_caps)
                    if override_caps is not None
                    else [model.capability]
                ),
                capability_overridden=override_caps is not None,
            )
        )

    return TierSettingsResponse(
        tiers=tiers,
        models=models,
        known_capabilities=list(KNOWN_MODEL_CAPABILITIES),
    )


@router.get("/settings/tiers", response_model=TierSettingsResponse)
async def get_tier_settings() -> TierSettingsResponse:
    """Return tier rankings, model capability tags, and override state."""
    return _tier_settings_response(load_ui_settings())


@router.put(
    "/settings/tiers",
    response_model=TierSettingsResponse,
    responses={
        422: {"description": "Invalid tier configuration"},
        503: {"description": "Settings store is not writable"},
    },
)
async def put_tier_settings(request: TierSettingsUpdateRequest) -> TierSettingsResponse:
    """Update tier reranking overrides and capability tags.

    Semantics are merge-per-key: only tiers/models present in the request
    change; an empty list clears that tier's or model's override.
    """
    current = load_ui_settings()
    tier_overrides = dict(current.tier_overrides)
    for tier, chain in request.tier_overrides.items():
        cleaned = [m.strip() for m in chain if m.strip()]
        if cleaned:
            tier_overrides[tier] = cleaned
        else:
            tier_overrides.pop(tier, None)

    known_capabilities = set(KNOWN_MODEL_CAPABILITIES)
    model_capabilities = dict(current.model_capabilities)
    for model_id, capabilities in request.model_capabilities.items():
        cleaned = [c.strip() for c in capabilities if c.strip()]
        unknown = sorted(set(cleaned) - known_capabilities)
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Unknown capabilities for {model_id!r}: {unknown}. "
                    f"Known: {sorted(known_capabilities)}."
                ),
            )
        if cleaned:
            model_capabilities[model_id] = cleaned
        else:
            model_capabilities.pop(model_id, None)

    try:
        updated = UiSettings(
            version=current.version,
            providers=current.providers,
            tier_overrides=tier_overrides,
            model_capabilities=model_capabilities,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _save_or_503(updated)
    return _tier_settings_response(updated)


def _save_or_503(settings: UiSettings) -> None:
    """Persist settings, translating filesystem failures to HTTP 503."""
    try:
        save_ui_settings(settings)
    except OSError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"UI settings store is not writable: {exc}",
        ) from exc
