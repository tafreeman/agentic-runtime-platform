"""Model Context Protocol (MCP) Integration Package.

This package provides a production-ready Python implementation of an MCP client
for dynamically loading tools, resources, and prompts from external MCP servers.

Architecture:
- transports/: Raw byte-stream adapters (stdio, websocket)
- protocol/: JSON-RPC message correlation and timeout management
- runtime/: Connection lifecycle, reconnection, exponential backoff
- discovery/: Tool/resource/prompt capability fetching with LRU caching
- adapters/: Bridge between MCP capabilities and local tool registry
- results/: Output safety, truncation, and context budget protection
- config.py: Configuration loading from .mcp.json files with variable expansion
"""

from agentic_v2.integrations.mcp.config import McpConfigLoader
from agentic_v2.integrations.mcp.types import (
    McpConnectionState,
    McpServerConfig,
    McpSSEConfig,
    McpStdioConfig,
    McpTransportConfig,
    McpWebSocketConfig,
    TransportType,
)

__all__ = [
    "McpConfigLoader",
    "McpConnectionState",
    "McpServerConfig",
    "McpStdioConfig",
    "McpTransportConfig",
    "McpWebSocketConfig",
    "McpSSEConfig",
    "TransportType",
]
