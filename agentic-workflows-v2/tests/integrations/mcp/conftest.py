"""Pytest configuration and shared fixtures for MCP integration tests."""

import asyncio
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from agentic_v2.integrations.mcp.protocol.client import McpProtocolClient
from agentic_v2.integrations.mcp.transports.base import McpTransport
from agentic_v2.integrations.mcp.types import (
    McpServerConfig,
    McpStdioConfig,
    TransportType,
)


@pytest.fixture
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_transport() -> McpTransport:
    """Create a mock transport for testing."""
    transport = MagicMock(spec=McpTransport)
    transport.start = AsyncMock()
    transport.send = AsyncMock()
    transport.close = AsyncMock()
    transport.is_connected = True
    transport.on_message = None
    transport.on_error = None
    transport.on_close = None
    return transport


@pytest.fixture
def sample_stdio_config() -> McpServerConfig:
    """Sample stdio server configuration."""
    return McpServerConfig(
        name="test-server",
        transport_type=TransportType.STDIO,
        stdio=McpStdioConfig(
            command="npx",
            args=["test-mcp-server"],
            env={"TEST_VAR": "test_value"},
        ),
        enabled=True,
    )


@pytest.fixture
def sample_initialize_response() -> dict[str, Any]:
    """Sample initialize response from MCP server."""
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {
            "tools": {"listChanged": True},
            "resources": {"subscribe": True, "listChanged": True},
            "prompts": {"listChanged": True},
        },
        "serverInfo": {
            "name": "test-server",
            "version": "1.0.0",
        },
    }


@pytest.fixture
def sample_tools_list_response() -> dict[str, Any]:
    """Sample tools/list response."""
    return {
        "tools": [
            {
                "name": "test_tool",
                "description": "A test tool",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "arg1": {"type": "string", "description": "First argument"}
                    },
                    "required": ["arg1"],
                },
            },
            {
                "name": "another_tool",
                "description": "Another test tool",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "count": {"type": "integer", "description": "A count"}
                    },
                },
            },
        ]
    }


@pytest.fixture
def sample_tool_call_response() -> dict[str, Any]:
    """Sample tools/call response."""
    return {
        "content": [
            {
                "type": "text",
                "text": "Tool execution successful! Result data here.",
            }
        ]
    }


@pytest.fixture
def sample_resources_list_response() -> dict[str, Any]:
    """Sample resources/list response."""
    return {
        "resources": [
            {
                "uri": "file:///path/to/resource.txt",
                "name": "Test Resource",
                "description": "A test resource",
                "mimeType": "text/plain",
            }
        ]
    }


@pytest.fixture
def sample_prompts_list_response() -> dict[str, Any]:
    """Sample prompts/list response."""
    return {
        "prompts": [
            {
                "name": "test_prompt",
                "description": "A test prompt",
                "arguments": [
                    {
                        "name": "context",
                        "description": "Context for the prompt",
                        "required": True,
                    }
                ],
            }
        ]
    }


@pytest.fixture
async def mock_protocol_client(
    mock_transport: McpTransport,
    sample_initialize_response: dict[str, Any],
) -> AsyncGenerator[McpProtocolClient, None]:
    """Create a mock protocol client with initialized connection."""
    client = McpProtocolClient(mock_transport)

    # Mock the initialize handshake
    client._initialized = True
    client._server_capabilities = sample_initialize_response["capabilities"]
    client._server_info = sample_initialize_response["serverInfo"]

    yield client

    await client.close()
