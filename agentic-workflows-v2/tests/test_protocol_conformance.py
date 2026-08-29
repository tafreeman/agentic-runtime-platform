"""Protocol conformance tests — verify all runtime_checkable protocols.

Tests every concrete implementation against its structural protocol via
``isinstance``, following the TDD conformance pattern established in
``test_core_protocols.py``.

Covered protocols:
- Core: AgentProtocol, ToolProtocol, MemoryStoreProtocol (MemoryStore alias)

Each section has:
1. Positive tests — concrete implementations satisfy the protocol.
2. Negative tests — near-miss classes that are missing one required method
   or property do NOT satisfy the protocol.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# TestAgentProtocolConformance
# ---------------------------------------------------------------------------


class TestAgentProtocolConformance:
    """Verify AgentProtocol is satisfied by a minimal concrete subclass."""

    def test_minimal_agent_subclass_satisfies_agent_protocol(self):
        """A class with `name` property and async `run` satisfies AgentProtocol."""
        from agentic_v2.core.protocols import AgentProtocol

        class _MinimalAgent:
            @property
            def name(self) -> str:
                return "minimal-agent"

            async def run(self, input_data, ctx=None):
                return {"status": "ok"}

        assert isinstance(_MinimalAgent(), AgentProtocol)

    def test_agent_with_extra_methods_satisfies_agent_protocol(self):
        """Extra public methods must not break structural conformance."""
        from agentic_v2.core.protocols import AgentProtocol

        class _RichAgent:
            @property
            def name(self) -> str:
                return "rich-agent"

            async def run(self, input_data, ctx=None):
                return {}

            async def health_check(self) -> bool:
                return True

        assert isinstance(_RichAgent(), AgentProtocol)

    def test_agent_missing_name_fails(self):
        """An agent without `name` property must not satisfy AgentProtocol."""
        from agentic_v2.core.protocols import AgentProtocol

        class _NoName:
            async def run(self, input_data, ctx=None):
                return {}

        assert not isinstance(_NoName(), AgentProtocol)

    def test_agent_missing_run_fails(self):
        """An agent without `run` method must not satisfy AgentProtocol."""
        from agentic_v2.core.protocols import AgentProtocol

        class _NoRun:
            @property
            def name(self) -> str:
                return "no-run"

        assert not isinstance(_NoRun(), AgentProtocol)


# ---------------------------------------------------------------------------
# TestToolProtocolConformance
# ---------------------------------------------------------------------------


class TestToolProtocolConformance:
    """Verify ToolProtocol is satisfied by built-in tool classes."""

    def test_file_read_tool_satisfies_tool_protocol(self):
        from agentic_v2.core.protocols import ToolProtocol
        from agentic_v2.tools.builtin.file_ops import FileReadTool

        assert isinstance(FileReadTool(), ToolProtocol)

    def test_file_write_tool_satisfies_tool_protocol(self):
        from agentic_v2.core.protocols import ToolProtocol
        from agentic_v2.tools.builtin.file_ops import FileWriteTool

        assert isinstance(FileWriteTool(), ToolProtocol)

    def test_http_tool_satisfies_tool_protocol(self):
        from agentic_v2.core.protocols import ToolProtocol
        from agentic_v2.tools.builtin.http_ops import HttpTool

        assert isinstance(HttpTool(), ToolProtocol)

    def test_search_tool_satisfies_tool_protocol(self):
        from agentic_v2.core.protocols import ToolProtocol
        from agentic_v2.tools.builtin.search_ops import SearchTool

        assert isinstance(SearchTool(), ToolProtocol)

    def test_git_status_tool_satisfies_tool_protocol(self):
        from agentic_v2.core.protocols import ToolProtocol
        from agentic_v2.tools.builtin.git_ops import GitStatusTool

        assert isinstance(GitStatusTool(), ToolProtocol)

    def test_tool_missing_description_fails(self):
        from agentic_v2.core.protocols import ToolProtocol

        class _NoDescription:
            @property
            def name(self) -> str:
                return "no-desc"

            async def execute(self, **kwargs):
                return "done"

        assert not isinstance(_NoDescription(), ToolProtocol)

    def test_tool_missing_execute_fails(self):
        from agentic_v2.core.protocols import ToolProtocol

        class _NoExecute:
            @property
            def name(self) -> str:
                return "no-exec"

            @property
            def description(self) -> str:
                return "missing execute"

        assert not isinstance(_NoExecute(), ToolProtocol)


# ---------------------------------------------------------------------------
# TestMemoryStoreConformance
# ---------------------------------------------------------------------------


class TestMemoryStoreConformance:
    """Verify MemoryStoreProtocol conformance for InMemoryStore."""

    def test_in_memory_store_satisfies_memory_store_protocol(self):
        from agentic_v2.core.memory import InMemoryStore, MemoryStoreProtocol

        assert isinstance(InMemoryStore(), MemoryStoreProtocol)

    def test_in_memory_store_satisfies_memory_store_alias(self):
        """The MemoryStore alias exported from core.protocols must match."""
        from agentic_v2.core.memory import InMemoryStore
        from agentic_v2.core.protocols import MemoryStore

        assert isinstance(InMemoryStore(), MemoryStore)

    def test_memory_store_missing_list_keys_fails(self):
        from agentic_v2.core.memory import MemoryStoreProtocol

        class _Incomplete:
            async def store(self, key, value, *, metadata=None):
                pass

            async def retrieve(self, key):
                return None

            async def search(self, query, *, top_k=5):
                return []

            async def delete(self, key):
                return False

            # list_keys deliberately omitted

        assert not isinstance(_Incomplete(), MemoryStoreProtocol)

    def test_memory_store_missing_delete_fails(self):
        from agentic_v2.core.memory import MemoryStoreProtocol

        class _NoDelete:
            async def store(self, key, value, *, metadata=None):
                pass

            async def retrieve(self, key):
                return None

            async def search(self, query, *, top_k=5):
                return []

            async def list_keys(self, *, prefix=None):
                return []

            # delete deliberately omitted

        assert not isinstance(_NoDelete(), MemoryStoreProtocol)
