import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { NodeConfigModal } from "@/components/canvas/NodeConfigModal";
import type { FlowNode, FlowEdge } from "@/lib/graph";

import { api } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      ...actual.api,
      executeStep: vi.fn(),
    },
  };
});


describe("NodeConfigModal - n8n-Style 3-Panel Editor", () => {
  const mockNode: FlowNode = {
    id: "transform_1",
    type: "forge",
    position: { x: 100, y: 100 },
    data: {
      nodeType: "transform",
      config: { name: "Order Transformer", operations: [] },
      debug: { output: { payload: { initial: true } } },
    },
  };

  const upstreamNode: FlowNode = {
    id: "inject_1",
    type: "forge",
    position: { x: 0, y: 100 },
    data: {
      nodeType: "inject",
      config: { topic: "orders.new" },
      debug: { output: { msg: { _msgid: "msg-123", topic: "orders.new", payload: { order_id: "ORD-99", total: 150 } } } },
    },
  };

  const secondUpstreamNode: FlowNode = {
    id: "inject_2",
    type: "forge",
    position: { x: 0, y: 200 },
    data: {
      nodeType: "inject",
      config: { topic: "orders.secondary" },
      debug: { output: { msg: { _msgid: "msg-456", topic: "orders.secondary", payload: { shipping: "express" } } } },
    },
  };

  const mockEdges: FlowEdge[] = [
    { id: "e1", source: "inject_1", target: "transform_1" },
  ];

  it("renders the 3 canonical panels: INPUT DATA, PARAMETERS, OUTPUT DATA", () => {
    render(
      <NodeConfigModal
        node={mockNode}
        nodes={[upstreamNode, mockNode]}
        edges={mockEdges}
        project={{ id: "p1" }}
        workflowId="wf1"
        tools={[]}
        toolSets={[]}
        agents={[]}
        mcpServers={[]}
        components={[]}
        onUpdateConfig={vi.fn()}
        onRenameNode={vi.fn()}
        onDeleteNode={vi.fn()}
        onClose={vi.fn()}
        renderParameters={() => <div data-testid="param-fields">Configuration Parameters</div>}
      />
    );

    expect(screen.getByText("INPUT DATA")).toBeInTheDocument();
    expect(screen.getByText("PARAMETERS")).toBeInTheDocument();
    expect(screen.getByText("OUTPUT DATA")).toBeInTheDocument();
    expect(screen.getByTestId("param-fields")).toBeInTheDocument();
    expect(screen.getByText("order_id")).toBeInTheDocument();
  });

  it("handles single-step execution and updates output panel", async () => {
    vi.mocked(api.executeStep).mockResolvedValue({
      ok: true,
      output: { payload: { status: "success", count: 99 } },
      duration_ms: 15.2,
      mocked: true,
    });

    render(
      <NodeConfigModal
        node={mockNode}
        nodes={[upstreamNode, mockNode]}
        edges={mockEdges}
        project={{ id: "p1" }}
        workflowId="wf1"
        tools={[]}
        toolSets={[]}
        agents={[]}
        mcpServers={[]}
        components={[]}
        onUpdateConfig={vi.fn()}
        onRenameNode={vi.fn()}
        onDeleteNode={vi.fn()}
        onClose={vi.fn()}
        renderParameters={() => <div>Params</div>}
      />
    );

    const testStepBtn = screen.getByText("Test Step");
    fireEvent.click(testStepBtn);

    await waitFor(() => {
      expect(api.executeStep).toHaveBeenCalledTimes(1);
    });

    await waitFor(() => {
      expect(screen.getByText(/15.2ms/)).toBeInTheDocument();
      expect(screen.getByText("Simulated Dry Run")).toBeInTheDocument();
    });
  });

  it("supports Safe (Dry Run) vs Live test mode toggle and Combined Branches view", async () => {
    render(
      <NodeConfigModal
        node={mockNode}
        nodes={[upstreamNode, secondUpstreamNode, mockNode]}
        edges={[
          { id: "e1", source: "inject_1", target: "transform_1" },
          { id: "e2", source: "inject_2", target: "transform_1" },
        ]}
        project={{ id: "p1" }}
        workflowId="wf1"
        tools={[]}
        toolSets={[]}
        agents={[]}
        mcpServers={[]}
        components={[]}
        onUpdateConfig={vi.fn()}
        onRenameNode={vi.fn()}
        onDeleteNode={vi.fn()}
        onClose={vi.fn()}
        renderParameters={() => <div>Params</div>}
      />
    );

    expect(screen.getByText("Safe (Dry Run)")).toBeInTheDocument();
    expect(screen.getByText("Live")).toBeInTheDocument();
    expect(screen.getByText(/Combined Branches/)).toBeInTheDocument();
  });
});
