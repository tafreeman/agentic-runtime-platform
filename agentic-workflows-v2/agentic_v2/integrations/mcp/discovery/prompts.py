"""Prompt discovery service with LRU caching.

Fetches and caches prompt lists from MCP servers, invalidating on server
notifications.
"""

import logging
from typing import Optional

from agentic_v2.integrations.mcp.protocol.client import McpProtocolClient
from agentic_v2.integrations.mcp.types import McpPromptDescriptor
from cachetools import TTLCache

logger = logging.getLogger(__name__)

# Cache configuration
CACHE_MAX_SIZE = 100
CACHE_TTL_SECONDS = 300  # 5 minutes TTL as fallback


class PromptDiscovery:
    """Service for discovering prompts from MCP servers.

    Features:
    - Fetches prompts/list from servers with prompt capability
    - LRU cache with TTL for performance
    - Automatic invalidation on notifications/prompts/list_changed
    - Thread-safe cache operations
    """

    def __init__(self) -> None:
        """Initialize prompt discovery service."""
        self._cache: TTLCache = TTLCache(maxsize=CACHE_MAX_SIZE, ttl=CACHE_TTL_SECONDS)

    async def discover_prompts(
        self,
        server_name: str,
        client: McpProtocolClient,
    ) -> list[McpPromptDescriptor]:
        """Discover prompts from an MCP server.

        Args:
            server_name: Server name (for cache key)
            client: Connected protocol client

        Returns:
            List of prompt descriptors

        Raises:
            RuntimeError: If server doesn't support prompts capability
        """
        # Check capability
        if not client.capabilities or not client.capabilities.prompts:
            raise RuntimeError(f"Server {server_name} does not support prompts")

        # Check cache
        if server_name in self._cache:
            logger.debug(f"Using cached prompts for {server_name}")
            return self._cache[server_name]

        # Fetch from server
        logger.info(f"Fetching prompts from {server_name}")
        try:
            response = await client.request("prompts/list", timeout=30.0)
            prompts_data = response.get("prompts", [])

            # Parse into descriptors
            prompts = []
            for prompt_data in prompts_data:
                try:
                    descriptor = McpPromptDescriptor(
                        name=prompt_data["name"],
                        description=prompt_data.get("description"),
                        arguments=prompt_data.get("arguments", []),
                    )
                    prompts.append(descriptor)
                except Exception as e:
                    logger.warning(
                        f"Failed to parse prompt {prompt_data.get('name', 'unknown')}: {e}"
                    )

            # Cache result
            self._cache[server_name] = prompts
            logger.info(f"Discovered {len(prompts)} prompts from {server_name}")

            return prompts

        except Exception as e:
            logger.error(f"Failed to fetch prompts from {server_name}: {e}")
            raise

    async def get_prompt(
        self,
        server_name: str,
        client: McpProtocolClient,
        prompt_name: str,
        arguments: Optional[dict] = None,
    ) -> dict:
        """Get a specific prompt from an MCP server.

        Args:
            server_name: Server name (for logging)
            client: Connected protocol client
            prompt_name: Prompt name to retrieve
            arguments: Optional arguments for parameterized prompts

        Returns:
            Prompt content (structure varies by prompt)

        Raises:
            RuntimeError: If server doesn't support prompts
        """
        # Check capability
        if not client.capabilities or not client.capabilities.prompts:
            raise RuntimeError(f"Server {server_name} does not support prompts")

        logger.debug(f"Getting prompt {prompt_name} from {server_name}")
        try:
            params = {"name": prompt_name}
            if arguments:
                params["arguments"] = arguments

            response = await client.request(
                "prompts/get",
                params=params,
                timeout=30.0,
            )
            return response

        except Exception as e:
            logger.error(f"Failed to get prompt {prompt_name} from {server_name}: {e}")
            raise

    def invalidate_cache(self, server_name: str) -> None:
        """Invalidate cached prompts for a server.

        Called when server sends notifications/prompts/list_changed.

        Args:
            server_name: Server to invalidate
        """
        if server_name in self._cache:
            del self._cache[server_name]
            logger.info(f"Invalidated prompt cache for {server_name}")

    def invalidate_all(self) -> None:
        """Clear all cached prompts."""
        self._cache.clear()
        logger.info("Cleared all prompt caches")

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

        def on_prompts_list_changed(params: dict) -> None:
            logger.info(f"Prompts changed notification from {server_name}")
            self.invalidate_cache(server_name)

        client.register_notification_handler(
            "notifications/prompts/list_changed", on_prompts_list_changed
        )
        logger.debug(f"Registered prompt notification handler for {server_name}")
