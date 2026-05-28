"""Integrations with external frameworks."""

from __future__ import annotations

from .base import CanonicalEvent, TraceAdapter
from .otel import (
    create_trace_adapter,
    get_tracer,
    is_sensitive_capture_enabled,
    is_tracing_enabled,
    shutdown_tracing,
)
from .tracing import (
    CompositeTraceAdapter,
    ConsoleTraceAdapter,
    FileTraceAdapter,
    NullTraceAdapter,
    OtelTraceAdapter,
)

__all__ = [
    "CanonicalEvent",
    "CompositeTraceAdapter",
    "ConsoleTraceAdapter",
    "FileTraceAdapter",
    "NullTraceAdapter",
    "OtelTraceAdapter",
    "TraceAdapter",
    "create_trace_adapter",
    "get_tracer",
    "is_sensitive_capture_enabled",
    "is_tracing_enabled",
    "shutdown_tracing",
]
