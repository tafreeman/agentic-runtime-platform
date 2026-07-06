"""Tests for WebSocket ConnectionManager."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any
from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from agentic_v2.server import websocket as websocket_module
from agentic_v2.server.app import create_app
from agentic_v2.server.auth import AuthThrottle
from agentic_v2.server.websocket import ConnectionManager


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


class TestConnectionManagerRetention:
    """Tests for the grace-delayed clear scheduled by terminal-event broadcasts.

    ``broadcast()`` never clears immediately at ``workflow_end``/``error`` --
    late-joining clients legitimately replay shortly after completion. It
    instead schedules ``clear_buffer`` after ``retention_seconds``. Tests
    inject a tiny ``retention_seconds`` (well under the 0.5s slow-test
    threshold) rather than sleeping for the real default (3600s).
    """

    _TINY_RETENTION = 0.05

    @pytest.mark.asyncio
    async def test_buffer_survives_within_grace_window(self) -> None:
        """The buffer is NOT cleared immediately after a workflow_end broadcast."""
        mgr = ConnectionManager(retention_seconds=self._TINY_RETENTION)

        await mgr.broadcast("run-1", _workflow_end_event())

        assert "run-1" in mgr.event_buffers

    @pytest.mark.asyncio
    async def test_buffer_cleared_after_retention_expires(self) -> None:
        """The buffer IS cleared once retention_seconds has elapsed."""
        mgr = ConnectionManager(retention_seconds=self._TINY_RETENTION)

        await mgr.broadcast("run-1", _workflow_end_event())
        await asyncio.sleep(self._TINY_RETENTION * 4)

        assert "run-1" not in mgr.event_buffers

    @pytest.mark.asyncio
    async def test_error_event_also_schedules_clear(self) -> None:
        """A top-level 'error' event is terminal too and schedules a clear."""
        mgr = ConnectionManager(retention_seconds=self._TINY_RETENTION)
        error_event = {
            "type": "error",
            "run_id": "run-1",
            "error": "boom",
            "timestamp": "2026-04-21T00:00:00Z",
        }

        await mgr.broadcast("run-1", error_event)
        assert "run-1" in mgr.event_buffers  # still within grace window

        await asyncio.sleep(self._TINY_RETENTION * 4)

        assert "run-1" not in mgr.event_buffers

    @pytest.mark.asyncio
    async def test_non_terminal_event_does_not_schedule_clear(self) -> None:
        """A non-terminal event (e.g. step_start) never schedules a clear."""
        mgr = ConnectionManager(retention_seconds=self._TINY_RETENTION)
        step_event = {
            "type": "step_start",
            "run_id": "run-1",
            "step": "step-a",
            "timestamp": "2026-04-21T00:00:00Z",
        }

        await mgr.broadcast("run-1", step_event)
        await asyncio.sleep(self._TINY_RETENTION * 4)

        # Long past what would have been the retention window — buffer
        # must still be present because nothing scheduled a clear.
        assert "run-1" in mgr.event_buffers
        assert "run-1" not in mgr._pending_clears

    @pytest.mark.asyncio
    async def test_second_terminal_event_reschedules_not_stacks(self) -> None:
        """A second terminal event for the same run replaces the pending timer."""
        mgr = ConnectionManager(retention_seconds=self._TINY_RETENTION)

        await mgr.broadcast("run-1", _workflow_end_event())
        first_task = mgr._pending_clears["run-1"]

        await mgr.broadcast("run-1", _workflow_end_event())
        second_task = mgr._pending_clears["run-1"]

        assert first_task is not second_task
        # cancel() only *requests* cancellation; yield once so the event loop
        # can actually process it before asserting the resulting state.
        await asyncio.sleep(0)
        assert first_task.cancelled() or first_task.done()

        await asyncio.sleep(self._TINY_RETENTION * 4)
        assert "run-1" not in mgr.event_buffers

    @pytest.mark.asyncio
    async def test_clears_durable_store_too(self) -> None:
        """The delayed clear also purges the durable replay store (via clear_buffer)."""
        from agentic_v2.server.replay_store import InMemoryReplayStore

        store = InMemoryReplayStore(max_events=100)
        mgr = ConnectionManager(
            replay_store=store, retention_seconds=self._TINY_RETENTION
        )

        await mgr.broadcast("run-1", _workflow_end_event())
        await asyncio.sleep(self._TINY_RETENTION * 4)

        assert await store.get_events("run-1") == []

    def test_schedule_without_running_loop_is_safe(self) -> None:
        """_schedule_delayed_clear() is a no-op outside a running event loop.

        Mirrors clear_buffer()'s own no-event-loop fallback: safe to
        call from a sync context (e.g. a non-async unit test) without
        raising.
        """
        mgr = ConnectionManager(retention_seconds=self._TINY_RETENTION)
        mgr._schedule_delayed_clear("run-1")  # must not raise
        assert "run-1" not in mgr._pending_clears

    @pytest.mark.asyncio
    async def test_broadcast_tolerates_scheduling_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Broadcast() never fails even if _schedule_delayed_clear() itself raises.

        Retention housekeeping is best-effort by contract — a bug in the
        scheduling path must not take down the broadcast path that every
        WebSocket/SSE client depends on.
        """
        mgr = ConnectionManager(retention_seconds=self._TINY_RETENTION)

        def _raising_schedule(run_id: str) -> None:
            raise RuntimeError("scheduling exploded")

        monkeypatch.setattr(mgr, "_schedule_delayed_clear", _raising_schedule)

        # Must not raise.
        await mgr.broadcast("run-1", _workflow_end_event())
        # The event itself was still buffered/broadcast normally.
        assert "run-1" in mgr.event_buffers

    @pytest.mark.asyncio
    async def test_delayed_clear_logs_and_swallows_clear_buffer_failure(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A clear_buffer() failure inside the delayed task is logged, not raised.

        The scheduled task runs detached from any caller — an unhandled
        exception there would only surface as an "exception was never
        retrieved" warning at GC time, silently defeating retention. It
        must be caught and logged instead.
        """
        mgr = ConnectionManager(retention_seconds=self._TINY_RETENTION)

        def _raising_clear_buffer(run_id: str) -> None:
            raise RuntimeError("clear_buffer exploded")

        monkeypatch.setattr(mgr, "clear_buffer", _raising_clear_buffer)

        with caplog.at_level("WARNING"):
            await mgr.broadcast("run-1", _workflow_end_event())
            await asyncio.sleep(self._TINY_RETENTION * 4)

        warning_text = " ".join(
            record.message for record in caplog.records if record.levelname == "WARNING"
        )
        assert "_delayed_clear failed" in warning_text
        assert "clear_buffer exploded" in warning_text

    @pytest.mark.asyncio
    async def test_resolve_retention_seconds_uses_constructor_value(self) -> None:
        """An explicit constructor value bypasses settings entirely."""
        mgr = ConnectionManager(retention_seconds=42.0)
        assert mgr._resolve_retention_seconds() == 42.0

    @pytest.mark.asyncio
    async def test_resolve_retention_seconds_reads_settings_when_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When no constructor value is given, the setting is read lazily."""
        from agentic_v2.settings import get_settings

        monkeypatch.setenv("REPLAY_STORE_RETENTION_SECONDS", "123")
        get_settings.cache_clear()
        try:
            mgr = ConnectionManager()
            assert mgr._resolve_retention_seconds() == 123.0
        finally:
            get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_resolve_retention_seconds_falls_back_on_settings_error(self) -> None:
        """A broken settings load degrades to the hardcoded fallback, not a raise.

        ``get_settings`` is imported lazily inside ``_resolve_retention_seconds``
        (``from ..settings import get_settings``), so the module attribute is
        replaced directly rather than via ``monkeypatch.setattr`` -- the
        ``lru_cache``-wrapped original is restored manually in ``finally`` so
        the other autouse settings-cache-reset fixtures (which call
        ``get_settings.cache_clear()`` in their own teardown) never see a
        plain function without that attribute, regardless of fixture
        teardown order.
        """
        import agentic_v2.server.websocket as ws_module
        import agentic_v2.settings as settings_module

        mgr = ConnectionManager()
        original_get_settings = settings_module.get_settings

        def _raising_get_settings() -> Any:
            raise RuntimeError("settings broken")

        settings_module.get_settings = _raising_get_settings  # type: ignore[assignment]
        try:
            assert (
                mgr._resolve_retention_seconds()
                == ws_module._FALLBACK_RETENTION_SECONDS
            )
        finally:
            settings_module.get_settings = original_get_settings  # type: ignore[assignment]


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


class TestWebSocketEndpointAuthThrottle:
    """Brute-force throttle must apply to the WebSocket auth path (C-05)."""

    _THRESHOLD = 3
    _BAD_HEADERS = {
        "Origin": "http://testserver",
        "Authorization": "Bearer wrong-key",
    }

    def _attempt(self, client: TestClient) -> None:
        """Make one failed WebSocket auth attempt; the server closes the socket."""
        with suppress(WebSocketDisconnect):
            with client.websocket_connect(
                "/ws/execution/run-1", headers=self._BAD_HEADERS
            ):
                pass

    def test_locks_out_after_threshold_failures(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The (N+1)th failed attempt is rejected by the throttle, not the token check.

        After N failures lock the IP, the next handshake must be closed before
        the credential check runs — so ``is_token_authorized`` (the token-store
        interaction) is not invoked again on the locked attempt.
        """
        monkeypatch.setenv("AGENTIC_API_KEY", "test-secret-key")
        app = create_app()
        # Inject a fresh throttle with a small threshold so the test is fast.
        app.state.auth_throttle = AuthThrottle(
            window=60.0, threshold=self._THRESHOLD, lockout=300.0
        )

        # Count token-store interactions to prove the locked attempt skips it.
        real_is_token_authorized = websocket_module.is_token_authorized
        calls: list[int] = []

        def _counting_is_token_authorized(
            token: str | None, api_key: str | None
        ) -> bool:
            calls.append(1)
            return real_is_token_authorized(token, api_key)

        monkeypatch.setattr(
            websocket_module, "is_token_authorized", _counting_is_token_authorized
        )

        with TestClient(app) as client:
            # N failures — each reaches and fails the credential check.
            for _ in range(self._THRESHOLD):
                self._attempt(client)
            calls_before_lockout = len(calls)
            assert calls_before_lockout == self._THRESHOLD

            # The (N+1)th attempt is now rejected by the lockout, before the
            # credential check — so no additional token-store interaction occurs.
            self._attempt(client)
            assert len(calls) == calls_before_lockout

    def test_first_n_attempts_reach_credential_check(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Below the threshold, attempts still hit the credential check (not
        throttled)."""
        monkeypatch.setenv("AGENTIC_API_KEY", "test-secret-key")
        app = create_app()
        app.state.auth_throttle = AuthThrottle(
            window=60.0, threshold=self._THRESHOLD, lockout=300.0
        )

        throttle = app.state.auth_throttle
        with TestClient(app) as client:
            for _ in range(self._THRESHOLD - 1):
                self._attempt(client)

        # Not yet locked: failures recorded but below threshold.
        locked, _retry = throttle.is_locked("testclient")
        assert locked is False
