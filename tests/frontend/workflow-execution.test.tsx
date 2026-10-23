import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      ...actual.api,
      getProject: vi.fn(),
      listSecrets: vi.fn(),
      listComponents: vi.fn(),
      listWorkflows: vi.fn(),
      createRun: vi.fn(),
      resumeRun: vi.fn(),
      cancelRun: vi.fn(),
      runStreamUrl: vi.fn(),
    },
    openSSE: vi.fn(),
  };
});

import { WorkflowExecutionPanel, redactSensitive } from "@/components/canvas/WorkflowTestPanel";
import { api, openSSE, type Workflow } from "@/lib/api";

const apiMock = vi.mocked(api);
const openSSEMock = vi.mocked(openSSE);

const sampleWorkflow: Workflow = {
  id: "wf-123",
  project_id: "p1",
  name: "Customer Lead Ingestion",
  description: "Validates and notifies on new customer leads",
  status: "active",
  active_version: 2,
  executable: {
    nodes: [
      { id: "node-validator", type: "router", config: { name: "Lead Validator" } },
      { id: "node-agent", type: "agent", config: { name: "Enrichment Agent" } },
      { id: "node-notify", type: "tool", config: { name: "Slack Notifier" } },
    ],
  },
  canvas: { nodes: [], edges: [] },
};

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.listComponents.mockResolvedValue([]);
  apiMock.createRun.mockResolvedValue({ id: "run-exec-999", status: "queued", thread_id: "thread-abc" });
  apiMock.runStreamUrl.mockImplementation((_pid: string, _wid: string, runId: string) => `/stream/${runId}`);
  apiMock.resumeRun.mockResolvedValue({ status: "running" });
  apiMock.cancelRun.mockResolvedValue({ ok: true });
});

describe("WorkflowExecutionPanel - Unified Orchestration Viewer", () => {
  it("renders manual trigger input, workflow name, and execution controls", () => {
    render(<WorkflowExecutionPanel project={{ id: "p1" }} workflow={sampleWorkflow} />);

    expect(screen.getByText("Orchestrator Execution")).toBeInTheDocument();
    expect(screen.getByText("Customer Lead Ingestion")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Message the workflow…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reset" })).toBeInTheDocument();
  });

  it("switches to JSON mode and validates JSON input syntax", async () => {
    const user = userEvent.setup();
    render(<WorkflowExecutionPanel project={{ id: "p1" }} workflow={sampleWorkflow} />);

    await user.click(screen.getByRole("button", { name: "JSON Payload" }));
    const textarea = screen.getByPlaceholderText(/param/);
    expect(textarea).toBeInTheDocument();

    // Type invalid JSON
    fireEvent.change(textarea, { target: { value: "{ bad json }" } });
    expect(screen.getByText(/Invalid JSON/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run" })).toBeDisabled();

    // Clear and type valid JSON
    fireEvent.change(textarea, { target: { value: '{"lead_id": 42}' } });
    await waitFor(() => {
      expect(screen.queryByText(/Invalid JSON/i)).not.toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Run" })).not.toBeDisabled();
  });

  it("executes workflow stream, tracks node steps, and displays output", async () => {
    const user = userEvent.setup();
    const onNodeStepMock = vi.fn();
    const onFinalDebugMock = vi.fn();

    openSSEMock.mockImplementation(async (_url: string, onFrame: any) => {
      onFrame({ event: "node_start", data: { node: "node-validator" } });
      onFrame({ event: "updates", data: { "node-validator": { valid: true, score: 0.95 } } });
      onFrame({
        event: "activity",
        data: { id: "act-1", kind: "subagent", name: "Enrichment Agent", phase: "start", input: { domain: "example.com" } },
      });
      onFrame({
        event: "activity",
        data: { id: "act-1", kind: "subagent", name: "Enrichment Agent", phase: "end", output: { company: "Example Corp" } },
      });
      onFrame({
        event: "done",
        data: {
          status: "done",
          answer: "Lead successfully qualified and enriched.",
          total_tokens: 350,
          total_cost_usd: 0.0012,
          debug: { nodes: { "node-validator": { duration_ms: 120 } } },
        },
      });
    });

    render(
      <WorkflowExecutionPanel
        project={{ id: "p1" }}
        workflow={sampleWorkflow}
        onNodeStep={onNodeStepMock}
        onFinalDebug={onFinalDebugMock}
      />
    );

    const input = screen.getByPlaceholderText("Message the workflow…");
    await user.type(input, "Ingest lead for Alice");
    await user.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => {
      expect(apiMock.createRun).toHaveBeenCalledWith(
        "p1",
        "wf-123",
        { messages: [{ role: "user", content: "Ingest lead for Alice" }] },
        undefined,
      );
    });

    await waitFor(() => {
      expect(screen.getByText("Lead successfully qualified and enriched.")).toBeInTheDocument();
      expect(screen.getByText(/350 tok/)).toBeInTheDocument();
    });

    expect(onNodeStepMock).toHaveBeenCalledWith("node-validator", "running");
    expect(onNodeStepMock).toHaveBeenCalledWith("node-validator", "done", { valid: true, score: 0.95 });
    expect(onFinalDebugMock).toHaveBeenCalledWith({ "node-validator": { duration_ms: 120 } });
  });

  it("handles human-in-the-loop interrupt and resumes approval", async () => {
    const user = userEvent.setup();
    openSSEMock.mockImplementation(async (_url: string, onFrame: any) => {
      onFrame({
        event: "interrupt",
        data: [{ tool: "send_slack_alert", reason: "Requires human review before posting to channel" }],
      });
    });

    render(<WorkflowExecutionPanel project={{ id: "p1" }} workflow={sampleWorkflow} />);

    const input = screen.getByPlaceholderText("Message the workflow…");
    await user.type(input, "Trigger notification");
    await user.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => {
      expect(screen.getByText("Action Requires Approval")).toBeInTheDocument();
    });

    const approveBtn = screen.getByRole("button", { name: "Approve Action" });
    await user.click(approveBtn);

    await waitFor(() => {
      expect(apiMock.resumeRun).toHaveBeenCalledWith("p1", "wf-123", "run-exec-999", { approved: true });
    });
  });

  it("redacts sensitive keys in structured JSON output", () => {
    const sensitiveData = {
      user: "alice",
      token: "secret-token-12345",
      api_key: "sk-abcdef123456789",
      nested: {
        password: "supersecretpass",
        port: 8080,
      },
    };

    const redacted = redactSensitive(sensitiveData);
    expect(redacted.user).toBe("alice");
    expect(redacted.token).toBe("••••••••");
    expect(redacted.api_key).toBe("••••••••");
    expect(redacted.nested.password).toBe("••••••••");
    expect(redacted.nested.port).toBe(8080);
  });
});
