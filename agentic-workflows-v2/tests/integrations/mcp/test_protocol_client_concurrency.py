"""Concurrency regression tests for ``McpProtocolClient`` (C-13).

Validates that ``_handle_transport_error`` and ``_handle_transport_close``
reject every pending request even when resolving one future synchronously
mutates ``_pending_requests`` (the documented "dictionary changed size during
iteration" race). The transport callbacks must snapshot the mapping with
``list()`` before iterating.
"""

import asyncio

from agentic_v2.integrations.mcp.protocol.client import (
    McpProtocolClient,
    McpProtocolError,
)


class _PoppingFuture(asyncio.Future):
    """Future whose rejection synchronously pops a sibling pending request.

    This models the real-world callback chain where ``set_exception`` wakes a
    coroutine that calls ``self._pending_requests.pop(...)`` while a transport
    handler is still iterating the mapping.
    """

    def __init__(
        self,
        pending: dict[object, asyncio.Future],
        sibling_id: object,
    ) -> None:
        super().__init__()
        self._pending = pending
        self._sibling_id = sibling_id

    def set_exception(self, exc: object) -> None:  # type: ignore[override]
        # Mutate the dict the handler is iterating over, mirroring a callback
        # that pops a different in-flight request.
        self._pending.pop(self._sibling_id, None)
        super().set_exception(exc)


def _build_client_with_mutating_pending(mock_transport: object) -> McpProtocolClient:
    """Wire a client whose first future pops a second on rejection.

    Must run inside a running event loop so the futures bind to it.
    """
    client = McpProtocolClient(mock_transport)  # type: ignore[arg-type]
    loop = asyncio.get_running_loop()

    second = loop.create_future()
    first = _PoppingFuture(client._pending_requests, sibling_id="req-2")

    # Insertion order matters: the popping future must be visited first so it
    # mutates the mapping mid-iteration.
    client._pending_requests["req-1"] = first
    client._pending_requests["req-2"] = second
    return client


async def test_handle_transport_close_survives_mid_iteration_pop(mock_transport):
    """Closing the transport must not raise when a callback pops a sibling."""
    client = _build_client_with_mutating_pending(mock_transport)

    # Must not raise RuntimeError: dictionary changed size during iteration.
    client._handle_transport_close()

    # The surviving future was rejected; the popped one was removed cleanly.
    assert client._pending_requests == {}
    assert not client._initialized


async def test_handle_transport_error_survives_mid_iteration_pop(mock_transport):
    """Transport errors must not raise when a callback pops a sibling."""
    client = _build_client_with_mutating_pending(mock_transport)
    first = client._pending_requests["req-1"]

    # Must not raise RuntimeError: dictionary changed size during iteration.
    client._handle_transport_error(RuntimeError("boom"))

    # The visited future was rejected with the transport-error envelope.
    assert first.done()
    assert isinstance(first.exception(), McpProtocolError)


async def test_handle_transport_close_rejects_all_pending(mock_transport):
    """Every still-pending future is rejected and the mapping is cleared."""
    client = McpProtocolClient(mock_transport)  # type: ignore[arg-type]
    loop = asyncio.get_running_loop()
    futures = {f"req-{i}": loop.create_future() for i in range(5)}
    client._pending_requests.update(futures)

    client._handle_transport_close()

    assert client._pending_requests == {}
    for future in futures.values():
        assert isinstance(future.exception(), McpProtocolError)
