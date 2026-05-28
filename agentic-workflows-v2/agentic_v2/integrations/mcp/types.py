"""Core type definitions for MCP integration.

Defines Pydantic models for configuration, connection state, and
protocol types. Follows the patterns from claude-code-main but adapted
for Python/Pydantic.
"""

from enum import Enum
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator


class TransportType(str, Enum):
    """Supported MCP transport types."""

    STDIO = "stdio"
    WEBSOCKET = "ws"
    SSE = "sse"
    HTTP = "http"


class McpConnectionState(str, Enum):
    """MCP connection lifecycle states."""

    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    DISCONNECTED = "disconnected"
    NEEDS_AUTH = "needs-auth"
    FAILED = "failed"


class McpStdioConfig(BaseModel):
    """Configuration for stdio transport (spawns subprocess)."""

    type: Literal[TransportType.STDIO] = TransportType.STDIO
    command: str = Field(..., min_length=1, description="Executable command")
    args: list[str] = Field(default_factory=list, description="Command arguments")
    env: Optional[dict[str, str]] = Field(
        None, description="Environment variables for subprocess"
    )

    @field_validator("command")
    @classmethod
    def validate_command(cls, v: str) -> str:
        """Ensure command is not empty."""
        if not v.strip():
            raise ValueError("Command cannot be empty")
        return v.strip()


class McpWebSocketConfig(BaseModel):
    """Configuration for WebSocket transport."""

    type: Literal[TransportType.WEBSOCKET] = TransportType.WEBSOCKET
    url: str = Field(
        ..., description="WebSocket URL (ws://, wss://, http://, or https://)"
    )
    headers: Optional[dict[str, str]] = Field(
        None, description="Headers to send on connection"
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Ensure URL uses a supported WebSocket or HTTP scheme."""
        if not v.startswith(("ws://", "wss://", "http://", "https://")):
            raise ValueError(
                "WebSocket URL must start with ws://, wss://, http://, or https://"
            )
        return v


class McpSSEConfig(BaseModel):
    """Configuration for Server-Sent Events transport."""

    type: Literal[TransportType.SSE] = TransportType.SSE
    url: str = Field(..., description="SSE endpoint URL (https://)")
    headers: Optional[dict[str, str]] = Field(
        None, description="Headers to send with requests"
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Ensure URL uses HTTPS for security."""
        if not v.startswith("https://"):
            raise ValueError("SSE URL must use HTTPS")
        return v


# Union type for transport configs (for backward compatibility)
McpTransportConfig = Union[McpStdioConfig, McpWebSocketConfig, McpSSEConfig]


class McpServerConfig(BaseModel):
    """Complete server configuration including metadata and transport.

    Wraps transport-specific configs (stdio/websocket/sse) with server
    metadata.
    """

    name: str = Field(..., description="Server name/identifier")
    enabled: bool = Field(True, description="Whether server is enabled")
    transport_type: TransportType = Field(..., description="Transport type")
    stdio: Optional[McpStdioConfig] = Field(None, description="Stdio transport config")
    websocket: Optional[McpWebSocketConfig] = Field(
        None, description="WebSocket transport config"
    )
    sse: Optional[McpSSEConfig] = Field(None, description="SSE transport config")

    @field_validator("stdio", "websocket", "sse")
    @classmethod
    def validate_transport_config(cls, v: Any, info) -> Any:
        """Ensure at least one transport config is provided."""
        return v


class McpCapabilities(BaseModel):
    """Server capabilities after initialize handshake."""

    tools: bool = Field(False, description="Server supports tools")
    resources: bool = Field(False, description="Server supports resources")
    prompts: bool = Field(False, description="Server supports prompts")
    logging: bool = Field(False, description="Server supports logging")
    experimental: dict[str, Any] = Field(
        default_factory=dict, description="Experimental capabilities"
    )


class McpServerInfo(BaseModel):
    """Server metadata from initialize response."""

    name: str = Field(..., description="Server name")
    version: str = Field(..., description="Server version")
    instructions: Optional[str] = Field(
        None, description="Usage instructions from server"
    )


class McpToolDescriptor(BaseModel):
    """Metadata for a remote MCP tool."""

    name: str = Field(..., description="Tool name")
    description: Optional[str] = Field(None, description="Tool description")
    input_schema: dict[str, Any] = Field(
        ..., description="JSON Schema for tool input (preserved verbatim)"
    )


# Alias for convenience — tests and adapters may import as ToolDescriptor
ToolDescriptor = McpToolDescriptor


class McpResourceDescriptor(BaseModel):
    """Metadata for a remote MCP resource."""

    uri: str = Field(..., description="Resource URI (e.g., mcp://server/path)")
    name: Optional[str] = Field(None, description="Human-readable resource name")
    description: Optional[str] = Field(None, description="Resource description")
    mime_type: Optional[str] = Field(None, description="MIME type hint")


class McpPromptDescriptor(BaseModel):
    """Metadata for a remote MCP prompt template."""

    name: str = Field(..., description="Prompt name")
    description: Optional[str] = Field(None, description="Prompt description")
    arguments: list[dict[str, Any]] = Field(
        default_factory=list, description="Required prompt arguments"
    )


class JsonRpcRequest(BaseModel):
    """JSON-RPC 2.0 request message."""

    jsonrpc: Literal["2.0"] = "2.0"
    id: Union[str, int] = Field(..., description="Request ID")
    method: str = Field(..., description="Method name")
    params: Optional[dict[str, Any]] = Field(None, description="Method parameters")


class JsonRpcResponse(BaseModel):
    """JSON-RPC 2.0 response message."""

    jsonrpc: Literal["2.0"] = "2.0"
    id: Union[str, int] = Field(..., description="Request ID")
    result: Optional[Any] = Field(None, description="Result (if success)")
    error: Optional[dict[str, Any]] = Field(None, description="Error (if failed)")


class JsonRpcNotification(BaseModel):
    """JSON-RPC 2.0 notification (no id, no response expected)."""

    jsonrpc: Literal["2.0"] = "2.0"
    method: str = Field(..., description="Notification method")
    params: Optional[dict[str, Any]] = Field(None, description="Notification params")


# Union type for all JSON-RPC messages
JsonRpcMessage = Union[JsonRpcRequest, JsonRpcResponse, JsonRpcNotification]
