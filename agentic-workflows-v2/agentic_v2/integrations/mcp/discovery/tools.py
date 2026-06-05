"""Tool discovery service with LRU caching.

Fetches and caches tool lists from MCP servers, invalidating on server
notifications.
"""

import logging

from cachetools import TTLCache

from agentic_v2.integrations.mcp.protocol.client import McpProtocolClient
from agentic_v2.integrations.mcp.types import McpToolDescriptor

logger = logging.getLogger(__name__)

# Cache configuration
CACHE_MAX_SIZE = 100
CACHE_TTL_SECONDS = 300  # 5 minutes TTL as fallback


class ToolDiscovery:
    """Service for discovering tools from MCP servers.

    Features:
    - Fetches tools/list from servers with tool capability
    - LRU cache with TTL for performance
    - Automatic invalidation on notifications/tools/list_changed
    - Thread-safe cache operations
    """

    def __init__(self) -> None:
        """Initialize tool discovery service."""
        self._cache: TTLCache = TTLCache(maxsize=CACHE_MAX_SIZE, ttl=CACHE_TTL_SECONDS)

    async def discover_tools(
        self,
        server_name: str,
        client: McpProtocolClient,
    ) -> list[McpToolDescriptor]:
        """Discover tools from an MCP server.

        Args:
            server_name: Server name (for cache key)
            client: Connected protocol client

        Returns:
            List of tool descriptors

        Raises:
            RuntimeError: If server doesn't support tools capability
        """
        # Check capability
        if not client.capabilities or not client.capabilities.tools:
            raise RuntimeError(f"Server {server_name} does not support tools")

        # Check cache
        if server_name in self._cache:
            logger.debug(f"Using cached tools for {server_name}")
            return self._cache[server_name]

        # Fetch from server
        logger.info(f"Fetching tools from {server_name}")
        try:
            response = await client.request("tools/list", timeout=30.0)
            tools_data = response.get("tools", [])

            # Parse into descriptors
            tools = []
            for tool_data in tools_data:
                try:
                    descriptor = McpToolDescriptor(
                        name=tool_data["name"],
                        description=tool_data.get("description"),
                        input_schema=tool_data.get("inputSchema", {}),
                    )
                    tools.append(descriptor)
                except Exception as e:
                    logger.warning(
                        f"Failed to parse tool {tool_data.get('name', 'unknown')}: {e}"
                    )

            # Cache result
            self._cache[server_name] = tools
            logger.info(f"Discovered {len(tools)} tools from {server_name}")

            return tools

        except Exception as e:
            logger.error(f"Failed to fetch tools from {server_name}: {e}")
            raise

    def invalidate_cache(self, server_name: str) -> None:
        """Invalidate cached tools for a server.

        Called when server sends notifications/tools/list_changed.

        Args:
            server_name: Server to invalidate
        """
        if server_name in self._cache:
            del self._cache[server_name]
            logger.info(f"Invalidated tool cache for {server_name}")

    def invalidate_all(self) -> None:
        """Clear all cached tools."""
        self._cache.clear()
        logger.info("Cleared all tool caches")

    def register_client_notification_handlers(
        self,
        server_name: str,
        client: McpProtocolClient,
    ) -> None:
        """Register notification handlers for cache invalidation.

        Args:
            server_name: Server name
            client: Protocol client to register handlers on
        """

        def on_tools_list_changed(params: dict) -> None:
            logger.info(f"Tools changed notification from {server_name}")
            self.invalidate_cache(server_name)

        client.register_notification_handler(
            "notifications/tools/list_changed", on_tools_list_changed
        )
        logger.debug(f"Registered tool notification handler for {server_name}")
