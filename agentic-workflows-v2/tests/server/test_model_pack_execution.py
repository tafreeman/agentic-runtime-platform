"""Regression tests for model-pack execution isolation and judge resolution.

Covers two review findings on the evidence-ledger/model-packs work:

- Compiled-graph cache bypass: pack tier chains are read from a ContextVar
  at graph-compile time, so a run with an active pack must bypass the
  runner's pack-blind compiled-graph cache (the same rule ``model_override``
  already follows).  Without the bypass, a pack-A compile is cached and a
  later pack-B (or default) run silently executes pack-A candidates.
- Judge model resolution: a pack's ``judge_model`` is honored when no
  dedicated judge env var is set, while ``AGENTIC_JUDGE_MODEL`` still wins
  when both are set (env config outranks the pack; the pack outranks the
  generic tier fallbacks — mirroring tier routing precedence).

Deterministic and key-free: ``compile_workflow``, ``load_workflow_config``,
broadcast, and the run logger are patched; no graph or provider is touched.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agentic_v2 import ui_settings as ui_settings_module
from agentic_v2.contracts import StepStatus
from agentic_v2.langchain import runner as runner_module
from agentic_v2.langchain.config import StepConfig, WorkflowConfig
from agentic_v2.langchain.runner import WorkflowRunner
from agentic_v2.server import execution
from agentic_v2.ui_settings import ModelPack

PACK_A_MODEL = "openai:pack-a-model"
PACK_B_MODEL = "openai:pack-b-model"
JUDGE_ENV_VARS = ("AGENTIC_JUDGE_MODEL", "AGENTIC_MODEL_TIER_2", "AGENTIC_MODEL_TIER_1")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pack(pack_id: str, tier2_model: str, judge_model: str | None = None) -> ModelPack:
    """Build a minimal valid pack with a single tier-2 chain entry."""
    return ModelPack(
        id=pack_id,
        name=pack_id,
        tier_chains={2: [tier2_model]},
        judge_model=judge_model,
    )


def _wf_config(name: str) -> WorkflowConfig:
    """One-step workflow config with no declared inputs or outputs."""
    return WorkflowConfig(name=name, steps=[StepConfig(name="parse", agent="tier0")])


def _clear_judge_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in JUDGE_ENV_VARS:
        monkeypatch.delenv(key, raising=False)


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


class _UseCacheCapturingRunner:
    """Runner double recording the astream kwargs it receives."""

    def __init__(self) -> None:
        self.astream_kwargs: dict[str, Any] | None = None

    async def astream(self, _workflow_name: str, **kwargs: Any) -> Any:
        self.astream_kwargs = kwargs
        yield {"node": {"steps": {}}}

    def resolve_outputs(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {}

    def extract_metadata(self, *_args: Any, **_kwargs: Any) -> tuple[dict, dict]:
        return {}, {}


class _StreamFailsCapturingRunner:
    """Runner double whose stream breaks so the run() fallback fires."""

    def __init__(self) -> None:
        self.run_kwargs: dict[str, Any] | None = None

    async def astream(self, _workflow_name: str, **_kwargs: Any) -> Any:
        raise RuntimeError("stream broken")
        yield {}  # pragma: no cover - makes this an async generator

    async def run(self, _workflow_name: str, **kwargs: Any) -> Any:
        self.run_kwargs = kwargs
        return SimpleNamespace(
            steps={},
            token_counts={},
            models_used={},
            errors=[],
            overall_status=StepStatus.SUCCESS,
            elapsed_seconds=0.0,
            final_output={},
        )


class _StubTenantLogger:
    def log(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class _StubRunLogger:
    def for_tenant(self, _tenant_id: str) -> _StubTenantLogger:
        return _StubTenantLogger()


def _patch_stream_dependencies(
    monkeypatch: pytest.MonkeyPatch, runner: Any, config: Any = None
) -> None:
    monkeypatch.setattr(execution, "_get_lc_runner", lambda: runner)
    monkeypatch.setattr(
        execution,
        "load_workflow_config",
        lambda _name: config or SimpleNamespace(name="wf", steps=[]),
    )

    async def _noop_broadcast(_run_id: str, _event: dict[str, Any]) -> None:
        return None

    monkeypatch.setattr(execution.websocket.manager, "broadcast", _noop_broadcast)


# ---------------------------------------------------------------------------
# _stream_and_run — use_cache forwarding to astream and the run fallback
# ---------------------------------------------------------------------------


async def test_stream_and_run_forwards_use_cache_false_to_astream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _UseCacheCapturingRunner()
    _patch_stream_dependencies(monkeypatch, runner)

    result = await execution._stream_and_run(
        "wf",
        "run-pack-1",
        {"prompt": "hi"},
        use_cache=False,
    )

    assert result.overall_status == StepStatus.SUCCESS
    assert runner.astream_kwargs is not None
    assert runner.astream_kwargs["use_cache"] is False


async def test_stream_and_run_defaults_to_cached_compiles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _UseCacheCapturingRunner()
    _patch_stream_dependencies(monkeypatch, runner)

    await execution._stream_and_run("wf", "run-pack-2", {"prompt": "hi"})

    assert runner.astream_kwargs is not None
    assert runner.astream_kwargs["use_cache"] is True


async def test_stream_and_run_fallback_forwards_use_cache_to_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _StreamFailsCapturingRunner()
    _patch_stream_dependencies(monkeypatch, runner)

    result = await execution._stream_and_run(
        "wf",
        "run-pack-3",
        {"prompt": "hi"},
        use_cache=False,
    )

    assert result.overall_status == StepStatus.SUCCESS
    assert runner.run_kwargs is not None
    assert runner.run_kwargs["use_cache"] is False


# ---------------------------------------------------------------------------
# _run_and_evaluate — cache bypass decision for pack runs
# ---------------------------------------------------------------------------


def _run_and_evaluate_stubs(
    monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]
) -> list[dict[str, Any]]:
    """Patch _stream_and_run, broadcast, and the run logger; return events."""

    async def _fake_stream_and_run(
        workflow_name: str,
        _run_id: str,
        _workflow_inputs: dict[str, Any],
        adapter_name: str = "langchain",
        tenant_id: str = "default",
        model_override: str | None = None,
        use_cache: bool = True,
    ) -> Any:
        captured["workflow_name"] = workflow_name
        captured["use_cache"] = use_cache
        return SimpleNamespace(
            overall_status=SimpleNamespace(value="success"),
            steps=[],
            metadata={},
            final_output={},
            total_duration_ms=10.0,
        )

    events: list[dict[str, Any]] = []

    async def _capture_broadcast(_run_id: str, event: dict[str, Any]) -> None:
        events.append(event)

    monkeypatch.setattr(execution, "_stream_and_run", _fake_stream_and_run)
    monkeypatch.setattr(execution, "run_logger", _StubRunLogger())
    monkeypatch.setattr(execution.websocket.manager, "broadcast", _capture_broadcast)
    return events


async def test_run_and_evaluate_bypasses_graph_cache_when_pack_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An active pack forces use_cache=False (the model_override rule)."""
    captured: dict[str, Any] = {}
    events = _run_and_evaluate_stubs(monkeypatch, captured)

    await execution._run_and_evaluate(
        "wf",
        "run-pack-4",
        {"prompt": "hi"},
        SimpleNamespace(name="wf"),
        None,
        None,
        None,
        "langchain",
        "default",
        model_pack=_pack("pack-a", PACK_A_MODEL),
        model_pack_source="run",
    )

    assert captured["use_cache"] is False
    # A clean lifecycle proves the error path never fired.
    assert [event["type"] for event in events] == ["workflow_start", "workflow_end"]


async def test_run_and_evaluate_keeps_graph_cache_without_pack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    _run_and_evaluate_stubs(monkeypatch, captured)

    await execution._run_and_evaluate(
        "wf",
        "run-pack-5",
        {"prompt": "hi"},
        SimpleNamespace(name="wf"),
        None,
        None,
        None,
        "langchain",
        "default",
        model_pack=None,
    )

    assert captured["use_cache"] is True


# ---------------------------------------------------------------------------
# End-to-end regression — pack B after pack A never reuses pack A's compile
# ---------------------------------------------------------------------------


async def test_pack_b_run_after_pack_a_compile_does_not_reuse_pack_a_candidates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A pack-B run after a pack-A compile recompiles under pack B.

    Drives ``_run_and_evaluate`` with the real ``_stream_and_run`` and a
    real ``WorkflowRunner``; only ``compile_workflow`` is faked, capturing
    the tier-2 candidate chain visible at compile time (exactly what the
    LLM-node closures bake in).  Before the fix, run 1 cached its pack-A
    graph under a pack-blind key, so run 2 (pack B) and run 3 (default)
    silently reused pack-A candidates.
    """
    monkeypatch.setenv("AGENTIC_UI_SETTINGS_PATH", str(tmp_path / "ui-settings.json"))
    compiled_candidates: list[list[str]] = []

    def _fake_compile(
        config: WorkflowConfig,
        checkpointer: Any = None,
        trace_adapter: Any = None,
        **_kwargs: Any,
    ) -> _DummyGraph:
        compiled_candidates.append(ui_settings_module.tier_override_models(2))
        return _DummyGraph()

    wf_config = _wf_config("wf_pack_cache")
    monkeypatch.setattr(runner_module, "compile_workflow", _fake_compile)
    monkeypatch.setattr(
        runner_module, "load_workflow_config", lambda *_a, **_k: wf_config
    )

    runner = WorkflowRunner(checkpointer=object())
    _patch_stream_dependencies(monkeypatch, runner, config=wf_config)
    monkeypatch.setattr(execution, "run_logger", _StubRunLogger())

    async def _run(pack: ModelPack | None, run_id: str) -> None:
        await execution._run_and_evaluate(
            "wf_pack_cache",
            run_id,
            {},
            SimpleNamespace(name="wf_pack_cache"),
            None,
            None,
            None,
            "langchain",
            "default",
            model_pack=pack,
            model_pack_source="run" if pack is not None else "default",
        )

    # Run 1 compiles with pack A's candidates in scope …
    await _run(_pack("pack-a", PACK_A_MODEL), "run-pack-a")
    assert compiled_candidates == [[PACK_A_MODEL]]
    # … and never poisons the shared cache.
    assert runner._graph_cache == {}

    # Run 2 (pack B) must recompile with pack B's candidates, not reuse A's.
    await _run(_pack("pack-b", PACK_B_MODEL), "run-pack-b")
    assert compiled_candidates == [[PACK_A_MODEL], [PACK_B_MODEL]]
    assert runner._graph_cache == {}

    # Run 3 (default routing) compiles pristine candidates and may cache.
    await _run(None, "run-default")
    assert compiled_candidates == [[PACK_A_MODEL], [PACK_B_MODEL], []]
    assert len(runner._graph_cache) == 1


# ---------------------------------------------------------------------------
# _resolve_judge_model — pack judge_model vs env precedence
# ---------------------------------------------------------------------------


def test_judge_pack_judge_model_honored_when_env_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no judge env vars set, the pack's judge_model is used."""
    _clear_judge_env(monkeypatch)
    pack = _pack("pack-a", PACK_A_MODEL, judge_model="openai:pack-judge")

    assert execution._resolve_judge_model(pack) == "openai:pack-judge"


def test_judge_env_var_wins_over_pack_judge_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AGENTIC_JUDGE_MODEL (deployment config) outranks the pack."""
    _clear_judge_env(monkeypatch)
    monkeypatch.setenv("AGENTIC_JUDGE_MODEL", "anthropic:env-judge")
    pack = _pack("pack-a", PACK_A_MODEL, judge_model="openai:pack-judge")

    assert execution._resolve_judge_model(pack) == "anthropic:env-judge"


def test_judge_pack_wins_over_generic_tier_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pack's judge sits above the generic tier env fallbacks."""
    _clear_judge_env(monkeypatch)
    monkeypatch.setenv("AGENTIC_MODEL_TIER_2", "openai:tier2-fallback")
    pack = _pack("pack-a", PACK_A_MODEL, judge_model="openai:pack-judge")

    assert execution._resolve_judge_model(pack) == "openai:pack-judge"


def test_judge_tier_fallback_when_pack_has_no_judge_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_judge_env(monkeypatch)
    monkeypatch.setenv("AGENTIC_MODEL_TIER_2", "openai:tier2-fallback")

    assert (
        execution._resolve_judge_model(_pack("pack-a", PACK_A_MODEL))
        == "openai:tier2-fallback"
    )


def test_judge_whitespace_pack_judge_model_falls_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_judge_env(monkeypatch)
    monkeypatch.setenv("AGENTIC_MODEL_TIER_1", "openai:tier1-fallback")
    pack = _pack("pack-a", PACK_A_MODEL, judge_model="   ")

    assert execution._resolve_judge_model(pack) == "openai:tier1-fallback"


def test_judge_none_when_nothing_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_judge_env(monkeypatch)

    assert execution._resolve_judge_model(_pack("pack-a", PACK_A_MODEL)) is None
    assert execution._resolve_judge_model(None) is None


async def test_run_and_evaluate_passes_pack_to_judge_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The evaluation path builds the judge from the run's pack judge_model."""
    _clear_judge_env(monkeypatch)
    captured: dict[str, Any] = {}
    _run_and_evaluate_stubs(monkeypatch, captured)

    judge_models: list[str | None] = []

    class _CapturingJudge:
        def __init__(self, model: str | None = None) -> None:
            judge_models.append(model)

    scored = {
        key: None
        for key in (
            "rubric",
            "rubric_id",
            "rubric_version",
            "weighted_score",
            "overall_score",
            "grade",
            "passed",
            "pass_threshold",
            "criteria",
            "hard_gates",
            "hard_gate_failures",
            "step_scores",
            "judge_skipped",
            "judge_skip_reason",
            "judge_skip_code",
            "expected_text_present",
        )
    }
    monkeypatch.setattr(execution, "LLMJudge", _CapturingJudge)
    monkeypatch.setattr(
        execution, "score_workflow_result", lambda *_a, **_k: dict(scored)
    )

    await execution._run_and_evaluate(
        "wf",
        "run-pack-judge",
        {},
        SimpleNamespace(name="wf"),
        SimpleNamespace(
            enabled=True, rubric_id=None, rubric=None, enforce_hard_gates=True
        ),
        None,
        None,
        "langchain",
        "default",
        model_pack=_pack("pack-a", PACK_A_MODEL, judge_model="openai:pack-judge"),
        model_pack_source="run",
    )

    assert judge_models == ["openai:pack-judge"]
