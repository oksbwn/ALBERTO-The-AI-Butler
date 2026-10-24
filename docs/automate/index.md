# Automate: Visual Workflow Designer

**Automate** is Alberto's visual multi-agent workflow designer. It bridges intuitive visual graph design with industrial-grade deterministic execution, compiling interactive React Flow DAGs directly into LangGraph state machines.

![Workflows List](../assets/screenshots/automate/workflows-list.png){: .doc-screenshot }
<p class="doc-caption">Figure 8.1: Workflows dashboard displaying created workflow graphs, node counts, and run histories.</p>

---

## Architectural Philosophy

Traditional workflow engines (such as n8n or Zapier) are built for deterministic webhook ETL, but struggle with autonomous multi-agent branching and tool loops. Conversely, purely autonomous multi-agent frameworks often lack deterministic controls, predictable branching, and visual observability.

Automate combines both worlds:
1. **Deterministic Nodes:** Triggers, filters, code snippets, and template renderers execute with absolute predictability.
2. **Agentic Nodes:** Specialist agent nodes possess bounded autonomy, utilizing tool calling and semantic reasoning where appropriate.
3. **Durable Checkpoints:** Every node transition saves state to SQLite, allowing long-running tasks to survive crashes and wait indefinitely for human approval.

```mermaid
graph LR
    Trigger[Trigger: Cron / Webhook / Chat] --> CheckCondition{Condition: JMESPath}
    CheckCondition -->|Rule A| SpecialistA[Agent: Code Reviewer]
    CheckCondition -->|Rule B| ToolNode[Tool: Execute Script]
    SpecialistA --> JoinNode[Synthesize Report]
    ToolNode --> JoinNode
    JoinNode --> Output[Delivery: Telegram / Email]
```

---

## In This Section

- [Visual Canvas](canvas.md) — The React Flow canvas editor, node palette, handles, and inspector panel.
- [Node Types & Flow Control](node-types.md) — Exhaustive guide to Triggers, Conditions, Agents, Tools, and Formatting steps.
- [Execution & Dry Runs](execution.md) — Running workflows, inspecting step outputs, and pausing for human approval.
- [Real-World Workflow Examples](examples.md) — Complete walkthroughs of production workflow graphs.
