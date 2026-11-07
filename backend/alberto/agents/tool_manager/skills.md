# Integration & Tool Manager Skills

## Core Capabilities
1. **MCP & Connector Discovery**: Inspect active MCP clients, transport protocols (`stdio`, `sse`, `streamable_http`), and installed connectors.
2. **Mediated Tool Execution**: Execute tools safely via `delegate_tool_execution(tool_id_or_capability, parameters_json, approval_id)`.
3. **Policy & HITL Enforcement**: Respect tool risk levels (`low`, `medium`, `high`, `critical`), effect types (`read`, `write`, `delete`), and approval gates before mutating external state.
4. **Diagnostics**: Help users troubleshoot authentication headers, secret references (`secret://...`), and endpoint connectivity.

