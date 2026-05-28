#!/usr/bin/env python3
"""
Model Lock Utilities
====================

Provides lock file management for tracking which ONNX models are in use.
This allows parallel evaluation scripts to detect and avoid conflicts.

Usage:
    from model_locks import create_model_lock, get_models_in_use

    # When loading a model
    create_model_lock("Phi-4 Mini")

    # When checking what's in use
    in_use = get_models_in_use(available_models_dict)
"""

from __future__ import annotations

import atexit
import contextlib
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def get_lock_dir() -> Path:
    """Get the directory for model lock files."""
    lock_dir = Path.home() / ".cache" / "prompts-eval" / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    return lock_dir


def create_model_lock(model_name: str) -> Path:
    """Create a lock file indicating this model is in use. Automatically cleaned up when
    process exits.

    Args:
        model_name: Human-readable model name (e.g., "Phi-4 Mini")

    Returns:
        Path to the created lock file
    """
    import os

    lock_dir = get_lock_dir()
    # Use PID in filename to allow detection of which process has the lock
    lock_file = lock_dir / f"{model_name.replace(' ', '_')}_{os.getpid()}.lock"

    # Write lock info
    lock_info = {
        "pid": os.getpid(),
        "model": model_name,
        "timestamp": datetime.now().isoformat(),
        "script": Path(sys.argv[0]).name if sys.argv else "unknown",
    }
    lock_file.write_text(json.dumps(lock_info))

    # Register cleanup on exit
    def cleanup():
        try:
            if lock_file.exists():
                lock_file.unlink()
        except Exception:
            pass

    atexit.register(cleanup)
    return lock_file


def get_models_in_use(available: dict[str, Path] | None = None) -> dict[str, str]:
    """Check which models are currently in use by checking lock files. Validates PIDs
    are still running and cleans up stale locks.

    Args:
        available: Optional dict of available models to filter by.
                   If None, returns all locked models.

    Returns:
        Dict mapping model name to info string (e.g., "PID 1234: run_eval_geval.py")
    """
    try:
        import psutil
    except ImportError:
        # psutil not available, can't validate PIDs
        return {}

    in_use = {}
    lock_dir = get_lock_dir()

    if not lock_dir.exists():
        return in_use

    for lock_file in lock_dir.glob("*.lock"):
        try:
            lock_info = json.loads(lock_file.read_text())
            pid = lock_info.get("pid")
            model_name = lock_info.get("model", "Unknown")
            script = lock_info.get("script", "unknown")

            # Check if process is still running
            if pid and psutil.pid_exists(pid):
                # If available dict provided, only include if model is in it
                if available is None or model_name in available:
                    in_use[model_name] = f"PID {pid}: {script}"
            else:
                # Stale lock file - remove it
                lock_file.unlink()

        except (OSError, json.JSONDecodeError):
            # Corrupted lock file - remove it
            with contextlib.suppress(Exception):
                lock_file.unlink()

    return in_use


def clear_all_locks():
    """Remove all lock files.

    Useful for cleanup after crashes.
    """
    lock_dir = get_lock_dir()
    if lock_dir.exists():
        for lock_file in lock_dir.glob("*.lock"):
            with contextlib.suppress(Exception):
                lock_file.unlink()


if __name__ == "__main__":
    # Show current locks
    logger.info("Current model locks:")
    in_use = get_models_in_use()
    if in_use:
        for model, info in in_use.items():
            logger.info(f"  - {model}: {info}")
    else:
        logger.info("  (none)")
