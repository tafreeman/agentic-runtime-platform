#!/usr/bin/env python3
"""
Tool Initialization Module
==========================

Import this module at the top of any script to automatically enforce:
- Unicode/encoding fixes for Windows
- Fail-fast prerequisite checking
- Iterative logging
- Model availability checking
- Progress reporting
- Error classification

Usage:
    from tools.core.tool_init import ToolInit, init_tool

    # Quick initialization (most common)
    init = init_tool(
        name="my_script",
        required_models=["local:phi4"],
        required_env=["GITHUB_TOKEN"],
    )

    # Now safe to proceed - prerequisites verified
    for item in items:
        with init.log_item(item) as log:
            result = process(item)
            log.success(score=result.score)

    # At end
    init.summary()
"""

from __future__ import annotations

import io
import json
import logging
import os
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from tools.core.errors import ErrorCode, classify_error
from tools.core.model_availability import is_model_available

logger = logging.getLogger(__name__)

# =============================================================================
# WINDOWS CONSOLE ENCODING FIX (Applied on import)
# =============================================================================


def _is_pytest_running() -> bool:
    """Check if we're running under pytest (avoid breaking capture)."""
    return "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ


def _is_already_wrapped(stream) -> bool:
    """Check if stream is already a TextIOWrapper with UTF-8."""
    return (
        isinstance(stream, io.TextIOWrapper)
        and getattr(stream, "encoding", "").lower() == "utf-8"
    )


if sys.platform == "win32" and not _is_pytest_running():
    os.environ["PYTHONIOENCODING"] = "utf-8"
    try:
        if not _is_already_wrapped(sys.stdout):
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding="utf-8", errors="replace"
            )
        if not _is_already_wrapped(sys.stderr):
            sys.stderr = io.TextIOWrapper(
                sys.stderr.buffer, encoding="utf-8", errors="replace"
            )
    except (OSError, AttributeError):
        pass  # Already wrapped or not available


# =============================================================================
# ERROR CODES (Standardized)
# =============================================================================


# =============================================================================
# SAFE STRING HANDLING
# =============================================================================


def safe_str(text: Any) -> str:
    """Ensure value is a string safe for console output."""
    if not isinstance(text, str):
        text = str(text)
    return text.encode("utf-8", errors="replace").decode("utf-8")


def safe_print(text: str = "", **kwargs):
    """Print text safely, handling Unicode errors."""
    try:
        print(text, **kwargs)
    except UnicodeEncodeError:
        print(safe_str(text), **kwargs)


# =============================================================================
# LOG ENTRY CONTEXT MANAGER
# =============================================================================


@dataclass
class LogEntry:
    """Context manager for logging a single item's processing."""

    init: "ToolInit"
    item: str
    start_time: float = field(default_factory=time.time)
    _logged: bool = False

    def success(self, **data):
        """Log successful completion."""
        self._log(ErrorCode.SUCCESS, None, data)

    def error(self, error: str, code: str | None = None, **data):
        """Log an error."""
        if code is None:
            code, _ = classify_error(error)
        self._log(code, error, data)

    def _log(self, code: str, error: str | None, data: dict):
        """Write log entry."""
        if self._logged:
            return
        self._logged = True

        duration_ms = int((time.time() - self.start_time) * 1000)

        entry = {
            "timestamp": datetime.now().isoformat(),
            "item": self.item,
            "error_code": code,
            "error": error,
            "duration_ms": duration_ms,
            **data,
        }

        self.init._write_log(entry)

        if code == ErrorCode.SUCCESS:
            self.init._success_count += 1
        else:
            self.init._failed_count += 1
            self.init._failed_items.append(
                {"item": self.item, "error": error, "code": code}
            )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None and not self._logged:
            self.error(str(exc_val))
        elif not self._logged:
            # Auto-success if no error and not explicitly logged
            self.success()
        return False  # Don't suppress exceptions


# =============================================================================
# MAIN TOOL INITIALIZATION CLASS
# =============================================================================


@dataclass
class ToolInit:
    """Tool initialization and runtime support.

    Handles:
    - Prerequisite checking (fail-fast)
    - Model availability verification
    - Iterative logging
    - Progress tracking
    - Summary reporting
    """

    name: str
    log_file: Path = None
    verbose: bool = False

    # Internal state
    _success_count: int = 0
    _failed_count: int = 0
    _failed_items: list[dict] = field(default_factory=list)
    _start_time: float = field(default_factory=time.time)
    _total_items: int = 0
    _current_item: int = 0

    def __post_init__(self):
        if self.log_file is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.log_file = Path(f"{self.name}_log_{timestamp}.jsonl")

    # =========================================================================
    # PREREQUISITE CHECKING
    # =========================================================================

    def check_env(self, required: list[str]) -> list[str]:
        """Check required environment variables.

        Returns list of missing vars.
        """
        missing = []
        for var in required:
            if not os.getenv(var):
                missing.append(var)
        return missing

    def check_models(self, required: list[str]) -> list[str]:
        """Check required models.

        Returns list of unavailable models.
        """
        unavailable = []
        for model in required:
            if not is_model_available(model):
                unavailable.append(model)
        return unavailable

    def check_paths(self, required: list[Path]) -> list[Path]:
        """Check required paths exist.

        Returns list of missing paths.
        """
        missing = []
        for path in required:
            if not path.exists():
                missing.append(path)
        return missing

    def check_all(
        self,
        required_env: list[str] | None = None,
        required_models: list[str] | None = None,
        required_paths: list[Path] | None = None,
    ) -> bool:
        """Check all prerequisites. Exits with code 1 if any fail.

        Returns True if all checks pass.
        """
        errors = []

        if required_env:
            missing = self.check_env(required_env)
            for var in missing:
                errors.append(f"Missing required env var: {var}")

        if required_models:
            unavailable = self.check_models(required_models)
            for model in unavailable:
                errors.append(f"Model not available: {model}")

        if required_paths:
            missing = self.check_paths(required_paths)
            for path in missing:
                errors.append(f"Path not found: {path}")

        if errors:
            logger.error("=" * 60)
            logger.error("FATAL: Prerequisites not met for %s", self.name)
            logger.error("=" * 60)
            for e in errors:
                logger.error("  x %s", e)
            logger.error("Exiting with code 1.")
            sys.exit(1)

        if self.verbose:
            logger.info("All prerequisites satisfied for %s", self.name)

        return True

    # =========================================================================
    # LOGGING
    # =========================================================================

    def _write_log(self, entry: dict):
        """Append entry to log file immediately."""
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            f.flush()

    @contextmanager
    def log_item(self, item: str):
        """Context manager for logging a single item."""
        self._current_item += 1
        if self._total_items > 0:
            pct = (self._current_item / self._total_items) * 100
            logger.info(
                "[%d/%d] (%5.1f%%) %s...",
                self._current_item,
                self._total_items,
                pct,
                safe_str(item)[:50],
            )
        else:
            logger.info("[%d] %s...", self._current_item, safe_str(item)[:50])

        entry = LogEntry(init=self, item=str(item))
        try:
            yield entry
        finally:
            if not entry._logged:
                entry.success()

    def set_total(self, total: int):
        """Set total items for progress tracking."""
        self._total_items = total

    # =========================================================================
    # SUMMARY
    # =========================================================================

    def summary(self) -> dict:
        """Print and return execution summary."""
        duration = time.time() - self._start_time

        summary = {
            "tool": self.name,
            "duration_seconds": round(duration, 2),
            "total": self._success_count + self._failed_count,
            "success": self._success_count,
            "failed": self._failed_count,
            "success_rate": round(
                self._success_count
                / max(1, self._success_count + self._failed_count)
                * 100,
                1,
            ),
            "log_file": str(self.log_file),
        }

        logger.info("=" * 60)
        logger.info("Summary: %s", self.name)
        logger.info("=" * 60)
        logger.info("  Duration: %.1fs", duration)
        logger.info("  Total: %d", summary["total"])
        logger.info("  Success: %d (%s%%)", summary["success"], summary["success_rate"])
        logger.info("  Failed: %d", summary["failed"])
        logger.info("  Log: %s", self.log_file)

        if self._failed_items:
            logger.warning("Failed items:")
            for item in self._failed_items[:10]:
                logger.warning("  x %s: %s", item["item"], item["code"])
            if len(self._failed_items) > 10:
                logger.warning("  ... and %d more", len(self._failed_items) - 10)

        # Write summary to log
        self._write_log({"type": "summary", **summary})

        return summary

    def exit_code(self) -> int:
        """Return appropriate exit code (0 if all success, 1 if any failed)."""
        return 0 if self._failed_count == 0 else 1


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================


def init_tool(
    name: str,
    required_models: list[str] | None = None,
    required_env: list[str] | None = None,
    required_paths: list[Path] | None = None,
    verbose: bool = False,
    log_file: Path | None = None,
) -> ToolInit:
    """Initialize a tool with prerequisite checking.

    Example:
        init = init_tool(
            name="my_evaluator",
            required_models=["local:phi4", "gh:gpt-4o-mini"],
            required_env=["GITHUB_TOKEN"],
        )

        init.set_total(len(items))
        for item in items:
            with init.log_item(item) as log:
                result = process(item)
                log.success(score=result)

        init.summary()
        sys.exit(init.exit_code())
    """
    init = ToolInit(name=name, verbose=verbose, log_file=log_file)
    init.check_all(
        required_env=required_env or [],
        required_models=required_models or [],
        required_paths=required_paths or [],
    )
    return init


# =============================================================================
# RETRY DECORATOR
# =============================================================================


def with_retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    transient_only: bool = True,
):
    """Decorator for retrying functions on transient errors.

    Example:
        @with_retry(max_attempts=3, delay=1.0)
        def call_model(prompt):
            return LLMClient.generate_text("gh:gpt-4o-mini", prompt)
    """

    def decorator(func: Callable):
        def wrapper(*args, **kwargs):
            last_error = None
            current_delay = delay

            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    error_code, should_retry = classify_error(str(e))

                    if transient_only and not should_retry:
                        raise  # Don't retry permanent errors

                    if attempt < max_attempts - 1:
                        logger.info(
                            "  [Retry %d/%d] %s: waiting %.1fs...",
                            attempt + 1,
                            max_attempts,
                            error_code,
                            current_delay,
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff

            raise last_error

        return wrapper

    return decorator


# =============================================================================
# CLI ENTRY POINT
# =============================================================================


def main():
    """Self-test and demo."""
    logger.info("Tool Init Module - Self Test")
    logger.info("=" * 40)

    # Test encoding fix
    logger.info("✓ Unicode test: 你好世界 🎉 émojis")

    # Test error classification
    test_errors = [
        "403 Forbidden",
        "Model not found",
        "429 Too Many Requests",
        "Connection refused",
    ]

    logger.info("\nError Classification:")
    for err in test_errors:
        code, retry = classify_error(err)
        logger.info(f"  '{err}' -> {code} (retry={retry})")

    # Test init (without actual model check)
    logger.info("\nTool Init Demo:")
    init = ToolInit(name="demo", verbose=True)
    init.set_total(3)

    for i in range(3):
        with init.log_item(f"item_{i}") as log:
            if i == 1:
                log.error("Simulated error", code=ErrorCode.PARSE_ERROR)
            else:
                log.success(score=95 - i * 5)

    init.summary()

    logger.info(f"\nLog file created: {init.log_file}")
    logger.info(f"Exit code would be: {init.exit_code()}")


if __name__ == "__main__":
    main()
