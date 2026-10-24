# Visual Canvas Editor

Implemented in `frontend/components/screens/workflows.tsx` using `@xyflow/react` (React Flow 12.3), the **Automate Canvas** provides an interactive drag-and-drop workspace for building and editing workflows.

![Workflow Canvas](../assets/screenshots/automate/workflow-canvas.png){: .doc-screenshot }
<p class="doc-caption">Figure 8.2: Visual canvas editor showing node palette, canvas viewport, and property inspector.</p>

---

## 1. Canvas Layout & Controls

The canvas interface is divided into three primary zones:

1. **Left Node Palette:** Contains draggable node templates categorized by type:
    - *Triggers:* Webhook, Manual, Cron Schedule, Channel Inbound.
    - *Intelligence:* Specialist Agent, LLM Prompt, Evaluator.
    - *Tools & Integrations:* Tool Call, MCP Tool, REST Call.
    - *Logic & Control:* Condition / Branch, Switch, Merge, Delay.
    - *Data & Transform:* Template Render, JMESPath Transform, Code Snippet.
2. **Central Viewport:** Infinite canvas with panning, zooming, minimap, background grid, and multi-node selection.
3. **Right Properties Inspector (`ConfigForm.tsx`):** Contextual configuration panel reflecting the currently selected node or edge.

---

## 2. Connections & Data Flow

- **Handles:** Nodes have typed input handles (left) and output handles (right).
- **Edge Data Propagation:** Data flows along edges as structured JSON envelopes:
  ```json
  {
    "msg": "Incoming message",
    "payload": { "document_id": "doc_123", "score": 0.94 },
    "metadata": { "trigger_time": "2026-10-24T23:00:00Z" }
  }
  ```
- **Type Compatibility Checks:** The canvas warns if an incompatible output is wired into a node expecting strict structured data.

---

## 3. Graph Compilation to LangGraph

When you click **Publish**, `frontend/lib/graph.ts` compiles the visual layout into an executable LangGraph specification:

```typescript
export function canvasToExecutable(nodes: FlowNode[], edges: FlowEdge[], meta: any): ExecutableGraph {
  return {
    id: meta.id,
    nodes: nodes.map(compileNode),
    edges: edges.map(compileEdge),
    entry_point: findTriggerNodeId(nodes),
  };
}
```

The resulting executable definition is validated by the backend (`backend/alberto/services/validation.py`) to verify that all upstream variables resolve and no illegal cycles exist.
