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


@pytest.mark.asyncio
async def test_agent_default_json_output_envelope():
    """Every agent node must produce a valid JSON-compatible object in standard envelope:
    payload, msg.payload, and output, even when no schema is configured and LLM outputs plain text."""
    ctx = make_runtime_ctx("t_plain", "p_plain")
    ctx.checkpointer = InMemorySaver()

    workflow_def = {
        "id": "wf_plain_agent",
        "version": 1,
        "state": {
            "messages": {"type": "list[message]", "reducer": "add_messages"},
            "payload": {"type": "json", "reducer": "last_value"},
            "msg": {"type": "json", "reducer": "last_value"},
            "output": {"type": "json", "reducer": "last_value"},
        },
        "entry_node": "plain_agent",
        "nodes": [
            {
                "id": "plain_agent",
                "type": "agent",
                "config": {
                    "flavor": "agent",
                    "model": "fake:Server status is operational with latency 42ms.",
                },
            },
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [{"source": "plain_agent", "target": "end"}],
    }

    graph = compile_workflow(workflow_def, ctx)
    out = await graph.ainvoke(
        {"messages": [HumanMessage(content="Check server status")]},
        {"configurable": {"thread_id": "th_plain_1"}},
    )

    # 1. Output is valid JSON-compatible dict, not string
    assert isinstance(out.get("payload"), dict)
    assert out["payload"]["response"] == "Server status is operational with latency 42ms."
    assert out["payload"]["content"] == "Server status is operational with latency 42ms."

    # 2. msg.payload and output mirror payload
    assert isinstance(out.get("output"), dict)
    assert out["output"]["response"] == "Server status is operational with latency 42ms."
    assert out.get("msg") is not None
    assert out["msg"]["payload"]["response"] == "Server status is operational with latency 42ms."

    # 3. messages list still preserved for backward compatibility
    assert len(out.get("messages", [])) >= 2


@pytest.mark.asyncio
async def test_agent_schema_validation_failure_raises():
    """When agent response fails schema validation even after retries, raises ValueError."""
    ctx = make_runtime_ctx("t_fail", "p_fail")
    ctx.checkpointer = InMemorySaver()

    strict_schema = {
        "type": "object",
        "properties": {
            "expected_field": {"type": "string"},
        },
        "required": ["expected_field"],
    }

    workflow_def = {
        "id": "wf_schema_fail",
        "version": 1,
        "state": {
            "messages": {"type": "list[message]", "reducer": "add_messages"},
        },
        "entry_node": "bad_agent",
        "nodes": [
            {
                "id": "bad_agent",
                "type": "agent",
                "config": {
                    "flavor": "agent",
                    "model": 'fake:{"wrong_field": 123}',
                    "response_format": {"mode": "structured", "schema": strict_schema},
                },
            },
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [{"source": "bad_agent", "target": "end"}],
    }

    graph = compile_workflow(workflow_def, ctx)
    with pytest.raises(ValueError, match="failed schema validation"):
        await graph.ainvoke(
            {"messages": [HumanMessage(content="Produce data")]},
            {"configurable": {"thread_id": "th_fail_1"}},
        )


@pytest.mark.asyncio
async def test_agent_to_router_rules_nested_property():
    """Agent structured output with nested fields feeds directly into Router rules mode."""
    ctx = make_runtime_ctx("t_nested", "p_nested")
    ctx.checkpointer = InMemorySaver()

    nested_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "details": {
                "type": "object",
                "properties": {
                    "priority": {"type": "integer"},
                },
                "required": ["priority"],
            },
        },
        "required": ["title", "details"],
    }

    workflow_def = {
        "id": "wf_nested_router",
        "version": 1,
        "state": {
            "messages": {"type": "list[message]", "reducer": "add_messages"},
            "target_queue": {"type": "string"},
        },
        "entry_node": "eval_agent",
        "nodes": [
            {
                "id": "eval_agent",
                "type": "agent",
                "config": {
                    "flavor": "agent",
                    "model": 'fake:{"title": "Kernel panic", "details": {"priority": 5}}',
                    "response_format": {"mode": "structured", "schema": nested_schema},
                },
            },
            {
                "id": "priority_router",
                "type": "router",
                "config": {
                    "rules": [
                        {
                            "property": "details.priority",
                            "op": "gte",
                            "value": 4,
                            "target": "p0_queue",
                        },
                        {
                            "property": "details.priority",
                            "op": "lt",
                            "value": 4,
                            "target": "standard_queue",
                        },
                    ],
                },
            },
            {
                "id": "p0_queue",
                "type": "transform",
                "config": {
                    "engine": "jmespath",
                    "expression": "'P0-HIGH-SEVERITY'",
                    "output_key": "target_queue",
                },
            },
            {
                "id": "standard_queue",
                "type": "transform",
                "config": {
                    "engine": "jmespath",
                    "expression": "'STANDARD-SEVERITY'",
                    "output_key": "target_queue",
                },
            },
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [
            {"source": "eval_agent", "target": "priority_router"},
            {"source": "p0_queue", "target": "end"},
            {"source": "standard_queue", "target": "end"},
        ],
    }

    graph = compile_workflow(workflow_def, ctx)
    out = await graph.ainvoke(
        {"messages": [HumanMessage(content="Evaluate panic incident")]},
        {"configurable": {"thread_id": "th_nested_1"}},
    )

    assert out.get("target_queue") == "P0-HIGH-SEVERITY"
    assert out.get("payload") == {"title": "Kernel panic", "details": {"priority": 5}}

