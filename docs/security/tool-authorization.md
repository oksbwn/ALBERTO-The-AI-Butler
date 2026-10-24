# Tool Authorization & Execution Sandboxing

Alberto treats every tool call as an action crossing an untrusted boundary. Implemented across `tool_manager.py` and `tool_policy.py`, the authorization engine enforces strict least-privilege controls.

---

## 1. Tool Scoping & Association

By default, newly installed integrations and tools are assigned **zero permissions**. They cannot be invoked until an administrator explicitly binds them:

1. **Per-Agent Whitelist:** Agents can only call tools explicitly listed in their configuration `tools: [...]` array.
2. **Project Boundary:** Connectors and tools registered in Project A are inaccessible to agents in Project B.
3. **Role Checks:** Non-admin users cannot trigger tools configured with elevated privileges.

---

## 2. Destructive Action Gating & Human Approval

```mermaid
sequenceDiagram
    autonumber
    participant Agent as Specialist Agent
    participant Policy as Policy Gate (tool_policy.py)
    participant Checkpoint as SQLite Checkpointer
    participant User as Operator UI

    Agent->>Policy: execute("delete_server_instance", {instance_id: "i-098"})
    Policy->>Policy: Inspect danger_level == "destructive"
    Policy->>Checkpoint: Suspend graph and snapshot state
    Policy-->>User: Emits approval_required {run_id, tool, params}
    Note over User: Modal dialog displays action details
    alt User Approves
        User->>Policy: POST /v1/runs/{run_id}/approve {approved: true}
        Policy->>Policy: Generate one-time cryptographic approval token
        Policy->>Agent: Resume graph & execute tool
    else User Rejects
        User->>Policy: POST /v1/runs/{run_id}/approve {approved: false}
        Policy->>Agent: Resume graph with ToolRejectedException
    end
```

---

## 3. Subprocess & AST Code Sandboxing

For dynamic Python code evaluation (e.g. in Automate code nodes):
- Alberto utilizes `RestrictedPython 8.5` to compile and execute Python code.
- Dangerous builtins (`__import__`, `eval`, `exec`, `open`, `os`, `sys`) are stripped from the execution namespace.
- Memory usage and CPU cycles are bounded by subprocess watchdog timers.
