"""
MCP Tool Adapter - wraps remote MCP tools as local tool instances.

Critical design choices:
1. **Schema Passthrough**: Original JSON Schema preserved verbatim (no Pydantic reconstruction)
2. **Namespacing**: Tools named `mcp_{server_name}_{tool_name}` to prevent conflicts
3. **Error Trapping**: All execution errors caught and returned as friendly strings (never crash orchestrator)
4. **Timeout Enforcement**: All tool calls wrapped with configurable timeout
"""

import asyncio
import logging
from typing import Any, Optional

from agentic_v2.integrations.mcp.discovery.tools import ToolDiscovery
from agentic_v2.integrations.mcp.protocol.client import (
    McpProtocolClient,
    McpProtocolError,
    McpTimeoutError,
)
from agentic_v2.integrations.mcp.types import McpToolDescriptor

logger = logging.getLogger(__name__)

# Tool execution timeout (matching claude-code-main)
TOOL_CALL_TIMEOUT = 120.0  # 2 minutes


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
        timeout: Optional[float] = None,
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
        timeout: Optional[float] = None,
    ) -> str:
        """Execute the remote tool.

        Args:
            arguments: Tool input arguments (validated against input_schema)
            timeout: Execution timeout (default: 120s)

        Returns:
            Tool result as string (never raises exceptions to LLM)
        """
        timeout_value = timeout or self._default_timeout or TOOL_CALL_TIMEOUT

        logger.info(
            f"Executing MCP tool {self.tool_descriptor.name} on {self.server_name}"
        )
        logger.debug(f"Tool arguments: {arguments}")

        try:
            # Call remote tool with timeout
            response = await asyncio.wait_for(
                self.client.call_tool(self.tool_descriptor.name, arguments),
                timeout=timeout_value,
            )

            # Extract content from response
            content = response.get("content", [])

            # Format response based on content type
            if not content:
                return "[Tool returned no content]"

            # MCP tools can return multiple content blocks
            formatted_parts = []
            for block in content:
                block_type = block.get("type")

                if block_type == "text":
                    formatted_parts.append(block.get("text", ""))

                elif block_type == "image":
                    # Image blocks have data URL
                    image_data = block.get("data", "")
                    mime_type = block.get("mimeType", "image/png")
                    formatted_parts.append(
                        f"[Image: {mime_type}, {len(image_data)} bytes]"
                    )

                elif block_type == "resource":
                    # Resource reference — include URI and inline text if present
                    resource = block.get("resource", {})
                    resource_uri = resource.get("uri", "")
                    resource_text = resource.get("text", "")
                    if resource_text:
                        formatted_parts.append(
                            f"[Resource: {resource_uri}]\n{resource_text}"
                        )
                    else:
                        formatted_parts.append(f"[Resource: {resource_uri}]")

                else:
                    # Unknown block type
                    formatted_parts.append(f"[Unknown block type: {block_type}]")

            result = "\n\n".join(formatted_parts)
            logger.debug(f"Tool result length: {len(result)} chars")
            return result

        except TimeoutError:
            error_msg = f"Tool execution timed out after {timeout_value}s"
            logger.warning(f"{self.name}: {error_msg}")
            return f"Error: {error_msg}"

        except McpTimeoutError as e:
            error_msg = f"MCP protocol timeout: {e}"
            logger.warning(f"{self.name}: {error_msg}")
            return f"Error: {error_msg}"

        except McpProtocolError as e:
            error_msg = f"MCP protocol error: {e}"
            logger.error(f"{self.name}: {error_msg}")
            return f"Error: {error_msg}"

        except Exception as e:
            # Catch-all for any unexpected errors
            error_msg = f"Unexpected error: {e}"
            logger.error(f"{self.name}: {error_msg}", exc_info=True)
            return f"Error: {error_msg}"

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
