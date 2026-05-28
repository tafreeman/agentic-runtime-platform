"""OpenTelemetry setup for AI Toolkit tracing.

This module provides opt-in OTLP tracing aligned with VS Code AI Toolkit.
Tracing is disabled by default and enabled via environment variables.

Environment variables:
    AGENTIC_TRACING: Set to "1" to enable tracing (default: disabled)
    AGENTIC_TRACE_SENSITIVE: Set to "1" to include prompt/response content (default: redacted)
    OTEL_EXPORTER_OTLP_ENDPOINT: OTLP endpoint (default: http://localhost:4317 for gRPC)
    OTEL_EXPORTER_OTLP_PROTOCOL: "grpc" or "http/protobuf" (default: grpc)
    OTEL_SERVICE_NAME: Service name for traces (default: agentic-workflows-v2)
"""

from __future__ import annotations

import logging
import os
from typing import Any

from .base import TraceAdapter
from .tracing import NullTraceAdapter

logger = logging.getLogger(__name__)

# Module-level defaults — exported so callers and tests can refer to the same
# canonical values without depending on the cached Settings singleton.
DEFAULT_OTLP_ENDPOINT = "http://localhost:4317"
DEFAULT_OTLP_PROTOCOL = "grpc"
DEFAULT_SERVICE_NAME = "agentic-workflows-v2"

_TRUTHY_VALUES = frozenset({"1", "true", "yes"})


def _truthy_env(name: str) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return False
    return raw.strip().lower() in _TRUTHY_VALUES


def is_tracing_enabled() -> bool:
    """Check if tracing is enabled via environment variable."""
    return _truthy_env("AGENTIC_TRACING")


def is_sensitive_capture_enabled() -> bool:
    """Check if sensitive data capture (prompts/responses) is enabled."""
    return _truthy_env("AGENTIC_TRACE_SENSITIVE")


def get_otlp_endpoint() -> str:
    """Get the OTLP exporter endpoint from environment or default."""
    raw = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if raw is None:
        return DEFAULT_OTLP_ENDPOINT
    stripped = raw.strip()
    return stripped or DEFAULT_OTLP_ENDPOINT


def get_otlp_protocol() -> str:
    """Get the OTLP protocol (grpc or http/protobuf)."""
    raw = os.environ.get("OTEL_EXPORTER_OTLP_PROTOCOL")
    if raw is None:
        return DEFAULT_OTLP_PROTOCOL
    normalized = raw.strip().lower()
    return normalized or DEFAULT_OTLP_PROTOCOL


def get_service_name() -> str:
    """Get the service name for traces."""
    raw = os.environ.get("OTEL_SERVICE_NAME")
    if raw is None:
        return DEFAULT_SERVICE_NAME
    stripped = raw.strip()
    return stripped or DEFAULT_SERVICE_NAME


def _setup_otel_tracer() -> Any:
    """Initialize OpenTelemetry tracer provider and exporter.

    Returns the tracer instance or None if setup fails.
    """
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        logger.warning(
            "OpenTelemetry SDK not installed. Install with: "
            "pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc"
        )
        raise ImportError(
            "OpenTelemetry tracing requires the 'tracing' extra. "
            "Install with: pip install agentic-workflows-v2[tracing]"
        ) from exc

    protocol = get_otlp_protocol()
    endpoint = get_otlp_endpoint()

    # Create exporter based on protocol
    if protocol == "grpc":
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
        except ImportError as exc:
            raise ImportError(
                "gRPC OTLP exporter not installed. Install with: "
                "pip install opentelemetry-exporter-otlp-proto-grpc"
            ) from exc
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    else:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
        except ImportError as exc:
            raise ImportError(
                "HTTP OTLP exporter not installed. Install with: "
                "pip install opentelemetry-exporter-otlp-proto-http"
            ) from exc
        # HTTP endpoint typically needs /v1/traces suffix
        http_endpoint = endpoint
        if not http_endpoint.endswith("/v1/traces"):
            http_endpoint = http_endpoint.rstrip("/") + "/v1/traces"
        exporter = OTLPSpanExporter(endpoint=http_endpoint)

    # Create resource with service name
    resource = Resource.create(
        {
            "service.name": get_service_name(),
            "service.version": "0.1.0",
        }
    )

    # Create and set tracer provider
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    logger.info(
        "OpenTelemetry tracing initialized: endpoint=%s, protocol=%s, service=%s",
        endpoint,
        protocol,
        get_service_name(),
    )

    return trace.get_tracer(get_service_name())


_tracer_instance: Any = None


def get_tracer() -> Any:
    """Get or create the OpenTelemetry tracer instance.

    Returns None if tracing is disabled or setup fails.
    """
    global _tracer_instance

    if not is_tracing_enabled():
        return None

    if _tracer_instance is None:
        try:
            _tracer_instance = _setup_otel_tracer()
        except ImportError:
            logger.warning("Failed to initialize OpenTelemetry tracer")
            return None

    return _tracer_instance


def create_trace_adapter() -> TraceAdapter:
    """Create the appropriate trace adapter based on environment configuration.

    Returns:
        OtelTraceAdapter if tracing is enabled and OTEL is available,
        otherwise NullTraceAdapter.
    """
    if not is_tracing_enabled():
        logger.debug("Tracing disabled (set AGENTIC_TRACING=1 to enable)")
        return NullTraceAdapter()

    tracer = get_tracer()
    if tracer is None:
        logger.warning(
            "Tracing enabled but OTEL setup failed; falling back to NullTraceAdapter"
        )
        return NullTraceAdapter()

    # Import here to avoid circular dependency
    from .tracing import OtelTraceAdapter

    capture_sensitive = is_sensitive_capture_enabled()
    logger.info(
        "Creating OtelTraceAdapter (sensitive_capture=%s)",
        capture_sensitive,
    )
    return OtelTraceAdapter(tracer=tracer, capture_sensitive=capture_sensitive)


def shutdown_tracing() -> None:
    """Shutdown the tracer provider and flush pending spans."""
    global _tracer_instance

    if _tracer_instance is None:
        return

    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        if hasattr(provider, "shutdown"):
            provider.shutdown()
        logger.info("OpenTelemetry tracing shutdown complete")
    except Exception as exc:
        logger.warning("Error during tracing shutdown: %s", exc)
    finally:
        _tracer_instance = None
