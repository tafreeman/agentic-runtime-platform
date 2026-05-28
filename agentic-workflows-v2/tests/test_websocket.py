"""Tests for WebSocket ConnectionManager."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest
from agentic_v2.server.app import create_app
from agentic_v2.server.websocket import ConnectionManager
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


def _mock_websocket() -> AsyncMock:
    """Create a mock WebSocket with accept() and send_json() methods."""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


def _workflow_end_event(seq: int = 0) -> dict[str, Any]:
    """Return a valid ExecutionEvent payload for broadcast tests.

    The broadcast path validates events against the Pydantic union; tests that
    exercise broadcast mechanics must supply a real event shape. ``seq`` is
    threaded into ``run_id`` so tests that care about ordering can distinguish
    events.
    """
    return {
        "type": "workflow_end",
        "run_id": f"run-{seq}",
        "status": "success",
        "timestamp": "2026-04-21T00:00:00Z",
    }


class TestConnectionManagerConnect:
    """Tests for connect/disconnect lifecycle."""

    @pytest.mark.asyncio
    async def test_connect_adds_to_connections(self) -> None:
        """Connect() adds the websocket to the run_id's connection list."""
        mgr = ConnectionManager()
        ws = _mock_websocket()

        await mgr.connect(ws, "run-1")

        assert "run-1" in mgr.connections
        assert ws in mgr.connections["run-1"]

    @pytest.mark.asyncio
    async def test_connect_accepts_websocket(self) -> None:
        """Connect() calls websocket.accept()."""
        mgr = ConnectionManager()
        ws = _mock_websocket()

        await mgr.connect(ws, "run-1")

        ws.accept.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_multiple_connections_same_run(self) -> None:
        """Multiple websockets can connect to the same run."""
        mgr = ConnectionManager()
        ws1 = _mock_websocket()
        ws2 = _mock_websocket()

        await mgr.connect(ws1, "run-1")
        await mgr.connect(ws2, "run-1")

        assert len(mgr.connections["run-1"]) == 2


class TestConnectionManagerDisconnect:
    """Tests for disconnect behavior."""

    @pytest.mark.asyncio
    async def test_disconnect_removes_connection(self) -> None:
        """Disconnect() removes the websocket from the run's list."""
        mgr = ConnectionManager()
        ws1 = _mock_websocket()
        ws2 = _mock_websocket()
        await mgr.connect(ws1, "run-1")
        await mgr.connect(ws2, "run-1")

        mgr.disconnect(ws1, "run-1")

        assert ws1 not in mgr.connections["run-1"]
        assert ws2 in mgr.connections["run-1"]

    @pytest.mark.asyncio
    async def test_disconnect_cleans_up_empty_run(self) -> None:
        """Disconnect() removes the run_id key when list is empty."""
        mgr = ConnectionManager()
        ws = _mock_websocket()
        await mgr.connect(ws, "run-1")

        mgr.disconnect(ws, "run-1")

        assert "run-1" not in mgr.connections

    def test_disconnect_nonexistent_run_no_error(self) -> None:
        """Disconnect() is safe when run_id doesn't exist."""
        mgr = ConnectionManager()
        ws = _mock_websocket()
        # Should not raise
        mgr.disconnect(ws, "nonexistent-run")


class TestConnectionManagerBroadcast:
    """Tests for broadcast behavior."""

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all_connections(self) -> None:
        """Broadcast() sends the message to all connected websockets."""
        mgr = ConnectionManager()
        ws1 = _mock_websocket()
        ws2 = _mock_websocket()
        await mgr.connect(ws1, "run-1")
        await mgr.connect(ws2, "run-1")

        msg = _workflow_end_event()
        await mgr.broadcast("run-1", msg)

        ws1.send_json.assert_awaited_once_with(msg)
        ws2.send_json.assert_awaited_once_with(msg)

    @pytest.mark.asyncio
    async def test_broadcast_buffers_events(self) -> None:
        """Broadcast() adds events to the replay buffer."""
        mgr = ConnectionManager()
        msg = _workflow_end_event(seq=1)

        await mgr.broadcast("run-1", msg)

        assert len(mgr.event_buffers["run-1"]) == 1
        assert mgr.event_buffers["run-1"][0] == msg

    @pytest.mark.asyncio
    async def test_broadcast_buffer_respects_max_size(self) -> None:
        """Buffer evicts oldest event when max_buffer_size is exceeded."""
        mgr = ConnectionManager(max_buffer_size=3)

        for i in range(5):
            await mgr.broadcast("run-1", _workflow_end_event(seq=i))

        buf = mgr.event_buffers["run-1"]
        assert len(buf) == 3
        # Oldest events (0 and 1) should have been evicted
        assert buf[0]["run_id"] == "run-2"
        assert buf[2]["run_id"] == "run-4"

    @pytest.mark.asyncio
    async def test_broadcast_pushes_to_sse_listeners(self) -> None:
        """Broadcast() puts messages into registered SSE listener queues."""
        mgr = ConnectionManager()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=10)
        mgr.register_sse_listener("run-1", queue)

        msg = _workflow_end_event()
        await mgr.broadcast("run-1", msg)

        assert not queue.empty()
        assert queue.get_nowait() == msg

    @pytest.mark.asyncio
    async def test_broadcast_handles_full_sse_queue(self) -> None:
        """QueueFull on SSE listener logs warning but doesn't crash."""
        mgr = ConnectionManager()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
        mgr.register_sse_listener("run-1", queue)

        # Fill the queue
        await mgr.broadcast("run-1", _workflow_end_event(seq=1))
        # This should not raise even though queue is full
        await mgr.broadcast("run-1", _workflow_end_event(seq=2))

        # Queue still has only the first message
        assert queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_broadcast_tolerates_failed_ws(self) -> None:
        """Broadcast() tolerates a websocket that raises on send."""
        mgr = ConnectionManager()
        ws = _mock_websocket()
        ws.send_json = AsyncMock(side_effect=Exception("disconnected"))
        await mgr.connect(ws, "run-1")
        # Must not raise
        await mgr.broadcast("run-1", _workflow_end_event())

    @pytest.mark.asyncio
    async def test_broadcast_no_connections_no_error(self) -> None:
        """Broadcast() with no connected clients doesn't error."""
        mgr = ConnectionManager()
        await mgr.broadcast("run-1", _workflow_end_event())
        assert len(mgr.event_buffers["run-1"]) == 1

    @pytest.mark.asyncio
    async def test_broadcast_rejects_malformed_event(self) -> None:
        """Broadcast() refuses to emit events that fail Pydantic validation."""
        mgr = ConnectionManager()
        ws = _mock_websocket()
        await mgr.connect(ws, "run-1")

        with pytest.raises(ValueError):
            await mgr.broadcast("run-1", {"type": "bogus", "data": "test"})

        ws.send_json.assert_not_awaited()
        assert "run-1" not in mgr.event_buffers


class TestConnectionManagerReplay:
    """Tests for replay behavior."""

    @pytest.mark.asyncio
    async def test_replay_sends_buffered_events(self) -> None:
        """Replay() sends all buffered events to a new websocket."""
        mgr = ConnectionManager()
        # Pre-buffer some events
        for i in range(3):
            await mgr.broadcast("run-1", _workflow_end_event(seq=i))

        ws = _mock_websocket()
        await mgr.replay(ws, "run-1")

        assert ws.send_json.await_count == 3

    @pytest.mark.asyncio
    async def test_replay_stops_on_send_error(self) -> None:
        """Replay() breaks cleanly if send_json raises."""
        mgr = ConnectionManager()
        for i in range(3):
            await mgr.broadcast("run-1", _workflow_end_event(seq=i))

        ws = _mock_websocket()
        ws.send_json.side_effect = [None, RuntimeError("disconnected")]
        await mgr.replay(ws, "run-1")

        # Should have stopped after the error on second call
        assert ws.send_json.await_count == 2

    @pytest.mark.asyncio
    async def test_replay_no_buffer_no_error(self) -> None:
        """Replay() with no buffered events sends nothing."""
        mgr = ConnectionManager()
        ws = _mock_websocket()

        await mgr.replay(ws, "nonexistent-run")

        ws.send_json.assert_not_awaited()


class TestConnectionManagerSSE:
    """Tests for SSE listener registration."""

    def test_register_sse_listener(self) -> None:
        """register_sse_listener() adds queue to the run's listener list."""
        mgr = ConnectionManager()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        mgr.register_sse_listener("run-1", queue)

        assert queue in mgr._sse_listeners["run-1"]

    def test_unregister_sse_listener(self) -> None:
        """unregister_sse_listener() removes queue and cleans up."""
        mgr = ConnectionManager()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        mgr.register_sse_listener("run-1", queue)

        mgr.unregister_sse_listener("run-1", queue)

        assert "run-1" not in mgr._sse_listeners

    def test_unregister_nonexistent_no_error(self) -> None:
        """unregister_sse_listener() is safe for unknown run_id."""
        mgr = ConnectionManager()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        # Should not raise
        mgr.unregister_sse_listener("nonexistent", queue)


class TestConnectionManagerClearBuffer:
    """Tests for clear_buffer."""

    @pytest.mark.asyncio
    async def test_clear_buffer(self) -> None:
        """clear_buffer() removes the run's event buffer."""
        mgr = ConnectionManager()
        await mgr.broadcast("run-1", _workflow_end_event())
        assert "run-1" in mgr.event_buffers

        mgr.clear_buffer("run-1")

        assert "run-1" not in mgr.event_buffers

    def test_clear_buffer_nonexistent_no_error(self) -> None:
        """clear_buffer() is safe for unknown run_id."""
        mgr = ConnectionManager()
        mgr.clear_buffer("nonexistent")


class TestWebSocketEndpointAuth:
    """Integration tests for WebSocket auth and origin policy."""

    def test_websocket_accepts_authorization_header(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENTIC_API_KEY", "test-secret-key")
        app = create_app()

        with (
            TestClient(app) as client,
            client.websocket_connect(
                "/ws/execution/run-1",
                headers={
                    "Authorization": "Bearer test-secret-key",
                    "Origin": "http://testserver",
                },
            ),
        ):
            pass

    def test_websocket_accepts_x_api_key_header(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENTIC_API_KEY", "test-secret-key")
        app = create_app()

        with (
            TestClient(app) as client,
            client.websocket_connect(
                "/ws/execution/run-1",
                headers={
                    "Origin": "http://testserver",
                    "X-API-Key": "test-secret-key",
                },
            ),
        ):
            pass

    def test_websocket_rejects_missing_token_when_auth_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENTIC_API_KEY", "test-secret-key")
        app = create_app()

        with (
            TestClient(app) as client,
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(
                "/ws/execution/run-1",
                headers={"Origin": "http://testserver"},
            ),
        ):
            pass

    def test_websocket_rejects_query_token_auth(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENTIC_API_KEY", "test-secret-key")
        app = create_app()

        with (
            TestClient(app) as client,
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(
                "/ws/execution/run-1?token=test-secret-key",
                headers={"Origin": "http://testserver"},
            ),
        ):
            pass

    def test_websocket_rejects_invalid_bearer_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENTIC_API_KEY", "test-secret-key")
        app = create_app()

        with (
            TestClient(app) as client,
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(
                "/ws/execution/run-1",
                headers={
                    "Origin": "http://testserver",
                    "Authorization": "Bearer wrong-key",
                },
            ),
        ):
            pass

    def test_websocket_rejects_disallowed_origin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("AGENTIC_API_KEY", raising=False)
        monkeypatch.setenv("AGENTIC_CORS_ORIGINS", "https://allowed.example")
        app = create_app()

        with (
            TestClient(app) as client,
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(
                "/ws/execution/run-1",
                headers={"Origin": "https://evil.example"},
            ),
        ):
            pass
