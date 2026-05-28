"""Route-level tests for workflow evaluation API behavior."""

from __future__ import annotations

from agentic_v2.server import result_normalization
from agentic_v2.server.app import create_app
from agentic_v2.server.routes import evaluation_routes
from fastapi.testclient import TestClient


def test_eval_datasets_endpoint_returns_expected_shape():
    app = create_app()
    client = TestClient(app)

    response = client.get("/api/eval/datasets")
    assert response.status_code == 200

    payload = response.json()
    assert "repository" in payload
    assert "local" in payload
    assert isinstance(payload["repository"], list)
    assert isinstance(payload["local"], list)


def test_run_endpoint_returns_422_when_repository_dataset_id_missing(monkeypatch):
    app = create_app()
    client = TestClient(app)

    # Mock load_workflow_config for this validation-path test
    from agentic_v2.langchain import config
    from agentic_v2.server.routes import workflows

    def _mock_load_config(name, definitions_dir=None):
        return config.WorkflowConfig(name=name, inputs={}, steps=[])

    monkeypatch.setattr(workflows, "load_workflow_config", _mock_load_config)

    response = client.post(
        "/api/run",
        json={
            "workflow": "dummy_workflow",
            "input_data": {},
            "evaluation": {
                "enabled": True,
                "dataset_source": "repository",
            },
        },
    )

    assert response.status_code == 422
    assert "dataset_id is required" in response.json()["detail"]


def test_run_endpoint_returns_422_when_local_dataset_ref_missing(monkeypatch):
    app = create_app()
    client = TestClient(app)

    from agentic_v2.langchain import config
    from agentic_v2.server.routes import workflows

    def _mock_load_config(name, definitions_dir=None):
        return config.WorkflowConfig(name=name, inputs={}, steps=[])

    monkeypatch.setattr(workflows, "load_workflow_config", _mock_load_config)

    response = client.post(
        "/api/run",
        json={
            "workflow": "dummy_workflow",
            "input_data": {},
            "evaluation": {
                "enabled": True,
                "dataset_source": "local",
            },
        },
    )

    assert response.status_code == 422
    assert "local_dataset_path" in response.json()["detail"]


def test_eval_datasets_filtered_by_workflow(monkeypatch):
    app = create_app()
    client = TestClient(app)

    from agentic_v2.langchain import config

    def _mock_load_config(name, definitions_dir=None):
        return config.WorkflowConfig(
            name=name,
            inputs={
                "code_file": config.InputConfig(
                    name="code_file", type="string", required=True
                )
            },
            steps=[],
        )

    monkeypatch.setattr(evaluation_routes, "load_workflow_config", _mock_load_config)
    monkeypatch.setattr(
        evaluation_routes,
        "list_local_datasets",
        lambda: [
            {
                "id": "a.json",
                "name": "A",
                "source": "local",
                "description": "",
                "sample_count": 1,
            },
            {
                "id": "b.json",
                "name": "B",
                "source": "local",
                "description": "",
                "sample_count": 1,
            },
        ],
    )
    monkeypatch.setattr(evaluation_routes, "list_repository_datasets", lambda: [])

    def _load_local(dataset_id: str, sample_index: int = 0):
        if dataset_id == "a.json":
            return {"code_file": "x.py"}, {"source": "local", "dataset_id": dataset_id}
        return {"prompt": ""}, {"source": "local", "dataset_id": dataset_id}

    monkeypatch.setattr(evaluation_routes, "load_local_dataset_sample", _load_local)

    response = client.get("/api/eval/datasets?workflow=dummy_workflow")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["local"]) == 1
    assert payload["local"][0]["id"] == "a.json"


def test_run_rejects_incompatible_dataset_422(monkeypatch):
    app = create_app()
    client = TestClient(app)

    from agentic_v2.langchain import config
    from agentic_v2.server.routes import workflows

    def _mock_load_config(name, definitions_dir=None):
        return config.WorkflowConfig(
            name=name,
            inputs={
                "code_file": config.InputConfig(
                    name="code_file", type="string", required=True
                )
            },
            steps=[],
        )

    monkeypatch.setattr(workflows, "load_workflow_config", _mock_load_config)
    monkeypatch.setattr(
        result_normalization,
        "load_local_dataset_sample",
        lambda _dataset_ref, sample_index=0: ({"prompt": ""}, {"source": "local"}),
    )

    response = client.post(
        "/api/run",
        json={
            "workflow": "dummy_workflow",
            "evaluation": {
                "enabled": True,
                "dataset_source": "local",
                "dataset_id": "any.json",
            },
        },
    )

    assert response.status_code == 422
    payload = response.json()["detail"]
    assert "reasons" in payload
    assert "missing: code_file" in payload["reasons"]


def test_reject_empty_required_adapted_input(monkeypatch):
    app = create_app()
    client = TestClient(app)

    from agentic_v2.langchain import config
    from agentic_v2.server.routes import workflows

    def _mock_load_config(name, definitions_dir=None):
        return config.WorkflowConfig(
            name=name,
            inputs={
                "code_file": config.InputConfig(
                    name="code_file", type="string", required=True
                ),
                "notes": config.InputConfig(
                    name="notes", type="string", required=False
                ),
            },
            steps=[],
        )

    monkeypatch.setattr(workflows, "load_workflow_config", _mock_load_config)
    monkeypatch.setattr(
        result_normalization,
        "load_local_dataset_sample",
        lambda _dataset_ref, sample_index=0: (
            {"code_file": "x.py"},
            {"source": "local"},
        ),
    )
    monkeypatch.setattr(
        result_normalization,
        "adapt_sample_to_workflow_inputs",
        lambda *_args, **_kwargs: {"code_file": "", "notes": ""},
    )

    response = client.post(
        "/api/run",
        json={
            "workflow": "dummy_workflow",
            "evaluation": {
                "enabled": True,
                "dataset_source": "local",
                "dataset_id": "any.json",
            },
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "missing_inputs" in detail
    assert "code_file" in detail["missing_inputs"]


def test_accept_empty_optional_adapted_input(monkeypatch):
    app = create_app()
    client = TestClient(app)

    from agentic_v2.langchain import config
    from agentic_v2.server.routes import workflows

    def _mock_load_config(name, definitions_dir=None):
        return config.WorkflowConfig(
            name=name,
            inputs={
                "code_file": config.InputConfig(
                    name="code_file", type="string", required=True
                ),
                "notes": config.InputConfig(
                    name="notes", type="string", required=False
                ),
            },
            steps=[],
        )

    monkeypatch.setattr(workflows, "load_workflow_config", _mock_load_config)
    monkeypatch.setattr(
        result_normalization,
        "load_local_dataset_sample",
        lambda _dataset_ref, sample_index=0: (
            {"code_file": "x.py"},
            {"source": "local"},
        ),
    )
    monkeypatch.setattr(
        result_normalization,
        "adapt_sample_to_workflow_inputs",
        lambda *_args, **_kwargs: {"code_file": "x.py", "notes": ""},
    )

    response = client.post(
        "/api/run",
        json={
            "workflow": "dummy_workflow",
            "evaluation": {
                "enabled": True,
                "dataset_source": "local",
                "dataset_id": "any.json",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pending"


def test_accept_full_adapted_inputs(monkeypatch):
    app = create_app()
    client = TestClient(app)

    from agentic_v2.langchain import config
    from agentic_v2.server.routes import workflows

    def _mock_load_config(name, definitions_dir=None):
        return config.WorkflowConfig(
            name=name,
            inputs={
                "code_file": config.InputConfig(
                    name="code_file", type="string", required=True
                ),
                "notes": config.InputConfig(
                    name="notes", type="string", required=False
                ),
            },
            steps=[],
        )

    monkeypatch.setattr(workflows, "load_workflow_config", _mock_load_config)
    monkeypatch.setattr(
        result_normalization,
        "load_local_dataset_sample",
        lambda _dataset_ref, sample_index=0: (
            {"code_file": "x.py"},
            {"source": "local"},
        ),
    )
    monkeypatch.setattr(
        result_normalization,
        "adapt_sample_to_workflow_inputs",
        lambda *_args, **_kwargs: {"code_file": "x.py", "notes": "ready"},
    )

    response = client.post(
        "/api/run",
        json={
            "workflow": "dummy_workflow",
            "evaluation": {
                "enabled": True,
                "dataset_source": "local",
                "dataset_id": "any.json",
            },
        },
    )

    assert response.status_code == 200


def test_empty_request_input_does_not_override_dataset_adapted_value(monkeypatch):
    app = create_app()
    client = TestClient(app)

    from agentic_v2.langchain import config
    from agentic_v2.server.routes import workflows

    def _mock_load_config(name, definitions_dir=None):
        return config.WorkflowConfig(
            name=name,
            inputs={
                "code_file": config.InputConfig(
                    name="code_file", type="string", required=True
                ),
                "review_depth": config.InputConfig(
                    name="review_depth", type="string", required=False
                ),
            },
            steps=[],
        )

    monkeypatch.setattr(workflows, "load_workflow_config", _mock_load_config)
    monkeypatch.setattr(
        result_normalization,
        "load_local_dataset_sample",
        lambda _dataset_ref, sample_index=0: (
            {"prompt": "Review this code"},
            {"source": "local"},
        ),
    )
    monkeypatch.setattr(
        result_normalization,
        "adapt_sample_to_workflow_inputs",
        lambda *_args, **_kwargs: {
            "code_file": "adapted/path.py",
            "review_depth": "deep",
        },
    )

    response = client.post(
        "/api/run",
        json={
            "workflow": "dummy_workflow",
            "input_data": {
                "code_file": "",
                "review_depth": "shallow",
            },
            "evaluation": {
                "enabled": True,
                "dataset_source": "local",
                "dataset_id": "any.json",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pending"
