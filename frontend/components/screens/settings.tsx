"use client";
/* Settings: project config, split into a secondary-nav of focused sections
   (General · Members · API Keys · Model Pricing · Budgets · Knowledge · Versioning ·
   Observability · Advanced). Config-backed sections share one Save; Members, API Keys,
   Model Pricing and Secrets manage their own persistence. */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Icon } from "../icons";
import { EmptyState, Field, Modal, Segmented, Tabs, Toggle } from "../primitives";
import { api, clearTokens, DiscoveredModelItemT, InviteResult, MeResult, ModelProviderT, ModelServerT, ProjectVersion, RegisteredModelT, Secret, TeamMember } from "@/lib/api";
import { invalidateModelCatalog, useEmbeddingModels, useModels, useRerankerModels } from "@/lib/models";

const ROLES = ["owner", "admin", "editor", "viewer", "connector"];

// Embedder + reranker models (and which one is default) come from the backend catalog now
// (useEmbeddingModels / useRerankerModels) - the frontend hardcodes no model lists.
const DEFAULT_CHILD_CHUNK_SIZE = 300;

type SectionId =
  | "models" | "apikeys" | "members"
  | "guardrails" | "versioning" | "observability" | "advanced" | "history";

const SECTIONS: { id: SectionId; label: string; icon: string; savesConfig?: boolean }[] = [
  { id: "models", label: "Models & Providers", icon: "sparkles", savesConfig: true },
  { id: "apikeys", label: "Secrets & Credentials", icon: "secret" },
  { id: "members", label: "Members & Roles", icon: "user" },
  { id: "guardrails", label: "Guardrails & Egress", icon: "shield-check", savesConfig: true },
  { id: "versioning", label: "Versioning", icon: "clock", savesConfig: true },
  { id: "observability", label: "Observability & Retention", icon: "traces", savesConfig: true },
  { id: "advanced", label: "Advanced", icon: "settings", savesConfig: true },
  { id: "history", label: "History", icon: "clock" },
];

// Which settings section each project-config field belongs to, so History can group changes
// under the same tab names as the nav. Top-level snapshot fields + config.* keys. Anything not
// listed falls through to "advanced". Members/API-key values are intentionally NOT diffed here
// (Members isn't config-backed; secrets are masked below).
const FIELD_SECTION: Record<string, SectionId> = {
  name: "advanced", description: "advanced", slug: "advanced", status: "advanced",
  default_model: "models", provider_credentials: "models",
  default_middleware: "guardrails", egress: "guardrails",
  rag_defaults: "models",
  version_history_limit: "versioning", versioning: "versioning",
  observability: "observability",
  scheduler: "advanced",
  budgets: "advanced",
};
// The config-backed sections that get a History tab (Members isn't config-backed → skipped).
const HISTORY_TABS: SectionId[] = ["models", "guardrails", "versioning", "observability", "advanced"];
// Field paths whose values must never be shown in a diff (secrets / credentials).
const MASK_RE = /credential|secret|token|api[_-]?key|password/i;

export function SettingsScreen({ project }: { project: any }) {
  const [section, setSection] = useState<SectionId>("models");
  const MODELS = useModels();
  const embeddingModels = useEmbeddingModels();
  const rerankerModels = useRerankerModels();
  const [config, setConfig] = useState<Record<string, any>>({});
  const [meta, setMeta] = useState<{ name: string; description: string }>({ name: "", description: "" });
  const [secrets, setSecrets] = useState<Secret[]>([]);
  const [save, setSave] = useState<"idle" | "saving" | "saved">("idle");
  const [open, setOpen] = useState(false);
  const [secForm, setSecForm] = useState({ name: "", value: "", kind: "api_key" });
  const [pkeys, setPkeys] = useState<Record<string, string>>({});
  const [keySave, setKeySave] = useState<"idle" | "saving" | "saved">("idle");

  const [modelServers, setModelServers] = useState<ModelServerT[]>([]);
  const [registeredModels, setRegisteredModels] = useState<RegisteredModelT[]>([]);
  const [loadingRegistry, setLoadingRegistry] = useState(false);

  // Server & Model Wizard State
  const [serverForm, setServerForm] = useState({ name: "Local Ollama", provider_type: "ollama", base_url: "http://localhost:11434", api_key: "" });
  const [serverTesting, setServerTesting] = useState(false);
  const [serverTestResult, setServerTestResult] = useState<{ ok: boolean; status_code?: number; latency_ms?: number; discovered_count?: number; error?: string } | null>(null);
  const [serverSaving, setServerSaving] = useState(false);
  const [providerDropdownOpen, setProviderDropdownOpen] = useState(false);
  const [providerSearchQuery, setProviderSearchQuery] = useState("");

  // Add Model Wizard Modal State
  const [addModelOpen, setAddModelOpen] = useState(false);
  const [wizardStep, setWizardStep] = useState<1 | 2 | 3 | 4>(1);
  const [isConnectingNewServer, setIsConnectingNewServer] = useState(false);
  const [selectedServerId, setSelectedServerId] = useState("");
  const [serverDiscoveredModels, setServerDiscoveredModels] = useState<DiscoveredModelItemT[]>([]);
  const [discovering, setDiscovering] = useState(false);
  const [wireModelInput, setWireModelInput] = useState("");
  const [modelConfigForm, setModelConfigForm] = useState({
    displayName: "",
    contextConfigured: 32768,
    supportsTools: true,
    supportsVision: false,
    temperature: 0.3,
    topP: 0.9,
    maxOutputTokens: 4096,
    setAsDefault: false,
  });
  const [testInfRunning, setTestInfRunning] = useState(false);
  const [testInfResult, setTestInfResult] = useState<{ ok: boolean; latency_ms?: number; snippet?: string; error?: string } | null>(null);
  const [testToolsRunning, setTestToolsRunning] = useState(false);
  const [testToolsResult, setTestToolsResult] = useState<{ ok: boolean; latency_ms?: number; toolCalled?: string; error?: string } | null>(null);
  const [savingModel, setSavingModel] = useState(false);

  // Edit Model Modal
  const [editModelModal, setEditModelModal] = useState<RegisteredModelT | null>(null);
  const [editModelForm, setEditModelForm] = useState({
    displayName: "",
    contextConfigured: 32768,
    supportsTools: true,
    supportsVision: false,
    temperature: 0.3,
    topP: 0.9,
    maxOutputTokens: 4096,
    enabled: true,
  });

  // Discover server modal
  const [discoverServerModal, setDiscoverServerModal] = useState<ModelServerT | null>(null);
  const [discoverModalList, setDiscoverModalList] = useState<DiscoveredModelItemT[]>([]);
  const [discoverModalLoading, setDiscoverModalLoading] = useState(false);

  // Testing modal for registered model
  const [activeTestModel, setActiveTestModel] = useState<RegisteredModelT | null>(null);

  const reloadSecrets = useCallback(() => { if (project?.id) api.listSecrets(project.id).then(setSecrets).catch(() => {}); }, [project?.id]);
  const reloadRegistry = useCallback(async () => {
    setLoadingRegistry(true);
    try {
      const [s, m] = await Promise.all([
        api.listServers(),
        api.listRegistryModels(project?.id),
      ]);
      setModelServers(s);
      setRegisteredModels(m);
      invalidateModelCatalog();
    } catch (e) {
      console.error("Failed to load model registry:", e);
    } finally {
      setLoadingRegistry(false);
    }
  }, [project?.id]);

  useEffect(() => {
    if (!project?.id) return;
    api.getProject(project.id).then((p) => {
      setConfig(p.config || {});
      setMeta({ name: p.name || "", description: p.description || "" });
    }).catch(() => {});
    reloadSecrets();
    reloadRegistry();
  }, [project?.id, reloadSecrets, reloadRegistry]);


  const setCfg = (patch: Record<string, any>) => setConfig((c) => ({ ...c, ...patch }));
  const features = config.features || {};
  const budgets = config.budgets || {};
  const rag = config.rag_defaults || {};
  const versioning = config.versioning || {};
  const observability = config.observability || {};
  const scheduler = config.scheduler || {};
  const defaultEmbedding = embeddingModels.find((m) => m.default)?.id ?? "";
  const defaultReranker = rerankerModels.find((m) => m.default)?.id ?? "";
  const embeddingModel = rag.embedding_model || defaultEmbedding;
  const setRag = (patch: Record<string, any>) => setCfg({ rag_defaults: { ...rag, ...patch } });

  const [embedStatus, setEmbedStatus] = useState<{
    model_id: string;
    is_local: boolean;
    cached: boolean;
    package_installed: boolean;
    approx_size?: string;
    cache_dir?: string;
    error?: string;
  } | null>(null);
  const [downloadingEmbed, setDownloadingEmbed] = useState(false);

  useEffect(() => {
    if (!embeddingModel) return;
    api.getEmbeddingModelStatus(embeddingModel)
      .then(setEmbedStatus)
      .catch(() => setEmbedStatus(null));
  }, [embeddingModel]);

  const handleDownloadEmbed = async () => {
    if (!embeddingModel || downloadingEmbed) return;
    setDownloadingEmbed(true);
    try {
      await api.downloadEmbeddingModel(embeddingModel);
      const res = await api.getEmbeddingModelStatus(embeddingModel);
      setEmbedStatus(res);
    } catch (e: any) {
      alert(`Download failed: ${e?.message || e}`);
    } finally {
      setDownloadingEmbed(false);
    }
  };

  async function persist() {
    setSave("saving");
    try {
      await api.updateProject(project.id, { config });
      setSave("saved"); setTimeout(() => setSave("idle"), 1400);
    } catch { setSave("idle"); }
  }
  async function addSecret() {
    if (!secForm.name.trim()) return;
    await api.createSecret(project.id, { name: secForm.name, value: secForm.value, kind: secForm.kind });
    setOpen(false); setSecForm({ name: "", value: "", kind: "api_key" }); reloadSecrets();
  }
  async function removeSecret(name: string) {
    let used: { type: string; label: string }[] = [];
    try { used = (await api.secretUsage(project.id, name)).references; } catch { /* fall back to a plain confirm */ }
    const detail = used.length
      ? `\n\nIn use by ${used.length}:\n` + used.map((r) => `• ${r.label} - ${r.type.replace(/_/g, " ")}`).join("\n") + `\n\nDeleting will break these.`
      : "";
    if (!window.confirm(`Delete secret "${name}"?${detail}`)) return;
    await api.deleteSecret(project.id, name, true); reloadSecrets();
  }
  async function saveKeys() {
    setKeySave("saving");
    const pc = { ...(config.provider_credentials || {}) };
    for (const [prov, val] of Object.entries(pkeys)) {
      if (!val.trim()) continue;
      const name = `${prov}_key`;
      await api.createSecret(project.id, { name, value: val, kind: "api_key" });
      pc[prov] = `secret://proj/${name}`;
    }
    const newConfig = { ...config, provider_credentials: pc };
    setConfig(newConfig);
    await api.updateProject(project.id, { config: newConfig });
    setPkeys({}); reloadSecrets();
    setKeySave("saved"); setTimeout(() => setKeySave("idle"), 1400);
  }

  // --- Registry & Server Actions ---

  async function handleTestServer() {
    setServerTesting(true);
    setServerTestResult(null);
    try {
      const res = await api.testServer({
        provider_type: serverForm.provider_type,
        base_url: serverForm.base_url.trim(),
        api_key: serverForm.api_key.trim() || undefined,
      });
      setServerTestResult(res);
    } catch (e: any) {
      setServerTestResult({ ok: false, latency_ms: 0, discovered_count: 0, error: e?.message || "Failed to reach server" });
    } finally {
      setServerTesting(false);
    }
  }

  async function handleCreateServer() {
    if (!serverForm.name.trim()) return;
    setServerSaving(true);
    try {
      const created = await api.createServer({
        name: serverForm.name.trim(),
        provider_type: serverForm.provider_type,
        base_url: serverForm.base_url.trim(),
        api_key: serverForm.api_key.trim() || undefined,
        enabled: true,
      });
      await reloadRegistry();
      setServerForm({ name: "Local Ollama", provider_type: "ollama", base_url: "http://localhost:11434", api_key: "" });
      setServerTestResult(null);
      setIsConnectingNewServer(false);
      if (created?.id) {
        await handleSelectServerInWizard(created.id);
      }
    } catch (e: any) {
      alert("Failed to create server: " + (e?.message || e));
    } finally {
      setServerSaving(false);
    }
  }

  async function handleDeleteServer(id: string, name: string) {
    if (!window.confirm(`Delete inference server "${name}"?`)) return;
    try {
      const res = await api.deleteServer(id, false);
      if (res.status === 409) {
        const text = await res.text();
        if (window.confirm(`${text}\n\nDo you want to force deletion along with associated models?`)) {
          await api.deleteServer(id, true);
        } else {
          return;
        }
      }
      await reloadRegistry();
    } catch (e: any) {
      alert("Failed to delete server: " + (e?.message || e));
    }
  }

  async function handleSelectServerInWizard(srvId: string) {
    setSelectedServerId(srvId);
    setDiscovering(true);
    setServerDiscoveredModels([]);
    try {
      const res = await api.discoverServerModels(srvId);
      if (res.ok) {
        setServerDiscoveredModels(res.models);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setDiscovering(false);
      setWizardStep(2);
    }
  }

  function handlePickDiscoveredModel(m: DiscoveredModelItemT) {
    setWireModelInput(m.model_name);
    setModelConfigForm((f) => ({
      ...f,
      displayName: m.display_name || m.model_name,
      contextConfigured: m.context_window_max || 32768,
      supportsTools: m.supports_tools !== false,
      supportsVision: !!m.supports_vision,
    }));
    setWizardStep(3);
  }

  async function handleRegisterModelInWizard() {
    if (!selectedServerId || !wireModelInput.trim()) return;
    setSavingModel(true);
    try {
      await api.createRegistryModel({
        server_id: selectedServerId,
        model_name: wireModelInput.trim(),
        display_name: modelConfigForm.displayName.trim() || wireModelInput.trim(),
        enabled: true,
        context_window_configured: modelConfigForm.contextConfigured,
        supports_tools: modelConfigForm.supportsTools,
        supports_vision: modelConfigForm.supportsVision,
        temperature: modelConfigForm.temperature,
        top_p: modelConfigForm.topP,
        max_output_tokens: modelConfigForm.maxOutputTokens,
        set_as_default: modelConfigForm.setAsDefault,
        project_id: project?.id,
      });
      await reloadRegistry();
      setAddModelOpen(false);
      setWizardStep(1);
      setSelectedServerId("");
      setWireModelInput("");
    } catch (e: any) {
      alert("Failed to register model: " + (e?.message || e));
    } finally {
      setSavingModel(false);
    }
  }

  async function handleToggleModel(m: RegisteredModelT) {
    try {
      await api.updateRegistryModel(m.id, { enabled: !m.enabled, project_id: project?.id });
      await reloadRegistry();
    } catch (e: any) {
      alert("Failed to update model: " + (e?.message || e));
    }
  }

  async function handleSetDefault(modelId: string) {
    try {
      await api.setDefaultModel(modelId, project?.id);
      await reloadRegistry();
    } catch (e: any) {
      alert("Failed to set default: " + (e?.message || e));
    }
  }

  async function handleDeleteModel(m: RegisteredModelT) {
    if (!window.confirm(`Delete model "${m.display_name}" from registry?`)) return;
    try {
      const res = await api.deleteRegistryModel(m.id, false);
      if (res.status === 409) {
        const text = await res.text();
        alert(text);
        return;
      }
      await reloadRegistry();
    } catch (e: any) {
      alert("Failed to delete model: " + (e?.message || e));
    }
  }

  function handleOpenEditModel(m: RegisteredModelT) {
    setEditModelModal(m);
    setEditModelForm({
      displayName: m.display_name,
      contextConfigured: m.context_window_configured || m.context_window_max || 32768,
      supportsTools: m.supports_tools !== false,
      supportsVision: !!m.supports_vision,
      temperature: m.temperature ?? 0.3,
      topP: m.top_p ?? 0.9,
      maxOutputTokens: m.max_output_tokens ?? 4096,
      enabled: m.enabled,
    });
  }

  async function handleSaveEditModel() {
    if (!editModelModal) return;
    try {
      await api.updateRegistryModel(editModelModal.id, {
        display_name: editModelForm.displayName.trim() || editModelModal.model_name,
        context_window_configured: editModelForm.contextConfigured,
        supports_tools: editModelForm.supportsTools,
        supports_vision: editModelForm.supportsVision,
        temperature: editModelForm.temperature,
        top_p: editModelForm.topP,
        max_output_tokens: editModelForm.maxOutputTokens,
        enabled: editModelForm.enabled,
        project_id: project?.id,
      });
      setEditModelModal(null);
      await reloadRegistry();
    } catch (e: any) {
      alert("Failed to save model: " + (e?.message || e));
    }
  }

  async function handleOpenDiscoverModal(srv: ModelServerT) {
    setDiscoverServerModal(srv);
    setDiscoverModalLoading(true);
    setDiscoverModalList([]);
    try {
      const res = await api.discoverServerModels(srv.id);
      if (res.ok) {
        setDiscoverModalList(res.models);
      }
    } catch (e: any) {
      alert("Failed to discover models: " + (e?.message || e));
    } finally {
      setDiscoverModalLoading(false);
    }
  }

  async function handleQuickRegisterFromDiscover(m: DiscoveredModelItemT) {
    if (!discoverServerModal) return;
    try {
      await api.createRegistryModel({
        server_id: discoverServerModal.id,
        model_name: m.model_name,
        display_name: m.display_name || m.model_name,
        enabled: true,
        context_window_configured: m.context_window_max || 32768,
        supports_tools: m.supports_tools !== false,
        supports_vision: !!m.supports_vision,
        temperature: 0.3,
        top_p: 0.9,
        max_output_tokens: 4096,
        project_id: project?.id,
      });
      // Refresh discover list
      const res = await api.discoverServerModels(discoverServerModal.id);
      if (res.ok) setDiscoverModalList(res.models);
      await reloadRegistry();
    } catch (e: any) {
      alert("Failed to register: " + (e?.message || e));
    }
  }

  async function handleRunInferenceTest(mId: string) {
    setTestInfRunning(true);
    setTestInfResult(null);
    try {
      const res = await api.testModelInference(mId);
      setTestInfResult({ ok: res.ok, latency_ms: res.latency_ms, snippet: res.response_snippet, error: res.error });
    } catch (e: any) {
      setTestInfResult({ ok: false, error: e?.message || "Inference failed" });
    } finally {
      setTestInfRunning(false);
    }
  }

  async function handleRunToolTest(mId: string) {
    setTestToolsRunning(true);
    setTestToolsResult(null);
    try {
      const res = await api.testModelTools(mId);
      setTestToolsResult({ ok: res.ok, latency_ms: res.latency_ms, toolCalled: res.tool_called, error: res.error });
    } catch (e: any) {
      setTestToolsResult({ ok: false, error: e?.message || "Tool test failed" });
    } finally {
      setTestToolsRunning(false);
    }
  }

  const SERVER_PRESETS = [
    { id: "ollama", label: "Ollama", type: "ollama", url: "http://localhost:11434", desc: "Local Ollama engine (native /api)", icon: "server", tag: "Local" },
    { id: "lm_studio", label: "LM Studio", type: "lm_studio", url: "http://localhost:1234", desc: "Local LM Studio OpenAI-compatible endpoint", icon: "bot", tag: "Local" },
    { id: "vllm", label: "vLLM", type: "vllm", url: "http://localhost:8000", desc: "High-throughput local vLLM cluster", icon: "bolt", tag: "Engine" },
    { id: "openai_compatible", label: "OpenAI-Compatible", type: "openai_compatible", url: "http://localhost:8080/v1", desc: "Custom gateway (llama.cpp, text-gen, etc.)", icon: "globe", tag: "Custom" },
    { id: "openai", label: "OpenAI Cloud", type: "openai", url: "https://api.openai.com/v1", desc: "GPT-4o, o3, GPT-4.1 Cloud", icon: "sparkles", tag: "Cloud" },
    { id: "anthropic", label: "Anthropic Cloud", type: "anthropic", url: "https://api.anthropic.com", desc: "Claude 3.7 Sonnet, Haiku Cloud", icon: "sparkles", tag: "Cloud" },
    { id: "google", label: "Google Gemini", type: "google", url: "https://generativelanguage.googleapis.com", desc: "Gemini 2.5 Flash, Gemini Pro Cloud", icon: "sparkles", tag: "Cloud" },
    { id: "groq", label: "Groq Cloud", type: "groq", url: "https://api.groq.com/openai/v1", desc: "Ultra-fast LPU Cloud inference", icon: "bolt", tag: "Cloud" },
    { id: "deepseek", label: "DeepSeek Cloud", type: "deepseek", url: "https://api.deepseek.com/v1", desc: "DeepSeek V3, R1 Cloud", icon: "sparkles", tag: "Cloud" },
  ];

  const activePreset = SERVER_PRESETS.find((p) => p.type === serverForm.provider_type) || SERVER_PRESETS[0];
  const filteredPresets = SERVER_PRESETS.filter((p) => {
    const q = providerSearchQuery.trim().toLowerCase();
    if (!q) return true;
    return (
      p.label.toLowerCase().includes(q) ||
      p.desc.toLowerCase().includes(q) ||
      p.type.toLowerCase().includes(q) ||
      p.tag.toLowerCase().includes(q)
    );
  });

  const PROVIDERS: [string, string][] = [["openai", "OpenAI"], ["anthropic", "Anthropic"], ["google_genai", "Google"]];
  const pcreds = config.provider_credentials || {};
  const activeMeta = SECTIONS.find((s) => s.id === section)!;

  return (
    <div className="col" style={{ flex: 1, minHeight: 0 }}>
      <div className="row" style={{ flex: 1, minHeight: 0, alignItems: "stretch" }}>
        {/* secondary nav */}
        <nav className="scroll-y" style={{ width: 224, flex: "none", borderRight: "1px solid var(--line)", background: "var(--bg-1)", padding: 10 }}>
          <div className="t-micro" style={{ padding: "6px 8px 8px" }}>Settings</div>
          {SECTIONS.map((s) => {
            const on = section === s.id;
            return (
              <button key={s.id} onClick={() => setSection(s.id)} className={"sidenav-item" + (on ? " active" : "")}
                style={{ display: "flex", alignItems: "center", gap: 10, width: "100%", height: 34, padding: "0 10px", marginBottom: 1, borderRadius: 7, border: "none", cursor: "pointer", textAlign: "left", color: on ? "var(--accent)" : "var(--fg-1)", fontSize: 13, fontWeight: on ? 600 : 500, fontFamily: "var(--font-ui)" }}>
                <Icon name={s.icon} size={16} style={{ flex: "none" }} />
                <span className="grow truncate">{s.label}</span>
              </button>
            );
          })}
        </nav>

        {/* content */}
        <div className="scroll-y grow" style={{ minWidth: 0 }}>
          <div className="fade-up" style={{ width: "100%", padding: "24px 32px" }}>
            <div className="row spread" style={{ marginBottom: 18 }}>
              <div className="t-display">{activeMeta.label}</div>
              {activeMeta.savesConfig && (
                <button className="btn btn-primary btn-sm" onClick={persist} disabled={save === "saving"}>
                  <Icon name={save === "saved" ? "check" : "save"} size={14} />{save === "saving" ? "Saving…" : save === "saved" ? "Saved" : "Save"}
                </button>
              )}
            </div>



            {section === "models" && (
              <>
                {/* 1. Header with primary Add action */}
                <div className="row spread" style={{ marginBottom: 14 }}>
                  <div>
                    <div className="t-h2">Model Registry</div>
                    <div className="t-caption fg-2" style={{ marginTop: 2 }}>
                      Explicitly registered local and cloud models for Alberto agents, chat, and workflows.
                    </div>
                  </div>
                  <div>
                    <button
                      className="btn btn-primary btn-sm"
                      onClick={() => {
                        setWizardStep(1);
                        setIsConnectingNewServer(modelServers.length === 0);
                        setSelectedServerId(modelServers[0]?.id || "");
                        setWireModelInput("");
                        setTestInfResult(null);
                        setTestToolsResult(null);
                        setAddModelOpen(true);
                      }}
                    >
                      <Icon name="plus" size={13} /> Add Model
                    </button>
                  </div>
                </div>

                {/* 2. Registered Models Section */}
                <div className="card" style={{ padding: 0, overflow: "hidden", marginBottom: 16 }}>
                  <div className="row spread" style={{ padding: "14px 18px", borderBottom: "1px solid var(--line)", alignItems: "flex-start" }}>
                    <div>
                      <div className="t-h2">Registered Models ({registeredModels.length})</div>
                      <div className="field-help" style={{ marginTop: 2, marginBottom: 0 }}>
                        Only registered, enabled models appear in Alberto execution selectors. Unregistered engines or cloud models are never exposed.
                      </div>
                    </div>
                    <button className="btn btn-secondary btn-sm" onClick={reloadRegistry} disabled={loadingRegistry} style={{ flex: "none" }}>
                      <Icon name="refresh" size={12} /> {loadingRegistry ? "Refreshing…" : "Refresh"}
                    </button>
                  </div>

                  {registeredModels.length === 0 ? (
                    <div style={{ padding: 18 }}>
                      <EmptyState
                        icon="sparkles"
                        title="No models configured"
                        sub="Add an Ollama, LM Studio or cloud provider to get started."
                        action={
                          <button
                            className="btn btn-primary btn-sm"
                            onClick={() => {
                              setWizardStep(1);
                              setIsConnectingNewServer(modelServers.length === 0);
                              setSelectedServerId(modelServers[0]?.id || "");
                              setWireModelInput("");
                              setTestInfResult(null);
                              setTestToolsResult(null);
                              setAddModelOpen(true);
                            }}
                          >
                            <Icon name="plus" size={13} /> Add Model
                          </button>
                        }
                      />
                    </div>
                  ) : (
                    <div style={{ overflowX: "auto", width: "100%" }}>
                      <table className="tbl" style={{ width: "100%", borderCollapse: "collapse" }}>
                        <thead>
                          <tr>
                            <th style={{ paddingLeft: 18, width: "22%" }}>Model & Alias</th>
                            <th style={{ width: "16%" }}>Server</th>
                            <th style={{ width: "10%" }}>Provider</th>
                            <th style={{ width: "11%" }}>Context</th>
                            <th style={{ width: "12%" }}>Capabilities</th>
                            <th style={{ width: "10%" }}>Default</th>
                            <th style={{ width: "10%" }}>Status</th>
                            <th style={{ width: "160px", textAlign: "right", paddingRight: 18 }}>Actions</th>
                          </tr>
                        </thead>
                        <tbody>
                          {registeredModels.map((m) => (
                            <tr key={m.id} style={{ background: m.is_default ? "var(--bg-1)" : "transparent" }}>
                              <td style={{ paddingLeft: 18, paddingRight: 12 }}>
                                <div style={{ fontWeight: 600, color: "var(--fg-0)" }}>{m.display_name}</div>
                                <div className="mono-sm fg-2" style={{ fontSize: 11 }}>{m.model_name}</div>
                              </td>
                              <td style={{ padding: "0 12px" }}>
                                <div style={{ fontWeight: 500 }}>{m.server_name}</div>
                              </td>
                              <td style={{ padding: "0 12px" }}>
                                <span className="typechip" style={{ fontSize: 11 }}>{m.provider_type}</span>
                              </td>
                              <td style={{ padding: "0 12px" }} className="mono-sm">
                                {m.context_window_configured ? `${m.context_window_configured.toLocaleString()} t` : "Default"}
                              </td>
                              <td style={{ padding: "0 12px" }}>
                                <div className="row gap1 wrap">
                                  {m.supports_tools && <span className="pill pill-ok" style={{ fontSize: 10 }}>Tools</span>}
                                  {m.supports_vision && <span className="pill pill-ok" style={{ fontSize: 10 }}>Vision</span>}
                                  {!m.supports_tools && !m.supports_vision && <span className="fg-2" style={{ fontSize: 11 }}>Basic</span>}
                                </div>
                              </td>
                              <td style={{ padding: "0 12px" }}>
                                {m.is_default ? (
                                  <span className="pill pill-ok" style={{ fontSize: 11, fontWeight: 600 }}>★ DEFAULT</span>
                                ) : (
                                  <button className="btn btn-ghost btn-sm" style={{ fontSize: 11, padding: "2px 8px", height: 24 }} onClick={() => handleSetDefault(m.id)}>
                                    Make Default
                                  </button>
                                )}
                              </td>
                              <td style={{ padding: "0 12px" }}>
                                <div className="row gap2" style={{ alignItems: "center" }}>
                                  <Toggle on={m.enabled} onChange={() => handleToggleModel(m)} />
                                  {m.availability === "available" ? (
                                    <span className="pill pill-ok" style={{ fontSize: 10 }}>live</span>
                                  ) : (
                                    <span className="pill" style={{ fontSize: 10, background: "var(--line)", color: "var(--fg-2)" }}>offline</span>
                                  )}
                                </div>
                              </td>
                              <td style={{ paddingRight: 18, paddingLeft: 12, textAlign: "right" }}>
                                <div className="row gap1" style={{ justifyContent: "flex-end", alignItems: "center", flexWrap: "nowrap", whiteSpace: "nowrap" }}>
                                  <button className="btn btn-secondary btn-sm" style={{ height: 26, padding: "0 8px", fontSize: 12 }} title="Test inference or tools" onClick={() => setActiveTestModel(m)}>
                                    <Icon name="search" size={12} /> Test
                                  </button>
                                  <button className="btn btn-secondary btn-sm" style={{ height: 26, padding: "0 8px", fontSize: 12 }} title="Edit model attributes" onClick={() => handleOpenEditModel(m)}>
                                    Edit
                                  </button>
                                  <button className="iconbtn" style={{ width: 26, height: 26 }} title="Delete model" onClick={() => handleDeleteModel(m)}>
                                    <Icon name="trash" size={13} />
                                  </button>
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>

                {/* 4. RAG, Embeddings & Reranker Configuration */}
                <Card title="RAG, Embeddings & Reranker">
                  <Field label="Embedding model" help="Used to embed knowledge sources and search queries project-wide. Changing it changes the vector dimension, so re-embed existing sources afterward.">
                    <select className="select" value={embeddingModel} onChange={(e) => setRag({ embedding_model: e.target.value })}>
                      {Array.from(new Set(embeddingModels.map((m) => m.provider))).map((prov) => {
                        const items = embeddingModels.filter((m) => m.provider === prov);
                        const label = items.some((m) => m.billed)
                          ? `${prov} · billed per token (ingest + query)`
                          : `${prov} · open-source · free (offline)`;
                        return (
                          <optgroup key={prov} label={label}>
                            {items.map((m) => (
                              <option key={m.id} value={m.id}>
                                {m.name} · {m.billed ? "billed" : "local, free"} ({m.dim}-dim)
                              </option>
                            ))}
                          </optgroup>
                        );
                      })}
                      {embeddingModel && !embeddingModels.some((m) => m.id === embeddingModel) && <option value={embeddingModel}>{embeddingModel}</option>}
                    </select>
                    {embedStatus?.is_local && (
                      <div className="row gap2" style={{ marginTop: 8, alignItems: "center" }}>
                        <span
                          className="badge"
                          style={{
                            background: embedStatus.cached
                              ? "rgba(34, 197, 94, 0.12)"
                              : "rgba(234, 179, 8, 0.15)",
                            color: embedStatus.cached
                              ? "var(--ok, #22c55e)"
                              : "var(--warn, #eab308)",
                          }}
                        >
                          {embedStatus.cached
                            ? "✓ Weights ready"
                            : `Not downloaded (${embedStatus.approx_size || "local"})`}
                        </span>
                        {!embedStatus.cached && (
                          <button
                            type="button"
                            className="btn btn-sm btn-primary"
                            onClick={handleDownloadEmbed}
                            disabled={downloadingEmbed}
                          >
                            <Icon name="download" size={13} />
                            {downloadingEmbed ? "Downloading…" : "Download weights"}
                          </button>
                        )}
                        {!embedStatus.package_installed && !embedStatus.cached && (
                          <span className="t-micro fg-2" style={{ color: "var(--err)" }}>
                            Requires fastembed installed in backend
                          </span>
                        )}
                      </div>
                    )}
                  </Field>
                  <Field label="Retrieval mode" help="How chunks are matched vs. handed to the agent. Chunk: search and return the same chunks. Parent/child: embed small child chunks for precise matching but feed the agent the larger parent passage for context.">
                    <Segmented
                      options={[{ value: "chunk", label: "Chunk" }, { value: "parent_child", label: "Parent / child" }]}
                      value={rag.retrieval_mode || "chunk"}
                      onChange={(v) => setRag({ retrieval_mode: v })}
                    />
                  </Field>
                  {rag.retrieval_mode === "parent_child" && (
                    <Field label="Child chunk size" help="Size (chars) of the small child chunks that get embedded in parent/child mode. Smaller children = more precise matches.">
                      <input className="input mono" type="number" placeholder={String(DEFAULT_CHILD_CHUNK_SIZE)}
                        value={rag.child_chunk_size ?? ""}
                        onChange={(e) => setRag({ child_chunk_size: parseInt(e.target.value, 10) || undefined })} />
                    </Field>
                  )}
                  <Field label="Reranker model" help="Local cross-encoder used when a retrieval node has rerank on. Runs offline on CPU, no API cost.">
                    <select className="select" value={rag.reranker_model || defaultReranker} onChange={(e) => setRag({ reranker_model: e.target.value })}>
                      {rerankerModels.map((m) => <option key={m.id} value={m.id}>{m.name} · {m.note}{m.default ? " (default)" : ""}</option>)}
                      {rag.reranker_model && !rerankerModels.some((m) => m.id === rag.reranker_model) && <option value={rag.reranker_model}>{rag.reranker_model}</option>}
                    </select>
                  </Field>
                </Card>
              </>
            )}

            {section === "members" && <TeamCard />}

            {section === "apikeys" && (
              <Card title="Secrets" action={<button className="btn btn-secondary btn-sm" onClick={() => setOpen(true)}><Icon name="plus" size={14} />Add secret</button>}>
                <div className="field-help" style={{ marginTop: 0, marginBottom: 8 }}>Write-only - values are encrypted (Fernet) and never returned. Reference as <span className="mono-sm">secret://proj/&lt;name&gt;</span>.</div>
                {secrets.map((s) => (
                  <div key={s.id} className="row spread" style={{ padding: "8px 0", borderTop: "1px solid var(--line)" }}>
                    <div className="row gap2"><Icon name="secret" size={15} style={{ color: "var(--fg-2)" }} /><span className="mono-sm">{s.name}</span><span className="typechip">{s.kind}</span></div>
                    <div className="row gap2"><span className="mono-sm fg-2">••••••</span><span className="t-caption fg-2">v{s.version}</span><span className="iconbtn" role="button" title="Delete secret" onClick={() => removeSecret(s.name)}><Icon name="trash" size={13} /></span></div>
                  </div>
                ))}
                {secrets.length === 0 && <div className="fg-2 t-caption">No secrets yet.</div>}
              </Card>
            )}

            {section === "guardrails" && <GuardrailsCard config={config} setCfg={setCfg} />}

            {section === "versioning" && (
              <Card title="Version history">
                <div className="field-help" style={{ marginTop: 0, marginBottom: 10 }}>Every save/publish of a workflow, agent, tool, component, or auth provider captures a version you can inspect and restore from the editor&apos;s History panel.</div>
                <Field label="Versions kept per entity" help="Older versions beyond this count are pruned. Leave blank to keep all.">
                  <input className="input mono" type="number" min={1} step={1} style={{ width: 140 }} placeholder="unlimited"
                    value={config.version_history_limit ?? ""}
                    onChange={(e) => setCfg({ version_history_limit: parseInt(e.target.value, 10) || undefined })} />
                </Field>
                <label className="row spread" style={{ padding: "8px 0" }}>
                  <div><div className="t-body-sm" style={{ fontWeight: 600 }}>Snapshot on publish</div><div className="field-help" style={{ marginTop: 0 }}>Capture a labeled version each time a workflow is published.</div></div>
                  <Toggle on={versioning.snapshot_on_publish !== false} onChange={(v) => setCfg({ versioning: { ...versioning, snapshot_on_publish: v } })} />
                </label>
              </Card>
            )}

            {section === "observability" && (
              <>
                <Card title="Trace redaction">
                  <label className="row spread" style={{ padding: "8px 0" }}>
                    <div><div className="t-body-sm" style={{ fontWeight: 600 }}>Redact PII in traces</div><div className="field-help" style={{ marginTop: 0 }}>Mask emails, phone numbers, and card-like values in stored span inputs/outputs.</div></div>
                    <Toggle on={!!observability.redact_pii} onChange={(v) => setCfg({ observability: { ...observability, redact_pii: v } })} />
                  </label>
                  <label className="row spread" style={{ padding: "8px 0" }}>
                    <div><div className="t-body-sm" style={{ fontWeight: 600 }}>Store message bodies</div><div className="field-help" style={{ marginTop: 0 }}>Persist full user/assistant text on traces. Turn off to keep only metrics (tokens, latency, cost).</div></div>
                    <Toggle on={observability.store_message_bodies !== false} onChange={(v) => setCfg({ observability: { ...observability, store_message_bodies: v } })} />
                  </label>
                </Card>
                <Card title="Retention">
                  <Field label="Trace retention (days)" help="Traces and conversations older than this are eligible for purge. Leave blank to keep indefinitely.">
                    <input className="input mono" type="number" min={1} step={1} style={{ width: 140 }} placeholder="keep all"
                      value={observability.retention_days ?? ""}
                      onChange={(e) => setCfg({ observability: { ...observability, retention_days: parseInt(e.target.value, 10) || undefined } })} />
                  </Field>
                  <label className="row spread" style={{ padding: "8px 0" }}>
                    <div><div className="t-body-sm" style={{ fontWeight: 600 }}>Scheduled cleanup</div><div className="field-help" style={{ marginTop: 0 }}>Run a periodic job to purge data past the retention window.</div></div>
                    <Toggle on={!!scheduler.cleanup_enabled} onChange={(v) => setCfg({ scheduler: { ...scheduler, cleanup_enabled: v } })} />
                  </label>
                </Card>
              </>
            )}

            {section === "advanced" && (
              <>
                <Card title="Execution limits">
                  <Field label="Max tokens / run" help="Safeguard cap on total tokens for a single run. Leave blank for unconstrained.">
                    <input
                      className="input mono"
                      type="number"
                      min={0}
                      step={1000}
                      placeholder="unconstrained"
                      value={budgets.max_tokens_per_run ?? ""}
                      onChange={(e) =>
                        setCfg({
                          budgets: {
                            ...budgets,
                            max_tokens_per_run: parseInt(e.target.value, 10) || undefined,
                          },
                        })
                      }
                    />
                  </Field>
                </Card>
                <Card title="Feature flags">
                  {[["code_nodes", "Code nodes", "Allow sandboxed code execution"], ["remote_sandbox", "Remote sandbox", "Use E2B/Modal/Daytona for code"], ["advanced_scripts", "Advanced scripts", "RestrictedPython custom auth scripts"]].map(([k, label, desc]) => (
                    <label key={k} className="row spread" style={{ padding: "8px 0" }}>
                      <div><div className="t-body-sm" style={{ fontWeight: 600 }}>{label}</div><div className="field-help" style={{ marginTop: 0 }}>{desc}</div></div>
                      <Toggle on={!!features[k]} onChange={(v) => setCfg({ features: { ...features, [k]: v } })} />
                    </label>
                  ))}
                </Card>

              </>
            )}

            {section === "history" && <SettingsHistory project={project} />}
          </div>
        </div>
      </div>

      <Modal open={open} onClose={() => setOpen(false)} title="Add secret" width={460}
        footer={<><button className="btn btn-ghost" onClick={() => setOpen(false)}>Cancel</button><button className="btn btn-primary" onClick={addSecret}>Save secret</button></>}>
        <Field label="Name"><input className="input mono" value={secForm.name} onChange={(e) => setSecForm((f) => ({ ...f, name: e.target.value }))} placeholder="openai_key" /></Field>
        <Field label="Value" help="Encrypted at rest; never shown again."><input className="input mono" type="password" value={secForm.value} onChange={(e) => setSecForm((f) => ({ ...f, value: e.target.value }))} /></Field>
        <Field label="Kind"><input className="input" value={secForm.kind} onChange={(e) => setSecForm((f) => ({ ...f, kind: e.target.value }))} /></Field>
      </Modal>

      {/* Add Model Wizard Modal (Server configuration + Model registration) */}
      <Modal
        open={addModelOpen}
        onClose={() => setAddModelOpen(false)}
        title={`Add Registered Model (Step ${wizardStep} of 4)`}
        width={620}
        footer={
          <div className="row spread" style={{ width: "100%" }}>
            <div>
              {wizardStep > 1 && (
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => setWizardStep((s) => (s - 1) as any)}
                >
                  Back
                </button>
              )}
            </div>
            <div className="row gap2">
              <button type="button" className="btn btn-ghost" onClick={() => setAddModelOpen(false)}>Cancel</button>
              {wizardStep === 1 && isConnectingNewServer && (
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={serverSaving || !serverForm.name.trim() || !serverForm.base_url.trim()}
                  onClick={handleCreateServer}
                >
                  {serverSaving ? "Connecting…" : "Connect & Discover Models"}
                </button>
              )}
              {wizardStep === 1 && !isConnectingNewServer && (
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={!selectedServerId || discovering}
                  onClick={() => handleSelectServerInWizard(selectedServerId)}
                >
                  {discovering ? "Discovering…" : "Next: Discover Models"}
                </button>
              )}
              {wizardStep === 2 && (
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={!wireModelInput.trim()}
                  onClick={() => {
                    setModelConfigForm((f) => ({
                      ...f,
                      displayName: f.displayName || wireModelInput.trim(),
                    }));
                    setWizardStep(3);
                  }}
                >
                  Next: Configure
                </button>
              )}
              {wizardStep === 3 && (
                <div className="row gap2">
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => setWizardStep(4)}
                  >
                    Review Summary →
                  </button>
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={savingModel}
                    onClick={handleRegisterModelInWizard}
                  >
                    {savingModel ? "Registering…" : "Register Model"}
                  </button>
                </div>
              )}
              {wizardStep === 4 && (
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={savingModel}
                  onClick={handleRegisterModelInWizard}
                >
                  {savingModel ? "Registering…" : "Register Model"}
                </button>
              )}
            </div>
          </div>
        }
      >
        {/* Full-width Stepper Widget */}
        <div style={{ width: "100%", marginBottom: 22, padding: "4px 0" }}>
          <div className="row spread" style={{ position: "relative", alignItems: "flex-start" }}>
            {/* Background connecting track */}
            <div
              style={{
                position: "absolute",
                top: 13,
                left: "12%",
                right: "12%",
                height: 2,
                background: "var(--line)",
                zIndex: 0,
              }}
            >
              {/* Active filled track segment */}
              <div
                style={{
                  height: "100%",
                  width: `${((wizardStep - 1) / 3) * 100}%`,
                  background: "var(--accent)",
                  transition: "width 0.25s ease",
                }}
              />
            </div>

            {[
              { n: 1, title: "Server", sub: "Host & Engine" },
              { n: 2, title: "Model", sub: "Discover / ID" },
              { n: 3, title: "Configure", sub: "Tuning & Context" },
              { n: 4, title: "Register", sub: "Validate & Save" },
            ].map((st) => {
              const isPast = wizardStep > st.n;
              const isCurr = wizardStep === st.n;
              return (
                <div
                  key={st.n}
                  className="col"
                  style={{
                    alignItems: "center",
                    position: "relative",
                    zIndex: 1,
                    flex: 1,
                    textAlign: "center",
                  }}
                >
                  <div
                    style={{
                      width: 26,
                      height: 26,
                      borderRadius: "50%",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: 11,
                      fontWeight: 600,
                      background: isPast
                        ? "var(--ok, #10b981)"
                        : isCurr
                        ? "var(--accent)"
                        : "var(--bg-1)",
                      color: isPast || isCurr ? "#fff" : "var(--fg-2)",
                      border: isPast || isCurr ? "none" : "1px solid var(--line)",
                      boxShadow: isCurr ? "0 0 0 3px rgba(99, 102, 241, 0.22)" : "none",
                      transition: "all 0.2s ease",
                    }}
                  >
                    {isPast ? <Icon name="check" size={13} style={{ strokeWidth: 2.2 }} /> : st.n}
                  </div>
                  <div style={{ marginTop: 5 }}>
                    <div
                      style={{
                        fontSize: 12,
                        fontWeight: isCurr ? 600 : 500,
                        color: isCurr ? "var(--fg-1)" : isPast ? "var(--fg-1)" : "var(--fg-2)",
                      }}
                    >
                      {st.title}
                    </div>
                    <div
                      className="fg-2"
                      style={{
                        fontSize: 10,
                        marginTop: 1,
                      }}
                    >
                      {st.sub}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Step 1: Select or Connect Server */}
        {wizardStep === 1 && isConnectingNewServer && (
          <div className="col gap2">
            <div className="row spread" style={{ alignItems: "center" }}>
              <div className="field-help" style={{ margin: 0 }}>
                Configure connection to inference engine or cloud provider.
              </div>
              {modelServers.length > 0 && (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  style={{ fontSize: 12 }}
                  onClick={() => setIsConnectingNewServer(false)}
                >
                  ← Select from existing servers
                </button>
              )}
            </div>

            {/* Searchable Model Provider Dropdown */}
            <Field label="Inference Engine / Provider" help="Select an inference protocol, local engine, or cloud provider.">
              <div style={{ position: "relative" }}>
                <div
                  role="button"
                  tabIndex={0}
                  className="input"
                  onClick={() => setProviderDropdownOpen((o) => !o)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    cursor: "pointer",
                    height: 38,
                    padding: "0 10px",
                    background: "var(--bg-1)",
                  }}
                >
                  <div className="row gap2" style={{ alignItems: "center" }}>
                    <div
                      style={{
                        width: 24,
                        height: 24,
                        borderRadius: 4,
                        background: "var(--bg-2)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        border: "1px solid var(--line)",
                      }}
                    >
                      <Icon name={activePreset.icon} size={14} style={{ color: "var(--accent)" }} />
                    </div>
                    <span style={{ fontWeight: 600, fontSize: 13 }}>{activePreset.label}</span>
                    <span className="typechip" style={{ fontSize: 10, marginLeft: 2 }}>{activePreset.tag}</span>
                  </div>
                  <Icon
                    name="chevdown"
                    size={14}
                    style={{
                      color: "var(--fg-2)",
                      transform: providerDropdownOpen ? "rotate(180deg)" : "none",
                      transition: "transform 0.15s ease",
                    }}
                  />
                </div>

                {providerDropdownOpen && (
                  <div
                    style={{
                      position: "absolute",
                      top: "calc(100% + 4px)",
                      left: 0,
                      right: 0,
                      background: "var(--bg-1)",
                      border: "1px solid var(--line)",
                      borderRadius: 4,
                      boxShadow: "0 6px 20px rgba(0,0,0,0.22)",
                      zIndex: 100,
                      overflow: "hidden",
                    }}
                  >
                    <div style={{ padding: "8px 10px", borderBottom: "1px solid var(--line)", background: "var(--bg-2)" }} className="row gap2">
                      <Icon name="search" size={13} style={{ color: "var(--fg-2)", alignSelf: "center" }} />
                      <input
                        className="input"
                        autoFocus
                        placeholder="Search providers (Ollama, vLLM, OpenAI, Anthropic, Gemini...)"
                        value={providerSearchQuery}
                        onChange={(e) => setProviderSearchQuery(e.target.value)}
                        style={{
                          border: "none",
                          height: 24,
                          fontSize: 12,
                          padding: "0 4px",
                          outline: "none",
                          background: "transparent",
                          width: "100%",
                        }}
                      />
                    </div>

                    <div className="col" style={{ maxHeight: 240, overflowY: "auto", padding: 4 }}>
                      {filteredPresets.length === 0 ? (
                        <div className="fg-2 t-caption" style={{ padding: "12px 10px", textAlign: "center" }}>
                          No matching provider found.
                        </div>
                      ) : (
                        filteredPresets.map((p) => {
                          const isSel = serverForm.provider_type === p.type;
                          return (
                            <div
                              key={p.id}
                              role="button"
                              onClick={() => {
                                setServerForm((f) => ({
                                  ...f,
                                  name: f.name === "Local Ollama" || SERVER_PRESETS.some((s) => s.label === f.name) ? p.label : f.name,
                                  provider_type: p.type,
                                  base_url: p.url,
                                }));
                                setServerTestResult(null);
                                setProviderDropdownOpen(false);
                                setProviderSearchQuery("");
                              }}
                              style={{
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "space-between",
                                padding: "8px 10px",
                                borderRadius: 4,
                                background: isSel ? "var(--bg-2)" : "transparent",
                                cursor: "pointer",
                                borderBottom: "1px solid var(--line-subtle, transparent)",
                              }}
                              onMouseEnter={(e) => {
                                if (!isSel) e.currentTarget.style.background = "var(--bg-2)";
                              }}
                              onMouseLeave={(e) => {
                                if (!isSel) e.currentTarget.style.background = "transparent";
                              }}
                            >
                              <div className="row gap2" style={{ alignItems: "center" }}>
                                <div
                                  style={{
                                    width: 24,
                                    height: 24,
                                    borderRadius: 4,
                                    background: isSel ? "var(--bg-1)" : "var(--bg-2)",
                                    display: "flex",
                                    alignItems: "center",
                                    justifyContent: "center",
                                    border: "1px solid var(--line)",
                                  }}
                                >
                                  <Icon name={p.icon} size={14} style={{ color: isSel ? "var(--accent)" : "var(--fg-1)" }} />
                                </div>
                                <div className="col">
                                  <div style={{ fontWeight: 600, fontSize: 13 }}>{p.label}</div>
                                  <div className="fg-2" style={{ fontSize: 11 }}>{p.desc}</div>
                                </div>
                              </div>
                              <div className="row gap2" style={{ alignItems: "center" }}>
                                <span className="typechip" style={{ fontSize: 10 }}>{p.tag}</span>
                                {isSel && <Icon name="check" size={14} style={{ color: "var(--accent)" }} />}
                              </div>
                            </div>
                          );
                        })
                      )}
                    </div>
                  </div>
                )}
              </div>
            </Field>

            <Field label="Server Name" help="Display name to identify this endpoint in Alberto.">
              <input
                className="input"
                value={serverForm.name}
                onChange={(e) => setServerForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="e.g. Local Ollama"
              />
            </Field>

            <Field label="Endpoint URL" help="Base URL of server. Path /v1 is normalized automatically.">
              <input
                className="input mono"
                value={serverForm.base_url}
                onChange={(e) => setServerForm((f) => ({ ...f, base_url: e.target.value }))}
                placeholder="http://localhost:11434"
              />
            </Field>

            <Field label="API Key (optional)" help="Stored securely and never returned in plain text. Leave blank for local unauthenticated engines.">
              <input
                className="input mono"
                type="password"
                value={serverForm.api_key}
                onChange={(e) => setServerForm((f) => ({ ...f, api_key: e.target.value }))}
                placeholder="Optional API key"
              />
            </Field>

            <div style={{ marginTop: 6 }}>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={handleTestServer}
                disabled={serverTesting || !serverForm.base_url.trim()}
              >
                <Icon name="search" size={13} /> {serverTesting ? "Testing endpoint…" : "Test Connection"}
              </button>
            </div>

            {serverTestResult && (
              <div
                style={{
                  padding: 8,
                  borderRadius: 4,
                  background: serverTestResult.ok ? "rgba(16, 185, 129, 0.08)" : "rgba(239, 68, 68, 0.08)",
                  border: `1px solid ${serverTestResult.ok ? "var(--ok, #10b981)" : "var(--err, #ef4444)"}`,
                  marginTop: 6,
                }}
              >
                {serverTestResult.ok ? (
                  <span className="t-body-sm" style={{ fontWeight: 600, color: "var(--ok, #10b981)" }}>
                    ✓ Connected successfully ({serverTestResult.latency_ms}ms). Discovered {serverTestResult.discovered_count} model(s).
                  </span>
                ) : (
                  <span className="t-body-sm" style={{ color: "var(--err, #ef4444)" }}>
                    ✕ Connection failed: {serverTestResult.error || "Unable to reach endpoint"}
                  </span>
                )}
              </div>
            )}
          </div>
        )}

        {wizardStep === 1 && !isConnectingNewServer && (
          <div className="col gap2">
            <div className="row spread" style={{ alignItems: "center" }}>
              <div className="field-help" style={{ margin: 0 }}>
                Choose which inference server hosts the model you want to register:
              </div>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                style={{ fontSize: 12 }}
                onClick={() => {
                  setServerForm({ name: "Local Ollama", provider_type: "ollama", base_url: "http://localhost:11434", api_key: "" });
                  setServerTestResult(null);
                  setIsConnectingNewServer(true);
                }}
              >
                <Icon name="plus" size={12} /> Connect New Server
              </button>
            </div>

            {modelServers.length === 0 ? (
              <div className="col gap2" style={{ padding: 20, background: "var(--bg-1)", borderRadius: 4, textAlign: "center" }}>
                <span className="fg-2">No servers configured yet.</span>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  style={{ alignSelf: "center" }}
                  onClick={() => setIsConnectingNewServer(true)}
                >
                  <Icon name="plus" size={12} /> Connect an Inference Server
                </button>
              </div>
            ) : (
              <div className="col gap1">
                {modelServers.map((srv) => {
                  const sel = selectedServerId === srv.id;
                  return (
                    <div
                      key={srv.id}
                      role="button"
                      onClick={() => setSelectedServerId(srv.id)}
                      style={{
                        padding: "10px 12px",
                        borderRadius: 4,
                        border: `1px solid ${sel ? "var(--accent)" : "var(--line)"}`,
                        background: sel ? "var(--bg-2)" : "var(--bg-1)",
                        cursor: "pointer",
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                      }}
                    >
                      <div className="col">
                        <div className="row gap2" style={{ alignItems: "center" }}>
                          <span style={{ fontWeight: 600 }}>{srv.name}</span>
                          <span className="typechip" style={{ fontSize: 11 }}>{srv.provider_type}</span>
                          {srv.registered_models_count > 0 && (
                            <span className="t-caption fg-2">
                              ({srv.registered_models_count} model{srv.registered_models_count === 1 ? "" : "s"})
                            </span>
                          )}
                        </div>
                        <span className="mono-sm fg-2" style={{ fontSize: 11, marginTop: 2 }}>{srv.base_url}</span>
                      </div>

                      <div className="row gap1" onClick={(e) => e.stopPropagation()}>
                        <span
                          className="iconbtn"
                          role="button"
                          title="Delete server"
                          onClick={() => handleDeleteServer(srv.id, srv.name)}
                        >
                          <Icon name="trash" size={13} />
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {wizardStep === 2 && (
          <div className="col gap2">
            <div className="field-help" style={{ marginTop: 0 }}>
              Pick a discovered model from the server or enter a model identifier manually.
            </div>

            {discovering ? (
              <div className="fg-2 t-caption">Contacting server to discover available models…</div>
            ) : serverDiscoveredModels.length > 0 ? (
              <div>
                <span className="t-caption fg-2" style={{ marginBottom: 6, display: "block" }}>
                  Discovered on server ({serverDiscoveredModels.length}):
                </span>
                <div className="row gap1 wrap" style={{ maxHeight: 180, overflowY: "auto", border: "1px solid var(--line)", padding: 8, borderRadius: 4 }}>
                  {serverDiscoveredModels.map((m) => (
                    <button
                      key={m.model_name}
                      type="button"
                      className={`btn btn-sm ${wireModelInput === m.model_name ? "btn-primary" : "btn-secondary"}`}
                      style={{ fontSize: 12, borderRadius: 4 }}
                      onClick={() => handlePickDiscoveredModel(m)}
                    >
                      {m.display_name || m.model_name}
                      {m.supports_tools && <span style={{ marginLeft: 4, opacity: 0.7, fontSize: 10 }}>🔧</span>}
                      {m.supports_vision && <span style={{ marginLeft: 2, opacity: 0.7, fontSize: 10 }}>👁</span>}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="fg-2 t-caption">No models returned automatically. You can enter the model ID manually below.</div>
            )}

            <Field label="Model Identifier (Provider ID)" help="Exact name passed to the engine (e.g. llama3.2:latest, gpt-4o, claude-3-7-sonnet).">
              <input
                className="input mono"
                value={wireModelInput}
                onChange={(e) => setWireModelInput(e.target.value)}
                placeholder="e.g. qwen2.5:7b or gpt-4o"
              />
            </Field>
          </div>
        )}

        {wizardStep === 3 && (
          <div className="col gap2">
            <Field label="Display Name / Alias" help="Friendly name shown in Alberto agent and chat selectors.">
              <input
                className="input"
                value={modelConfigForm.displayName}
                onChange={(e) => setModelConfigForm((f) => ({ ...f, displayName: e.target.value }))}
                placeholder="e.g. Qwen 2.5 7B (Fast)"
              />
            </Field>

            <Field label="Context Window (Configured Tokens)" help="Tokens allocated to Alberto prompts and history for this model.">
              <input
                className="input mono"
                type="number"
                min={1024}
                step={1024}
                value={modelConfigForm.contextConfigured}
                onChange={(e) => setModelConfigForm((f) => ({ ...f, contextConfigured: parseInt(e.target.value, 10) || 32768 }))}
              />
            </Field>

            <div className="row gap3 wrap" style={{ padding: "4px 0" }}>
              <label className="row gap2" style={{ alignItems: "center", cursor: "pointer" }}>
                <Toggle
                  on={modelConfigForm.supportsTools}
                  onChange={(v) => setModelConfigForm((f) => ({ ...f, supportsTools: v }))}
                />
                <span className="t-body-sm">Supports Function / Tool Calling</span>
              </label>

              <label className="row gap2" style={{ alignItems: "center", cursor: "pointer" }}>
                <Toggle
                  on={modelConfigForm.supportsVision}
                  onChange={(v) => setModelConfigForm((f) => ({ ...f, supportsVision: v }))}
                />
                <span className="t-body-sm">Supports Vision</span>
              </label>
            </div>

            <div className="row gap2">
              <div style={{ flex: 1 }}>
                <Field label="Temperature" help="0.0 = deterministic, 1.0 = creative.">
                  <input
                    className="input mono"
                    type="number"
                    step={0.05}
                    min={0}
                    max={2}
                    value={modelConfigForm.temperature}
                    onChange={(e) => setModelConfigForm((f) => ({ ...f, temperature: parseFloat(e.target.value) || 0.3 }))}
                  />
                </Field>
              </div>
              <div style={{ flex: 1 }}>
                <Field label="Top-P" help="Nucleus sampling probability.">
                  <input
                    className="input mono"
                    type="number"
                    step={0.05}
                    min={0}
                    max={1}
                    value={modelConfigForm.topP}
                    onChange={(e) => setModelConfigForm((f) => ({ ...f, topP: parseFloat(e.target.value) || 0.9 }))}
                  />
                </Field>
              </div>
              <div style={{ flex: 1 }}>
                <Field label="Max Output Tokens" help="Upper token generation bound.">
                  <input
                    className="input mono"
                    type="number"
                    step={512}
                    min={256}
                    value={modelConfigForm.maxOutputTokens}
                    onChange={(e) => setModelConfigForm((f) => ({ ...f, maxOutputTokens: parseInt(e.target.value, 10) || 4096 }))}
                  />
                </Field>
              </div>
            </div>

            <label className="row gap2" style={{ alignItems: "center", cursor: "pointer", marginTop: 4 }}>
              <Toggle
                on={modelConfigForm.setAsDefault}
                onChange={(v) => setModelConfigForm((f) => ({ ...f, setAsDefault: v }))}
              />
              <span className="t-body-sm" style={{ fontWeight: 600 }}>Set as Project Default Execution Model</span>
            </label>
          </div>
        )}

        {wizardStep === 4 && (
          <div className="col gap2">
            <div className="field-help" style={{ marginTop: 0 }}>
              Review model parameters before saving to the Alberto registry. Zero-Phantom policy: Only registered models can be executed.
            </div>

            <div style={{ padding: 12, borderRadius: 4, background: "var(--bg-1)", border: "1px solid var(--line)" }} className="col gap1">
              <div className="row spread">
                <span className="fg-2">Model Alias:</span>
                <span style={{ fontWeight: 600 }}>{modelConfigForm.displayName || wireModelInput}</span>
              </div>
              <div className="row spread">
                <span className="fg-2">Provider Model ID:</span>
                <span className="mono-sm">{wireModelInput}</span>
              </div>
              <div className="row spread">
                <span className="fg-2">Inference Server:</span>
                <span>{modelServers.find((s) => s.id === selectedServerId)?.name || selectedServerId}</span>
              </div>
              <div className="row spread">
                <span className="fg-2">Context Window:</span>
                <span className="mono-sm">{modelConfigForm.contextConfigured.toLocaleString()} tokens</span>
              </div>
              <div className="row spread">
                <span className="fg-2">Capabilities:</span>
                <span>
                  {modelConfigForm.supportsTools && "Tools "}
                  {modelConfigForm.supportsVision && "Vision "}
                  {!modelConfigForm.supportsTools && !modelConfigForm.supportsVision && "Basic"}
                </span>
              </div>
              <div className="row spread">
                <span className="fg-2">Default Tuning:</span>
                <span className="mono-sm">T={modelConfigForm.temperature}, P={modelConfigForm.topP}, max={modelConfigForm.maxOutputTokens}</span>
              </div>
              {modelConfigForm.setAsDefault && (
                <div className="row spread" style={{ color: "var(--ok, #10b981)", fontWeight: 600 }}>
                  <span>Default Model:</span>
                  <span>Will be set as active default</span>
                </div>
              )}
            </div>
          </div>
        )}
      </Modal>

      {/* 3. Edit Model Modal */}
      <Modal
        open={!!editModelModal}
        onClose={() => setEditModelModal(null)}
        title={`Edit Model: ${editModelModal?.display_name || ""}`}
        width={500}
        footer={
          <>
            <button className="btn btn-ghost" onClick={() => setEditModelModal(null)}>Cancel</button>
            <button className="btn btn-primary" onClick={handleSaveEditModel}>Save Changes</button>
          </>
        }
      >
        {editModelModal && (
          <div className="col gap2">
            <Field label="Display Name / Alias" help="Friendly name shown in model pickers.">
              <input
                className="input"
                value={editModelForm.displayName}
                onChange={(e) => setEditModelForm((f) => ({ ...f, displayName: e.target.value }))}
              />
            </Field>

            <Field label="Configured Context Window" help="Max tokens per prompt/history context.">
              <input
                className="input mono"
                type="number"
                min={1024}
                step={1024}
                value={editModelForm.contextConfigured}
                onChange={(e) => setEditModelForm((f) => ({ ...f, contextConfigured: parseInt(e.target.value, 10) || 32768 }))}
              />
            </Field>

            <div className="row gap3 wrap">
              <label className="row gap2" style={{ alignItems: "center", cursor: "pointer" }}>
                <Toggle
                  on={editModelForm.supportsTools}
                  onChange={(v) => setEditModelForm((f) => ({ ...f, supportsTools: v }))}
                />
                <span className="t-body-sm">Tools</span>
              </label>
              <label className="row gap2" style={{ alignItems: "center", cursor: "pointer" }}>
                <Toggle
                  on={editModelForm.supportsVision}
                  onChange={(v) => setEditModelForm((f) => ({ ...f, supportsVision: v }))}
                />
                <span className="t-body-sm">Vision</span>
              </label>
              <label className="row gap2" style={{ alignItems: "center", cursor: "pointer" }}>
                <Toggle
                  on={editModelForm.enabled}
                  onChange={(v) => setEditModelForm((f) => ({ ...f, enabled: v }))}
                />
                <span className="t-body-sm">Enabled for execution</span>
              </label>
            </div>

            <div className="row gap2">
              <div style={{ flex: 1 }}>
                <Field label="Temperature">
                  <input
                    className="input mono"
                    type="number"
                    step={0.05}
                    min={0}
                    max={2}
                    value={editModelForm.temperature}
                    onChange={(e) => setEditModelForm((f) => ({ ...f, temperature: parseFloat(e.target.value) || 0.3 }))}
                  />
                </Field>
              </div>
              <div style={{ flex: 1 }}>
                <Field label="Top-P">
                  <input
                    className="input mono"
                    type="number"
                    step={0.05}
                    min={0}
                    max={1}
                    value={editModelForm.topP}
                    onChange={(e) => setEditModelForm((f) => ({ ...f, topP: parseFloat(e.target.value) || 0.9 }))}
                  />
                </Field>
              </div>
              <div style={{ flex: 1 }}>
                <Field label="Max Output Tokens">
                  <input
                    className="input mono"
                    type="number"
                    step={512}
                    min={256}
                    value={editModelForm.maxOutputTokens}
                    onChange={(e) => setEditModelForm((f) => ({ ...f, maxOutputTokens: parseInt(e.target.value, 10) || 4096 }))}
                  />
                </Field>
              </div>
            </div>
          </div>
        )}
      </Modal>

      {/* 4. Discover Server Models Modal */}
      <Modal
        open={!!discoverServerModal}
        onClose={() => setDiscoverServerModal(null)}
        title={`Discovered Models on ${discoverServerModal?.name || "Server"}`}
        width={560}
        footer={<button className="btn btn-secondary" onClick={() => setDiscoverServerModal(null)}>Close</button>}
      >
        {discoverModalLoading ? (
          <div className="fg-2 t-caption" style={{ padding: 16, textAlign: "center" }}>
            Contacting server to discover available models…
          </div>
        ) : discoverModalList.length === 0 ? (
          <div className="fg-2 t-caption" style={{ padding: 16, textAlign: "center" }}>
            No models discovered on this server or provider does not support catalogue listing.
          </div>
        ) : (
          <div className="col gap2">
            <div className="field-help" style={{ marginTop: 0 }}>
              Found {discoverModalList.length} model(s). Click &quot;Register&quot; to add a model to Alberto&apos;s registry with recommended defaults.
            </div>
            <div className="col gap1" style={{ maxHeight: 360, overflowY: "auto" }}>
              {discoverModalList.map((m) => {
                const alreadyReg = registeredModels.some(
                  (r) => r.server_id === discoverServerModal?.id && r.model_name === m.model_name
                );
                return (
                  <div
                    key={m.model_name}
                    className="card"
                    style={{
                      padding: "8px 12px",
                      background: "var(--bg-1)",
                      border: "1px solid var(--line)",
                      borderRadius: 4,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                    }}
                  >
                    <div className="col">
                      <div className="row gap2" style={{ alignItems: "center" }}>
                        <span style={{ fontWeight: 600 }}>{m.display_name || m.model_name}</span>
                        {m.supports_tools && <span className="pill pill-ok" style={{ fontSize: 10 }}>Tools</span>}
                        {m.supports_vision && <span className="pill pill-ok" style={{ fontSize: 10 }}>Vision</span>}
                      </div>
                      <span className="mono-sm fg-2" style={{ fontSize: 11 }}>{m.model_name}</span>
                    </div>

                    <div>
                      {alreadyReg ? (
                        <span className="pill" style={{ fontSize: 10, background: "var(--line)", color: "var(--fg-2)" }}>Registered</span>
                      ) : (
                        <button
                          className="btn btn-primary btn-sm"
                          style={{ fontSize: 11, padding: "2px 8px" }}
                          onClick={() => handleQuickRegisterFromDiscover(m)}
                        >
                          Register
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </Modal>

      {/* 5. Active Test Modal */}
      <Modal
        open={!!activeTestModel}
        onClose={() => {
          setActiveTestModel(null);
          setTestInfResult(null);
          setTestToolsResult(null);
        }}
        title={`Test Model: ${activeTestModel?.display_name || ""}`}
        width={540}
        footer={
          <button
            className="btn btn-secondary"
            onClick={() => {
              setActiveTestModel(null);
              setTestInfResult(null);
              setTestToolsResult(null);
            }}
          >
            Close
          </button>
        }
      >
        {activeTestModel && (
          <div className="col gap3">
            <div className="row spread" style={{ padding: "8px 12px", background: "var(--bg-1)", borderRadius: 4, border: "1px solid var(--line)" }}>
              <div>
                <span className="fg-2" style={{ fontSize: 11 }}>Provider Model ID:</span>
                <div className="mono-sm" style={{ fontWeight: 600 }}>{activeTestModel.model_name}</div>
              </div>
              <div>
                <span className="fg-2" style={{ fontSize: 11 }}>Server:</span>
                <div>{activeTestModel.server_name} ({activeTestModel.provider_type})</div>
              </div>
            </div>

            {/* Inference Test */}
            <div className="card" style={{ padding: 12, borderRadius: 4, border: "1px solid var(--line)" }}>
              <div className="row spread" style={{ marginBottom: 8 }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 13 }}>Test Inference</div>
                  <div className="fg-2" style={{ fontSize: 11 }}>Sends a lightweight prompt to verify generation &amp; latency.</div>
                </div>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={testInfRunning}
                  onClick={() => handleRunInferenceTest(activeTestModel.id)}
                >
                  <Icon name="search" size={12} /> {testInfRunning ? "Testing…" : "Run Test"}
                </button>
              </div>

              {testInfResult && (
                <div
                  style={{
                    padding: 8,
                    borderRadius: 4,
                    background: testInfResult.ok ? "rgba(16, 185, 129, 0.08)" : "rgba(239, 68, 68, 0.08)",
                    border: `1px solid ${testInfResult.ok ? "var(--ok, #10b981)" : "var(--err, #ef4444)"}`,
                  }}
                >
                  {testInfResult.ok ? (
                    <div className="col gap1">
                      <span className="t-body-sm" style={{ fontWeight: 600, color: "var(--ok, #10b981)" }}>
                        ✓ Success ({testInfResult.latency_ms}ms)
                      </span>
                      {testInfResult.snippet && (
                        <div className="mono-sm fg-1" style={{ fontSize: 11, background: "var(--bg-2)", padding: 6, borderRadius: 3 }}>
                          {testInfResult.snippet}
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="t-body-sm" style={{ color: "var(--err, #ef4444)" }}>
                      ✕ Failed: {testInfResult.error}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Tool-calling Test */}
            <div className="card" style={{ padding: 12, borderRadius: 4, border: "1px solid var(--line)" }}>
              <div className="row spread" style={{ marginBottom: 8 }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 13 }}>Test Tool Calling</div>
                  <div className="fg-2" style={{ fontSize: 11 }}>Passes a harmless test tool without executing any real devices.</div>
                </div>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={testToolsRunning}
                  onClick={() => handleRunToolTest(activeTestModel.id)}
                >
                  <Icon name="search" size={12} /> {testToolsRunning ? "Testing…" : "Run Tool Test"}
                </button>
              </div>

              {testToolsResult && (
                <div
                  style={{
                    padding: 8,
                    borderRadius: 4,
                    background: testToolsResult.ok ? "rgba(16, 185, 129, 0.08)" : "rgba(239, 68, 68, 0.08)",
                    border: `1px solid ${testToolsResult.ok ? "var(--ok, #10b981)" : "var(--err, #ef4444)"}`,
                  }}
                >
                  {testToolsResult.ok ? (
                    <div className="col gap1">
                      <span className="t-body-sm" style={{ fontWeight: 600, color: "var(--ok, #10b981)" }}>
                        ✓ Success ({testToolsResult.latency_ms}ms)
                      </span>
                      <div className="t-caption fg-2">
                        Tool invoked: <span className="mono-sm">{testToolsResult.toolCalled || "alberto_test_ping"}</span>
                      </div>
                    </div>
                  ) : (
                    <div className="t-body-sm" style={{ color: "var(--err, #ef4444)" }}>
                      ✕ Failed: {testToolsResult.error}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}

/* Settings > History: read-only per-section change log. Diffs consecutive project snapshots
   (captured on every settings save) and buckets each changed field under the matching settings
   tab. No restore - it's a log. Secret values are masked. */
function fmtVal(v: any): string {
  if (v === undefined || v === null || v === "") return "—";
  if (typeof v === "object") { try { return JSON.stringify(v); } catch { return String(v); } }
  return String(v);
}
function flattenConfig(snap: Record<string, any>): Record<string, any> {
  // Merge the top-level snapshot fields with config.* so section bucketing keys off the
  // outermost key (e.g. "budgets.max_usd" -> budgets), then flatten nested objects to dot-paths.
  const src = { name: snap.name, slug: snap.slug, description: snap.description, status: snap.status, ...(snap.config || {}) };
  const out: Record<string, any> = {};
  const walk = (o: any, prefix: string) => {
    for (const [k, v] of Object.entries(o || {})) {
      const path = prefix ? `${prefix}.${k}` : k;
      if (v && typeof v === "object" && !Array.isArray(v)) walk(v, path);
      else out[path] = v;
    }
  };
  walk(src, "");
  return out;
}
type FieldChange = { path: string; from: any; to: any };
type ChangeSet = { id: string; author?: string | null; at?: string | null; changes: FieldChange[] };

function SettingsHistory({ project }: { project: any }) {
  const [tab, setTab] = useState<SectionId>("models");
  const [versions, setVersions] = useState<ProjectVersion[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!project?.id) return;
    setVersions(null); setErr(null);
    api.projectConfigHistory(project.id).then(setVersions).catch((e) => setErr(String(e?.message || e)));
  }, [project?.id]);

  // The list is newest-first, so [i+1] is the older snapshot each version is diffed against.
  const changeSets: ChangeSet[] = useMemo(() => {
    if (!versions) return [];
    const out: ChangeSet[] = [];
    for (let i = 0; i < versions.length - 1; i++) {
      const newer = flattenConfig(versions[i].snapshot || {});
      const older = flattenConfig(versions[i + 1].snapshot || {});
      const changes: FieldChange[] = [];
      new Set([...Object.keys(newer), ...Object.keys(older)]).forEach((k) => {
        if (JSON.stringify(newer[k]) !== JSON.stringify(older[k])) changes.push({ path: k, from: older[k], to: newer[k] });
      });
      if (changes.length) out.push({ id: versions[i].id, author: versions[i].author_email, at: versions[i].created_at, changes });
    }
    return out;
  }, [versions]);

  const sectionOf = (path: string): SectionId => FIELD_SECTION[path.split(".")[0]] || "advanced";
  const forTab = changeSets
    .map((cs) => ({ ...cs, changes: cs.changes.filter((c) => sectionOf(c.path) === tab) }))
    .filter((cs) => cs.changes.length > 0);

  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="field-help" style={{ marginTop: 0 }}>A read-only log of what changed in each settings section, newest first — captured on every save. Pick a section:</div>
      <Tabs
        equal
        tabs={HISTORY_TABS.map((id) => ({ value: id, label: SECTIONS.find((s) => s.id === id)!.label }))}
        value={tab}
        onChange={(v) => setTab(v as SectionId)}
      />
      {err && <div className="card" style={{ padding: 12, color: "var(--err)" }}>{err}</div>}
      {!err && versions === null && <div className="fg-2 t-caption">Loading history…</div>}
      {!err && versions !== null && forTab.length === 0 && (
        <div className="card col center" style={{ padding: 34, gap: 6, color: "var(--fg-2)" }}>
          <Icon name="clock" size={20} />
          <div className="t-body-sm">No changes recorded for this section.</div>
        </div>
      )}
      {forTab.map((cs) => (
        <div key={cs.id} className="card" style={{ padding: "12px 14px" }}>
          <div className="t-caption fg-2" style={{ marginBottom: 8 }}>{cs.author || "unknown"}{cs.at ? ` · ${new Date(cs.at).toLocaleString()}` : ""}</div>
          <div className="col" style={{ gap: 6 }}>
            {cs.changes.map((c) => {
              const mask = MASK_RE.test(c.path);
              return (
                <div key={c.path} className="row gap2" style={{ alignItems: "baseline", fontSize: 12 }}>
                  <span className="mono-sm" style={{ minWidth: 150, flex: "none", color: "var(--fg-1)" }}>{c.path}</span>
                  <span className="mono-sm fg-2 truncate" style={{ textDecoration: "line-through", minWidth: 0 }}>{mask ? "••••" : fmtVal(c.from)}</span>
                  <Icon name="chevright" size={12} style={{ color: "var(--fg-2)", flex: "none" }} />
                  <span className="mono-sm truncate" style={{ color: "var(--fg-0)", minWidth: 0 }}>{mask ? "••••" : fmtVal(c.to)}</span>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function TeamCard() {
  const [me, setMe] = useState<MeResult | null>(null);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [invite, setInvite] = useState({ email: "", role: "editor" });
  const [msg, setMsg] = useState<string | null>(null);
  const [result, setResult] = useState<InviteResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  const isAdmin = me ? me.role === "owner" || me.role === "admin" : false;
  const reload = useCallback(() => { api.listTeam().then(setMembers).catch(() => setMembers([])); }, []);
  useEffect(() => { api.me().then(setMe).catch(() => {}); }, []);
  useEffect(() => { if (isAdmin) reload(); }, [isAdmin, reload]);

  async function doInvite() {
    setMsg(null); setResult(null); setCopied(false);
    if (!invite.email.trim()) return;
    setBusy(true);
    try {
      const r = await api.inviteMember({ email: invite.email.trim(), role: invite.role });
      setResult(r);
      setInvite({ email: "", role: "editor" });
      reload();
    } catch { setMsg("Could not invite (that email may already be on the team)."); }
    finally { setBusy(false); }
  }
  function copyInvite() {
    if (!result?.invite_url) return;
    navigator.clipboard?.writeText(result.invite_url).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1800); }).catch(() => {});
  }
  async function setRole(uid: string, role: string) { try { await api.updateMember(uid, { role }); reload(); } catch { setMsg("Could not update role."); } }
  async function deactivate(uid: string) { if (!window.confirm("Deactivate this user?")) return; try { await api.deactivateMember(uid); reload(); } catch { setMsg("Could not deactivate."); } }
  function logout() { clearTokens(); window.location.reload(); }

  return (
    <Card title="Team & account" action={<button className="btn btn-secondary btn-sm" onClick={logout}><Icon name="external" size={14} />Sign out</button>}>
      {me && (
        <div className="field-help" style={{ marginTop: 0, marginBottom: 10 }}>
          Signed in as <b>{me.email || "(dev)"}</b> · role <span className="typechip">{me.role}</span>
          {me.is_fallback && <span className="pill pill-muted" style={{ height: 16, marginLeft: 8 }}>auth disabled (dev)</span>}
        </div>
      )}
      {isAdmin && (
        <>
          <div style={{ border: "1px solid var(--line)", borderRadius: 10, padding: 12, marginBottom: 12, background: "var(--bg-1)" }}>
            <div className="t-body-sm" style={{ fontWeight: 600, marginBottom: 8 }}>Invite a teammate</div>
            <div className="row gap2" style={{ alignItems: "flex-end", flexWrap: "wrap" }}>
              <label className="col gap1" style={{ flex: "2 1 220px", minWidth: 200 }}>
                <span className="t-micro">Email</span>
                <input className="input" type="email" placeholder="teammate@company.com" value={invite.email}
                  onChange={(e) => setInvite((i) => ({ ...i, email: e.target.value }))} onKeyDown={(e) => { if (e.key === "Enter") doInvite(); }} />
              </label>
              <label className="col gap1" style={{ flex: "0 0 140px" }}>
                <span className="t-micro">Role</span>
                <select className="select" value={invite.role} onChange={(e) => setInvite((i) => ({ ...i, role: e.target.value }))}>
                  {ROLES.filter((r) => r !== "owner").map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </label>
              <button className="btn btn-primary btn-sm" onClick={doInvite} disabled={busy || !invite.email.trim()} style={{ height: 34 }}>
                <Icon name="plus" size={14} />{busy ? "Inviting…" : "Send invite"}
              </button>
            </div>
            <div className="field-help" style={{ marginTop: 8, marginBottom: 0 }}>
              They&apos;ll get an email with a secure link to set their own password and join the workspace.
            </div>
          </div>
          {result && (
            <div className="card" style={{ padding: 10, marginBottom: 12, background: "var(--bg-2)" }}>
              {result.email_sent ? (
                <div className="t-body-sm"><Icon name="check" size={13} style={{ color: "var(--ok)" }} /> Invitation emailed to <b>{result.email}</b>. They&apos;ll set their own password from the link.</div>
              ) : (
                <>
                  <div className="t-body-sm" style={{ marginBottom: 6 }}>Invite created for <b>{result.email}</b>. Email isn&apos;t configured on this server, so share this link - it lets them set their password and join:</div>
                  <div className="row gap2">
                    <input className="input mono" readOnly value={result.invite_url || ""} style={{ flex: 1, fontSize: 12 }} onFocus={(e) => e.currentTarget.select()} />
                    <button className="btn btn-secondary btn-sm" onClick={copyInvite}><Icon name={copied ? "check" : "copy"} size={13} />{copied ? "Copied" : "Copy"}</button>
                  </div>
                </>
              )}
            </div>
          )}
          {members.map((m) => (
            <div key={m.id} className="row spread" style={{ padding: "7px 0", borderTop: "1px solid var(--line)" }}>
              <div className="row gap2"><Icon name="user" size={15} style={{ color: "var(--fg-2)" }} /><span className="t-body-sm">{m.email}</span>{m.status !== "active" && <span className="pill pill-muted" style={{ height: 16 }}>{m.status}</span>}</div>
              <div className="row gap2">
                <select className="select" value={m.role} disabled={m.id === me?.id} onChange={(e) => setRole(m.id, e.target.value)}>
                  {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
                {m.id !== me?.id && <button className="iconbtn" title="Deactivate" onClick={() => deactivate(m.id)}><Icon name="trash" size={14} /></button>}
              </div>
            </div>
          ))}
        </>
      )}
      {msg && <div className="t-caption" style={{ color: "var(--err)", marginTop: 8 }}>{msg}</div>}
    </Card>
  );
}



/* Guardrails & Egress: one project-level I/O policy enforced on EVERY agent, plus the
   outbound-network egress scope. Content guardrails compile to `config.default_middleware`
   (the engine prepends this to every agent's own middleware stack — see agent_node); the
   network scope writes `config.egress` (the SSRF EgressPolicy, applied to every tool/webhook/
   web_fetch call). Entries this screen owns are tagged `_managed`, so any middleware authored
   elsewhere is preserved on save.

   Textareas keep their raw text in `config._guardrails_ui` (a UI-only sidecar the backend
   ignores) — deriving the value from the compiled arrays instead would strip a trailing newline
   on every keystroke, making it impossible to type a second line. Built-in PII compiles to a
   `pii` entry per type; custom patterns add a `detector` regex (label = its pii_type); blocked
   terms compile to one case-insensitive `guardrail_regex` of escaped literals (no runaway-regex
   risk). Only patterns that parse as a valid regex are compiled, so a half-typed one can't break
   every agent's compile. */
const PII_TYPES: [string, string][] = [
  ["email", "Email"], ["credit_card", "Credit card"], ["ip", "IP address"], ["mac_address", "MAC address"], ["url", "URL"],
];
function escapeRegex(s: string): string { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
function isValidRegex(p: string): boolean { try { new RegExp(p); return true; } catch { return false; } }
const splitLines = (s: string): string[] => (s || "").split("\n").map((x) => x.trim()).filter(Boolean);
// Parse "Label = regex" lines into {name, pattern}. Split on the first "=" so a pattern may
// itself contain "="; lines without both parts are skipped (e.g. a blank in-progress row).
function parseCustoms(text: string): { name: string; pattern: string }[] {
  const out: { name: string; pattern: string }[] = [];
  for (const line of (text || "").split("\n")) {
    const t = line.trim();
    const i = t.indexOf("=");
    if (i <= 0) continue;
    const name = t.slice(0, i).trim();
    const pattern = t.slice(i + 1).trim();
    if (name && pattern) out.push({ name, pattern });
  }
  return out;
}

function GuardrailsCard({ config, setCfg }: { config: Record<string, any>; setCfg: (patch: Record<string, any>) => void }) {
  const mw: any[] = Array.isArray(config.default_middleware) ? config.default_middleware : [];
  const isManagedPii = (m: any) => m?.type === "pii" && m?.config?._managed;
  const isManagedTerms = (m: any) => m?.type === "guardrail_regex" && m?.config?._managed;
  const unmanaged = mw.filter((m) => !isManagedPii(m) && !isManagedTerms(m));
  const pii = mw.filter(isManagedPii);
  const termsEntry = mw.find(isManagedTerms);
  const egress = config.egress || {};
  const ui = config._guardrails_ui || {};

  // Discrete controls read straight from the compiled entries (no typing, so no newline issue).
  const builtinTypes = new Set<string>(pii.filter((m) => !m.config?.detector).map((m) => m.config?.pii_type));
  const strategy: string = pii[0]?.config?.strategy || "redact";
  const scanIn: boolean = pii[0]?.config?.apply_to_input ?? true;
  const scanOut: boolean = pii[0]?.config?.apply_to_output ?? true;
  const onMatch: string = termsEntry?.config?.on_match || "block";
  const blockPrivate = !!egress.block_private;
  // Free-text controls read their raw text from the sidecar, falling back to reconstructing it
  // from the compiled config (for policies created via the API or before this UI existed).
  const termsText: string = ui.terms_text ?? (termsEntry?.config?._terms || []).join("\n");
  const customsText: string = ui.customs_text ?? pii.filter((m) => m.config?.detector).map((m) => `${m.config.pii_type} = ${m.config.detector}`).join("\n");
  const allowText: string = ui.allow_text ?? (egress.allow_hosts || []).join("\n");
  const denyText: string = ui.deny_text ?? (egress.deny_hosts || []).join("\n");

  const invalidCustoms = parseCustoms(customsText).filter((c) => !isValidRegex(c.pattern)).map((c) => c.name);
  const hasPii = builtinTypes.size > 0 || parseCustoms(customsText).length > 0;

  // Recompile the whole managed policy from a snapshot of UI state, preserving unmanaged entries.
  function commit(next: Partial<{ types: Set<string>; strategy: string; scanIn: boolean; scanOut: boolean; termsText: string; customsText: string; onMatch: string; blockPrivate: boolean; allowText: string; denyText: string }>) {
    const types = next.types ?? builtinTypes;
    const strat = next.strategy ?? strategy;
    const sIn = next.scanIn ?? scanIn;
    const sOut = next.scanOut ?? scanOut;
    const tText = next.termsText ?? termsText;
    const cText = next.customsText ?? customsText;
    const oMatch = next.onMatch ?? onMatch;
    const bPriv = next.blockPrivate ?? blockPrivate;
    const aText = next.allowText ?? allowText;
    const dText = next.denyText ?? denyText;

    const mkPii = (pii_type: string, detector?: string) => ({
      type: "pii", config: { _managed: true, pii_type, ...(detector ? { detector } : {}), strategy: strat, apply_to_input: sIn, apply_to_output: sOut },
    });
    const builtin = [...types].map((t) => mkPii(t));
    const customs = parseCustoms(cText).filter((c) => isValidRegex(c.pattern)).map((c) => mkPii(c.name, c.pattern));
    const termList = splitLines(tText);
    const termEntry = termList.length
      ? [{ type: "guardrail_regex", config: { _managed: true, _terms: termList, patterns: termList.map((t) => "(?i)" + escapeRegex(t)), on_match: oMatch, apply_to: "both" } }]
      : [];

    const allow = splitLines(aText);
    const deny = splitLines(dText);
    const nextEgress: Record<string, any> = { ...egress };
    if (bPriv) nextEgress.block_private = true; else delete nextEgress.block_private;
    if (allow.length) nextEgress.allow_hosts = allow; else delete nextEgress.allow_hosts;
    if (deny.length) nextEgress.deny_hosts = deny; else delete nextEgress.deny_hosts;

    setCfg({
      default_middleware: [...unmanaged, ...builtin, ...customs, ...termEntry],
      egress: Object.keys(nextEgress).length ? nextEgress : undefined,
      _guardrails_ui: { terms_text: tText, customs_text: cText, allow_text: aText, deny_text: dText },
    });
  }

  return (
    <>
      <Card title="Content guardrails">
        <div className="field-help" style={{ marginTop: 0, marginBottom: 12 }}>
          Enforced on <b>every agent</b> in this project, ahead of any per-agent middleware. These run locally (regex) on each turn — no added network latency. Use an agent&apos;s own middleware for exceptions.
        </div>
        <Field label="Redact / block PII" help="Detect these entities in messages and apply the strategy below. Each type is matched with a built-in detector.">
          <div className="row gap2 wrap">
            {PII_TYPES.map(([id, label]) => {
              const on = builtinTypes.has(id);
              return (
                <button key={id} type="button"
                  onClick={() => { const t = new Set(builtinTypes); if (on) t.delete(id); else t.add(id); commit({ types: t }); }}
                  style={{ padding: "5px 11px", borderRadius: 8, border: "1px solid var(--line)", cursor: "pointer", fontSize: 13, fontWeight: 600, background: on ? "var(--accent)" : "transparent", color: on ? "#fff" : "var(--fg-1)" }}>
                  {label}
                </button>
              );
            })}
          </div>
        </Field>
        <Field label="Custom patterns" help="One per line as `Label = regex` — e.g. a phone or national-ID format. Matched with your regex and handled by the strategy below. Unlike blocked terms, a regex you write here is your responsibility (keep it simple to avoid slow matching).">
          <textarea className="textarea mono" rows={2} placeholder={"Phone = \\d{3}[- ]?\\d{3}[- ]?\\d{4}\nUS SSN = \\d{3}-\\d{2}-\\d{4}"}
            value={customsText} onChange={(e) => commit({ customsText: e.target.value })} />
        </Field>
        {invalidCustoms.length > 0 && (
          <div className="field-help" style={{ marginTop: -6, color: "var(--err)" }}>⚠ Not a valid regex (ignored until fixed): {invalidCustoms.join(", ")}</div>
        )}
        {hasPii && (
          <>
            <Field label="Strategy" help="Applies to every PII match above (built-in and custom). Redact removes the value, Mask shows only the last few chars, Hash substitutes a stable hash, Block refuses the whole message.">
              <Segmented
                options={[{ value: "redact", label: "Redact" }, { value: "mask", label: "Mask" }, { value: "hash", label: "Hash" }, { value: "block", label: "Block" }]}
                value={strategy} onChange={(v) => commit({ strategy: v })} />
            </Field>
            <div className="row gap3 wrap">
              <label className="row gap2" style={{ alignItems: "center" }}><Toggle on={scanIn} onChange={(v) => commit({ scanIn: v })} /><span className="t-body-sm">Scan input (what comes in)</span></label>
              <label className="row gap2" style={{ alignItems: "center" }}><Toggle on={scanOut} onChange={(v) => commit({ scanOut: v })} /><span className="t-body-sm">Scan output (what leaves to the model / user)</span></label>
            </div>
          </>
        )}
        <div style={{ height: 14 }} />
        <Field label="Blocked terms" help="One term per line. Matched case-insensitively in both input and output. Kept as literal keywords — safe from regex pitfalls.">
          <textarea className="textarea mono" rows={3} placeholder={"internal-codename\nproject-atlas"}
            value={termsText} onChange={(e) => commit({ termsText: e.target.value })} />
        </Field>
        {splitLines(termsText).length > 0 && (
          <Field label="On a blocked term" help="Block replaces the message with a notice; Redact masks just the term; Flag keeps it but tags the trace for review.">
            <Segmented
              options={[{ value: "block", label: "Block" }, { value: "redact", label: "Redact" }, { value: "flag", label: "Flag" }]}
              value={onMatch} onChange={(v) => commit({ onMatch: v })} />
          </Field>
        )}
      </Card>

      <Card title="Network egress">
        <div className="field-help" style={{ marginTop: 0, marginBottom: 12 }}>
          Scopes where this project&apos;s tools, webhooks, and web-fetch can connect. It can only <b>tighten</b> the server&apos;s egress guard for this project — never loosen it.
        </div>
        <label className="row spread" style={{ padding: "8px 0" }}>
          <div><div className="t-body-sm" style={{ fontWeight: 600 }}>Block private / internal addresses</div><div className="field-help" style={{ marginTop: 0 }}>Refuse outbound calls that resolve to private, loopback, or cloud-metadata addresses (SSRF guard).</div></div>
          <Toggle on={blockPrivate} onChange={(v) => commit({ blockPrivate: v })} />
        </label>
        <Field label="Allowed domains" help="One host per line. If any are listed, ONLY these hosts (and their subdomains) are reachable — everything else is blocked.">
          <textarea className="textarea mono" rows={2} placeholder={"api.example.com\nhooks.slack.com"}
            value={allowText} onChange={(e) => commit({ allowText: e.target.value })} />
        </Field>
        <Field label="Blocked domains" help="One host per line. These hosts (and their subdomains) are always refused.">
          <textarea className="textarea mono" rows={2} placeholder={"pastebin.com"}
            value={denyText} onChange={(e) => commit({ denyText: e.target.value })} />
        </Field>
      </Card>
    </>
  );
}

function Card({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="card" style={{ padding: 18, marginBottom: 16 }}>
      <div className="row spread" style={{ marginBottom: 12 }}><div className="t-h2">{title}</div>{action}</div>
      {children}
    </div>
  );
}
