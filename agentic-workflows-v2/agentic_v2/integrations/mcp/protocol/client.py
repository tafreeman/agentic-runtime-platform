"""
MCP Protocol Client - JSON-RPC correlation and timeout management.

Handles request/response matching, notification dispatching, and timeout enforcement.
Strictly separated from transport layer (doesn't know about WebSocket vs stdio).
"""

import asyncio
import logging
from typing import Any, Callable, Union

from agentic_v2.integrations.mcp.protocol.messages import MessageBuilder
from agentic_v2.integrations.mcp.transports.base import McpTransport
from agentic_v2.integrations.mcp.types import (
    JsonRpcMessage,
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcResponse,
    McpCapabilities,
    McpServerInfo,
)

logger = logging.getLogger(__name__)

# Timeout constants (matching claude-code-main patterns)
DEFAULT_REQUEST_TIMEOUT = 60.0  # 60s for general requests
INITIALIZE_TIMEOUT = 30.0  # 30s for initialize handshake
TOOL_CALL_TIMEOUT = 120.0  # 2 minutes for tool execution


class McpTimeoutError(Exception):
    """Raised when a request times out."""

    pass


class McpProtocolError(Exception):
    """Raised when protocol-level error occurs."""

    pass


class McpProtocolClient:
    """JSON-RPC protocol client for MCP.

    Responsibilities:
    - Correlate requests with responses using request IDs
    - Enforce timeouts on all requests
    - Dispatch notifications to registered handlers
    - Manage connection lifecycle (initialize, capabilities)

    NOT responsible for:
    - Transport management (passed in as dependency)
    - Connection retry/backoff (handled by ConnectionManager)
    - Discovery of tools/resources (handled by DiscoveryServices)
    """

    def __init__(self, transport: McpTransport) -> None:
        """Initialize protocol client.

        Args:
            transport: Transport layer (stdio, websocket, etc.)
        """
        self.transport = transport
        self._pending_requests: dict[Union[str, int], asyncio.Future] = {}
        self._notification_handlers: dict[str, Callable[[dict[str, Any]], None]] = {}
        self._initialized = False
        self._capabilities: McpCapabilities | None = None
        self._server_info: McpServerInfo | None = None

        # Wire up transport event handlers
        self.transport.on_message = self._handle_message
        self.transport.on_error = self._handle_transport_error
        self.transport.on_close = self._handle_transport_close

    async def connect(self) -> None:
        """Start the transport layer.

        Raises:
            ConnectionError: If transport fails to start.
        """
        await self.transport.start()
        logger.info("Protocol client connected")

    async def initialize(
        self,
        client_info: dict[str, str] | None = None,
        capabilities: dict[str, Any] | None = None,
    ) -> McpServerInfo:
        """Perform MCP initialize handshake.

        Args:
            client_info: Client name and version
            capabilities: Client capabilities to advertise

        Returns:
            Server info from initialize response

        Raises:
            McpTimeoutError: If handshake times out.
            McpProtocolError: If handshake fails.
        """
        request = MessageBuilder.create_initialize_request(
            client_info=client_info,
            capabilities=capabilities,
        )

        try:
            response = await self.request(
                request.method,
                request.params,
                timeout=INITIALIZE_TIMEOUT,
            )
        except TimeoutError as e:
            raise McpTimeoutError(
                f"Initialize handshake timed out after {INITIALIZE_TIMEOUT}s"
            ) from e

        # Parse server capabilities
        server_caps = response.get("capabilities", {})
        self._capabilities = McpCapabilities(
            tools=server_caps.get("tools", False),
            resources=server_caps.get("resources", False),
            prompts=server_caps.get("prompts", False),
            logging=server_caps.get("logging", False),
            experimental=server_caps.get("experimental", {}),
        )

        # Parse server info
        server_info_data = response.get("serverInfo", {})
        self._server_info = McpServerInfo(
            name=server_info_data.get("name", "unknown"),
            version=server_info_data.get("version", "unknown"),
            instructions=response.get("instructions"),
        )

        self._initialized = True
        logger.info(
            f"Initialized MCP server: {self._server_info.name} v{self._server_info.version}"
        )
        logger.debug(f"Server capabilities: {self._capabilities}")

        return self._server_info

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Send a JSON-RPC request and wait for response.

        Args:
            method: Method name
            params: Method parameters
            timeout: Request timeout in seconds (default: 60s)

        Returns:
            Response result

        Raises:
            asyncio.TimeoutError: If request times out.
            McpProtocolError: If server returns error.
        """
        request = MessageBuilder.create_request(method, params)
        request_id = request.id

        # Create future for this request
        future: asyncio.Future = asyncio.Future()
        self._pending_requests[request_id] = future

        try:
            # Send request
            await self.transport.send(request)

            # Wait for response with timeout
            timeout_value = timeout or DEFAULT_REQUEST_TIMEOUT
            result = await asyncio.wait_for(future, timeout=timeout_value)
            return result

        except TimeoutError:
            # Clean up pending request
            self._pending_requests.pop(request_id, None)
            logger.warning(f"Request {method} timed out after {timeout_value}s")
            raise

        except Exception:
            # Clean up on any error
            self._pending_requests.pop(request_id, None)
            raise

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        timeout: float | None = None,
    ) -> Any:
        """Invoke a remote MCP tool via ``tools/call``.

        Thin wrapper over :meth:`request` that serializes the standard
        MCP tools/call envelope. Callers (e.g., ``McpToolAdapter``) may
        still wrap this in their own ``asyncio.wait_for`` to enforce an
        outer deadline.

        Args:
            name: Tool name as advertised by the server.
            arguments: Tool arguments (JSON-serializable dict).
            timeout: Optional per-request timeout forwarded to ``request``.
                Defaults to :data:`TOOL_CALL_TIMEOUT` when ``None``.

        Returns:
            Parsed ``result`` payload from the server (typically a dict
            with a ``content`` key).

        Raises:
            asyncio.TimeoutError: If the request exceeds ``timeout``.
            McpProtocolError: If the server returns an error.
        """
        return await self.request(
            "tools/call",
            params={"name": name, "arguments": arguments},
            timeout=timeout or TOOL_CALL_TIMEOUT,
        )

    async def notify(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Send a JSON-RPC notification (no response expected).

        Args:
            method: Notification method
            params: Notification parameters
        """
        notification = MessageBuilder.create_notification(method, params)
        await self.transport.send(notification)
        logger.debug(f"Sent notification: {method}")

    def register_notification_handler(
        self,
        method: str,
        handler: Callable[[dict[str, Any]], None],
    ) -> None:
        """Register a handler for server notifications.

        Args:
            method: Notification method to handle (e.g., "notifications/tools/list_changed")
            handler: Callback function (receives params dict)
        """
        self._notification_handlers[method] = handler
        logger.debug(f"Registered notification handler: {method}")

    async def close(self) -> None:
        """Close the protocol client and transport.

        Rejects all pending requests and cleans up resources.
        """
        logger.debug("Closing protocol client")

        # Reject all pending requests
        for request_id, future in self._pending_requests.items():
            if not future.done():
                future.set_exception(
                    McpProtocolError("Connection closed while request pending")
                )

        self._pending_requests.clear()
        self._initialized = False

        # Close transport
        await self.transport.close()

    @property
    def capabilities(self) -> McpCapabilities | None:
        """Get server capabilities (available after initialize)."""
        return self._capabilities

    @property
    def server_info(self) -> McpServerInfo | None:
        """Get server info (available after initialize)."""
        return self._server_info

    @property
    def is_initialized(self) -> bool:
        """Check if initialize handshake completed."""
        return self._initialized

    def _handle_message(self, message: JsonRpcMessage) -> None:
        """Handle incoming JSON-RPC message from transport.

        Routes to appropriate handler based on message type.
        """
        if isinstance(message, JsonRpcResponse):
            self._handle_response(message)
        elif isinstance(message, JsonRpcNotification):
            self._handle_notification(message)
        elif isinstance(message, JsonRpcRequest):
            # We don't expect requests from server (client-only implementation)
            logger.warning(f"Unexpected request from server: {message.method}")

    def _handle_response(self, response: JsonRpcResponse) -> None:
        """
        Handle JSON-RPC response - resolve pending future.

        Args:
            response: Response message
        """
        request_id = response.id
        future = self._pending_requests.pop(request_id, None)

        if not future:
            logger.warning(f"Received response for unknown request: {request_id}")
            return

        if future.done():
            logger.warning(f"Future already resolved for request: {request_id}")
            return

        # Check for error response
        if response.error:
            error = response.error
            error_msg = f"MCP error {error.get('code')}: {error.get('message')}"
            future.set_exception(McpProtocolError(error_msg))
        else:
            future.set_result(response.result)

    def _handle_notification(self, notification: JsonRpcNotification) -> None:
        """
        Handle JSON-RPC notification - dispatch to registered handler.

        Args:
            notification: Notification message
        """
        method = notification.method
        params = notification.params or {}

        handler = self._notification_handlers.get(method)
        if handler:
            try:
                handler(params)
            except Exception as e:
                logger.error(f"Notification handler error for {method}: {e}")
        else:
            logger.debug(f"No handler for notification: {method}")

    def _handle_transport_error(self, error: Exception) -> None:
        """
        Handle transport errors - reject all pending requests.

        Args:
            error: Transport error
        """
        logger.error(f"Transport error: {error}")

        # Reject all pending requests
        for request_id, future in self._pending_requests.items():
            if not future.done():
                future.set_exception(McpProtocolError(f"Transport error: {error}"))

    def _handle_transport_close(self) -> None:
        """
        Handle transport closure - reject all pending requests.
        """
        logger.info("Transport closed")

        # Reject all pending requests
        for request_id, future in self._pending_requests.items():
            if not future.done():
                future.set_exception(McpProtocolError("Transport closed unexpectedly"))

        self._pending_requests.clear()
        self._initialized = False
