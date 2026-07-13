"""Curated single source-of-truth model registry (ADR-040).

This module owns the *curated* half of model selection. It is the single source
of truth for:

- which model ids serve which tier (the fallback chains),
- which model each named agent (architect, coder, …) defaults to,
- a handful of special-purpose ids (judge default, NotebookLM fallback, the
  ultimate tier fallback, the GitHub backup models), and
- a per-Mtok price table.

``models/router.py`` and ``langchain/models.py`` read their chains from here, and
the named-agent loader reads per-agent defaults from here, so a model id is
declared in exactly one place.

Design principle (see ADR-040): **dynamic for FACTS the runtime can verify**
(availability, health, rate-limit state — owned by the discovery probes,
``rate_limit_tracker``, and ``model_stats``); **curated for JUDGMENTS a human
owns** (tier membership, capability, price). The probe layer may *warn* and
*quarantine* a retired id, but it never auto-promotes a newly discovered id into
a chain.

Cost-per-token **cannot** be probed: provider ``/models`` endpoints return ids
only (see :mod:`agentic_v2.models.cloud_discovery`). Prices are a maintained
table in ``config/defaults/model_registry.yaml``; :func:`compute_spend` turns
observed token usage into a dollar figure, or ``None`` when a price is unknown.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

logger = logging.getLogger(__name__)

ModelStatus = Literal["active", "deprecated", "quarantined"]

_TOKENS_PER_MTOK = 1_000_000

# Default ultimate fallback if the registry is missing/empty (mirrors the
# registry's special.tier_ultimate_fallback; must be a model actually kept
# pulled on the local daemon).
_DEFAULT_ULTIMATE_FALLBACK = "ollama:qwen3-coder:30b"


# ---------------------------------------------------------------------------
# Schema (frozen Pydantic models)
# ---------------------------------------------------------------------------


class RegisteredModel(BaseModel):
    """A single curated model entry.

    ``price_in`` / ``price_out`` are USD per 1,000,000 tokens; ``None`` means the
    price is unknown (spend is reported as ``None``, never guessed).
    """

    model_config = ConfigDict(frozen=True)

    id: str
    provider: str
    tiers: tuple[int, ...] = ()
    capability: str = "balanced"
    status: ModelStatus = "active"
    price_in: float | None = None
    price_out: float | None = None
    context_window: int | None = None


class SpecialModels(BaseModel):
    """Special-purpose model ids referenced by individual call sites."""

    model_config = ConfigDict(frozen=True)

    judge_default: str
    notebooklm_fallback: str
    tier_ultimate_fallback: str


class Registry(BaseModel):
    """The parsed, validated registry."""

    model_config = ConfigDict(frozen=True)

    version: int = 1
    models: tuple[RegisteredModel, ...]
    tiers: dict[int, tuple[str, ...]]
    special: SpecialModels

    def by_id(self) -> dict[str, RegisteredModel]:
        """Return an id -> model mapping (built fresh; registry is immutable)."""
        return {m.id: m for m in self.models}


# ---------------------------------------------------------------------------
# Loading + validation
# ---------------------------------------------------------------------------


def _resolve_project_root() -> Path:
    """Locate the project root by searching parents for ``pyproject.toml``.

    Mirrors :func:`agentic_v2.scoring.eval_config._resolve_project_root` so the
    registry resolves identically under both the flat and ``src/`` layouts.
    """
    this_file = Path(__file__).resolve()
    parents = this_file.parents
    candidates = [parents[index] for index in (2, 3) if len(parents) > index]
    for root in candidates:
        if (root / "agentic_v2").exists() and (root / "pyproject.toml").exists():
            return root
        if (root / "src" / "agentic_v2").exists() and (
            root / "pyproject.toml"
        ).exists():
            return root
    return candidates[0] if candidates else this_file.parent


def _resolve_registry_path(project_root: Path) -> Path:
    """Resolve the path to ``model_registry.yaml`` under the project root."""
    candidates = [
        project_root / "agentic_v2" / "config" / "defaults" / "model_registry.yaml",
        project_root
        / "src"
        / "agentic_v2"
        / "config"
        / "defaults"
        / "model_registry.yaml",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _authoritative_providers() -> frozenset[str]:
    """Return the authoritative set of routable provider names.

    ``PROVIDER_ENV_KEYS`` (the credential-gate map) is authoritative -- it lists
    every routable provider, keyed (gemini/anthropic/openai/gh/nvidia) or
    keyless-local (ollama/local/onnx/lmstudio/local_api). It is deliberately NOT
    ``langchain.models._KNOWN_PREFIXES``, which is a display superset that
    includes prefixes with no backend or key (``azure:``, ``windows-ai:``).
    Imported lazily so importing this module never pulls in the langchain layer.
    """
    from ..langchain.model_utils import PROVIDER_ENV_KEYS

    return frozenset(PROVIDER_ENV_KEYS)


def _validate(registry: Registry) -> None:
    """Raise ``ValueError`` on missing tiers, dangling references, or unknown providers.

    Catches the failure modes the registry exists to prevent: a missing tier
    chain (which would surface later as a cryptic ``KeyError`` in
    ``ModelRouter.get_chain``'s ``DEFAULT_CHAINS[TIER_2]`` fallback), or a tier
    chain / special slot pointing at an id that has no ``models:`` entry.
    """
    required_tiers = {1, 2, 3, 4, 5}
    missing_tiers = sorted(t for t in required_tiers if not registry.tiers.get(t))
    if missing_tiers:
        raise ValueError(
            "model_registry.yaml is missing a non-empty fallback chain for "
            f"required tier(s): {missing_tiers}"
        )

    ids = {m.id for m in registry.models}
    providers = _authoritative_providers()

    bad_providers = sorted(
        f"{m.id} (provider={m.provider!r})"
        for m in registry.models
        if m.provider not in providers
    )
    if bad_providers:
        raise ValueError(
            "model_registry.yaml references unknown providers (not in "
            f"PROVIDER_ENV_KEYS): {bad_providers}"
        )

    dangling: list[str] = []
    for tier, chain in registry.tiers.items():
        dangling += [f"tiers[{tier}] -> {mid}" for mid in chain if mid not in ids]
    for slot in ("judge_default", "notebooklm_fallback", "tier_ultimate_fallback"):
        mid = getattr(registry.special, slot)
        if mid not in ids:
            dangling.append(f"special.{slot} -> {mid}")

    if dangling:
        raise ValueError(
            "model_registry.yaml has dangling model references "
            f"(no matching models: entry): {sorted(dangling)}"
        )


@lru_cache(maxsize=1)
def load_registry() -> Registry:
    """Load, validate, and cache the model registry.

    Raises:
        FileNotFoundError: if the registry file is missing.
        ValueError: if the YAML is malformed or has dangling/unknown references.
    """
    path = _resolve_registry_path(_resolve_project_root())
    if not path.exists():
        raise FileNotFoundError(f"model registry not found at {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ValueError(f"malformed YAML in model registry {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"model_registry.yaml must be a mapping, got {type(raw)}")
    try:
        registry = Registry.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"invalid model registry schema: {exc}") from exc
    _validate(registry)
    return registry


def clear_cache() -> None:
    """Clear the cached registry and runtime quarantine (test isolation)."""
    load_registry.cache_clear()
    _warned_unknown_price.clear()
    _quarantined.clear()


# ---------------------------------------------------------------------------
# Accessors (module-level; each reads the cached registry)
# ---------------------------------------------------------------------------


def tier_chain(tier: int) -> tuple[str, ...]:
    """Return the ordered fallback chain for ``tier`` (empty if unknown)."""
    return load_registry().tiers.get(tier, ())


def special(name: str) -> str | tuple[str, ...]:
    """Return a special-slot value (e.g. ``"judge_default"``).

    Raises:
        AttributeError: if ``name`` is not a known special slot.
    """
    return getattr(load_registry().special, name)


def all_ids() -> frozenset[str]:
    """Return the set of every model id declared in ``models:``."""
    return frozenset(m.id for m in load_registry().models)


def provider_for(model_id: str) -> str:
    """Return the curated provider for ``model_id``, falling back to its prefix."""
    entry = load_registry().by_id().get(model_id)
    if entry is not None:
        return entry.provider
    from ..langchain.model_utils import provider_prefix

    return provider_prefix(model_id)


def price_for(model_id: str) -> tuple[float | None, float | None]:
    """Return ``(price_in, price_out)`` per Mtok for ``model_id``.

    Returns ``(None, None)`` when the model is unknown or its price is uncurated.
    """
    entry = load_registry().by_id().get(model_id)
    if entry is None:
        return (None, None)
    return (entry.price_in, entry.price_out)


# Ids we have already warned about (warn once per unknown price, per process).
_warned_unknown_price: set[str] = set()


def compute_spend(
    model_id: str, prompt_tokens: int, completion_tokens: int
) -> float | None:
    """Compute USD spend for a call, or ``None`` if the price is unknown.

    Spend = ``tokens / 1e6 * price`` summed over input/output. A ``None`` price
    on either side yields ``None`` (never a guessed zero) and logs one WARNING
    per model id for the life of the process.
    """
    price_in, price_out = price_for(model_id)
    if price_in is None or price_out is None:
        if model_id not in _warned_unknown_price:
            _warned_unknown_price.add(model_id)
            logger.warning(
                "model %s has no curated price; spend not computed", model_id
            )
        return None
    return (
        prompt_tokens / _TOKENS_PER_MTOK * price_in
        + completion_tokens / _TOKENS_PER_MTOK * price_out
    )


# ---------------------------------------------------------------------------
# Runtime quarantine — populated by probe-time drift detection (ADR-040)
# ---------------------------------------------------------------------------
# Ids the probe found retired at their provider (the live listing no longer
# includes them). Quarantined ids are filtered out of routing by both engines.
# This is RUNTIME state, distinct from the curated registry, and is reset on
# clear_cache() and at the start of each drift run.

_quarantined: set[str] = set()


def quarantine(ids: Iterable[str]) -> None:
    """Add model ids to the quarantine set (drop them from routing)."""
    _quarantined.update(ids)


def set_quarantine(ids: Iterable[str]) -> None:
    """Replace the quarantine set atomically with ``ids``.

    Rebinds the module global to a freshly-built set in a single
    assignment (atomic under the GIL), so readers never observe a half-
    built set. Drift detection uses this to swap in the new quarantine
    *after* network discovery completes, rather than clearing first and
    leaving a gap concurrent requests could route through.
    """
    global _quarantined
    _quarantined = set(ids)


def is_quarantined(model_id: str) -> bool:
    """Return True if ``model_id`` is currently quarantined."""
    return model_id in _quarantined


def quarantined_ids() -> frozenset[str]:
    """Return the set of currently-quarantined model ids."""
    return frozenset(_quarantined)


def clear_quarantine() -> None:
    """Clear all quarantine state."""
    global _quarantined
    _quarantined = set()


class RegistryDriftError(RuntimeError):
    """Raised by drift detection in strict mode when a pinned id is retired."""
