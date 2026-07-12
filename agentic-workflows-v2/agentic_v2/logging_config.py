"""Logging configuration for agentic-workflows-v2.

Provides :func:`configure_logging`, which sets up the root logger with either
a human-readable text formatter or a JSON formatter (via ``python-json-logger``)
depending on the ``log_format`` argument.

Typical usage (called once at application startup)::

    from agentic_v2.logging_config import configure_logging
    from agentic_v2.settings import get_settings

    configure_logging(log_format=get_settings().log_format)

The ``LOG_FORMAT`` environment variable (exposed via :class:`~agentic_v2.settings.Settings`)
controls which formatter is active at runtime:

* ``LOG_FORMAT=json``  — structured JSON output, one object per line.
* ``LOG_FORMAT=text``  — human-readable ``asctime level name: message`` format (default).

All output is written to **stdout** for compatibility with cloud log aggregators
(e.g. CloudWatch, GCP Logging, Datadog).
"""

from __future__ import annotations

import logging
import sys
from typing import Any

_SERVICE_NAME = "agentic-workflows-v2"

_TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# Fields included in JSON output when python-json-logger is available.
# Use standard LogRecord attribute names here; rename_fields handles the final key names.
_JSON_FORMAT_FIELDS = (
    "%(asctime)s %(levelname)s %(name)s %(message)s %(module)s %(funcName)s %(lineno)s"
)


def configure_logging(log_format: str = "text", level: int = logging.INFO) -> None:
    """Configure the root logger for the application.

    Parameters
    ----------
    log_format:
        ``"text"`` (default) for human-readable output or ``"json"`` for
        structured JSON output.  Any unrecognised value falls back to
        ``"text"`` with a warning.
    level:
        Log level applied to the root logger (default ``logging.INFO``).
    """
    root = logging.getLogger()
    root.setLevel(level)

    # Remove any handlers previously attached (e.g. from a prior basicConfig call)
    # so we don't end up with duplicate log lines.
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    if log_format == "json":
        formatter = _build_json_formatter()
    else:
        if log_format not in {"text", "json"}:
            logging.warning(
                "configure_logging: unrecognised log_format=%r; using 'text'.",
                log_format,
            )
        formatter = logging.Formatter(_TEXT_FORMAT)

    handler.setFormatter(formatter)
    root.addHandler(handler)


def _build_json_formatter() -> logging.Formatter:
    """Return a JSON formatter, falling back to text on import failure."""
    try:
        from pythonjsonlogger.json import JsonFormatter  # type: ignore[import-untyped]

        class _AgenticJsonFormatter(JsonFormatter):  # type: ignore[misc]
            """JsonFormatter subclass that injects a static ``service`` field."""

            def add_fields(
                self,
                log_record: dict[str, Any],
                record: logging.LogRecord,
                message_dict: dict[str, Any],
            ) -> None:
                super().add_fields(log_record, record, message_dict)
                log_record.setdefault("service", _SERVICE_NAME)

        return _AgenticJsonFormatter(
            _JSON_FORMAT_FIELDS,
            rename_fields={
                "asctime": "timestamp",
                "levelname": "level",
            },
        )

    except ImportError:
        logging.warning(
            "python-json-logger is not installed; falling back to text format. "
            "Install it with: pip install python-json-logger"
        )
        return logging.Formatter(_TEXT_FORMAT)
