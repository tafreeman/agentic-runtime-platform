"""Unit tests for per-run model override and compiled-graph invalidation.

Covers the LangChain :class:`WorkflowRunner` additions:

- ``_apply_model_override`` is pure: it stamps every step of a *copy* and
  never mutates the input config.
- ``run``/``astream`` with ``model_override`` compile the overridden copy
  with the graph cache bypassed (no read, no poisoning write).
- ``invalidate_compiled_workflow`` drops cached graphs for one workflow so
  the next run recompiles (the editor-save path relies on this).

All tests are deterministic and key-free: ``compile_workflow`` and
``load_workflow_config`` are patched, so no graph or provider is touched.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentic_v2.contracts import StepStatus
from agentic_v2.langchain import runner as runner_module
from agentic_v2.langchain.config import StepConfig, WorkflowConfig
from agentic_v2.langchain.runner import WorkflowRunner, _apply_model_override

OVERRIDE_ID = "ollama:qwen3-coder:30b"


def _config(name: str = "wf_override") -> WorkflowConfig:
    """Two-step config: one bare step, one with a pre-existing override."""
    return WorkflowConfig(
        name=name,
        steps=[
            StepConfig(name="parse", agent="tier0_parser"),
            StepConfig(
                name="review",
                agent="tier2_reviewer",
                depends_on=["parse"],
                model_override="openai:gpt-4o",
            ),
        ],
    )


class _DummyGraph:
    """Minimal graph double supporting ainvoke and astream."""

    async def ainvoke(
        self, state: dict[str, Any], config: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return {"steps": {}, "errors": [], "context": state.get("context", {})}

    async def astream(
        self, state: dict[str, Any], config: dict[str, Any] | None = None
    ) -> Any:
        yield {"node": {"steps": {}}}


# ---------------------------------------------------------------------------
# _apply_model_override — purity and coverage of every step
# ---------------------------------------------------------------------------


class TestApplyModelOverride:
    """The helper must stamp every step on a copy, never the input."""

    def test_sets_override_on_every_step(self) -> None:
        overridden = _apply_model_override(_config(), OVERRIDE_ID)
        assert [step.model_override for step in overridden.steps] == [
            OVERRIDE_ID,
            OVERRIDE_ID,
        ]

    def test_replaces_pre_existing_step_override(self) -> None:
        overridden = _apply_model_override(_config(), OVERRIDE_ID)
        review = next(s for s in overridden.steps if s.name == "review")
        assert review.model_override == OVERRIDE_ID

    def test_does_not_mutate_input_config(self) -> None:
        config = _config()
        _apply_model_override(config, OVERRIDE_ID)
        assert config.steps[0].model_override is None
        assert config.steps[1].model_override == "openai:gpt-4o"

    def test_returns_new_config_and_step_objects(self) -> None:
        config = _config()
        overridden = _apply_model_override(config, OVERRIDE_ID)
        assert overridden is not config
        for new_step, old_step in zip(overridden.steps, config.steps, strict=True):
            assert new_step is not old_step

    def test_preserves_all_other_step_fields(self) -> None:
        config = _config()
        overridden = _apply_model_override(config, OVERRIDE_ID)
        review = next(s for s in overridden.steps if s.name == "review")
        assert review.agent == "tier2_reviewer"
        assert review.depends_on == ["parse"]
        assert overridden.name == config.name

    def test_empty_steps_config_yields_empty_copy(self) -> None:
        empty = WorkflowConfig(name="wf_empty", steps=[])
        overridden = _apply_model_override(empty, OVERRIDE_ID)
        assert overridden.steps == []
        assert overridden is not empty


# ---------------------------------------------------------------------------
# run / astream — cache bypass when an override is active
# ---------------------------------------------------------------------------


class TestRunnerModelOverride:
    """run/astream with model_override compile a copy, cache untouched."""

    def _patch_compile(
        self,
        monkeypatch: pytest.MonkeyPatch,
        compiled_configs: list[WorkflowConfig],
        graphs: list[_DummyGraph],
    ) -> None:
        def _fake_compile(
            config: WorkflowConfig,
            checkpointer: Any = None,
            trace_adapter: Any = None,
            **_kwargs: Any,
        ) -> _DummyGraph:
            compiled_configs.append(config)
            graph = _DummyGraph()
            graphs.append(graph)
            return graph

        monkeypatch.setattr(runner_module, "compile_workflow", _fake_compile)

    async def test_run_compiles_overridden_copy_without_caching(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        compiled_configs: list[WorkflowConfig] = []
        graphs: list[_DummyGraph] = []
        self._patch_compile(monkeypatch, compiled_configs, graphs)

        base_config = _config("wf_run_override")
        monkeypatch.setattr(
            runner_module,
            "load_workflow_config",
            lambda *_args, **_kwargs: base_config,
        )

        runner = WorkflowRunner(checkpointer=object())
        result = await runner.run("wf_run_override", model_override=OVERRIDE_ID)

        assert result.overall_status == StepStatus.SUCCESS
        assert len(compiled_configs) == 1
        assert all(
            step.model_override == OVERRIDE_ID for step in compiled_configs[0].steps
        )
        # Cache stays clean: the overridden compile is neither read from nor
        # written to the graph cache.
        assert runner._graph_cache == {}
        # The pristine config was never mutated.
        assert base_config.steps[0].model_override is None

    async def test_run_without_override_still_caches(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        compiled_configs: list[WorkflowConfig] = []
        graphs: list[_DummyGraph] = []
        self._patch_compile(monkeypatch, compiled_configs, graphs)

        base_config = _config("wf_run_plain")
        monkeypatch.setattr(
            runner_module,
            "load_workflow_config",
            lambda *_args, **_kwargs: base_config,
        )

        runner = WorkflowRunner(checkpointer=object())
        result = await runner.run("wf_run_plain")

        assert result.overall_status == StepStatus.SUCCESS
        assert len(runner._graph_cache) == 1
        assert compiled_configs[0].steps[0].model_override is None

    async def test_astream_with_override_does_not_poison_cache(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        compiled_configs: list[WorkflowConfig] = []
        graphs: list[_DummyGraph] = []
        self._patch_compile(monkeypatch, compiled_configs, graphs)

        base_config = _config("wf_astream_override")
        monkeypatch.setattr(
            runner_module,
            "load_workflow_config",
            lambda *_args, **_kwargs: base_config,
        )

        runner = WorkflowRunner(checkpointer=object())

        # Prime the cache with the pristine graph.
        events = [event async for event in runner.astream("wf_astream_override")]
        assert len(events) == 1
        assert len(runner._graph_cache) == 1

        # Streaming with an override compiles a second, overridden graph …
        events = [
            event
            async for event in runner.astream(
                "wf_astream_override", model_override=OVERRIDE_ID
            )
        ]
        assert len(events) == 1
        assert len(compiled_configs) == 2
        assert all(
            step.model_override == OVERRIDE_ID for step in compiled_configs[1].steps
        )
        # … while the cache still holds exactly the pristine entry.
        assert len(runner._graph_cache) == 1
        assert next(iter(runner._graph_cache.values())) is graphs[0]


# ---------------------------------------------------------------------------
# invalidate_compiled_workflow — editor-save cache invalidation
# ---------------------------------------------------------------------------


class TestInvalidateCompiledWorkflow:
    """Invalidation drops cached graphs for one workflow only."""

    def _runner_with_compile_spy(
        self, monkeypatch: pytest.MonkeyPatch, compile_calls: list[str]
    ) -> WorkflowRunner:
        def _fake_compile(
            config: WorkflowConfig,
            checkpointer: Any = None,
            trace_adapter: Any = None,
            **_kwargs: Any,
        ) -> _DummyGraph:
            compile_calls.append(config.name)
            return _DummyGraph()

        monkeypatch.setattr(runner_module, "compile_workflow", _fake_compile)
        return WorkflowRunner(checkpointer=object())

    def test_invalidation_forces_recompile(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        compile_calls: list[str] = []
        runner = self._runner_with_compile_spy(monkeypatch, compile_calls)
        config = _config("wf_invalidate")

        first = runner._get_or_compile(config, use_cache=True)
        second = runner._get_or_compile(config, use_cache=True)
        assert first is second
        assert compile_calls == ["wf_invalidate"]

        removed = runner.invalidate_compiled_workflow("wf_invalidate")
        assert removed == 1
        assert len(runner._graph_cache) == 0

        third = runner._get_or_compile(config, use_cache=True)
        assert third is not first
        assert compile_calls == ["wf_invalidate", "wf_invalidate"]

    def test_invalidation_leaves_other_workflows_cached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        compile_calls: list[str] = []
        runner = self._runner_with_compile_spy(monkeypatch, compile_calls)
        config_a = _config("wf_a")
        config_b = _config("wf_b")

        runner._get_or_compile(config_a, use_cache=True)
        graph_b = runner._get_or_compile(config_b, use_cache=True)

        assert runner.invalidate_compiled_workflow("wf_a") == 1
        assert len(runner._graph_cache) == 1
        # wf_b is still served from cache — no recompile.
        assert runner._get_or_compile(config_b, use_cache=True) is graph_b
        assert compile_calls == ["wf_a", "wf_b"]

    def test_invalidation_of_unknown_workflow_returns_zero(self) -> None:
        runner = WorkflowRunner(checkpointer=object())
        assert runner.invalidate_compiled_workflow("never_compiled") == 0
