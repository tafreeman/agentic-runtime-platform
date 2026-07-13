"""Sample-title derivation and honest repo-dataset failure tests.

Covers two evaluation-picker fixes:

* ``_make_sample_summary`` title derivation across the real benchmark row
  shapes (humaneval, code_review_instruct, mbpp, swe_bench,
  code_instructions, react_code_instructions) — none of which carry the
  classic ``title``/``name``/``problem`` keys, so every row used to render
  as ``Sample {index}``.
* ``load_repository_dataset_samples`` raising (route 422) instead of
  silently returning ``[]`` when the registry says the dataset has samples
  but the load failed (expired cache + failed network fetch). A genuinely
  empty LOCAL dataset must still list as 200 + ``[]``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from agentic_v2.server import datasets as datasets_module
from agentic_v2.server.routes.evaluation_routes import _make_sample_summary

# ---------------------------------------------------------------------------
# Title derivation — construct fixture-shaped rows inline
# ---------------------------------------------------------------------------


def _summary(sample: dict[str, Any], index: int = 0):
    return _make_sample_summary(sample, index, {})


class TestTitleDerivation:
    def test_humaneval_shape_uses_task_id(self) -> None:
        sample = {
            "task_id": "HumanEval/0",
            "prompt": "def has_close_elements(numbers, threshold):\n    ...",
            "canonical_solution": "    for idx, elem in enumerate(numbers): ...",
            "entry_point": "has_close_elements",
            "test": "def check(candidate): ...",
        }
        assert _summary(sample).title == "HumanEval/0"

    def test_swe_bench_shape_uses_instance_id(self) -> None:
        sample = {
            "instance_id": "astropy__astropy-12907",
            "repo": "astropy/astropy",
            "problem_statement": "Modeling's separability_matrix does not ...",
            "patch": "diff --git a/astropy/modeling/separable.py ...",
        }
        assert _summary(sample).title == "astropy__astropy-12907"

    def test_code_review_instruct_shape_uses_string_question_id(self) -> None:
        sample = {
            "question_id": "q-1287",
            "prompt": "Review the following change ...",
            "body": "...",
            "response": "...",
            "answer": "...",
        }
        assert _summary(sample).title == "q-1287"

    def test_mbpp_shape_with_int_task_id_falls_through_to_text(self) -> None:
        # mbpp task_id values are ints — an id-like key must be a *string*
        # to become the title, so the prose ``text`` field wins here.
        sample = {
            "task_id": 2,
            "text": (
                "Write a function to find the similar elements from "
                "the given two tuple lists."
            ),
            "code": "def similar_elements(t1, t2): ...",
            "test_list": ["assert similar_elements(...) == ..."],
        }
        title = _summary(sample).title
        assert title.startswith("Write a function to find the similar elements")
        assert len(title) <= 80

    def test_code_instructions_shape_uses_instruction_preview(self) -> None:
        sample = {
            "instruction": (
                "Create a function to\ncalculate the sum of a sequence "
                "of integers."
            ),
            "input": "[1, 2, 3, 4, 5]",
            "output": "def sum_sequence(seq): ...",
        }
        assert _summary(sample).title == (
            "Create a function to calculate the sum of a sequence of integers."
        )

    def test_react_code_instructions_shape_uses_first_message_content(self) -> None:
        long_tail = "x" * 200
        sample = {
            "model": "some-model",
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Build a React   component\nthat renders a data grid "
                        + long_tail
                    ),
                },
                {"role": "assistant", "content": "Sure!"},
            ],
        }
        title = _summary(sample).title
        assert title.startswith("Build a React component that renders a data grid")
        assert len(title) == 80
        assert "\n" not in title

    def test_explicit_title_wins_over_id_like_keys(self) -> None:
        sample = {"title": "Two Sum", "task_id": "LC/1", "prompt": "..."}
        assert _summary(sample).title == "Two Sum"

    def test_name_wins_over_prose_fields(self) -> None:
        sample = {"name": "warmup-1", "question": "What is 2+2?"}
        assert _summary(sample).title == "warmup-1"

    def test_fallback_when_nothing_usable(self) -> None:
        assert _summary({"value": 42}, index=7).title == "Sample 7"
        assert _summary({}, index=3).title == "Sample 3"

    def test_blank_and_non_string_candidates_are_skipped(self) -> None:
        sample = {"title": "   ", "task_id": 17, "prompt": "Do the thing."}
        assert _summary(sample).title == "Do the thing."

    def test_chat_shape_with_non_dict_first_message_falls_back(self) -> None:
        sample = {"messages": ["not-a-dict"]}
        assert _summary(sample, index=4).title == "Sample 4"

    def test_summary_field_logic_is_unchanged(self) -> None:
        # The summary stays the raw first non-identifier string field
        # (200-char cap, no whitespace collapsing) — only the title changed.
        sample = {"task_id": "HumanEval/0", "prompt": "def foo():\n    pass"}
        result = _summary(sample)
        assert result.summary == "def foo():\n    pass"
        assert result.task_id == "HumanEval/0"


# ---------------------------------------------------------------------------
# Honest repository-dataset failures
# ---------------------------------------------------------------------------


@dataclass
class _FakeDefinition:
    """Minimal registry stand-in — only ``size`` is read."""

    size: int = 164


@pytest.fixture
def empty_repo_batch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Registry advertises 164 samples, but the loader returns nothing."""
    import tools.agents.benchmarks.datasets as bench_datasets
    import tools.agents.benchmarks.loader as bench_loader

    def fake_load_benchmark(
        benchmark_id: str,
        limit: int | None = None,
        offset: int = 0,
        **_kwargs: Any,
    ) -> list[Any]:
        return []

    monkeypatch.setattr(bench_loader, "load_benchmark", fake_load_benchmark)
    monkeypatch.setattr(
        bench_datasets,
        "BENCHMARK_DEFINITIONS",
        {"humaneval": _FakeDefinition(size=164)},
        raising=False,
    )


class TestEmptyRepositoryBatch:
    def test_loader_raises_when_registry_expects_samples(
        self, empty_repo_batch_env: None
    ) -> None:
        with pytest.raises(ValueError, match="returned no samples"):
            datasets_module.load_repository_dataset_samples(
                "humaneval", offset=0, limit=20
            )

    def test_route_maps_empty_batch_to_422(
        self, client, empty_repo_batch_env: None
    ) -> None:
        response = client.get(
            "/api/eval/datasets/repository/humaneval/samples",
            params={"offset": 0, "limit": 20},
        )
        assert response.status_code == 422, response.text
        assert "returned no samples" in response.json()["detail"]

    def test_paging_past_the_end_stays_an_empty_page(
        self, empty_repo_batch_env: None
    ) -> None:
        # offset beyond the registry size is a legitimate empty page, not a
        # failed load — it must not raise.
        batch = datasets_module.load_repository_dataset_samples(
            "humaneval", offset=200, limit=20
        )
        assert batch == []

    def test_unknown_registry_entry_stays_lenient(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import tools.agents.benchmarks.datasets as bench_datasets
        import tools.agents.benchmarks.loader as bench_loader

        monkeypatch.setattr(
            bench_loader, "load_benchmark", lambda **_kwargs: [], raising=False
        )
        monkeypatch.setattr(
            bench_datasets, "BENCHMARK_DEFINITIONS", {}, raising=False
        )

        batch = datasets_module.load_repository_dataset_samples(
            "mystery-benchmark", offset=0, limit=20
        )
        assert batch == []


def test_empty_local_dataset_stays_200(
    client, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A genuinely-empty LOCAL dataset lists as 200 + [] — never a 422."""
    dataset_dir = tmp_path / "tests" / "fixtures" / "datasets"
    dataset_dir.mkdir(parents=True)
    (dataset_dir / "empty.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(datasets_module, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(datasets_module, "_WORKSPACE_ROOT", tmp_path)

    response = client.get(
        "/api/eval/datasets/local/tests/fixtures/datasets/empty.json/samples",
        params={"offset": 0, "limit": 20},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["samples"] == []
    assert payload["sample_count"] == 0
