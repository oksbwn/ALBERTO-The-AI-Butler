"use client";

/* Knowledge module root router & re-exports.
   Each knowledge type is maintained in its own dedicated screen file:
   - knowledge-playground.tsx: Multi-source recall tester, sub-agent simulation, & grounding matrix
   - knowledge-docs.tsx: Vector RAG files, folder hierarchy, chunk distributions, & search debugger
   - knowledge-qa.tsx: Curated Q&A pairs, category filters, & intent deflection matcher
   - knowledge-graph.tsx: LadybugDB property graph visualizer, entities, & domain ontology
   - knowledge-memory.tsx: Authoritative SQLite memories, synced Markdown files, & learning queue
*/

import { KnowledgePlaygroundScreen } from "./knowledge-playground";
import { KnowledgeDocsScreen } from "./knowledge-docs";
import { KnowledgeVectorScreen } from "./knowledge-vector";
import { KnowledgeQaScreen } from "./knowledge-qa";
import { KnowledgeGraphScreen } from "./knowledge-graph";
import { KnowledgeMemoryScreen } from "./knowledge-memory";

export { KnowledgePlaygroundScreen } from "./knowledge-playground";
export { KnowledgeDocsScreen } from "./knowledge-docs";
export { KnowledgeVectorScreen } from "./knowledge-vector";
export { KnowledgeQaScreen } from "./knowledge-qa";
export { KnowledgeGraphScreen } from "./knowledge-graph";
export { KnowledgeMemoryScreen } from "./knowledge-memory";
export { KnowledgeHistory } from "./knowledge-history";

export type KnowledgeSubNav = "playground" | "explorer" | "docs" | "vector" | "qa" | "graph" | "memory";

export function KnowledgeScreen({
  project,
  subNav = "playground",
}: {
  project: any;
  subNav?: KnowledgeSubNav;
  onNav?: (screen: string) => void;
}) {
  switch (subNav) {
    case "docs":
      return <KnowledgeDocsScreen project={project} />;
    case "vector":
      return <KnowledgeVectorScreen project={project} />;
    case "qa":
      return <KnowledgeQaScreen project={project} />;
    case "graph":
      return <KnowledgeGraphScreen project={project} />;
    case "memory":
      return <KnowledgeMemoryScreen project={project} />;
    case "playground":
    case "explorer":
    default:
      return <KnowledgePlaygroundScreen project={project} />;
  }
}
