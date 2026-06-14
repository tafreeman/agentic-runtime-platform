"""Tests for MCP tool adapter.

Validates:
- Tool execution with various input types
- Error handling and string conversion
- Timeout enforcement
- Content block parsing (text, image, resource)
- Schema passthrough preservation
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agentic_v2.integrations.mcp.adapters.tool_adapter import McpToolAdapter
from agentic_v2.integrations.mcp.error_envelope import ErrorCategory
from agentic_v2.integrations.mcp.protocol.client import (
    McpProtocolError,
    McpTimeoutError,
)
from agentic_v2.integrations.mcp.types import ToolDescriptor


def _adapter(name: str = "test_tool", timeout: float | None = None) -> McpToolAdapter:
    """Build an adapter wrapping a mock client for envelope tests."""
    tool = ToolDescriptor(
        name=name,
        description="Test",
        input_schema={"type": "object"},
    )
    return McpToolAdapter("server", tool, MagicMock(), timeout=timeout)


@pytest.mark.asyncio
class TestMcpToolAdapter:
    """Test McpToolAdapter functionality."""

    def test_adapter_creation(self):
        """Test creating a tool adapter."""
        tool = ToolDescriptor(
            name="test_tool",
            description="A test tool",
            input_schema={"type": "object", "properties": {}},
        )
        client = MagicMock()

        adapter = McpToolAdapter(
            server_name="test-server",
            tool_descriptor=tool,
            client=client,
        )

        assert adapter.name == "mcp_test-server_test_tool"
        assert adapter.description == "A test tool"
        assert adapter.input_schema == tool.input_schema

    def test_schema_passthrough(self):
        """Test that JSON Schema is preserved verbatim (not reconstructed)."""
        original_schema = {
            "type": "object",
            "properties": {
                "arg1": {
                    "type": "string",
                    "description": "First arg",
                    "pattern": "^[a-z]+$",  # Complex pattern
                }
            },
            "required": ["arg1"],
            "additionalProperties": False,
        }

        tool = ToolDescriptor(
            name="complex_tool",
            description="Tool with complex schema",
            input_schema=original_schema,
        )
        client = MagicMock()

        adapter = McpToolAdapter("server", tool, client)

        # Schema content must be preserved verbatim (no reconstruction)
        assert adapter.input_schema == original_schema

    async def test_execute_success_text_response(self):
        """Test successful tool execution with text response."""
        tool = ToolDescriptor(
            name="test_tool",
            description="Test",
            input_schema={"type": "object"},
        )
        client = MagicMock()
        client.call_tool = AsyncMock(
            return_value={
                "content": [{"type": "text", "text": "Success! Result data."}]
            }
        )

        adapter = McpToolAdapter("server", tool, client)
        result = await adapter.execute({"arg": "value"})

        assert "Success! Result data." in result
        client.call_tool.assert_called_once_with("test_tool", {"arg": "value"})

    async def test_execute_multiple_content_blocks(self):
        """Test execution with multiple content blocks."""
        tool = ToolDescriptor(
            name="multi_tool",
            description="Multi-block tool",
            input_schema={"type": "object"},
        )
        client = MagicMock()
        client.call_tool = AsyncMock(
            return_value={
                "content": [
                    {"type": "text", "text": "Part 1"},
                    {"type": "text", "text": "Part 2"},
                    {"type": "text", "text": "Part 3"},
                ]
            }
        )

        adapter = McpToolAdapter("server", tool, client)
        result = await adapter.execute({})

        assert "Part 1" in result
        assert "Part 2" in result
        assert "Part 3" in result

    async def test_execute_image_content(self):
        """Test execution with image content block."""
        tool = ToolDescriptor(
            name="image_tool",
            description="Returns image",
            input_schema={"type": "object"},
        )
        client = MagicMock()
        client.call_tool = AsyncMock(
            return_value={
                "content": [
                    {
                        "type": "image",
                        "data": "iVBORw0KGgoAAAANS...",  # Base64 data
                        "mimeType": "image/png",
                    }
                ]
            }
        )

        adapter = McpToolAdapter("server", tool, client)
        result = await adapter.execute({})

        assert "[Image: image/png" in result

    async def test_execute_resource_content(self):
        """Test execution with resource content block."""
        tool = ToolDescriptor(
            name="resource_tool",
            description="Returns resource",
            input_schema={"type": "object"},
        )
        client = MagicMock()
        client.call_tool = AsyncMock(
            return_value={
                "content": [
                    {
                        "type": "resource",
                        "resource": {
                            "uri": "file:///path/to/file.txt",
                            "mimeType": "text/plain",
                            "text": "File content here",
                        },
                    }
                ]
            }
        )

        adapter = McpToolAdapter("server", tool, client)
        result = await adapter.execute({})

        assert "file:///path/to/file.txt" in result
        assert "File content here" in result

    async def test_execute_error_handling(self):
        """Test error handling returns friendly string."""
        tool = ToolDescriptor(
            name="failing_tool",
            description="This tool fails",
            input_schema={"type": "object"},
        )
        client = MagicMock()
        client.call_tool = AsyncMock(side_effect=Exception("Connection failed"))

        adapter = McpToolAdapter("server", tool, client)
        result = await adapter.execute({})

        # Should return error string, NOT raise exception
        assert "Error" in result or "Failed" in result
        assert "Connection failed" in result

    async def test_execute_timeout_handling(self):
        """Test timeout is enforced on tool execution."""
        import asyncio

        tool = ToolDescriptor(
            name="slow_tool",
            description="Slow tool",
            input_schema={"type": "object"},
        )
        client = MagicMock()

        # Simulate slow operation
        async def slow_call(*args, **kwargs):
            await asyncio.sleep(10)
            return {"content": [{"type": "text", "text": "Done"}]}

        client.call_tool = slow_call

        adapter = McpToolAdapter("server", tool, client, timeout=0.1)

        # Should timeout and return error string
        result = await adapter.execute({})
        assert "timeout" in result.lower() or "timed out" in result.lower()

    async def test_execute_empty_content(self):
        """Test handling of empty content array."""
        tool = ToolDescriptor(
            name="empty_tool",
            description="Returns nothing",
            input_schema={"type": "object"},
        )
        client = MagicMock()
        client.call_tool = AsyncMock(return_value={"content": []})

        adapter = McpToolAdapter("server", tool, client)
        result = await adapter.execute({})

        # Should return some indication of no output
        assert len(result) > 0  # Not empty string

    def test_to_dict_serialization(self):
        """Test adapter can serialize to dict for registry."""
        tool = ToolDescriptor(
            name="test_tool",
            description="Test tool",
            input_schema={
                "type": "object",
                "properties": {"arg": {"type": "string"}},
            },
        )
        client = MagicMock()

        adapter = McpToolAdapter("server", tool, client)
        tool_dict = adapter.to_dict()

        assert tool_dict["name"] == "mcp_server_test_tool"
        assert tool_dict["description"] == "Test tool"
        assert tool_dict["input_schema"] == tool.input_schema
        assert "execute" in tool_dict  # Callable present

    def test_namespacing_prevents_collisions(self):
        """Test tool namespacing prevents name collisions across servers."""
        tool = ToolDescriptor(
            name="common_tool",
            description="Tool",
            input_schema={"type": "object"},
        )

        adapter1 = McpToolAdapter("server1", tool, MagicMock())
        adapter2 = McpToolAdapter("server2", tool, MagicMock())

        assert adapter1.name == "mcp_server1_common_tool"
        assert adapter2.name == "mcp_server2_common_tool"
        assert adapter1.name != adapter2.name


@pytest.mark.asyncio
class TestMcpToolAdapterErrorEnvelope:
    """Test the MCP-standard structured error envelope surfaced to the model."""

    async def test_success_envelope(self) -> None:
        adapter = _adapter()
        adapter.client.call_tool = AsyncMock(
            return_value={"content": [{"type": "text", "text": "data"}]}
        )

        env = await adapter.execute_envelope({})

        assert env.is_error is False
        assert env.is_empty is False
        assert env.error_category is None
        assert env.text == "data"

    async def test_valid_empty_result_is_not_an_error(self) -> None:
        # A tool that ran fine but matched nothing: empty content, no isError.
        adapter = _adapter()
        adapter.client.call_tool = AsyncMock(return_value={"content": []})

        env = await adapter.execute_envelope({})

        assert env.is_error is False
        assert env.is_empty is True
        assert env.error_category is None

    async def test_access_failure_differs_from_empty_result(self) -> None:
        # Same empty-looking content, but the server flagged isError -> failure.
        adapter = _adapter()
        adapter.client.call_tool = AsyncMock(
            return_value={
                "isError": True,
                "content": [{"type": "text", "text": "403 Forbidden: no access"}],
            }
        )

        env = await adapter.execute_envelope({})

        assert env.is_error is True
        assert env.is_empty is False
        assert env.error_category is ErrorCategory.PERMISSION
        assert env.is_retryable is False

    async def test_is_error_flag_surfaces_business_failure(self) -> None:
        adapter = _adapter()
        adapter.client.call_tool = AsyncMock(
            return_value={
                "isError": True,
                "content": [{"type": "text", "text": "Issue is already closed"}],
            }
        )

        env = await adapter.execute_envelope({})

        assert env.is_error is True
        assert env.error_category is ErrorCategory.BUSINESS
        assert env.is_retryable is False

    async def test_timeout_is_transient_and_retryable(self) -> None:
        adapter = _adapter(timeout=0.01)

        async def slow_call(*args: object, **kwargs: object) -> dict[str, object]:
            import asyncio

            await asyncio.sleep(5)
            return {"content": []}

        adapter.client.call_tool = slow_call  # type: ignore[assignment]

        env = await adapter.execute_envelope({})

        assert env.is_error is True
        assert env.error_category is ErrorCategory.TRANSIENT
        assert env.is_retryable is True
        assert "timed out" in env.text.lower()

    async def test_protocol_timeout_is_transient(self) -> None:
        adapter = _adapter()
        adapter.client.call_tool = AsyncMock(
            side_effect=McpTimeoutError("request timed out")
        )

        env = await adapter.execute_envelope({})

        assert env.is_error is True
        assert env.error_category is ErrorCategory.TRANSIENT
        assert env.is_retryable is True

    async def test_protocol_validation_error_is_not_retryable(self) -> None:
        # JSON-RPC -32602 "Invalid params" -> validation, not retryable.
        adapter = _adapter()
        adapter.client.call_tool = AsyncMock(
            side_effect=McpProtocolError("MCP error -32602: Invalid params")
        )

        env = await adapter.execute_envelope({})

        assert env.is_error is True
        assert env.error_category is ErrorCategory.VALIDATION
        assert env.is_retryable is False

    async def test_unexpected_exception_is_classified(self) -> None:
        adapter = _adapter()
        adapter.client.call_tool = AsyncMock(
            side_effect=Exception("Connection reset by peer")
        )

        env = await adapter.execute_envelope({})

        assert env.is_error is True
        assert env.error_category is ErrorCategory.TRANSIENT
        assert env.is_retryable is True
        assert "Connection reset" in env.text

    async def test_execute_string_wrapper_embeds_structured_fields(self) -> None:
        # The legacy str-returning execute() must carry the envelope text.
        adapter = _adapter()
        adapter.client.call_tool = AsyncMock(
            side_effect=McpProtocolError("403 Forbidden")
        )

        result = await adapter.execute({})

        assert isinstance(result, str)
        assert "permission" in result
        assert "not retryable" in result

    async def test_to_mcp_result_round_trip(self) -> None:
        adapter = _adapter()
        adapter.client.call_tool = AsyncMock(
            side_effect=McpProtocolError("429 too many requests")
        )

        env = await adapter.execute_envelope({})
        payload = env.to_mcp_result()

        assert payload["isError"] is True
        assert payload["errorCategory"] == "transient"
        assert payload["isRetryable"] is True
