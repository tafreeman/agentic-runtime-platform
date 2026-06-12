"""
Models module - Model routing and statistics.

Exports:
- Routing: ModelRouter, SmartModelRouter, ModelTier, FallbackChain
- Stats: ModelStats, CircuitState, LatencyPercentiles, CooldownConfig
- Rate Limits: RateLimitTracker, TokenBucket (ADR-002E)
- Client: LLMClientWrapper, LLMBackend, TokenBudget
- Globals: get_router, get_smart_router, get_client
"""

from typing import TYPE_CHECKING

from .backends import (
    AnthropicBackend,
    AzureFoundryBackend,
    AzureOpenAIBackend,
    GeminiBackend,
    GitHubModelsBackend,
    MockBackend,
    MultiBackend,
    OllamaBackend,
    OnnxBackend,
    OpenAIBackend,
    auto_configure_backend,
    get_backend,
)
from .cache_budget import CachedResponse, TokenBudget
from .client import (
    LLMBackend,
    LLMClientWrapper,
    get_client,
    reset_client,
    retry_with_jitter,
)
from .model_stats import CircuitState, LatencyPercentiles, ModelStats
from .rate_limit_tracker import RateLimitTracker, TokenBucket
from .redis_state import RedisCircuitBreakerStore
from .router import (
    DEFAULT_CHAINS,
    ChainBuilder,
    FallbackChain,
    ModelRouter,
    ModelTier,
    ScopedRouter,
    get_router,
    reset_router,
)
from .smart_router import (
    CooldownConfig,
    ModelSelection,
    SmartModelRouter,
    get_smart_router,
    reset_smart_router,
)

if TYPE_CHECKING:
    from ..core.errors import NoProviderConfiguredError


def __getattr__(name: str):
    """Lazily resolve error re-exports without importing core during init."""
    if name == "NoProviderConfiguredError":
        from ..core.errors import NoProviderConfiguredError

        return NoProviderConfiguredError
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Stats
    "CircuitState",
    "LatencyPercentiles",
    "ModelStats",
    # Router
    "ModelTier",
    "FallbackChain",
    "ChainBuilder",
    "ModelRouter",
    "ScopedRouter",
    "DEFAULT_CHAINS",
    "get_router",
    "reset_router",
    # Rate-limit tracker (ADR-002E)
    "RateLimitTracker",
    "TokenBucket",
    # Redis state
    "RedisCircuitBreakerStore",
    # Smart router
    "CooldownConfig",
    "ModelSelection",
    "NoProviderConfiguredError",
    "SmartModelRouter",
    "get_smart_router",
    "reset_smart_router",
    # Client
    "LLMBackend",
    "TokenBudget",
    "CachedResponse",
    "LLMClientWrapper",
    "retry_with_jitter",
    "get_client",
    "reset_client",
    # Backends
    "GitHubModelsBackend",
    "OpenAIBackend",
    "AnthropicBackend",
    "GeminiBackend",
    "AzureOpenAIBackend",
    "AzureFoundryBackend",
    "OllamaBackend",
    "OnnxBackend",
    "MultiBackend",
    "MockBackend",
    "get_backend",
    "auto_configure_backend",
]
