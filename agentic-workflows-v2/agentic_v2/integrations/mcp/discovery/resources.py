"""Resource discovery service with LRU caching.

Fetches and caches resource lists from MCP servers, invalidating on
server notifications.
"""

import logging
from agentic_v2.integrations.mcp.protocol.client import McpProtocolClient
from agentic_v2.integrations.mcp.types import McpResourceDescriptor
from cachetools import TTLCache

logger = logging.getLogger(__name__)

# Cache configuration
CACHE_MAX_SIZE = 100
CACHE_TTL_SECONDS = 300  # 5 minutes TTL as fallback


class ResourceDiscovery:
    """Service for discovering resources from MCP servers.

    Features:
    - Fetches resources/list from servers with resource capability
    - LRU cache with TTL for performance
    - Automatic invalidation on notifications/resources/list_changed
    - Thread-safe cache operations
    """

    def __init__(self) -> None:
        """Initialize resource discovery service."""
        self._cache: TTLCache = TTLCache(maxsize=CACHE_MAX_SIZE, ttl=CACHE_TTL_SECONDS)

    async def discover_resources(
        self,
        server_name: str,
        client: McpProtocolClient,
    ) -> list[McpResourceDescriptor]:
        """Discover resources from an MCP server.

        Args:
            server_name: Server name (for cache key)
            client: Connected protocol client

        Returns:
            List of resource descriptors

        Raises:
            RuntimeError: If server doesn't support resources capability
        """
        # Check capability
        if not client.capabilities or not client.capabilities.resources:
            raise RuntimeError(f"Server {server_name} does not support resources")

        # Check cache
        if server_name in self._cache:
            logger.debug(f"Using cached resources for {server_name}")
            return self._cache[server_name]

        # Fetch from server
        logger.info(f"Fetching resources from {server_name}")
        try:
            response = await client.request("resources/list", timeout=30.0)
            resources_data = response.get("resources", [])

            # Parse into descriptors
            resources = []
            for resource_data in resources_data:
                try:
                    descriptor = McpResourceDescriptor(
                        uri=resource_data["uri"],
                        name=resource_data.get("name"),
                        description=resource_data.get("description"),
                        mime_type=resource_data.get("mimeType"),
                    )
                    resources.append(descriptor)
                except Exception as e:
                    logger.warning(
                        f"Failed to parse resource {resource_data.get('uri', 'unknown')}: {e}"
                    )

            # Cache result
            self._cache[server_name] = resources
            logger.info(f"Discovered {len(resources)} resources from {server_name}")

            return resources

        except Exception as e:
            logger.error(f"Failed to fetch resources from {server_name}: {e}")
            raise

    async def read_resource(
        self,
        server_name: str,
        client: McpProtocolClient,
        uri: str,
    ) -> dict:
        """Read a specific resource from an MCP server.

        Args:
            server_name: Server name (for logging)
            client: Connected protocol client
            uri: Resource URI to read

        Returns:
            Resource contents (structure varies by resource)

        Raises:
            RuntimeError: If server doesn't support resources
        """
        # Check capability
        if not client.capabilities or not client.capabilities.resources:
            raise RuntimeError(f"Server {server_name} does not support resources")

        logger.debug(f"Reading resource {uri} from {server_name}")
        try:
            response = await client.request(
                "resources/read",
                params={"uri": uri},
                timeout=60.0,  # Resources can be large
            )
            return response

        except Exception as e:
            logger.error(f"Failed to read resource {uri} from {server_name}: {e}")
            raise

    def invalidate_cache(self, server_name: str) -> None:
        """Invalidate cached resources for a server.

        Called when server sends notifications/resources/list_changed.

        Args:
            server_name: Server to invalidate
        """
        if server_name in self._cache:
            del self._cache[server_name]
            logger.info(f"Invalidated resource cache for {server_name}")

    def invalidate_all(self) -> None:
        """Clear all cached resources."""
        self._cache.clear()
        logger.info("Cleared all resource caches")

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

        def on_resources_list_changed(params: dict) -> None:
            logger.info(f"Resources changed notification from {server_name}")
            self.invalidate_cache(server_name)

        client.register_notification_handler(
            "notifications/resources/list_changed", on_resources_list_changed
        )
        logger.debug(f"Registered resource notification handler for {server_name}")
