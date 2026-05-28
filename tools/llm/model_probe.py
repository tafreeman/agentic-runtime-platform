#!/usr/bin/env python3
"""Model Probe & Cache -- slim facade.

Provides runtime probing of model availability with persistent caching.
This prevents wasted evaluation runs on models that are known to be unavailable.

Implementation is split across:
    - ``probe_config``     : Constants, ProbeResult, cache helpers, retry decorator
    - ``probe_providers``  : Per-provider probe functions
    - ``probe_discovery``  : Multi-provider discovery

Usage:
    from tools.llm.model_probe import ModelProbe

    probe = ModelProbe()

    # Check if a model is usable
    status = probe.check_model("gh:gpt-4o-mini")
    if status.usable:
        # Safe to evaluate
        ...

    # Filter a list of models to only runnable ones
    runnable = probe.filter_runnable(["gh:gpt-4o-mini", "gh:o1", "local:phi4"])

    # Get cached probe results
    probe.get_cache_summary()
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Re-export everything callers used to import from this module
from tools.core.errors import ErrorCode, classify_error
from tools.llm.probe_config import (
    CACHE_VERSION,
    ProbeResult,
    cache_key,
    get_cache_file,
    load_cache,
    save_cache,
    with_retry,
)
from tools.llm.probe_discovery import discover_all_models
from tools.llm.probe_providers import get_provider, probe_model

# Backward-compat: re-export public names so ``from tools.llm.model_probe import X`` still works
__all__ = [
    "ModelProbe",
    "ProbeResult",
    "discover_all_models",
    "filter_usable_models",
    "get_model_error",
    "get_probe",
    "is_model_usable",
    "main",
    "with_retry",
]


# =============================================================================
# MODEL PROBE CLASS
# =============================================================================


class ModelProbe:
    """Probes model availability and caches results.

    Cache TTL:
    - Permanent errors (403, unavailable): 24 hours
    - Transient errors (rate limit, timeout): 5 minutes
    - Success: 1 hour
    """

    # Cache TTLs
    TTL_SUCCESS = timedelta(hours=1)
    TTL_PERMANENT_ERROR = timedelta(hours=24)
    TTL_TRANSIENT_ERROR = timedelta(minutes=5)

    def __init__(self, use_cache: bool = True, verbose: bool = False):
        self.use_cache = use_cache
        self.verbose = verbose
        self._cache = (
            load_cache() if use_cache else {"version": CACHE_VERSION, "probes": {}}
        )
        self._session_probes: dict[str, ProbeResult] = {}

    def _log(self, msg: str) -> None:
        if self.verbose:
            logger.debug("[ModelProbe] %s", msg)

    def _get_provider(self, model: str) -> str:
        """Extract provider from model string."""
        return get_provider(model)

    def _cache_key(self, model: str) -> str:
        """Generate cache key for a model."""
        return cache_key(model)

    def _is_cache_valid(self, cached: dict[str, Any]) -> bool:
        """Check if a cached probe result is still valid."""
        if not cached.get("probe_time"):
            return False

        try:
            probe_time = datetime.fromisoformat(cached["probe_time"])
        except Exception:
            return False

        now = datetime.now()
        error_code = cached.get("error_code")

        if error_code is None or error_code == ErrorCode.SUCCESS.value:
            ttl = self.TTL_SUCCESS
        elif error_code in [
            ErrorCode.PERMISSION_DENIED.value,
            ErrorCode.UNAVAILABLE_MODEL.value,
        ]:
            ttl = self.TTL_PERMANENT_ERROR
        else:
            ttl = self.TTL_TRANSIENT_ERROR

        return (now - probe_time) < ttl

    def _probe_model(self, model: str) -> ProbeResult:
        """Probe a model based on its provider."""
        return probe_model(model, log=self._log)

    def check_model(self, model: str, force_probe: bool = False) -> ProbeResult:
        """Check if a model is usable.

        Args:
            model: Model identifier (e.g., "gh:gpt-4o-mini", "local:phi4")
            force_probe: Skip cache and probe fresh

        Returns:
            ProbeResult with usability status
        """
        ck = self._cache_key(model)

        # Check session cache first (fastest)
        if not force_probe and ck in self._session_probes:
            result = self._session_probes[ck]
            result.cached = True
            return result

        # Check persistent cache
        if not force_probe and self.use_cache:
            cached = self._cache.get("probes", {}).get(ck)
            if cached and self._is_cache_valid(cached):
                result = ProbeResult(**cached)
                result.cached = True
                self._session_probes[ck] = result
                self._log(f"Cache hit: {model} -> usable={result.usable}")
                return result

        # Probe the model
        self._log(f"Probing: {model}")
        result = self._probe_model(model)

        # Cache the result
        self._session_probes[ck] = result
        if self.use_cache:
            self._cache.setdefault("probes", {})[ck] = result.to_dict()
            save_cache(self._cache)

        self._log(
            f"Probe complete: {model} -> usable={result.usable}, error={result.error_code}"
        )
        return result

    def filter_runnable(
        self, models: list[str], force_probe: bool = False
    ) -> list[str]:
        """Filter a list of models to only those that are runnable.

        Args:
            models: List of model identifiers
            force_probe: Skip cache and probe fresh

        Returns:
            List of runnable model identifiers
        """
        runnable = []
        for model in models:
            result = self.check_model(model, force_probe=force_probe)
            if result.usable:
                runnable.append(model)
        return runnable

    def get_probe_report(self, models: list[str]) -> dict[str, Any]:
        """Get a detailed probe report for a list of models.

        Returns:
            Dict with probe results and summary
        """
        results = {}
        usable = []
        unusable = []

        for model in models:
            result = self.check_model(model)
            results[model] = result.to_dict()
            if result.usable:
                usable.append(model)
            else:
                unusable.append((model, result.error_code, result.error_message))

        return {
            "timestamp": datetime.now().isoformat(),
            "total": len(models),
            "usable_count": len(usable),
            "unusable_count": len(unusable),
            "usable": usable,
            "unusable": [
                {"model": m, "error_code": c, "error": e} for m, c, e in unusable
            ],
            "details": results,
        }

    def clear_cache(self, model: str | None = None) -> None:
        """Clear probe cache.

        Args:
            model: If provided, clear only this model. Otherwise clear all.
        """
        if model:
            ck = self._cache_key(model)
            self._session_probes.pop(ck, None)
            self._cache.get("probes", {}).pop(ck, None)
        else:
            self._session_probes.clear()
            self._cache["probes"] = {}

        if self.use_cache:
            save_cache(self._cache)

    def get_cache_summary(self) -> dict[str, Any]:
        """Get a summary of the current cache state."""
        probes = self._cache.get("probes", {})

        valid = 0
        expired = 0
        usable = 0
        unusable = 0

        for cached in probes.values():
            if self._is_cache_valid(cached):
                valid += 1
                if cached.get("usable"):
                    usable += 1
                else:
                    unusable += 1
            else:
                expired += 1

        return {
            "cache_file": str(get_cache_file()),
            "total_entries": len(probes),
            "valid_entries": valid,
            "expired_entries": expired,
            "usable_models": usable,
            "unusable_models": unusable,
            "last_updated": self._cache.get("last_updated"),
        }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def is_model_usable(model: str) -> bool:
    """Quick check if a model is usable."""
    return get_probe().check_model(model).usable


def filter_usable_models(models: list[str]) -> list[str]:
    """Filter a list to only usable models."""
    return get_probe().filter_runnable(models)


def get_model_error(model: str) -> str | None:
    """Get the error message for an unusable model."""
    result = get_probe().check_model(model)
    return result.error_message if not result.usable else None


# =============================================================================
# CANONICAL SINGLETON ACCESS
# =============================================================================

_DEFAULT_PROBE: ModelProbe | None = None


def get_probe(*, verbose: bool = False, use_cache: bool = True) -> ModelProbe:
    """Return a process-wide ModelProbe instance.

    Many scripts (and tool_init) want a quick probe without managing lifetime.
    We provide a singleton so callers share cache and avoid repeated disk I/O.

    Args:
        verbose: Enable probe logging.
        use_cache: Enable persistent cache.
    """
    global _DEFAULT_PROBE
    if _DEFAULT_PROBE is None:
        _DEFAULT_PROBE = ModelProbe(use_cache=use_cache, verbose=verbose)
    return _DEFAULT_PROBE


# =============================================================================
# CLI
# =============================================================================


def main(argv: list[str]) -> int:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Probe model availability")
    parser.add_argument("models", nargs="*", help="Models to probe")
    parser.add_argument(
        "--all-github", action="store_true", help="Probe common GitHub models"
    )
    parser.add_argument(
        "--all-local", action="store_true", help="Probe all local ONNX models"
    )
    parser.add_argument(
        "--all-azure", action="store_true", help="Check Azure Foundry/OpenAI"
    )
    parser.add_argument("--all-ollama", action="store_true", help="Probe Ollama models")
    parser.add_argument(
        "--all-aitk", action="store_true", help="Probe AI Toolkit local models (free)"
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Discover all available models from all providers",
    )
    parser.add_argument(
        "--force", action="store_true", help="Force fresh probe (ignore cache)"
    )
    parser.add_argument(
        "--clear-cache", action="store_true", help="Clear the probe cache"
    )
    parser.add_argument(
        "--cache-info", action="store_true", help="Show cache information"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("-o", "--output", help="Output file (JSON)")

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    probe = ModelProbe(verbose=args.verbose)

    if args.clear_cache:
        probe.clear_cache()
        logger.info("Cache cleared.")
        return 0

    if args.cache_info:
        info = probe.get_cache_summary()
        logger.info(json.dumps(info, indent=2))
        return 0

    # Discovery mode - find all available models
    if args.discover:
        discovered = discover_all_models(verbose=args.verbose)

        if args.output:
            Path(args.output).write_text(json.dumps(discovered, indent=2))
            logger.info(f"Discovery saved to: {args.output}")
        else:
            logger.info("\n" + "=" * 60)
            logger.info("MODEL DISCOVERY REPORT")
            logger.info("=" * 60)
            logger.info(f"Total available: {discovered['summary']['total_available']}")
            logger.info(
                f"Providers configured: {discovered['summary']['providers_configured']}"
            )
            logger.info("")

            for name, info in discovered["providers"].items():
                logger.info(f"\n{name.upper().replace('_', ' ')}")
                if info.get("available"):
                    logger.info(f"   [OK] {len(info['available'])} model(s) available:")
                    for m in info["available"][:10]:
                        logger.info(f"      - {m}")
                    if len(info.get("available", [])) > 10:
                        logger.info(f"      ... and {len(info['available']) - 10} more")
                elif info.get("configured"):
                    logger.info("   [OK] Configured (use explicit model IDs)")
                else:
                    logger.info(f"   [FAIL] {info.get('error', 'Not configured')}")

        return 0

    # Build model list
    models = list(args.models)

    if args.all_github:
        # Use full publisher/model format for GitHub models
        models.extend(
            [
                "gh:openai/gpt-4o-mini",
                "gh:openai/gpt-4o",
                "gh:openai/gpt-4.1",
                "gh:openai/gpt-4.1-nano",
                "gh:meta/llama-3.3-70b-instruct",
                "gh:mistralai/mistral-small-2503",
                "gh:openai/o1",
                "gh:openai/o3",
                "gh:deepseek/deepseek-r1",
                "gh:microsoft/phi-4",
            ]
        )

    if args.all_local:
        models.extend(
            [
                "local:phi4",
                "local:phi3.5",
                "local:phi3",
                "local:mistral",
                "local:phi3-medium",
            ]
        )

    if args.all_azure:
        models.extend(
            [
                "azure-foundry:default",
                "azure-openai:default",
            ]
        )

    if args.all_ollama:
        # Discover Ollama models dynamically
        try:
            discovered = discover_all_models(verbose=False)
            ollama_models = (
                discovered.get("providers", {}).get("ollama", {}).get("available", [])
            )
            models.extend(ollama_models)
        except Exception:
            pass

    if args.all_aitk:
        # Discover AI Toolkit local models dynamically
        try:
            discovered = discover_all_models(verbose=False)
            aitk_models = (
                discovered.get("providers", {})
                .get("ai_toolkit", {})
                .get("available", [])
            )
            models.extend(aitk_models)
        except Exception:
            pass

    if not models:
        selected_provider_group = any(
            [
                args.all_github,
                args.all_local,
                args.all_azure,
                args.all_ollama,
                args.all_aitk,
            ]
        )
        if selected_provider_group:
            logger.warning("No models discovered for the selected provider flags.")
            logger.warning(
                "Check provider connectivity/configuration (e.g., OLLAMA_HOST, "
                "gh auth, local model installation)."
            )
            return 1

        parser.print_help()
        return 1

    # Remove duplicates while preserving order
    seen: set[str] = set()
    unique_models = []
    for m in models:
        if m not in seen:
            seen.add(m)
            unique_models.append(m)

    # Get report
    report = probe.get_probe_report(unique_models)

    # Output
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2))
        logger.info(f"Report saved to: {args.output}")
    else:
        logger.info("\n" + "=" * 60)
        logger.info("Model Probe Report")
        logger.info("=" * 60)
        logger.info(
            f"Total: {report['total']} | Usable: {report['usable_count']} | Unusable: {report['unusable_count']}"
        )
        logger.info("")

        if report["usable"]:
            logger.info("[OK] Usable models:")
            for m in report["usable"]:
                logger.info(f"   {m}")

        if report["unusable"]:
            logger.info("\n[FAIL] Unusable models:")
            for item in report["unusable"]:
                logger.info(
                    f"   {item['model']}: {item['error_code']} - {item['error'][:60]}"
                )

        logger.info("")

    return 0 if report["unusable_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
