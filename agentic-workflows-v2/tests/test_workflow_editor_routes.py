from __future__ import annotations

import yaml
from agentic_v2.langchain import config as lc_config
from agentic_v2.server.app import create_app
from agentic_v2.server.routes import workflows
from fastapi.testclient import TestClient


def _write_workflow(tmp_path, name: str, document: dict) -> None:
    (tmp_path / f"{name}.yaml").write_text(
        yaml.safe_dump(document, sort_keys=False),
        encoding="utf-8",
    )


def _patch_workflow_editor_dir(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        workflows,
        "load_workflow_document",
        lambda name: lc_config.load_workflow_document(name, definitions_dir=tmp_path),
    )
    monkeypatch.setattr(
        workflows,
        "save_workflow_document",
        lambda name, document: lc_config.save_workflow_document(
            name,
            document,
            definitions_dir=tmp_path,
        ),
    )


def test_get_workflow_editor_returns_yaml_and_document(tmp_path, monkeypatch) -> None:
    _write_workflow(
        tmp_path,
        "editor-demo",
        {
            "name": "editor-demo",
            "description": "Editable workflow",
            "steps": [{"name": "draft", "agent": "tier2_coder"}],
        },
    )
    _patch_workflow_editor_dir(monkeypatch, tmp_path)

    client = TestClient(create_app())
    response = client.get("/api/workflows/editor-demo/editor")

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "editor-demo"
    assert payload["document"]["steps"][0]["name"] == "draft"
    assert "Editable workflow" in payload["yaml_text"]


def test_put_workflow_editor_persists_document(tmp_path, monkeypatch) -> None:
    _patch_workflow_editor_dir(monkeypatch, tmp_path)

    client = TestClient(create_app())
    response = client.put(
        "/api/workflows/new-editor",
        json={
            "document": {
                "description": "Saved through API",
                "steps": [{"name": "draft", "agent": "tier2_coder"}],
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["step_count"] == 1
    saved = lc_config.load_workflow_config("new-editor", definitions_dir=tmp_path)
    assert saved.name == "new-editor"
    assert saved.steps[0].name == "draft"


def test_validate_workflow_editor_rejects_invalid_dependency_graph(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        workflows,
        "_compile_workflow_for_validation",
        lambda _config: (_ for _ in ()).throw(
            ValueError("Unknown dependency: missing")
        ),
    )

    client = TestClient(create_app())
    response = client.post(
        "/api/workflows/validate",
        json={
            "document": {
                "name": "broken",
                "steps": [
                    {
                        "name": "draft",
                        "agent": "tier2_coder",
                        "depends_on": ["missing"],
                    }
                ],
            }
        },
    )

    assert response.status_code == 422
    assert "Unknown dependency" in response.json()["detail"]
