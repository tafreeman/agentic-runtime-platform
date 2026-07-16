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

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import BackgroundTasks, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from agentic_v2.contracts import StepStatus
from agentic_v2.core.tenant import TenantContext
from agentic_v2.langchain.config import (
    InputConfig,
    WorkflowConfig,
    load_workflow_config,
    validate_workflow_inputs,
)
from agentic_v2.server.app import create_app
from agentic_v2.server.models import WorkflowEvaluationRequest, WorkflowRunRequest
from agentic_v2.server.routes import workflows


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


# ---------------------------------------------------------------------------
# POST /api/run -- dataset-backed evaluation resolves inputs before validation
#
# An evaluation-enabled request may legitimately submit empty ``input_data``:
# the dataset sample is expected to supply the workflow's required inputs.
# The route must call ``_resolve_evaluation_inputs`` first and validate its
# *returned* (merged) inputs -- not the raw, possibly-empty request body.
# ---------------------------------------------------------------------------


def _request(path: str = "/api/run") -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": [],
        "app": SimpleNamespace(state=SimpleNamespace(agentic_oidc_enabled=False)),
    }
    return Request(scope)


async def _noop_audit(*_args: Any, **_kwargs: Any) -> None:
    return None


def _patch_run_route_for_evaluation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    workflow_def: WorkflowConfig,
    resolved_inputs: dict[str, Any],
) -> None:
    """Patch run_workflow dependencies, stubbing only dataset resolution.

    Everything else (``validate_workflow_inputs``, the adapter/background-task
    plumbing) runs for real, so the test exercises the actual call ordering
    instead of a mocked stand-in for it.
    """
    registry = SimpleNamespace(
        get_adapter=lambda _name: object(),
        list_adapters=lambda: ["native", "langchain"],
    )
    monkeypatch.setattr("agentic_v2.adapters.get_registry", lambda: registry)
    monkeypatch.setattr(workflows, "_require_langchain_runtime", lambda: None)
    monkeypatch.setattr(workflows, "load_workflow_config", lambda _name: workflow_def)
    monkeypatch.setattr(workflows, "audit_request_event", _noop_audit)
    monkeypatch.setattr(workflows, "tenant_dataset_dir", lambda _tenant_id: tmp_path)

    def _fake_resolve_evaluation_inputs(
        _workflow_def: Any,
        _evaluation: Any,
        _run_id: str,
        _workflow_inputs: dict[str, Any],
        **_kwargs: Any,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        return dict(resolved_inputs), {"sample": "data"}, {"dataset_id": "ds1"}

    monkeypatch.setattr(
        workflows,
        "_resolve_evaluation_inputs",
        _fake_resolve_evaluation_inputs,
    )


def _evaluation_request() -> WorkflowEvaluationRequest:
    return WorkflowEvaluationRequest(
        enabled=True, dataset_source="repository", dataset_id="ds1"
    )


async def test_dataset_resolution_runs_before_input_validation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A dataset sample that fills the required input is accepted.

    Regression guard: if the route validated ``request.input_data`` directly
    instead of the merged inputs returned by dataset resolution, this would
    422 on the empty ``input_data`` even though the resolved sample supplies
    the required 'feature_spec' input.
    """
    workflow_def = WorkflowConfig(
        name="wf",
        inputs={"feature_spec": InputConfig(name="feature_spec", required=True)},
        steps=[],
    )
    _patch_run_route_for_evaluation(
        monkeypatch, tmp_path, workflow_def, {"feature_spec": "from dataset"}
    )
    background_tasks = BackgroundTasks()
    tenant = TenantContext(tenant_id="tenant-a", source="default")

    response = await workflows.run_workflow(
        WorkflowRunRequest(
            workflow="wf",
            input_data={},
            adapter="langchain",
            evaluation=_evaluation_request(),
        ),
        background_tasks,
        _request(),
        tenant,
    )

    assert response.status == StepStatus.PENDING
    assert len(background_tasks.tasks) == 1
    # workflow_inputs is the third positional arg to _run_and_evaluate.
    assert background_tasks.tasks[0].args[2] == {"feature_spec": "from dataset"}


async def test_dataset_resolution_still_enforces_required_inputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A dataset sample that leaves a required input empty is still rejected.

    Confirms dataset resolution is not a way to bypass
    ``validate_workflow_inputs`` -- validation still runs (and rejects) on
    the merged inputs after resolution.
    """
    workflow_def = WorkflowConfig(
        name="wf",
        inputs={"feature_spec": InputConfig(name="feature_spec", required=True)},
        steps=[],
    )
    _patch_run_route_for_evaluation(
        monkeypatch, tmp_path, workflow_def, {"feature_spec": "   "}
    )
    background_tasks = BackgroundTasks()
    tenant = TenantContext(tenant_id="tenant-a", source="default")

    with pytest.raises(HTTPException) as exc_info:
        await workflows.run_workflow(
            WorkflowRunRequest(
                workflow="wf",
                input_data={},
                adapter="langchain",
                evaluation=_evaluation_request(),
            ),
            background_tasks,
            _request(),
            tenant,
        )

    assert exc_info.value.status_code == 422
    assert "feature_spec" in exc_info.value.detail
    assert background_tasks.tasks == []
