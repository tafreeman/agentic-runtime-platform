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
import os
import time
from datetime import UTC, datetime
from typing import get_args
from urllib.parse import urljoin

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import ValidationError

from ...ui_settings import (
    KNOWN_MODEL_CAPABILITIES,
    ModelPack,
    ModelPackRef,
    ProviderType,
    UiSettings,
    get_model_pack,
    is_valid_api_key_env,
    latest_model_pack,
    load_ui_settings,
    save_ui_settings,
)
from ...workflows.run_logger import RunLogger
from ..models_settings import (
    ModelPackCreateRequest,
    ModelPackDependenciesResponse,
    ModelPackDuplicateRequest,
    ModelPackExportResponse,
    ModelPackImportRequest,
    ModelPackIssue,
    ModelPackListResponse,
    ModelPackUpdateRequest,
    ModelPackValidationResponse,
    ProviderProbeResponse,
    ProviderSettingsResponse,
    ProviderSettingsUpdateRequest,
    TierChainModel,
    TierModelInfo,
    TierSettingsResponse,
    TierSettingsUpdateRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["settings"])
run_logger = RunLogger()

#: 422 detail for a credential-shaped ``api_key_env`` (write-side hardening;
#: reads stay lenient via the load-time sanitizer in ``agentic_v2.ui_settings``).
_API_KEY_ENV_DETAIL = (
    "api_key_env must be an environment variable NAME "
    "(e.g. OLLAMA_API_KEY), never the credential itself"
)


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
    """Replace the provider endpoint list.

    Writes are strict about ``api_key_env``: it must be an environment
    variable NAME, so a raw credential pasted into the field is rejected
    before it can be persisted (and later echoed) by the settings store.
    """
    for provider in request.providers:
        if provider.api_key_env is not None and not is_valid_api_key_env(
            provider.api_key_env
        ):
            raise HTTPException(status_code=422, detail=_API_KEY_ENV_DETAIL)
    current = load_ui_settings()
    try:
        updated = UiSettings(
            version=current.version,
            providers=request.providers,
            tier_overrides=current.tier_overrides,
            model_capabilities=current.model_capabilities,
            model_packs=current.model_packs,
            active_model_pack=current.active_model_pack,
            workflow_model_packs=current.workflow_model_packs,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _save_or_503(updated)
    return ProviderSettingsResponse(
        providers=updated.providers,
        provider_types=list(get_args(ProviderType)),
        env_configured_providers=_env_configured_providers(),
    )


def _provider_probe_endpoint(provider) -> str | None:
    """Return the safe discovery endpoint for a configured provider."""
    if not provider.base_url:
        return None
    suffix = "api/tags" if provider.type == "ollama" else "models"
    return urljoin(f"{provider.base_url}/", suffix)


def _provider_error_category(exc: Exception) -> tuple[str, str]:
    """Classify connection failures without exposing credentials or payloads."""
    if isinstance(exc, httpx.TimeoutException):
        return "timeout", "The provider did not respond before the probe timeout."
    if isinstance(exc, httpx.ConnectError):
        return "connection", "The provider endpoint could not be reached."
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in {401, 403}:
            return "authentication", "The provider rejected its configured credential."
        if status == 404:
            return "endpoint", "The provider discovery endpoint was not found."
        return "provider", f"The provider returned HTTP {status}."
    return "unknown", "The provider probe failed."


@router.post(
    "/settings/providers/{provider_id}/probe",
    response_model=ProviderProbeResponse,
    responses={404: {"description": "Provider not found"}},
)
async def probe_provider(provider_id: str) -> ProviderProbeResponse:
    """Test one saved provider without accepting or returning a raw secret."""
    settings = load_ui_settings()
    provider = next(
        (item for item in settings.providers if item.id == provider_id), None
    )
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    started = time.perf_counter()
    checked_at = datetime.now(UTC)
    endpoint = _provider_probe_endpoint(provider)
    if endpoint is None:
        # Cloud providers without an endpoint use the runtime's authoritative
        # availability probe. This performs the same real listing used at
        # startup and never exposes the credential.
        try:
            from .models import probe_models

            result = await probe_models()
            provider_name = "gh" if provider.type == "gh" else provider.type
            discovered = [
                model
                for model in result.get("models", [])
                if model.get("provider") == provider_name
            ]
            available = provider_name in result.get("available_providers", [])
            return ProviderProbeResponse(
                provider_id=provider.id,
                status="available" if available else "unavailable",
                checked_at=checked_at,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                discovered_model_count=len(discovered),
                error_category=None if available else "configuration",
                detail=(
                    "Provider responded to the runtime probe."
                    if available
                    else "The provider is saved but its deployment credential is unavailable."
                ),
            )
        except HTTPException as exc:
            return ProviderProbeResponse(
                provider_id=provider.id,
                status="error",
                checked_at=checked_at,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                error_category="runtime_probe",
                detail=str(exc.detail),
            )

    headers: dict[str, str] = {}
    if provider.api_key_env:
        credential = os.environ.get(provider.api_key_env)
        if credential:
            headers["Authorization"] = f"Bearer {credential}"
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
            response = await client.get(endpoint, headers=headers)
            response.raise_for_status()
            payload = response.json()
        entries = payload.get("models", payload.get("data", []))
        discovered_count = len(entries) if isinstance(entries, list) else 0
        return ProviderProbeResponse(
            provider_id=provider.id,
            status="available",
            checked_at=checked_at,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            discovered_model_count=discovered_count,
            detail="Provider discovery endpoint responded successfully.",
        )
    except (httpx.HTTPError, ValueError) as exc:
        category, detail = _provider_error_category(exc)
        return ProviderProbeResponse(
            provider_id=provider.id,
            status="error",
            checked_at=checked_at,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            error_category=category,
            detail=detail,
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
            model_packs=current.model_packs,
            active_model_pack=current.active_model_pack,
            workflow_model_packs=current.workflow_model_packs,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _save_or_503(updated)
    return _tier_settings_response(updated)


def _pack_ref(pack: ModelPack) -> ModelPackRef:
    return ModelPackRef(id=pack.id, version=pack.version)


def _pack_list_response(settings: UiSettings) -> ModelPackListResponse:
    return ModelPackListResponse(
        packs=sorted(settings.model_packs, key=lambda item: (item.name, -item.version)),
        active=settings.active_model_pack,
        workflow_bindings=settings.workflow_model_packs,
    )


def _require_pack(ref: ModelPackRef, settings: UiSettings) -> ModelPack:
    pack = get_model_pack(ref, settings)
    if pack is None:
        raise HTTPException(
            status_code=404,
            detail=f"Model pack {ref.id!r} version {ref.version} was not found.",
        )
    return pack


def _derived_tier_chains(source: str, settings: UiSettings) -> dict[int, list[str]]:
    if source not in {"effective", "defaults"}:
        return {}
    tiers = _tier_settings_response(settings).tiers
    return {
        tier.tier: list(tier.effective if source == "effective" else tier.default_chain)
        for tier in tiers
        if (tier.effective if source == "effective" else tier.default_chain)
    }


def _validate_pack(
    pack: ModelPack, settings: UiSettings
) -> ModelPackValidationResponse:
    issues: list[ModelPackIssue] = []
    if not pack.tier_chains:
        issues.append(
            ModelPackIssue(
                severity="error",
                code="empty_pack",
                message="Add at least one tier chain before using this pack.",
            )
        )

    available = set(_env_configured_providers())
    available.update(
        provider.type for provider in settings.providers if provider.enabled
    )
    known_capabilities = set(KNOWN_MODEL_CAPABILITIES)
    for tier, requirements in pack.capability_requirements.items():
        unknown = sorted(set(requirements) - known_capabilities)
        if unknown:
            issues.append(
                ModelPackIssue(
                    severity="error",
                    code="unknown_capability",
                    tier=tier,
                    message=f"Tier {tier} has unknown capabilities: {unknown}.",
                )
            )

    for tier, chain in pack.tier_chains.items():
        if not chain:
            issues.append(
                ModelPackIssue(
                    severity="error",
                    code="empty_tier",
                    tier=tier,
                    message=f"Tier {tier} has no routing candidates.",
                )
            )
        for model in chain:
            provider = model.split(":", 1)[0] if ":" in model else ""
            if not provider:
                issues.append(
                    ModelPackIssue(
                        severity="error",
                        code="unprefixed_model",
                        tier=tier,
                        model=model,
                        message="Model IDs in packs must include a provider prefix.",
                    )
                )
                continue
            if pack.allowed_providers and provider not in pack.allowed_providers:
                issues.append(
                    ModelPackIssue(
                        severity="error",
                        code="provider_not_allowed",
                        tier=tier,
                        model=model,
                        message=f"Provider {provider!r} is outside this pack's allowed set.",
                    )
                )
            if provider not in available:
                issues.append(
                    ModelPackIssue(
                        severity="warning",
                        code="provider_unavailable",
                        tier=tier,
                        model=model,
                        message=f"Provider {provider!r} is not currently available.",
                    )
                )

    return ModelPackValidationResponse(
        ref=_pack_ref(pack),
        valid=not any(issue.severity == "error" for issue in issues),
        issues=issues,
        candidate_chains=pack.tier_chains,
    )


@router.get("/settings/model-packs", response_model=ModelPackListResponse)
async def list_model_packs() -> ModelPackListResponse:
    """List every immutable model-pack version and current bindings."""
    return _pack_list_response(load_ui_settings())


@router.post(
    "/settings/model-packs",
    response_model=ModelPack,
    status_code=201,
    responses={409: {"description": "Pack ID already exists"}},
)
async def create_model_pack(request: ModelPackCreateRequest) -> ModelPack:
    """Create a pack from explicit chains, effective routing, or defaults."""
    settings = load_ui_settings()
    if latest_model_pack(request.id, settings) is not None:
        raise HTTPException(status_code=409, detail="Model pack ID already exists")
    chains = request.tier_chains or _derived_tier_chains(request.source, settings)
    allowed = request.allowed_providers or sorted(
        {
            model.split(":", 1)[0]
            for chain in chains.values()
            for model in chain
            if ":" in model
        }
    )
    try:
        pack = ModelPack(
            id=request.id,
            name=request.name,
            description=request.description,
            version=1,
            tier_chains=chains,
            allowed_providers=allowed,
            capability_requirements=request.capability_requirements,
            model_capabilities=request.model_capabilities,
            judge_model=request.judge_model,
            source=request.source,
        )
        updated = UiSettings.model_validate(
            {**settings.model_dump(), "model_packs": [*settings.model_packs, pack]}
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _save_or_503(updated)
    return pack


@router.put(
    "/settings/model-packs/{pack_id}",
    response_model=ModelPack,
    responses={404: {"description": "Pack not found"}},
)
async def version_model_pack(
    pack_id: str, request: ModelPackUpdateRequest
) -> ModelPack:
    """Append a new immutable version, inheriting omitted values."""
    settings = load_ui_settings()
    previous = latest_model_pack(pack_id, settings)
    if previous is None:
        raise HTTPException(status_code=404, detail="Model pack not found")
    now = datetime.now(UTC)
    values = request.model_dump(exclude_unset=True)
    try:
        pack = previous.model_copy(
            update={
                **values,
                "version": previous.version + 1,
                "updated_at": now,
                "archived": False,
                "source": "explicit",
            }
        )
        pack = ModelPack.model_validate(pack.model_dump())
        updated = UiSettings.model_validate(
            {**settings.model_dump(), "model_packs": [*settings.model_packs, pack]}
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _save_or_503(updated)
    return pack


@router.post(
    "/settings/model-packs/{pack_id}/duplicate",
    response_model=ModelPack,
    status_code=201,
)
async def duplicate_model_pack(
    pack_id: str, request: ModelPackDuplicateRequest
) -> ModelPack:
    settings = load_ui_settings()
    if request.source.id != pack_id:
        raise HTTPException(
            status_code=422, detail="Source pack ID does not match path"
        )
    source = _require_pack(request.source, settings)
    if latest_model_pack(request.new_id, settings) is not None:
        raise HTTPException(status_code=409, detail="Model pack ID already exists")
    now = datetime.now(UTC)
    duplicate = ModelPack.model_validate(
        {
            **source.model_dump(),
            "id": request.new_id,
            "name": request.name,
            "description": request.description or source.description,
            "version": 1,
            "created_at": now,
            "updated_at": now,
            "archived": False,
            "source": "duplicate",
        }
    )
    updated = UiSettings.model_validate(
        {**settings.model_dump(), "model_packs": [*settings.model_packs, duplicate]}
    )
    _save_or_503(updated)
    return duplicate


@router.post(
    "/settings/model-packs/{pack_id}/validate",
    response_model=ModelPackValidationResponse,
)
async def validate_model_pack(
    pack_id: str, version: int = Query(..., ge=1)
) -> ModelPackValidationResponse:
    settings = load_ui_settings()
    pack = _require_pack(ModelPackRef(id=pack_id, version=version), settings)
    return _validate_pack(pack, settings)


@router.post(
    "/settings/model-packs/{pack_id}/activate",
    response_model=ModelPackListResponse,
)
async def activate_model_pack(
    pack_id: str, version: int = Query(..., ge=1)
) -> ModelPackListResponse:
    settings = load_ui_settings()
    ref = ModelPackRef(id=pack_id, version=version)
    pack = _require_pack(ref, settings)
    validation = _validate_pack(pack, settings)
    if pack.archived or not validation.valid:
        raise HTTPException(
            status_code=409, detail="Only a valid, active pack can be activated"
        )
    updated = UiSettings.model_validate(
        {**settings.model_dump(), "active_model_pack": ref.model_dump()}
    )
    _save_or_503(updated)
    return _pack_list_response(updated)


@router.put(
    "/settings/model-packs/{pack_id}/bindings/{workflow_name}",
    response_model=ModelPackListResponse,
)
async def bind_model_pack(
    pack_id: str, workflow_name: str, version: int = Query(..., ge=1)
) -> ModelPackListResponse:
    settings = load_ui_settings()
    ref = ModelPackRef(id=pack_id, version=version)
    pack = _require_pack(ref, settings)
    if pack.archived:
        raise HTTPException(status_code=409, detail="Archived packs cannot be bound")
    from ...langchain.config import list_workflows

    if workflow_name not in list_workflows():
        raise HTTPException(status_code=404, detail="Workflow not found")
    bindings = {**settings.workflow_model_packs, workflow_name: ref}
    updated = UiSettings.model_validate(
        {**settings.model_dump(), "workflow_model_packs": bindings}
    )
    _save_or_503(updated)
    return _pack_list_response(updated)


@router.delete(
    "/settings/model-packs/bindings/{workflow_name}",
    response_model=ModelPackListResponse,
)
async def clear_model_pack_binding(workflow_name: str) -> ModelPackListResponse:
    settings = load_ui_settings()
    bindings = dict(settings.workflow_model_packs)
    bindings.pop(workflow_name, None)
    updated = UiSettings.model_validate(
        {**settings.model_dump(), "workflow_model_packs": bindings}
    )
    _save_or_503(updated)
    return _pack_list_response(updated)


def _recent_pack_run_ids(ref: ModelPackRef) -> list[str]:
    run_ids: list[str] = []
    for path in run_logger.list_runs()[-50:]:
        try:
            record = run_logger.load_run(path)
        except (OSError, ValueError):
            continue
        extra = record.get("extra") if isinstance(record.get("extra"), dict) else {}
        routing = extra.get("routing") if isinstance(extra.get("routing"), dict) else {}
        pack = routing.get("pack") if isinstance(routing.get("pack"), dict) else {}
        if pack.get("id") == ref.id and pack.get("version") == ref.version:
            run_ids.append(str(record.get("run_id") or path.stem))
    return run_ids[-10:]


def _pack_dependencies(
    ref: ModelPackRef, settings: UiSettings
) -> ModelPackDependenciesResponse:
    return ModelPackDependenciesResponse(
        ref=ref,
        globally_active=settings.active_model_pack == ref,
        workflows=sorted(
            name
            for name, binding in settings.workflow_model_packs.items()
            if binding == ref
        ),
        recent_run_ids=_recent_pack_run_ids(ref),
    )


@router.get(
    "/settings/model-packs/{pack_id}/dependencies",
    response_model=ModelPackDependenciesResponse,
)
async def model_pack_dependencies(
    pack_id: str, version: int = Query(..., ge=1)
) -> ModelPackDependenciesResponse:
    settings = load_ui_settings()
    ref = ModelPackRef(id=pack_id, version=version)
    _require_pack(ref, settings)
    return _pack_dependencies(ref, settings)


@router.post(
    "/settings/model-packs/{pack_id}/archive",
    response_model=ModelPack,
)
async def archive_model_pack(
    pack_id: str, version: int = Query(..., ge=1)
) -> ModelPack:
    settings = load_ui_settings()
    ref = ModelPackRef(id=pack_id, version=version)
    pack = _require_pack(ref, settings)
    dependencies = _pack_dependencies(ref, settings)
    if dependencies.globally_active or dependencies.workflows:
        raise HTTPException(
            status_code=409,
            detail="Remove global activation and workflow bindings before archiving.",
        )
    archived = pack.model_copy(
        update={"archived": True, "updated_at": datetime.now(UTC)}
    )
    packs = [
        archived if item.id == pack.id and item.version == pack.version else item
        for item in settings.model_packs
    ]
    updated = UiSettings.model_validate({**settings.model_dump(), "model_packs": packs})
    _save_or_503(updated)
    return archived


@router.get(
    "/settings/model-packs/{pack_id}/export",
    response_model=ModelPackExportResponse,
)
async def export_model_pack(
    pack_id: str, version: int = Query(..., ge=1)
) -> ModelPackExportResponse:
    settings = load_ui_settings()
    pack = _require_pack(ModelPackRef(id=pack_id, version=version), settings)
    return ModelPackExportResponse(pack=pack)


@router.post(
    "/settings/model-packs/import",
    response_model=ModelPack,
    status_code=201,
)
async def import_model_pack(request: ModelPackImportRequest) -> ModelPack:
    pack_request = request.pack.model_copy(update={"source": "imported"})
    return await create_model_pack(pack_request)


def _save_or_503(settings: UiSettings) -> None:
    """Persist settings, translating filesystem failures to HTTP 503."""
    try:
        save_ui_settings(settings)
    except OSError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"UI settings store is not writable: {exc}",
        ) from exc
