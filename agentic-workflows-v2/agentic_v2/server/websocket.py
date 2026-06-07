"""WebSocket and SSE streaming for real-time workflow execution updates.

Provides :class:`ConnectionManager`, a pub/sub hub that fans out execution
events (``step_start``, ``step_end``, ``workflow_end``, etc.) to:

* **WebSocket clients** -- connected via ``/ws/execution/{run_id}``.
  Each client is associated with exactly one ``run_id``.  Late-connecting
  clients receive a replay of buffered events so they can reconstruct
  current workflow state.
* **SSE listeners** -- registered via :meth:`ConnectionManager.register_sse_listener`
  using an ``asyncio.Queue``.  The ``GET /runs/{run_id}/stream`` endpoint
  in the workflows router consumes this queue.

Architecture:
    ``broadcast(run_id, event)`` is the single write path.  It appends
    the event to a per-run circular buffer (default 500 events), then
    pushes to all WebSocket connections *and* all SSE queues for that
    ``run_id``.  Disconnection cleanup is handled per-client; the buffer
    persists until :meth:`ConnectionManager.clear_buffer` is called.

    Events are also persisted to a durable :class:`ReplayStore` backend
    (Redis, SQLite, or in-memory) so that late-connecting clients can
    recover full event history after a server restart or across workers.
    Persistence failures are logged but never propagate to the broadcast
    path — the broadcast always succeeds as long as WebSocket send succeeds.

A module-level singleton ``manager`` is used by both the WebSocket
endpoint and the workflow execution background task.  Call
``await manager.initialize_store()`` once at application startup to
connect the configured backend.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..contracts.events import validate_event
from ..integrations.otel import is_tracing_enabled
from .auth import (
    _get_api_key,
    extract_websocket_token,
    is_token_authorized,
    is_websocket_origin_allowed,
    websocket_uses_query_token,
)
from .middleware.tracing import build_traceparent
from .replay_store import InMemoryReplayStore, ReplayStore

logger = logging.getLogger(__name__)
router = APIRouter(tags=["streaming"])


class ConnectionManager:
    """Pub/sub hub for WebSocket connections and SSE listeners, keyed by run ID.

    Maintains three per-run data structures:

    * ``connections`` -- list of accepted ``WebSocket`` instances.
    * ``event_buffers`` -- circular list of JSON-serializable event dicts
      (capped at ``max_buffer_size``) used as a hot in-process cache.
    * ``_sse_listeners`` -- list of ``asyncio.Queue`` instances that
      receive the same events for Server-Sent Event streaming.

    Additionally, events are durably persisted to a :class:`ReplayStore`
    backend so that late-connecting clients can reconstruct state after a
    server restart or when connecting to a different worker.  The in-memory
    ``event_buffers`` act as a hot cache; the store is authoritative for
    replay when it has data.

    Call :meth:`initialize_store` once at application startup to connect
    the configured backend.

    Attributes:
        connections: Mapping of ``run_id`` to active WebSocket list.
        event_buffers: Mapping of ``run_id`` to bounded deque of event dicts.
        _sse_listeners: Mapping of ``run_id`` to SSE queue list.
    """

    def __init__(
        self,
        max_buffer_size: int = 500,
        replay_store: ReplayStore | None = None,
    ):
        """Initialize the connection manager.

        Args:
            max_buffer_size: Maximum number of events to retain in the
                per-run in-memory replay buffer.  Oldest events are evicted
                O(1) via ``deque(maxlen=...)``.
            replay_store: Optional pre-built :class:`ReplayStore` to use for
                durable persistence.  When *None*, an :class:`InMemoryReplayStore`
                is used (same as the in-process deque but behind the protocol).
                Call :meth:`initialize_store` to swap in a configured backend.
        """
        # map run_id -> list of websockets
        self.connections: dict[str, list[WebSocket]] = {}
        # Replay buffer: run_id -> deque of events (O(1) eviction via maxlen)
        self.event_buffers: dict[str, deque[dict[str, Any]]] = {}
        self._max_buffer_size = max_buffer_size
        # SSE listeners: run_id -> list of asyncio.Queue
        self._sse_listeners: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}
        # Durable replay store — defaults to in-memory; replaced by initialize_store()
        self._replay_store: ReplayStore = replay_store or InMemoryReplayStore(
            max_events=max_buffer_size
        )

    async def connect(self, websocket: WebSocket, run_id: str):
        """Accept a WebSocket connection and associate it with a run.

        Args:
            websocket: The incoming WebSocket to accept.
            run_id: Workflow run identifier to subscribe to.
        """
        await websocket.accept()
        if run_id not in self.connections:
            self.connections[run_id] = []
        self.connections[run_id].append(websocket)

    def disconnect(self, websocket: WebSocket, run_id: str):
        """Remove a WebSocket from the run's connection list.

        Args:
            websocket: The disconnected WebSocket instance.
            run_id: The run identifier the socket was subscribed to.
        """
        if run_id in self.connections:
            if websocket in self.connections[run_id]:
                self.connections[run_id].remove(websocket)
            if not self.connections[run_id]:
                del self.connections[run_id]

    async def initialize_store(self) -> None:
        """Auto-select and connect the durable replay store from settings.

        Reads ``Settings.replay_store_backend`` and related settings to
        build the appropriate :class:`ReplayStore` backend.  Closes any
        previously held backend first.

        This method is idempotent and safe to call multiple times.
        """
        from .replay_store import build_replay_store

        try:
            from ..settings import get_settings

            settings = get_settings()
        except Exception as exc:
            logger.warning(
                "ConnectionManager.initialize_store: could not load settings (%s); "
                "keeping InMemoryReplayStore",
                exc,
            )
            return

        try:
            await self._replay_store.close()
        except Exception:
            pass

        try:
            self._replay_store = await build_replay_store(settings)
            logger.info(
                "ConnectionManager replay store initialized: %s",
                type(self._replay_store).__name__,
            )
        except Exception as exc:
            logger.warning(
                "ConnectionManager.initialize_store failed (%s); "
                "keeping InMemoryReplayStore",
                exc,
            )
            self._replay_store = InMemoryReplayStore(max_events=self._max_buffer_size)

    async def replay(self, websocket: WebSocket, run_id: str):
        """Send all buffered events to a newly connected client.

        Tries the durable :attr:`_replay_store` first (which may have events
        from before a restart or from another worker).  Falls back to the
        in-memory ``event_buffers`` if the store returns nothing.

        Args:
            websocket: The freshly accepted WebSocket.
            run_id: Run whose event history should be replayed.
        """
        # Prefer durable store — it may have more or fresher events than the
        # in-process hot cache.
        events: list[dict[str, Any]] = []
        try:
            events = await self._replay_store.get_events(run_id)
        except Exception as exc:
            logger.warning(
                "ConnectionManager.replay: store error for run %s (%s); "
                "falling back to in-memory buffer",
                run_id,
                exc,
            )

        if not events:
            events = list(self.event_buffers.get(run_id, []))

        for event in events:
            try:
                await websocket.send_json(event)
            except (ConnectionError, RuntimeError) as exc:
                logger.debug("Replay interrupted for run %s: %s", run_id, exc)
                break

    async def broadcast(self, run_id: str, message: dict[str, Any]):
        """Broadcast an event to all WebSocket clients and SSE listeners for a run.

        The event is first appended to the run's replay buffer (evicting
        the oldest entry if the buffer exceeds ``_max_buffer_size``), then
        pushed to every WebSocket connection and every SSE queue registered
        for the given ``run_id``.

        Args:
            run_id: Target workflow run identifier.
            message: JSON-serializable event dict to broadcast.
        """
        try:
            validate_event(message)
        except ValueError as exc:
            logger.error(
                "Refusing to broadcast malformed event for run %s: %s", run_id, exc
            )
            raise

        # Buffer the event for late-connecting clients.
        # deque(maxlen=...) evicts the oldest entry in O(1) automatically.
        if run_id not in self.event_buffers:
            self.event_buffers[run_id] = deque(maxlen=self._max_buffer_size)
        self.event_buffers[run_id].append(message)

        # Persist to durable store (fire-and-forget — never fail the broadcast).
        try:
            await self._replay_store.append(run_id, message)
        except Exception as exc:
            logger.warning(
                "ConnectionManager.broadcast: replay store persist failed for run %s: %s",
                run_id,
                exc,
            )

        # Snapshot the connection list before iterating so that concurrent
        # connect/disconnect calls cannot modify the list mid-loop.
        dead: list[WebSocket] = []
        for connection in self.connections.get(run_id, []):
            try:
                await connection.send_json(message)
            except Exception:
                logger.debug(
                    "Failed to send to WebSocket client for run %s; removing dead socket",
                    run_id,
                )
                dead.append(connection)
        for ws in dead:
            self.disconnect(ws, run_id)

        # Push to SSE listeners
        for queue in self._sse_listeners.get(run_id, []):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning(
                    "SSE listener queue full for run %s, dropping event", run_id
                )

    def register_sse_listener(
        self, run_id: str, queue: asyncio.Queue[dict[str, Any]]
    ) -> None:
        """Register an asyncio queue to receive broadcast events via SSE.

        Args:
            run_id: Run identifier to subscribe to.
            queue: Bounded asyncio queue that will receive event dicts.
        """
        if run_id not in self._sse_listeners:
            self._sse_listeners[run_id] = []
        self._sse_listeners[run_id].append(queue)

    def unregister_sse_listener(
        self, run_id: str, queue: asyncio.Queue[dict[str, Any]]
    ) -> None:
        """Remove a previously registered SSE listener queue.

        Args:
            run_id: Run identifier the queue was subscribed to.
            queue: The queue instance to remove.
        """
        if run_id in self._sse_listeners:
            if queue in self._sse_listeners[run_id]:
                self._sse_listeners[run_id].remove(queue)
            if not self._sse_listeners[run_id]:
                del self._sse_listeners[run_id]

    def clear_buffer(self, run_id: str) -> None:
        """Clear the replay event buffer for a completed run.

        Clears both the in-memory hot cache and schedules a clear on the
        durable store (fire-and-forget via a background task).

        Args:
            run_id: Run identifier whose buffer should be freed.
        """
        self.event_buffers.pop(run_id, None)
        # Schedule the durable store clear without blocking.
        # We use asyncio.ensure_future so this works whether or not
        # we are inside a running event loop.
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                _task = asyncio.ensure_future(self._clear_store(run_id))
                _task.add_done_callback(lambda _t: None)  # prevent GC of fire-and-forget task
        except RuntimeError:
            # No event loop — store clear will be skipped; this is acceptable
            # in unit tests that don't run an event loop.
            pass

    async def _clear_store(self, run_id: str) -> None:
        """Fire-and-forget helper that clears the durable store for *run_id*."""
        try:
            await self._replay_store.clear(run_id)
        except Exception as exc:
            logger.warning(
                "ConnectionManager._clear_store failed for run %s: %s", run_id, exc
            )


manager = ConnectionManager()


@router.websocket("/ws/execution/{run_id}")
async def websocket_endpoint(websocket: WebSocket, run_id: str):
    """WebSocket endpoint for real-time execution streaming.

    On connect:
    1. Validate browser origin (when provided)
    2. Validate API key from headers or compatibility query parameter
    2. Accept the connection and replay buffered events
    3. Keep alive — execution events are pushed via broadcast()
    4. Client can send ping/commands; server ignores content
    """
    client_host = websocket.client.host if websocket.client else "unknown"

    if not is_websocket_origin_allowed(websocket):
        await websocket.close(code=1008, reason="Origin not allowed")
        logger.warning(
            "Rejected WebSocket origin %r for run %s from %s",
            websocket.headers.get("origin"),
            run_id,
            client_host,
        )
        return

    if websocket_uses_query_token(websocket):
        await websocket.close(
            code=1008,
            reason="Query-string API keys are not supported for WebSocket auth",
        )
        logger.warning(
            "Rejected WebSocket query-token auth for run %s from %s",
            run_id,
            client_host,
        )
        return

    api_key = _get_api_key()
    token = extract_websocket_token(websocket)
    if api_key is not None and not is_token_authorized(
        token.value if token is not None else None, api_key
    ):
        await websocket.close(code=1008, reason="Invalid or missing API key")
        logger.warning("WebSocket auth failed for run %s from %s", run_id, client_host)
        return

    await manager.connect(websocket, run_id)
    try:
        # Inject W3C trace context as the first message when tracing is enabled.
        # The UI uses this to correlate WebSocket events with backend spans.
        if is_tracing_enabled():
            try:
                trace_result = build_traceparent()
                if trace_result is not None:
                    traceparent, tracestate = trace_result
                    trace_ctx_msg: dict[str, Any] = {
                        "type": "trace_context",
                        "traceparent": traceparent,
                    }
                    if tracestate:
                        trace_ctx_msg["tracestate"] = tracestate
                    await websocket.send_json(trace_ctx_msg)
            except Exception:
                logger.debug(
                    "WebSocket: failed to send trace_context for run %s", run_id, exc_info=True
                )

        # Replay buffered events for late joiners
        await manager.replay(websocket, run_id)

        # Keep alive — events are pushed via broadcast()
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        manager.disconnect(websocket, run_id)
        logger.info("Client disconnected from execution stream: %s", run_id)
    except Exception as e:
        logger.error("WebSocket error for %s: %s", run_id, e)
        manager.disconnect(websocket, run_id)
