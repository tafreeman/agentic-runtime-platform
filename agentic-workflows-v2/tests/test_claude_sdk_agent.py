"""Regression tests for ``ClaudeSDKAgent``.

The wrapper dispatched on ``message.type == "result"``, but no
``claude-agent-sdk`` message class carries a ``.type`` attribute -- they are
plain dataclasses. Every call therefore raised ``AttributeError`` on the first
message of the run, so the agent was entirely non-functional rather than
subtly wrong.

Also covers the credential scrub: the SDK spawns the Claude Code CLI with
``{**os.environ, **options.env}``, and ``agentic_v2.models.secrets`` puts
``ANTHROPIC_API_KEY`` into ``os.environ`` during backend auto-configuration, so
without an explicit blank the child authenticates with the API key instead of
the subscription sign-in.

Offline: ``query`` is monkeypatched and the SDK's own dataclasses are replayed.
Skips without the optional ``claude`` extra; the ``claude-subscription-tests``
CI job installs it and hard-guards the import.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("claude_agent_sdk", reason="requires the [claude] extra")

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
)

from agentic_v2.agents.implementations import claude_sdk_agent as mod
from agentic_v2.agents.implementations.claude_sdk_agent import (
    ClaudeSDKAgent,
)


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the inbound sanitizer on its documented no-op path."""
    monkeypatch.setenv("AGENTIC_NO_LLM", "1")


def assistant(text: str) -> AssistantMessage:
    return AssistantMessage(content=[TextBlock(text=text)], model="claude-opus-5")


def result(
    *, text: str | None, is_error: bool = False, errors: list[str] | None = None
) -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=is_error,
        num_turns=1,
        session_id="s1",
        result=text,
        errors=errors,
    )


def patch_query(monkeypatch: pytest.MonkeyPatch, *messages: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def _query(*, prompt: str, options: Any):  # type: ignore[no-untyped-def]
        calls.append({"prompt": prompt, "options": options})
        for message in messages:
            yield message

    monkeypatch.setattr(mod, "query", _query)
    return calls


async def test_run_returns_the_final_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """The regression: this raised AttributeError on the first message."""
    patch_query(monkeypatch, assistant("thinking out loud"), result(text="done"))
    assert await ClaudeSDKAgent().run("go") == "done"


async def test_run_falls_back_to_assistant_text_without_a_result_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run cut short by max turns still returns what the model produced."""
    patch_query(monkeypatch, assistant("partial "), assistant("answer"))
    assert await ClaudeSDKAgent().run("go") == "partial answer"


async def test_run_raises_on_a_failed_run(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_query(monkeypatch, result(text=None, is_error=True, errors=["boom"]))
    with pytest.raises(RuntimeError, match="boom"):
        await ClaudeSDKAgent().run("go")


async def test_default_model_is_current(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = patch_query(monkeypatch, result(text="ok"))
    await ClaudeSDKAgent().run("go")
    assert calls[0]["options"].model == "claude-opus-5"


async def test_cli_subprocess_cannot_inherit_an_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-never-reach-the-cli")
    calls = patch_query(monkeypatch, result(text="ok"))
    await ClaudeSDKAgent().run("go")
    assert calls[0]["options"].env["ANTHROPIC_API_KEY"] == ""


async def test_explicit_env_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = patch_query(monkeypatch, result(text="ok"))
    await ClaudeSDKAgent(env={"ANTHROPIC_API_KEY": "deliberate"}).run("go")
    assert calls[0]["options"].env["ANTHROPIC_API_KEY"] == "deliberate"


async def test_stream_yields_sdk_messages_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Consumers dispatch with isinstance; there are no (type, content) tuples."""
    patch_query(monkeypatch, assistant("a"), result(text="b"))
    seen = [message async for message in ClaudeSDKAgent().stream("go")]
    assert [type(m).__name__ for m in seen] == ["AssistantMessage", "ResultMessage"]
