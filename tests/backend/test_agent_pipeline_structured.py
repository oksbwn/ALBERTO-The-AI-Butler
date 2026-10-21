"""Tests for agent node pipeline features: task_prompt interpolation and structured output_key unpacking."""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from alberto.engine.compiler import compile_workflow
from alberto.services.runtime import make_runtime_ctx


@pytest.mark.asyncio
async def test_agent_task_prompt_and_structured_output_key():
    ctx = make_runtime_ctx("t_pipe", "p_pipe")
    ctx.checkpointer = InMemorySaver()

    triage_schema = {
        "title": "TriageResult",
        "type": "object",
        "properties": {
            "category": {"type": "string"},
            "urgency": {"type": "integer"},
            "action": {"type": "string"},
        },
        "required": ["category", "urgency", "action"],
    }

    workflow_def = {
        "id": "wf_pipeline",
        "version": 1,
        "state": {
            "messages": {"type": "list[message]", "reducer": "add_messages"},
            "ticket_id": {"type": "string"},
            "ticket_body": {"type": "string"},
            "triage": {"type": "object"},
            "routed_to": {"type": "string"},
        },
        "entry_node": "triage_agent",
        "nodes": [
            {
                "id": "triage_agent",
                "type": "agent",
                "config": {
                    "flavor": "agent",
                    "model": 'fake:{"category": "database", "urgency": 5, "action": "page_oncall"}',
                    "task_prompt": "Analyze ticket {{state.ticket_id}}: {{state.ticket_body}}",
                    "output_key": "triage",
                    "response_format": {
                        "mode": "structured",
                        "schema": triage_schema,
                    },
                },
            },
            {
                "id": "router",
                "type": "router",
                "config": {
                    "expression": "triage['urgency'] >= 4",
                    "cases": {
                        "true": "urgent_action",
                        "false": "normal_action",
                    },
                },
            },
            {
                "id": "urgent_action",
                "type": "transform",
                "config": {
                    "engine": "jmespath",
                    "expression": "'escalated_tier3'",
                    "output_key": "routed_to",
                },
            },
            {
                "id": "normal_action",
                "type": "transform",
                "config": {
                    "engine": "jmespath",
                    "expression": "'standard_queue'",
                    "output_key": "routed_to",
                },
            },
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [
            {"source": "triage_agent", "target": "router"},
            {"source": "urgent_action", "target": "end"},
            {"source": "normal_action", "target": "end"},
        ],
    }

    graph = compile_workflow(workflow_def, ctx)

    init_state = {
        "messages": [],
        "ticket_id": "INC-402",
        "ticket_body": "Database primary replica connection pool exhausted under heavy load.",
    }

    out = await graph.ainvoke(init_state, {"configurable": {"thread_id": "th_pipe_1"}})

    # 1. Verify structured data was unpacked directly into state['triage']
    assert "triage" in out
    triage = out["triage"]
    assert triage == {
        "category": "database",
        "urgency": 5,
        "action": "page_oncall",
    }

    # 2. Verify router branched on state.triage.urgency >= 4 and reached urgent_action
    assert out.get("routed_to") == "escalated_tier3"

    # 3. Verify messages contain the interpolated task_prompt
    human_msgs = [m for m in out["messages"] if isinstance(m, HumanMessage) or getattr(m, "type", None) == "human"]
    assert any("INC-402" in m.content and "exhausted" in m.content for m in human_msgs)


@pytest.mark.asyncio
async def test_bound_agent_preserves_task_prompt_and_structured_output_key():
    """When a node references a saved agent preset (`agent_ref`), it mirrors the preset
    persona/model/tools while preserving the pipeline step's task_prompt and output_key."""
    ctx = make_runtime_ctx("t_bound", "p_bound")
    ctx.checkpointer = InMemorySaver()
    ctx.agent_presets = {
        "sec_triage_preset": {
            "flavor": "agent",
            "model": 'fake:{"category": "security", "urgency": 5, "action": "block_ip"}',
            "system_prompt": "You are a Tier-3 Security Analyst.",
            "tools": [],
        }
    }

    schema = {
        "type": "object",
        "properties": {
            "category": {"type": "string"},
            "urgency": {"type": "integer"},
            "action": {"type": "string"},
        },
    }

    workflow_def = {
        "id": "wf_bound_pipeline",
        "version": 1,
        "state": {
            "messages": {"type": "list[message]", "reducer": "add_messages"},
            "incident": {"type": "string"},
            "verdict": {"type": "object"},
        },
        "entry_node": "agent_step",
        "nodes": [
            {
                "id": "agent_step",
                "type": "agent",
                "config": {
                    "agent_ref": "sec_triage_preset",
                    "task_prompt": "Investigate incident {{state.incident}}",
                    "output_key": "verdict",
                    "response_format": {"mode": "structured", "schema": schema},
                },
            },
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [{"source": "agent_step", "target": "end"}],
    }

    graph = compile_workflow(workflow_def, ctx)
    out = await graph.ainvoke(
        {"messages": [], "incident": "Brute-force SSH attack detected on bastion"},
        {"configurable": {"thread_id": "th_bound_1"}},
    )

    # Output unpacked into verdict state key
    assert out.get("verdict") == {"category": "security", "urgency": 5, "action": "block_ip"}
    # Task prompt rendered dynamically
    human_msgs = [m for m in out["messages"] if isinstance(m, HumanMessage) or getattr(m, "type", None) == "human"]
    assert any("Brute-force SSH attack" in m.content for m in human_msgs)
