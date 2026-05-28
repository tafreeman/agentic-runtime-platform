"""OpenTelemetry Metrics API with Prometheus scrape endpoint.

This module provides opt-in OTEL metrics instrumentation with a Prometheus-
compatible /metrics endpoint for production scraping.

Metrics are disabled by default. Enable via ``AGENTIC_METRICS=1``.

All imports are guarded with ``try/except ImportError`` so the module degrades
gracefully to a no-op when ``opentelemetry-exporter-prometheus`` is not installed.

Environment variables:
    AGENTIC_METRICS: Set to "1" to enable metrics (default: disabled)
    OTEL_SERVICE_NAME: Service name label on all metrics (default: agentic-workflows-v2)
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# Re-use the service name constant from the tracing module
DEFAULT_SERVICE_NAME = "agentic-workflows-v2"

_TRUTHY_VALUES = frozenset({"1", "true", "yes"})


def _truthy_env(name: str) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return False
    return raw.strip().lower() in _TRUTHY_VALUES


def is_metrics_enabled() -> bool:
    """Return True when metrics collection is enabled via environment variable."""
    return _truthy_env("AGENTIC_METRICS")


def get_service_name() -> str:
    """Return the OTEL service name from environment or default."""
    raw = os.environ.get("OTEL_SERVICE_NAME")
    if raw is None:
        return DEFAULT_SERVICE_NAME
    stripped = raw.strip()
    return stripped or DEFAULT_SERVICE_NAME


# ---------------------------------------------------------------------------
# OTEL Metrics SDK — all imports are optional
# ---------------------------------------------------------------------------

try:
    from opentelemetry import metrics as _otel_metrics
    from opentelemetry.sdk.metrics import MeterProvider as _MeterProvider
    from opentelemetry.sdk.resources import Resource as _Resource

    _OTEL_METRICS_AVAILABLE = True
except ImportError:
    _OTEL_METRICS_AVAILABLE = False
    _otel_metrics = None  # type: ignore[assignment]
    _MeterProvider = None  # type: ignore[assignment]
    _Resource = None  # type: ignore[assignment]

try:
    from opentelemetry.exporter.prometheus import PrometheusMetricReader as _PrometheusReader

    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False
    _PrometheusReader = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Module-level meter provider and instruments — populated by _setup_metrics()
# ---------------------------------------------------------------------------

_meter_provider: Any = None
_meter: Any = None

# Histograms
_http_request_duration: Any = None
_llm_request_duration: Any = None

# Counters
_circuit_breaker_trips: Any = None
_llm_tokens: Any = None
_http_requests: Any = None

# Gauges (UpDownCounter used as gauge — OTEL SDK gauge is synchronous/observable)
_active_workflows: Any = None
_circuit_breaker_state: Any = None


# ---------------------------------------------------------------------------
# Path normalisation — strip variable segments from URL paths so high-
# cardinality run IDs do not create a unique label per request.
# ---------------------------------------------------------------------------

_PATH_PARAM_PATTERN = re.compile(r"/[0-9a-f\-]{8,}|/\d+")


def normalize_path(path: str) -> str:
    """Replace numeric IDs and UUID-like segments with ``{id}``.

    Examples::

        /api/runs/abc12345-1234-1234-1234-abcdef012345  →  /api/runs/{id}
        /api/runs/42                                     →  /api/runs/{id}
        /api/health                                      →  /api/health
    """
    return _PATH_PARAM_PATTERN.sub("/{id}", path)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def _setup_metrics() -> bool:
    """Initialise the OTEL MeterProvider with a Prometheus reader.

    Returns:
        True if initialisation succeeded, False otherwise.
    """
    global _meter_provider, _meter
    global _http_request_duration, _llm_request_duration
    global _circuit_breaker_trips, _llm_tokens, _http_requests
    global _active_workflows, _circuit_breaker_state

    if not _OTEL_METRICS_AVAILABLE:
        logger.warning(
            "OpenTelemetry metrics SDK not installed. "
            "Install with: pip install opentelemetry-sdk"
        )
        return False

    if not _PROMETHEUS_AVAILABLE:
        logger.warning(
            "Prometheus exporter not installed. "
            "Install with: pip install opentelemetry-exporter-prometheus"
        )
        return False

    service_name = get_service_name()
    resource = _Resource.create(
        {
            "service.name": service_name,
            "service.version": "0.1.0",
        }
    )

    reader = _PrometheusReader()
    _meter_provider = _MeterProvider(resource=resource, metric_readers=[reader])
    _otel_metrics.set_meter_provider(_meter_provider)

    _meter = _meter_provider.get_meter(service_name, version="0.1.0")

    # ----- Histograms --------------------------------------------------------

    _http_request_duration = _meter.create_histogram(
        name="http_request_duration_seconds",
        description="HTTP request latency in seconds",
        unit="s",
    )

    _llm_request_duration = _meter.create_histogram(
        name="llm_request_duration_seconds",
        description="LLM API call latency in seconds",
        unit="s",
    )

    # ----- Counters ----------------------------------------------------------

    _circuit_breaker_trips = _meter.create_counter(
        name="circuit_breaker_trips_total",
        description="Total number of circuit breaker trips by provider and state",
        unit="1",
    )

    _llm_tokens = _meter.create_counter(
        name="llm_tokens_total",
        description="Total LLM tokens consumed by provider and direction",
        unit="1",
    )

    _http_requests = _meter.create_counter(
        name="http_requests_total",
        description="Total HTTP requests by method, path, and status code",
        unit="1",
    )

    # ----- UpDownCounters (used as gauges for mutable values) ----------------

    _active_workflows = _meter.create_up_down_counter(
        name="active_workflows",
        description="Number of currently running workflow executions",
        unit="1",
    )

    _circuit_breaker_state = _meter.create_up_down_counter(
        name="circuit_breaker_state",
        description=(
            "Circuit breaker state by provider: "
            "0=closed (healthy), 1=open (tripped), 2=half_open (probing)"
        ),
        unit="1",
    )

    logger.info(
        "OpenTelemetry metrics initialized (Prometheus exporter): service=%s",
        service_name,
    )
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_meter() -> Any:
    """Return the configured OTEL meter, or None if metrics are not available."""
    global _meter_provider
    if _meter is not None:
        return _meter
    if not is_metrics_enabled():
        return None
    if _meter_provider is None:
        _setup_metrics()
    return _meter


def get_metrics_app() -> Any | None:
    """Return a Starlette/ASGI app serving the Prometheus /metrics endpoint.

    Returns ``None`` when the Prometheus SDK is not installed or metrics are
    not enabled, so callers can skip mounting the endpoint gracefully.
    """
    if not is_metrics_enabled():
        return None
    if not _PROMETHEUS_AVAILABLE:
        return None

    # Ensure the provider is set up (idempotent)
    if _meter_provider is None:
        ok = _setup_metrics()
        if not ok:
            return None

    try:
        from prometheus_client import REGISTRY, make_asgi_app

        return make_asgi_app(registry=REGISTRY)
    except ImportError:
        logger.warning(
            "prometheus_client not available. "
            "The opentelemetry-exporter-prometheus package bundles it; "
            "ensure it is installed."
        )
        return None


# ---------------------------------------------------------------------------
# Convenience recorders — all no-op when metrics are disabled
# ---------------------------------------------------------------------------


def record_http_request(
    method: str,
    path: str,
    status_code: int,
    duration_seconds: float,
) -> None:
    """Record an HTTP request duration and increment the request counter.

    Safe to call even when metrics are not enabled — all operations are no-ops
    when the instruments are ``None``.
    """
    if _http_request_duration is None and _http_requests is None:
        return
    normalized = normalize_path(path)
    attributes = {
        "http.method": method.upper(),
        "http.route": normalized,
        "http.status_code": str(status_code),
    }
    if _http_request_duration is not None:
        _http_request_duration.record(duration_seconds, attributes)
    if _http_requests is not None:
        _http_requests.add(1, attributes)


def record_llm_request(
    provider: str,
    duration_seconds: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    """Record an LLM API call duration and token consumption."""
    if _llm_request_duration is None and _llm_tokens is None:
        return
    if _llm_request_duration is not None:
        _llm_request_duration.record(
            duration_seconds, {"llm.provider": provider}
        )
    if _llm_tokens is not None and input_tokens > 0:
        _llm_tokens.add(input_tokens, {"llm.provider": provider, "direction": "input"})
    if _llm_tokens is not None and output_tokens > 0:
        _llm_tokens.add(output_tokens, {"llm.provider": provider, "direction": "output"})


def record_circuit_breaker_trip(provider: str, state: str) -> None:
    """Increment the circuit breaker trips counter.

    Args:
        provider: The model/provider key (e.g. ``"openai"``, ``"anthropic"``).
        state: The new circuit state after the trip (e.g. ``"open"``, ``"half_open"``).
    """
    if _circuit_breaker_trips is None:
        return
    _circuit_breaker_trips.add(1, {"provider": provider, "state": state})


def record_active_workflows_delta(delta: int) -> None:
    """Adjust the active workflow gauge by *delta* (+1 on start, -1 on end)."""
    if _active_workflows is None:
        return
    _active_workflows.add(delta)


def set_circuit_breaker_state(provider: str, state_value: int) -> None:
    """Update the circuit breaker state gauge for a provider.

    Args:
        provider: Provider/model key.
        state_value: 0=closed, 1=open, 2=half_open.
    """
    if _circuit_breaker_state is None:
        return
    # UpDownCounter: emit the absolute value each call (caller manages sign)
    _circuit_breaker_state.add(state_value, {"provider": provider})


def shutdown_metrics() -> None:
    """Flush and shut down the metrics provider."""
    global _meter_provider

    if _meter_provider is None:
        return
    try:
        if hasattr(_meter_provider, "shutdown"):
            _meter_provider.shutdown()
        logger.info("OpenTelemetry metrics shutdown complete")
    except Exception as exc:
        logger.warning("Error during metrics shutdown: %s", exc)
    finally:
        _meter_provider = None
