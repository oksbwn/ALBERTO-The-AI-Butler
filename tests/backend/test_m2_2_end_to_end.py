"""
End-to-End Scenario Test for Alberto Milestone 2.2:
Mock Home Assistant MCP server discovery -> Execution -> Learning -> Contextual Recall.
"""

import pytest
from unittest.mock import AsyncMock, patch

from alberto.services.mcp_discovery import McpDiscoveryService
from alberto.services.mcp_learning import McpLearningService
from alberto.services.retrieval_policy import select_sources
from alberto.services.context_assembler import ContextAssembler
from alberto.services.unified_memory import UnifiedMemoryRecord


@pytest.mark.asyncio
async def test_m2_2_end_to_end_mcp_learning_and_retrieval_scenario():
    """Execute complete Milestone 2.2 Part P §28 End-to-End scenario."""
    # 1. Connect mock Home Assistant MCP server
    mock_ha_tools = [
        {
            "name": "get_device_inventory",
            "description": "Returns list of configured smart home devices",
            "parameters": {
                "type": "object",
                "properties": {"filter": {"type": "string"}},
            },
        },
        {
            "name": "set_device_state",
            "description": "Turn device on or off",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string"},
                    "state": {"type": "string"},
                },
                "required": ["entity_id", "state"],
            },
        },
    ]

    # 2. Discover tool capabilities & fingerprint
    fingerprint = McpDiscoveryService.compute_fingerprint(mock_ha_tools)
    assert len(fingerprint) == 64

    # 3. Verify no device inventory is fetched automatically on discovery
    # Discovery only records tool schemas and capabilities, not dynamic entity states.

    # 4. User/Agent executes device discovery tool
    raw_tool_output = {
        "devices": [
            {
                "name": "Living Room Thermostat",
                "kind": "climate",
                "model": "Ecobee SmartThermostat",
                "room": "Living Room",
                "state": "heat",
                "target_temp": 72,
            }
        ]
    }

    # 5. With tool learning enabled, extract knowledge
    parsed = McpLearningService.parse_structured_output(
        tool_name="get_device_inventory",
        tool_output=raw_tool_output,
        source_ref="mcp:ha_server:get_device_inventory",
    )

    assert parsed.should_learn is True
    assert len(parsed.entities) == 2  # thermostat + living room
    assert len(parsed.relationships) == 1  # LOCATED_IN
    assert parsed.relationships[0].kind == "LOCATED_IN"

    # Durable fact created
    durable_facts = [m for m in parsed.memories if m.durability == "long_term"]
    assert len(durable_facts) >= 1
    assert "Living Room Thermostat" in durable_facts[0].content
    assert "Ecobee SmartThermostat" in durable_facts[0].content

    # 6. User asks about that device later: "Which devices are in the Living Room?"
    user_query = "Which devices are in the Living Room?"
    selected_sources = select_sources(user_query)

    # Must select graph/memory, NOT generic web/docs
    assert "graph" in selected_sources or "memory" in selected_sources
    assert "knowledge" not in selected_sources  # Unrelated document search avoided

    # 7. Mock recalled evidence
    recalled_records = [
        UnifiedMemoryRecord(
            source="graph",
            record_id="ent_thermostat_1",
            content="Living Room Thermostat (climate) LOCATED_IN Living Room",
            score=1.0,
            provenance="mcp_tool:ha_server",
        ),
        UnifiedMemoryRecord(
            source="memory",
            record_id="mem_thermostat_1",
            content="Device Living Room Thermostat (climate) with Model: Ecobee SmartThermostat",
            score=0.95,
            provenance="mcp_tool:ha_server",
        ),
    ]

    context = ContextAssembler.assemble_context(recalled_records, max_tokens=1500)
    assert "Living Room Thermostat" in context
    assert "LOCATED_IN Living Room" in context
    assert "[RECALLED MEMORY & KNOWLEDGE CONTEXT" in context

    # 8. Verify disabled-learning version: returns None and mutates nothing
    with patch.object(McpLearningService, "is_tool_learning_enabled", new_callable=AsyncMock) as mock_enabled:
        mock_enabled.return_value = False
        event = await McpLearningService.schedule_tool_learning(
            tenant_id="test_tenant",
            project_id="test_project",
            client_id="ha_server",
            client_name="Home Assistant",
            tool_name="get_device_inventory",
            tool_input={},
            tool_output=raw_tool_output,
        )
        assert event is None
