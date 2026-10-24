import { Page } from "@playwright/test";
import { test, expect } from "../fixtures";
import { DataFixture, TestProject } from "../fixtures/data.fixture";

test.describe("Alberto Knowledge & Memory Lifecycle Acceptance", () => {
  let project: TestProject;

  test.beforeEach(async ({ page, data }: { page: Page; data: DataFixture }) => {
    project = await data.getOrCreateDefaultProject();
    await page.goto("/");
    await page.waitForSelector(".topbar", { timeout: 15000 });
  });

  test("Test A — Ingests and persists knowledge in authoritative memory store", async ({ data }: { data: DataFixture }) => {
    const statement = "My preferred programming language for backend development is Python.";

    // 1. Ingest fact into authoritative memory store
    const rememberRes = await data.rememberMemory(project.id, statement, {
      kind: "preference",
      entity_kind: "Language",
      entity_name: "Python",
    });
    expect(rememberRes.status).toBe("stored");

    // 2. Verify authoritative SQLite record persistence
    const records = await data.getMemoryRecords(project.id);
    const storedRecord = records.find((r: any) => r.text && r.text.includes("Python"));
    expect(storedRecord).toBeDefined();
    expect(storedRecord.status).toBe("active");

    // 3. Verify SQLite direct query
    const dbRows = data.querySqlite(
      `SELECT * FROM memories WHERE project_id = '${project.id}' AND text LIKE '%Python%'`
    );
    expect(dbRows.length).toBeGreaterThan(0);
    expect(dbRows[0].text).toContain("Python");
  });

  test("Test B — Recalls persisted memory across separate retrieval sessions", async ({ data }: { data: DataFixture }) => {
    // Query in a separate session without conversation history carryover
    const query = "What programming language do I prefer for backend development?";

    const recallRes = await data.recallMemory(project.id, query);
    expect(recallRes.results).toBeDefined();
    expect(recallRes.results.length).toBeGreaterThan(0);

    // Assert that the recalled context contains the previously persisted preference
    const matchedRecord = recallRes.results.find(
      (r: any) => r.content && r.content.toLowerCase().includes("python")
    );
    expect(matchedRecord).toBeDefined();
    expect(matchedRecord.content).toContain("Python");
  });

  test("Test C — Deduplication and idempotent relationship updates", async ({ data }: { data: DataFixture }) => {
    const entityName = `Lang_${Date.now()}`;

    // Ingest entity into Knowledge Graph
    const res1 = await data.rememberMemory(project.id, "Initial Rust description", {
      target: "graph",
      entity_kind: "Language",
      entity_name: entityName,
    });
    expect(res1.status).toBe("stored");

    // Ingest updated description for the same entity
    const res2 = await data.rememberMemory(project.id, "Updated Rust description with memory safety", {
      target: "graph",
      entity_kind: "Language",
      entity_name: entityName,
    });
    expect(res2.status).toBe("stored");

    // Verify deduplication: same entity ID is reused idempotently
    expect(res1.details.id).toBe(res2.details.id);

    // Verify entity count in graph: exactly 1 entity exists, no duplicate created
    const entities = await data.getGraphEntities(project.id, "Language", entityName);
    expect(entities.length).toBe(1);
    expect(entities[0].name).toBe(entityName);
  });

  test("Test D — Storage validation across SQLite, Markdown projections and Knowledge Graph", async ({ data }: { data: DataFixture }) => {
    // 1. Verify memory status endpoint reporting across tiers
    const status = await data.getMemoryStatus(project.id);
    expect(status).toBeDefined();
    expect(status.sqlite).toBeDefined();

    // 2. Verify Markdown memory projection accessibility
    const markdownFiles = await data.getMarkdownMemories(project.id);
    expect(Array.isArray(markdownFiles)).toBe(true);

    // 3. Verify Knowledge Graph adapter stats
    const graphStats = await data.getGraphStats(project.id);
    expect(graphStats).toBeDefined();
    expect(typeof graphStats.entity_count).toBe("number");
    expect(typeof graphStats.relationship_count).toBe("number");
  });
});
