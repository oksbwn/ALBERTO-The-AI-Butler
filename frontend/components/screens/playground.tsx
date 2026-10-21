"use client";
/* Playground - primary Automate experience: conversational workflow authoring with Automation Manager
   + visual graph preview + safe testing & approval + live SSE workflow execution testing.
   Matches the split workbench layout of Knowledge and Integrations Playgrounds. */

import "@xyflow/react/dist/style.css";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
  type Node,
} from "@xyflow/react";
import Mustache from "mustache";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  type ApprovalResult,
  type AuthoringSession,
  type ComponentT,
  type SafeTestResult,
  type Workflow,
} from "@/lib/api";
import { type Part } from "@/lib/chat-parts";
import { buildNodeLabels, fmtUSD } from "@/lib/data";
import { runWorkflowSSE, type StreamActivity } from "@/lib/run-stream";
import { ComponentRenderer } from "../component-renderer";
import { Icon } from "../icons";
import { Markdown } from "../markdown";
import { StatusPill } from "../primitives";
import { ChatScreen } from "./chat";

interface ChatMsg {
  role: "user" | "assistant";
  content?: string;
  parts?: Part[];
}
interface Step {
  node: string;
}

export function PlaygroundScreen({
  project,
  onOpenWorkflow,
  onNav,
  defaultTab = "ai_authoring",
}: {
  project: any;
  onOpenWorkflow?: (w: Workflow) => void;
  onNav?: (screen: string) => void;
  defaultTab?: "ai_authoring" | "workflow_test";
}) {
  // Draggable split percentage: defaults to 50% (half half), identical to Knowledge and Integrations Playgrounds
  const [splitPct, setSplitPct] = useState(50);
  const containerRef = useRef<HTMLDivElement>(null);
  const isDraggingRef = useRef(false);

  // Handle draggable divider
  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    isDraggingRef.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    const handleMouseMove = (moveEvent: MouseEvent) => {
      if (!isDraggingRef.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const rawPct = ((moveEvent.clientX - rect.left) / rect.width) * 100;
      // Clamp between 20% and 80%
      const clamped = Math.max(20, Math.min(80, Math.round(rawPct)));
      setSplitPct(clamped);
    };

    const handleMouseUp = () => {
      isDraggingRef.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
  };

  // Cross-panel communication: sends prompts from Workbench into the ChatScreen on the right
  const [externalChatInput, setExternalChatInput] = useState<string>("");

  const [activeTab, setActiveTab] = useState<"ai_authoring" | "workflow_test">(defaultTab);

  // AI Authoring workbench state
  const [sessions, setSessions] = useState<AuthoringSession[]>([]);
  const [activeSession, setActiveSession] = useState<AuthoringSession | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [safeTestResult, setSafeTestResult] = useState<SafeTestResult | null>(null);
  const [testing, setTesting] = useState(false);
  const [approving, setApproving] = useState(false);
  const [approvalResult, setApprovalResult] = useState<ApprovalResult | null>(null);

  // Workflow Test & Run state (SSE)
  const [wf, setWf] = useState<Workflow | null>(null);
  const [wfs, setWfs] = useState<Workflow[]>([]);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [testInput, setTestInput] = useState("");
  const [testMsgs, setTestMsgs] = useState<ChatMsg[]>([]);
  const [testStreaming, setTestStreaming] = useState("");
  const [testSteps, setTestSteps] = useState<Step[]>([]);
  const [testActivity, setTestActivity] = useState<StreamActivity[]>([]);
  const [testRunning, setTestRunning] = useState(false);
  const [testMeter, setTestMeter] = useState<{ tokens: number; cost: number } | null>(null);
  const [compDefs, setCompDefs] = useState<Record<string, ComponentT>>({});
  const [liveParts, setLiveParts] = useState<Part[]>([]);

  const nodeLabels = useMemo(() => buildNodeLabels(wf), [wf]);
  const testScrollRef = useRef<HTMLDivElement>(null);
  const threadRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Load project workflows and authoring sessions
  const loadSessions = useCallback(async () => {
    if (!project?.id) return;
    try {
      const sessList = await api.listAutomationSessions(project.id);
      setSessions(sessList);
      if (sessList.length > 0 && !activeSession) {
        setActiveSession(sessList[0]);
      }
    } catch {
      // ignore
    }
  }, [project?.id, activeSession]);

  useEffect(() => {
    if (!project?.id) return;
    loadSessions();
    api.listComponents(project.id).then((cs) => setCompDefs(Object.fromEntries(cs.map((c) => [c.id, c])))).catch(() => {});
    api.listWorkflows(project.id)
      .then((ws) => {
        setWfs(ws);
        const active = ws.find((w) => w.status === "active") || ws[0] || null;
        setWf(active);
        if (!active) setLoadErr("No workflows in this project yet. Ask Automation Manager to design one!");
      })
      .catch((e) => setLoadErr(String(e.message || e)));
  }, [project?.id, loadSessions]);

  useEffect(() => {
    testScrollRef.current?.scrollTo({ top: 1e9, behavior: "smooth" });
  }, [testMsgs, testStreaming, testSteps, liveParts]);

  // Create new authoring session
  async function handleNewSession() {
    if (!project?.id) return;
    setAiLoading(true);
    setAiError(null);
    setApprovalResult(null);
    setSafeTestResult(null);
    try {
      const created = await api.createAutomationSession(project.id, {
        requirement: "Design a new intelligent workflow pipeline",
      });
      setSessions((prev) => [created, ...prev]);
      setActiveSession(created);
      setExternalChatInput("Hello! Let's design a new automation pipeline together. What should we build?");
    } catch (e: any) {
      setAiError(String(e.message || e));
    } finally {
      setAiLoading(false);
    }
  }

  // Safe dry-run test
  async function handleRunSafeTest() {
    if (!project?.id || !activeSession) return;
    setTesting(true);
    setAiError(null);
    try {
      const res = await api.testAutomationProposal(project.id, activeSession.id);
      setSafeTestResult(res);
      const refreshed = await api.getAutomationSession(project.id, activeSession.id);
      setActiveSession(refreshed);
    } catch (e: any) {
      setAiError(String(e.message || e));
    } finally {
      setTesting(false);
    }
  }

  // Consolidated Approval & Activation
  async function handleApproveAndActivate() {
    if (!project?.id || !activeSession) return;
    setApproving(true);
    setAiError(null);
    try {
      const res = await api.approveAutomationProposal(project.id, activeSession.id, {
        revision: activeSession.revision,
        create_agents: true,
        activate: true,
      });
      setApprovalResult(res);
      const refreshed = await api.getAutomationSession(project.id, activeSession.id);
      setActiveSession(refreshed);
      // Refresh workflows list
      const updatedWfs = await api.listWorkflows(project.id);
      setWfs(updatedWfs);
      const matchingWf = updatedWfs.find((w) => w.id === res.workflow_id);
      if (matchingWf) setWf(matchingWf);
    } catch (e: any) {
      setAiError(String(e.message || e));
    } finally {
      setApproving(false);
    }
  }

  // Open generated workflow in canvas
  function handleOpenInCanvas() {
    const wid = activeSession?.proposal?.workflow_id;
    if (wid) {
      const found = wfs.find((w) => w.id === wid);
      if (found && onOpenWorkflow) {
        onOpenWorkflow(found);
        return;
      }
    }
    if (onNav) onNav("workflows");
  }

  // SSE Workflow execution runner
  async function handleSendTestRun(textArg?: string) {
    const text = (typeof textArg === "string" ? textArg : testInput).trim();
    if (!text || !wf || testRunning || !project?.id) return;
    if (typeof textArg !== "string") setTestInput("");
    setTestMsgs((m) => [...m, { role: "user", content: text }]);
    setTestStreaming("");
    setTestSteps([]);
    setTestActivity([]);
    setTestMeter(null);
    setTestRunning(true);
    setLiveParts([]);

    try {
      const run = await api.createRun(
        project.id,
        wf.id,
        { messages: [{ role: "user", content: text }] },
        threadRef.current || undefined,
      );
      threadRef.current = run.thread_id;
      const controller = new AbortController();
      abortRef.current = controller;

      const result = await runWorkflowSSE(
        api.runStreamUrl(project.id, wf.id, run.id),
        {
          onText: (fullText, parts) => {
            setTestStreaming(fullText);
            setLiveParts(parts);
          },
          onNodeStep: (node) => {
            setTestSteps((s) => (s.some((x) => x.node === node) ? s : [...s, { node }]));
          },
          onActivity: (act) => {
            setTestActivity((prev) => {
              const idx = prev.findIndex((x) => x.id === act.id);
              if (idx >= 0) {
                const next = [...prev];
                next[idx] = act;
                return next;
              }
              return [...prev, act];
            });
          },
          onComponent: (comp, parts) => {
            setLiveParts(parts);
          },
          onDone: (meter) => {
            setTestMeter({ tokens: meter.tokens, cost: meter.cost });
          },
        },
        controller.signal,
      );

      if (!result.interrupted) {
        setTestMsgs((m) => [
          ...m,
          result.parts.length > 0
            ? { role: "assistant", parts: result.parts }
            : { role: "assistant", content: result.answer },
        ]);
      }
    } catch (e: any) {
      if (e?.name !== "AbortError") {
        setTestMsgs((m) => [...m, { role: "assistant", content: `⚠ ${e.message || e}` }]);
      }
    } finally {
      abortRef.current = null;
      setTestStreaming("");
      setTestRunning(false);
      setLiveParts([]);
    }
  }

  // React Flow preview elements from proposal
  const previewNodes: Node[] = useMemo(() => {
    const rawNodes = activeSession?.proposal?.canvas?.nodes || [];
    return rawNodes.map((n: any) => ({
      id: n.id,
      position: n.position || { x: 100, y: 100 },
      data: {
        label: (
          <div style={{ padding: "6px 10px", fontSize: 12, fontWeight: 600 }}>
            <span style={{ color: "var(--accent)", marginRight: 5 }}>●</span>
            {n.data?.label || n.id}
            <div style={{ fontSize: 10, color: "var(--fg-2)", fontWeight: 400 }}>{n.data?.nodeType || n.type}</div>
          </div>
        ),
      },
      style: {
        background: "var(--bg-card)",
        border: "1px solid var(--line)",
        borderRadius: 8,
        color: "var(--fg-0)",
        minWidth: 140,
        boxShadow: "var(--sh-card)",
      },
    }));
  }, [activeSession?.proposal]);

  const previewEdges: Edge[] = useMemo(() => {
    const rawEdges = activeSession?.proposal?.canvas?.edges || [];
    return rawEdges.map((e: any) => ({
      id: e.id || `${e.source}->${e.target}`,
      source: e.source,
      target: e.target,
      label: e.label || undefined,
      animated: true,
      style: { stroke: "var(--accent)" },
    }));
  }, [activeSession?.proposal]);

  const proposal = activeSession?.proposal;

  return (
    <div
      ref={containerRef}
      style={{
        display: "flex",
        width: "100%",
        height: "100%",
        minHeight: 0,
        overflow: "hidden",
        position: "relative",
      }}
    >
      {/* ==================================================================== */}
      {/* LEFT HALF: Automate Workbench (Visual Studio, Graph, Safe-Test)       */}
      {/* ==================================================================== */}
      <div
        style={{
          width: `${splitPct}%`,
          height: "100%",
          minWidth: 340,
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          background: "var(--bg-0)",
        }}
      >
        {/* Left Workbench Top Bar */}
        <div
          className="row spread"
          style={{
            padding: "10px 16px",
            borderBottom: "1px solid var(--line)",
            background: "var(--bg-surface)",
            flex: "none",
            alignItems: "center",
          }}
        >
          <div className="row gap2" style={{ alignItems: "center" }}>
            <div
              style={{
                width: 28,
                height: 28,
                borderRadius: 6,
                background: "rgba(99, 102, 241, 0.12)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <Icon name="workflows" size={16} style={{ color: "var(--accent)" }} />
            </div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, lineHeight: 1.2 }}>Automate Workbench</div>
              <div className="fg-2" style={{ fontSize: 11 }}>Visual Pipeline Designer & Runtime</div>
            </div>
          </div>

          {/* Sub-tabs */}
          <div className="row gap1" style={{ background: "var(--bg-card)", padding: 2, borderRadius: 6, border: "1px solid var(--line)" }}>
            <button
              className={`btn btn-xs ${activeTab === "ai_authoring" ? "btn-secondary" : "btn-ghost"}`}
              style={{ fontSize: 11, padding: "3px 8px", height: "auto" }}
              onClick={() => setActiveTab("ai_authoring")}
            >
              <Icon name="sparkles" size={12} /> Studio & Graph
            </button>
            <button
              className={`btn btn-xs ${activeTab === "workflow_test" ? "btn-secondary" : "btn-ghost"}`}
              style={{ fontSize: 11, padding: "3px 8px", height: "auto" }}
              onClick={() => setActiveTab("workflow_test")}
            >
              <Icon name="play" size={12} /> Test & Run
            </button>
          </div>
        </div>

        {/* Tab 1: AI Workflow Studio (Sessions, Proposals, Safe-Test & Graph Preview) */}
        {activeTab === "ai_authoring" && (
          <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
            {/* Studio Control Strip */}
            <div
              className="row spread"
              style={{
                padding: "8px 16px",
                borderBottom: "1px solid var(--line)",
                background: "var(--bg-glass)",
                flex: "none",
                alignItems: "center",
                gap: 8,
              }}
            >
              <div className="row gap2" style={{ alignItems: "center", flex: 1, minWidth: 0 }}>
                <button
                  className="btn btn-primary btn-sm"
                  onClick={handleNewSession}
                  disabled={aiLoading}
                  style={{ flexShrink: 0, height: 28, fontSize: 12, padding: "0 10px" }}
                >
                  <Icon name="plus" size={13} /> New Draft
                </button>

                {sessions.length > 0 && (
                  <div style={{ position: "relative", flex: 1, minWidth: 120 }}>
                    <select
                      className="select"
                      style={{ height: 28, fontSize: 12, width: "100%", paddingRight: 24 }}
                      value={activeSession?.id || ""}
                      onChange={(e) => {
                        const sel = sessions.find((s) => s.id === e.target.value) || null;
                        setActiveSession(sel);
                        setApprovalResult(null);
                        if (sel?.proposal?.safe_test_results) {
                          setSafeTestResult(sel.proposal.safe_test_results);
                        }
                      }}
                    >
                      {sessions.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.title || "Untitled"} (Rev {s.revision} · {s.status})
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                {activeSession && (
                  <StatusPill
                    status={activeSession.status === "approved" ? "active" : activeSession.status === "proposed" ? "review" : "draft"}
                  />
                )}
              </div>

              <div className="row gap1" style={{ flexShrink: 0 }}>
                {proposal && (
                  <>
                    <button
                      className="btn btn-sm btn-ghost"
                      onClick={handleRunSafeTest}
                      disabled={testing}
                      title="Dry-run safe simulation"
                      style={{ height: 28, fontSize: 11, padding: "0 8px" }}
                    >
                      <Icon name="shield" size={12} /> {testing ? "Testing…" : "Safe Test"}
                    </button>
                    <button
                      className="btn btn-sm btn-primary"
                      onClick={handleApproveAndActivate}
                      disabled={approving || activeSession?.status === "approved"}
                      title="Approve specialist agents & activate workflow"
                      style={{ height: 28, fontSize: 11, padding: "0 9px" }}
                    >
                      <Icon name="check-circle" size={12} /> {approving ? "Approving…" : activeSession?.status === "approved" ? "Approved" : "Approve"}
                    </button>
                  </>
                )}
                <button
                  className="btn btn-sm btn-ghost"
                  onClick={handleOpenInCanvas}
                  title="Open in Low-Code Designer"
                  style={{ height: 28, fontSize: 11, padding: "0 8px" }}
                >
                  <Icon name="external-link" size={12} /> Canvas
                </button>
              </div>
            </div>

            {/* Scrollable Studio Content & Graph View */}
            <div className="scroll-y" style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
              {/* Proposal Summary & Verdict Card */}
              {proposal ? (
                <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--line)", background: "var(--bg-surface)" }}>
                  <div className="card col gap2" style={{ padding: 14, border: "1px solid var(--accent)", background: "var(--bg-card)" }}>
                    <div className="row spread">
                      <div className="row gap2" style={{ alignItems: "center" }}>
                        <Icon name="workflows" size={18} style={{ color: "var(--accent)" }} />
                        <div>
                          <div style={{ fontSize: 13, fontWeight: 700 }}>{proposal.title}</div>
                          <div className="fg-2" style={{ fontSize: 11 }}>{proposal.description}</div>
                        </div>
                      </div>
                      <div className="row gap1" style={{ alignItems: "center" }}>
                        <span className="pill" style={{ background: "var(--accent-glow)", color: "var(--accent)", fontSize: 10 }}>
                          {proposal.strategy}
                        </span>
                        <StatusPill status={proposal.validation?.valid ? "active" : "error"} />
                      </div>
                    </div>

                    <div className="fg-1" style={{ fontSize: 12, lineHeight: "17px" }}>
                      {proposal.explanation}
                    </div>

                    {/* Proposed Specialist Agents */}
                    {proposal.proposed_agents?.length > 0 && (
                      <div className="col gap1" style={{ padding: "8px 10px", background: "var(--bg-surface)", borderRadius: 6 }}>
                        <div className="t-micro" style={{ color: "var(--fg-2)" }}>Proposed Specialist Agents</div>
                        {proposal.proposed_agents.map((ag, idx) => (
                          <div key={idx} className="row spread" style={{ fontSize: 11 }}>
                            <span style={{ fontWeight: 600 }}>{ag.name}</span>
                            <span className="fg-2 truncate" style={{ maxWidth: 160 }}>{ag.responsibility}</span>
                            <span className="pill" style={{ fontSize: 9.5 }}>{ag.tools?.length || 0} tools</span>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Safe Dry-Run Results */}
                    {safeTestResult && (
                      <div className="col gap1" style={{ padding: "8px 10px", background: "var(--bg-surface)", borderRadius: 6 }}>
                        <div className="row spread">
                          <span className="t-micro" style={{ color: "var(--fg-2)" }}>Safe Dry-Run Verdict</span>
                          <StatusPill status={safeTestResult.status === "passed" ? "active" : "warn"} />
                        </div>
                        {safeTestResult.checks.map((chk, idx) => (
                          <div key={idx} className="row gap2" style={{ fontSize: 11 }}>
                            <Icon
                              name={chk.status === "passed" ? "check" : "alert-triangle"}
                              size={12}
                              style={{ color: chk.status === "passed" ? "var(--ok)" : "var(--warn)" }}
                            />
                            <span style={{ fontWeight: 500 }}>{chk.name}:</span>
                            <span className="fg-2">{chk.detail}</span>
                          </div>
                        ))}
                        {safeTestResult.risks_identified?.length > 0 && (
                          <div className="col gap1" style={{ marginTop: 2 }}>
                            <span style={{ color: "var(--warn)", fontWeight: 600, fontSize: 11 }}>Identified Risks:</span>
                            {safeTestResult.risks_identified.map((r, ri) => (
                              <div key={ri} className="fg-2" style={{ fontSize: 10.5 }}>• {r}</div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Approval Result Banner */}
                    {approvalResult && (
                      <div style={{ padding: "6px 10px", background: "rgba(16,185,129,0.1)", border: "1px solid var(--ok)", borderRadius: 6, color: "var(--ok)", fontSize: 12 }}>
                        <div className="row gap1" style={{ alignItems: "center" }}>
                          <Icon name="check" size={14} />
                          <span style={{ fontWeight: 600 }}>{approvalResult.message}</span>
                        </div>
                      </div>
                    )}

                    {/* Quick Consultation bridge */}
                    <div className="row spread" style={{ alignItems: "center", marginTop: 4 }}>
                      <button
                        className="btn btn-xs btn-ghost"
                        onClick={() =>
                          setExternalChatInput(
                            `Can you explain the design decisions and optimize the proposed workflow "${proposal.title}"?`
                          )
                        }
                        title="Inquire in Automation Manager chat"
                        style={{ fontSize: 11 }}
                      >
                        <Icon name="sparkles" size={12} /> Ask Automation Manager to optimize
                      </button>
                      <button
                        className="btn btn-xs btn-ghost"
                        onClick={() =>
                          setExternalChatInput(
                            `What potential failure modes or edge cases exist in the "${proposal.title}" pipeline?`
                          )
                        }
                        title="Risk analysis in chat"
                        style={{ fontSize: 11 }}
                      >
                        <Icon name="shield" size={12} /> Consult about risks
                      </button>
                    </div>
                  </div>
                </div>
              ) : null}

              {/* Error Banner */}
              {aiError && (
                <div style={{ margin: "10px 16px", padding: "8px 12px", background: "rgba(239,68,68,0.1)", border: "1px solid var(--err)", borderRadius: 6, color: "var(--err)", fontSize: 12 }}>
                  <div className="row gap1" style={{ alignItems: "center" }}>
                    <Icon name="alert-triangle" size={14} />
                    <span>{aiError}</span>
                  </div>
                </div>
              )}

              {/* Live Graph Visual Preview Area */}
              <div style={{ flex: 1, minHeight: 340, position: "relative", display: "flex", flexDirection: "column" }}>
                <div className="row spread" style={{ padding: "8px 16px", borderBottom: "1px solid var(--line)", background: "var(--bg-surface)", alignItems: "center" }}>
                  <div className="row gap2" style={{ alignItems: "center" }}>
                    <span style={{ fontSize: 12, fontWeight: 600 }}>Live Graph Preview</span>
                    {previewNodes.length > 0 && (
                      <span className="mono-sm fg-2" style={{ fontSize: 10 }}>
                        ({previewNodes.length} nodes · {previewEdges.length} edges)
                      </span>
                    )}
                  </div>
                  <button className="btn btn-xs btn-ghost" onClick={handleOpenInCanvas} title="Open in Low-Code Designer">
                    <Icon name="external-link" size={11} /> Open in Designer
                  </button>
                </div>

                <div style={{ flex: 1, minHeight: 0, position: "relative" }}>
                  {previewNodes.length > 0 ? (
                    <ReactFlowProvider>
                      <ReactFlow
                        nodes={previewNodes}
                        edges={previewEdges}
                        fitView
                        nodesDraggable={false}
                        nodesConnectable={false}
                        elementsSelectable={false}
                        zoomOnScroll={true}
                      >
                        <Background color="var(--line)" gap={16} />
                        <Controls showInteractive={false} />
                        <MiniMap
                          nodeColor="var(--accent)"
                          maskColor="rgba(0,0,0,0.5)"
                          style={{ background: "var(--bg-card)", border: "1px solid var(--line)" }}
                        />
                      </ReactFlow>
                    </ReactFlowProvider>
                  ) : (
                    <div className="col center" style={{ height: "100%", padding: 24, textAlign: "center", color: "var(--fg-2)" }}>
                      <div
                        style={{
                          width: 44,
                          height: 44,
                          borderRadius: 10,
                          background: "var(--bg-card)",
                          border: "1px solid var(--line)",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          marginBottom: 12,
                        }}
                      >
                        <Icon name="workflows" size={24} style={{ color: "var(--accent)", opacity: 0.8 }} />
                      </div>
                      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--fg-0)", marginBottom: 4 }}>
                        No Active Graph Proposal
                      </div>
                      <div style={{ fontSize: 11.5, maxWidth: 300, lineHeight: "16px", marginBottom: 16 }}>
                        Ask the Automation Manager in the chat panel on the right to design, propose, and validate an automated workflow.
                      </div>
                      <div className="row gap2" style={{ flexWrap: "wrap", justifyContent: "center" }}>
                        <button
                          className="btn btn-xs btn-secondary"
                          onClick={() =>
                            setExternalChatInput(
                              "Design an automated customer onboarding pipeline that validates user data and notifies the team."
                            )
                          }
                          style={{ fontSize: 11 }}
                        >
                          Customer Onboarding
                        </button>
                        <button
                          className="btn btn-xs btn-secondary"
                          onClick={() =>
                            setExternalChatInput(
                              "Create a daily health monitoring and alerting workflow with automatic recovery."
                            )
                          }
                          style={{ fontSize: 11 }}
                        >
                          Health & Alerting
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Tab 2: Workflow Execution Test & Runner (SSE) */}
        {activeTab === "workflow_test" && (
          <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
            {/* Target Workflow Picker & Metrics */}
            <div className="row spread" style={{ padding: "8px 16px", borderBottom: "1px solid var(--line)", background: "var(--bg-surface)", alignItems: "center" }}>
              <div className="row gap2" style={{ alignItems: "center" }}>
                <span className="fg-2" style={{ fontSize: 11.5 }}>Workflow:</span>
                <select
                  className="select"
                  style={{ height: 28, fontSize: 12 }}
                  value={wf?.id || ""}
                  onChange={(e) => {
                    const sel = wfs.find((w) => w.id === e.target.value) || null;
                    setWf(sel);
                    setTestMsgs([]);
                    threadRef.current = null;
                  }}
                >
                  {wfs.map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.name} ({w.status})
                    </option>
                  ))}
                </select>
              </div>
              {testMeter && (
                <span className="mono-sm fg-2" style={{ fontSize: 11 }}>
                  {testMeter.tokens} tok · {fmtUSD(testMeter.cost)}
                </span>
              )}
            </div>

            {/* SSE Messages & Activity Area */}
            <div ref={testScrollRef} className="scroll-y" style={{ flex: 1, padding: "16px 20px" }}>
              <div className="col gap3">
                {loadErr && (
                  <div className="card" style={{ padding: 12, color: "var(--warn)", fontSize: 12 }}>
                    {loadErr}
                  </div>
                )}
                {testMsgs.map((m, i) => (
                  <div
                    key={i}
                    className="row"
                    style={{
                      gap: 10,
                      alignItems: "flex-start",
                      flexDirection: m.role === "user" ? "row-reverse" : "row",
                    }}
                  >
                    <div
                      style={{
                        maxWidth: "85%",
                        padding: "8px 12px",
                        borderRadius: 10,
                        background: m.role === "user" ? "var(--accent)" : "var(--bg-card)",
                        color: m.role === "user" ? "var(--fg-on-accent)" : "var(--fg-0)",
                        border: m.role === "user" ? "none" : "1px solid var(--line)",
                        fontSize: 13,
                        lineHeight: "18px",
                      }}
                    >
                      {m.content && <Markdown>{m.content}</Markdown>}
                      {m.parts?.map((p, pi) =>
                        p.kind === "text" ? (
                          <Markdown key={pi}>{p.text}</Markdown>
                        ) : (
                          <ComponentRenderer
                            key={pi}
                            def={compDefs[p.inst.component_id] || { id: p.inst.component_id, name: p.inst.name, html: "", css: "" }}
                            props={p.inst.props || {}}
                            onAction={() => {}}
                          />
                        ),
                      )}
                    </div>
                  </div>
                ))}
                {testStreaming && (
                  <div className="row gap2" style={{ padding: "8px 12px", color: "var(--accent)" }}>
                    <div style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--accent)", animation: "pulse 1s infinite" }} />
                    <Markdown>{testStreaming}</Markdown>
                  </div>
                )}
              </div>
            </div>

            {/* Execution Input Bar */}
            <div style={{ padding: "10px 16px", borderTop: "1px solid var(--line)", background: "var(--bg-glass)" }}>
              <div className="row gap2">
                <input
                  className="input grow"
                  placeholder="Message the workflow…"
                  value={testInput}
                  onChange={(e) => setTestInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      handleSendTestRun();
                    }
                  }}
                  disabled={testRunning}
                  style={{ height: 32, fontSize: 12.5 }}
                />
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => {
                    threadRef.current = null;
                    setTestMsgs([]);
                  }}
                  style={{ height: 32 }}
                >
                  Reset
                </button>
                {testRunning ? (
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => {
                      abortRef.current?.abort();
                      setTestRunning(false);
                    }}
                    style={{ height: 32 }}
                  >
                    Stop
                  </button>
                ) : (
                  <button className="btn btn-primary btn-sm" onClick={() => handleSendTestRun()} disabled={!testInput.trim()} style={{ height: 32 }}>
                    <Icon name="play" size={13} /> Run
                  </button>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ==================================================================== */}
      {/* DRAGGABLE DIVIDER (1px hairline matching Memory & Integrations)       */}
      {/* ==================================================================== */}
      <div
        onMouseDown={handleMouseDown}
        style={{
          width: 1,
          flex: "none",
          position: "relative",
          background: "var(--line)",
          cursor: "col-resize",
          userSelect: "none",
          outline: "none",
        }}
      >
        <div
          style={{
            position: "absolute",
            top: 0,
            bottom: 0,
            left: -4,
            right: -4,
            cursor: "col-resize",
            zIndex: 10,
          }}
          title="Drag to resize Workbench and Chat panels"
        />
      </div>

      {/* ==================================================================== */}
      {/* RIGHT HALF: Chat Panel (identical to Memory & Integrations Playgrounds) */}
      {/* ==================================================================== */}
      <div
        style={{
          width: `${100 - splitPct}%`,
          height: "100%",
          minWidth: 340,
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        <ChatScreen
          project={project}
          persona="automation_manager"
          externalInput={externalChatInput}
          onExternalInputConsumed={() => setExternalChatInput("")}
        />
      </div>
    </div>
  );
}
