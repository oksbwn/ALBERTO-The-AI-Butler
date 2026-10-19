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
      connectorCatalog: vi.fn(),
      listConnectors: vi.fn(),
      listMcpClients: vi.fn(),
      listTools: vi.fn(),
      connectorExamples: vi.fn(),
      listChannels: vi.fn(),
      listWorkflows: vi.fn(),
      listAgents: vi.fn(),
      listAuthProviders: vi.fn(),
      listToolSets: vi.fn(),
      listPendingApprovals: vi.fn(),
      testTool: vi.fn(),
    },
  };
});

import { IntegrationsScreen } from "@/components/screens/integrations";
import { IntegrationsPlaygroundScreen } from "@/components/screens/integrations-playground";
import { api } from "@/lib/api";

const apiMock = vi.mocked(api);

describe("Integrations v3 Frontend Test Suite", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.getProject.mockResolvedValue({
      id: "p1", name: "Alberto", slug: "alberto", description: "", status: "active", config: {},
    });
    apiMock.connectorCatalog.mockResolvedValue({
      connectors: [
        { slug: "home-assistant", name: "Home Assistant", summary: "Smart home automation", icon: "home", type: "Connector", auth: { kind: "token" } },
      ],
      categories: ["Smart Home"],
      roles: [],
    });
    apiMock.listConnectors.mockResolvedValue([]);
    apiMock.listMcpClients.mockResolvedValue([]);
    apiMock.listTools.mockResolvedValue([
      { id: "tool-1", name: "turn_on_light", description: "Turn on smart light", input_schema: { type: "object", properties: { light_id: { type: "string" } } }, enabled: true },
    ]);
    apiMock.connectorExamples.mockResolvedValue([]);
    apiMock.listChannels.mockResolvedValue([
      {
        id: "chan-legacy-1",
        name: "Legacy Telegram Bot",
        type: "telegram",
        routing_state: "needs_review",
        target_type: null,
        target_id: null,
        enabled: true,
        state: { connected: true },
      },
    ]);
    apiMock.listWorkflows.mockResolvedValue([]);
    apiMock.listAgents.mockResolvedValue([]);
    apiMock.listAuthProviders.mockResolvedValue([]);
    apiMock.listToolSets.mockResolvedValue([]);
    apiMock.listPendingApprovals.mockResolvedValue([]);
  });

  it("renders Integrations Hub tabs including My Integrations, Explore, Custom, and Advanced Settings", async () => {
    render(<IntegrationsScreen project={{ id: "p1" }} />);

    await waitFor(() => {
      expect(screen.getByText(/My Integrations/i)).toBeInTheDocument();
      expect(screen.getByText(/Explore/i)).toBeInTheDocument();
      expect(screen.getByText(/Custom/i)).toBeInTheDocument();
      expect(screen.getByText(/Advanced Settings/i)).toBeInTheDocument();
    });
  });

  it("displays Review Required badge for historical channels needing destination confirmation", async () => {
    render(<IntegrationsScreen project={{ id: "p1" }} />);

    await waitFor(() => {
      expect(screen.getByText("Legacy Telegram Bot")).toBeInTheDocument();
      expect(screen.getByText("⚠ Review Required")).toBeInTheDocument();
    });
  });

  it("navigates to Advanced Settings and switches to Shared OAuth configuration", async () => {
    const user = userEvent.setup();
    render(<IntegrationsScreen project={{ id: "p1" }} />);

    await waitFor(() => expect(screen.getByText(/Advanced Settings/i)).toBeInTheDocument());
    await user.click(screen.getByText(/Advanced Settings/i));

    expect(screen.getByText("Advanced Integration Settings")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Shared OAuth/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Advanced MCP/i })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Shared OAuth/i }));
    expect(screen.getByText("Shared OAuth 2.0 Client Configuration")).toBeInTheDocument();
  });

  it("renders dedicated Integrations Playground with tool catalog and test execution console", async () => {
    render(<IntegrationsPlaygroundScreen project={{ id: "p1" }} />);

    await waitFor(() => {
      expect(screen.getByText("Integrations Playground")).toBeInTheDocument();
      expect(screen.getByText("turn_on_light")).toBeInTheDocument();
    });
  });
});
