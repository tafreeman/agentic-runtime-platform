"""
MCP Tool Adapter - wraps remote MCP tools as local tool instances.

Critical design choices:
1. **Schema Passthrough**: Original JSON Schema preserved verbatim (no Pydantic reconstruction)
2. **Namespacing**: Tools named `mcp_{server_name}_{tool_name}` to prevent conflicts
3. **Error Trapping**: All execution errors caught and returned as a structured,
   MCP-correct error envelope (``isError`` + ``errorCategory`` + ``isRetryable``)
   the model can reason about — never crash the orchestrator
4. **Timeout Enforcement**: All tool calls wrapped with configurable timeout
5. **Empty vs access-failure**: A valid result that legitimately carried no
   content is reported as a (non-error) empty result, distinct from an
   access/permission failure that sets ``isError``.
"""

import asyncio
import logging
from typing import Any

from agentic_v2.integrations.mcp.discovery.tools import ToolDiscovery
from agentic_v2.integrations.mcp.error_envelope import (
    ErrorCategory,
    ToolResultEnvelope,
)
from agentic_v2.integrations.mcp.protocol.client import (
    McpProtocolClient,
    McpProtocolError,
    McpTimeoutError,
)
from agentic_v2.integrations.mcp.types import McpToolDescriptor

logger = logging.getLogger(__name__)

# Tool execution timeout (matching claude-code-main)
TOOL_CALL_TIMEOUT = 120.0  # 2 minutes

# Sentinel text for a valid, non-error empty result.
EMPTY_RESULT_TEXT = "[Tool returned no content]"


class McpToolAdapter:
    """Adapter that wraps remote MCP tools as local tool instances.

    Handles:
    - Tool name namespacing
    - JSON Schema passthrough (no conversion)
    - Error trapping (returns friendly strings)
    - Timeout enforcement
    - Progress tracking (optional)
    """

    def __init__(
        self,
        server_name: str,
        tool_descriptor: McpToolDescriptor,
        client: McpProtocolClient,
        timeout: float | None = None,
    ) -> None:
        """Initialize tool adapter.

        Args:
            server_name: Server providing this tool
            tool_descriptor: Tool metadata from discovery
            client: Protocol client for tool invocation
        """
        self.server_name = server_name
        self.tool_descriptor = tool_descriptor
        self.client = client

        # Namespaced tool name
        self.name = f"mcp_{server_name}_{tool_descriptor.name}"
        self.description = (
            tool_descriptor.description
            or f"Tool '{tool_descriptor.name}' from MCP server '{server_name}'"
        )

        # Preserve original JSON Schema (CRITICAL: no conversion)
        self.input_schema = tool_descriptor.input_schema
        self._default_timeout = timeout

    async def execute(
        self,
        arguments: dict[str, Any],
        timeout: float | None = None,
    ) -> str:
        """Execute the remote tool, returning the model-facing result string.

        Backward-compatible thin wrapper over :meth:`execute_envelope`. The
        returned string embeds the structured error fields (category +
        retryability) inline for failures, so callers that only handle strings
        still surface the MCP-correct error text to the model.

        Args:
            arguments: Tool input arguments (validated against input_schema)
            timeout: Execution timeout (default: 120s)

        Returns:
            Tool result as string (never raises exceptions to LLM)
        """
        envelope = await self.execute_envelope(arguments, timeout)
        return envelope.text

    async def execute_envelope(
        self,
        arguments: dict[str, Any],
        timeout: float | None = None,
    ) -> ToolResultEnvelope:
        """Execute the remote tool and return the structured MCP result envelope.

        The envelope carries the MCP-correct contract surfaced to the model:
        ``isError`` for true failures, an ``errorCategory``
        (transient/validation/business/permission), an ``isRetryable`` flag,
        and human-readable ``text``. A valid result that legitimately returned
        no content is reported as a (non-error) empty result — explicitly
        distinct from an access/permission failure.

        Args:
            arguments: Tool input arguments (validated against input_schema)
            timeout: Execution timeout (default: 120s)

        Returns:
            A :class:`ToolResultEnvelope`. Never raises exceptions to the LLM.
        """
        timeout_value = timeout or self._default_timeout or TOOL_CALL_TIMEOUT

        logger.info(
            f"Executing MCP tool {self.tool_descriptor.name} on {self.server_name}"
        )
        logger.debug(f"Tool arguments: {arguments}")

        try:
            # Call remote tool with timeout
            async with asyncio.timeout(timeout_value):
                response = await self.client.call_tool(
                    self.tool_descriptor.name, arguments
                )

            return self._envelope_from_response(response)

        except TimeoutError:
            error_msg = f"Tool execution timed out after {timeout_value}s"
            logger.warning(f"{self.name}: {error_msg}")
            return ToolResultEnvelope.failure(
                error_msg,
                category=ErrorCategory.TRANSIENT,
                is_retryable=True,
            )

        except McpTimeoutError as e:
            error_msg = f"MCP protocol timeout: {e}"
            logger.warning(f"{self.name}: {error_msg}")
            return ToolResultEnvelope.failure(
                error_msg,
                category=ErrorCategory.TRANSIENT,
                is_retryable=True,
            )

        except McpProtocolError as e:
            # JSON-RPC protocol errors carry the server's code/message — let the
            # classifier bucket them (e.g. -32602 -> validation, 403 -> permission).
            error_msg = f"MCP protocol error: {e}"
            logger.error(f"{self.name}: {error_msg}")
            return ToolResultEnvelope.failure(error_msg)

        except Exception as e:
            # Catch-all for any unexpected errors
            error_msg = f"Unexpected error: {e}"
            logger.error(f"{self.name}: {error_msg}", exc_info=True)
            return ToolResultEnvelope.failure(error_msg)

    def _envelope_from_response(self, response: dict[str, Any]) -> ToolResultEnvelope:
        """Build a result envelope from a successful JSON-RPC tool response.

        Handles the MCP ``isError: true`` flag (a tool-execution failure
        reported inside an otherwise-successful JSON-RPC result) and the
        access-failure vs valid-empty-result distinction.
        """
        content = response.get("content", [])

        formatted_parts = [self._format_content_block(block) for block in content]
        result_text = "\n\n".join(part for part in formatted_parts if part)

        # MCP spec: a tool may report a domain failure via ``isError: true``
        # while still returning HTTP/JSON-RPC success. That is a TRUE error the
        # model must see — surface it through the envelope (not as plain text).
        if response.get("isError"):
            error_text = result_text or "Tool reported an error with no detail"
            logger.warning(f"{self.name}: tool returned isError -> {error_text}")
            return ToolResultEnvelope.failure(error_text)

        # No content + no isError == a *valid* empty result (e.g. a search that
        # matched nothing). This is explicitly NOT an access failure.
        if not result_text:
            logger.debug(f"{self.name}: tool returned a valid empty result")
            return ToolResultEnvelope.success(EMPTY_RESULT_TEXT, is_empty=True)

        logger.debug(f"Tool result length: {len(result_text)} chars")
        return ToolResultEnvelope.success(result_text)

    @staticmethod
    def _format_content_block(block: dict[str, Any]) -> str:
        """Format a single MCP content block into a display string."""
        block_type = block.get("type")

        if block_type == "text":
            return block.get("text", "")

        if block_type == "image":
            # Image blocks have data URL
            image_data = block.get("data", "")
            mime_type = block.get("mimeType", "image/png")
            return f"[Image: {mime_type}, {len(image_data)} bytes]"

        if block_type == "resource":
            return McpToolAdapter._format_resource_block(block)

        # Unknown block type
        return f"[Unknown block type: {block_type}]"

    @staticmethod
    def _format_resource_block(block: dict[str, Any]) -> str:
        """Format a resource content block, including inline text if present."""
        resource = block.get("resource", {})
        resource_uri = resource.get("uri", "")
        resource_text = resource.get("text", "")
        if resource_text:
            return f"[Resource: {resource_uri}]\n{resource_text}"
        return f"[Resource: {resource_uri}]"

    def to_dict(self) -> dict[str, Any]:
        """Convert adapter to dictionary representation.

        Used for tool registry serialization.

        Returns:
            Tool metadata dict
        """
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "server_name": self.server_name,
            "original_tool_name": self.tool_descriptor.name,
            "type": "mcp_tool",
            "execute": self.execute,
        }

    @classmethod
    async def create_all_for_server(
        cls,
        server_name: str,
        client: McpProtocolClient,
        tool_discovery: ToolDiscovery,
    ) -> list["McpToolAdapter"]:
        """Create adapters for all tools on a server.

        Args:
            server_name: Server name
            client: Protocol client
            tool_discovery: Tool discovery service

        Returns:
            List of tool adapters
        """
        try:
            # Discover tools
            tools = await tool_discovery.discover_tools(server_name, client)

            # Create adapters
            adapters = [
                cls(server_name, tool_descriptor, client) for tool_descriptor in tools
            ]

            logger.info(f"Created {len(adapters)} tool adapters for {server_name}")
            return adapters

        except Exception as e:
            logger.error(f"Failed to create tool adapters for {server_name}: {e}")
            return []
