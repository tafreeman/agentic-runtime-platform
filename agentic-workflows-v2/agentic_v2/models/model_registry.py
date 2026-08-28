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
import os
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

logger = logging.getLogger(__name__)

ModelStatus = Literal["active", "deprecated", "quarantined"]
CostLane = Literal["local", "free", "paid"]

_TOKENS_PER_MTOK = 1_000_000

# Fail-closed default: an uncurated model is routed as if it were the most
# expensive lane, never silently treated as free (ARP-IMPROVEMENTS F1).
_DEFAULT_COST_LANE: CostLane = "paid"

# Ordinal cost ranking, cheapest first. Used both to enforce a ceiling (drop
# any candidate ranked above it) and to detect a failover "lane crossing"
# (attempted model's rank increases) worth a warning.
_LANE_RANK: dict[CostLane, int] = {"local": 0, "free": 1, "paid": 2}

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
    cost_lane: CostLane | None = None
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


_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _ollama_base_is_loopback() -> bool:
    """Whether the configured ``OLLAMA_BASE_URL`` (or its default) is loopback.

    A non-loopback ``OLLAMA_BASE_URL`` means every call to it already leaves
    this machine over the network to whatever remote daemon the operator
    configured -- that fails the ``"local"`` cost lane's own definition
    (weights *on this machine*, no network) regardless of whether
    ``OLLAMA_API_KEY`` / the ADR-051 cloud-reroute path is involved at all.
    """
    from urllib.parse import urlparse

    from .ollama_discovery import DEFAULT_LOCAL_HOST, ENV_BASE_URL

    base = os.environ.get(ENV_BASE_URL, DEFAULT_LOCAL_HOST)
    host = (urlparse(base).hostname or "").lower().strip("[]")
    return host in _LOOPBACK_HOSTS


def cost_lane_for(model_id: str) -> CostLane:
    """Return the cost lane for ``model_id``, failing closed to ``"paid"``.

    A model absent from the registry, or present but with no curated
    ``cost_lane``, is treated as ``"paid"`` -- never silently assumed free.
    This is the single source of truth every candidate resolver
    (``langchain.models.get_model_candidates_for_tier``,
    ``models.router.ModelRouter``, ``models.smart_router.SmartModelRouter``)
    filters against for ``AGENTIC_MAX_COST_LANE``.

    Curated ``"local"`` on an ``ollama:`` id is downgraded to ``"free"`` when
    either is true:

    - ``OLLAMA_BASE_URL`` is configured to a non-loopback host -- every call
      already leaves this machine, key or not (see
      :func:`_ollama_base_is_loopback`).
    - ``OLLAMA_API_KEY`` is set and the model is not pulled on the local
      daemon: :func:`agentic_v2.langchain.model_builders.build_ollama_model`
      reroutes exactly that case to the account-bound ``ollama.com`` cloud
      endpoint (ADR-051).

    Both would otherwise make a static ``"local"`` curation wrong precisely
    when it matters most -- under an ``AGENTIC_MAX_COST_LANE=local``
    ceiling. Neither check runs for a non-``ollama:`` provider.
    """
    entry = load_registry().by_id().get(model_id)
    lane = (
        _DEFAULT_COST_LANE
        if entry is None or entry.cost_lane is None
        else entry.cost_lane
    )
    if lane == "local" and model_id.startswith("ollama:"):
        if not _ollama_base_is_loopback():
            return "free"
        if os.environ.get("OLLAMA_API_KEY"):
            from .ollama_discovery import is_served_locally

            if not is_served_locally(model_id.removeprefix("ollama:")):
                return "free"
    return lane


def cost_lane_rank(lane: CostLane) -> int:
    """Return the ordinal rank of ``lane`` (0=local, 1=free, 2=paid)."""
    return _LANE_RANK[lane]


def is_within_cost_lane(model_id: str, ceiling: CostLane) -> bool:
    """Return ``True`` when ``model_id``'s cost lane is at or under ``ceiling``."""
    return _LANE_RANK[cost_lane_for(model_id)] <= _LANE_RANK[ceiling]


_VALID_COST_LANES: tuple[CostLane, ...] = ("local", "free", "paid")


def max_cost_lane_ceiling() -> CostLane:
    """Read ``AGENTIC_MAX_COST_LANE``, defaulting/failing-safe to ``"paid"``.

    ``"paid"`` is the ceiling that filters nothing -- unset or an
    unrecognised value both fail safe to it (with a logged warning for the
    latter), matching every deployment's behavior before this setting
    existed. The single source of truth both engines' candidate resolvers
    read (``langchain/models.get_model_candidates_for_tier``,
    ``models/router.ModelRouter``, ``models/smart_router.SmartModelRouter``)
    so a ceiling set once applies regardless of which engine a workflow uses.
    """
    raw = os.environ.get("AGENTIC_MAX_COST_LANE", "").strip().lower()
    if not raw:
        return "paid"
    if raw in _VALID_COST_LANES:
        return raw  # type: ignore[return-value]
    logger.warning(
        "AGENTIC_MAX_COST_LANE=%r not recognised; treating as 'paid' "
        "(no filtering). Accepted: %s.",
        raw,
        _VALID_COST_LANES,
    )
    return "paid"


def apply_cost_lane_ceiling(
    candidates: Iterable[str],
    *,
    ceiling: CostLane | None = None,
    context: str = "",
) -> list[str]:
    """Filter ``candidates`` to those at or under the cost-lane ceiling.

    ``ceiling`` defaults to :func:`max_cost_lane_ceiling` (i.e.
    ``AGENTIC_MAX_COST_LANE``). A ``"paid"`` ceiling is a no-op -- returns
    ``candidates`` unchanged, matching unset/default behavior exactly, at
    every call site. Raises :class:`CostLaneCeilingExceededError` (naming
    the ceiling, the count considered, and ``context`` when given) rather
    than silently returning an empty list when filtering would empty an
    otherwise non-empty ``candidates`` -- never fall through to an
    unfiltered chain (ARP-IMPROVEMENTS F1).
    """
    resolved = ceiling if ceiling is not None else max_cost_lane_ceiling()
    ordered = list(candidates)
    if resolved == "paid":
        return ordered
    within_ceiling = [m for m in ordered if is_within_cost_lane(m, resolved)]
    if ordered and not within_ceiling:
        where = f" for {context}" if context else ""
        raise CostLaneCeilingExceededError(
            f"AGENTIC_MAX_COST_LANE={resolved!r} filtered every candidate"
            f"{where} ({len(ordered)} considered, 0 within the ceiling); "
            "refusing to fall through to an unfiltered chain."
        )
    return within_ceiling


def enforce_cost_lane_ceiling(model_id: str, *, ceiling: CostLane | None = None) -> None:
    """Raise :class:`CostLaneCeilingExceededError` if ``model_id`` is above the ceiling.

    For call sites where a single explicit model is used exactly as given,
    never substituted -- e.g. ``fallback_selector.run_with_fallback``'s
    ``model`` param and ``EKProvider.complete_chat``'s ``model`` kwarg both
    mean "attempt exactly this model, no re-selection" (an override contract
    those call sites deliberately preserve). :func:`apply_cost_lane_ceiling`
    cannot help there -- it filters a *candidate list*, and an explicit
    override is never resolved through one, so it silently bypassed the
    ceiling entirely before this existed. A ``"paid"`` ceiling (unset,
    default) is a no-op, matching every other ceiling call site.
    """
    resolved = ceiling if ceiling is not None else max_cost_lane_ceiling()
    if resolved != "paid" and not is_within_cost_lane(model_id, resolved):
        raise CostLaneCeilingExceededError(
            f"AGENTIC_MAX_COST_LANE={resolved!r} refuses explicit model "
            f"{model_id!r}: its cost lane ({cost_lane_for(model_id)!r}) is "
            "above the ceiling and this call site does not substitute "
            "models."
        )


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


class CostLaneCeilingExceededError(RuntimeError):
    """Raised when an ``AGENTIC_MAX_COST_LANE`` ceiling filters every candidate.

    Fail-closed (ARP-IMPROVEMENTS F1): a caller that asks for e.g. ``"free"``
    and gets an empty candidate list must see this, never a silent empty list
    or a silent fall-through to an unfiltered (potentially paid) chain.
    """
