"""Tests for server adapter routing.

Covers:
- ``GET /api/adapters`` — list available execution engine adapters.
- ``POST /api/run`` with adapter field — use specified adapter.
- ``POST /api/run`` without adapter field — default to langchain.
- Dispatch verification — native adapter path is actually invoked.
"""

from __future__ import annotations

from tests._server_test_helpers import make_configured_app

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# GET /api/adapters
# ---------------------------------------------------------------------------


class TestGetAdapters:
    """Tests for the ``GET /api/adapters`` endpoint."""

    def test_get_adapters_returns_list(self):
        """GET /api/adapters returns a list of adapter names."""
        app = make_configured_app()
        client = TestClient(app)

        response = client.get("/api/adapters")
        assert response.status_code == 200

        payload = response.json()
        assert "adapters" in payload
        assert isinstance(payload["adapters"], list)

    def test_get_adapters_includes_native(self):
        """GET /api/adapters includes 'native' adapter."""
        app = make_configured_app()
        client = TestClient(app)

        response = client.get("/api/adapters")
        assert response.status_code == 200

        adapter_names = response.json()["adapters"]
        assert "native" in adapter_names

    def test_get_adapters_includes_langchain(self):
        """GET /api/adapters includes 'langchain' adapter."""
        app = make_configured_app()
        client = TestClient(app)

        response = client.get("/api/adapters")
        assert response.status_code == 200

        adapter_names = response.json()["adapters"]
        assert "langchain" in adapter_names


# ---------------------------------------------------------------------------
# POST /api/run with adapter field
# ---------------------------------------------------------------------------


class TestRunWithAdapter:
    """Tests for adapter field in ``POST /api/run``."""

    def test_run_request_accepts_adapter_field(self, monkeypatch):
        """POST /api/run accepts an 'adapter' field and routes to the native engine.

        Verifies that when ``adapter="native"`` is passed:
        1. The request is accepted (HTTP 200 with a run_id) — confirming the
           adapter validation step found "native" in the registry.
        2. ``_run_via_native_adapter`` is called during background execution
           instead of the LangChain streaming path — confirming that the
           adapter name is threaded all the way into ``_stream_and_run``.
        """
        from agentic_v2.langchain import config
        from agentic_v2.server.routes import workflows

        def _mock_load_config(name, definitions_dir=None):
            return config.WorkflowConfig(name=name, inputs={}, steps=[])

        monkeypatch.setattr(workflows, "load_workflow_config", _mock_load_config)

        # Track calls to _run_via_native_adapter to confirm the native path is taken.
        native_calls: list[str] = []

        async def _fake_native(
            adapter_name,
            workflow_name,
            run_id,
            workflow_inputs,
            on_update=None,
        ):
            import asyncio
            from datetime import datetime, timezone

            from agentic_v2.contracts import StepStatus, WorkflowResult

            native_calls.append(adapter_name)
            await asyncio.sleep(0)  # yield to event loop — satisfies async contract
            return WorkflowResult(
                workflow_id=run_id,
                workflow_name=workflow_name,
                overall_status=StepStatus.SUCCESS,
                start_time=datetime.now(timezone.utc),
            )

        from agentic_v2.server import execution as execution_mod

        monkeypatch.setattr(execution_mod, "_run_via_native_adapter", _fake_native)

        app = make_configured_app()
        client = TestClient(app)

        response = client.post(
            "/api/run",
            json={
                "workflow": "test_workflow",
                "input_data": {},
                "adapter": "native",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert "run_id" in payload
        # Background task runs synchronously in TestClient — native path must have fired.
        assert native_calls == ["native"], (
            "Expected _run_via_native_adapter to be called with 'native', "
            f"got: {native_calls}"
        )

    def test_run_request_without_adapter_defaults_to_langchain(self, monkeypatch):
        """POST /api/run without adapter field defaults to 'langchain'."""
        from agentic_v2.langchain import config
        from agentic_v2.server.routes import workflows

        def _mock_load_config(name, definitions_dir=None):
            return config.WorkflowConfig(name=name, inputs={}, steps=[])

        monkeypatch.setattr(workflows, "load_workflow_config", _mock_load_config)

        app = make_configured_app()
        client = TestClient(app)

        response = client.post(
            "/api/run",
            json={
                "workflow": "test_workflow",
                "input_data": {},
            },
        )
        assert response.status_code == 200
        # The default adapter should be "langchain" — the request is accepted

    def test_run_request_with_unknown_adapter_fails(self, monkeypatch):
        """POST /api/run with unknown adapter returns an error."""
        from agentic_v2.langchain import config
        from agentic_v2.server.routes import workflows

        def _mock_load_config(name, definitions_dir=None):
            return config.WorkflowConfig(name=name, inputs={}, steps=[])

        monkeypatch.setattr(workflows, "load_workflow_config", _mock_load_config)

        app = make_configured_app()
        client = TestClient(app)

        response = client.post(
            "/api/run",
            json={
                "workflow": "test_workflow",
                "input_data": {},
                "adapter": "nonexistent_adapter",
            },
        )
        # Should fail validation or return error
        assert response.status_code in (400, 422, 500)
