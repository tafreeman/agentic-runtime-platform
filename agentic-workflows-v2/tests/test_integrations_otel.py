"""Tests for agentic_v2.integrations.otel tracing setup.

ADR-008 Phase 3 — Tier 1 (branching, error paths) and Tier 2 (contracts,
boundaries) tests for the OpenTelemetry integration module.

All OTEL SDK imports are mocked; no real tracer provider is created.
Environment variables are patched per-test for isolation.

NOTE: test_workflow_tracing.py already covers:
  - is_tracing_enabled() with 0/1/true values
  - create_trace_adapter() returning NullTraceAdapter when disabled
  - OtelTraceAdapter emit/sanitize/span lifecycle
This file tests the remaining untested paths: sensitive capture,
protocol branching, shutdown, get_tracer caching, HTTP endpoint suffix,
_setup_otel_tracer import failures, and service name configuration.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

# Import the module under test (not individual functions) so we can
# patch the module-level _tracer_instance.
import agentic_v2.integrations.otel as otel_mod
import pytest
from agentic_v2.integrations.otel import (
    DEFAULT_OTLP_ENDPOINT,
    DEFAULT_SERVICE_NAME,
    get_otlp_endpoint,
    get_otlp_protocol,
    get_service_name,
    is_sensitive_capture_enabled,
    is_tracing_enabled,
)

# ---------------------------------------------------------------------------
# Environment helper readers
# ---------------------------------------------------------------------------


class TestIsSensitiveCaptureEnabled:
    """Tests for is_sensitive_capture_enabled()."""

    @pytest.mark.parametrize(
        "env_value,expected",
        [
            ("1", True),
            ("true", True),
            ("yes", True),
            ("0", False),
            ("false", False),
            ("no", False),
            ("", False),
        ],
        ids=["one", "true", "yes", "zero", "false", "no", "empty"],
    )
    def test_sensitive_capture_values(self, env_value, expected):
        """ADR-008 Phase 3: sensitive capture follows same truthy pattern as tracing."""
        with patch.dict(
            os.environ, {"AGENTIC_TRACE_SENSITIVE": env_value}, clear=False
        ):
            assert is_sensitive_capture_enabled() is expected

    def test_sensitive_capture_unset(self):
        """ADR-008 Phase 3: unset env var means sensitive capture disabled."""
        env = dict(os.environ)
        env.pop("AGENTIC_TRACE_SENSITIVE", None)
        with patch.dict(os.environ, env, clear=True):
            assert is_sensitive_capture_enabled() is False


class TestGetOtlpEndpoint:
    """Tests for get_otlp_endpoint()."""

    def test_returns_default_when_unset(self):
        """ADR-008 Phase 3: default endpoint is localhost:4317."""
        env = dict(os.environ)
        env.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
        with patch.dict(os.environ, env, clear=True):
            assert get_otlp_endpoint() == DEFAULT_OTLP_ENDPOINT

    def test_returns_custom_endpoint(self):
        """ADR-008 Phase 3: custom endpoint from env var."""
        with patch.dict(
            os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4317"}
        ):
            assert get_otlp_endpoint() == "http://collector:4317"

    def test_strips_whitespace(self):
        """ADR-008 Phase 3: endpoint value is stripped of whitespace."""
        with patch.dict(
            os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "  http://x:4317  "}
        ):
            assert get_otlp_endpoint() == "http://x:4317"


class TestGetOtlpProtocol:
    """Tests for get_otlp_protocol()."""

    def test_default_is_grpc(self):
        """ADR-008 Phase 3: default protocol is grpc."""
        env = dict(os.environ)
        env.pop("OTEL_EXPORTER_OTLP_PROTOCOL", None)
        with patch.dict(os.environ, env, clear=True):
            assert get_otlp_protocol() == "grpc"

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("grpc", "grpc"),
            ("http/protobuf", "http/protobuf"),
            ("GRPC", "grpc"),
            ("  HTTP/PROTOBUF  ", "http/protobuf"),
        ],
        ids=["grpc", "http", "uppercase-grpc", "padded-http"],
    )
    def test_normalizes_protocol(self, raw, expected):
        """ADR-008 Phase 3: protocol is lowercased and stripped."""
        with patch.dict(os.environ, {"OTEL_EXPORTER_OTLP_PROTOCOL": raw}):
            assert get_otlp_protocol() == expected


class TestGetServiceName:
    """Tests for get_service_name()."""

    def test_default_service_name(self):
        """ADR-008 Phase 3: default service name matches constant."""
        env = dict(os.environ)
        env.pop("OTEL_SERVICE_NAME", None)
        with patch.dict(os.environ, env, clear=True):
            assert get_service_name() == DEFAULT_SERVICE_NAME

    def test_custom_service_name(self):
        """ADR-008 Phase 3: custom service name from env."""
        with patch.dict(os.environ, {"OTEL_SERVICE_NAME": "my-service"}):
            assert get_service_name() == "my-service"


# ---------------------------------------------------------------------------
# _setup_otel_tracer
# ---------------------------------------------------------------------------


class TestSetupOtelTracer:
    """Tests for _setup_otel_tracer() import and configuration branches."""

    def test_raises_import_error_when_sdk_missing(self):
        """ADR-008 Phase 3: ImportError raised when opentelemetry SDK not installed."""
        with (
            patch.dict(
                "sys.modules",
                {"opentelemetry": None, "opentelemetry.trace": None},
            ),
            pytest.raises(ImportError, match="tracing"),
        ):
            otel_mod._setup_otel_tracer()

    def test_grpc_exporter_import_error(self):
        """ADR-008 Phase 3: ImportError raised when gRPC exporter not installed."""
        mock_trace = MagicMock()
        mock_resource = MagicMock()
        mock_sdk_trace = MagicMock()

        with patch.dict(os.environ, {"OTEL_EXPORTER_OTLP_PROTOCOL": "grpc"}):
            with patch.dict(
                "sys.modules",
                {
                    "opentelemetry": MagicMock(trace=mock_trace),
                    "opentelemetry.trace": mock_trace,
                    "opentelemetry.sdk": MagicMock(),
                    "opentelemetry.sdk.resources": mock_resource,
                    "opentelemetry.sdk.trace": mock_sdk_trace,
                    "opentelemetry.sdk.trace.export": MagicMock(),
                    "opentelemetry.exporter": MagicMock(),
                    "opentelemetry.exporter.otlp": MagicMock(),
                    "opentelemetry.exporter.otlp.proto": MagicMock(),
                    "opentelemetry.exporter.otlp.proto.grpc": MagicMock(),
                    "opentelemetry.exporter.otlp.proto.grpc.trace_exporter": None,
                },
            ):
                with pytest.raises(ImportError, match="gRPC OTLP exporter"):
                    otel_mod._setup_otel_tracer()

    def test_http_exporter_import_error(self):
        """ADR-008 Phase 3: ImportError raised when HTTP exporter not installed."""
        mock_trace = MagicMock()
        mock_resource = MagicMock()
        mock_sdk_trace = MagicMock()

        with patch.dict(os.environ, {"OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf"}):
            with patch.dict(
                "sys.modules",
                {
                    "opentelemetry": MagicMock(trace=mock_trace),
                    "opentelemetry.trace": mock_trace,
                    "opentelemetry.sdk": MagicMock(),
                    "opentelemetry.sdk.resources": mock_resource,
                    "opentelemetry.sdk.trace": mock_sdk_trace,
                    "opentelemetry.sdk.trace.export": MagicMock(),
                    "opentelemetry.exporter": MagicMock(),
                    "opentelemetry.exporter.otlp": MagicMock(),
                    "opentelemetry.exporter.otlp.proto": MagicMock(),
                    "opentelemetry.exporter.otlp.proto.http": MagicMock(),
                    "opentelemetry.exporter.otlp.proto.http.trace_exporter": None,
                },
            ):
                with pytest.raises(ImportError, match="HTTP OTLP exporter"):
                    otel_mod._setup_otel_tracer()


# ---------------------------------------------------------------------------
# get_tracer
# ---------------------------------------------------------------------------


class TestGetTracer:
    """Tests for the cached get_tracer() accessor."""

    def setup_method(self):
        """Reset module-level singleton before each test."""
        otel_mod._tracer_instance = None

    def teardown_method(self):
        """Clean up module-level singleton after each test."""
        otel_mod._tracer_instance = None

    def test_returns_none_when_tracing_disabled(self):
        """ADR-008 Phase 3: get_tracer returns None when AGENTIC_TRACING unset."""
        env = dict(os.environ)
        env.pop("AGENTIC_TRACING", None)
        with patch.dict(os.environ, env, clear=True):
            assert otel_mod.get_tracer() is None

    def test_returns_cached_instance(self):
        """ADR-008 Phase 3: get_tracer returns cached tracer on second call."""
        sentinel = object()
        otel_mod._tracer_instance = sentinel
        with patch.dict(os.environ, {"AGENTIC_TRACING": "1"}):
            assert otel_mod.get_tracer() is sentinel

    def test_returns_none_on_import_failure(self):
        """ADR-008 Phase 3: get_tracer returns None when _setup_otel_tracer fails."""
        with (
            patch.dict(os.environ, {"AGENTIC_TRACING": "1"}),
            patch.object(
                otel_mod,
                "_setup_otel_tracer",
                side_effect=ImportError("no sdk"),
            ),
        ):
            assert otel_mod.get_tracer() is None
            # _tracer_instance should remain None (not cached)
            assert otel_mod._tracer_instance is None


# ---------------------------------------------------------------------------
# create_trace_adapter
# ---------------------------------------------------------------------------


class TestCreateTraceAdapter:
    """Tests for the create_trace_adapter() factory."""

    def setup_method(self):
        otel_mod._tracer_instance = None

    def teardown_method(self):
        otel_mod._tracer_instance = None

    def test_returns_null_adapter_when_disabled(self):
        """ADR-008 Phase 3: NullTraceAdapter when tracing is off."""
        from agentic_v2.integrations.tracing import NullTraceAdapter

        env = dict(os.environ)
        env.pop("AGENTIC_TRACING", None)
        with patch.dict(os.environ, env, clear=True):
            adapter = otel_mod.create_trace_adapter()
            assert isinstance(adapter, NullTraceAdapter)

    def test_returns_null_adapter_when_tracer_is_none(self):
        """ADR-008 Phase 3: NullTraceAdapter when OTEL setup fails."""
        from agentic_v2.integrations.tracing import NullTraceAdapter

        with patch.dict(os.environ, {"AGENTIC_TRACING": "1"}):
            with patch.object(otel_mod, "get_tracer", return_value=None):
                adapter = otel_mod.create_trace_adapter()
                assert isinstance(adapter, NullTraceAdapter)

    def test_returns_otel_adapter_when_tracer_available(self):
        """ADR-008 Phase 3: OtelTraceAdapter when tracer is available."""
        from agentic_v2.integrations.tracing import OtelTraceAdapter

        mock_tracer = MagicMock()
        env = {"AGENTIC_TRACING": "1"}
        env_cleared = dict(os.environ)
        env_cleared.pop("AGENTIC_TRACE_SENSITIVE", None)
        env_cleared.update(env)
        with patch.dict(os.environ, env_cleared, clear=True):
            with patch.object(otel_mod, "get_tracer", return_value=mock_tracer):
                adapter = otel_mod.create_trace_adapter()
                assert isinstance(adapter, OtelTraceAdapter)
                assert adapter._capture_sensitive is False

    def test_sensitive_capture_forwarded_to_adapter(self):
        """ADR-008 Phase 3: sensitive flag propagated to OtelTraceAdapter."""
        from agentic_v2.integrations.tracing import OtelTraceAdapter

        mock_tracer = MagicMock()
        env = {"AGENTIC_TRACING": "1", "AGENTIC_TRACE_SENSITIVE": "1"}
        with patch.dict(os.environ, env, clear=False):
            with patch.object(otel_mod, "get_tracer", return_value=mock_tracer):
                adapter = otel_mod.create_trace_adapter()
                assert isinstance(adapter, OtelTraceAdapter)
                assert adapter._capture_sensitive is True


# ---------------------------------------------------------------------------
# shutdown_tracing
# ---------------------------------------------------------------------------


class TestShutdownTracing:
    """Tests for shutdown_tracing()."""

    def setup_method(self):
        otel_mod._tracer_instance = None

    def teardown_method(self):
        otel_mod._tracer_instance = None

    def test_noop_when_no_tracer(self):
        """ADR-008 Phase 3: shutdown_tracing is safe when no tracer exists."""
        otel_mod._tracer_instance = None
        otel_mod.shutdown_tracing()  # should not raise
        assert otel_mod._tracer_instance is None

    def test_calls_provider_shutdown(self):
        """ADR-008 Phase 3: shutdown_tracing calls provider.shutdown()."""
        mock_provider = MagicMock()
        mock_provider.shutdown = MagicMock()
        mock_trace_mod = MagicMock()
        mock_trace_mod.get_tracer_provider.return_value = mock_provider

        otel_mod._tracer_instance = MagicMock()  # non-None so we enter the block
        with patch.dict(
            "sys.modules",
            {
                "opentelemetry": MagicMock(trace=mock_trace_mod),
                "opentelemetry.trace": mock_trace_mod,
            },
        ):
            otel_mod.shutdown_tracing()

        mock_provider.shutdown.assert_called_once()
        assert otel_mod._tracer_instance is None

    def test_clears_tracer_on_exception(self):
        """ADR-008 Phase 3: _tracer_instance is cleared even if shutdown raises."""
        mock_trace_mod = MagicMock()
        mock_trace_mod.get_tracer_provider.side_effect = RuntimeError("shutdown boom")

        otel_mod._tracer_instance = MagicMock()
        with patch.dict(
            "sys.modules",
            {
                "opentelemetry": MagicMock(trace=mock_trace_mod),
                "opentelemetry.trace": mock_trace_mod,
            },
        ):
            otel_mod.shutdown_tracing()  # should not raise

        assert otel_mod._tracer_instance is None

    def test_provider_without_shutdown_attribute(self):
        """ADR-008 Phase 3: graceful when provider lacks shutdown method."""
        mock_provider = MagicMock(spec=[])  # no shutdown attr
        mock_trace_mod = MagicMock()
        mock_trace_mod.get_tracer_provider.return_value = mock_provider

        otel_mod._tracer_instance = MagicMock()
        with patch.dict(
            "sys.modules",
            {
                "opentelemetry": MagicMock(trace=mock_trace_mod),
                "opentelemetry.trace": mock_trace_mod,
            },
        ):
            otel_mod.shutdown_tracing()

        assert otel_mod._tracer_instance is None


# ---------------------------------------------------------------------------
# is_tracing_enabled (supplementary to test_workflow_tracing.py)
# ---------------------------------------------------------------------------


class TestIsTracingEnabledSupplementary:
    """Supplementary tests not covered in test_workflow_tracing.py."""

    def test_tracing_enabled_with_yes(self):
        """ADR-008 Phase 3: AGENTIC_TRACING=yes enables tracing."""
        with patch.dict(os.environ, {"AGENTIC_TRACING": "yes"}):
            assert is_tracing_enabled() is True

    def test_tracing_with_whitespace_padding(self):
        """ADR-008 Phase 3: whitespace around value is stripped."""
        with patch.dict(os.environ, {"AGENTIC_TRACING": "  1  "}):
            assert is_tracing_enabled() is True

    def test_tracing_disabled_with_random_string(self):
        """ADR-008 Phase 3: arbitrary strings do not enable tracing."""
        with patch.dict(os.environ, {"AGENTIC_TRACING": "enabled"}):
            assert is_tracing_enabled() is False
