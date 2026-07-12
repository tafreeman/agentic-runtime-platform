"""Integrity checks for locally loaded model weight files."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = "trusted-model-hashes.v1"
_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
_READ_CHUNK_SIZE = 1024 * 1024
_DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "defaults"
    / "trusted_model_hashes.yaml"
)


class TrustedHashConfigError(ValueError):
    """Raised when trusted model hash configuration is malformed."""


class ModelWeightVerificationError(RuntimeError):
    """Raised when strict model weight verification fails."""


@dataclass(frozen=True)
class TrustedModelHash:
    """One trusted model hash entry loaded from YAML."""

    id: str
    path: Path
    sha256: str
    algorithm: str = "sha256"
    source: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class VerificationResult:
    """Result of a local model weight integrity check."""

    model_path: Path
    actual_hash: str
    expected_hash: str | None
    verified: bool
    status: str
    strict: bool
    warnings: list[str] = field(default_factory=list)
    config_path: Path | None = None
    matched_entry_id: str | None = None


def verify_model_weights(
    model_path: Path,
    expected_hash: str | None = None,
) -> VerificationResult:
    """Verify a model file or directory against an expected SHA-256 hash.

    If ``expected_hash`` is omitted, trusted hashes are loaded from
    ``AGENTIC_TRUSTED_MODEL_HASHES`` or the packaged default config. Unknown
    hashes warn in non-strict mode and fail in strict mode.
    """
    path = Path(model_path).expanduser()
    strict = _strict_model_verify_enabled()
    warnings: list[str] = []
    config_path: Path | None = None
    matched_entry_id: str | None = None

    actual_hash = compute_model_sha256(path)
    configured_hash = expected_hash.strip().lower() if expected_hash else None

    if configured_hash is not None and not _SHA256_RE.fullmatch(configured_hash):
        raise TrustedHashConfigError(
            "expected_hash must be a 64-character SHA-256 hex digest"
        )

    if configured_hash is None:
        config_path = _trusted_hash_config_path()
        try:
            trusted_hashes = load_trusted_hashes(config_path)
        except FileNotFoundError:
            trusted_hashes = []
        except TrustedHashConfigError as exc:
            if strict:
                raise ModelWeightVerificationError(str(exc)) from exc
            warning = f"Trusted model hash config invalid: {exc}"
            warnings.append(warning)
            logger.warning(warning)
            trusted_hashes = []

        matched = _find_trusted_hash(path, trusted_hashes)
        if matched is not None:
            configured_hash = matched.sha256
            matched_entry_id = matched.id

    if configured_hash is None:
        warning = f"No trusted SHA-256 hash configured for local model path: {path}"
        warnings.append(warning)
        logger.warning(warning)
        result = VerificationResult(
            model_path=path,
            actual_hash=actual_hash,
            expected_hash=None,
            verified=False,
            status="unknown",
            strict=strict,
            warnings=warnings,
            config_path=config_path,
            matched_entry_id=matched_entry_id,
        )
        _raise_if_strict_failure(result, "unknown model hash")
        _emit_audit_event(result)
        return result

    if hmac.compare_digest(actual_hash, configured_hash):
        result = VerificationResult(
            model_path=path,
            actual_hash=actual_hash,
            expected_hash=configured_hash,
            verified=True,
            status="verified",
            strict=strict,
            warnings=warnings,
            config_path=config_path,
            matched_entry_id=matched_entry_id,
        )
        logger.info("Verified local model weights: %s", path)
        _emit_audit_event(result)
        return result

    warning = (
        "Local model weight SHA-256 mismatch for "
        f"{path}: expected {configured_hash}, got {actual_hash}"
    )
    warnings.append(warning)
    logger.warning(warning)
    result = VerificationResult(
        model_path=path,
        actual_hash=actual_hash,
        expected_hash=configured_hash,
        verified=False,
        status="mismatch",
        strict=strict,
        warnings=warnings,
        config_path=config_path,
        matched_entry_id=matched_entry_id,
    )
    _raise_if_strict_failure(result, "model hash mismatch")
    _emit_audit_event(result)
    return result


def compute_model_sha256(model_path: Path) -> str:
    """Compute a deterministic SHA-256 digest for a model file or directory."""
    path = Path(model_path).expanduser()
    if path.is_file():
        return _file_sha256(path)
    if path.is_dir():
        files = sorted(
            (candidate for candidate in path.rglob("*") if candidate.is_file()),
            key=lambda candidate: candidate.relative_to(path).as_posix().lower(),
        )
        if not files:
            raise FileNotFoundError(f"No files found under model directory: {path}")
        digest = hashlib.sha256()
        for file_path in files:
            relative = file_path.relative_to(path).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(_file_sha256(file_path).encode("ascii"))
            digest.update(b"\n")
        return digest.hexdigest()
    raise FileNotFoundError(f"Model path does not exist: {path}")


def load_trusted_hashes(config_path: Path | None = None) -> list[TrustedModelHash]:
    """Load and validate trusted model hash YAML configuration."""
    path = Path(config_path) if config_path is not None else _trusted_hash_config_path()
    if not path.exists():
        raise FileNotFoundError(path)

    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise TrustedHashConfigError("trusted hash config must be a mapping")
    if raw.get("schema_version") != _SCHEMA_VERSION:
        raise TrustedHashConfigError(f"schema_version must be {_SCHEMA_VERSION!r}")

    models = raw.get("models")
    if models is None:
        return []
    if not isinstance(models, list):
        raise TrustedHashConfigError("models must be a list")

    entries: list[TrustedModelHash] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(models):
        entries.append(_parse_trusted_hash_entry(item, index, seen_ids))
    return entries


def _parse_trusted_hash_entry(
    item: Any,
    index: int,
    seen_ids: set[str],
) -> TrustedModelHash:
    """Validate one ``models[index]`` mapping and build its entry.

    Mutates ``seen_ids`` to enforce uniqueness across the configuration.
    """
    if not isinstance(item, dict):
        raise TrustedHashConfigError(f"models[{index}] must be a mapping")
    unknown_keys = set(item) - {"id", "path", "sha256", "algorithm", "source", "notes"}
    if unknown_keys:
        raise TrustedHashConfigError(
            f"models[{index}] has unknown keys: {', '.join(sorted(unknown_keys))}"
        )

    entry_id = _require_string(item, "id", index)
    if entry_id in seen_ids:
        raise TrustedHashConfigError(f"duplicate trusted model id: {entry_id}")
    seen_ids.add(entry_id)

    entry_path_raw = _require_string(item, "path", index)
    sha256 = _require_string(item, "sha256", index).lower()
    algorithm = str(item.get("algorithm", "sha256")).lower()
    if algorithm != "sha256":
        raise TrustedHashConfigError(f"models[{index}].algorithm must be 'sha256'")
    if not _SHA256_RE.fullmatch(sha256):
        raise TrustedHashConfigError(
            f"models[{index}].sha256 must be a 64-character SHA-256 hex digest"
        )

    return TrustedModelHash(
        id=entry_id,
        path=_expand_config_path(entry_path_raw),
        sha256=sha256,
        algorithm=algorithm,
        source=_optional_string(item, "source", index),
        notes=_optional_string(item, "notes", index),
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_READ_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _trusted_hash_config_path() -> Path:
    override = os.getenv("AGENTIC_TRUSTED_MODEL_HASHES")
    if override:
        return Path(override).expanduser()
    return _DEFAULT_CONFIG_PATH


def _strict_model_verify_enabled() -> bool:
    value = os.getenv("AGENTIC_STRICT_MODEL_VERIFY", "").strip().lower()
    return value in {"1", "true", "yes", "y", "on"}


def _find_trusted_hash(
    model_path: Path,
    trusted_hashes: list[TrustedModelHash],
) -> TrustedModelHash | None:
    resolved_model_path = _resolve_existing_path(model_path)
    for entry in trusted_hashes:
        if _resolve_existing_path(entry.path) == resolved_model_path:
            return entry
    return None


def _resolve_existing_path(path: Path) -> Path:
    try:
        return path.expanduser().resolve()
    except OSError:
        return path.expanduser().absolute()


def _expand_config_path(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser()


def _require_string(item: dict[str, Any], field_name: str, index: int) -> str:
    value = item.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise TrustedHashConfigError(
            f"models[{index}].{field_name} must be a non-empty string"
        )
    return value.strip()


def _optional_string(
    item: dict[str, Any],
    field_name: str,
    index: int,
) -> str | None:
    value = item.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TrustedHashConfigError(f"models[{index}].{field_name} must be a string")
    return value


def _raise_if_strict_failure(result: VerificationResult, reason: str) -> None:
    if not result.strict:
        return
    raise ModelWeightVerificationError(
        f"Strict local model verification failed ({reason}) for {result.model_path}"
    )


def _emit_audit_event(result: VerificationResult) -> None:
    """Best-effort audit emission when the server audit module is available."""
    audit_module = sys.modules.get("agentic_v2.server.audit_log")
    if audit_module is None:
        return
    build_audit_logger = getattr(audit_module, "build_audit_logger", None)
    if build_audit_logger is None:
        return

    async def _audit() -> None:
        audit_logger = await build_audit_logger()
        try:
            await audit_logger.audit(
                "model.weight_verification",
                outcome="success" if result.verified else "failure",
                target={
                    "path": str(result.model_path),
                    "entry_id": result.matched_entry_id,
                },
                metadata={
                    "actual_sha256": result.actual_hash,
                    "expected_sha256": result.expected_hash,
                    "status": result.status,
                    "strict": result.strict,
                    "config_path": (
                        str(result.config_path) if result.config_path else None
                    ),
                    "warnings": result.warnings,
                },
            )
        finally:
            await audit_logger.close()

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            asyncio.run(_audit())
        except Exception as exc:
            logger.debug("Model weight audit emission failed: %s", exc)
        return

    try:
        task = loop.create_task(_audit())
        task.add_done_callback(_log_audit_task_failure)
    except Exception as exc:
        logger.debug("Model weight audit task scheduling failed: %s", exc)


def _log_audit_task_failure(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except Exception as exc:
        logger.debug("Model weight audit emission failed: %s", exc)


__all__ = [
    "ModelWeightVerificationError",
    "TrustedHashConfigError",
    "TrustedModelHash",
    "VerificationResult",
    "compute_model_sha256",
    "load_trusted_hashes",
    "verify_model_weights",
]
