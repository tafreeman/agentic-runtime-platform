"""Secret provider abstractions with environment fallback.

This module gives runtime code a provider-agnostic way to resolve secrets
without hard-coding environment lookups everywhere. The default provider
chain keeps local development behavior intact by reading ``.env`` and the
process environment, while allowing tests or future vault-backed providers
to plug in explicitly.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

logger = logging.getLogger(__name__)


class SecretProvider(Protocol):
    """Minimal interface for secret lookups."""

    def get(self, name: str, default: str | None = None) -> str | None:
        """Return a secret value or *default* when it is unavailable."""


def _normalize_secret(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


@dataclass
class MappingSecretProvider:
    """Resolve secrets from a mapping.

    Useful in tests or as a building block for external secret stores.
    """

    secrets: Mapping[str, str]

    def get(self, name: str, default: str | None = None) -> str | None:
        return _normalize_secret(self.secrets.get(name)) or default


@dataclass
class EnvSecretProvider:
    """Resolve secrets from the environment, optionally hydrating ``.env``."""

    env: Mapping[str, str] | None = None
    load_dotenv: bool = True
    search_roots: Sequence[Path] | None = None
    _dotenv_loaded: bool = field(default=False, init=False, repr=False)
    _override_on_next_load: bool = field(default=False, init=False, repr=False)

    def get(self, name: str, default: str | None = None) -> str | None:
        self._load_dotenv_once()
        source = self.env if self.env is not None else os.environ  # env-pass: secrets abstraction reads env by design
        return _normalize_secret(source.get(name)) or default

    def refresh(self) -> None:
        """Allow callers to reload ``.env`` after secret rotation."""
        self._dotenv_loaded = False
        self._override_on_next_load = True

    def _load_dotenv_once(self) -> None:
        if not self.load_dotenv or self._dotenv_loaded:
            return

        self._dotenv_loaded = True
        try:
            from dotenv import load_dotenv
        except ImportError:
            return

        roots = self.search_roots or Path(__file__).resolve().parents
        for root in roots:
            env_path = root / ".env"
            if env_path.is_file():
                load_dotenv(env_path, override=self._override_on_next_load)
                logger.debug("Loaded env from %s", env_path)
                self._override_on_next_load = False
                break


@dataclass
class ChainedSecretProvider:
    """Resolve secrets from the first provider that returns a value."""

    providers: Sequence[SecretProvider]

    def get(self, name: str, default: str | None = None) -> str | None:
        for provider in self.providers:
            value = provider.get(name)
            if value is not None:
                return value
        return default


_default_provider: SecretProvider = ChainedSecretProvider([EnvSecretProvider()])


def get_default_secret_provider() -> SecretProvider:
    """Return the process-wide default secret provider."""
    return _default_provider


def set_default_secret_provider(provider: SecretProvider) -> None:
    """Override the process-wide default secret provider."""
    global _default_provider
    _default_provider = provider


def reset_default_secret_provider() -> None:
    """Restore the default environment-backed secret provider chain."""
    global _default_provider
    _default_provider = ChainedSecretProvider([EnvSecretProvider()])


def get_secret(
    name: str,
    *,
    default: str | None = None,
    provider: SecretProvider | None = None,
) -> str | None:
    """Resolve *name* via the configured provider chain."""
    active_provider = provider or get_default_secret_provider()
    return active_provider.get(name, default)


def get_first_secret(
    *names: str,
    default: str | None = None,
    provider: SecretProvider | None = None,
) -> str | None:
    """Return the first configured secret from *names*."""
    active_provider = provider or get_default_secret_provider()
    for name in names:
        value = active_provider.get(name)
        if value is not None:
            return value
    return default


__all__ = [
    "ChainedSecretProvider",
    "EnvSecretProvider",
    "MappingSecretProvider",
    "SecretProvider",
    "get_default_secret_provider",
    "get_first_secret",
    "get_secret",
    "reset_default_secret_provider",
    "set_default_secret_provider",
]
