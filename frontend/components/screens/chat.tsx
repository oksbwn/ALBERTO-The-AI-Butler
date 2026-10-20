"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "@/components/icons";
import { Tile, Avatar } from "@/components/primitives";
import { Markdown } from "@/components/markdown";
import { api, openSSE, Workflow, Agent, Conversation, ConversationDetail } from "@/lib/api";
import { useModels } from "@/lib/models";

function newThreadId() {
  return `chat-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function formatTime(iso?: string | null) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

interface CompactedTurn {
  role: string;
  content: string;
}

interface ChatMsg {
  role: "user" | "assistant" | "compaction";
  content: string;
  thinking?: string;
  thinkSecs?: number;
  tokensPerSec?: number;
  tokens?: number; // generated completion tokens
  promptTokens?: number;
  completionTokens?: number;
  totalTokens?: number;
  ttftSecs?: number;
  decodeDurationSecs?: number;
  totalDurationSecs?: number;
  durationSecs?: number;
  compactedCount?: number;
  tokensSaved?: number;
  compactedTurns?: CompactedTurn[];
}

function TokenMetricsBadge({ msg }: { msg: ChatMsg }) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const tps = msg.tokensPerSec;
  const completionToks = msg.completionTokens ?? msg.tokens;
  const promptToks = msg.promptTokens;
  const totalToks = msg.totalTokens;
  const ttft = msg.ttftSecs;
  const decodeDuration = msg.decodeDurationSecs ?? msg.durationSecs;
  const totalDuration = msg.totalDurationSecs;

  const hasTps = typeof tps === "number" && tps > 0;
  const hasCompletion = typeof completionToks === "number" && completionToks > 0;

  if (!hasTps && !hasCompletion) return null;

  return (
    <div
      ref={containerRef}
      style={{ position: "relative", marginLeft: "auto" }}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label="Generation metrics details"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        onFocus={() => setOpen(true)}
        onBlur={(e) => {
          if (!containerRef.current?.contains(e.relatedTarget as Node)) {
            setOpen(false);
          }
        }}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          fontSize: 11,
          color: "var(--fg-2)",
          background: "var(--bg-2)",
          border: "1px solid var(--line)",
          borderRadius: 4,
          padding: "1px 7px",
          height: 20,
          fontWeight: 500,
          cursor: "pointer",
        }}
      >
        <Icon name="bolt" size={10} style={{ color: "var(--accent)" }} />
        {hasTps ? (
          <>
            <span style={{ fontWeight: 600, color: "var(--fg-1)" }}>{tps}</span>
            <span style={{ opacity: 0.65, fontSize: 10 }}>tok/s</span>
          </>
        ) : null}
        {hasCompletion ? (
          <span style={{ opacity: 0.5, fontSize: 10 }}>{hasTps ? "· " : ""}{completionToks}t</span>
        ) : null}
      </button>

      {open && (
        <div
          role="tooltip"
          className="card fade-in"
          style={{
            position: "absolute",
            bottom: "calc(100% + 6px)",
            right: 0,
            zIndex: 9999,
            width: 250,
            padding: "10px 12px",
            background: "var(--bg-1)",
            border: "1px solid var(--line)",
            boxShadow: "var(--sh-pop)",
            borderRadius: 6,
            fontSize: 11.5,
            color: "var(--fg-1)",
            lineHeight: 1.4,
            pointerEvents: "auto",
            textAlign: "left",
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 8, color: "var(--fg-0)" }}>
            LLM Generation Metrics
          </div>

          <div style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--fg-2)", marginBottom: 4 }}>
            Token Usage
          </div>
          <table style={{ width: "100%", borderCollapse: "collapse", marginBottom: 8, fontSize: 11 }}>
            <tbody>
              <tr>
                <td style={{ color: "var(--fg-2)", padding: "1px 0" }}>Prompt tokens</td>
                <td style={{ textAlign: "right", fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums" }}>
                  {typeof promptToks === "number" ? promptToks.toLocaleString() : "N/A"}
                </td>
              </tr>
              <tr>
                <td style={{ color: "var(--fg-2)", padding: "1px 0" }}>Completion tokens</td>
                <td style={{ textAlign: "right", fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums" }}>
                  {typeof completionToks === "number" ? completionToks.toLocaleString() : "N/A"}
                </td>
              </tr>
              <tr style={{ borderTop: "1px solid var(--line)" }}>
                <td style={{ color: "var(--fg-1)", fontWeight: 500, padding: "2px 0 1px" }}>Total tokens</td>
                <td style={{ textAlign: "right", fontWeight: 600, fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums", padding: "2px 0 1px" }}>
                  {typeof totalToks === "number" ? totalToks.toLocaleString() : (
                    (typeof promptToks === "number" && typeof completionToks === "number") ? (promptToks + completionToks).toLocaleString() : "N/A"
                  )}
                </td>
              </tr>
            </tbody>
          </table>

          <div style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--fg-2)", marginBottom: 4 }}>
            Latency
          </div>
          <table style={{ width: "100%", borderCollapse: "collapse", marginBottom: 8, fontSize: 11 }}>
            <tbody>
              <tr>
                <td style={{ color: "var(--fg-2)", padding: "1px 0" }}>Time to first token</td>
                <td style={{ textAlign: "right", fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums" }}>
                  {typeof ttft === "number" ? `${ttft.toFixed(2)} s` : "N/A"}
                </td>
              </tr>
              <tr>
                <td style={{ color: "var(--fg-2)", padding: "1px 0" }}>Generation duration</td>
                <td style={{ textAlign: "right", fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums" }}>
                  {typeof decodeDuration === "number" ? `${decodeDuration.toFixed(2)} s` : "N/A"}
                </td>
              </tr>
              <tr style={{ borderTop: "1px solid var(--line)" }}>
                <td style={{ color: "var(--fg-1)", fontWeight: 500, padding: "2px 0 1px" }}>Total response time</td>
                <td style={{ textAlign: "right", fontWeight: 600, fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums", padding: "2px 0 1px" }}>
                  {typeof totalDuration === "number" ? `${totalDuration.toFixed(2)} s` : "N/A"}
                </td>
              </tr>
            </tbody>
          </table>

          <div style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--fg-2)", marginBottom: 4 }}>
            Performance
          </div>
          <div className="row spread" style={{ fontSize: 11, alignItems: "center" }}>
            <span style={{ color: "var(--fg-2)" }}>Generation speed</span>
            <span style={{ fontWeight: 600, color: "var(--accent)", fontFamily: "var(--font-mono)", fontVariantNumeric: "tabular-nums" }}>
              {hasTps ? `${tps} tok/s` : "N/A"}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

interface ChatStep {
  name: string;
  result?: any;
  turn: number;
}

interface ChatTodo {
  text: string;
  done: boolean;
}

export const SYSTEM_SUB_AGENTS: Agent[] = [
  {
    id: "tool_manager",
    project_id: "",
    name: "Integration Manager",
    system_key: "tool_manager",
    is_system: true,
    config: { description: "Inspects, tests, and manages tools, MCP servers, and integration channels." },
  },
  {
    id: "memory_curator",
    project_id: "",
    name: "Memory Curator",
    system_key: "memory_curator",
    is_system: true,
    config: { description: "Curates, audits, and organizes long-term memories and knowledge graph." },
  },
  {
    id: "graph_manager",
    project_id: "",
    name: "Graph Manager",
    system_key: "graph_manager",
    is_system: true,
    config: { description: "Inspects and explains entities, relationships, and ontology mappings in Alberto's graph." },
  },
  {
    id: "intent_router",
    project_id: "",
    name: "Intent Router",
    system_key: "intent_router",
    is_system: true,
    config: { description: "Analyzes user requests, classifies intents, and determines automation routing." },
  },
];

export function ChatScreen({
  project,
  onMutate,
  externalInput,
  onExternalInputConsumed,
  persona = "assistant",
  target: controlledTarget,
  onTargetChange,
}: {
  project: any;
  onMutate?: () => void;
  externalInput?: string;
  onExternalInputConsumed?: () => void;
  persona?: "assistant" | "memory_curator" | "tool_manager" | "integration_manager" | string;
  target?: string;
  onTargetChange?: (t: string) => void;
}) {
  // Target agent/workflow selector: "assistant" (default master agent), "agent:<system_key|id>", or "workflow:<id>"
  const [internalTarget, setInternalTarget] = useState<string>("assistant");
  const target = controlledTarget !== undefined ? controlledTarget : internalTarget;
  const setTarget = useCallback(
    (newTarget: string) => {
      setInternalTarget(newTarget);
      onTargetChange?.(newTarget);
    },
    [onTargetChange]
  );

  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);

  // Always guarantee system sub-agents exist
  const effectiveAgents = agents.length > 0 ? agents : SYSTEM_SUB_AGENTS;

  // Target agent/workflow selector resolution: "assistant" (default master agent), "agent:<system_key|id>", or "workflow:<id>"
  const isWorkflow = target.startsWith("workflow:") || (!target.startsWith("agent:") && target !== "assistant" && workflows.some((w) => w.id === target));
  const targetWorkflowId = target.startsWith("workflow:") ? target.slice("workflow:".length) : target;
  const isAgent = target.startsWith("agent:");
  const targetAgentKey = target.startsWith("agent:") ? target.slice("agent:".length) : null;
  const selectedAgent = effectiveAgents.find((a) => a.id === targetAgentKey || a.system_key === targetAgentKey);
  const selectedWf = workflows.find((w) => w.id === targetWorkflowId);

  // Custom agents not in the core system keys
  const coreKeys = new Set(["tool_manager", "integration_manager", "memory_curator", "graph_manager", "intent_router"]);
  const customAgents = effectiveAgents.filter((a) => !coreKeys.has(a.system_key || a.id));
  const isCustomAgent = isAgent && !coreKeys.has(targetAgentKey || "");

  // Active persona resolution
  const activePersona = persona === "memory_curator"
    ? "memory_curator"
    : persona === "tool_manager" || persona === "integration_manager"
    ? "tool_manager"
    : isAgent
    ? (selectedAgent?.system_key || selectedAgent?.name?.toLowerCase().replace(/\s+/g, "_") || "agent")
    : "assistant";

  const isCurator = activePersona === "memory_curator";
  const isGraphManager = activePersona === "graph_manager";
  const isIntentRouter = activePersona === "intent_router";
  const isToolManager = activePersona === "tool_manager" || activePersona === "integration_manager";

  const [agentDropdownOpen, setAgentDropdownOpen] = useState(false);
  const agentDropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (agentDropdownRef.current && !agentDropdownRef.current.contains(e.target as Node)) {
        setAgentDropdownOpen(false);
      }
    }
    if (agentDropdownOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [agentDropdownOpen]);

  // Current active entity display info for dropdown button
  const activeTargetInfo = useMemo(() => {
    if (isWorkflow) {
      return {
        name: selectedWf?.name || "Workflow",
        badge: "WORKFLOW",
        icon: "workflow",
        color: "var(--accent)",
      };
    }
    if (isToolManager) {
      return {
        name: "Integration Manager",
        badge: "SUB-AGENT",
        icon: "tools",
        color: "var(--accent, #6366f1)",
      };
    }
    if (isCurator) {
      return {
        name: "Memory Curator",
        badge: "SUB-AGENT",
        icon: "brain",
        color: "#a855f7",
      };
    }
    if (isGraphManager) {
      return {
        name: "Graph Manager",
        badge: "SUB-AGENT",
        icon: "workflows",
        color: "#06b6d4",
      };
    }
    if (isIntentRouter) {
      return {
        name: "Intent Router",
        badge: "SUB-AGENT",
        icon: "tools",
        color: "#f59e0b",
      };
    }
    if (isAgent) {
      return {
        name: selectedAgent?.name || "Sub-Agent",
        badge: "SUB-AGENT",
        icon: "bot",
        color: "var(--io-control)",
      };
    }
    return {
      name: "Alberto",
      badge: "MASTER AGENT",
      icon: "sparkles",
      color: "var(--accent)",
    };
  }, [isWorkflow, isToolManager, isCurator, isGraphManager, isIntentRouter, isAgent, selectedWf, selectedAgent]);

  const models = useModels();
  const [selectedModel, setSelectedModel] = useState<string>("");

  useEffect(() => {
    if (!selectedModel && models.length > 0) {
      const def = models.find((m) => m.is_default) || models[0];
      if (def) setSelectedModel(def.id);
    }
  }, [models, selectedModel]);

  const activeModel = models.find((m) => m.id === selectedModel) || models.find((m) => m.is_default) || models[0];

  // Messages & Stream State
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");

  useEffect(() => {
    if (externalInput) {
      setInput(externalInput);
      onExternalInputConsumed?.();
    }
  }, [externalInput, onExternalInputConsumed]);
  const [streaming, setStreaming] = useState("");
  const [liveThink, setLiveThink] = useState<string | null>(null);
  const [openThought, setOpenThought] = useState<number | null>(null);
  const [steps, setSteps] = useState<ChatStep[]>([]);
  const [currentTool, setCurrentTool] = useState<string | null>(null);
  const [stepsOpen, setStepsOpen] = useState(false);
  const [expandedStep, setExpandedStep] = useState<number | null>(null);
  const [todos, setTodos] = useState<ChatTodo[]>([]);
  const [busy, setBusy] = useState(false);
  const [busySecs, setBusySecs] = useState(0);
  const [thinkingMode, setThinkingMode] = useState(false);
  const [lastServerTokens, setLastServerTokens] = useState<number | null>(null);
  const [pendingApproval, setPendingApproval] = useState<string | null>(null);
  const [pendingRunInterrupt, setPendingRunInterrupt] = useState<{ runId: string; wid: string; payload: any } | null>(null);
  const [liveTps, setLiveTps] = useState<number>(0);
  const [liveTokens, setLiveTokens] = useState<number>(0);
  const firstTokenTsRef = useRef<number | null>(null);

  // Abort / Cancellation Controller
  const abortRef = useRef<AbortController | null>(null);

  const stopGenerating = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setBusy(false);
    setStreaming("");
    setLiveThink(null);
    setCurrentTool(null);
    setLiveTps(0);
    setLiveTokens(0);
  }, []);

  // Keyboard shortcut Esc to stop
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && busy) {
        e.preventDefault();
        stopGenerating();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, stopGenerating]);

  // Voice Butler (STT & TTS)
  const [isListening, setIsListening] = useState(false);
  const [autoSpeak, setAutoSpeak] = useState(false);
  const [currentlySpeaking, setCurrentlySpeaking] = useState<number | null>(null);
  const recognitionRef = useRef<any>(null);

  const toggleListening = useCallback(() => {
    if (isListening) {
      recognitionRef.current?.stop();
      setIsListening(false);
      return;
    }
    const SpeechRec = (typeof window !== "undefined" && ((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition));
    if (!SpeechRec) {
      alert("Speech recognition is not supported in this browser. Please use Chrome, Edge, or Safari.");
      return;
    }
    try {
      const rec = new SpeechRec();
      rec.continuous = false;
      rec.interimResults = true;
      rec.lang = "en-US";
      rec.onstart = () => setIsListening(true);
      rec.onresult = (e: any) => {
        const transcript = Array.from(e.results)
          .map((r: any) => r[0]?.transcript || "")
          .join("");
        if (transcript) setInput(transcript);
      };
      rec.onerror = () => setIsListening(false);
      rec.onend = () => setIsListening(false);
      recognitionRef.current = rec;
      rec.start();
    } catch {
      setIsListening(false);
    }
  }, [isListening]);

  const speakText = useCallback((text: string, msgIdx?: number) => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    if (currentlySpeaking === msgIdx && msgIdx !== undefined) {
      setCurrentlySpeaking(null);
      return;
    }
    const clean = text
      .replace(/```[\s\S]*?```/g, "Code block omitted.")
      .replace(/`([^`]+)`/g, "$1")
      .replace(/[*_#>[\]()]/g, "")
      .trim();
    if (!clean) return;
    const utter = new SpeechSynthesisUtterance(clean);
    utter.rate = 1.05;
    utter.onend = () => setCurrentlySpeaking(null);
    utter.onerror = () => setCurrentlySpeaking(null);
    if (msgIdx !== undefined) setCurrentlySpeaking(msgIdx);
    window.speechSynthesis.speak(utter);
  }, [currentlySpeaking]);

  // Compaction state
  const [expandedCompaction, setExpandedCompaction] = useState<number | null>(null);

  useEffect(() => {
    if (!busy) {
      setBusySecs(0);
      return;
    }
    const t = setInterval(() => setBusySecs((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [busy]);

  // Conversations History State
  const [convosOpen, setConvosOpen] = useState(false);
  const [convos, setConvos] = useState<Conversation[]>([]);
  const [loadingConvos, setLoadingConvos] = useState(false);
  const [convoSearch, setConvoSearch] = useState("");

  const turnRef = useRef(0);
  const threadRef = useRef<string>(newThreadId());
  const scrollRef = useRef<HTMLDivElement>(null);
  const thinkRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 1e9, behavior: "smooth" });
  }, [msgs, streaming, currentTool, pendingApproval, liveThink !== null]);

  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 180)}px`;
  }, [input]);

  useEffect(() => {
    if (thinkRef.current) thinkRef.current.scrollTop = thinkRef.current.scrollHeight;
  }, [liveThink]);

  // Load available workflows & agents for the selector
  useEffect(() => {
    if (!project?.id) return;
    api.listWorkflows(project.id).then(setWorkflows).catch(() => {});
    api.listAgents(project.id).then(setAgents).catch(() => {});
  }, [project?.id]);

  // Reset thread on project change
  useEffect(() => {
    threadRef.current = newThreadId();
    setMsgs([]);
    setSteps([]);
    setTodos([]);
    setPendingApproval(null);
    setPendingRunInterrupt(null);
    setLiveThink(null);
  }, [project?.id]);

  // Fetch past conversation threads
  const loadConversations = async () => {
    if (!project?.id) return;
    setLoadingConvos(true);
    try {
      const list = await api.listConversations(project.id, { limit: 30 });
      setConvos(list || []);
    } catch {
      setConvos([]);
    } finally {
      setLoadingConvos(false);
    }
  };

  const openConversation = async (c: Conversation) => {
    if (!project?.id) return;
    setBusy(true);
    try {
      const detail: ConversationDetail = await api.getConversation(project.id, c.thread_id);
      threadRef.current = c.thread_id;
      const parsedMsgs: ChatMsg[] = [];
      (detail.turns || []).forEach((t) => {
        if (t.user_message) parsedMsgs.push({ role: "user", content: t.user_message });
        if (t.ai_response) {
          const tm = (t.meta as any)?.token_metrics;
          parsedMsgs.push({
            role: "assistant",
            content: t.ai_response,
            tokensPerSec: tm?.tokens_per_sec ?? undefined,
            tokens: tm?.completion_tokens ?? tm?.tokens ?? undefined,
            promptTokens: tm?.prompt_tokens ?? undefined,
            completionTokens: tm?.completion_tokens ?? undefined,
            totalTokens: tm?.total_tokens ?? undefined,
            ttftSecs: tm?.ttft_secs ?? undefined,
            decodeDurationSecs: tm?.decode_duration_secs ?? undefined,
            totalDurationSecs: tm?.total_duration_secs ?? undefined,
            durationSecs: tm?.decode_duration_secs ?? undefined,
          });
        }
      });
      setMsgs(parsedMsgs);
      setLastServerTokens(null);
      setConvosOpen(false);
    } catch (e: any) {
      window.alert(`Failed to load conversation: ${e.message || e}`);
    } finally {
      setBusy(false);
    }
  };

  function describeInterrupt(data: any): string {
    const flat = (x: any): any[] => (Array.isArray(x) ? x.flatMap(flat) : [x]);
    for (const item of flat(data?.interrupts ?? data ?? [])) {
      const v = item && typeof item === "object" && "value" in item ? item.value : item;
      const reqs = v?.action_requests || (v?.action_request ? [v.action_request] : v?.action ? [v] : null);
      if (reqs) {
        return reqs.map((r: any) => r.description || `${r.action || r.name || "action"}(${JSON.stringify(r.args || {}).slice(0, 100)})`).join("; ");
      }
      if (v?.prompt) return String(v.prompt);
    }
    return "Action paused waiting for your review.";
  }

  // Stream turn for default Alberto Assistant
  async function streamAssistantTurn(body: Record<string, unknown>, url: string) {
    if (!project) return;
    setStreaming("");
    setLiveThink(null);
    setCurrentTool(null);
    setLiveTps(0);
    setLiveTokens(0);
    firstTokenTsRef.current = null;
    setBusy(true);
    setPendingApproval(null);
    const controller = new AbortController();
    abortRef.current = controller;
    const turn = ++turnRef.current;
    const turnStart = Date.now();
    let mutated = false;
    let interruptPrompt: string | null = null;
    let acted = false;
    let cur = "";
    let segId: string | null = null;
    const done: string[] = [];
    let thinking = false;
    let serverTokens: number | null = null;
    let serverPromptTokens: number | null = null;
    let serverCompletionTokens: number | null = null;

    const render = () => {
      if (thinking) {
        setStreaming("");
        setLiveThink([...done, cur].filter(Boolean).join("\n\n"));
      } else {
        setStreaming(cur);
      }
    };
    const closeSegment = () => {
      if (cur.trim()) done.push(cur.trim());
      cur = "";
    };
    const activateThinking = () => { thinking = true; };

    try {
      await openSSE(url, (f) => {
        if (f.event === "messages" && f.data?.content) {
          if (!firstTokenTsRef.current) {
            firstTokenTsRef.current = Date.now();
          }
          const id = f.data.id || null;
          if (segId && id && id !== segId) { closeSegment(); activateThinking(); }
          if (id) segId = id;
          cur += f.data.content;
          render();
          const totalChars = (thinking ? [...done, cur].join("") : cur).length;
          const approxToks = Math.max(1, Math.round(totalChars / 3.8));
          const elapsed = (Date.now() - firstTokenTsRef.current) / 1000;
          setLiveTokens(approxToks);
          if (elapsed > 0.15) {
            setLiveTps(Number((approxToks / elapsed).toFixed(1)));
          }
        } else if (f.event === "tool" && f.data?.name) {
          acted = true;
          closeSegment(); activateThinking(); render();
          setCurrentTool(f.data.name);
          setSteps((s) => [...s, { name: f.data.name, result: f.data.result, turn }]);
        } else if (f.event === "todos" && Array.isArray(f.data?.todos)) {
          acted = true;
          setTodos(f.data.todos);
        } else if (f.event === "interrupt") {
          interruptPrompt = describeInterrupt(f.data);
        } else if (f.event === "done") {
          mutated = (f.data?.mutated || []).length > 0;
          if (typeof f.data?.completion_tokens === "number") {
            serverCompletionTokens = f.data.completion_tokens;
          }
          if (typeof f.data?.prompt_tokens === "number") {
            serverPromptTokens = f.data.prompt_tokens;
          }
          if (typeof f.data?.total_tokens === "number") {
            serverTokens = f.data.total_tokens;
            setLastServerTokens(f.data.total_tokens);
          } else if (typeof f.data?.tokens === "number" && f.data.tokens > 0) {
            serverTokens = f.data.tokens;
            setLastServerTokens(f.data.tokens);
          }
        } else if (f.event === "error") {
          cur += `\n⚠ ${f.data?.message || "assistant error"}`;
          render();
        }
      }, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: controller.signal });
    } catch (e: any) {
      if (e?.name !== "AbortError") {
        cur += `\n⚠ ${e.message || e}`;
      }
    } finally {
      abortRef.current = null;
      let answer = cur.trim();
      let thought = thinking ? done.join("\n\n") : "";
      if (answer.includes("<think>")) {
        const parts = answer.split("</think>");
        if (parts.length > 1) {
          const extracted = parts[0].replace("<think>", "").trim();
          answer = parts.slice(1).join("</think>").trim();
          thought = thought ? `${thought}\n\n${extracted}` : extracted;
        }
      }
      const turnEnd = Date.now();
      const secs = Math.max(1, Math.round((turnEnd - turnStart) / 1000));
      const firstTok = firstTokenTsRef.current;
      const ttftSecs = firstTok ? Number(((firstTok - turnStart) / 1000).toFixed(2)) : undefined;
      const decodeDurationSecs = firstTok ? Number(Math.max(0.01, (turnEnd - firstTok) / 1000).toFixed(2)) : undefined;
      const totalDurationSecs = Number(Math.max(0.01, (turnEnd - turnStart) / 1000).toFixed(2));

      const finalCompletionTokens = serverCompletionTokens !== null
        ? serverCompletionTokens
        : Math.max(1, Math.round(((answer || "").length + (thought || "").length) / 3.8));

      const promptToks = serverPromptTokens !== null ? serverPromptTokens : undefined;
      const totalToks = serverTokens !== null
        ? serverTokens
        : (promptToks ? promptToks + finalCompletionTokens : undefined);

      const tps = (decodeDurationSecs && decodeDurationSecs > 0)
        ? Number((finalCompletionTokens / decodeDurationSecs).toFixed(1))
        : undefined;

      if (answer || thought || acted) {
        setMsgs((m) => [...m, {
          role: "assistant",
          content: answer || (interruptPrompt ? "(paused for your approval)" : "(action completed)"),
          ...(thought ? { thinking: thought, thinkSecs: secs } : {}),
          tokensPerSec: tps && tps > 0 ? tps : undefined,
          tokens: finalCompletionTokens,
          promptTokens: promptToks,
          completionTokens: finalCompletionTokens,
          totalTokens: totalToks,
          ttftSecs,
          decodeDurationSecs,
          totalDurationSecs,
          durationSecs: decodeDurationSecs,
        }]);
      }
      setStreaming("");
      setLiveThink(null);
      setCurrentTool(null);
      setLiveTps(0);
      setLiveTokens(0);
      setBusy(false);
      setPendingApproval(interruptPrompt);
      if (mutated) onMutate?.();
      if (answer && autoSpeak) {
        speakText(answer);
      }
    }
  }

  // Stream turn for custom Workflow
  async function streamWorkflowRun(wid: string, text: string) {
    if (!project) return;
    setStreaming("");
    setBusy(true);
    setLiveTps(0);
    setLiveTokens(0);
    firstTokenTsRef.current = null;
    setPendingRunInterrupt(null);
    const controller = new AbortController();
    abortRef.current = controller;
    const turn = ++turnRef.current;
    const turnStart = Date.now();
    let accumulated = "";
    let serverTokens: number | null = null;
    let serverPromptTokens: number | null = null;
    let serverCompletionTokens: number | null = null;

    try {
      const run = await api.createRun(
        project.id,
        wid,
        { messages: [{ role: "user", content: text }] },
        threadRef.current || undefined,
      );
      threadRef.current = run.thread_id;
      const url = api.runStreamUrl(project.id, wid, run.id);

      await openSSE(url, (f) => {
        if (f.event === "messages" && f.data?.content) {
          if (!firstTokenTsRef.current) {
            firstTokenTsRef.current = Date.now();
          }
          accumulated += f.data.content;
          setStreaming(accumulated);
          const approxToks = Math.max(1, Math.round(accumulated.length / 3.8));
          const elapsed = (Date.now() - firstTokenTsRef.current) / 1000;
          setLiveTokens(approxToks);
          if (elapsed > 0.15) {
            setLiveTps(Number((approxToks / elapsed).toFixed(1)));
          }
        } else if (f.event === "node_start" && f.data?.node) {
          setSteps((s) => [...s, { name: f.data.node, turn }]);
        } else if (f.event === "interrupt") {
          setPendingRunInterrupt({ runId: run.id, wid, payload: f.data });
        } else if (f.event === "done") {
          if (typeof f.data?.completion_tokens === "number") {
            serverCompletionTokens = f.data.completion_tokens;
          }
          if (typeof f.data?.prompt_tokens === "number") {
            serverPromptTokens = f.data.prompt_tokens;
          }
          if (typeof f.data?.total_tokens === "number") {
            serverTokens = f.data.total_tokens;
          } else if (typeof f.data?.tokens === "number") {
            serverTokens = f.data.tokens;
          }
          if (f.data?.answer) {
            accumulated = f.data.answer;
          }
        } else if (f.event === "error") {
          accumulated += `\n⚠ ${f.data?.message || "workflow error"}`;
        }
      }, { signal: controller.signal });
    } catch (e: any) {
      if (e?.name !== "AbortError") {
        accumulated += `\n⚠ ${e.message || e}`;
      }
    } finally {
      abortRef.current = null;
      const finalMsg = accumulated.trim();
      const turnEnd = Date.now();
      const firstTok = firstTokenTsRef.current;
      const ttftSecs = firstTok ? Number(((firstTok - turnStart) / 1000).toFixed(2)) : undefined;
      const decodeDurationSecs = firstTok ? Number(Math.max(0.01, (turnEnd - firstTok) / 1000).toFixed(2)) : undefined;
      const totalDurationSecs = Number(Math.max(0.01, (turnEnd - turnStart) / 1000).toFixed(2));

      const finalCompletionTokens = serverCompletionTokens !== null
        ? serverCompletionTokens
        : Math.max(1, Math.round(finalMsg.length / 3.8));

      const promptToks = serverPromptTokens !== null ? serverPromptTokens : undefined;
      const totalToks = serverTokens !== null
        ? serverTokens
        : (promptToks ? promptToks + finalCompletionTokens : undefined);

      const tps = (decodeDurationSecs && decodeDurationSecs > 0)
        ? Number((finalCompletionTokens / decodeDurationSecs).toFixed(1))
        : undefined;

      if (finalMsg) {
        setMsgs((m) => [...m, {
          role: "assistant",
          content: finalMsg,
          tokensPerSec: tps && tps > 0 ? tps : undefined,
          tokens: finalCompletionTokens,
          promptTokens: promptToks,
          completionTokens: finalCompletionTokens,
          totalTokens: totalToks,
          ttftSecs,
          decodeDurationSecs,
          totalDurationSecs,
          durationSecs: decodeDurationSecs,
        }]);
      }
      setStreaming("");
      setLiveTps(0);
      setLiveTokens(0);
      setBusy(false);
      if (finalMsg && autoSpeak) {
        speakText(finalMsg);
      }
    }
  }

  async function send(text: string) {
    const q = text.trim();
    if (!q || busy || !project) return;
    setMsgs((m) => [...m, { role: "user", content: q }]);
    setInput("");

    if (!isWorkflow) {
      await streamAssistantTurn({
        message: q,
        thread_id: threadRef.current,
        model: selectedModel || undefined,
        thinking: thinkingMode,
        persona: activePersona,
      }, api.assistantStreamUrl(project.id));
    } else {
      await streamWorkflowRun(targetWorkflowId, q);
    }
  }

  async function decide(decision: "approve" | "reject") {
    if (!project || busy) return;
    setMsgs((m) => [...m, { role: "user", content: decision === "approve" ? "✓ Approved" : "✕ Rejected" }]);

    if (pendingRunInterrupt) {
      const { wid, runId } = pendingRunInterrupt;
      setPendingRunInterrupt(null);
      setBusy(true);
      try {
        await api.resumeRun(project.id, wid, runId, decision === "approve");
      } catch (e: any) {
        setMsgs((m) => [...m, { role: "assistant", content: `Failed to resume: ${e.message || e}` }]);
      } finally {
        setBusy(false);
      }
    } else {
      await streamAssistantTurn({
        thread_id: threadRef.current,
        decision,
        model: selectedModel || undefined,
        thinking: thinkingMode,
      }, api.assistantResumeUrl(project.id));
    }
  }

  function resetChat() {
    threadRef.current = newThreadId();
    setMsgs([]);
    setSteps([]);
    setTodos([]);
    setPendingApproval(null);
    setPendingRunInterrupt(null);
    setLiveThink(null);
    setLastServerTokens(null);
  }

  const handleTargetSelect = useCallback(
    (newTarget: string) => {
      if (newTarget === target) return;
      setTarget(newTarget);
      resetChat();
    },
    [target, setTarget]
  );

  const prevTargetRef = useRef(target);
  useEffect(() => {
    if (prevTargetRef.current !== target) {
      prevTargetRef.current = target;
      resetChat();
    }
  }, [target]);

  const starters = isToolManager ? [
    { label: "Audit Tools", prompt: "Audit all registered tools, their risk levels, and approval policies." },
    { label: "Diagnose Errors", prompt: "Diagnose recent execution errors and connection failures." },
    { label: "Check MCP Servers", prompt: "Explain the active MCP servers and the tools they expose." },
    { label: "Channels Status", prompt: "Summarize communication channels and their routing destinations." },
  ] : isCurator ? [
    { label: "Audit facts", prompt: "Audit all durable facts you have stored about me and this system." },
    { label: "Check hardware", prompt: "What hardware specifications, RAM, and models do you have registered?" },
    { label: "Graph entities", prompt: "What entities and relationships are stored in the knowledge graph?" },
    { label: "Audit conflicts", prompt: "Audit conflicting or outdated facts across vector and relational stores." },
  ] : isGraphManager ? [
    { label: "List entities", prompt: "What entities are registered in the knowledge graph?" },
    { label: "Check relations", prompt: "Explain the relationships and ontology connections in the graph." },
    { label: "Graph stats", prompt: "Summarize the size and density of the knowledge graph." },
    { label: "Recent nodes", prompt: "What new graph nodes were learned recently?" },
  ] : isIntentRouter ? [
    { label: "Test routing", prompt: "How would you route a request to control room lights?" },
    { label: "Explain intents", prompt: "What capabilities and tool sets can you route to?" },
  ] : isAgent ? [
    { label: "Agent Overview", prompt: `Explain your role and how you assist as ${selectedAgent?.name || "this sub-agent"}.` },
    { label: "System prompt", prompt: "What are your core directives and tools?" },
  ] : target === "assistant" ? [
    { label: "Build a Workflow", prompt: "Create a customer feedback triaging workflow." },
    { label: "Review Capabilities", prompt: "What tools and connectors are currently installed in Alberto?" },
    { label: "System Health", prompt: "Run a system health check and summarize memory items." },
    { label: "Add Knowledge", prompt: "Help me add home appliance manuals into the knowledge base." },
  ] : [
    { label: `Run ${selectedWf?.name || "Workflow"}`, prompt: "Run this workflow with default inputs." },
    { label: "Test Edge Cases", prompt: "Provide edge case inputs to test this automation graph." },
  ];

  const heroBg = isToolManager
    ? "linear-gradient(135deg, var(--accent, #6366f1), #4f46e5)"
    : isCurator
    ? "linear-gradient(135deg, #a855f7, #6366f1)"
    : isGraphManager
    ? "linear-gradient(135deg, #06b6d4, #3b82f6)"
    : isIntentRouter
    ? "linear-gradient(135deg, #f59e0b, #ef4444)"
    : isAgent
    ? "linear-gradient(135deg, #8b5cf6, #ec4899)"
    : isWorkflow
    ? "linear-gradient(135deg, #10b981, #06b6d4)"
    : "linear-gradient(135deg, var(--accent), #4f46e5)";

  const heroShadow = isToolManager
    ? "0 6px 20px rgba(99, 102, 241, 0.25)"
    : isCurator
    ? "0 6px 20px rgba(168, 85, 247, 0.25)"
    : isGraphManager
    ? "0 6px 20px rgba(6, 182, 212, 0.25)"
    : isIntentRouter
    ? "0 6px 20px rgba(245, 158, 11, 0.25)"
    : isAgent
    ? "0 6px 20px rgba(139, 92, 246, 0.25)"
    : isWorkflow
    ? "0 6px 20px rgba(16, 185, 129, 0.25)"
    : "0 6px 20px rgba(99, 102, 241, 0.25)";

  const heroIcon = isToolManager
    ? "tools"
    : isCurator
    ? "brain"
    : isGraphManager
    ? "workflows"
    : isIntentRouter
    ? "tools"
    : isAgent
    ? "bot"
    : isWorkflow
    ? "workflow"
    : "sparkles";

  const heroTitle = isToolManager
    ? "Integration Manager Sub-Agent"
    : isCurator
    ? "Memory Curator Sub-Agent"
    : isGraphManager
    ? "Knowledge Graph Manager Sub-Agent"
    : isIntentRouter
    ? "Intent Router Sub-Agent"
    : isAgent
    ? `${selectedAgent?.name || "Custom"} Sub-Agent`
    : isWorkflow
    ? `Ready to run ${selectedWf?.name || "workflow"}`
    : "How can I help you today?";

  const heroDesc = isToolManager
    ? "Inspects, tests, and manages tools, MCP clients, connectors, and communication channels. Helps diagnose execution policies and HITL gates."
    : isCurator
    ? "Curates, audits, and organizes your long-term memories and knowledge graph. Chats here also train Alberto's background memory."
    : isGraphManager
    ? "Inspects and explains entities, relationships, and ontology mappings in Alberto's graph."
    : isIntentRouter
    ? "Analyzes user requests, classifies intents, and determines automation routing."
    : isAgent
    ? (selectedAgent?.config?.description || "Sub-agent configured in this project.")
    : isWorkflow
    ? (selectedWf?.description || "Send inputs to execute this automation workflow live.")
    : `Alberto is your local AI Butler powered by ${activeModel?.name || "local LLM"}. Ask questions, build automations, or query system tools.`;

  const agentAvatarIcon = heroIcon;
  const agentAvatarColor = isToolManager
    ? "var(--accent, #6366f1)"
    : isCurator
    ? "#a855f7"
    : isGraphManager
    ? "#06b6d4"
    : isIntentRouter
    ? "#f59e0b"
    : isAgent
    ? "#8b5cf6"
    : isWorkflow
    ? "#10b981"
    : "var(--accent)";

  const agentAvatarBg = isToolManager
    ? "rgba(99, 102, 241, 0.12)"
    : isCurator
    ? "rgba(168, 85, 247, 0.12)"
    : isGraphManager
    ? "rgba(6, 182, 212, 0.12)"
    : isIntentRouter
    ? "rgba(245, 158, 11, 0.12)"
    : isAgent
    ? "rgba(139, 92, 246, 0.12)"
    : "var(--bg-2)";

  const agentAvatarBorder = isToolManager
    ? "1px solid rgba(99, 102, 241, 0.3)"
    : isCurator
    ? "1px solid rgba(168, 85, 247, 0.3)"
    : isGraphManager
    ? "1px solid rgba(6, 182, 212, 0.3)"
    : isIntentRouter
    ? "1px solid rgba(245, 158, 11, 0.3)"
    : isAgent
    ? "1px solid rgba(139, 92, 246, 0.3)"
    : "1px solid var(--line)";

  const filteredConvos = convos.filter((c) => {
    if (!convoSearch.trim()) return true;
    const q = convoSearch.toLowerCase();
    return (c.preview || "").toLowerCase().includes(q) || c.thread_id.toLowerCase().includes(q);
  });

  // Context size consumption calculation
  const maxTokens = activeModel?.ctx_tokens || (activeModel?.ctx ? (parseInt(activeModel.ctx, 10) * 1024 || 32768) : 32768);
  const baseOverhead = thinkingMode ? 4500 : 150;
  const messagesChars = useMemo(() => {
    let count = 0;
    for (const m of msgs) {
      count += (m.content?.length || 0) + (m.thinking?.length || 0) + 16;
    }
    if (streaming) count += streaming.length;
    return count;
  }, [msgs, streaming]);
  const estimatedMsgTokens = Math.round(messagesChars / 3.8);
  const consumedTokens = Math.max(lastServerTokens || 0, baseOverhead + estimatedMsgTokens);
  const pctUsed = Math.min(100, Math.round((consumedTokens / maxTokens) * 100));

  function formatTokens(toks: number): string {
    if (toks >= 1_000_000) return `${(toks / 1_000_000).toFixed(1)}M`;
    if (toks >= 1_000) return `${(toks / 1_000).toFixed(1)}k`;
    return `${toks}`;
  }

  // Compaction logic (Auto-compaction on >80% or manual click)
  const compactConversation = useCallback(() => {
    const uncompacted = msgs.filter((m) => m.role !== "compaction");
    if (uncompacted.length < 2) return;
    const keepCount = Math.max(1, Math.min(4, Math.floor(uncompacted.length / 2)));
    const turnsToArchive = uncompacted.slice(0, uncompacted.length - keepCount);
    const recentTurns = uncompacted.slice(uncompacted.length - keepCount);
    if (turnsToArchive.length === 0) return;
    const saved = Math.round(turnsToArchive.reduce((acc, m) => acc + (m.content.length + (m.thinking?.length || 0) + 16), 0) / 3.8);
    const userTopics = turnsToArchive
      .filter((m) => m.role === "user")
      .map((m) => `"${m.content.slice(0, 40).trim()}${m.content.length > 40 ? "…" : ""}"`)
      .slice(0, 3)
      .join(", ");
    const summary = `Archived ${turnsToArchive.length} conversation turns into context checkpoint. Topics covered: ${userTopics || "Prior conversation"}. Key state, decisions, and platform schemas preserved in working memory.`;
    const compactionItem: ChatMsg = {
      role: "compaction",
      content: summary,
      compactedCount: turnsToArchive.length,
      tokensSaved: saved,
      compactedTurns: turnsToArchive.map((t) => ({ role: t.role, content: t.content })),
    };
    setMsgs([compactionItem, ...recentTurns]);
    setLastServerTokens(null);
    setExpandedCompaction(null);
  }, [msgs]);

  // Automatically compact when context consumption reaches >= 80%
  useEffect(() => {
    if (pctUsed >= 80 && !busy && msgs.filter((m) => m.role !== "compaction").length >= 2) {
      compactConversation();
    }
  }, [pctUsed, busy, msgs, compactConversation]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", width: "100%", minHeight: 0, overflow: "hidden", position: "relative" }}>
      
      {/* Top Header Bar */}
      <div className="row spread" style={{ height: 44, flex: "none", borderBottom: "1px solid var(--line)", padding: "0 14px", alignItems: "center", background: "var(--bg-1)" }}>
        
        {/* Left: Target & Model */}
        <div className="row gap2" style={{ alignItems: "center", minWidth: 0 }}>
          {/* Target Selector / Persona Badge */}
          {persona === "memory_curator" ? (
            <div
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                height: 26,
                padding: "0 10px",
                fontSize: 12,
                fontWeight: 600,
                background: "rgba(168, 85, 247, 0.1)",
                border: "1px solid rgba(168, 85, 247, 0.3)",
                borderRadius: 5,
                color: "#c084fc",
              }}
              title="Memory Curator Sub-Agent: inspects and curates durable facts"
            >
              <Icon name="brain" size={13} style={{ color: "#a855f7" }} />
              <span>Memory Curator</span>
              <span
                style={{
                  fontSize: 9.5,
                  fontWeight: 700,
                  padding: "1px 5px",
                  borderRadius: 4,
                  background: "rgba(168, 85, 247, 0.2)",
                  color: "#d8b4fe",
                  letterSpacing: "0.04em",
                }}
              >
                SUB-AGENT
              </span>
            </div>
          ) : persona === "tool_manager" || persona === "integration_manager" ? (
            <div
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                height: 26,
                padding: "0 10px",
                fontSize: 12,
                fontWeight: 600,
                background: "rgba(99, 102, 241, 0.1)",
                border: "1px solid rgba(99, 102, 241, 0.3)",
                borderRadius: 5,
                color: "var(--accent, #6366f1)",
              }}
              title="Integration Manager Sub-Agent: inspects and tests tools and channels"
            >
              <Icon name="tools" size={13} style={{ color: "var(--accent, #6366f1)" }} />
              <span>Integration Manager</span>
              <span
                style={{
                  fontSize: 9.5,
                  fontWeight: 700,
                  padding: "1px 5px",
                  borderRadius: 4,
                  background: "rgba(99, 102, 241, 0.2)",
                  color: "var(--accent, #6366f1)",
                  letterSpacing: "0.04em",
                }}
              >
                SUB-AGENT
              </span>
            </div>
          ) : (
            <div ref={agentDropdownRef} style={{ position: "relative", display: "inline-block" }}>
              <button
                type="button"
                onClick={() => setAgentDropdownOpen((o) => !o)}
                style={{
                  height: 28,
                  padding: "0 10px 0 8px",
                  fontSize: 12,
                  fontWeight: 600,
                  background: agentDropdownOpen ? "var(--bg-0)" : "var(--bg-2)",
                  border: agentDropdownOpen ? "1px solid var(--accent)" : "1px solid var(--line)",
                  borderRadius: 6,
                  color: "var(--fg-0)",
                  cursor: "pointer",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 7,
                  boxShadow: agentDropdownOpen ? "0 0 0 2px rgba(99, 102, 241, 0.15)" : "none",
                  transition: "all 0.15s ease",
                }}
              >
                <div
                  style={{
                    width: 18,
                    height: 18,
                    borderRadius: 4,
                    background: `${activeTargetInfo.color}20`,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flexShrink: 0,
                  }}
                >
                  <Icon name={activeTargetInfo.icon} size={11} style={{ color: activeTargetInfo.color }} />
                </div>
                <span style={{ maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {activeTargetInfo.name}
                </span>
                <span
                  style={{
                    fontSize: 9,
                    fontWeight: 700,
                    padding: "1px 5px",
                    borderRadius: 3,
                    background: `${activeTargetInfo.color}18`,
                    color: activeTargetInfo.color,
                    letterSpacing: "0.03em",
                  }}
                >
                  {activeTargetInfo.badge}
                </span>
                <Icon
                  name="chevdown"
                  size={11}
                  style={{
                    color: "var(--fg-2)",
                    transform: agentDropdownOpen ? "rotate(180deg)" : "none",
                    transition: "transform 0.15s ease",
                    marginLeft: 2,
                  }}
                />
              </button>

              {agentDropdownOpen && (
                <div
                  style={{
                    position: "absolute",
                    top: "calc(100% + 4px)",
                    left: 0,
                    width: 290,
                    background: "var(--bg-1)",
                    border: "1px solid var(--line-strong)",
                    borderRadius: 8,
                    boxShadow: "0 8px 24px rgba(0,0,0,0.35)",
                    zIndex: 100,
                    padding: "6px",
                    display: "flex",
                    flexDirection: "column",
                    gap: 2,
                  }}
                >
                  {/* SECTION 1: MAIN AGENT */}
                  <div style={{ padding: "4px 8px 2px", fontSize: 10, fontWeight: 700, color: "var(--fg-2)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    Main Agent
                  </div>
                  <div
                    role="button"
                    tabIndex={0}
                    onClick={() => {
                      handleTargetSelect("assistant");
                      setAgentDropdownOpen(false);
                    }}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      padding: "7px 8px",
                      borderRadius: 6,
                      cursor: "pointer",
                      background: target === "assistant" ? "var(--bg-2)" : "transparent",
                      transition: "background 0.1s ease",
                    }}
                    onMouseEnter={(e) => {
                      if (target !== "assistant") e.currentTarget.style.background = "var(--bg-2)";
                    }}
                    onMouseLeave={(e) => {
                      if (target !== "assistant") e.currentTarget.style.background = "transparent";
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                      <div
                        style={{
                          width: 24,
                          height: 24,
                          borderRadius: 5,
                          background: "linear-gradient(135deg, var(--accent), #4f46e5)",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          color: "#fff",
                          flexShrink: 0,
                        }}
                      >
                        <Icon name="sparkles" size={13} />
                      </div>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontWeight: 600, fontSize: 12 }}>Alberto (Master Agent)</div>
                        <div className="fg-2" style={{ fontSize: 10.5, lineHeight: "13px" }}>
                          Primary coordinator · tools & reasoning
                        </div>
                      </div>
                    </div>
                    {target === "assistant" && (
                      <Icon name="check" size={13} style={{ color: "var(--accent)", flexShrink: 0 }} />
                    )}
                  </div>

                  <div style={{ height: 1, background: "var(--line)", margin: "4px 0" }} />

                  {/* SECTION 2: SUB-AGENTS */}
                  <div style={{ padding: "4px 8px 2px", fontSize: 10, fontWeight: 700, color: "var(--fg-2)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    Sub-Agents ({effectiveAgents.length})
                  </div>
                  {effectiveAgents.map((a) => {
                    const aKey = a.system_key || a.id;
                    const targetVal = `agent:${aKey}`;
                    const isSelected = target === targetVal || (aKey === "memory_curator" && isCurator) || (aKey === "graph_manager" && isGraphManager) || (aKey === "intent_router" && isIntentRouter);
                    const iconName = aKey === "memory_curator" ? "brain" : aKey === "graph_manager" ? "workflows" : aKey === "intent_router" ? "tools" : "bot";
                    const iconColor = aKey === "memory_curator" ? "#a855f7" : aKey === "graph_manager" ? "#06b6d4" : aKey === "intent_router" ? "#f59e0b" : "var(--io-control)";
                    const desc = a.config?.description || (aKey === "memory_curator" ? "Curates durable facts & audits conflicts" : aKey === "graph_manager" ? "Knowledge graph ontology & relations" : aKey === "intent_router" ? "Query classification & intent routing" : "Custom project sub-agent");

                    return (
                      <div
                        key={a.id || aKey}
                        role="button"
                        tabIndex={0}
                        onClick={() => {
                          handleTargetSelect(targetVal);
                          setAgentDropdownOpen(false);
                        }}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          padding: "7px 8px",
                          borderRadius: 6,
                          cursor: "pointer",
                          background: isSelected ? "var(--bg-2)" : "transparent",
                          transition: "background 0.1s ease",
                        }}
                        onMouseEnter={(e) => {
                          if (!isSelected) e.currentTarget.style.background = "var(--bg-2)";
                        }}
                        onMouseLeave={(e) => {
                          if (!isSelected) e.currentTarget.style.background = "transparent";
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                          <div
                            style={{
                              width: 24,
                              height: 24,
                              borderRadius: 5,
                              background: `${iconColor}18`,
                              border: `1px solid ${iconColor}33`,
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "center",
                              color: iconColor,
                              flexShrink: 0,
                            }}
                          >
                            <Icon name={iconName} size={13} />
                          </div>
                          <div style={{ minWidth: 0 }}>
                            <div style={{ fontWeight: 600, fontSize: 12 }}>{a.name}</div>
                            <div className="fg-2" style={{ fontSize: 10.5, lineHeight: "13px" }}>
                              {desc}
                            </div>
                          </div>
                        </div>
                        {isSelected && (
                          <Icon name="check" size={13} style={{ color: iconColor, flexShrink: 0 }} />
                        )}
                      </div>
                    );
                  })}

                  {/* SECTION 3: WORKFLOWS */}
                  {workflows.length > 0 && (
                    <>
                      <div style={{ height: 1, background: "var(--line)", margin: "4px 0" }} />
                      <div style={{ padding: "4px 8px 2px", fontSize: 10, fontWeight: 700, color: "var(--fg-2)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                        Workflows ({workflows.length})
                      </div>
                      {workflows.map((w) => {
                        const targetVal = `workflow:${w.id}`;
                        const isSelected = target === targetVal || target === w.id;
                        return (
                          <div
                            key={w.id}
                            role="button"
                            tabIndex={0}
                            onClick={() => {
                              handleTargetSelect(targetVal);
                              setAgentDropdownOpen(false);
                            }}
                            style={{
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "space-between",
                              padding: "6px 8px",
                              borderRadius: 6,
                              cursor: "pointer",
                              background: isSelected ? "var(--bg-2)" : "transparent",
                              transition: "background 0.1s ease",
                            }}
                            onMouseEnter={(e) => {
                              if (!isSelected) e.currentTarget.style.background = "var(--bg-2)";
                            }}
                            onMouseLeave={(e) => {
                              if (!isSelected) e.currentTarget.style.background = "transparent";
                            }}
                          >
                            <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                              <div
                                style={{
                                  width: 22,
                                  height: 22,
                                  borderRadius: 4,
                                  background: "rgba(16, 185, 129, 0.15)",
                                  display: "flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                  color: "#10b981",
                                  flexShrink: 0,
                                }}
                              >
                                <Icon name="workflow" size={12} />
                              </div>
                              <span style={{ fontWeight: 500, fontSize: 11.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                {w.name}
                              </span>
                            </div>
                            {isSelected && (
                              <Icon name="check" size={12} style={{ color: "#10b981", flexShrink: 0 }} />
                            )}
                          </div>
                        );
                      })}
                    </>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Model Selector Pill */}
          {!isWorkflow && (
            <div style={{ position: "relative", display: "inline-flex", alignItems: "center" }}>
              <div
                style={{
                  position: "absolute",
                  left: 8,
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background: activeModel ? "var(--ok, #10b981)" : "var(--fg-2)",
                  pointerEvents: "none",
                }}
              />
              <select
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
                style={{
                  height: 26,
                  padding: "0 22px 0 20px",
                  fontSize: 11.5,
                  fontWeight: 500,
                  background: "var(--bg-2)",
                  border: "1px solid var(--line)",
                  borderRadius: 5,
                  color: "var(--fg-0)",
                  cursor: "pointer",
                  appearance: "none",
                  outline: "none",
                  maxWidth: 160,
                }}
                title="Active inference model"
              >
                {models.length === 0 ? (
                  <option value="">No models registered</option>
                ) : (
                  models.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name} {m.is_default ? "★" : ""}
                    </option>
                  ))
                )}
              </select>
              <Icon name="chevdown" size={11} style={{ position: "absolute", right: 7, pointerEvents: "none", color: "var(--fg-2)" }} />
            </div>
          )}
        </div>

        {/* Right: Actions */}
        <div className="row gap1" style={{ alignItems: "center", flexShrink: 0 }}>
          {/* Voice Butler Toggle */}
          <button
            type="button"
            className="iconbtn"
            style={{
              height: 28,
              width: 28,
              padding: 0,
              borderRadius: 4,
              border: "1px solid var(--line)",
              background: autoSpeak ? "var(--accent)" : "var(--bg-2)",
              color: autoSpeak ? "#fff" : "var(--fg-2)",
            }}
            onClick={() => {
              if (autoSpeak) {
                if (typeof window !== "undefined") window.speechSynthesis?.cancel();
                setCurrentlySpeaking(null);
              }
              setAutoSpeak((s) => !s);
            }}
            title={autoSpeak ? "Voice Butler: ON (auto-reads responses)" : "Voice Butler: OFF (click to enable)"}
          >
            <Icon name={autoSpeak ? "volume" : "volume-x"} size={13} />
          </button>

          {/* Steps */}
          {steps.length > 0 && (
            <button
              className="btn btn-secondary btn-xs"
              onClick={() => setStepsOpen((o) => !o)}
              style={{ height: 28, fontSize: 11, padding: "0 6px", gap: 3 }}
              title="View execution steps"
            >
              <Icon name="tools" size={11} />
              <span>{steps.length}</span>
            </button>
          )}

          {/* Conversations Drawer */}
          <button
            className={`iconbtn${convosOpen ? " active" : ""}`}
            title="Browse past conversations"
            onClick={() => {
              if (!convosOpen) loadConversations();
              setConvosOpen((o) => !o);
            }}
            style={{
              height: 28,
              width: 28,
              padding: 0,
              borderRadius: 4,
              border: "1px solid var(--line)",
              background: convosOpen ? "var(--bg-3)" : "var(--bg-2)",
            }}
          >
            <Icon name="inbox" size={13} />
          </button>

          {/* New Chat */}
          <button
            className="iconbtn"
            title="Start new conversation"
            onClick={resetChat}
            disabled={busy || msgs.length === 0}
            style={{
              height: 28,
              width: 28,
              padding: 0,
              borderRadius: 4,
              border: "1px solid var(--line)",
              background: "var(--bg-2)",
              opacity: (busy || msgs.length === 0) ? 0.35 : 1,
            }}
          >
            <Icon name="refresh" size={13} />
          </button>
        </div>
      </div>

      {/* Main transcript scroll area (vertically contained, only messages scroll) */}
      <div
        ref={scrollRef}
        style={{
          flex: "1 1 0%",
          minHeight: 0,
          overflowY: "auto",
          overflowX: "hidden",
          padding: "16px 14px",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: 16 }}>
          
          {msgs.length === 0 && !streaming && (
            <div className="fade-in col center" style={{ padding: "36px 0 20px", textAlign: "center", gap: 12 }}>
              <div
                style={{
                  width: 44,
                  height: 44,
                  borderRadius: 12,
                  background: heroBg,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "#fff",
                  boxShadow: heroShadow,
                }}
              >
                <Icon name={heroIcon} size={22} />
              </div>
              <div>
                <h1 style={{ fontSize: 19, fontWeight: 700, margin: "0 0 5px", letterSpacing: "-0.02em" }}>
                  {heroTitle}
                </h1>
                <p className="fg-2" style={{ margin: 0, maxWidth: 440, fontSize: 13, lineHeight: "19px" }}>
                  {heroDesc}
                </p>
              </div>

              {/* Minimalist prompt chips */}
              <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: 8, maxWidth: 540, width: "100%", marginTop: 6 }}>
                {starters.map((s, i) => (
                  <button
                    key={i}
                    onClick={() => send(s.prompt)}
                    style={{
                      padding: "6px 12px",
                      borderRadius: 16,
                      border: "1px solid var(--line)",
                      background: "var(--bg-2)",
                      color: "var(--fg-1)",
                      fontSize: 12,
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                      transition: "all 0.15s ease",
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.borderColor = "var(--accent)";
                      e.currentTarget.style.color = "var(--fg-0)";
                      e.currentTarget.style.background = "var(--bg-3)";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.borderColor = "var(--line)";
                      e.currentTarget.style.color = "var(--fg-1)";
                      e.currentTarget.style.background = "var(--bg-2)";
                    }}
                  >
                    <Icon name={heroIcon} size={11} style={{ color: agentAvatarColor }} />
                    <span style={{ fontWeight: 600 }}>{s.label}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {msgs.map((m, i) => {
            if (m.role === "compaction") {
              const isOpen = expandedCompaction === i;
              return (
                <div key={i} className="fade-in col" style={{ margin: "10px 0", gap: 6 }}>
                  {/* Minimal Timeline Divider with interactive pill */}
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <div style={{ flex: 1, height: 1, background: "var(--line)" }} />
                    <button
                      type="button"
                      onClick={() => setExpandedCompaction(isOpen ? null : i)}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                        padding: "3px 10px",
                        borderRadius: 12,
                        background: "var(--bg-2)",
                        border: "1px solid var(--line)",
                        fontSize: 11,
                        color: "var(--fg-2)",
                        cursor: "pointer",
                        transition: "all 0.15s ease",
                        whiteSpace: "nowrap",
                        flexShrink: 0,
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.borderColor = "var(--accent)";
                        e.currentTarget.style.color = "var(--fg-0)";
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.borderColor = "var(--line)";
                        e.currentTarget.style.color = "var(--fg-2)";
                      }}
                      title="Click to toggle archived turns"
                    >
                      <Icon name="archive" size={12} style={{ color: "var(--accent)" }} />
                      <span style={{ fontWeight: 600, color: "var(--fg-1)" }}>Context Compacted</span>
                      {m.tokensSaved ? (
                        <span style={{ color: "var(--ok, #10b981)", fontWeight: 600, fontSize: 10.5 }}>
                          +{m.tokensSaved.toLocaleString()} toks
                        </span>
                      ) : null}
                      <span style={{ opacity: 0.6 }}>· {m.compactedCount || 2} turns</span>
                      <Icon name={isOpen ? "chevup" : "chevdown"} size={11} style={{ opacity: 0.7 }} />
                    </button>
                    <div style={{ flex: 1, height: 1, background: "var(--line)" }} />
                  </div>

                  {/* Collapsible Details Drawer */}
                  {isOpen && (
                    <div
                      className="fade-in col"
                      style={{
                        margin: "4px 24px 0",
                        padding: "10px 14px",
                        borderRadius: 8,
                        background: "var(--bg-2)",
                        border: "1px solid var(--line)",
                        fontSize: 12,
                        gap: 8,
                        maxHeight: 220,
                        overflowY: "auto",
                      }}
                    >
                      <div className="fg-2" style={{ fontSize: 11, fontStyle: "italic", borderBottom: "1px solid var(--line)", paddingBottom: 6 }}>
                        {m.content}
                      </div>
                      {m.compactedTurns?.map((t, ti) => (
                        <div key={ti} style={{ fontSize: 11.5, lineHeight: "17px" }}>
                          <span style={{ fontWeight: 600, color: t.role === "user" ? "var(--accent)" : "var(--fg-0)" }}>
                            {t.role === "user" ? "You" : "Alberto"}:
                          </span>{" "}
                          <span className="fg-1">{t.content.slice(0, 260)}{t.content.length > 260 ? "…" : ""}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            }

            return (
              <div key={i} className="col" style={{ gap: 6 }}>
                {m.thinking && (
                  <div style={{ paddingLeft: 40, marginBottom: 4 }}>
                    <button
                      onClick={() => setOpenThought(openThought === i ? null : i)}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                        background: "none",
                        border: "none",
                        cursor: "pointer",
                        padding: 0,
                        color: "var(--fg-2)",
                        fontSize: 12,
                        fontFamily: "var(--font-ui)",
                      }}
                    >
                      <Icon name={openThought === i ? "chevdown" : "chevright"} size={13} />
                      <span>Thought for {m.thinkSecs || 1}s</span>
                    </button>
                    {openThought === i && (
                      <div className="card fade-in" style={{ marginTop: 6, padding: "10px 14px", fontSize: 12.5, lineHeight: "20px", color: "var(--fg-1)", background: "var(--bg-2)", borderLeft: "3px solid var(--accent)", borderRadius: 6, whiteSpace: "pre-wrap" }}>
                        {m.thinking}
                      </div>
                    )}
                  </div>
                )}

                <div className="row" style={{ gap: 10, alignItems: "flex-start", justifyContent: m.role === "user" ? "flex-end" : "flex-start" }}>
                  {m.role === "assistant" && (
                    <div style={{ width: 26, height: 26, borderRadius: "50%", background: agentAvatarBg, border: agentAvatarBorder, display: "flex", alignItems: "center", justifyContent: "center", color: agentAvatarColor, flex: "none", marginTop: 2 }}>
                      <Icon name={agentAvatarIcon} size={13} />
                    </div>
                  )}
                  <div
                    style={{
                      maxWidth: m.role === "user" ? "80%" : "92%",
                      padding: m.role === "user" ? "8px 14px" : "2px 0",
                      borderRadius: m.role === "user" ? 10 : 0,
                      fontSize: 13.8,
                      lineHeight: "22px",
                      background: m.role === "user" ? "var(--bg-2)" : "transparent",
                      border: m.role === "user" ? "1px solid var(--line)" : "none",
                      color: "var(--fg-0)",
                      position: "relative",
                    }}
                  >
                    <Markdown>{m.content}</Markdown>
                    {m.role === "assistant" && (
                      <div className="row gap1" style={{ marginTop: 6, alignItems: "center" }}>
                        <button
                          type="button"
                          className="iconbtn"
                          onClick={() => navigator.clipboard.writeText(m.content)}
                          title="Copy response"
                          style={{ padding: "2px 6px", fontSize: 11, gap: 4, height: 22, opacity: 0.65 }}
                        >
                          <Icon name="copy" size={11} />
                          <span style={{ fontSize: 11 }}>Copy</span>
                        </button>
                        <button
                          type="button"
                          className="iconbtn"
                          onClick={() => speakText(m.content, i)}
                          title={currentlySpeaking === i ? "Stop speaking" : "Read aloud (Voice)"}
                          style={{ padding: "2px 6px", fontSize: 11, gap: 4, height: 22, opacity: 0.65, color: currentlySpeaking === i ? "var(--accent)" : "inherit" }}
                        >
                          <Icon name={currentlySpeaking === i ? "volume-x" : "volume"} size={11} />
                          <span style={{ fontSize: 11 }}>{currentlySpeaking === i ? "Stop" : "Voice"}</span>
                        </button>
                        <TokenMetricsBadge msg={m} />
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}

          {/* Waiting for first token / thinking indicator */}
          {busy && !streaming && !liveThink && (
            <div className="row fade-in" style={{ gap: 10, alignItems: "center" }}>
              <div
                style={{
                  width: 26,
                  height: 26,
                  borderRadius: "50%",
                  background: agentAvatarBg,
                  border: agentAvatarBorder,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: agentAvatarColor,
                  flex: "none",
                }}
              >
                <Icon name={agentAvatarIcon} size={13} />
              </div>
              <div
                className="row gap2"
                style={{
                  padding: "8px 14px",
                  borderRadius: 8,
                  background: "var(--bg-2)",
                  border: "1px solid var(--line)",
                  alignItems: "center",
                }}
              >
                <div className="row gap1" style={{ alignItems: "center", marginRight: 6 }}>
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                </div>
                <span className="fg-2" style={{ fontSize: 12, fontWeight: 500 }}>
                  {currentTool ? `Running ${currentTool}…` : isCurator ? "Auditing memory…" : isGraphManager ? "Traversing graph…" : isIntentRouter ? "Routing intent…" : !isWorkflow ? "Thinking…" : "Executing automation…"}
                  {busySecs > 1 && <span style={{ opacity: 0.65, marginLeft: 6 }}>({busySecs}s)</span>}
                </span>
              </div>
            </div>
          )}

          {/* Real-time Thinking Ticker */}
          {liveThink !== null && (
            <div className="row gap2 fade-in" style={{ paddingLeft: 36, alignItems: "flex-start" }}>
              <div style={{ width: 14, height: 14, marginTop: 4, borderRadius: "50%", border: "2px solid var(--accent)", borderTopColor: "transparent" }} className="spin" />
              <div ref={thinkRef} style={{ maxHeight: 90, overflowY: "auto", fontSize: 12.5, color: "var(--fg-2)", fontStyle: "italic", lineHeight: "19px" }}>
                {liveThink || "Thinking…"}
              </div>
            </div>
          )}

          {/* Current active tool */}
          {currentTool && (
            <div className="row gap2 fade-in" style={{ paddingLeft: 36, alignItems: "center", color: "var(--accent)", fontSize: 12.5 }}>
              <Icon name="tools" size={13} className="spin" />
              <span>Running {currentTool}…</span>
            </div>
          )}

          {/* Streaming response bubble */}
          {streaming && (
            <div className="row" style={{ gap: 10, alignItems: "flex-start" }}>
              <div style={{ width: 26, height: 26, borderRadius: "50%", background: agentAvatarBg, border: agentAvatarBorder, display: "flex", alignItems: "center", justifyContent: "center", color: agentAvatarColor, flex: "none", marginTop: 2 }}>
                <Icon name={agentAvatarIcon} size={13} />
              </div>
              <div style={{ maxWidth: "92%", padding: "2px 0", fontSize: 13.8, lineHeight: "22px" }}>
                <Markdown>{streaming}</Markdown>
                {busy && (
                  <span
                    style={{
                      display: "inline-block",
                      width: 6,
                      height: 13,
                      marginLeft: 4,
                      background: "var(--accent)",
                      verticalAlign: "middle",
                      animation: "blink 0.9s infinite",
                    }}
                  />
                )}
                {liveTps > 0 && (
                  <div
                    className="row gap1 fade-in"
                    style={{
                      marginTop: 6,
                      alignItems: "center",
                      fontSize: 11,
                      color: "var(--fg-2)",
                      opacity: 0.85,
                    }}
                  >
                    <Icon name="bolt" size={11} style={{ color: "var(--accent)" }} />
                    <span style={{ fontWeight: 600, color: "var(--fg-1)" }}>{liveTps} tok/s</span>
                    <span style={{ opacity: 0.6 }}>· ~{liveTokens} tokens</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Human-in-the-Loop Interactive Approval Card */}
          {(pendingApproval || pendingRunInterrupt) && (
            <div
              className="fade-in col"
              style={{
                border: "1.5px solid var(--warn, #f59e0b)",
                background: "linear-gradient(135deg, rgba(245, 158, 11, 0.08), var(--bg-1))",
                padding: "16px 18px",
                borderRadius: 10,
                boxShadow: "0 4px 16px rgba(245, 158, 11, 0.15)",
                gap: 12,
              }}
            >
              <div className="row spread" style={{ alignItems: "center" }}>
                <div className="row gap2" style={{ alignItems: "center" }}>
                  <div
                    style={{
                      width: 28,
                      height: 28,
                      borderRadius: 6,
                      background: "rgba(245, 158, 11, 0.18)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: "var(--warn, #f59e0b)",
                    }}
                  >
                    <Icon name="shield-check" size={17} />
                  </div>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: 13.5, color: "var(--fg-0)" }}>
                      Action Paused · Approval Required
                    </div>
                    <div className="fg-2" style={{ fontSize: 11 }}>
                      Alberto requested execution of a privileged action
                    </div>
                  </div>
                </div>
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 700,
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                    padding: "3px 8px",
                    borderRadius: 4,
                    background: "rgba(245, 158, 11, 0.15)",
                    color: "var(--warn, #f59e0b)",
                    border: "1px solid rgba(245, 158, 11, 0.3)",
                  }}
                >
                  Pending Human Decision
                </span>
              </div>

              <div
                style={{
                  fontSize: 13,
                  lineHeight: "20px",
                  color: "var(--fg-1)",
                  padding: "10px 12px",
                  background: "var(--bg-2)",
                  borderRadius: 6,
                  border: "1px solid var(--line)",
                  fontFamily: "var(--font-mono, monospace)",
                }}
              >
                {pendingApproval || "The automated agent paused before executing a mutating platform tool."}
              </div>

              <div className="row spread" style={{ alignItems: "center", paddingTop: 4 }}>
                <div className="fg-2" style={{ fontSize: 11.5 }}>
                  Review parameters before continuing execution.
                </div>
                <div className="row gap2">
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => decide("reject")}
                    disabled={busy}
                    style={{
                      color: "var(--err, #ef4444)",
                      borderColor: "rgba(239, 68, 68, 0.3)",
                      fontWeight: 600,
                      gap: 4,
                    }}
                  >
                    <Icon name="x" size={12} />
                    <span>Reject Action</span>
                  </button>
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    onClick={() => decide("approve")}
                    disabled={busy}
                    style={{
                      background: "var(--ok, #10b981)",
                      borderColor: "var(--ok, #10b981)",
                      color: "#fff",
                      fontWeight: 600,
                      gap: 4,
                    }}
                  >
                    <Icon name="check" size={13} />
                    <span>Approve & Continue</span>
                  </button>
                </div>
              </div>
            </div>
          )}

        </div>
      </div>

      {/* Slide-over Conversations History Panel */}
      {convosOpen && (
        <div
          className="fade-in"
          style={{
            position: "absolute",
            top: 50,
            right: 0,
            bottom: 0,
            width: 320,
            background: "var(--bg-1)",
            borderLeft: "1px solid var(--line)",
            boxShadow: "var(--sh-pop)",
            zIndex: 30,
            display: "flex",
            flexDirection: "column",
          }}
        >
          <div className="row spread" style={{ padding: "12px 14px", borderBottom: "1px solid var(--line)", alignItems: "center" }}>
            <div className="row gap2" style={{ alignItems: "center" }}>
              <Icon name="inbox" size={16} style={{ color: "var(--accent)" }} />
              <span style={{ fontWeight: 600, fontSize: 13 }}>Conversations</span>
            </div>
            <button className="iconbtn" onClick={() => setConvosOpen(false)}>
              <Icon name="x" size={14} />
            </button>
          </div>

          <div style={{ padding: "8px 10px", borderBottom: "1px solid var(--line)" }}>
            <input
              className="input"
              value={convoSearch}
              onChange={(e) => setConvoSearch(e.target.value)}
              placeholder="Search conversations…"
              style={{ width: "100%", fontSize: 12, height: 30 }}
            />
          </div>

          <div className="scroll-y grow col" style={{ padding: 6, gap: 4 }}>
            {loadingConvos ? (
              <div className="fg-2 t-caption" style={{ padding: 20, textAlign: "center" }}>Loading history…</div>
            ) : filteredConvos.length === 0 ? (
              <div className="fg-2 t-caption" style={{ padding: 20, textAlign: "center" }}>No conversations found</div>
            ) : (
              filteredConvos.map((c) => (
                <div
                  key={c.thread_id}
                  onClick={() => openConversation(c)}
                  style={{
                    padding: "8px 10px",
                    borderRadius: 8,
                    cursor: "pointer",
                    background: c.thread_id === threadRef.current ? "var(--bg-3)" : "transparent",
                    border: "1px solid " + (c.thread_id === threadRef.current ? "var(--accent)" : "transparent"),
                    transition: "background 0.12s ease",
                  }}
                  onMouseEnter={(e) => {
                    if (c.thread_id !== threadRef.current) e.currentTarget.style.background = "var(--bg-2)";
                  }}
                  onMouseLeave={(e) => {
                    if (c.thread_id !== threadRef.current) e.currentTarget.style.background = "transparent";
                  }}
                >
                  <div className="truncate" style={{ fontSize: 12.5, fontWeight: 600, color: "var(--fg-0)" }}>
                    {c.preview || `Thread ${c.thread_id.slice(-6)}`}
                  </div>
                  <div className="row spread" style={{ marginTop: 4, fontSize: 11, color: "var(--fg-2)" }}>
                    <span>{c.turns} turn{c.turns === 1 ? "" : "s"}</span>
                    <span>{formatTime(c.last_activity || c.started_at)}</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* Steps Drawer Overlay */}
      {stepsOpen && (
        <div className="fade-in" style={{ position: "absolute", bottom: 84, right: 24, width: 320, maxHeight: 340, zIndex: 20, background: "var(--bg-1)", border: "1px solid var(--line)", borderRadius: 10, boxShadow: "var(--sh-pop)", display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <div className="row spread" style={{ padding: "10px 14px", borderBottom: "1px solid var(--line)", fontWeight: 600, fontSize: 13 }}>
            <span>Execution Steps ({steps.length})</span>
            <button className="iconbtn" onClick={() => setStepsOpen(false)}><Icon name="x" size={14} /></button>
          </div>
          <div className="scroll-y col" style={{ padding: 8, gap: 4, maxHeight: 280 }}>
            {steps.map((st, i) => (
              <div key={i} className="card" style={{ padding: "8px 10px", fontSize: 12 }}>
                <div className="row spread" style={{ cursor: "pointer" }} onClick={() => setExpandedStep(expandedStep === i ? null : i)}>
                  <div className="row gap2" style={{ alignItems: "center" }}>
                    <Icon name="tools" size={13} style={{ color: "var(--accent)" }} />
                    <span style={{ fontWeight: 600 }}>{st.name}</span>
                  </div>
                  {st.result && <Icon name={expandedStep === i ? "chevup" : "chevdown"} size={12} />}
                </div>
                {st.result && expandedStep === i && (
                  <pre style={{ marginTop: 6, fontSize: 11, background: "var(--bg-2)", padding: 6, borderRadius: 4, overflowX: "auto" }}>
                    {JSON.stringify(st.result, null, 2)}
                  </pre>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Unified Capsule Composer (Cursor / Claude style) */}
      <div style={{ flex: "none", padding: "10px 14px 12px", background: "var(--bg-1)", borderTop: "1px solid var(--line)" }}>
        <form
          onSubmit={(e) => { e.preventDefault(); send(input); }}
          style={{
            width: "100%",
            display: "flex",
            flexDirection: "column",
            background: "var(--bg-2)",
            border: "1px solid var(--line)",
            borderRadius: 10,
            padding: "8px 12px 6px",
            boxShadow: "0 1px 4px rgba(0,0,0,0.03)",
            transition: "border-color 0.15s ease, box-shadow 0.15s ease",
          }}
        >
            {/* Text input area */}
            <textarea
              ref={taRef}
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send(input);
                }
              }}
              placeholder={target === "assistant" ? "Ask Alberto anything..." : `Message ${selectedWf?.name || "workflow"}...`}
              style={{
                width: "100%",
                minHeight: 38,
                maxHeight: 180,
                border: "none",
                outline: "none",
                background: "transparent",
                color: "var(--fg-0)",
                fontSize: 13.5,
                lineHeight: "21px",
                fontFamily: "var(--font-ui)",
                resize: "none",
                padding: "2px 0 8px",
              }}
            />

            {/* Embedded Bottom Toolbar Tray */}
            <div className="row spread" style={{ alignItems: "center", borderTop: "1px solid rgba(255,255,255,0.04)", paddingTop: 6 }}>
              {/* Left tray tools */}
              <div className="row gap2" style={{ alignItems: "center" }}>
                {!isWorkflow && (
                  <>
                    {/* Thinking Mode Toggle */}
                    <button
                      type="button"
                      onClick={() => setThinkingMode((m) => !m)}
                      style={{
                        height: 24,
                        fontSize: 11,
                        borderRadius: 4,
                        padding: "0 8px",
                        gap: 4,
                        fontWeight: 600,
                        border: "1px solid var(--line)",
                        background: thinkingMode ? "var(--accent)" : "var(--bg-1)",
                        color: thinkingMode ? "#fff" : "var(--fg-2)",
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        transition: "all 0.12s ease",
                      }}
                      title={thinkingMode ? "Thinking: Deep Agent (click for Fast Butler)" : "Thinking: Fast Butler (click for Deep Agent)"}
                    >
                      <Icon name={thinkingMode ? "sparkles" : "bolt"} size={11} />
                      <span>{thinkingMode ? "Thinking: Deep" : "Fast"}</span>
                    </button>

                    {/* Context Meter Chip */}
                    <div
                      className="row gap1"
                      style={{
                        alignItems: "center",
                        fontSize: 11,
                        color: "var(--fg-2)",
                        height: 24,
                        padding: "0 7px",
                        borderRadius: 4,
                        border: "1px solid var(--line)",
                        background: "var(--bg-1)",
                        cursor: "default",
                      }}
                      title={`Context: ${consumedTokens.toLocaleString()} / ${maxTokens.toLocaleString()} tokens (${pctUsed}%)\n• Base prompt: ${baseOverhead.toLocaleString()} tokens\n• Chat turns: ~${estimatedMsgTokens.toLocaleString()} tokens`}
                    >
                      <Icon name="db" size={11} style={{ opacity: 0.7 }} />
                      <span style={{ fontWeight: 600, color: pctUsed > 80 ? "var(--warn)" : "var(--fg-1)" }}>
                        {formatTokens(consumedTokens)}
                      </span>
                      <div
                        style={{
                          width: 32,
                          height: 3,
                          borderRadius: 2,
                          background: "var(--bg-3)",
                          overflow: "hidden",
                          marginLeft: 3,
                          marginRight: 2,
                        }}
                      >
                        <div
                          style={{
                            height: "100%",
                            width: `${pctUsed}%`,
                            background: pctUsed > 85 ? "var(--err, #ef4444)" : pctUsed > 60 ? "var(--warn, #f59e0b)" : "var(--accent, #6366f1)",
                            transition: "width 0.3s ease",
                          }}
                        />
                      </div>
                      <span style={{ fontSize: 10, fontWeight: 700, color: pctUsed > 85 ? "var(--err)" : "var(--fg-2)" }}>
                        {pctUsed}%
                      </span>
                    </div>

                    {/* Live Generation Speed Badge */}
                    {busy && liveTps > 0 && (
                      <div
                        className="row gap1 fade-in"
                        style={{
                          alignItems: "center",
                          fontSize: 11,
                          color: "var(--accent)",
                          height: 24,
                          padding: "0 8px",
                          borderRadius: 4,
                          border: "1px solid rgba(99, 102, 241, 0.35)",
                          background: "rgba(99, 102, 241, 0.08)",
                          fontWeight: 600,
                          cursor: "default",
                        }}
                        title={`Live Generation Throughput: ${liveTps} tokens/sec`}
                      >
                        <Icon name="bolt" size={11} />
                        <span>{liveTps} tok/s</span>
                      </div>
                    )}

                    {/* Manual Compact Button */}
                    <button
                      type="button"
                      onClick={compactConversation}
                      disabled={msgs.filter((m) => m.role !== "compaction").length < 2}
                      style={{
                        height: 24,
                        fontSize: 11,
                        borderRadius: 4,
                        padding: "0 7px",
                        gap: 4,
                        border: "1px solid var(--line)",
                        background: "var(--bg-1)",
                        color: msgs.filter((m) => m.role !== "compaction").length >= 2 ? "var(--fg-1)" : "var(--fg-2)",
                        opacity: msgs.filter((m) => m.role !== "compaction").length >= 2 ? 1 : 0.45,
                        cursor: msgs.filter((m) => m.role !== "compaction").length >= 2 ? "pointer" : "not-allowed",
                        display: "flex",
                        alignItems: "center",
                      }}
                      title={msgs.filter((m) => m.role !== "compaction").length >= 2 ? "Compact conversation context" : "Compact requires at least 2 conversation turns"}
                    >
                      <Icon name="archive" size={11} style={{ color: "var(--accent)" }} />
                      <span>Compact</span>
                    </button>
                  </>
                )}
              </div>

              {/* Right tray buttons (Voice & Send/Stop) */}
              <div className="row gap1" style={{ alignItems: "center" }}>
                {/* Voice Dictation (Mic) */}
                <button
                  type="button"
                  onClick={toggleListening}
                  className="iconbtn"
                  title={isListening ? "Listening... click to stop" : "Voice dictation"}
                  style={{
                    width: 26,
                    height: 26,
                    borderRadius: 6,
                    color: isListening ? "var(--err, #ef4444)" : "var(--fg-2)",
                    background: isListening ? "rgba(239, 68, 68, 0.15)" : "transparent",
                    border: isListening ? "1px solid var(--err, #ef4444)" : "none",
                  }}
                >
                  <Icon name="mic" size={14} />
                </button>

                {/* Stop Generation or Send button */}
                {busy ? (
                  <button
                    type="button"
                    onClick={stopGenerating}
                    style={{
                      height: 26,
                      padding: "0 10px",
                      borderRadius: 6,
                      display: "flex",
                      alignItems: "center",
                      gap: 4,
                      background: "var(--err, #ef4444)",
                      color: "#fff",
                      border: "none",
                      cursor: "pointer",
                      fontSize: 11.5,
                      fontWeight: 600,
                    }}
                    title="Stop generation (Esc)"
                  >
                    <Icon name="stop" size={11} />
                    <span>Stop</span>
                  </button>
                ) : (
                  <button
                    type="submit"
                    disabled={!input.trim()}
                    style={{
                      width: 26,
                      height: 26,
                      padding: 0,
                      borderRadius: 6,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      background: input.trim() ? "var(--accent)" : "var(--bg-3)",
                      color: input.trim() ? "#fff" : "var(--fg-3)",
                      border: "none",
                      cursor: input.trim() ? "pointer" : "default",
                      transition: "background 0.12s ease",
                    }}
                    title="Send message (Enter)"
                  >
                    <Icon name="chevup" size={14} />
                  </button>
                )}
              </div>
            </div>
          </form>
        </div>
      </div>
  );
}
