"""
MCP Prompt Adapter - proxies MCP prompts as local context sources.

Prompts are server-defined context templates that can be parameterized.
"""

import logging
from typing import Any, Optional

from agentic_v2.integrations.mcp.discovery.prompts import PromptDiscovery
from agentic_v2.integrations.mcp.protocol.client import McpProtocolClient
from agentic_v2.integrations.mcp.types import McpPromptDescriptor

logger = logging.getLogger(__name__)


class McpPromptAdapter:
    """Adapter for MCP prompts.

    Prompts are reusable context templates (e.g., "code review
    guidelines", "bug report template") that can be dynamically inserted
    into agent context.
    """

    def __init__(
        self,
        server_name: str,
        prompt_descriptor: McpPromptDescriptor,
        client: McpProtocolClient,
    ) -> None:
        """Initialize prompt adapter.

        Args:
            server_name: Server providing this prompt
            prompt_descriptor: Prompt metadata from discovery
            client: Protocol client for prompt retrieval
        """
        self.server_name = server_name
        self.prompt_descriptor = prompt_descriptor
        self.client = client

        # Namespaced prompt name
        self.name = f"mcp_{server_name}_{prompt_descriptor.name}"
        self.description = (
            prompt_descriptor.description
            or f"Prompt '{prompt_descriptor.name}' from MCP server '{server_name}'"
        )
        self.arguments = prompt_descriptor.arguments

    async def get_content(
        self,
        arguments: Optional[dict[str, Any]] = None,
    ) -> str:
        """Retrieve prompt content from server.

        Args:
            arguments: Prompt parameters (if parameterized)

        Returns:
            Prompt content as string
        """
        logger.info(
            f"Retrieving MCP prompt {self.prompt_descriptor.name} from {self.server_name}"
        )

        try:
            # Fetch from server via discovery service
            prompt_discovery = PromptDiscovery()
            response = await prompt_discovery.get_prompt(
                self.server_name,
                self.client,
                self.prompt_descriptor.name,
                arguments or {},
            )

            # Extract messages from response
            messages = response.get("messages", [])

            # Format messages into single string
            formatted_parts = []
            for message in messages:
                role = message.get("role", "assistant")
                content = message.get("content", {})

                # Content can be text or structured
                if isinstance(content, str):
                    formatted_parts.append(f"[{role}]: {content}")
                elif isinstance(content, dict) and "text" in content:
                    formatted_parts.append(f"[{role}]: {content['text']}")
                else:
                    formatted_parts.append(f"[{role}]: {content}")  # Fallback

            result = "\n\n".join(formatted_parts)
            logger.debug(f"Prompt content length: {len(result)} chars")
            return result

        except Exception as e:
            error_msg = f"Failed to retrieve prompt: {e}"
            logger.error(f"{self.name}: {error_msg}")
            return f"Error: {error_msg}"

    def to_dict(self) -> dict[str, Any]:
        """Convert adapter to dictionary representation.

        Returns:
            Prompt metadata dict
        """
        return {
            "name": self.name,
            "description": self.description,
            "arguments": self.arguments,
            "server_name": self.server_name,
            "original_prompt_name": self.prompt_descriptor.name,
            "type": "mcp_prompt",
        }

    @classmethod
    async def create_all_for_server(
        cls,
        server_name: str,
        client: McpProtocolClient,
        prompt_discovery: PromptDiscovery,
    ) -> list["McpPromptAdapter"]:
        """Create adapters for all prompts on a server.

        Args:
            server_name: Server name
            client: Protocol client
            prompt_discovery: Prompt discovery service

        Returns:
            List of prompt adapters
        """
        try:
            # Discover prompts
            prompts = await prompt_discovery.discover_prompts(server_name, client)

            # Create adapters
            adapters = [
                cls(server_name, prompt_descriptor, client)
                for prompt_descriptor in prompts
            ]

            logger.info(f"Created {len(adapters)} prompt adapters for {server_name}")
            return adapters

        except Exception as e:
            logger.error(f"Failed to create prompt adapters for {server_name}: {e}")
            return []
