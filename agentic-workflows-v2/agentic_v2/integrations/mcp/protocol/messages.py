"""JSON-RPC message builders and validators.

Provides helper functions to construct well-formed JSON-RPC messages for
the MCP protocol.
"""

import uuid
from typing import Any, Optional, Union

from agentic_v2.integrations.mcp.types import (
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcResponse,
)


class MessageBuilder:
    """Helper class for building JSON-RPC messages.

    Handles ID generation, method validation, and message construction
    according to JSON-RPC 2.0 spec.
    """

    @staticmethod
    def create_request(
        method: str,
        params: Optional[dict[str, Any]] = None,
        request_id: Optional[Union[str, int]] = None,
    ) -> JsonRpcRequest:
        """Create a JSON-RPC request.

        Args:
            method: Method name to invoke
            params: Method parameters (optional)
            request_id: Request ID (auto-generated if not provided)

        Returns:
            JsonRpcRequest object
        """
        if request_id is None:
            request_id = str(uuid.uuid4())

        return JsonRpcRequest(
            jsonrpc="2.0",
            id=request_id,
            method=method,
            params=params,
        )

    @staticmethod
    def create_response(
        request_id: Union[str, int],
        result: Optional[Any] = None,
        error: Optional[dict[str, Any]] = None,
    ) -> JsonRpcResponse:
        """Create a JSON-RPC response.

        Args:
            request_id: ID from the original request
            result: Result value (if success)
            error: Error object (if failure)

        Returns:
            JsonRpcResponse object

        Raises:
            ValueError: If both result and error are provided or neither
        """
        if (result is None and error is None) or (
            result is not None and error is not None
        ):
            raise ValueError("Exactly one of result or error must be provided")

        return JsonRpcResponse(
            jsonrpc="2.0",
            id=request_id,
            result=result,
            error=error,
        )

    @staticmethod
    def create_notification(
        method: str,
        params: Optional[dict[str, Any]] = None,
    ) -> JsonRpcNotification:
        """Create a JSON-RPC notification (no response expected).

        Args:
            method: Notification method name
            params: Notification parameters (optional)

        Returns:
            JsonRpcNotification object
        """
        return JsonRpcNotification(
            jsonrpc="2.0",
            method=method,
            params=params,
        )

    @staticmethod
    def create_initialize_request(
        protocol_version: str = "2024-11-05",
        client_info: Optional[dict[str, str]] = None,
        capabilities: Optional[dict[str, Any]] = None,
    ) -> JsonRpcRequest:
        """Create an MCP initialize request.

        Args:
            protocol_version: MCP protocol version
            client_info: Client name and version
            capabilities: Client capabilities

        Returns:
            JsonRpcRequest for initialize
        """
        params = {
            "protocolVersion": protocol_version,
            "clientInfo": client_info
            or {"name": "agentic-workflows-v2", "version": "0.1.0"},
            "capabilities": capabilities or {},
        }

        return MessageBuilder.create_request("initialize", params)

    @staticmethod
    def create_error(
        code: int,
        message: str,
        data: Optional[Any] = None,
    ) -> dict[str, Any]:
        """Create a JSON-RPC error object.

        Args:
            code: Error code (e.g., -32600 for invalid request)
            message: Error message
            data: Additional error data (optional)

        Returns:
            Error object dict
        """
        error = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return error


# Standard JSON-RPC error codes
class ErrorCode:
    """Standard JSON-RPC 2.0 error codes."""

    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    # MCP-specific error codes (from SDK)
    SESSION_NOT_FOUND = -32001
    TOOL_NOT_FOUND = -32002
    RESOURCE_NOT_FOUND = -32003
