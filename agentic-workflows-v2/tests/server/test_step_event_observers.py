"""Tests for per-step observer filtering of websocket/scoring step events."""

from __future__ import annotations

from typing import Any

import pytest

import agentic_v2.server.execution  # noqa: F401  (installs _stream_dict_ref)
from agentic_v2.server import _step_events, websocket


class _RecordingScoringListener:
    def __init__(self):
        self.updates: list[dict[str, Any]] = []

    async def handle_update(self, event: dict[str, Any]) -> None:
        self.updates.append(event)


@pytest.fixture()
def broadcasts(monkeypatch):
    sent: list[dict[str, Any]] = []

    async def _record(run_id: str, event: dict[str, Any]) -> None:
        sent.append(event)

    monkeypatch.setattr(websocket.manager, "broadcast", _record)
    return sent


async def _drive_step(
    broadcasts_list,
    scoring: _RecordingScoringListener,
    step_observers,
) -> None:
    common = {
        "aggregated_state": {"steps": {}},
        "run_id": "run-1",
        "tenant_id": "default",
        "now": "2026-07-06T12:00:00+00:00",
        "step_start_times": {},
        "last_status_by_step": {},
        "scoring_listener": scoring,
        "step_observers": step_observers,
    }
    await _step_events._process_streamed_step(
        "review", {"status": "running", "inputs": {}}, **common
    )
    await _step_events._process_streamed_step(
        "review",
        {"status": "success", "outputs": {"review": "ok"}, "duration_ms": 5},
        **common,
    )


class TestStepEventObserverFiltering:
    async def test_default_none_emits_websocket_and_scoring(self, broadcasts):
        scoring = _RecordingScoringListener()
        await _drive_step(broadcasts, scoring, step_observers=None)

        assert [e["type"] for e in broadcasts] == ["step_start", "step_end"]
        assert len(scoring.updates) == 1

    async def test_explicit_channels_pass_through(self, broadcasts):
        scoring = _RecordingScoringListener()
        await _drive_step(
            broadcasts,
            scoring,
            step_observers={"review": ["websocket", "scoring"]},
        )
        assert [e["type"] for e in broadcasts] == ["step_start", "step_end"]
        assert len(scoring.updates) == 1

    async def test_omitting_websocket_suppresses_broadcasts_only(self, broadcasts):
        scoring = _RecordingScoringListener()
        await _drive_step(broadcasts, scoring, step_observers={"review": ["scoring"]})
        assert broadcasts == []
        assert len(scoring.updates) == 1

    async def test_omitting_scoring_suppresses_score_updates_only(self, broadcasts):
        scoring = _RecordingScoringListener()
        await _drive_step(broadcasts, scoring, step_observers={"review": ["websocket"]})
        assert [e["type"] for e in broadcasts] == ["step_start", "step_end"]
        assert scoring.updates == []

    async def test_step_without_entry_defaults_to_all_channels(self, broadcasts):
        scoring = _RecordingScoringListener()
        await _drive_step(broadcasts, scoring, step_observers={"other_step": []})
        assert [e["type"] for e in broadcasts] == ["step_start", "step_end"]
        assert len(scoring.updates) == 1
