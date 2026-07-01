"""Tests for the single-tool dispatch error handling in ``engine.tool_execution``.

Covers ARP-8: :func:`agentic_v2.engine.tool_execution._dispatch_single_tool_call`
must log the traceback (not just the stringified error) when a tool raises, and
must never swallow ``asyncio.CancelledError`` — cancellation must keep
propagating out of the dispatcher rather than being serialized as a tool error.

All offline, no network, no LLM calls.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import pytest

from agentic_v2.engine.tool_execution import _dispatch_single_tool_call
from agentic_v2.tools.base import BaseTool, ToolResult

# Async tests are auto-detected (asyncio_mode = "auto" in pyproject.toml).


class _RaisingTool(BaseTool):
    """Tier-0 tool whose ``execute`` raises a configurable exception."""

    def __init__(self, exc: BaseException, *, name: str = "raiser") -> None:
        super().__init__()
        self._exc = exc
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "Tool that always raises for error-handling tests."

    @property
    def parameters(self) -> dict[str, Any]:
        return {}

    async def execute(self, **kwargs: Any) -> ToolResult:
        raise self._exc


async def _dispatch(tool: BaseTool, args: dict[str, Any] | None = None) -> str:
    """Drive the engine dispatch point directly, returning the raw JSON text."""
    return await _dispatch_single_tool_call(tool, tool.name, args or {})


@pytest.mark.unit
async def test_tool_exception_logs_traceback(caplog: pytest.LogCaptureFixture) -> None:
    """A tool raising ValueError logs a full traceback via logger.exception."""
    tool = _RaisingTool(ValueError("boom"), name="failing_tool")

    with caplog.at_level(logging.ERROR, logger="agentic_v2.engine.tool_execution"):
        result_text = await _dispatch(tool)

    # The LLM-facing serialized error is unchanged (behavior-preserving).
    payload = json.loads(result_text)
    assert payload["success"] is False
    assert "failing_tool" in payload["error"]
    assert "boom" in payload["error"]

    # The traceback was actually logged, not just the stringified exception.
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None
    formatted = caplog.text
    assert "Traceback" in formatted
    assert "ValueError" in formatted
    assert "boom" in formatted


@pytest.mark.unit
async def test_tool_cancelled_error_propagates() -> None:
    """CancelledError from a tool is never serialized — it propagates."""
    tool = _RaisingTool(asyncio.CancelledError(), name="cancelled_tool")

    with pytest.raises(asyncio.CancelledError):
        await _dispatch(tool)


@pytest.mark.unit
async def test_tool_keyboard_interrupt_propagates() -> None:
    """KeyboardInterrupt from a tool is never serialized — it propagates.

    Both ``asyncio.CancelledError`` and ``KeyboardInterrupt`` derive from
    ``BaseException`` (not ``Exception``), so the dispatcher's
    ``except Exception`` already does not catch them today; this test pins
    that behavior so a future refactor to a broader ``except`` is caught.
    """
    tool = _RaisingTool(KeyboardInterrupt(), name="interrupted_tool")

    with pytest.raises(KeyboardInterrupt):
        await _dispatch(tool)


@pytest.mark.unit
async def test_successful_tool_call_does_not_log_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The happy path stays silent — no error-level noise on success."""

    class _EchoTool(BaseTool):
        @property
        def name(self) -> str:
            return "echo"

        @property
        def description(self) -> str:
            return "Echoes input."

        @property
        def parameters(self) -> dict[str, Any]:
            return {}

        async def execute(self, **kwargs: Any) -> ToolResult:
            return ToolResult(success=True, data={"ok": True}, tool_name=self.name)

    with caplog.at_level(logging.ERROR, logger="agentic_v2.engine.tool_execution"):
        result_text = await _dispatch(_EchoTool())

    payload = json.loads(result_text)
    assert payload["success"] is True
    assert not any(r.levelno >= logging.ERROR for r in caplog.records)
