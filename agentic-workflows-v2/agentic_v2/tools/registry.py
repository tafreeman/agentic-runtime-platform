"""Tool registry with auto-discovery."""

from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path

from .base import BaseTool, ToolSchema

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Registry for managing tools.

    Supports:
    - Manual registration
    - Auto-discovery from builtin tools
    - Tool lookup by name
    - Listing tools by tier
    """

    def __init__(self):
        """Initialize the registry."""
        self._tools: dict[str, BaseTool] = {}
        self._initialized = False

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance.

        Args:
            tool: Tool instance to register
        """
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        """Get a tool by name.

        Args:
            name: Tool name

        Returns:
            Tool instance or None if not found
        """
        if not self._initialized:
            self.discover_builtin()
        return self._tools.get(name)

    def list_tools(self, tier: int | None = None) -> list[BaseTool]:
        """List all registered tools, optionally filtered by tier.

        Args:
            tier: Filter by tier (0-3), or None for all

        Returns:
            List of tool instances
        """
        if not self._initialized:
            self.discover_builtin()

        tools = list(self._tools.values())
        if tier is not None:
            tools = [t for t in tools if t.tier == tier]
        return tools

    def get_schemas(self, tier: int | None = None) -> list[ToolSchema]:
        """Get schemas for all tools, optionally filtered by tier.

        Args:
            tier: Filter by tier (0-3), or None for all

        Returns:
            List of tool schemas
        """
        tools = self.list_tools(tier=tier)
        return [tool.get_schema() for tool in tools]

    def discover_builtin(self) -> None:
        """Auto-discover and register all builtin tools.

        Scans the builtin/ directory for tool implementations and
        registers them automatically.
        """
        if self._initialized:
            return

        try:
            # Import builtin module
            from . import builtin

            # Get the builtin package path
            builtin_path = Path(builtin.__file__).parent

            # Discover all modules in builtin/
            for module_info in pkgutil.iter_modules([str(builtin_path)]):
                if module_info.name.startswith("_"):
                    continue

                # Import the module
                module = importlib.import_module(
                    f".builtin.{module_info.name}", package="agentic_v2.tools"
                )

                # Find all tool classes
                for attr_name in dir(module):
                    if attr_name.startswith("_"):
                        continue

                    attr = getattr(module, attr_name)

                    # Check if it's a tool class (not the base class)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, BaseTool)
                        and attr is not BaseTool
                    ):
                        # Instantiate and register
                        tool_instance = attr()
                        self.register(tool_instance)

            self._initialized = True
        except Exception as e:
            # Log error but don't fail
            logger.warning(f"Failed to discover builtin tools: {e}")

    def clear(self) -> None:
        """Clear all registered tools."""
        self._tools.clear()
        self._initialized = False

    def __len__(self) -> int:
        """Return the number of registered tools."""
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        """Check if a tool is registered."""
        if not self._initialized:
            self.discover_builtin()
        return name in self._tools

    def __repr__(self) -> str:
        """Return string representation."""
        if not self._initialized:
            self.discover_builtin()
        return f"ToolRegistry({len(self._tools)} tools registered)"


# Global registry instance
_global_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    """Get or create the global tool registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
        _global_registry.discover_builtin()
    return _global_registry


def reset_registry() -> None:
    """Reset the global registry (useful for testing)."""
    global _global_registry
    _global_registry = None
