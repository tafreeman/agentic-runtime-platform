"""LangGraph-path response sanitization.

The native engine masks secrets in model responses inside the shared LLM
client. The LangGraph engine, the default for named YAML workflows,
never calls that client, so a secret a model echoed there reached step
outputs, context, traces and run results unmasked (2026-09-22 audit,
finding H5).

These tests plant a secret in a LangGraph agent's response and follow it
through a real step node into everything the step records. All offline:
the agent is a stand-in, and no model or network is involved.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage

from agentic_v2.integrations.base import CanonicalEvent, TraceAdapter
from agentic_v2.langchain import graph as graph_module
from agentic_v2.langchain.config import StepConfig, WorkflowConfig
from agentic_v2.langchain.response_sanitization import sanitize_agent_response_text
from agentic_v2.settings import get_settings
from tests.fixtures.secrets_corpus import NEGATIVE_SECRETS, POSITIVE_SECRETS

_SECRET = next(value for value, kind in POSITIVE_SECRETS if kind == "github_token")


class _RecordingTrace(TraceAdapter):
    def __init__(self) -> None:
        self.events: list[CanonicalEvent] = []

    def emit(self, event: CanonicalEvent) -> None:
        self.events.append(event)


@pytest.fixture
def live_mode(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Leave placeholder mode, where both engines skip sanitization by design."""
    monkeypatch.setenv("AGENTIC_NO_LLM", "0")
    monkeypatch.delenv("AGENTIC_SANITIZE_AGENT_LOOP", raising=False)
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def _run_llm_step(
    monkeypatch: pytest.MonkeyPatch, response: str
) -> tuple[dict[str, Any], _RecordingTrace]:
    """Run one LLM step whose agent answers ``response``; return its state update."""

    class _Agent:
        def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
            return {"messages": [AIMessage(content=response)]}

    monkeypatch.setattr(graph_module, "create_agent", lambda *_a, **_k: _Agent())
    monkeypatch.setattr(
        graph_module, "get_model_candidates_for_tier", lambda *_a, **_k: ["stub:model"]
    )
    step = StepConfig(
        name="llm_step", agent="tier2_researcher", outputs={"report": "report_ctx"}
    )
    trace = _RecordingTrace()
    node = graph_module._make_step_node(
        step, WorkflowConfig(name="wf", steps=[step]), trace
    )
    state: dict[str, Any] = {
        "inputs": {},
        "context": {},
        "steps": {},
        "messages": [],
        "errors": [],
        "outputs": {},
        "current_step": "",
    }
    return dict(node(state)), trace


def test_a_secret_in_a_langgraph_response_is_masked_everywhere_the_step_records_it(
    live_mode: pytest.MonkeyPatch,
) -> None:
    update, trace = _run_llm_step(
        live_mode, f'{{"report": "deploy with {_SECRET} then verify"}}'
    )

    assert update["steps"]["llm_step"]["status"] == "success"
    assert "[REDACTED" in update["context"]["report_ctx"]
    recorded = {
        "context": update["context"],
        "step result": update["steps"],
        "message": [m.content for m in update["messages"]],
        "trace": trace.events,
    }
    leaked = [where for where, value in recorded.items() if _SECRET in repr(value)]
    assert leaked == [], f"secret reached: {leaked}"


def test_sanitization_off_leaves_the_response_untouched(
    live_mode: pytest.MonkeyPatch,
) -> None:
    """``AGENTIC_SANITIZE_AGENT_LOOP=0`` switches off both engines, not just one."""
    live_mode.setenv("AGENTIC_SANITIZE_AGENT_LOOP", "0")
    get_settings.cache_clear()

    update, _ = _run_llm_step(live_mode, f'{{"report": "deploy with {_SECRET}"}}')

    assert _SECRET in update["context"]["report_ctx"]


def test_placeholder_mode_leaves_the_response_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Under ``AGENTIC_NO_LLM`` the native path attaches no sanitizer; parity here."""
    monkeypatch.setenv("AGENTIC_NO_LLM", "1")

    assert sanitize_agent_response_text(f"token {_SECRET}") == f"token {_SECRET}"


@pytest.mark.parametrize(("secret", "kind"), POSITIVE_SECRETS)
def test_every_corpus_secret_is_masked_on_the_langgraph_path(
    live_mode: pytest.MonkeyPatch, secret: str, kind: str
) -> None:
    masked = sanitize_agent_response_text(f"the answer contains {secret} inline")

    assert secret not in masked, kind
    assert "[REDACTED" in masked


@pytest.mark.parametrize("benign", NEGATIVE_SECRETS)
def test_benign_text_passes_through_unchanged(
    live_mode: pytest.MonkeyPatch, benign: str
) -> None:
    assert sanitize_agent_response_text(benign) == benign
