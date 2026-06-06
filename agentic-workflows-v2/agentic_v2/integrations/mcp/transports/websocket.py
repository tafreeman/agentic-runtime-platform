"""WebSocket transport for MCP servers.

Connects to remote MCP servers via WebSocket (ws:// or wss:// URLs).
Uses the `websockets` library for async WebSocket client implementation.
"""

import asyncio
import json
import logging

# Note: websockets library needs to be added to dependencies
try:
    import websockets
    from websockets.client import WebSocketClientProtocol
except ImportError:
    raise ImportError(
        "websockets library required for WebSocket transport. "
        "Install with: pip install websockets"
    )

from agentic_v2.integrations.mcp.transports.base import McpTransport
from agentic_v2.integrations.mcp.types import (
    JsonRpcMessage,
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcResponse,
)

logger = logging.getLogger(__name__)


class WebSocketTransport(McpTransport):
    """Transport for MCP servers accessible via WebSocket.

    Supports both ws:// (insecure) and wss:// (TLS) connections. Handles
    connection establishment, message framing, and cleanup.
    """

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Initialize WebSocket transport.

        Args:
            url: WebSocket URL (must start with ws:// or wss://)
            headers: Optional headers to send during handshake
        """
        super().__init__()
        if not url.startswith(("ws://", "wss://")):
            raise ValueError("WebSocket URL must start with ws:// or wss://")

        self.url = url
        self.headers = headers or {}
        self._ws: WebSocketClientProtocol | None = None
        self._receive_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Connect to the WebSocket server and start receiving.

        Raises:
            RuntimeError: If already started.
            ConnectionError: If connection fails.
        """
        if self._started:
            raise RuntimeError("Transport already started")
        if self._closed:
            raise RuntimeError("Transport is closed")

        logger.debug(f"Connecting to WebSocket: {self.url}")

        try:
            self._ws = await websockets.connect(
                self.url,
                additional_headers=self.headers,
                ping_interval=20,  # Send ping every 20s to keep alive
                ping_timeout=10,  # Wait 10s for pong before considering dead
            )
        except Exception as e:
            raise ConnectionError(f"WebSocket connection failed: {e}") from e

        self._started = True
        # Start receiving messages in background
        self._receive_task = asyncio.create_task(self._receive_loop())
        logger.info(f"WebSocket connected: {self.url}")

    async def send(self, message: JsonRpcMessage) -> None:
        """Send a JSON-RPC message via WebSocket.

        Args:
            message: JSON-RPC message to send

        Raises:
            RuntimeError: If transport not started.
            ConnectionError: If send fails.
        """
        self._ensure_started()

        if not self._ws or self._ws.closed:
            raise RuntimeError("WebSocket connection is closed")

        try:
            payload = json.dumps(message.model_dump(exclude_none=True))
            await self._ws.send(payload)
        except Exception as e:
            raise ConnectionError(f"WebSocket send failed: {e}") from e

    async def close(self) -> None:
        """Close the WebSocket connection gracefully.

        Idempotent: safe to call multiple times.
        """
        if self._closed:
            return

        logger.debug("Closing WebSocket transport")

        if self._ws and not self._ws.closed:
            try:
                await self._ws.close()
            except Exception as e:
                logger.warning(f"Error closing WebSocket: {e}")

        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            await asyncio.gather(self._receive_task, return_exceptions=True)

        self._emit_close()

    async def _receive_loop(self) -> None:
        """Receive and parse JSON-RPC messages from WebSocket.

        Runs until connection closes or transport is shut down.
        """
        if not self._ws:
            return

        try:
            async for message in self._ws:
                if self._closed:
                    break

                try:
                    # websockets library delivers messages as str or bytes
                    if isinstance(message, bytes):
                        message = message.decode("utf-8")

                    data = json.loads(message)
                    parsed = self._parse_json_rpc(data)
                    self._emit_message(parsed)
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON from WebSocket: {e}")
                    self._emit_error(ValueError(f"Invalid JSON: {e}"))
                except Exception as e:
                    logger.warning(f"Failed to parse WebSocket message: {e}")
                    self._emit_error(e)

        except asyncio.CancelledError:
            logger.debug("WebSocket receive loop cancelled")
            raise
        except websockets.exceptions.ConnectionClosed as e:
            logger.info(f"WebSocket connection closed: {e}")
        except Exception as e:
            logger.error(f"WebSocket receive error: {e}")
            self._emit_error(e)
        finally:
            # Connection closed
            if not self._closed:
                self._emit_close()

    def _parse_json_rpc(self, data: dict) -> JsonRpcMessage:
        """Parse raw JSON into typed JSON-RPC message.

        Args:
            data: Deserialized JSON object

        Returns:
            Typed JsonRpcMessage (request, response, or notification)
        """
        if "id" in data:
            if "method" in data:
                return JsonRpcRequest(**data)
            else:
                return JsonRpcResponse(**data)
        else:
            return JsonRpcNotification(**data)
