"""Runtime-mutable UI settings store.

Persists the settings the web UI manages at runtime — provider endpoint
configurations, model-tier reranking overrides, and model capability tags —
as a small JSON document. Environment variables and
``config/defaults/model_registry.yaml`` remain the deployment-time source of
truth; this store layers user edits on top without touching either.

Secrets never live here: provider entries reference the *name* of an
environment variable (``api_key_env``), not the credential itself.

The default location is ``<repo>/.agentic_ui_settings.json`` (anchored at the
repo root like ``run_logger`` and the SQLite replay store — never the process
CWD). Override with ``AGENTIC_UI_SETTINGS_PATH`` (used by tests).
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

_DEFAULT_SETTINGS_PATH = (
    Path(__file__).resolve().parents[2] / ".agentic_ui_settings.json"
)

_PROVIDER_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

# Option keys that suggest a raw credential is being smuggled into the store.
_FORBIDDEN_OPTION_KEYS = frozenset({"api_key", "apikey", "token", "secret", "password"})

ProviderType = Literal[
    "openai",
    "anthropic",
    "gh",
    "ollama",
    "foundry_local",
    "custom",
]

# Capability tags the UI offers for model capability editing.
KNOWN_MODEL_CAPABILITIES: tuple[str, ...] = (
    "fast",
    "balanced",
    "reasoning",
    "local",
    "vision",
    "audio",
    "tools",
    "long-context",
)


class ProviderConfig(BaseModel):
    """A single user-configured provider endpoint.

    Attributes:
        id: Stable slug identifying this entry (unique within the store).
        type: Provider family; drives which model-id prefix and builder apply.
        label: Display name shown in the UI.
        base_url: Endpoint URL override (Ollama host, custom OpenAI-compatible
            endpoint, Foundry Local port, ...). None uses the builder default.
        api_key_env: Name of the environment variable holding the credential.
            The credential itself is never persisted.
        default_model: Preferred model id for this provider, or None.
        enabled: Whether the provider participates in routing UI hints.
        options: Non-secret extra properties (org id, API version, default
            sampling params, ...).
    """

    id: str
    type: ProviderType
    label: str = ""
    base_url: str | None = None
    api_key_env: str | None = None
    default_model: str | None = None
    enabled: bool = True
    options: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        if not _PROVIDER_ID_PATTERN.fullmatch(value):
            raise ValueError(
                "Provider id must be a lowercase slug "
                "(letters, digits, '-', '_'; max 64 chars)."
            )
        return value

    @field_validator("options")
    @classmethod
    def _reject_secret_options(cls, value: dict[str, Any]) -> dict[str, Any]:
        forbidden = sorted(
            key for key in value if key.lower().replace("-", "_") in _FORBIDDEN_OPTION_KEYS
        )
        if forbidden:
            raise ValueError(
                f"Provider options must not contain credentials: {forbidden}. "
                "Reference an environment variable via api_key_env instead."
            )
        return value


class UiSettings(BaseModel):
    """The full persisted UI settings document."""

    version: int = 1
    providers: list[ProviderConfig] = Field(default_factory=list)
    tier_overrides: dict[int, list[str]] = Field(default_factory=dict)
    model_capabilities: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("providers")
    @classmethod
    def _unique_provider_ids(cls, value: list[ProviderConfig]) -> list[ProviderConfig]:
        seen: set[str] = set()
        for provider in value:
            if provider.id in seen:
                raise ValueError(f"Duplicate provider id: {provider.id!r}")
            seen.add(provider.id)
        return value

    @field_validator("tier_overrides")
    @classmethod
    def _validate_tiers(cls, value: dict[int, list[str]]) -> dict[int, list[str]]:
        for tier, models in value.items():
            if not 0 <= tier <= 5:
                raise ValueError(f"Tier must be between 0 and 5, got {tier}.")
            if any(not isinstance(m, str) or not m.strip() for m in models):
                raise ValueError(f"Tier {tier} override contains an empty model id.")
        return value


def get_ui_settings_path() -> Path:
    """Resolve the settings file path (env override wins)."""
    override = (os.environ.get("AGENTIC_UI_SETTINGS_PATH") or "").strip()
    if override:
        return Path(override)
    return _DEFAULT_SETTINGS_PATH


def load_ui_settings(path: Path | None = None) -> UiSettings:
    """Load the settings document, returning defaults when absent or invalid.

    A corrupt file is logged and treated as empty rather than failing the
    request path — the UI can always re-save a clean document.
    """
    settings_path = path or get_ui_settings_path()
    if not settings_path.exists():
        return UiSettings()
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        return UiSettings.model_validate(data)
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring invalid UI settings at %s: %s", settings_path, exc)
        return UiSettings()


def save_ui_settings(settings: UiSettings, path: Path | None = None) -> Path:
    """Atomically persist the settings document and return its path."""
    settings_path = path or get_ui_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(settings.model_dump(mode="json"), indent=2, sort_keys=False)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(settings_path.parent), prefix=settings_path.name, suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_name, settings_path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise
    return settings_path


def tier_override_models(tier: int) -> list[str]:
    """Return the UI-configured model ranking for a tier (empty when unset).

    Used by the LangChain model dispatch layer between the env-var override
    and the probed tier default.
    """
    return list(load_ui_settings().tier_overrides.get(tier, []))
