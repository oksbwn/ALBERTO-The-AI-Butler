/* Forge mock data - generic, plausible SaaS content. Ported from the design handoff.
   Screens not yet wired to the live API render from this; the Dashboard merges live
   projects from the backend when available (see lib/api.ts). */

/* Format a USD cost. Cheap models cost fractions of a cent per run, so a flat
   $0.00 reads as "broken" even when tracking works - show small amounts with
   enough precision (down to a sub-cent floor) so non-zero cost is visible. */
export const fmtUSD = (v: number | null | undefined): string => {
  const n = v || 0;
  if (n <= 0) return "$0.00";
  if (n >= 0.01) return `$${n.toFixed(2)}`;
  if (n >= 0.0001) return `$${n.toFixed(4)}`;
  return "<$0.0001";
};

// The model catalog now lives on the backend (single source of truth so the picker and cost
// engine can't disagree). Fetch it with `useModels()` from lib/models.ts.

export const NODE_CATALOG = [
  { group: "Flow", color: "var(--io-control)", items: [
    { type: "inject", icon: "play", label: "Inject", desc: "Manual trigger / message input" },
    { type: "debug", icon: "eye", label: "Debug", desc: "Inspect msg payload" },
    { type: "delay", icon: "clock", label: "Delay", desc: "Wait for a specified duration" },
    { type: "start", icon: "n_start", label: "Start", desc: "Entry marker" },
    { type: "end", icon: "n_end", label: "End", desc: "Terminal node" },
    { type: "router", icon: "n_router", label: "Router", desc: "Conditional branch / switch" },
    { type: "loop", icon: "n_loop", label: "Loop", desc: "Bounded iteration" },
    { type: "parallel_fanout", icon: "n_fanout", label: "Fan-out", desc: "Map over a list" },
    { type: "join", icon: "n_join", label: "Join", desc: "Wait-for-all / reduce" },
  ]},
  { group: "Agents", color: "var(--accent)", items: [
    { type: "agent", icon: "n_agent", label: "Agent", desc: "ReAct tool loop" },
    { type: "deep_agent", icon: "n_deepagent", label: "Deep Agent", desc: "Planning + subagents harness" },
  ]},
  { group: "Model & Tools", color: "var(--io-json)", items: [
    { type: "llm", icon: "n_llm", label: "LLM", desc: "Single model call" },
    { type: "classifier", icon: "n_router", label: "Classifier", desc: "Intent classification" },
    { type: "tool_call", icon: "n_tool", label: "Tool Call", desc: "Run a specific tool" },
    { type: "transform", icon: "n_transform", label: "Transform", desc: "JMESPath data map" },
  ]},
  { group: "Knowledge", color: "var(--io-vector)", items: [
    { type: "retrieval", icon: "n_retrieval", label: "Retrieval", desc: "RAG + Q&A" },
  ]},
  { group: "Human", color: "var(--warn)", items: [
    { type: "human_input", icon: "n_human", label: "Human Input", desc: "HITL pause via interrupt" },
  ]},
  { group: "Integrations", color: "var(--signal)", items: [
    { type: "subworkflow", icon: "n_subworkflow", label: "Subworkflow", desc: "Embed another graph" },
    { type: "webhook_out", icon: "n_webhook", label: "Webhook", desc: "Call external URL" },
    { type: "emit_event", icon: "n_emit", label: "Emit Event", desc: "Push custom SSE frame" },
  ]},
];

export const NODE_META: Record<string, any> = {};
NODE_CATALOG.forEach((g) => g.items.forEach((it) => (NODE_META[it.type] = { ...it, group: g.group, color: g.color })));

/* The friendly, human-readable name for a node - the SAME string the canvas shows on the node
   card (ForgeNode): the operator-set `config.name`, else the node type's catalog label, else the
   raw type. Runs, traces and the RUN STEPS list key everything on the node `id` (needed for the
   graph and the per-node cost rollup), so the id stays canonical - this is a DISPLAY layer that
   makes a bigger workflow readable without losing traceability (the id is still shown alongside). */
export type NodeLabel = { label: string; type: string };

// Build an `id -> {label, type}` map from a workflow definition. Accepts either the executable
// (`{id,type,config}`) or the canvas / React-Flow (`{id, data:{nodeType, config}}`) node shape, so
// callers can pass whichever they have (mirrors WorkflowTestPanel's dual-shape read).
export function buildNodeLabels(workflow: any): Record<string, NodeLabel> {
  const nodes = workflow?.executable?.nodes || workflow?.canvas?.nodes || workflow?.nodes || [];
  const map: Record<string, NodeLabel> = {};
  for (const n of nodes) {
    if (!n?.id) continue;
    const type = n.type ?? n?.data?.nodeType ?? "";
    const name = n?.config?.name ?? n?.data?.config?.name;
    map[n.id] = { label: name || NODE_META[type]?.label || type || n.id, type };
  }
  return map;
}

// The label to show for a run step / span whose canonical name is a node id. Falls back to the
// raw name for spans that aren't graph nodes (e.g. "model · …", "embedding · …", a subagent).
export function nodeLabel(name: string, labels: Record<string, NodeLabel>): string {
  return labels[name]?.label || name;
}

/* Hover help for the canvas palette: what each node is for + a tiny concrete example.
   Keep these in plain product language - they're the first thing a new user reads. */
export const NODE_HELP: Record<string, { what: string; example: string }> = {
  start: {
    what: "The entry point. Every run begins here - wire it to your first real step.",
    example: "Start → Retrieval → Agent → End",
  },
  end: {
    what: "Marks where the run finishes. A workflow can have several Ends (one per branch).",
    example: "FAQ hit → End (answered early), miss → Agent → End",
  },
  router: {
    what: "Branches the flow based on a value already in state - no model call. One labeled connector per case, plus Else. With 'multi' on, a list value (multi-label Classifier) runs EVERY matching branch in parallel. Always set a Default - without one, an unmatched value ends the run silently.",
    example: "intent = 'refund' → refund_agent · 'cancel' → retention_agent · Else → general_agent",
  },
  classifier: {
    what: "Calls the model once (structured output) to pick a label from your list and writes it to state (default: intent). Multi-label mode writes EVERY applicable label (a list) - pair with a multi Router so two-part questions reach both specialists. Put a Router after it to branch.",
    example: "labels: return_item, cancel, question - “I want my money back” → return_item",
  },
  agent: {
    what: "A model with tools and a system prompt that loops reason → act until it can answer (ReAct). The workhorse node for answering users.",
    example: "Support agent with a weather tool + knowledge-base grounding",
  },
  deep_agent: {
    what: "An agent plus planning (write_todos), a virtual filesystem, and subagents - for long, multi-step tasks that need decomposition.",
    example: "“Research our top 3 competitors and draft a comparison”",
  },
  llm: {
    what: "One single model call - no tools, no loop. A cheap text step for rewriting, summarizing, or extracting.",
    example: "“Summarize the conversation so far into 2 sentences”",
  },
  transform: {
    what: "Reshapes state with a JMESPath expression - pure data, no model. Reads input_key, writes output_key.",
    example: "messages[-1].content → question",
  },
  tool_call: {
    what: "Invokes one specific project tool directly with fixed arguments - no model deciding whether to call it. Result lands in a state key.",
    example: "Always fetch get_weather before the agent answers",
  },
  human_input: {
    what: "PAUSES the run with a real interrupt until a person approves or rejects in the Playground. Use for irreversible or sensitive steps.",
    example: "Agent drafts a refund email → human approves → it goes out",
  },
  webhook_out: {
    what: "Sends data from the run to an external URL (POST/PUT/…) - push results into your own systems.",
    example: "POST the final answer to your Slack webhook",
  },
  emit_event: {
    what: "Emits a named custom event into the run's live stream - for UI badges, metrics, or integrations listening to the run.",
    example: "Emit 'escalated' when the agent hands off to a human",
  },
  retrieval: {
    what: "Pulls the most relevant knowledge into context for the user's question - place it right before a grounded agent. Toggle DOCUMENTS (RAG over your chunks) and Q&A PAIRS independently: use either or both. Tip: for multi-part questions, give the agent a knowledge_search TOOL instead, so it can search per sub-question.",
    example: "KB says “returns within 30 days” → agent answers with that policy",
  },
  // --- flow ---
  loop: {
    what: "Repeats a section of the graph until a condition is false or a max-iteration cap is hit. It increments _loop_count and writes _loop = continue/done - wire a Router on _loop and point the 'continue' branch back to this node.",
    example: "Refine a draft up to 3 times: loop → agent → loop (until good enough)",
  },
  parallel_fanout: {
    what: "Maps over a list in state: runs a child node ONCE PER ITEM, all in parallel (LangGraph Send). Each child reads its item from the chosen state key. Children write to an add-reducer key so results aggregate.",
    example: "over: tickets → run a summarizer per ticket, in parallel",
  },
  join: {
    what: "A convergence point where parallel branches (e.g. a Parallel Fanout's children) meet before the flow continues. Results aggregate via an add-reducer state key.",
    example: "Fanout → (summarize each) → Join → final agent composes the digest",
  },
  subworkflow: {
    what: "Runs ANOTHER workflow in this project as a reusable component (shares the messages state). Build a flow once - 'verify identity', 'look up order' - and drop it into many workflows.",
    example: "Support flow → Subworkflow: 'verify_identity' → continue",
  },
  handoff: {
    what: "Escalates the conversation to a HUMAN: pauses the run and opens a ticket in the Agent inbox. When an agent replies there, their message becomes the assistant's answer and is delivered over the channel.",
    example: "Agent can't resolve → Handoff → a person replies from the inbox",
  },
  // --- triggers (entry points) ---
  webhook_in: {
    what: "Starts the workflow when an external system POSTs to this workflow's hook URL (shown on the Triggers screen after publish). Optionally verify an HMAC signature. Map the JSON body to the message with a JMESPath.",
    example: "Your app POSTs {text: '…'} → the workflow runs and replies",
  },
  schedule: {
    what: "Runs the workflow on a recurring schedule - every N minutes or a cron expression. Sends a fixed message into the flow each time.",
    example: "Every weekday 9am → 'Summarize overnight tickets'",
  },
  email_in: {
    what: "Starts the workflow when an email arrives in the connected mailbox (configure the Email channel under Connect → Channels). Optionally replies to the sender with the answer.",
    example: "support@yourco.com receives a question → agent replies by email",
  },
  app_event: {
    what: "Polls an external source on an interval and runs the workflow once PER NEW item (deduped by a key you choose). Turns any API/feed into an event source.",
    example: "Poll the issues API every 5 min → triage each new issue",
  },
};

export const MIDDLEWARE_CATALOG = [
  { cat: "Memory & Context", color: "var(--signal)", items: [
    { type: "summarization", name: "Summarization", desc: "Summarize older messages near a token limit." },
    { type: "context_editing", name: "Context Editing", desc: "Clear old tool outputs past a threshold." },
    { type: "todo", name: "Planning (To-do)", desc: "Add a write_todos planning tool." },
  ]},
  { cat: "Safety & Guardrails", color: "var(--err)", items: [
    { type: "pii", name: "PII Handling", desc: "Detect & redact/mask/block PII." },
    { type: "guardrail_regex", name: "Regex Guardrail", desc: "Block or flag matched patterns." },
    { type: "openai_moderation", name: "Moderation", desc: "OpenAI moderation on input/output." },
  ]},
  { cat: "Reliability", color: "var(--info)", items: [
    { type: "tool_retry", name: "Tool Retry", desc: "Retry failed tool calls with backoff." },
    { type: "model_retry", name: "Model Retry", desc: "Retry failed model calls." },
    { type: "model_fallback", name: "Model Fallback", desc: "Failover across providers." },
  ]},
  { cat: "Cost & Limits", color: "var(--warn)", items: [
    { type: "model_call_limit", name: "Model Call Limit", desc: "Cap model calls per run/thread." },
    { type: "tool_call_limit", name: "Tool Call Limit", desc: "Cap tool calls, global or per-tool." },
    { type: "tenant_budget", name: "Budget Cap", desc: "Stop when cost/tokens exceed a cap." },
    { type: "llm_tool_selector", name: "Tool Selector", desc: "Pre-select relevant tools (saves tokens)." },
  ]},
  { cat: "Human Oversight", color: "var(--accent)", items: [
    { type: "human_in_the_loop", name: "Human-in-the-loop", desc: "Pause for approval on sensitive tools." },
  ]},
  { cat: "Provider-specific", color: "var(--io-json)", items: [
    { type: "anthropic_prompt_caching", name: "Prompt Caching", desc: "Cache the system prompt (Anthropic)." },
  ]},
  { cat: "Advanced", color: "var(--io-vector)", items: [
    { type: "dynamic_model_by_state", name: "Dynamic Model", desc: "Switch model at runtime by state." },
    { type: "tool_filter_by_context", name: "Tool Filter", desc: "Show/hide tools by context/role." },
  ]},
];
export const MW_META: Record<string, any> = {};
MIDDLEWARE_CATALOG.forEach((c) => c.items.forEach((it) => (MW_META[it.type] = { ...it, cat: c.cat, color: c.color })));

// Sectioned nav: top-level leaves (Overview, Settings) plus collapsible groups
// (Build / Deploy / Observe). The sidebar renders a leaf as a button and a group as a
// labeled, collapsible section. `countKey` shows a live badge.
export type NavLeaf = { id: string; label: string; icon: string; help?: string; countKey?: string };
export type NavGroup = { id: string; section: string; icon: string; help?: string; items: NavLeaf[] };
export type NavEntry = NavLeaf | NavGroup;

export const PROJECT_NAV: NavEntry[] = [
  { id: "home", label: "Home", icon: "home", help: "Alberto Home: AI assistant & system insights." },
  {
    id: "automate",
    section: "Automate",
    icon: "workflow",
    help: "Conversational workflow engineering with Automation Manager, visual workflows, agents, and components.",
    items: [
      { id: "playground", label: "Playground", icon: "playground", help: "AI Automation Manager Studio: conversational design, safe testing, and execution." },
      { id: "workflows", label: "Workflows", icon: "workflow", countKey: "workflows", help: "Visual workflow builder & graph canvas." },
      { id: "agents", label: "Agents", icon: "bot", countKey: "agents", help: "Autonomous agent presets and prompts." },
      { id: "components", label: "Components", icon: "grid", countKey: "components", help: "Interactive UI chat widgets." },
      { id: "traces", label: "Executions", icon: "activity", help: "Execution traces, monitoring, and troubleshooting." },
    ],
  },
  {
    id: "knowledge_group",
    section: "Knowledge",
    icon: "book-open",
    help: "Interactive recall playground, document RAG, curated Q&A, graph ontology, and autonomous memory.",
    items: [
      { id: "knowledge-playground", label: "Playground", icon: "playground", help: "Interactive multi-source recall probe, memory sub-agent simulator, and grounding matrix." },
      { id: "knowledge-docs", label: "Documents", icon: "book-open", countKey: "knowledge", help: "Vector RAG documents, files, and chunks." },
      { id: "knowledge-vector", label: "Vector Store", icon: "layers", help: "ChromaDB vector persistence, chunk map visualizer, and embedding health." },
      { id: "knowledge-qa", label: "Q&A Pairs", icon: "n_qa", help: "Curated questions and answers for exact RAG matching." },
      { id: "knowledge-graph", label: "Knowledge Graph", icon: "n_router", help: "LadybugDB graph entities, relations, and ontology." },
      { id: "knowledge-memory", label: "Long-Term Memory", icon: "brain", countKey: "memories", help: "Authoritative SQLite & Markdown memory entries." },
    ],
  },
  {
    id: "integrations",
    section: "Integrations",
    icon: "plug",
    help: "Connectors, tools, and auth.",
    items: [
      { id: "integrations-playground", label: "Playground", icon: "playground", help: "Interactive test bench for REST, MCP tools and channels with HITL approval." },
      { id: "integrations", label: "Integrations", icon: "plug", countKey: "connectors", help: "Unified Integrations (Connectors, MCP, Channels, Custom API)." },
      { id: "tools", label: "Tools", icon: "tools", countKey: "tools", help: "REST, Code, SQL, and custom tools." },
      { id: "triggers", label: "Triggers", icon: "bolt", help: "Webhooks, pollers, and scheduled routines." },
      { id: "auth", label: "Auth & Credentials", icon: "key", help: "Authentication providers and shared OAuth 2.0 app credentials." },
    ],
  },
  {
    id: "observability",
    section: "Observability",
    icon: "activity",
    help: "Analytics, traces, evaluations, and inbox.",
    items: [
      { id: "overview", label: "Analytics", icon: "layout-dashboard", help: "Latency, volume, tokens, and model breakdowns." },
      { id: "traces", label: "Traces", icon: "activity", help: "Waterfall spans, model turns, and token logs." },
      { id: "datasets", label: "Evaluations", icon: "validate", help: "Automated regression tests and scorecards." },
      { id: "handoff", label: "Agent Inbox", icon: "inbox", countKey: "handoffs", help: "Human review tickets and escalations." },
    ],
  },
  { id: "settings", label: "Settings", icon: "settings", help: "Model defaults, provider keys, secrets, and system configuration." },
];

export const IO_COLOR: Record<string, string> = {
  messages: "var(--io-messages)", text: "var(--io-text)", json: "var(--io-json)", tool: "var(--io-tool)",
  embedding: "var(--io-vector)", vector: "var(--io-vector)", any: "var(--io-any)", control: "var(--io-control)",
};
export const KIND_LABEL: Record<string, string> = { rest_api: "REST", graphql: "GraphQL", code: "Code", sql: "SQL", builtin: "Builtin" };
export const KIND_ICON: Record<string, string> = { rest_api: "k_rest", graphql: "k_graphql", code: "k_code", sql: "db", builtin: "k_builtin" };
