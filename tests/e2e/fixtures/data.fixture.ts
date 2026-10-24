import { APIRequestContext, request } from "@playwright/test";

export interface TestProject {
  id: string;
  name: string;
  slug: string;
}

export interface TestWorkflow {
  id: string;
  project_id: string;
  name: string;
  status: string;
  executable: any;
  canvas: any;
}

export class DataFixture {
  private apiContext!: APIRequestContext;
  private baseURL: string;
  private createdWorkflowIds: { projectId: string; id: string }[] = [];
  private createdProjectIds: string[] = [];
  public token: string | null = null;

  constructor(baseURL: string = process.env.ALBERTO_API_URL || "http://127.0.0.1:8005") {
    this.baseURL = baseURL;
  }

  async init() {
    this.apiContext = await request.newContext({
      baseURL: this.baseURL,
      extraHTTPHeaders: {
        "Content-Type": "application/json",
      },
    });

    try {
      const loginRes = await this.apiContext.post("/v1/auth/login", {
        data: {
          email: "admin",
          password: "password",
        },
      });
      if (loginRes.ok()) {
        const authData = await loginRes.json();
        if (authData.access_token) {
          this.token = authData.access_token;
          await this.apiContext.dispose();
          this.apiContext = await request.newContext({
            baseURL: this.baseURL,
            extraHTTPHeaders: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${authData.access_token}`,
            },
          });
        }
      }
    } catch {
      // In dev mode with anonymous owner, fall through
    }

    await this.verifyIsolation();
  }

  async verifyIsolation(): Promise<void> {
    try {
      const res = await this.apiContext.get("/v1/projects");
      if (res.ok()) {
        const projects = await res.json();
        const testProjectId = projects[0]?.id;
        if (testProjectId) {
          const statsRes = await this.apiContext.get(`/v1/projects/${testProjectId}/graph/stats`);
          if (statsRes.ok()) {
            const stats = await statsRes.json();
            const storagePath = (stats.storage_path || "").toLowerCase();
            if (storagePath && !storagePath.includes("test_e2e") && storagePath.includes("data\\db\\ladybug")) {
              throw new Error(
                `TEST ISOLATION VIOLATION: Connected backend at ${this.baseURL} is using production/dev storage (${stats.storage_path}). ` +
                `Tests must run against an isolated instance using ALBERTO_DATA_DIR=data/test_e2e.`
              );
            }
          }
        }
      }
    } catch (err: any) {
      if (err.message?.includes("TEST ISOLATION VIOLATION")) {
        throw err;
      }
    }
  }

  async getOrCreateDefaultProject(): Promise<TestProject> {
    const res = await this.apiContext.get("/v1/projects");
    if (res.ok()) {
      const list = await res.json();
      if (list && list.length > 0) {
        return list[0];
      }
    }
    const createRes = await this.apiContext.post("/v1/projects", {
      data: { name: `Test Project ${Date.now()}` },
    });
    const proj = await createRes.json();
    this.createdProjectIds.push(proj.id);
    return proj;
  }

  async createDeterministicWorkflow(projectId: string, name: string): Promise<TestWorkflow> {
    const payload = {
      name,
      description: "Automated Playwright E2E Deterministic Workflow",
      executable: {
        id: `e2e_${Date.now()}`,
        version: 1,
        entry_node: "start_node",
        state: {
          messages: { type: "list[message]", reducer: "add_messages" },
          output: { type: "str", reducer: "last" },
        },
        nodes: [
          {
            id: "start_node",
            type: "start",
            config: {},
            position: { x: 50, y: 150 },
          },
          {
            id: "echo_agent",
            type: "agent",
            config: {
              name: "echo_agent",
              model: "fake:E2E execution confirmed successfully.",
              system_prompt: "You are an E2E testing agent.",
            },
            position: { x: 300, y: 150 },
          },
          {
            id: "end_node",
            type: "end",
            config: {},
            position: { x: 550, y: 150 },
          },
        ],
      },
      canvas: {
        nodes: [
          {
            id: "start_node",
            type: "forgeNode",
            position: { x: 50, y: 150 },
            data: { nodeType: "start", config: {} },
          },
          {
            id: "echo_agent",
            type: "forgeNode",
            position: { x: 300, y: 150 },
            data: {
              nodeType: "agent",
              config: {
                name: "echo_agent",
                model: "fake:E2E execution confirmed successfully.",
              },
            },
          },
          {
            id: "end_node",
            type: "forgeNode",
            position: { x: 550, y: 150 },
            data: { nodeType: "end", config: {} },
          },
        ],
        edges: [
          { id: "e1", source: "start_node", target: "echo_agent" },
          { id: "e2", source: "echo_agent", target: "end_node" },
        ],
      },
    };

    const res = await this.apiContext.post(`/v1/projects/${projectId}/workflows`, {
      data: payload,
    });
    if (!res.ok()) {
      throw new Error(`Failed to create test workflow: ${await res.text()}`);
    }
    const wf = await res.json();
    this.createdWorkflowIds.push({ projectId, id: wf.id });
    return wf;
  }

  async createHitlWorkflow(projectId: string, name: string): Promise<TestWorkflow> {
    const payload = {
      name,
      description: "Automated Playwright E2E HITL Approval Workflow",
      executable: {
        id: `hitl_${Date.now()}`,
        version: 1,
        entry_node: "start_node",
        state: {
          messages: { type: "list[message]", reducer: "add_messages" },
          approved: { type: "bool", reducer: "last" },
        },
        nodes: [
          {
            id: "start_node",
            type: "start",
            config: {},
            position: { x: 50, y: 150 },
          },
          {
            id: "pause_approval",
            type: "human_input",
            config: {
              name: "pause_approval",
              prompt: "Please approve or reject this automated transaction.",
            },
            position: { x: 300, y: 150 },
          },
          {
            id: "end_node",
            type: "end",
            config: {},
            position: { x: 550, y: 150 },
          },
        ],
      },
      canvas: {
        nodes: [
          {
            id: "start_node",
            type: "forgeNode",
            position: { x: 50, y: 150 },
            data: { nodeType: "start", config: {} },
          },
          {
            id: "pause_approval",
            type: "forgeNode",
            position: { x: 300, y: 150 },
            data: {
              nodeType: "human_input",
              config: {
                name: "pause_approval",
                prompt: "Please approve or reject this automated transaction.",
              },
            },
          },
          {
            id: "end_node",
            type: "forgeNode",
            position: { x: 550, y: 150 },
            data: { nodeType: "end", config: {} },
          },
        ],
        edges: [
          { id: "e1", source: "start_node", target: "pause_approval" },
          { id: "e2", source: "pause_approval", target: "end_node" },
        ],
      },
    };

    const res = await this.apiContext.post(`/v1/projects/${projectId}/workflows`, {
      data: payload,
    });
    if (!res.ok()) {
      throw new Error(`Failed to create HITL workflow: ${await res.text()}`);
    }
    const wf = await res.json();
    this.createdWorkflowIds.push({ projectId, id: wf.id });
    return wf;
  }

  // --- Generic API Helpers ---

  async apiGet(path: string): Promise<any> {
    const res = await this.apiContext.get(path);
    if (!res.ok()) {
      throw new Error(`GET ${path} failed (${res.status()}): ${await res.text()}`);
    }
    return res.json();
  }

  async apiPost(path: string, data: any): Promise<any> {
    const res = await this.apiContext.post(path, { data });
    if (!res.ok()) {
      throw new Error(`POST ${path} failed (${res.status()}): ${await res.text()}`);
    }
    return res.json();
  }

  async apiPatch(path: string, data: any): Promise<any> {
    const res = await this.apiContext.patch(path, { data });
    if (!res.ok()) {
      throw new Error(`PATCH ${path} failed (${res.status()}): ${await res.text()}`);
    }
    return res.json();
  }

  async apiDelete(path: string): Promise<any> {
    const res = await this.apiContext.delete(path);
    if (!res.ok() && res.status() !== 204 && res.status() !== 404) {
      throw new Error(`DELETE ${path} failed (${res.status()}): ${await res.text()}`);
    }
    return res.status() === 204 ? null : res.json();
  }

  // --- Traces & Spans Inspection ---

  async getTraces(projectId: string): Promise<any[]> {
    return this.apiGet(`/v1/projects/${projectId}/traces`);
  }

  async getTrace(projectId: string, traceId: string): Promise<any> {
    return this.apiGet(`/v1/projects/${projectId}/traces/${traceId}`);
  }

  // --- Memory & Knowledge Lifecycle ---

  async getMemoryStatus(projectId: string): Promise<any> {
    return this.apiGet(`/v1/projects/${projectId}/memory/status`);
  }

  async recallMemory(projectId: string, query: string, sources: string[] = ["sqlite", "markdown", "chromadb", "graph"]): Promise<any> {
    return this.apiPost(`/v1/projects/${projectId}/memory/recall`, {
      query,
      sources,
      scope: "project",
      top_k: 8,
    });
  }

  async rememberMemory(
    projectId: string,
    text: string,
    options: { target?: string; kind?: string; entity_kind?: string; entity_name?: string } = {}
  ): Promise<any> {
    return this.apiPost(`/v1/projects/${projectId}/memory/remember`, {
      text,
      target: options.target || "sqlite",
      scope: "project",
      kind: options.kind || "fact",
      entity_kind: options.entity_kind,
      entity_name: options.entity_name,
    });
  }

  async getMemoryRecords(projectId: string, status: string = "active"): Promise<any[]> {
    return this.apiGet(`/v1/projects/${projectId}/memory/records?status=${status}`);
  }

  async getMarkdownMemories(projectId: string): Promise<any[]> {
    return this.apiGet(`/v1/projects/${projectId}/memory/markdown`);
  }

  async getGraphStats(projectId: string): Promise<any> {
    return this.apiGet(`/v1/projects/${projectId}/graph/stats`);
  }

  async getGraphEntities(projectId: string, kind?: string, search?: string): Promise<any[]> {
    const params = new URLSearchParams();
    if (kind) params.set("kind", kind);
    if (search) params.set("search", search);
    return this.apiGet(`/v1/projects/${projectId}/graph/entities?${params.toString()}`);
  }

  async getGraphSubgraph(projectId: string, focusId?: string): Promise<any> {
    const path = focusId ? `/v1/projects/${projectId}/graph/subgraph?focus_id=${focusId}` : `/v1/projects/${projectId}/graph/subgraph`;
    return this.apiGet(path);
  }

  // --- Tool Manager & Policy ---

  async listTools(projectId: string): Promise<any[]> {
    return this.apiGet(`/v1/projects/${projectId}/tools`);
  }

  async testToolExecution(projectId: string, toolId: string, args: any = {}, approvalId?: string): Promise<any> {
    const res = await this.apiContext.post(`/v1/projects/${projectId}/tools/${toolId}/test`, {
      data: { args, approval_id: approvalId },
    });
    return { status: res.status(), ok: res.ok(), data: await res.json() };
  }

  async updateToolActivation(projectId: string, toolId: string, enabled: boolean, requiresApproval?: boolean): Promise<any> {
    return this.apiPatch(`/v1/projects/${projectId}/tool-manager/tools/${toolId}/activation`, {
      enabled,
      requires_approval: requiresApproval,
    });
  }

  // --- Automation Manager ---

  async discoverCapabilities(projectId: string): Promise<any> {
    return this.apiGet(`/v1/projects/${projectId}/automate/capabilities`);
  }

  async createAuthoringSession(projectId: string, requirement: string, title?: string): Promise<any> {
    return this.apiPost(`/v1/projects/${projectId}/automate/sessions`, {
      requirement,
      title: title || `Auto Session ${Date.now()}`,
    });
  }

  async sendAuthoringMessage(projectId: string, sessionId: string, message: string): Promise<any> {
    return this.apiPost(`/v1/projects/${projectId}/automate/sessions/${sessionId}/messages`, {
      message,
    });
  }

  async testSessionProposal(projectId: string, sessionId: string): Promise<any> {
    return this.apiPost(`/v1/projects/${projectId}/automate/sessions/${sessionId}/test`, {});
  }

  async approveSessionProposal(projectId: string, sessionId: string, body: any = {}): Promise<any> {
    const payload = {
      revision: body.revision !== undefined ? body.revision : 1,
      create_agents: body.create_agents ?? true,
      activate_triggers: body.activate_triggers ?? false,
      ...body,
    };
    return this.apiPost(`/v1/projects/${projectId}/automate/sessions/${sessionId}/approve`, payload);
  }

  // --- Read-Only SQLite Validation Helper with Deterministic Isolation ---
  getTestDbPath(): string {
    const path = require("path");
    const fs = require("fs");
    const repoRoot = path.resolve(__dirname, "../../..");
    const envDataDir = process.env.ALBERTO_DATA_DIR || process.env.FORGE_DATA_DIR || path.join(repoRoot, "data/test_e2e");
    
    // Explicit canonical validation
    const resolvedDataDir = fs.existsSync(envDataDir) ? fs.realpathSync(envDataDir) : path.resolve(envDataDir);
    const prodDataDir = fs.existsSync(path.join(repoRoot, "data")) ? fs.realpathSync(path.join(repoRoot, "data")) : null;
    
    // Fail immediately if path references production or normal development storage
    if (prodDataDir && (resolvedDataDir === prodDataDir || (resolvedDataDir.startsWith(prodDataDir) && !resolvedDataDir.includes("test_e2e")))) {
      throw new Error(`TEST ISOLATION VIOLATION: Resolved test database directory '${resolvedDataDir}' points to production/dev storage '${prodDataDir}'. Test database selection must be strictly isolated to data/test_e2e.`);
    }

    const testDb = path.join(resolvedDataDir, "db", "alberto.db");
    if (!fs.existsSync(testDb)) {
      const dbDir = path.dirname(testDb);
      if (!fs.existsSync(dbDir)) {
        fs.mkdirSync(dbDir, { recursive: true });
      }
    }
    return testDb;
  }

  querySqlite(sql: string): any[] {
    const cp = require("child_process");
    const path = require("path");
    const fs = require("fs");
    const repoRoot = path.resolve(__dirname, "../../..");
    const testDb = this.getTestDbPath();
    const pythonBin = process.platform === "win32"
      ? (fs.existsSync(path.join(repoRoot, "backend/.venv/Scripts/python.exe"))
          ? path.join(repoRoot, "backend/.venv/Scripts/python.exe")
          : "python")
      : (fs.existsSync(path.join(repoRoot, "backend/.venv/bin/python"))
          ? path.join(repoRoot, "backend/.venv/bin/python")
          : "python3");

    const escapedSql = sql.replace(/"/g, '\\"');
    const cmd = `"${pythonBin}" -c "import sqlite3, json; conn=sqlite3.connect(r'${testDb}'); conn.row_factory=sqlite3.Row; cur=conn.cursor(); cur.execute(\\"${escapedSql}\\"); print(json.dumps([dict(r) for r in cur.fetchall()]))"`;
    try {
      const output = cp.execSync(cmd, { encoding: "utf-8", timeout: 10000 });
      return JSON.parse(output.trim());
    } catch (e: any) {
      console.warn("querySqlite warning:", e.message);
      return [];
    }
  }

  async cleanup() {
    for (const item of this.createdWorkflowIds) {
      try {
        await this.apiContext.delete(`/v1/projects/${item.projectId}/workflows/${item.id}`);
      } catch {
        // Ignore deletion cleanup error
      }
    }
    for (const pid of this.createdProjectIds) {
      try {
        await this.apiContext.delete(`/v1/projects/${pid}`);
      } catch {
        // Ignore deletion cleanup error
      }
    }
    if (this.apiContext) {
      await this.apiContext.dispose();
    }
  }
}
