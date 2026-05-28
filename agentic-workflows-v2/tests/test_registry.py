"""Tests for tool registry."""

from __future__ import annotations

from agentic_v2.tools.base import BaseTool, ToolResult
from agentic_v2.tools.registry import ToolRegistry, get_registry, reset_registry


class DummyTool(BaseTool):
    """A dummy tool for testing."""

    @property
    def name(self) -> str:
        return "dummy"

    @property
    def description(self) -> str:
        return "A dummy tool"

    @property
    def parameters(self) -> dict:
        return {}

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, data="dummy result")


class TestToolRegistry:
    """Tests for ToolRegistry."""

    def test_register_and_get(self):
        """Test registering and retrieving a tool."""
        registry = ToolRegistry()
        tool = DummyTool()

        registry.register(tool)
        retrieved = registry.get("dummy")

        assert retrieved is not None
        assert retrieved.name == "dummy"

    def test_get_nonexistent(self):
        """Test getting a nonexistent tool."""
        registry = ToolRegistry()
        result = registry.get("nonexistent")

        assert result is None

    def test_discover_builtin(self):
        """Test auto-discovery of builtin tools."""
        registry = ToolRegistry()
        registry.discover_builtin()

        # Should have discovered multiple tools
        assert len(registry) > 0

        # Check for specific tools
        assert "file_copy" in registry
        assert "json_transform" in registry
        assert "template_render" in registry

    def test_list_tools_all(self):
        """Test listing all tools."""
        registry = ToolRegistry()
        registry.discover_builtin()

        tools = registry.list_tools()
        assert len(tools) > 0

    def test_list_tools_by_tier(self):
        """Test listing tools filtered by tier."""
        registry = ToolRegistry()
        registry.discover_builtin()

        # Should have tools at different tiers now
        tier0_tools = registry.list_tools(tier=0)
        tier1_tools = registry.list_tools(tier=1)
        tier2_tools = registry.list_tools(tier=2)
        all_tools = registry.list_tools()

        # All tools = tier0 + tier1 + tier2
        assert len(tier0_tools) + len(tier1_tools) + len(tier2_tools) == len(all_tools)

        # Verify we have tools in each tier
        assert len(tier0_tools) > 0  # Git, HTTP, Shell, File ops
        assert len(tier1_tools) > 0  # Code analysis
        assert len(tier2_tools) > 0  # Search

    def test_get_schemas(self):
        """Test getting tool schemas."""
        registry = ToolRegistry()
        registry.discover_builtin()

        schemas = registry.get_schemas()
        assert len(schemas) > 0

        # Check schema structure
        schema = schemas[0]
        assert hasattr(schema, "name")
        assert hasattr(schema, "description")
        assert hasattr(schema, "parameters")

    def test_global_registry(self):
        """Test global registry singleton."""
        reset_registry()

        registry1 = get_registry()
        registry2 = get_registry()

        assert registry1 is registry2

    def test_clear(self):
        """Test clearing the registry."""
        registry = ToolRegistry()
        registry.discover_builtin()

        assert len(registry) > 0

        registry.clear()
        assert len(registry) == 0
