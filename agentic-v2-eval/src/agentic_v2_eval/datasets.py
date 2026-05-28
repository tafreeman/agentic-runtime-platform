"""Benchmark datasets for agent evaluation.

This module bridges the benchmark infrastructure from tools.agents.benchmarks
into the agentic-v2-eval package, providing access to standard coding benchmarks.

Supported Benchmarks:
    - SWE-bench: Real GitHub issues requiring code patches
    - SWE-bench-lite: 300-task subset for quick evaluation
    - SWE-bench-verified: Human-validated subset
    - HumanEval: 164 function-level Python tasks
    - MBPP: 974 basic Python programming tasks
    - CodeClash: Competitive programming problems
    - custom-local: User-defined local tasks

Example:
    >>> from agentic_v2_eval.datasets import (
    ...     load_benchmark,
    ...     BENCHMARK_DEFINITIONS,
    ...     BenchmarkTask,
    ... )
    >>>
    >>> # List available benchmarks
    >>> for bid, bdef in BENCHMARK_DEFINITIONS.items():
    ...     print(f"{bid}: {bdef.name} ({bdef.size} tasks)")
    >>>
    >>> # Load tasks from a benchmark
    >>> tasks = load_benchmark("humaneval", limit=10)
    >>> for task in tasks:
    ...     print(f"{task.task_id}: {task.prompt[:50]}...")
"""

from __future__ import annotations

import logging
from types import ModuleType
from typing import TYPE_CHECKING, Any, cast

logger = logging.getLogger(__name__)

# Lazy imports to avoid circular dependencies and allow standalone usage
_datasets_module: ModuleType | None = None
_loader_module: ModuleType | None = None
_registry_module: ModuleType | None = None


def _ensure_imports() -> None:
    """Ensure benchmark modules are imported."""
    global _datasets_module, _loader_module, _registry_module
    if _datasets_module is None:
        try:
            from tools.agents.benchmarks import datasets as _datasets_mod
            from tools.agents.benchmarks import loader as _loader_mod
            from tools.agents.benchmarks import registry as _registry_mod

            _datasets_module = _datasets_mod
            _loader_module = _loader_mod
            _registry_module = _registry_mod
        except ImportError as e:
            logger.warning(
                "Could not import tools.agents.benchmarks: %s. "
                "Benchmark loading will not be available.",
                e,
            )
            raise ImportError(
                "tools.agents.benchmarks is required for dataset access. "
                "Ensure it's installed and in your Python path."
            ) from e


def _require_datasets_module() -> ModuleType:
    """Return the loaded ``tools.agents.benchmarks.datasets`` module.

    Raises:
        ImportError: If benchmark modules are not available.
    """
    _ensure_imports()
    if _datasets_module is None:  # pragma: no cover - defensive
        raise ImportError("tools.agents.benchmarks.datasets is not available.")
    return _datasets_module


def _require_loader_module() -> ModuleType:
    """Return the loaded ``tools.agents.benchmarks.loader`` module."""
    _ensure_imports()
    if _loader_module is None:  # pragma: no cover - defensive
        raise ImportError("tools.agents.benchmarks.loader is not available.")
    return _loader_module


def _require_registry_module() -> ModuleType:
    """Return the loaded ``tools.agents.benchmarks.registry`` module."""
    _ensure_imports()
    if _registry_module is None:  # pragma: no cover - defensive
        raise ImportError("tools.agents.benchmarks.registry is not available.")
    return _registry_module


# Type-checking stubs for IDE support
if TYPE_CHECKING:
    from tools.agents.benchmarks.datasets import (
        BENCHMARK_DEFINITIONS,
        BenchmarkDefinition,
        BenchmarkType,
        DataSource,
    )
    from tools.agents.benchmarks.loader import BenchmarkTask
    from tools.agents.benchmarks.registry import (
        PRESET_CONFIGS,
        BenchmarkConfig,
        BenchmarkRegistry,
    )


def get_benchmark_definitions() -> dict[str, BenchmarkDefinition]:
    """Get all available benchmark definitions.

    Returns:
        Dictionary mapping benchmark IDs to their definitions.
    """
    return cast(
        "dict[str, BenchmarkDefinition]",
        _require_datasets_module().BENCHMARK_DEFINITIONS,
    )


def get_benchmark_definition(benchmark_id: str) -> BenchmarkDefinition | None:
    """Get a specific benchmark definition.

    Args:
        benchmark_id: The benchmark ID (e.g., "humaneval", "swe-bench-lite")

    Returns:
        BenchmarkDefinition if found, None otherwise.
    """
    return cast(
        "BenchmarkDefinition | None",
        _require_datasets_module().BENCHMARK_DEFINITIONS.get(benchmark_id),
    )


def list_benchmarks() -> list[str]:
    """List all available benchmark IDs.

    Returns:
        List of benchmark IDs.
    """
    return list(_require_datasets_module().BENCHMARK_DEFINITIONS.keys())


def load_benchmark(
    benchmark_id: str,
    limit: int | None = None,
    language: str | None = None,
    difficulty: str | None = None,
    cache_dir: str | None = None,
    force_refresh: bool = False,
) -> list[BenchmarkTask]:
    """Load tasks from a benchmark.

    Args:
        benchmark_id: Which benchmark to load (e.g., "humaneval", "mbpp")
        limit: Maximum number of tasks to load (None = all)
        language: Filter by programming language
        difficulty: Filter by difficulty level
        cache_dir: Custom cache directory (default: ~/.cache/agentic-benchmarks)
        force_refresh: Force re-download even if cached

    Returns:
        List of BenchmarkTask objects.

    Raises:
        ValueError: If benchmark_id is not recognized.
        ImportError: If benchmark modules are not available.

    Example:
        >>> tasks = load_benchmark("humaneval", limit=5)
        >>> for task in tasks:
        ...     print(task.task_id, task.prompt[:50])
    """
    datasets_mod = _require_datasets_module()
    loader_mod = _require_loader_module()

    if benchmark_id not in datasets_mod.BENCHMARK_DEFINITIONS:
        available = ", ".join(list_benchmarks())
        raise ValueError(f"Unknown benchmark: {benchmark_id}. Available: {available}")

    # Load via loader (native API)
    tasks: list[BenchmarkTask] = loader_mod.load_benchmark(
        benchmark_id=benchmark_id,
        limit=limit,
        use_cache=not force_refresh,
    )

    # Apply optional filters locally
    if language:
        tasks = [t for t in tasks if getattr(t, "language", None) == language]
    if difficulty:
        tasks = [t for t in tasks if getattr(t, "difficulty", None) == difficulty]

    return tasks


def get_registry() -> BenchmarkRegistry:
    """Get the benchmark registry for advanced configuration.

    Returns:
        BenchmarkRegistry instance with preset configurations.
    """
    return cast("BenchmarkRegistry", _require_registry_module().BenchmarkRegistry())


# Re-export key types for convenience
def __getattr__(name: str) -> Any:
    """Lazy attribute access for re-exported types."""
    _ensure_imports()

    # Map attribute names to their source modules
    exports = {
        # From datasets
        "BENCHMARK_DEFINITIONS": (_datasets_module, "BENCHMARK_DEFINITIONS"),
        "BenchmarkDefinition": (_datasets_module, "BenchmarkDefinition"),
        "BenchmarkType": (_datasets_module, "BenchmarkType"),
        "DataSource": (_datasets_module, "DataSource"),
        # From loader
        "BenchmarkTask": (_loader_module, "BenchmarkTask"),
        # From registry
        "BenchmarkConfig": (_registry_module, "BenchmarkConfig"),
        "BenchmarkRegistry": (_registry_module, "BenchmarkRegistry"),
        "PRESET_CONFIGS": (_registry_module, "PRESET_CONFIGS"),
    }

    if name in exports:
        module, attr = exports[name]
        return getattr(module, attr)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Types (lazy-loaded)
    "BENCHMARK_DEFINITIONS",
    "PRESET_CONFIGS",
    "BenchmarkConfig",
    "BenchmarkDefinition",
    "BenchmarkRegistry",
    "BenchmarkTask",
    "BenchmarkType",
    "DataSource",
    "get_benchmark_definition",
    # Functions
    "get_benchmark_definitions",
    "get_registry",
    "list_benchmarks",
    "load_benchmark",
]
