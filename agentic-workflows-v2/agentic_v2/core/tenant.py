"""Tenant context and filesystem scoping helpers."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from fastapi import Request

from ..settings import get_settings

DEFAULT_TENANT_ID = "default"
TENANT_HEADER = "X-Tenant-ID"
_DEFAULT_DATASETS_DIR = Path(__file__).resolve().parents[3] / "datasets"
_DEFAULT_RUNS_DIR = Path(__file__).resolve().parents[3] / "runs"
_TENANT_CLAIM_KEYS = (
    "tenant_id",
    "tenant",
    "tid",
    "org_id",
    "organization_id",
    "organization",
)

TenantSource = Literal["oidc", "header", "default"]


@dataclass(frozen=True)
class TenantContext:
    """Resolved tenant scope for one request."""

    tenant_id: str
    source: TenantSource
    actor_subject: str | None = None


def sanitize_tenant_id(value: str | None) -> str:
    """Return a tenant identifier safe for path segments."""
    raw = (value or "").strip()
    if not raw:
        return DEFAULT_TENANT_ID
    cleaned = "".join(
        char if char.isalnum() or char in {"-", "_"} else "_" for char in raw
    ).strip("._-")
    return cleaned[:120] or DEFAULT_TENANT_ID


def get_tenant_context(request: Request) -> TenantContext:
    """Resolve the tenant for a FastAPI request.

    OIDC-authenticated requests use safe tenant/org claims copied onto
    ``request.state.user`` by auth middleware. In non-OIDC deployments,
    ``X-Tenant-ID`` is accepted as a compatibility scoping header. Requests
    without either signal use the default tenant for legacy behavior.
    """
    user = getattr(request.state, "user", None)
    tenant_from_user = _tenant_from_user(user)
    if tenant_from_user:
        return TenantContext(
            tenant_id=sanitize_tenant_id(tenant_from_user),
            source="oidc",
            actor_subject=_subject_from_user(user),
        )

    if not _oidc_enabled(request):
        header_value = request.headers.get(TENANT_HEADER)
        if header_value:
            return TenantContext(
                tenant_id=sanitize_tenant_id(header_value),
                source="header",
                actor_subject=_subject_from_user(user),
            )

    return TenantContext(
        tenant_id=DEFAULT_TENANT_ID,
        source="default",
        actor_subject=_subject_from_user(user),
    )


def tenant_dataset_dir(
    tenant_id: str,
    *,
    base_dir: Path | str | None = None,
    create: bool = True,
) -> Path:
    """Return ``datasets/{tenant_id}``, creating it by default."""
    root = Path(base_dir) if base_dir is not None else _DEFAULT_DATASETS_DIR
    path = root / sanitize_tenant_id(tenant_id)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def tenant_run_dir(
    tenant_id: str,
    *,
    base_dir: Path | str | None = None,
    create: bool = True,
) -> Path:
    """Return ``runs/{tenant_id}``, creating it by default."""
    root = Path(base_dir) if base_dir is not None else _DEFAULT_RUNS_DIR
    path = root / sanitize_tenant_id(tenant_id)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def migrate_legacy_tenant_storage(
    *,
    runs_dir: Path | str | None = None,
    datasets_dir: Path | str | None = None,
    tenant_id: str = DEFAULT_TENANT_ID,
    dry_run: bool = False,
) -> dict[str, list[str]]:
    """Move legacy root files into ``runs/{tenant}`` and ``datasets/{tenant}``.

    The helper is intentionally opt-in. It only moves files, not
    existing tenant subdirectories, so already-scoped data is left
    untouched.
    """
    tenant_id = sanitize_tenant_id(tenant_id)
    runs_root = Path(runs_dir) if runs_dir is not None else _DEFAULT_RUNS_DIR
    datasets_root = (
        Path(datasets_dir) if datasets_dir is not None else _DEFAULT_DATASETS_DIR
    )
    moved = {
        "runs": _migrate_legacy_runs(runs_root, tenant_id, dry_run),
        "datasets": _migrate_legacy_datasets(datasets_root, tenant_id, dry_run),
    }
    return moved


def _migrate_legacy_runs(runs_root: Path, tenant_id: str, dry_run: bool) -> list[str]:
    """Move legacy root run files into ``runs/{tenant}``."""
    moved: list[str] = []
    if not runs_root.exists():
        return moved
    target = tenant_run_dir(tenant_id, base_dir=runs_root, create=not dry_run)
    for path in sorted(runs_root.glob("*.json")):
        destination = target / path.name
        moved.append(f"{path} -> {destination}")
        if not dry_run:
            shutil.move(str(path), str(destination))
    return moved


def _migrate_legacy_datasets(
    datasets_root: Path, tenant_id: str, dry_run: bool
) -> list[str]:
    """Move legacy root dataset files into ``datasets/{tenant}``."""
    moved: list[str] = []
    if not datasets_root.exists():
        return moved
    target = tenant_dataset_dir(tenant_id, base_dir=datasets_root, create=not dry_run)
    tenant_target = target.resolve()
    for path in sorted(p for p in datasets_root.rglob("*") if p.is_file()):
        if path.resolve().is_relative_to(tenant_target):
            continue
        rel = path.relative_to(datasets_root)
        destination = target / rel
        moved.append(f"{path} -> {destination}")
        if not dry_run:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(destination))
    return moved


def _oidc_enabled(request: Request) -> bool:
    app_state = getattr(getattr(request, "app", None), "state", None)
    configured = getattr(app_state, "agentic_oidc_enabled", None)
    if configured is not None:
        return bool(configured)
    return bool(get_settings().agentic_oidc_enabled)


def _tenant_from_user(user: Any) -> str | None:
    if user is None:
        return None
    for key in _TENANT_CLAIM_KEYS:
        value = _get_user_value(user, key)
        if value:
            return str(value)
    claims = _get_user_value(user, "claims")
    if isinstance(claims, dict):
        for key in _TENANT_CLAIM_KEYS:
            value = claims.get(key)
            if value:
                return str(value)
    return None


def _subject_from_user(user: Any) -> str | None:
    for key in ("subject", "sub", "user_id"):
        value = _get_user_value(user, key)
        if value:
            return str(value)
    claims = _get_user_value(user, "claims")
    if isinstance(claims, dict) and claims.get("sub"):
        return str(claims["sub"])
    return None


def _get_user_value(user: Any, key: str) -> Any:
    if user is None:
        return None
    if isinstance(user, dict):
        return user.get(key)
    return getattr(user, key, None)
