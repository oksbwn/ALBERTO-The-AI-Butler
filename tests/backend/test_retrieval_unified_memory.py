"""Tests for Unified Memory integration inside the workflow retrieval node."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from alberto.engine.context import CompileContext
from alberto.nodes.rag import _KB_TAG, retrieval_factory
from alberto.services.unified_memory import UnifiedMemoryRecord


@pytest.mark.asyncio
async def test_retrieval_node_incorporates_unified_memory():
    ctx = CompileContext(tenant_id="t_um", project_id="p_um")
    cfg = {
        "include_memory": True,
        "include_graph": True,
        "include_docs": False,
        "include_qa": False,
        "route_key": "has_context",
    }
    node = retrieval_factory(cfg, ctx)

    fake_records = [
        UnifiedMemoryRecord(
            source="sqlite_memory",
            record_id="mem_1",
            content="User prefers dark mode and concise responses.",
            score=0.95,
            provenance="curator",
        ),
        UnifiedMemoryRecord(
            source="graph",
            record_id="ent_1",
            content="Project Alberto has component Automation Engine.",
            score=0.88,
            provenance="knowledge_graph",
        ),
    ]

    with patch("alberto.services.unified_memory.UnifiedMemoryManager.recall", new_callable=AsyncMock) as mock_recall:
        mock_recall.return_value = fake_records

        state = {"messages": [HumanMessage(content="What are my preferences and project components?")]}
        out = await node(state)

        assert out.get("has_context") == "yes"
        msgs = out.get("messages", [])
        sys_msgs = [m for m in msgs if isinstance(m, SystemMessage) and m.additional_kwargs.get(_KB_TAG)]
        assert len(sys_msgs) == 1
        content = sys_msgs[0].content
        assert "[Memory] User prefers dark mode and concise responses." in content
        assert "[Knowledge Graph] Project Alberto has component Automation Engine." in content

        # Check call arguments
        mock_recall.assert_awaited_once()
        _, kwargs = mock_recall.call_args
        assert kwargs["sources"] == ["memory", "graph"]


@pytest.mark.asyncio
async def test_retrieval_node_respects_unified_memory_toggles():
    ctx = CompileContext(tenant_id="t_um2", project_id="p_um2")
    cfg = {
        "include_memory": False,
        "include_graph": False,
        "include_docs": False,
        "include_qa": False,
        "announce_empty": True,
        "route_key": "found",
    }
    node = retrieval_factory(cfg, ctx)

    with patch("alberto.services.unified_memory.UnifiedMemoryManager.recall", new_callable=AsyncMock) as mock_recall:
        state = {"messages": [HumanMessage(content="Hello")]}
        out = await node(state)

        mock_recall.assert_not_called()
        assert out.get("found") == "no"
        sys_msgs = [m for m in out.get("messages", []) if isinstance(m, SystemMessage)]
        assert any("no relevant entries were found" in m.content for m in sys_msgs)
