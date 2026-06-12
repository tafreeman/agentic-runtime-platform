"""Abstract base class for MCP transports.

Implements the contract that all transports (stdio, WebSocket, SSE) must
follow. Strictly separates byte-stream management from JSON-RPC protocol
logic.
"""

import logging
from abc import ABC, abstractmethod
from typing import Callable

from agentic_v2.integrations.mcp.types import JsonRpcMessage

logger = logging.getLogger(__name__)


class McpTransport(ABC):
    """Abstract base class for MCP transport layers.

    Responsibilities:
    - Establish and maintain raw byte streams (stdin/stdout, WebSocket, HTTP)
    - Serialize outbound JSON-RPC messages
    - Deserialize inbound JSON-RPC messages
    - Emit lifecycle events (message, error, close)

    NOT responsible for:
    - JSON-RPC request/response correlation
    - Timeout enforcement
    - Reconnection logic
    - Capability negotiation
    """

    def __init__(self) -> None:
        """Initialize transport with empty event handlers."""
        self.on_message: Callable[[JsonRpcMessage], None] | None = None
        self.on_error: Callable[[Exception], None] | None = None
        self.on_close: Callable[[], None] | None = None
        self._started = False
        self._closed = False

    @abstractmethod
    async def start(self) -> None:
        """Start the transport and begin listening for messages.

        Raises:
            RuntimeError: If transport is already started or closed.
            ConnectionError: If transport fails to connect.
        """
        pass

    @abstractmethod
    async def send(self, message: JsonRpcMessage) -> None:
        """Send a JSON-RPC message over the transport.

        Args:
            message: The JSON-RPC message to send.

        Raises:
            RuntimeError: If transport is not started or is closed.
            ConnectionError: If send fails.
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close the transport and clean up resources.

        Should be idempotent (safe to call multiple times). Must trigger
        on_close callback on first call.
        """
        pass

    def _ensure_started(self) -> None:
        """Raise if transport not started."""
        if not self._started:
            raise RuntimeError("Transport not started. Call start() first.")
        if self._closed:
            raise RuntimeError("Transport is closed. Cannot operate.")

    def _emit_message(self, message: JsonRpcMessage) -> None:
        """Emit a message to the registered handler."""
        if self.on_message:
            try:
                self.on_message(message)
            except Exception as e:
                # Prevent handler errors from crashing transport
                self._emit_error(RuntimeError(f"Message handler raised exception: {e}"))

    def _emit_error(self, error: Exception) -> None:
        """Emit an error to the registered handler."""
        if self.on_error:
            try:
                self.on_error(error)
            except Exception as exc:
                # Last-ditch: don't crash if error handler crashes
                logger.debug("Error handler raised (ignored): %s", exc)

    def _emit_close(self) -> None:
        """Emit a close event to the registered handler (once)."""
        if not self._closed:
            self._closed = True
            if self.on_close:
                try:
                    self.on_close()
                except Exception as e:
                    # Don't crash during cleanup
                    self._emit_error(RuntimeError(f"Close handler raised exception: {e}"))
