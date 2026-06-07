"""
MCP Resource Adapter - exposes meta-tools for resource discovery and reading.

Provides two special tools to the LLM:
1. `list_mcp_resources` - Lists all resources from connected servers
2. `read_mcp_resource` - Reads a specific resource by URI
"""

import logging
from typing import Any

from agentic_v2.integrations.mcp.discovery.resources import ResourceDiscovery
from agentic_v2.integrations.mcp.runtime.manager import McpConnectionManager

logger = logging.getLogger(__name__)


class McpResourceAdapter:
    """Adapter that provides resource meta-tools to the LLM.

    Unlike tool and prompt adapters (which wrap individual
    capabilities), this adapter exposes generic meta-tools that work
    across all servers.
    """

    def __init__(
        self,
        connection_manager: McpConnectionManager,
        resource_discovery: ResourceDiscovery,
    ) -> None:
        """Initialize resource adapter.

        Args:
            connection_manager: Manager for all MCP connections
            resource_discovery: Resource discovery service
        """
        self.connection_manager = connection_manager
        self.resource_discovery = resource_discovery

    async def list_resources(self, server_name: str | None = None) -> str:
        """List available resources from MCP servers.

        Args:
            server_name: Optional server filter (list from single server)

        Returns:
            Formatted list of resources
        """
        logger.info(f"Listing MCP resources (server: {server_name or 'all'})")

        try:
            all_resources = []

            # Get connections
            connections = self.connection_manager.list_connections()

            for name, (state, _) in connections.items():
                if not self._is_connection_listable(name, state, server_name):
                    continue

                client = self.connection_manager.get_connection(name)
                if not client:
                    continue

                await self._collect_server_resources(name, client, all_resources)

            return self._format_resource_list(all_resources)

        except Exception as e:
            error_msg = f"Failed to list resources: {e}"
            logger.error(error_msg)
            return f"Error: {error_msg}"

    @staticmethod
    def _is_connection_listable(
        name: str, state: Any, server_name: str | None
    ) -> bool:
        """Return True if a connection should be included in resource listing."""
        # Filter by server if specified
        if server_name and name != server_name:
            return False
        # Skip if not connected
        return state.value == "connected"

    async def _collect_server_resources(
        self,
        name: str,
        client: Any,
        all_resources: list[dict[str, Any]],
    ) -> None:
        """Discover resources from one server and append them to all_resources."""
        try:
            resources = await self.resource_discovery.discover_resources(name, client)
            for resource in resources:
                all_resources.append(
                    {
                        "server": name,
                        "uri": resource.uri,
                        "name": resource.name or "(unnamed)",
                        "description": resource.description or "",
                        "mime_type": resource.mime_type or "unknown",
                    }
                )
        except Exception as e:
            logger.warning(f"Failed to list resources from {name}: {e}")

    @staticmethod
    def _format_resource_list(all_resources: list[dict[str, Any]]) -> str:
        """Format collected resources into a human-readable string."""
        if not all_resources:
            return "No resources available from connected MCP servers."

        lines = [f"Found {len(all_resources)} resources:\n"]
        for i, res in enumerate(all_resources, 1):
            lines.append(
                f"{i}. [{res['server']}] {res['name']}\n"
                f"   URI: {res['uri']}\n"
                f"   Type: {res['mime_type']}\n"
                f"   Description: {res['description']}\n"
            )

        return "\n".join(lines)

    async def read_resource(self, uri: str) -> str:
        """Read a specific resource by URI.

        Args:
            uri: Resource URI (format: mcp://server/path or server-specific)

        Returns:
            Resource content as string
        """
        logger.info(f"Reading MCP resource: {uri}")

        try:
            # Parse URI to extract server name
            # Format: mcp://server_name/resource_path
            if uri.startswith("mcp://"):
                parts = uri[6:].split("/", 1)
                if len(parts) < 2:
                    return f"Error: Invalid MCP resource URI: {uri}"
                server_name = parts[0]
            else:
                # Fallback: try to find which server has this resource
                server_name = await self._find_resource_server(uri)
                if not server_name:
                    return f"Error: Could not determine server for resource: {uri}"

            # Get client
            client = self.connection_manager.get_connection(server_name)
            if not client:
                return f"Error: Not connected to server: {server_name}"

            # Read resource
            response = await self.resource_discovery.read_resource(
                server_name, client, uri
            )

            # Extract content
            contents = response.get("contents", [])
            if not contents:
                return "[Resource returned no content]"

            # Format content blocks
            formatted_parts = []
            for content in contents:
                content_type = content.get("type")

                if content_type == "text":
                    formatted_parts.append(content.get("text", ""))

                elif content_type == "blob":
                    # Binary data
                    blob_data = content.get("blob", "")
                    mime_type = content.get("mimeType", "application/octet-stream")
                    formatted_parts.append(
                        f"[Binary data: {mime_type}, {len(blob_data)} bytes]\n"
                        f"(Binary content not displayed)"
                    )

                else:
                    formatted_parts.append(f"[Unknown content type: {content_type}]")

            result = "\n\n".join(formatted_parts)
            logger.debug(f"Resource content length: {len(result)} chars")
            return result

        except Exception as e:
            error_msg = f"Failed to read resource: {e}"
            logger.error(error_msg)
            return f"Error: {error_msg}"

    async def _find_resource_server(self, uri: str) -> str | None:
        """Find which server provides a given resource URI.

        Args:
            uri: Resource URI

        Returns:
            Server name if found, None otherwise
        """
        connections = self.connection_manager.list_connections()

        for name, (state, _) in connections.items():
            if state.value != "connected":
                continue

            client = self.connection_manager.get_connection(name)
            if not client:
                continue

            try:
                resources = await self.resource_discovery.discover_resources(
                    name, client
                )
                if any(r.uri == uri for r in resources):
                    return name
            except Exception:
                continue

        return None

    def get_meta_tools(self) -> list[dict[str, Any]]:
        """Get meta-tool definitions for tool registry.

        Returns:
            List of tool definitions
        """
        return [
            {
                "name": "list_mcp_resources",
                "description": (
                    "List all available resources from connected MCP servers. "
                    "Resources are files, data, or context provided by external tools."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "server_name": {
                            "type": "string",
                            "description": "Optional: filter by server name",
                        }
                    },
                },
                "handler": self.list_resources,
                "type": "mcp_meta_tool",
            },
            {
                "name": "read_mcp_resource",
                "description": (
                    "Read the content of a specific MCP resource by its URI. "
                    "Use list_mcp_resources first to discover available resources."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "uri": {
                            "type": "string",
                            "description": "Resource URI (from list_mcp_resources)",
                        }
                    },
                    "required": ["uri"],
                },
                "handler": self.read_resource,
                "type": "mcp_meta_tool",
            },
        ]
