"""Verify AdapterRegistry state does not leak between tests."""
from __future__ import annotations

from agentic_v2.adapters.registry import get_registry


class _FakeEngine:
    async def execute(self, workflow, ctx=None, on_update=None, **kwargs):
        return None


def test_registry_isolation_first():
    """Register a fake adapter — should not be visible in the next test."""
    reg = get_registry()
    reg.register("_test_leak", _FakeEngine)
    assert "_test_leak" in reg.list_adapters()


def test_registry_isolation_second():
    """Previous test's adapter must not be present."""
    reg = get_registry()
    assert "_test_leak" not in reg.list_adapters(), (
        "Registry leaked state from a previous test — isolation fixture is missing"
    )
