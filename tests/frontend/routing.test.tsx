import { describe, it, expect } from "vitest";
import { pathToScreen, screenToPath, parsePathAndQuery, buildUrl } from "../../frontend/lib/routing";

describe("Deterministic 2-level URL Routing (/module/page)", () => {
  it("always maps internal screen keys to deterministic 2-level paths", () => {
    // Home module
    expect(screenToPath("home")).toBe("/home/overview");
    expect(screenToPath("chat")).toBe("/home/overview");

    // Automate module
    expect(screenToPath("playground")).toBe("/automate/playground");
    expect(screenToPath("automate")).toBe("/automate/playground");
    expect(screenToPath("workflows")).toBe("/automate/workflows");
    expect(screenToPath("workflow-canvas")).toBe("/automate/canvas");
    expect(screenToPath("agents")).toBe("/automate/agents");
    expect(screenToPath("agent-config")).toBe("/automate/agents/config");
    expect(screenToPath("components")).toBe("/automate/components");
    expect(screenToPath("component-builder")).toBe("/automate/components/builder");

    // Knowledge module
    expect(screenToPath("knowledge-playground")).toBe("/knowledge/playground");
    expect(screenToPath("knowledge-docs")).toBe("/knowledge/docs");
    expect(screenToPath("knowledge-vector")).toBe("/knowledge/vector");
    expect(screenToPath("knowledge-qa")).toBe("/knowledge/qa");
    expect(screenToPath("knowledge-graph")).toBe("/knowledge/graph");
    expect(screenToPath("knowledge-memory")).toBe("/knowledge/memory");

    // Integrations module
    expect(screenToPath("integrations-playground")).toBe("/integrations/playground");
    expect(screenToPath("integrations")).toBe("/integrations/connectors");
    expect(screenToPath("connectors")).toBe("/integrations/connectors");
    expect(screenToPath("channels")).toBe("/integrations/channels");
    expect(screenToPath("tools")).toBe("/integrations/tools");
    expect(screenToPath("tool-builder")).toBe("/integrations/tools/builder");
    expect(screenToPath("triggers")).toBe("/integrations/triggers");
    expect(screenToPath("auth")).toBe("/integrations/auth");

    // Observability module
    expect(screenToPath("overview")).toBe("/observability/analytics");
    expect(screenToPath("traces")).toBe("/observability/traces");
    expect(screenToPath("datasets")).toBe("/observability/evaluations");
    expect(screenToPath("handoff")).toBe("/observability/inbox");

    // Settings module
    expect(screenToPath("settings")).toBe("/settings/general");
  });

  it("maps 2-level paths back to correct internal screen keys", () => {
    // Home
    expect(pathToScreen("/home/overview")).toBe("home");

    // Automate
    expect(pathToScreen("/automate/playground")).toBe("playground");
    expect(pathToScreen("/automate/workflows")).toBe("workflows");
    expect(pathToScreen("/automate/canvas")).toBe("workflow-canvas");
    expect(pathToScreen("/automate/agents")).toBe("agents");
    expect(pathToScreen("/automate/components")).toBe("components");

    // Knowledge
    expect(pathToScreen("/knowledge/playground")).toBe("knowledge-playground");
    expect(pathToScreen("/knowledge/docs")).toBe("knowledge-docs");
    expect(pathToScreen("/knowledge/vector")).toBe("knowledge-vector");
    expect(pathToScreen("/knowledge/qa")).toBe("knowledge-qa");
    expect(pathToScreen("/knowledge/graph")).toBe("knowledge-graph");
    expect(pathToScreen("/knowledge/memory")).toBe("knowledge-memory");

    // Integrations
    expect(pathToScreen("/integrations/playground")).toBe("integrations-playground");
    expect(pathToScreen("/integrations/connectors")).toBe("integrations");
    expect(pathToScreen("/integrations/tools")).toBe("tools");
    expect(pathToScreen("/integrations/auth")).toBe("auth");

    // Observability
    expect(pathToScreen("/observability/analytics")).toBe("overview");
    expect(pathToScreen("/observability/traces")).toBe("traces");
    expect(pathToScreen("/observability/evaluations")).toBe("datasets");
    expect(pathToScreen("/observability/inbox")).toBe("handoff");

    // Settings
    expect(pathToScreen("/settings/general")).toBe("settings");
  });

  it("handles shorthand paths and normalizes trailing slashes", () => {
    expect(pathToScreen("/")).toBe("home");
    expect(pathToScreen("/home")).toBe("home");
    expect(pathToScreen("/automate")).toBe("playground");
    expect(pathToScreen("/automate/")).toBe("playground");
    expect(pathToScreen("/workflows")).toBe("workflows");
    expect(pathToScreen("/analytics")).toBe("overview");
    expect(pathToScreen("/unknown/page")).toBe("home");
  });

  it("parses URL paths and query parameters for deep linking", () => {
    const target1 = parsePathAndQuery("/automate/canvas?id=wf-123");
    expect(target1.screen).toBe("workflow-canvas");
    expect(target1.params).toEqual({ id: "wf-123" });

    const target2 = parsePathAndQuery("/integrations/tools?tab=installed&filter=mcp");
    expect(target2.screen).toBe("tools");
    expect(target2.params).toEqual({ tab: "installed", filter: "mcp" });

    const target3 = parsePathAndQuery("/settings/general");
    expect(target3.screen).toBe("settings");
    expect(target3.params).toEqual({});
  });

  it("constructs canonical URLs with search parameters", () => {
    expect(buildUrl("workflow-canvas", { id: "wf-123" })).toBe("/automate/canvas?id=wf-123");
    expect(buildUrl("tools", { tab: "installed" })).toBe("/integrations/tools?tab=installed");
    expect(buildUrl("home")).toBe("/home/overview");
  });
});
