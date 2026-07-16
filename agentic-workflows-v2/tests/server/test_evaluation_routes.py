"""Route-level tests for /api/eval/datasets/sample-list pagination.

Covers the two Sprint B #4 bugs:

* **Bug A** — ``sample_count`` missing from meta caused the route to cap
  every repository dataset at 1 sample. We assert the response exposes
  the authoritative size from ``BENCHMARK_DEFINITIONS``.
* **Bug B** — N+1 loader pattern. We assert the underlying
  ``load_benchmark`` is called **once** per page, not ``limit`` times.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agentic_v2.server import datasets as datasets_module
from agentic_v2.server.app import create_app

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass
class _FakeTask:
    """Minimal stand-in for ``tools.agents.benchmarks.loader.BenchmarkTask``.

    The route code path only consumes ``.to_dict()`` or ``asdict()``, so a
    plain dataclass with a ``to_dict`` method is sufficient.
    """

    task_id: str
    benchmark_id: str
    prompt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "benchmark_id": self.benchmark_id,
            "prompt": self.prompt,
        }


@dataclass
class _FakeBenchmarkDefinition:
    """Minimal stand-in for a ``BenchmarkDefinition`` — only ``size`` is read."""

    size: int = 164


# ---------------------------------------------------------------------------
# Unit tests — exercise the batch helper through the route without HF
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_humaneval_env(monkeypatch: pytest.MonkeyPatch):
    """Patch ``load_benchmark`` and ``BENCHMARK_DEFINITIONS`` for offline use.

    The fixture also records every call to ``load_benchmark`` so tests can
    assert the N+1 fix holds.
    """
    # Disable sanitization middleware for tests
    monkeypatch.setenv("AGENTIC_SANITIZER_FAIL_OPEN", "1")

    call_log: list[dict[str, Any]] = []
    total = 164

    def fake_load_benchmark(
        benchmark_id: str,
        limit: int | None = None,
        offset: int = 0,
        **_kwargs: Any,
    ) -> list[_FakeTask]:
        call_log.append(
            {"benchmark_id": benchmark_id, "limit": limit, "offset": offset}
        )
        start = max(offset, 0)
        stop = min(start + (limit or total), total)
        return [
            _FakeTask(
                task_id=f"HumanEval/{idx}",
                benchmark_id=benchmark_id,
                prompt=f"prompt-{idx}",
            )
            for idx in range(start, stop)
        ]

    fake_registry = {"humaneval": _FakeBenchmarkDefinition(size=total)}

    # Patch the loader at its real module path so the lazy imports inside
    # ``datasets.load_repository_dataset_samples`` pick up the fake.
    import tools.agents.benchmarks.datasets as bench_datasets
    import tools.agents.benchmarks.loader as bench_loader

    monkeypatch.setattr(bench_loader, "load_benchmark", fake_load_benchmark)
    monkeypatch.setattr(
        bench_datasets, "BENCHMARK_DEFINITIONS", fake_registry, raising=False
    )
    return call_log


def test_sample_list_repository_page_has_correct_size_and_indexes(
    fake_humaneval_env: list[dict[str, Any]],
) -> None:
    """First page returns exactly ``limit`` summaries with sequential indexes."""
    app = create_app()
    client = TestClient(app)

    response = client.get(
        "/api/eval/datasets/sample-list",
        params={
            "dataset_source": "repository",
            "dataset_id": "humaneval",
            "offset": 0,
            "limit": 20,
        },
    )
    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload["sample_count"] == 164
    assert payload["offset"] == 0
    assert payload["limit"] == 20
    assert len(payload["samples"]) == 20

    indexes = [summary["sample_index"] for summary in payload["samples"]]
    assert indexes == list(range(0, 20))


def test_sample_list_repository_middle_page_indexes_are_absolute(
    fake_humaneval_env: list[dict[str, Any]],
) -> None:
    """Offset into the middle returns the requested slice, not 0..limit."""
    app = create_app()
    client = TestClient(app)

    response = client.get(
        "/api/eval/datasets/sample-list",
        params={
            "dataset_source": "repository",
            "dataset_id": "humaneval",
            "offset": 10,
            "limit": 5,
        },
    )
    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload["sample_count"] == 164
    assert [s["sample_index"] for s in payload["samples"]] == [10, 11, 12, 13, 14]


def test_sample_list_repository_calls_load_benchmark_exactly_once(
    fake_humaneval_env: list[dict[str, Any]],
) -> None:
    """Bug B regression: pagination must NOT call load_benchmark per row."""
    app = create_app()
    client = TestClient(app)

    response = client.get(
        "/api/eval/datasets/sample-list",
        params={
            "dataset_source": "repository",
            "dataset_id": "humaneval",
            "offset": 50,
            "limit": 20,
        },
    )
    assert response.status_code == 200, response.text
    assert len(fake_humaneval_env) == 1, (
        "Expected a single load_benchmark() call for the whole page, "
        f"got {len(fake_humaneval_env)}: {fake_humaneval_env}"
    )
    assert fake_humaneval_env[0]["offset"] == 50
    assert fake_humaneval_env[0]["limit"] == 20


def test_sample_count_meta_populated_from_registry(
    fake_humaneval_env: list[dict[str, Any]],
) -> None:
    """Bug A regression: meta.sample_count must reflect the canonical size."""
    _, meta = datasets_module.load_repository_dataset_sample(
        "humaneval", sample_index=0
    )
    assert meta["sample_count"] == 164
    assert meta["dataset_id"] == "humaneval"


# ---------------------------------------------------------------------------
# Integration test — real HuggingFace fetch, skipped offline
# ---------------------------------------------------------------------------


def _hf_datasets_available() -> bool:
    """Return True when the Hugging Face ``datasets`` extra is usable.

    A different top-level package named ``datasets`` can be importable in a
    monorepo checkout. The integration test needs the HF API specifically.
    """
    try:
        import datasets as _datasets

        return callable(getattr(_datasets, "load_dataset", None))
    except ImportError:
        return False


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("HF_HUB_OFFLINE") == "1"
    or os.environ.get("AGENTIC_SKIP_NETWORK_TESTS") == "1"
    or not _hf_datasets_available(),
    reason="Integration test requires network + `datasets` extra (pip install datasets)",
)
def test_sample_list_humaneval_real_fetch() -> None:
    """End-to-end: pull humaneval from HuggingFace through the route."""
    from tests._server_test_helpers import make_configured_app

    app = make_configured_app()
    client = TestClient(app)

    response = client.get(
        "/api/eval/datasets/sample-list",
        params={
            "dataset_source": "repository",
            "dataset_id": "humaneval",
            "offset": 0,
            "limit": 5,
        },
    )
    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload["sample_count"] == 164
    assert len(payload["samples"]) == 5
    assert [s["sample_index"] for s in payload["samples"]] == [0, 1, 2, 3, 4]


# ---------------------------------------------------------------------------
# Unit tests — local dataset batch loader
# ---------------------------------------------------------------------------


def test_local_dataset_batch_loader_slices_in_memory(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Local batch loader reads the JSON once and slices the list."""
    import json

    dataset_dir = tmp_path / "tests" / "fixtures" / "datasets"
    dataset_dir.mkdir(parents=True)
    dataset_path = dataset_dir / "synthetic.json"
    dataset_path.write_text(
        json.dumps([{"task_id": f"t-{i}", "prompt": f"p-{i}"} for i in range(50)]),
        encoding="utf-8",
    )

    monkeypatch.setattr(datasets_module, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(datasets_module, "_WORKSPACE_ROOT", tmp_path)

    dataset_ref = "tests/fixtures/datasets/synthetic.json"
    batch = datasets_module.load_local_dataset_samples(dataset_ref, offset=10, limit=5)

    assert len(batch) == 5
    assert [meta["sample_index"] for _, meta in batch] == [10, 11, 12, 13, 14]
    assert all(meta["sample_count"] == 50 for _, meta in batch)
    assert [sample["task_id"] for sample, _ in batch] == [
        "t-10",
        "t-11",
        "t-12",
        "t-13",
        "t-14",
    ]


# ---------------------------------------------------------------------------
# SB-1: New path-based endpoints (Sprint B carryover)
# ---------------------------------------------------------------------------


def test_new_path_based_samples_endpoint(
    fake_humaneval_env: list[dict[str, Any]],
) -> None:
    """New path-based endpoint: GET /eval/datasets/{source}/{dataset_id}/samples."""
    app = create_app()
    client = TestClient(app)

    response = client.get(
        "/api/eval/datasets/repository/humaneval/samples",
        params={"offset": 0, "limit": 10},
    )
    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload["sample_count"] == 164
    assert payload["offset"] == 0
    assert payload["limit"] == 10
    assert len(payload["samples"]) == 10


def test_new_path_based_sample_detail_endpoint(
    fake_humaneval_env: list[dict[str, Any]],
) -> None:
    """New path-based endpoint: GET /eval/datasets/{source}/{dataset_id}/samples/{index}."""
    app = create_app()
    client = TestClient(app)

    response = client.get("/api/eval/datasets/repository/humaneval/samples/5")
    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload["sample_index"] == 5
    assert payload["dataset_source"] == "repository"
    assert payload["dataset_id"] == "humaneval"


def test_old_sample_list_endpoint_redirects_to_new_path(
    fake_humaneval_env: list[dict[str, Any]],
) -> None:
    """Old query-param endpoint returns 302 redirect to new path-based URL."""
    app = create_app()
    client = TestClient(app, follow_redirects=False)

    response = client.get(
        "/api/eval/datasets/sample-list",
        params={
            "dataset_source": "repository",
            "dataset_id": "humaneval",
            "offset": 10,
            "limit": 5,
        },
    )
    assert response.status_code == 302
    assert "Location" in response.headers
    location = response.headers["Location"]
    assert "/api/eval/datasets/repository/humaneval/samples" in location
    assert "offset=10" in location
    assert "limit=5" in location


def test_old_sample_detail_endpoint_redirects_to_new_path(
    fake_humaneval_env: list[dict[str, Any]],
) -> None:
    """Old query-param detail endpoint returns 302 redirect to new path-based URL."""
    app = create_app()
    client = TestClient(app, follow_redirects=False)

    response = client.get(
        "/api/eval/datasets/sample-detail",
        params={
            "dataset_source": "repository",
            "dataset_id": "humaneval",
            "sample_index": 5,
        },
    )
    assert response.status_code == 302
    assert "Location" in response.headers
    location = response.headers["Location"]
    assert "/api/eval/datasets/repository/humaneval/samples/5" in location


def test_dataset_id_with_slashes_in_path_based_endpoint(
    fake_humaneval_env: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Path-based endpoint preserves slashes in dataset_id (e.g.,
    'openai/humaneval')."""
    app = create_app()
    client = TestClient(app)

    # Simulate a dataset_id with slashes (common in HuggingFace repos)
    # Patch the exact symbol the route calls.
    import agentic_v2.server.routes.evaluation_routes as evaluation_routes_module

    original_loader = evaluation_routes_module.load_repository_dataset_samples

    def patched_loader(dataset_id: str, offset: int = 0, limit: int = 20):
        if dataset_id == "openai/humaneval":
            # Return fake data as if this were a valid dataset
            return [
                (
                    {"task_id": f"test-{i}", "prompt": f"prompt-{i}"},
                    {
                        "sample_index": offset + i,
                        "sample_count": 50,
                        "dataset_id": "openai/humaneval",
                    },
                )
                for i in range(min(limit, 50 - offset))
            ]
        return original_loader(dataset_id, offset, limit)

    monkeypatch.setattr(
        evaluation_routes_module,
        "load_repository_dataset_samples",
        patched_loader,
    )

    try:
        response = client.get(
            "/api/eval/datasets/repository/openai/humaneval/samples",
            params={"offset": 0, "limit": 10},
        )
        assert response.status_code == 200, response.text

        payload = response.json()
        assert payload["dataset_id"] == "openai/humaneval"
        assert payload["sample_count"] == 50
        assert len(payload["samples"]) == 10
    finally:
        monkeypatch.setattr(
            evaluation_routes_module,
            "load_repository_dataset_samples",
            original_loader,
        )


def test_redirect_preserves_slashes_in_dataset_id(
    fake_humaneval_env: list[dict[str, Any]],
) -> None:
    """Old query-param redirect preserves slashes in dataset_id."""
    app = create_app()
    client = TestClient(app, follow_redirects=False)

    response = client.get(
        "/api/eval/datasets/sample-list",
        params={
            "dataset_source": "repository",
            "dataset_id": "openai/humaneval",
            "offset": 0,
            "limit": 10,
        },
    )
    assert response.status_code == 302
    assert "Location" in response.headers
    location = response.headers["Location"]
    # Verify slashes are preserved in the redirect URL
    assert "/api/eval/datasets/repository/openai/humaneval/samples" in location
    assert "offset=0" in location
    assert "limit=10" in location
