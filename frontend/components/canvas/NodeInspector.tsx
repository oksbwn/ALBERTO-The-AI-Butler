"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { Icon } from "../icons";
import { StatusPill, Tile, Field, Toggle } from "../primitives";
import { FieldsForm, ModelSelect, MultiSelectChips, VariablePicker, type FieldSpec, type UpstreamSource } from "./ConfigForm";
import { AgentConfig } from "./AgentConfig";
import { api, Agent, McpClientT, NodeType, Tool, ToolSet, Workflow, type ComponentT } from "@/lib/api";
import { NODE_META, NODE_HELP, IO_COLOR } from "@/lib/data";
import { type FlowEdge, type FlowNode } from "@/lib/graph";

function extractSchemaKeys(schema: any, prefix = ""): string[] {
  if (!schema) return [];
  let obj = schema;
  if (typeof obj === "string") {
    try {
      obj = JSON.parse(obj);
    } catch {
      return [];
    }
  }
  if (!obj || typeof obj !== "object") return [];
  const props = obj.properties;
  if (!props || typeof props !== "object") return [];
  const keys: string[] = [];
  for (const [key, val] of Object.entries(props)) {
    const fullKey = prefix ? `${prefix}.${key}` : key;
    keys.push(fullKey);
    if (val && typeof val === "object" && (val as any).type === "object" && (val as any).properties) {
      keys.push(...extractSchemaKeys(val, fullKey));
    }
  }
  return keys;
}

function getUpstreamOutputs(selectedId: string | null, nodes: FlowNode[], edges: FlowEdge[]): UpstreamSource[] {
  if (!selectedId) return [];
  const inMap: Record<string, string[]> = {};
  for (const e of edges) {
    if (!inMap[e.target]) inMap[e.target] = [];
    inMap[e.target].push(e.source);
  }
  const visited = new Set<string>();
  const queue = [...(inMap[selectedId] || [])];
  const upstreamNodeIds: string[] = [];
  while (queue.length > 0) {
    const cur = queue.shift()!;
    if (visited.has(cur)) continue;
    visited.add(cur);
    upstreamNodeIds.push(cur);
    if (inMap[cur]) queue.push(...inMap[cur]);
  }

  const byId = new Map(nodes.map((n) => [n.id, n]));
  const sources: UpstreamSource[] = [
    {
      nodeId: "flow",
      nodeName: "Flow State",
      keys: ["msg", "payload", "topic", "metadata", "messages"],
    },
  ];

  for (const id of upstreamNodeIds) {
    const n = byId.get(id);
    if (!n) continue;
    const t = n.data.nodeType;
    const cfg = n.data.config || {};
    const keys: string[] = [];
    if (t === "inject") {
      keys.push("payload", "topic", "msg", "metadata");
    } else if (t === "transform") {
      keys.push(cfg.output_key || "payload", "msg");
    } else if (t === "classifier") {
      keys.push(cfg.output_key || "intent");
    } else if (t === "tool_call") {
      keys.push(cfg.output_key || "result", "payload");
    } else if (t === "llm") {
      keys.push(cfg.output_key || "result", "messages");
    } else if (t === "agent" || t === "deep_agent") {
      keys.push("payload", "output", "msg", "response", "content", "messages", "tool_calls");
      if (cfg.output_key) {
        keys.push(cfg.output_key);
      }
      const schema =
        cfg.response_format?.schema ||
        cfg.response_format?.json_schema?.schema ||
        cfg.output_schema ||
        cfg.structured_output;
      if (schema) {
        const schemaKeys = extractSchemaKeys(schema);
        for (const sk of schemaKeys) {
          keys.push(sk);
          keys.push(`payload.${sk}`);
        }
      }
    } else if (t === "human_input") {
      keys.push(cfg.output_key || "decision");
    } else if (t === "webhook_in") {
      keys.push("payload", "body", "headers");
    } else if (t === "parallel_fanout") {
      keys.push(cfg.item_key || "item");
    } else if (t === "join") {
      keys.push(cfg.output_key || "results", "items");
    } else {
      keys.push("payload", "output");
    }
    sources.push({
      nodeId: n.id,
      nodeName: cfg.name || n.id,
      nodeType: t,
      keys: Array.from(new Set(keys)),
    });
  }

  return sources;
}

function TransformForm({
  c,
  set,
  upstreamSources,
}: {
  c: Record<string, any>;
  set: (p: Record<string, any>) => void;
  upstreamSources?: UpstreamSource[];
}) {
  const [mode, setMode] = useState<"simple" | "advanced">(c.operations ? "simple" : "advanced");
  const ops: Array<{ type: string; target: string; value?: any; from?: string; to?: string }> = Array.isArray(c.operations) ? c.operations : [];

  const addOp = () => {
    const next = [...ops, { type: "set", target: "payload.status", value: "active" }];
    set({ operations: next });
  };

  const updateOp = (idx: number, patch: Partial<(typeof ops)[0]>) => {
    const next = ops.map((op, i) => (i === idx ? { ...op, ...patch } : op));
    set({ operations: next });
  };

  const removeOp = (idx: number) => {
    const next = ops.filter((_, i) => i !== idx);
    set({ operations: next });
  };

  return (
    <div className="col gap3">
      <div className="row spread" style={{ borderBottom: "1px solid var(--line)", paddingBottom: 6 }}>
        <span className="t-micro">Transform Mode</span>
        <div className="row gap1">
          <button
            type="button"
            className="chip"
            style={{
              cursor: "pointer",
              background: mode === "simple" ? "var(--accent)" : "var(--bg-3)",
              color: mode === "simple" ? "var(--fg-on-accent)" : "var(--fg-1)",
              borderColor: mode === "simple" ? "var(--accent)" : "var(--line)",
            }}
            onClick={() => {
              setMode("simple");
              if (!c.operations) {
                set({ operations: [{ type: "set", target: "payload.status", value: "active" }] });
              }
            }}
          >
            Simple (Rules)
          </button>
          <button
            type="button"
            className="chip"
            style={{
              cursor: "pointer",
              background: mode === "advanced" ? "var(--accent)" : "var(--bg-3)",
              color: mode === "advanced" ? "var(--fg-on-accent)" : "var(--fg-1)",
              borderColor: mode === "advanced" ? "var(--accent)" : "var(--line)",
            }}
            onClick={() => setMode("advanced")}
          >
            Advanced (JMESPath)
          </button>
        </div>
      </div>

      {mode === "simple" ? (
        <div className="col gap2">
          <div className="row spread">
            <span className="t-body-sm fg-2">Operations</span>
            <button type="button" className="btn btn-xs btn-secondary" onClick={addOp}>
              <Icon name="plus" size={12} /> Add Operation
            </button>
          </div>
          {ops.length === 0 ? (
            <div className="field-help">No operations defined. Click "Add Operation" to configure field rules.</div>
          ) : (
            <div className="col gap2">
              {ops.map((op, i) => (
                <div key={i} className="card col gap1" style={{ padding: 8, background: "var(--bg-3)", border: "1px solid var(--line)" }}>
                  <div className="row spread">
                    <select
                      className="select"
                      style={{ height: 26, fontSize: 11, width: 100 }}
                      value={op.type}
                      onChange={(e) => updateOp(i, { type: e.target.value })}
                    >
                      <option value="set">Set</option>
                      <option value="change">Change</option>
                      <option value="move">Move</option>
                      <option value="rename">Rename</option>
                      <option value="delete">Delete</option>
                    </select>
                    <button type="button" className="iconbtn" style={{ width: 20, height: 20 }} onClick={() => removeOp(i)}>
                      <Icon name="trash" size={12} />
                    </button>
                  </div>
                  <div className="row gap1" style={{ alignItems: "center" }}>
                    <input
                      className="input mono"
                      style={{ height: 26, fontSize: 11, flex: 1 }}
                      placeholder="property (e.g. payload.item)"
                      value={op.target || ""}
                      onChange={(e) => updateOp(i, { target: e.target.value })}
                    />
                    <VariablePicker
                      sources={upstreamSources}
                      onSelect={(path) => updateOp(i, { target: path })}
                    />
                  </div>
                  {op.type !== "delete" && (
                    <div className="row gap1" style={{ alignItems: "center" }}>
                      <span className="fg-2 mono-sm" style={{ fontSize: 10, width: 36 }}>to:</span>
                      <input
                        className="input mono"
                        style={{ height: 26, fontSize: 11, flex: 1 }}
                        placeholder={op.type === "rename" || op.type === "move" ? "new property name" : "value or expression"}
                        value={op.value !== undefined ? String(op.value) : (op.to || "")}
                        onChange={(e) => {
                          if (op.type === "rename" || op.type === "move") {
                            updateOp(i, { to: e.target.value });
                          } else {
                            updateOp(i, { value: e.target.value });
                          }
                        }}
                      />
                      <VariablePicker
                        sources={upstreamSources}
                        onSelect={(path) => {
                          if (op.type === "rename" || op.type === "move") {
                            updateOp(i, { to: path });
                          } else {
                            updateOp(i, { value: `{{${path}}}` });
                          }
                        }}
                      />
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <FieldsForm specs={NODE_FIELDS.transform} config={c} onPatch={set} upstreamSources={upstreamSources} />
      )}
    </div>
  );
}

export function NodeInspector({
  node,
  nodes,
  edges,
  tools,
  toolSets,
  agents,
  mcpServers,
  components,
  dynamic,
  onChange,
  onRename,
  onDelete,
  onRouterCaseTarget,
  onRouterCaseRename,
  onRouterCaseRemove,
}: {
  node: FlowNode;
  nodes: FlowNode[];
  edges: FlowEdge[];
  tools: Tool[];
  toolSets: ToolSet[];
  agents: Agent[];
  mcpServers: McpClientT[];
  components: ComponentT[];
  dynamic?: Record<string, string[]>;
  onChange: (c: Record<string, any>) => void;
  onRename: (nodeId: string, name: string) => void;
  onDelete: (id: string) => void;
  onRouterCaseTarget: (nodeId: string, key: string, target: string) => void;
  onRouterCaseRename: (nodeId: string, oldKey: string, newKey: string) => void;
  onRouterCaseRemove: (nodeId: string, key: string) => void;
}) {
  const type = node.data.nodeType;
  const c = node.data.config || {};
  const set = (patch: Record<string, any>) => onChange({ ...c, ...patch });
  const meta = NODE_META[type] || { label: type, color: "var(--fg-2)", icon: "n_agent" };
  const nodeIds = nodes.map((n) => n.id).filter((id) => id !== node.id);
  const upstreamSources = useMemo(() => getUpstreamOutputs(node.id, nodes, edges), [node.id, nodes, edges]);

  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="row spread">
        <div className="row gap2" style={{ minWidth: 0 }}>
          <Tile icon={meta.icon} color={meta.color} size={28} />
          <div style={{ minWidth: 0 }}>
            <div className="t-h2 truncate">{meta.label}</div>
            <EditableName value={node.id} fallback={node.id} className="mono-sm fg-2 truncate" inputClassName="input mono" inputStyle={{ height: 26, maxWidth: 190 }} onCommit={(name) => onRename(node.id, name)} />
          </div>
        </div>
        <button className="btn btn-danger btn-sm" onClick={() => onDelete(node.id)}><Icon name="trash" size={14} />Delete</button>
      </div>

      {(type === "agent" || type === "deep_agent") && <AgentConfig config={c} onChange={onChange} tools={tools} toolSets={toolSets} agents={agents} mcpServers={mcpServers} components={components} folders={dynamic?.kb_folders || []} kinds={dynamic?.qa_kinds || []} upstreamSources={upstreamSources} />}

      {type === "retrieval" && <RetrievalForm c={c} set={set} folders={dynamic?.kb_folders || []} kinds={dynamic?.qa_kinds || []} />}

      {(type === "router" || type === "switch") && (
        <RouterForm
          nodeId={node.id}
          c={c}
          set={set}
          nodeIds={nodeIds}
          nodes={nodes}
          upstreamSources={upstreamSources}
          onCaseTarget={onRouterCaseTarget}
          onCaseRename={onRouterCaseRename}
          onCaseRemove={onRouterCaseRemove}
        />
      )}

      {type === "llm" && (
        <div className="col gap3">
          <Field label="Model"><ModelSelect value={c.model || ""} onChange={(v) => set({ model: v })} /></Field>
          <Field label="Prompt" help="The instruction the model runs on the incoming message."><textarea className="textarea" rows={4} value={c.prompt || ""} onChange={(e) => set({ prompt: e.target.value })} /></Field>
        </div>
      )}

      {type === "tool_call" && (
        <div className="col gap3">
          <Field label="Tool" help={tools.length ? "Which project tool to invoke." : "No tools in this project yet - add them on the Tools or Connectors screen."}>
            <ToolPicker tools={tools} toolSets={toolSets} value={c.tool_id || ""} onChange={(v) => set({ tool_id: v || undefined })} />
          </Field>
          <Field label="Output state key" help="Where the tool's result is written in state."><input className="input mono" value={c.output_key ?? ""} placeholder="result" onChange={(e) => set({ output_key: e.target.value || undefined })} /></Field>
        </div>
      )}

      {type === "transform" || type === "change" ? (
        <TransformForm c={c} set={set} upstreamSources={upstreamSources} />
      ) : NODE_FIELDS[type] ? (
        <FieldsForm specs={NODE_FIELDS[type]} config={c} onPatch={set} dynamic={dynamic} upstreamSources={upstreamSources} />
      ) : null}

      {(type === "start" || type === "end") && <div className="fg-2 t-body-sm">No configuration for this node.</div>}

      {!FORM_NODES.has(type) && (
        <>
          <div className="field-label">Config (JSON)</div>
          <textarea className="textarea mono" rows={8} style={{ fontSize: 12 }} defaultValue={JSON.stringify(c, null, 2)}
            onChange={(e) => { try { onChange(JSON.parse(e.target.value || "{}")); } catch { /* keep */ } }} />
        </>
      )}
    </div>
  );
}

/* Tool picker for the Tool Call node, grouped by tool set.

   Every installed connector owns a tool set, so its actions arrive here as their own group
   ("Slack", "Gmail", …) rather than being scattered through one flat alphabetical list of every
   tool in the project. With a couple of connectors installed that flat list runs to dozens of
   entries and picking the right one becomes guesswork; the group label is the only context that
   tells you which system an action actually talks to. A search box filters across both the tool
   name and its group, so typing "slack" finds the actions even when their names don't say so. */
function ToolPicker({ tools, toolSets, value, onChange }: {
  tools: Tool[]; toolSets: ToolSet[]; value: string; onChange: (v: string) => void;
}) {
  const [q, setQ] = useState("");
  const byId = useMemo(() => new Map(tools.map((t) => [t.id, t])), [tools]);

  // Group by tool set, preserving set order; anything in no set falls into "Other tools".
  // A tool in several sets is listed under each (membership is labels, not folders).
  const groups = useMemo(() => {
    const out: { label: string; icon?: string | null; tools: Tool[] }[] = [];
    const grouped = new Set<string>();
    for (const ts of toolSets) {
      const members = (ts.tool_ids || []).map((id) => byId.get(id)).filter(Boolean) as Tool[];
      if (!members.length) continue;
      members.forEach((t) => grouped.add(t.id));
      out.push({ label: ts.name, icon: ts.icon, tools: members });
    }
    const loose = tools.filter((t) => !grouped.has(t.id));
    if (loose.length) out.push({ label: "Other tools", tools: loose });
    return out;
  }, [tools, toolSets, byId]);

  const needle = q.trim().toLowerCase();
  const filtered = needle
    ? groups
        .map((g) => ({ ...g, tools: g.tools.filter((t) => (t.name + " " + g.label).toLowerCase().includes(needle)) }))
        .filter((g) => g.tools.length)
    : groups;

  const selected = value ? byId.get(value) : undefined;
  const selectedGroup = value ? groups.find((g) => g.tools.some((t) => t.id === value)) : undefined;

  return (
    <div className="col" style={{ gap: 6 }}>
      {tools.length > 8 && (
        <input className="input" style={{ height: 28, fontSize: 12 }} value={q} placeholder="Filter tools…"
          onChange={(e) => setQ(e.target.value)} />
      )}
      <select className="select" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Select a tool…</option>
        {/* Keep the current selection selectable even when the filter hides it, or typing in
            the filter box would silently blank the node's configured tool. */}
        {selected && needle && !filtered.some((g) => g.tools.some((t) => t.id === selected.id)) && (
          <option value={selected.id}>{selected.name} · current</option>
        )}
        {filtered.map((g) => (
          <optgroup key={g.label} label={g.label}>
            {g.tools.map((t) => <option key={g.label + t.id} value={t.id}>{t.name} · {t.kind}</option>)}
          </optgroup>
        ))}
      </select>
      {selectedGroup && (
        <div className="row gap2" style={{ fontSize: 11.5, color: "var(--fg-2)" }}>
          <Icon name={selectedGroup.icon || "tools"} size={12} />
          <span>from <strong style={{ color: "var(--fg-1)" }}>{selectedGroup.label}</strong></span>
        </div>
      )}
      {selected && !selected.enabled && (
        <div className="row gap1" style={{ fontSize: 11.5, color: "#ef4444", marginTop: 2 }}>
          <Icon name="alert" size={12} />
          <span>This tool is disabled or inactive. Enable it in Integrations to execute.</span>
        </div>
      )}
      {selected && selected.enabled && Boolean((selected as any).config?.requires_approval) && (
        <div className="row gap1" style={{ fontSize: 11.5, color: "#f59e0b", marginTop: 2 }}>
          <Icon name="shield" size={12} />
          <span>Execution requires human-in-the-loop approval.</span>
        </div>
      )}
    </div>
  );
}

/* Declarative field specs → friendly form widgets (no raw JSON for common nodes). The form
   merges only its own keys, so any extra config is preserved. Mirrors the node config schemas.
   (Widgets + FieldSpec live in canvas/ConfigForm.tsx, shared with the middleware stack.) */
const NODE_FIELDS: Record<string, FieldSpec[]> = {
  transform: [
    { key: "input_key", label: "Input state key", widget: "text", placeholder: "messages", help: "Which state field to read." },
    { key: "output_key", label: "Output state key", widget: "text", placeholder: "result", help: "Which state field to write." },
    { key: "expression", label: "Expression", widget: "textarea", help: "Sandboxed expression over state (e.g. len(messages))." },
  ],
  classifier: [
    { key: "labels", label: "Intent labels", widget: "csv", placeholder: "return_item, cancel_subscription, get_information", help: "Wire a Router after this with one case per label." },
    { key: "output_key", label: "Write label to state key", widget: "text", placeholder: "intent", help: "The Router's expression should read this key." },
    { key: "multi_label", label: "Multi-label (all that apply)", widget: "toggle", help: "Write EVERY applicable label (a list) instead of exactly one. Pair with a Router set to 'Route to every match' so a question with several intents reaches several specialists in parallel." },
    { key: "model", label: "Model", widget: "model", emptyLabel: "Auto (cheapest model)", help: "Left on Auto, the classifier uses your provider's cheapest model (e.g. gpt-4.1-nano) — not the project default — since classification is high-volume and low-stakes. Pick a model to override." },
    { key: "instructions", label: "Extra guidance (optional)", widget: "textarea", placeholder: "Domain hints, tie-breaking rules…" },
  ],
  human_input: [
    { key: "prompt", label: "Prompt to reviewer", widget: "textarea", help: "Shown when the run pauses for approval." },
    { key: "allowed_decisions", label: "Allowed decisions", widget: "csv", placeholder: "approve, reject", help: "The buttons the reviewer sees in the Playground." },
    { key: "output_key", label: "Write decision to state key", widget: "text", placeholder: "decision", help: "Optional: use a key name like decision. The selected value is written there so a Router can branch approve vs reject." },
  ],
  emit_event: [
    { key: "event", label: "Event name", widget: "text", placeholder: "order.created" },
  ],
  webhook_out: [
    { key: "url", label: "Webhook URL", widget: "text", placeholder: "https://…" },
    { key: "method", label: "Method", widget: "select", options: ["POST", "PUT", "PATCH", "GET"].map((m) => ({ value: m, label: m })) },
  ],
  handoff: [
    { key: "reason", label: "Reason", widget: "text", placeholder: "Escalated to a human agent.", help: "Why the conversation is handed off (shown in the agent inbox)." },
    { key: "ack_message", label: "Hold message (optional)", widget: "textarea", placeholder: "A team member will follow up shortly.", help: "Sent to the customer while they wait for a human." },
  ],
  // --- flow ---
  loop: [
    { key: "max_iter", label: "Max iterations", widget: "number", min: 1, step: 1, help: "Safety cap on how many times the body runs." },
    { key: "condition", label: "Continue while (expression)", widget: "textarea", placeholder: "keep_going == True", help: "Sandboxed expression over state; loops while truthy. Writes _loop = continue/done - wire a Router on _loop and point its body back to this node." },
  ],
  parallel_fanout: [
    { key: "over", label: "List state key", widget: "text", placeholder: "items", help: "State field holding the list to map over." },
    { key: "child_node", label: "Child node id", widget: "text", placeholder: "worker", help: "The node run once per item, in parallel (Send)." },
    { key: "item_key", label: "Item state key", widget: "text", placeholder: "item", help: "Each item is written here for the child to read." },
  ],
  join: [
    { key: "reducer", label: "Combine results", widget: "select", options: ["concat", "merge", "first", "last"].map((m) => ({ value: m, label: m })), help: "How parallel branches converge. Children should write to an add-reducer state key to aggregate." },
  ],
  subworkflow: [
    { key: "workflow_id", label: "Workflow (id or name)", widget: "text", placeholder: "Verify identity", help: "Another workflow in THIS project, run as a reusable component (shares messages state)." },
  ],
  // --- triggers ---
  webhook_in: [
    { key: "message_path", label: "Message JMESPath (optional)", widget: "text", placeholder: "text", help: "Path into the POSTed JSON body used as the message (empty = the whole body). The webhook URL appears on the Triggers screen after you publish." },
    { key: "require_signature", label: "Require HMAC signature", widget: "toggle", help: "Verify the X-Alberto-Signature or X-Forge-Signature (sha256) header using the secret below." },
    { key: "secret_ref", label: "Signing secret ref", widget: "text", placeholder: "secret://proj/webhook_secret", help: "Secret used to verify the signature." },
  ],
  schedule: [
    { key: "every_minutes", label: "Every N minutes", widget: "number", min: 1, step: 1, help: "Run on a fixed interval. Use this OR cron." },
    { key: "cron", label: "Cron expression (optional)", widget: "text", placeholder: "0 9 * * 1-5", help: "Standard cron (needs the workers extra). Overrides the interval if set." },
    { key: "message", label: "Message", widget: "textarea", placeholder: "Summarize today's tickets.", help: "The input sent into the workflow on each run." },
  ],
  email_in: [
    { key: "mailbox", label: "Mailbox", widget: "text", placeholder: "support@yourco.com", help: "The address this trigger handles. Connect an Email channel (Connect screen) to receive mail." },
    { key: "include_subject", label: "Include subject", widget: "toggle", help: "Prepend the email subject to the message." },
    { key: "reply", label: "Reply to sender", widget: "toggle", help: "Send the workflow's answer back as a threaded email." },
  ],
  app_event: [
    { key: "poll_url", label: "Poll URL", widget: "text", placeholder: "https://api.example.com/events", help: "Polled on each interval; new items fire the workflow." },
    { key: "method", label: "Method", widget: "select", options: ["GET", "POST"].map((m) => ({ value: m, label: m })) },
    { key: "interval_minutes", label: "Poll every N minutes", widget: "number", min: 1, step: 1 },
    { key: "items_path", label: "Items JMESPath", widget: "text", placeholder: "data.items", help: "Path to the list of items in the response (empty = the whole body)." },
    { key: "dedupe_key", label: "Dedupe key JMESPath", widget: "text", placeholder: "id", help: "Unique id within each item so it fires only once." },
    { key: "message_path", label: "Message JMESPath (optional)", widget: "text", placeholder: "title", help: "Path within an item for the message text (empty = the whole item)." },
  ],
  inject: [
    { key: "topic", label: "Topic (msg.topic)", widget: "text", placeholder: "home.status", help: "Topic identifier for message routing." },
    { key: "payload_type", label: "Payload type", widget: "select", options: [
      { value: "json", label: "JSON Object" },
      { value: "string", label: "String" },
      { value: "number", label: "Number" },
      { value: "boolean", label: "Boolean" },
      { value: "timestamp", label: "Current Timestamp" },
    ]},
    { key: "payload", label: "Payload (msg.payload)", widget: "textarea", placeholder: "{\n  \"status\": \"active\"\n}", help: "Message payload content injected into workflow." },
    { key: "repeat", label: "Repeat interval (seconds, 0=manual)", widget: "number", min: 0, step: 1 },
  ],
  debug: [
    { key: "target", label: "Inspect property", widget: "select", options: [
      { value: "payload", label: "msg.payload" },
      { value: "msg", label: "Complete msg object" },
      { value: "topic", label: "msg.topic" },
      { value: "messages", label: "messages (chat history)" },
    ], help: "Which state property to inspect and print in the debug sidebar." },
    { key: "active", label: "Debug active", widget: "toggle", help: "Mute debug output without disconnecting the node." },
  ],
  delay: [
    { key: "seconds", label: "Delay duration", widget: "number", min: 0.1, step: 0.5 },
    { key: "unit", label: "Unit", widget: "select", options: [
      { value: "seconds", label: "Seconds" },
      { value: "minutes", label: "Minutes" },
      { value: "hours", label: "Hours" },
    ]},
  ],
};
// Node types that render a real form (agent/router/llm/tool_call have bespoke forms; the rest come from NODE_FIELDS).
const FORM_NODES = new Set<string>(["agent", "deep_agent", "router", "switch", "llm", "tool_call", "retrieval", "start", "end", "transform", "change", "inject", "debug", "delay", ...Object.keys(NODE_FIELDS)]);

/** State keys written by upstream-capable nodes, with the values they can take -
 *  shown in the router form so users branch on real values, not made-up labels. */
function stateWriters(nodes: FlowNode[]): { key: string; values: string[]; from: string }[] {
  const out: { key: string; values: string[]; from: string }[] = [];
  const valuesOf = (value: any, fallback: string[] = []) => (
    Array.isArray(value)
      ? value
      : typeof value === "string"
        ? value.split(",")
        : fallback
  ).map((v) => String(v).trim()).filter(Boolean);
  for (const n of nodes) {
    const cfg = n.data.config || {};
    const t = n.data.nodeType;
    if (t === "classifier") out.push({ key: cfg.output_key || "intent", values: valuesOf(cfg.labels), from: n.id });
    if (t === "retrieval" && cfg.route_key) out.push({ key: cfg.route_key, values: ["yes", "no"], from: n.id });
    if (t === "human_input" && cfg.output_key) out.push({ key: cfg.output_key, values: valuesOf(cfg.allowed_decisions, ["approve", "reject"]), from: n.id });
  }
  return out;
}

/* Retrieval node config - toggleable Knowledge (RAG over documents) + FAQs / Q&A sections,
   mirroring the agent panel's Knowledge sections (AgentConfig). Document search (include_docs)
   and Q&A lookup (include_qa) are independent: use either or both. The flat retrieval config is
   read/written directly. */
function RetrievalForm({ c, set, folders, kinds }: { c: Record<string, any>; set: (p: Record<string, any>) => void; folders: string[]; kinds: string[] }) {
  const ragOn = c.include_docs !== false; // RAG on unless explicitly turned off
  const qaOn = !!c.include_qa;
  const memoryOn = c.include_memory !== false;
  const graphOn = c.include_graph !== false;
  return (
    <div className="col" style={{ gap: 18 }}>
      <CollapsibleSection label="Unified Memory" badge={memoryOn || graphOn ? "active" : undefined}
        hint="Automatically ground workflow steps with curated facts from Memory Curator and entity relations from Knowledge Graph.">
        <div className="col gap2">
          <label className="row gap2" style={{ cursor: "pointer" }}>
            <Toggle on={memoryOn} onChange={(on) => set({ include_memory: on })} />
            <span className="t-body-sm">Include Curated Memories (Facts &amp; Preferences)</span>
          </label>
          <label className="row gap2" style={{ cursor: "pointer" }}>
            <Toggle on={graphOn} onChange={(on) => set({ include_graph: on })} />
            <span className="t-body-sm">Include Knowledge Graph (Entities &amp; Relations)</span>
          </label>
        </div>
      </CollapsibleSection>

      <CollapsibleSection label="Knowledge" badge={ragOn ? "enabled" : undefined}
        hint="Pull the most relevant document chunks from your knowledge base into context for a grounded agent.">
        <div className="col gap2">
          <label className="row gap2" style={{ cursor: "pointer" }}>
            <Toggle on={ragOn} onChange={(on) => set({ include_docs: on })} />
            <span className="t-body-sm">Search knowledge base (RAG over documents)</span>
          </label>
          {ragOn && (
            <div className="col gap2" style={{ paddingLeft: 6 }}>
              <Field label="Folders" help="Limit document search to these folders (none selected = all).">
                <MultiSelectChips value={c.folders || []} options={folders} onChange={(items) => set({ folders: items })} />
              </Field>
              <div className="row gap3 wrap">
                <Field label="Documents (top K)" help="Chunks returned per search.">
                  <input className="input" type="number" min={1} max={20} step={1} style={{ width: 92 }}
                    value={c.top_k ?? 5} onChange={(e) => set({ top_k: Number(e.target.value) || 1 })} />
                </Field>
                <Field label="Min score" help="Drop chunks below this similarity (0–1).">
                  <input className="input" type="number" min={0} max={1} step={0.02} style={{ width: 92 }}
                    value={c.min_score ?? 0.18} onChange={(e) => set({ min_score: Number(e.target.value) })} />
                </Field>
              </div>
              <label className="row gap2" style={{ cursor: "pointer" }}>
                <Toggle on={!!c.hybrid} onChange={(on) => set({ hybrid: on })} />
                <span className="t-body-sm">Hybrid search (BM25 + vector)</span>
              </label>
              <div className="field-help">Blend lexical keyword (BM25) ranking with semantic vectors so exact terms - codes, names, SKUs - aren’t missed.</div>
              <label className="row gap2" style={{ cursor: "pointer" }}>
                <Toggle on={!!c.rerank} onChange={(on) => set({ rerank: on })} />
                <span className="t-body-sm">Rerank (cross-encoder)</span>
              </label>
              <div className="field-help">Two-stage retrieval: a local cross-encoder re-scores the shortlist and keeps only the best matches. Big accuracy boost; adds some latency. Runs offline on CPU (no extra cost). Min score is ignored while this is on (the reranker score is on a different scale).</div>
            </div>
          )}
        </div>
      </CollapsibleSection>

      <CollapsibleSection label="FAQs / Q&amp;A" badge={qaOn ? "enabled" : undefined}
        hint="Also pull curated FAQ / Q&amp;A pairs into context alongside the documents.">
        <div className="col gap2">
          <label className="row gap2" style={{ cursor: "pointer" }}>
            <Toggle on={qaOn} onChange={(on) => set({ include_qa: on })} />
            <span className="t-body-sm">Include FAQ / Q&amp;A answers</span>
          </label>
          {qaOn && (
            <div className="col gap2" style={{ paddingLeft: 6 }}>
              <Field label="Kinds" help="Limit Q&A to these kinds/categories (none selected = all).">
                <MultiSelectChips value={c.qa_kinds || []} options={kinds} onChange={(items) => set({ qa_kinds: items })} />
              </Field>
              <div className="row gap3 wrap">
                <Field label="Pairs (top K)" help="Q&A pairs returned per lookup.">
                  <input className="input" type="number" min={1} max={20} step={1} style={{ width: 92 }}
                    value={c.qa_top_k ?? 3} onChange={(e) => set({ qa_top_k: Number(e.target.value) || 1 })} />
                </Field>
                <Field label="Match threshold" help="Min similarity for a Q&A pair (0–1).">
                  <input className="input" type="number" min={0} max={1} step={0.05} style={{ width: 92 }}
                    value={c.qa_threshold ?? 0.3} onChange={(e) => set({ qa_threshold: Number(e.target.value) })} />
                </Field>
              </div>
            </div>
          )}
        </div>
      </CollapsibleSection>

      <div className="col gap2">
        <div className="t-micro">When nothing is found</div>
        <label className="row gap2" style={{ cursor: "pointer" }}>
          <Toggle on={!!c.announce_empty} onChange={(on) => set({ announce_empty: on })} />
          <span className="t-body-sm">Announce when empty</span>
        </label>
        <div className="field-help">Tells a grounded agent nothing relevant was found, so it says “I don’t know” instead of guessing.</div>
        <Field label="Route flag (state key)" help="Optional: writes 'yes'/'no' (anything found?) to this state field so a Router can branch found vs not-found.">
          <input className="input mono" value={c.route_key ?? ""} placeholder="data_found" onChange={(e) => set({ route_key: e.target.value || undefined })} />
        </Field>
      </div>

      {!ragOn && !qaOn && (
        <div className="field-help" style={{ color: "var(--warn)" }}>
          ⚠ Both sources are off - this node will retrieve nothing. Turn on Knowledge and/or Q&amp;A above.
        </div>
      )}
    </div>
  );
}

function RouterForm({
  nodeId,
  c,
  set,
  nodeIds,
  nodes,
  upstreamSources = [],
  onCaseTarget,
  onCaseRename,
  onCaseRemove,
}: {
  nodeId: string;
  c: Record<string, any>;
  set: (p: Record<string, any>) => void;
  nodeIds: string[];
  nodes: FlowNode[];
  upstreamSources?: UpstreamSource[];
  onCaseTarget: (nodeId: string, key: string, target: string) => void;
  onCaseRename: (nodeId: string, oldKey: string, newKey: string) => void;
  onCaseRemove: (nodeId: string, key: string) => void;
}) {
  const [mode, setMode] = useState<"rules" | "expression">(c.rules ? "rules" : "expression");
  const rules: Array<{ property: string; op: string; value: any; target: string }> = Array.isArray(c.rules) ? c.rules : [];
  const cases: Record<string, string> = c.cases || {};
  const rows = Object.entries(cases);

  const addRule = () => {
    const next = [...rules, { property: "payload.status", op: "eq", value: "active", target: nodeIds[0] || "" }];
    set({ rules: next });
  };
  const updateRule = (idx: number, patch: Partial<(typeof rules)[0]>) => {
    const next = rules.map((r, i) => (i === idx ? { ...r, ...patch } : r));
    set({ rules: next });
  };
  const removeRule = (idx: number) => {
    const next = rules.filter((_, i) => i !== idx);
    set({ rules: next });
  };

  const setCase = (k: string, v: string) => {
    set({ cases: { ...cases, [k]: v } });
    onCaseTarget(nodeId, k, v);
  };
  const renameCase = (oldK: string, newK: string) => {
    if (!newK || newK === oldK) return;
    const n = { ...cases };
    const val = n[oldK];
    delete n[oldK];
    n[newK] = val;
    set({ cases: n });
    onCaseRename(nodeId, oldK, newK);
  };
  const removeCase = (k: string) => {
    const n = { ...cases };
    delete n[k];
    set({ cases: n });
    onCaseRemove(nodeId, k);
  };
  const writers = stateWriters(nodes);
  const activeWriter = writers.find((w) => w.key === (c.expression || "").trim());
  const nextCaseKey = () => {
    const nextKnown = activeWriter?.values?.find((value) => value && !Object.prototype.hasOwnProperty.call(cases, value));
    if (nextKnown) return nextKnown;
    let i = rows.length + 1;
    while (Object.prototype.hasOwnProperty.call(cases, `case_${i}`)) i++;
    return `case_${i}`;
  };
  const addCase = () => setCase(nextCaseKey(), "");

  return (
    <div className="col gap3">
      <div className="row spread" style={{ borderBottom: "1px solid var(--line)", paddingBottom: 6 }}>
        <span className="t-micro">Routing Mode</span>
        <div className="row gap1">
          <button
            type="button"
            className="chip"
            style={{
              cursor: "pointer",
              background: mode === "rules" ? "var(--accent)" : "var(--bg-3)",
              color: mode === "rules" ? "var(--fg-on-accent)" : "var(--fg-1)",
              borderColor: mode === "rules" ? "var(--accent)" : "var(--line)",
            }}
            onClick={() => {
              setMode("rules");
              if (!c.rules) {
                set({ rules: [{ property: "payload.status", op: "eq", value: "active", target: nodeIds[0] || "" }] });
              }
            }}
          >
            Simple Rules
          </button>
          <button
            type="button"
            className="chip"
            style={{
              cursor: "pointer",
              background: mode === "expression" ? "var(--accent)" : "var(--bg-3)",
              color: mode === "expression" ? "var(--fg-on-accent)" : "var(--fg-1)",
              borderColor: mode === "expression" ? "var(--accent)" : "var(--line)",
            }}
            onClick={() => setMode("expression")}
          >
            Expression
          </button>
        </div>
      </div>

      {mode === "rules" ? (
        <div className="col gap3">
          <div className="row spread">
            <span className="t-body-sm fg-2">Switch Conditions</span>
            <button type="button" className="btn btn-xs btn-secondary" onClick={addRule}>
              <Icon name="plus" size={12} /> Add Rule
            </button>
          </div>
          {rules.length === 0 ? (
            <div className="field-help">No rules configured. Messages will follow the default target.</div>
          ) : (
            <div className="col gap2">
              {rules.map((r, i) => (
                <div key={i} className="card col gap1" style={{ padding: 8, background: "var(--bg-3)", border: "1px solid var(--line)" }}>
                  <div className="row spread">
                    <span className="mono-sm fg-2" style={{ fontSize: 11 }}>Rule #{i + 1}</span>
                    <button type="button" className="iconbtn" style={{ width: 20, height: 20 }} onClick={() => removeRule(i)}>
                      <Icon name="trash" size={12} />
                    </button>
                  </div>
                  <div className="row gap1" style={{ alignItems: "center" }}>
                    <input
                      className="input mono"
                      style={{ height: 26, fontSize: 11, flex: 1 }}
                      placeholder="property (e.g. payload.status)"
                      value={r.property || ""}
                      onChange={(e) => updateRule(i, { property: e.target.value })}
                    />
                    <VariablePicker
                      sources={upstreamSources}
                      onSelect={(path) => updateRule(i, { property: path })}
                    />
                  </div>
                  <div className="row gap1">
                    <select
                      className="select"
                      style={{ height: 26, fontSize: 11, flex: 1 }}
                      value={r.op}
                      onChange={(e) => updateRule(i, { op: e.target.value })}
                    >
                      <option value="eq">== (equals)</option>
                      <option value="neq">!= (not equals)</option>
                      <option value="contains">contains</option>
                      <option value="gt">&gt; (greater than)</option>
                      <option value="gte">&gt;= (greater than or equal)</option>
                      <option value="lt">&lt; (less than)</option>
                      <option value="lte">&lt;= (less than or equal)</option>
                      <option value="exists">exists</option>
                      <option value="empty">is empty</option>
                      <option value="true">is true</option>
                      <option value="false">is false</option>
                    </select>
                    {!["exists", "empty", "true", "false"].includes(r.op) && (
                      <input
                        className="input mono"
                        style={{ height: 26, fontSize: 11, flex: 1 }}
                        placeholder="value"
                        value={r.value !== undefined ? String(r.value) : ""}
                        onChange={(e) => updateRule(i, { value: e.target.value })}
                      />
                    )}
                  </div>
                  <div className="row gap1" style={{ alignItems: "center" }}>
                    <span className="fg-2 mono-sm" style={{ fontSize: 10, width: 44 }}>route →</span>
                    <select
                      className="select"
                      style={{ height: 26, fontSize: 11, flex: 1 }}
                      value={r.target || ""}
                      onChange={(e) => updateRule(i, { target: e.target.value })}
                    >
                      <option value="">Select target node…</option>
                      {nodeIds.map((id) => <option key={id} value={id}>{id}</option>)}
                    </select>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <>
          <div>
            <div className="field-label">Expression (over state)</div>
            <input className="input mono" value={c.expression || ""} placeholder="intent" list="router-state-keys" onChange={(e) => set({ expression: e.target.value })} />
            <datalist id="router-state-keys">{writers.map((w) => <option key={w.key} value={w.key} />)}</datalist>
            {writers.length > 0 ? (
              <div className="field-help">
                Keys written upstream: {writers.map((w) => `${w.key} (${w.values.slice(0, 4).join("/") || "…"}, from ${w.from})`).join(" · ")}
              </div>
            ) : (
              <div className="field-help" style={{ color: "var(--warn)" }}>
                ⚠ No node in this workflow writes a routable state key yet. Add a Classifier (writes a label), or set a route/decision flag on Retrieval or Human Input - otherwise every run takes the Default path.
              </div>
            )}
          </div>
          <div>
            <div className="field-label">Cases - when the expression VALUE equals… → go to</div>
            {activeWriter && (
              <div className="field-help" style={{ marginBottom: 6 }}>
                '{activeWriter.key}' takes the values: <b>{activeWriter.values.join(", ") || "(set by " + activeWriter.from + ")"}</b> - use those exact values as case keys.
              </div>
            )}
            <div className="col gap2">
              {rows.map(([k, v], i) => (
                <div key={i} className="row gap2">
                  <input className="input mono" style={{ flex: 1 }} value={k} onChange={(e) => renameCase(k, e.target.value)} />
                  <Icon name="chevright" size={14} style={{ color: "var(--fg-2)" }} />
                  <select className="select" style={{ flex: 1 }} value={v} onChange={(e) => setCase(k, e.target.value)}>
                    <option value="">target…</option>
                    {nodeIds.map((id) => <option key={id} value={id}>{id}</option>)}
                  </select>
                  <button className="iconbtn" onClick={() => removeCase(k)}><Icon name="trash" size={14} /></button>
                </div>
              ))}
              <button className="btn btn-secondary btn-sm" style={{ alignSelf: "flex-start" }} onClick={addCase}><Icon name="plus" size={13} />Add case</button>
            </div>
          </div>
        </>
      )}

      <div>
        <div className="field-label">Default target</div>
        <select className="select" value={c.default || ""} onChange={(e) => { set({ default: e.target.value }); onCaseTarget(nodeId, "__default__", e.target.value); }}>
          <option value="">none</option>
          {nodeIds.map((id) => <option key={id} value={id}>{id}</option>)}
        </select>
        {!c.default && (
          <div className="field-help" style={{ color: "var(--warn)" }}>
            ⚠ No default: if no rules match, the run ends silently.
          </div>
        )}
      </div>
      <div>
        <label className="row gap2" style={{ alignItems: "center", cursor: "pointer" }}>
          <input type="checkbox" checked={!!c.multi} onChange={(e) => set({ multi: e.target.checked })} />
          <span className="field-label" style={{ margin: 0 }}>Route to every match (multi)</span>
        </label>
        <div className="field-help">
          For list-valued expressions or multiple matching rules: run EVERY matching case in parallel.
        </div>
      </div>
    </div>
  );
}

