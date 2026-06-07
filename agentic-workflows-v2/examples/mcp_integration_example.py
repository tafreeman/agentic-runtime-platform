"""MCP Client Integration Example.

Demonstrates end-to-end usage of the MCP client:
1. Load configuration from .mcp.json
2. Connect to MCP servers
3. Discover tools and resources
4. Create adapters for LLM invocation
5. Handle oversized outputs safely
"""

import asyncio
import logging

from agentic_v2.integrations.mcp import McpConfigLoader
from agentic_v2.integrations.mcp.adapters.resource_adapter import (
    McpResourceAdapter,
)
from agentic_v2.integrations.mcp.adapters.tool_adapter import McpToolAdapter
from agentic_v2.integrations.mcp.discovery.resources import ResourceDiscovery
from agentic_v2.integrations.mcp.discovery.tools import ToolDiscovery
from agentic_v2.integrations.mcp.protocol.client import McpProtocolClient
from agentic_v2.integrations.mcp.results.budget import ContextBudgetGuard
from agentic_v2.integrations.mcp.results.storage import McpOutputStorage
from agentic_v2.integrations.mcp.runtime.manager import McpConnectionManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    """Main integration example."""

    # Step 1: Load configuration from .mcp.json files
    logger.info("Loading MCP configuration...")
    loader = McpConfigLoader()
    configs = loader.get_enabled()

    if not configs:
        logger.warning("No MCP servers configured. Create .mcp.json in project root.")
        return

    logger.info(f"Found {len(configs)} enabled MCP servers")

    # Step 2: Connect to all servers
    logger.info("Connecting to MCP servers...")
    manager = McpConnectionManager()
    clients: list[McpProtocolClient] = []

    for config in configs:
        try:
            client = await manager.connect(config.name, config)
            clients.append(client)
            logger.info(f"✅ Connected to {config.name}")
        except Exception as e:
            logger.error(f"❌ Failed to connect to {config.name}: {e}")

    if not clients:
        logger.error("No successful connections. Exiting.")
        return

    # Step 3: Discover capabilities from all servers
    logger.info("Discovering tools and resources...")
    tool_discovery = ToolDiscovery()
    resource_discovery = ResourceDiscovery()
    all_tools = []
    all_resources = []

    for client, config in zip(clients, configs):
        try:
            # Discover tools
            tools = await tool_discovery.discover_tools(config.name, client)
            all_tools.extend(tools)
            logger.info(f"Found {len(tools)} tools from {config.name}")

            # Discover resources
            resources = await resource_discovery.discover_resources(config.name, client)
            all_resources.extend(resources)
            logger.info(f"Found {len(resources)} resources from {config.name}")

        except Exception as e:
            logger.error(f"Failed to discover capabilities from {config.name}: {e}")

    logger.info(f"Total: {len(all_tools)} tools, {len(all_resources)} resources")

    # Step 4: Create adapters for LLM invocation
    logger.info("Creating tool adapters...")
    tool_adapters = []

    for tool in all_tools:
        # Find the client for this tool (match by server name)
        tool_server = tool.name.split("_")[1]  # Assumes "mcp_<server>_<tool>"
        client = clients[0]  # Simplified: example uses the first client

        adapter = McpToolAdapter(
            server_name=tool_server,
            tool_descriptor=tool,
            client=client,
        )
        tool_adapters.append(adapter)

    logger.info(f"Created {len(tool_adapters)} tool adapters")

    # Step 5: Example tool execution with output safety
    if tool_adapters:
        logger.info("Testing first tool with output safety...")
        adapter = tool_adapters[0]

        # Set up output safety
        guard = ContextBudgetGuard(max_tokens=25000)
        storage = McpOutputStorage()

        try:
            # Execute tool (use empty args for demo)
            result = await adapter.execute({})

            # Check token budget
            if guard.is_oversized(result):
                logger.warning("Output exceeds budget, saving to disk...")
                _, rel_path = storage.save_text_output(
                    result,
                    server_name=adapter.server_name,
                    tool_name=adapter.tool_descriptor.name,
                )
                result = storage.generate_file_pointer_message(
                    rel_path, len(result), format_description="Tool Output"
                )

            logger.info(f"Tool result: {result[:200]}...")  # Show first 200 chars

        except Exception as e:
            logger.error(f"Tool execution failed: {e}")

    # Step 6: Resource adapter example
    logger.info("Creating resource meta-tools...")
    resource_adapter = McpResourceAdapter(
        connection_manager=manager,
        resource_discovery=resource_discovery,
    )

    # Get meta-tools for tool registry
    meta_tools = resource_adapter.get_meta_tools()
    logger.info(f"Created {len(meta_tools)} resource meta-tools")

    # Example: List all resources
    try:
        resources_list = await resource_adapter.list_resources()
        logger.info(f"Available resources:\n{resources_list}")
    except Exception as e:
        logger.error(f"Failed to list resources: {e}")

    # Step 7: Cleanup
    logger.info("Closing connections...")
    await manager.disconnect_all()

    logger.info("Integration example complete!")


async def register_with_tool_registry_example():
    """Example of how to integrate MCP tools into the main tool registry.

    This would be called during application startup.
    """
    # Load MCP configs
    loader = McpConfigLoader()
    configs = loader.get_enabled()

    # Connect to servers
    manager = McpConnectionManager()
    mcp_clients = {}

    for config in configs:
        try:
            client = await manager.connect(config.name, config)
            mcp_clients[config.name] = client
        except Exception as e:
            logger.error(f"Failed to connect to {config.name}: {e}")

    # Discover all tools
    tool_discovery = ToolDiscovery()
    resource_discovery = ResourceDiscovery()
    all_tool_adapters = []

    for server_name, client in mcp_clients.items():
        tools = await tool_discovery.discover_tools(server_name, client)
        for tool in tools:
            adapter = McpToolAdapter(
                server_name=server_name,
                tool_descriptor=tool,
                client=client,
            )
            all_tool_adapters.append(adapter)

    # Register with main tool registry (pseudocode)
    # from agentic_v2.tools.registry import ToolRegistry
    # registry = ToolRegistry()
    # for adapter in all_tool_adapters:
    #     registry.register(adapter.to_dict())

    logger.info(f"Registered {len(all_tool_adapters)} MCP tools")

    # Resource meta-tools
    resource_adapter = McpResourceAdapter(
        connection_manager=manager,
        resource_discovery=resource_discovery,
    )
    for meta_tool in resource_adapter.get_meta_tools():
        # registry.register(meta_tool)
        logger.info(f"Registered resource meta-tool: {meta_tool['name']}")

    return all_tool_adapters, resource_adapter


if __name__ == "__main__":
    """Run the integration example."""
    asyncio.run(main())
