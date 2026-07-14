"""Tests for synchronous input validation on ``POST /api/run``.

A run submitted with missing or empty required inputs must be rejected with
a 422 at the endpoint instead of being accepted and erroring asynchronously
in the background task (which left the UI navigating to a live view that
immediately shows ``Input validation failed``).

Deterministic and key-free: the accepted-path test uses the real
``test_workflow`` definition (its only input is optional with a default),
and the rejection tests use ``fullstack_generation`` whose ``feature_spec``
input is required.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentic_v2.langchain.config import (
    InputConfig,
    WorkflowConfig,
    load_workflow_config,
    validate_workflow_inputs,
)
from agentic_v2.server.app import create_app


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AGENTIC_NO_LLM", "1")
    # raise_server_exceptions off: background-task errors must not fail the
    # request assertions.
    return TestClient(create_app(), raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# validate_workflow_inputs — shared helper
# ---------------------------------------------------------------------------


def _config(**inputs: InputConfig) -> WorkflowConfig:
    return WorkflowConfig(name="wf", inputs=dict(inputs), steps=[])


class TestValidateWorkflowInputs:
    def test_missing_required_input_raises(self) -> None:
        cfg = _config(spec=InputConfig(name="spec", required=True))
        with pytest.raises(ValueError, match="Missing required input: 'spec'"):
            validate_workflow_inputs(cfg, {})

    def test_empty_required_string_raises(self) -> None:
        cfg = _config(spec=InputConfig(name="spec", required=True))
        with pytest.raises(ValueError, match="'spec' must not be empty"):
            validate_workflow_inputs(cfg, {"spec": "   "})

    def test_default_applied_for_omitted_input(self) -> None:
        cfg = _config(stack=InputConfig(name="stack", required=False, default="python"))
        assert validate_workflow_inputs(cfg, {}) == {"stack": "python"}

    def test_enum_violation_raises(self) -> None:
        cfg = _config(
            mode=InputConfig(name="mode", required=True, enum=["fast", "slow"])
        )
        with pytest.raises(ValueError, match="must be one of"):
            validate_workflow_inputs(cfg, {"mode": "warp"})

    def test_all_violations_reported_together(self) -> None:
        cfg = _config(
            spec=InputConfig(name="spec", required=True),
            code=InputConfig(name="code", required=True),
        )
        with pytest.raises(ValueError) as excinfo:
            validate_workflow_inputs(cfg, {"spec": ""})
        message = str(excinfo.value)
        assert "'spec' must not be empty" in message
        assert "Missing required input: 'code'" in message


# ---------------------------------------------------------------------------
# POST /api/run — endpoint gating
# ---------------------------------------------------------------------------


class TestRunEndpointInputValidation:
    def test_missing_required_input_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/run",
            json={"workflow": "fullstack_generation", "input_data": {}},
        )
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "Input validation failed for 'fullstack_generation'" in detail
        assert "feature_spec" in detail

    def test_empty_required_input_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/run",
            json={
                "workflow": "fullstack_generation",
                "input_data": {"feature_spec": ""},
            },
        )
        assert response.status_code == 422
        assert "must not be empty" in response.json()["detail"]

    def test_valid_inputs_accepted(self, client: TestClient) -> None:
        # test_workflow's only input is optional with a default — the real
        # config proves defaults satisfy validation at the endpoint.
        config = load_workflow_config("test_workflow")
        assert all(
            not cfg.required or cfg.default is not None
            for cfg in config.inputs.values()
        )
        response = client.post(
            "/api/run",
            json={"workflow": "test_workflow", "input_data": {}},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "pending"
