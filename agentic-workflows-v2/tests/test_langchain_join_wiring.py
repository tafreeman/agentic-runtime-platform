"""LangGraph adapter join semantics: every step runs once, after all its deps.

The adapter used to wire one single-source edge per ``depends_on`` entry.
LangGraph runs a node once per superstep in which any incoming edge fires, so
a join whose dependencies finished at different depths ran several times —
the first time with the slower dependencies' outputs still ``None``. Loop
steps fired their dependents on every iteration as well. The native
executor's in-degree counting runs each step exactly once; these tests hold
the adapter to the same rule (ADR-062).
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from agentic_v2.langchain import graph as graph_module
from agentic_v2.langchain.config import StepConfig, WorkflowConfig
from agentic_v2.langchain.graph_wiring import (
    build_loop_exit_map,
    is_loop_exit_node,
    loop_exit_node_name,
)
from agentic_v2.langchain.runner import WorkflowRunner, _is_loop_exit_event
from agentic_v2.langchain.state import initial_state

_STEP_RE = re.compile(r"^Step: (\w+)$", flags=re.MULTILINE)
_INPUTS_RE = re.compile(r"^Inputs:\n(.*?)\n\nPlease complete", flags=re.DOTALL | re.M)


class _CountingAgent:
    """Canned agent: replies ``{"out": "<step>#<call>"}`` and records inputs."""

    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()
        self.inputs: dict[str, list[dict[str, Any]]] = {}

    def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        message = payload["messages"][-1].content
        name = _STEP_RE.search(message).group(1)
        self.calls[name] += 1
        self.inputs.setdefault(name, []).append(
            json.loads(_INPUTS_RE.search(message).group(1))
        )
        reply = {"out": f"{name}#{self.calls[name]}"}
        return {"messages": [AIMessage(content=json.dumps(reply))]}


@pytest.fixture
def agent(monkeypatch: pytest.MonkeyPatch) -> _CountingAgent:
    canned = _CountingAgent()
    monkeypatch.setattr(graph_module, "create_agent", lambda *_a, **_k: canned)
    monkeypatch.setattr(
        graph_module, "get_model_candidates_for_tier", lambda *_a, **_k: ["canned"]
    )
    return canned


def _step(name: str, *deps: str, **fields: Any) -> StepConfig:
    """An LLM step that takes each dependency's ``out`` as an input."""
    return StepConfig(
        name=name,
        agent="tier1_coder",
        depends_on=list(deps),
        inputs={dep: f"${{steps.{dep}.outputs.out}}" for dep in deps},
        outputs={"out": f"{name}_out"},
        **fields,
    )


def _run(config: WorkflowConfig, **inputs: Any) -> dict[str, Any]:
    graph = graph_module.compile_workflow(config)
    return asyncio.run(graph.ainvoke(initial_state(inputs)))


def test_uneven_depth_join_runs_once_with_every_dependency(
    agent: _CountingAgent,
) -> None:
    # join waits on b (depth 1), c (depth 1) and e (depth 3); tail joins a
    # step with one of its own ancestors.
    config = WorkflowConfig(
        name="uneven_join",
        steps=[
            _step("a"),
            _step("b", "a"),
            _step("c", "a"),
            _step("d", "b"),
            _step("e", "d"),
            _step("join", "b", "c", "e"),
            _step("tail", "join", "a"),
        ],
    )

    final = _run(config)

    assert agent.calls == Counter(
        {name: 1 for name in ("a", "b", "c", "d", "e", "join", "tail")}
    )
    assert agent.inputs["join"] == [{"b": "b#1", "c": "c#1", "e": "e#1"}]
    assert agent.inputs["tail"] == [{"join": "join#1", "a": "a#1"}]
    assert final["steps"]["tail"]["status"] == "success"


def test_join_on_a_skipped_conditional_dependency_still_runs_once(
    agent: _CountingAgent,
) -> None:
    config = WorkflowConfig(
        name="conditional_join",
        steps=[
            _step("a"),
            _step("gated", "a", when="${inputs.flag} == 'yes'"),
            _step("deep1", "a"),
            _step("deep2", "deep1"),
            _step("join", "gated", "deep2"),
        ],
    )

    final = _run(config, flag="no")

    assert final["steps"]["gated"]["status"] == "skipped"
    assert agent.calls == Counter({"a": 1, "deep1": 1, "deep2": 1, "join": 1})
    assert agent.inputs["join"] == [{"gated": None, "deep2": "deep2#1"}]


def _loop_config(**loop_fields: Any) -> WorkflowConfig:
    return WorkflowConfig(
        name="loop_join",
        steps=[
            _step("seed"),
            _step(
                "loop",
                "seed",
                loop_until="${steps.loop.outputs.out} == 'never'",
                loop_max=3,
                **loop_fields,
            ),
            _step("side", "seed"),
            _step("after_loop", "loop"),
            _step("join_loop", "loop", "side"),
            _step("tail", "loop", "after_loop"),
        ],
    )


def test_loop_dependents_run_once_after_the_last_iteration(
    agent: _CountingAgent,
) -> None:
    final = _run(_loop_config())

    assert agent.calls == Counter(
        {"seed": 1, "loop": 3, "side": 1, "after_loop": 1, "join_loop": 1, "tail": 1}
    )
    # Dependents see the final iteration, never an intermediate one.
    assert agent.inputs["after_loop"] == [{"loop": "loop#3"}]
    assert agent.inputs["join_loop"] == [{"loop": "loop#3", "side": "side#1"}]
    assert agent.inputs["tail"] == [{"loop": "loop#3", "after_loop": "after_loop#1"}]
    assert final["steps"]["loop"]["loop_iteration"] == 3
    assert not any(is_loop_exit_node(name) for name in final["steps"])


def test_skipped_loop_step_still_releases_its_dependents(
    agent: _CountingAgent,
) -> None:
    final = _run(_loop_config(when="${inputs.flag} == 'yes'"), flag="no")

    assert final["steps"]["loop"]["status"] == "skipped"
    assert agent.calls["loop"] == 0
    for name in ("after_loop", "join_loop", "tail"):
        assert agent.calls[name] == 1, name


def test_terminal_loop_step_ends_without_an_exit_node(
    agent: _CountingAgent,
) -> None:
    config = WorkflowConfig(
        name="terminal_loop",
        steps=[
            _step("seed"),
            _step(
                "loop",
                "seed",
                loop_until="${steps.loop.outputs.out} == 'loop#2'",
                loop_max=5,
            ),
        ],
    )

    final = _run(config)

    assert build_loop_exit_map(config) == {}
    assert agent.calls == Counter({"seed": 1, "loop": 2})
    assert final["steps"]["loop"]["loop_iteration"] == 2


def test_loop_exit_map_covers_only_loop_steps_with_dependents() -> None:
    config = _loop_config()

    assert build_loop_exit_map(config) == {"loop": loop_exit_node_name("loop")}
    assert is_loop_exit_node(loop_exit_node_name("loop"))
    assert not is_loop_exit_node("loop")


def test_runner_hides_loop_exit_nodes_from_stream_and_progress(
    agent: _CountingAgent,
) -> None:
    runner = WorkflowRunner()
    config = _loop_config()

    async def _collect() -> tuple[list[str], list[str]]:
        streamed = [
            name
            async for event in runner.astream(config, use_cache=False)
            for name in event
        ]
        progress: list[str] = []

        async def _on_update(event: dict[str, Any]) -> None:
            progress.append(event.get("step", ""))

        await runner.run(config, use_cache=False, on_update=_on_update)
        return streamed, progress

    streamed, progress = asyncio.run(_collect())

    assert streamed.count("loop") == 3
    assert "tail" in streamed
    assert "tail" in progress
    assert not any(is_loop_exit_node(name) for name in streamed + progress)


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ({loop_exit_node_name("loop"): None}, True),
        ({"loop": {}, loop_exit_node_name("loop"): None}, False),
        ({"loop": {}}, False),
        ({}, False),
        (("updates", {}), False),
    ],
)
def test_is_loop_exit_event(event: Any, expected: bool) -> None:
    assert _is_loop_exit_event(event) is expected
