"""Model router with configurable fallback chains.

Provides the foundational routing layer for LLM model selection:

- :class:`ModelTier` — 6-level capability tier (0=deterministic through
  5=premium cloud).
- :class:`FallbackChain` — immutable ordered sequence of model identifiers
  to try in priority order, built via :class:`ChainBuilder` fluent DSL.
- :class:`ModelRouter` — routes requests to the first available model in
  a tier's fallback chain.  Supports lazy model discovery, parallel health
  checks, and :class:`ScopedRouter` context-manager overrides.
- ``DEFAULT_CHAINS`` — pre-configured fallback chains for each tier,
  ordered free-tier-first (Gemini, GitHub Models) then paid (OpenAI,
  Anthropic).

Model identifiers use a ``provider:model_name`` format, e.g.
``"gemini:gemini-2.0-flash"`` or ``"gh:openai/gpt-4o-mini"``.
"""

import asyncio
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Sequence


class ModelTier(IntEnum):
    """Model capability tiers.

    Higher tiers have more capable (and expensive) models.
    """

    TIER_0 = 0  # No LLM (deterministic tools)
    TIER_1 = 1  # Small models (1-3B params) - fast, cheap
    TIER_2 = 2  # Medium models (7-14B params) - balanced
    TIER_3 = 3  # Large models (32B+ params) - capable
    TIER_4 = 4  # Cloud models (GPT-4, Claude) - most capable
    TIER_5 = 5  # Premium cloud (GPT-4-turbo, Claude-3-opus)


@dataclass
class FallbackChain:
    """A chain of models to try in order.

    Design: Immutable chain with fluent builder for construction.
    """

    models: tuple[str, ...]
    name: str = "default"

    def __post_init__(self):
        if not self.models:
            raise ValueError("FallbackChain must have at least one model")

    def __iter__(self):
        return iter(self.models)

    def __len__(self):
        return len(self.models)

    def __getitem__(self, index: int) -> str:
        return self.models[index]

    @classmethod
    def build(cls, name: str = "default") -> "ChainBuilder":
        """Start building a fallback chain with DSL.

        Usage:
            chain = FallbackChain.build("my-chain")
                .add("ollama:phi4")
                .add("gh:gpt-4o-mini")
                .add("gh:gpt-4o")
                .done()
        """
        return ChainBuilder(name)


class ChainBuilder:
    """Fluent builder for FallbackChain."""

    def __init__(self, name: str):
        self._name = name
        self._models: list[str] = []

    def add(self, model: str) -> "ChainBuilder":
        """Add a model to the chain."""
        self._models.append(model)
        return self

    def add_tier(self, tier: ModelTier, models: Sequence[str]) -> "ChainBuilder":
        """Add multiple models for a tier."""
        self._models.extend(models)
        return self

    def done(self) -> FallbackChain:
        """Complete the chain."""
        return FallbackChain(tuple(self._models), self._name)


# Default chains for each tier
# Ordering: free cloud (fast) → paid cloud.
# Gemini free tier and GitHub Models are free and fast — try first.
# OpenAI/Anthropic are paid — use as secondary.
DEFAULT_CHAINS: dict[ModelTier, FallbackChain] = {
    ModelTier.TIER_1: FallbackChain(
        (
            "gemini:gemini-2.0-flash-lite",
            "gh:openai/gpt-4o-mini",
            "openai:gpt-4o-mini",
        ),
        "tier1-default",
    ),
    ModelTier.TIER_2: FallbackChain(
        (
            "gemini:gemini-2.0-flash",
            "gh:openai/gpt-4o-mini",
            "openai:gpt-4o-mini",
            "anthropic:claude-3-5-haiku-20241022",
        ),
        "tier2-default",
    ),
    ModelTier.TIER_3: FallbackChain(
        (
            "gemini:gemini-2.5-flash",
            "gh:openai/gpt-4o",
            "openai:gpt-4o",
            "anthropic:claude-sonnet-4-5-20250929",
        ),
        "tier3-default",
    ),
    ModelTier.TIER_4: FallbackChain(
        (
            "gemini:gemini-2.5-pro",
            "gh:openai/gpt-4o",
            "openai:gpt-4o",
            "anthropic:claude-sonnet-4-5-20250929",
        ),
        "tier4-default",
    ),
    ModelTier.TIER_5: FallbackChain(
        (
            "gemini:gemini-2.5-pro",
            "openai:gpt-4o",
            "anthropic:claude-opus-4-6",
            "gh:openai/gpt-4o",
        ),
        "tier5-default",
    ),
}


@dataclass
class ModelRouter:
    """Routes requests to models based on tier and runtime availability.

    For each request, walks the tier's :class:`FallbackChain` and returns
    the first model that passes the health check.  Models that fail are
    cached as unavailable until explicitly re-probed.

    Supports:
    - **Custom chains** — per-tier overrides via :meth:`register_chain`.
    - **Lazy discovery** — models are probed only when first accessed.
    - **Parallel probing** — :meth:`discover_models_async` checks multiple
      models concurrently via a thread pool.
    - **Scoped routing** — :meth:`scoped` returns a context manager that
      temporarily overrides a tier's chain.

    Attributes:
        custom_chains: Per-tier chain overrides (take precedence over defaults).
    """

    # Custom chains override defaults
    custom_chains: dict[ModelTier, FallbackChain] = field(default_factory=dict)

    # Model availability cache
    _available_models: set[str] = field(default_factory=set)
    _unavailable_models: set[str] = field(default_factory=set)
    _discovered: bool = False

    # Health check function (injected)
    _health_checker: Callable[[str], bool] | None = None

    def set_health_checker(self, checker: Callable[[str], bool]) -> None:
        """Set the health check function.

        Args:
            checker: Function that returns True if model is available
        """
        self._health_checker = checker

    def register_chain(self, tier: ModelTier, chain: FallbackChain) -> None:
        """Register a custom chain for a tier.

        Args:
            tier: Model tier
            chain: Fallback chain to use
        """
        self.custom_chains[tier] = chain

    def get_chain(self, tier: ModelTier) -> FallbackChain:
        """Get the fallback chain for a tier.

        Args:
            tier: Model tier

        Returns:
            Configured or default chain
        """
        return self.custom_chains.get(
            tier, DEFAULT_CHAINS.get(tier, DEFAULT_CHAINS[ModelTier.TIER_2])
        )

    def is_model_available(self, model: str) -> bool:
        """Check if a model is available.

        Args:
            model: Model identifier

        Returns:
            True if model is available
        """
        if model in self._available_models:
            return True
        if model in self._unavailable_models:
            return False

        # Probe if we have a health checker
        if self._health_checker:
            available = self._health_checker(model)
            if available:
                self._available_models.add(model)
            else:
                self._unavailable_models.add(model)
            return available

        # Assume available if no checker
        return True

    def mark_available(self, model: str) -> None:
        """Mark a model as available."""
        self._available_models.add(model)
        self._unavailable_models.discard(model)

    def mark_unavailable(self, model: str) -> None:
        """Mark a model as unavailable."""
        self._unavailable_models.add(model)
        self._available_models.discard(model)

    def get_model_for_tier(self, tier: ModelTier) -> str | None:
        """Get first available model for a tier.

        Args:
            tier: Model tier

        Returns:
            Model identifier or None if none available
        """
        chain = self.get_chain(tier)
        for model in chain:
            if self.is_model_available(model):
                return model
        return None

    def get_fallback_for_model(self, model: str, tier: ModelTier) -> str | None:
        """Get next model in chain after the given one.

        Args:
            model: Current model
            tier: Model tier

        Returns:
            Next available model or None
        """
        chain = self.get_chain(tier)
        found_current = False
        for m in chain:
            if found_current and self.is_model_available(m):
                return m
            if m == model:
                found_current = True
        return None

    async def discover_models_async(self, models: Sequence[str]) -> dict[str, bool]:
        """Check multiple models in parallel.

        Args:
            models: Models to check

        Returns:
            Dict mapping model -> available
        """
        if not self._health_checker:
            return {m: True for m in models}

        async def check_one(model: str) -> tuple[str, bool]:
            # Run sync checker in a worker thread (idiomatic 3.9+ replacement for
            # get_event_loop().run_in_executor(None, ...)).
            available = await asyncio.to_thread(self._health_checker, model)
            return model, available

        results = await asyncio.gather(*[check_one(m) for m in models])

        availability = {}
        for model, available in results:
            availability[model] = available
            if available:
                self._available_models.add(model)
            else:
                self._unavailable_models.add(model)

        self._discovered = True
        return availability

    def discover_models_sync(self, models: Sequence[str]) -> dict[str, bool]:
        """Check multiple models synchronously.

        Args:
            models: Models to check

        Returns:
            Dict mapping model -> available
        """
        availability = {}
        for model in models:
            available = self.is_model_available(model)
            availability[model] = available
        self._discovered = True
        return availability

    def scoped(self, tier: ModelTier, models: Sequence[str]) -> "ScopedRouter":
        """Create a scoped router for a specific context.

        Usage:
            with router.scoped(ModelTier.TIER_2, ["ollama:phi4"]) as scoped:
                model = scoped.get_model()

        Args:
            tier: Tier for this scope
            models: Allowed models in this scope

        Returns:
            Context manager for scoped routing
        """
        return ScopedRouter(self, tier, models)

    def __repr__(self) -> str:
        return (
            f"ModelRouter(available={len(self._available_models)}, "
            f"unavailable={len(self._unavailable_models)}, "
            f"custom_chains={len(self.custom_chains)})"
        )


class ScopedRouter:
    """Context manager for scoped model routing.

    Allows temporary override of model selection within a context.
    """

    def __init__(self, parent: ModelRouter, tier: ModelTier, models: Sequence[str]):
        self._parent = parent
        self._tier = tier
        self._models = list(models)
        self._original_chain: FallbackChain | None = None

    def __enter__(self) -> "ScopedRouter":
        # Save original chain and register scoped chain
        self._original_chain = self._parent.custom_chains.get(self._tier)
        self._parent.register_chain(
            self._tier, FallbackChain(tuple(self._models), f"scoped-{self._tier.name}")
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Restore original chain
        if self._original_chain:
            self._parent.custom_chains[self._tier] = self._original_chain
        elif self._tier in self._parent.custom_chains:
            del self._parent.custom_chains[self._tier]
        return False

    def get_model(self) -> str | None:
        """Get first available model in scope."""
        return self._parent.get_model_for_tier(self._tier)

    def get_all_available(self) -> list[str]:
        """Get all available models in scope."""
        return [m for m in self._models if self._parent.is_model_available(m)]


# Global default router instance
_default_router: ModelRouter | None = None


def get_router() -> ModelRouter:
    """Get the global default router."""
    global _default_router
    if _default_router is None:
        _default_router = ModelRouter()
    return _default_router


def reset_router() -> None:
    """Reset the global router (for testing)."""
    global _default_router
    _default_router = None
