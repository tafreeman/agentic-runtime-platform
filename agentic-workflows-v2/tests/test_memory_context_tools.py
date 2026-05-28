"""Tests for memory/context builtin tools."""

from __future__ import annotations

import json

import pytest
from agentic_v2.tools.builtin.context_ops import ContextTrimTool, TokenEstimateTool
from agentic_v2.tools.builtin.memory_ops import (
    MemoryClearTool,
    MemoryDeleteTool,
    MemoryGetTool,
    MemoryListTool,
    MemorySearchTool,
    MemoryUpsertTool,
)


@pytest.mark.asyncio
async def test_memory_tools_roundtrip(tmp_path, monkeypatch):
    mem_path = tmp_path / "mem.json"
    monkeypatch.setenv("AGENTIC_MEMORY_PATH", str(mem_path))

    upsert = MemoryUpsertTool()
    get = MemoryGetTool()
    list_tool = MemoryListTool()
    search = MemorySearchTool()
    delete = MemoryDeleteTool()
    clear = MemoryClearTool()

    r1 = await upsert.execute(key="a", value={"x": 1}, tags=["t1"])
    assert r1.success

    r2 = await get.execute(key="a")
    assert r2.success
    assert r2.data["found"] is True
    assert r2.data["entry"]["value"] == {"x": 1}
    assert r2.data["entry"]["tags"] == ["t1"]

    # Ensure persistence to disk.
    assert mem_path.exists()
    on_disk = json.loads(mem_path.read_text(encoding="utf-8"))
    assert "a" in on_disk

    r3 = await list_tool.execute(prefix="", limit=10)
    assert r3.success
    assert r3.data["count"] == 1
    assert r3.data["keys"] == ["a"]

    r4 = await search.execute(query="x", limit=10)
    assert r4.success
    assert r4.data["count"] >= 1
    assert any(hit["key"] == "a" for hit in r4.data["results"])

    r5 = await delete.execute(key="a")
    assert r5.success
    assert r5.data["deleted"] is True

    r6 = await get.execute(key="a")
    assert r6.success
    assert r6.data["found"] is False

    # Safety: clear requires confirm.
    r7 = await clear.execute(confirm=False)
    assert r7.success is False

    r8 = await clear.execute(confirm=True)
    assert r8.success


@pytest.mark.asyncio
async def test_context_trim_tool(tmp_path):
    tool = ContextTrimTool()

    text = "A" * 5000 + "TAIL"  # make tail unique
    res = await tool.execute(text=text, max_tokens=200, head_tokens=50, tail_tokens=50)
    assert res.success
    assert res.data["trimmed"] is True
    out = res.data["text"]

    assert out.startswith("A" * (50 * 4))
    assert out.endswith("TAIL")
    assert "truncated" in out.lower()


@pytest.mark.asyncio
async def test_token_estimate_tool():
    tool = TokenEstimateTool()
    res = await tool.execute(text="hello world")
    assert res.success
    assert res.data["tokens"] >= 1
    assert res.data["chars"] == len("hello world")
