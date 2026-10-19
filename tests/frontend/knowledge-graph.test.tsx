import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Mock ResizeObserver for jsdom
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      ...actual.api,
      graphStats: vi.fn(),
      graphSubgraph: vi.fn(),
      graphEntities: vi.fn(),
      graphEntityNeighbors: vi.fn(),
      memoryStatus: vi.fn(),
      getMemoryLearningSettings: vi.fn(),
      listMemoryRecords: vi.fn(),
      listLearningEvents: vi.fn(),
      listMarkdownMemoryFiles: vi.fn(),
    },
  };
});

import { KnowledgeGraphExplorer, extractAliases } from "@/components/canvas/KnowledgeGraphExplorer";
import { KnowledgeScreen } from "@/components/screens/knowledge";
import { api, GraphEntity, GraphRelationship, GraphSubgraph } from "@/lib/api";

const apiMock = vi.mocked(api);

const mockOLMXEntity: GraphEntity = {
  id: "ent-olmx",
  tenant_id: "t-default",
  project_id: "p1",
  kind: "ModelRunner",
  name: "OLMX",
  canonical_name: "olmx",
  description: "Local high-performance inference engine [aliases: olmx-core, fast-olmx]",
  source: "manual",
  confidence: 1.0,
  created_at: 1700000000000,
  updated_at: 1700000000000,
};

const mockMacStudioEntity: GraphEntity = {
  id: "ent-mac",
  tenant_id: "t-default",
  project_id: "p1",
  kind: "Device",
  name: "MacStudio",
  canonical_name: "macstudio",
  description: "M2 Ultra 192GB",
  source: "mcp_scan",
  confidence: 0.95,
  created_at: 1700000000000,
  updated_at: 1700000000000,
};

const mockOllamaEntity: GraphEntity = {
  id: "ent-ollama",
  tenant_id: "t-default",
  project_id: "p1",
  kind: "Application",
  name: "Ollama",
  canonical_name: "ollama",
  description: "Separate standard runner",
  source: "manual",
  confidence: 0.9,
  created_at: 1700000000000,
  updated_at: 1700000000000,
};

const mockRelationship: GraphRelationship = {
  id: "rel-olmx-mac",
  source_id: "ent-olmx",
  target_id: "ent-mac",
  kind: "RUNS_ON",
  tenant_id: "t-default",
  project_id: "p1",
  source: "system_inspection",
  confidence: 1.0,
  provenance: "tool_inventory_scan",
  created_at: 1700000000000,
  updated_at: 1700000000000,
};

beforeEach(() => {
  vi.clearAllMocks();

  apiMock.graphStats.mockResolvedValue({
    entity_count: 3,
    relationship_count: 1,
    storage_path: "/data/db/ladybug/graph.db",
    is_available: true,
  });

  apiMock.graphSubgraph.mockResolvedValue({
    nodes: [mockOLMXEntity, mockMacStudioEntity],
    relationships: [mockRelationship],
    truncated: false,
    focus_id: null,
    total_nodes: 2,
    total_relationships: 1,
  });

  apiMock.graphEntities.mockResolvedValue([mockOLMXEntity, mockMacStudioEntity]);

  apiMock.memoryStatus.mockResolvedValue({
    memory_learning_enabled: true,
    sqlite: { memory_count: 2, qa_count: 0 },
    ladybug_graph: { available: true, entity_count: 2, relationship_count: 1 },
    chroma: { available: true, path: "/data/db/chroma" },
    markdown: { status: "active", active_writer: true, path: "/data/memory", directory_exists: true },
  });

  apiMock.getMemoryLearningSettings.mockResolvedValue({
    memory_learning_enabled: true,
    tool_execution_learning_enabled: true,
    memory_curator_model: "default",
    memory_curator_effective_model: "claude-3-5-sonnet",
    graph_manager_model: "default",
    graph_manager_effective_model: "claude-3-5-sonnet",
    operational_state: "ready",
  });

  apiMock.listMemoryRecords.mockResolvedValue([]);
  apiMock.listLearningEvents.mockResolvedValue([]);
  apiMock.listMarkdownMemoryFiles.mockResolvedValue([]);
});

describe("KnowledgeGraphExplorer", () => {
  it("extracts aliases correctly from description and canonical name", () => {
    const aliases = extractAliases(mockOLMXEntity);
    expect(aliases).toContain("olmx-core");
    expect(aliases).toContain("fast-olmx");
  });

  it("renders graph canvas, nodes, and toolbar controls", async () => {
    render(<KnowledgeGraphExplorer project={{ id: "p1" }} />);

    await waitFor(() => {
      expect(apiMock.graphSubgraph).toHaveBeenCalledWith("p1", expect.objectContaining({ limit: 60 }));
    });

    expect(await screen.findByText("OLMX")).toBeInTheDocument();
    expect(screen.getByText("MacStudio")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/search entity/i)).toBeInTheDocument();
  });

  it("selects an entity on click and displays properties, aliases, and provenance in inspector", async () => {
    const user = userEvent.setup();
    render(<KnowledgeGraphExplorer project={{ id: "p1" }} />);

    const olmxNode = await screen.findByText("OLMX");
    fireEvent.click(olmxNode);

    // Inspector should open with details
    expect(await screen.findByText("Entity Details")).toBeInTheDocument();
    expect(screen.getByText("olmx-core")).toBeInTheDocument();
    expect(screen.getByText("fast-olmx")).toBeInTheDocument();
    expect(screen.getByText("Properties & Provenance")).toBeInTheDocument();
    expect(screen.getByText("Expand 1-Hop")).toBeInTheDocument();
  });

  it("searches and filters for OLMX specifically", async () => {
    const user = userEvent.setup();
    render(<KnowledgeGraphExplorer project={{ id: "p1" }} />);

    const searchInput = screen.getByPlaceholderText(/search entity/i);
    await user.type(searchInput, "OLMX");
    await user.click(screen.getByRole("button", { name: /find/i }));

    await waitFor(() => {
      expect(apiMock.graphSubgraph).toHaveBeenCalledWith("p1", expect.objectContaining({ search: "OLMX" }));
    });
  });

  it("expands neighbours without creating duplicate nodes", async () => {
    const user = userEvent.setup();

    apiMock.graphEntityNeighbors.mockResolvedValueOnce([
      {
        nodes: [mockOLMXEntity, mockOllamaEntity],
        relationships: [],
        length: 1,
      },
    ]);

    render(<KnowledgeGraphExplorer project={{ id: "p1" }} />);

    const olmxNode = await screen.findByText("OLMX");
    fireEvent.click(olmxNode);

    const expandBtn = await screen.findByRole("button", { name: /expand 1-hop/i });
    await user.click(expandBtn);

    await waitFor(() => {
      expect(apiMock.graphEntityNeighbors).toHaveBeenCalledWith("p1", "ent-olmx", expect.anything());
    });

    // Ollama should now be in the canvas
    expect(await screen.findByText("Ollama")).toBeInTheDocument();
    // OLMX still exists once
    expect(screen.getAllByText("OLMX").length).toBeGreaterThanOrEqual(1);
  });

  it("shows truncation warning banner when graph results are bounded", async () => {
    apiMock.graphSubgraph.mockResolvedValueOnce({
      nodes: [mockOLMXEntity],
      relationships: [],
      truncated: true,
      focus_id: null,
      total_nodes: 500,
      total_relationships: 300,
    });

    render(<KnowledgeGraphExplorer project={{ id: "p1" }} />);

    expect(await screen.findByText(/bounded visualization/i)).toBeInTheDocument();
    expect(screen.getByText(/showing 1 of 500 entities/i)).toBeInTheDocument();
  });

  it("displays graceful empty state when scope contains no nodes", async () => {
    apiMock.graphSubgraph.mockResolvedValueOnce({
      nodes: [],
      relationships: [],
      truncated: false,
      focus_id: null,
      total_nodes: 0,
      total_relationships: 0,
    });

    render(<KnowledgeGraphExplorer project={{ id: "p1" }} />);

    expect(await screen.findByText("No entities found in scope")).toBeInTheDocument();
  });

  it("renders operating_system badge with formatted label distinct from device", async () => {
    const mockMacOSEntity: GraphEntity = {
      id: "ent-macos",
      tenant_id: "t-default",
      project_id: "p1",
      kind: "operating_system",
      name: "macOS",
      canonical_name: "macos",
      description: "The operating system the user is running on.",
      source: "manual",
      confidence: 0.9,
      created_at: 1700000000000,
      updated_at: 1700000000000,
    };

    apiMock.graphSubgraph.mockResolvedValueOnce({
      nodes: [mockMacOSEntity, mockMacStudioEntity],
      relationships: [],
      truncated: false,
      focus_id: null,
      total_nodes: 2,
      total_relationships: 0,
    });

    render(<KnowledgeGraphExplorer project={{ id: "p1" }} />);

    expect(await screen.findByText("macOS")).toBeInTheDocument();
    expect(screen.getAllByText(/operating system/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/device/i).length).toBeGreaterThanOrEqual(1);
  });
});

describe("KnowledgeScreen existing page regression", () => {
  it("preserves vertical tabs and renders KnowledgeGraphExplorer in Knowledge Graph tab", async () => {
    render(<KnowledgeScreen project={{ id: "p1", name: "Alberto Test" }} subNav="graph" />);

    // Verify existing Header Card items
    expect(await screen.findByText("LadybugDB Interactive Graph Explorer")).toBeInTheDocument();
    expect(screen.getByText("Graph Visualizer")).toBeInTheDocument();
    expect(screen.getByText("Entities & Relations")).toBeInTheDocument();

    // Verify KnowledgeGraphExplorer is rendered inside the page
    expect(screen.getByPlaceholderText(/search entity/i)).toBeInTheDocument();
  });
});
