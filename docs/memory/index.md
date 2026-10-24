# Memory & Knowledge Management

Alberto integrates three complementary memory models into a single unified architecture, providing immediate conversation awareness, semantic document recall, and entity-relationship reasoning.

![Long-Term Memory](../assets/screenshots/knowledge/memory.png){: .doc-screenshot }
<p class="doc-caption">Figure 7.1: Long-term episodic memory manager displaying extracted user facts and preferences.</p>

---

## The Three Tiers of Alberto Memory

```mermaid
graph TD
    Query[User Message / Context Query] --> UnifiedManager[Unified Memory Manager]
    
    subgraph Tier 1: Episodic & Working
        UnifiedManager <--> Working[Sliding-Window Buffer]
        UnifiedManager <--> Episodic[Extracted User Facts & Preferences]
    end

    subgraph Tier 2: Semantic Vector Store
        UnifiedManager <--> FastEmbed[Local FastEmbed Engine]
        FastEmbed <--> ChromaDB[(ChromaDB Vector Store)]
        UnifiedManager <--> BM25[BM25 Lexical Keyword Search]
    end

    subgraph Tier 3: Dynamic Knowledge Graph
        UnifiedManager <--> Ladybug[(Ladybug SQLite Graph Engine)]
        Ladybug <--> Ontology[Dynamic Ontology & Human Review Gate]
    end
```

---

## Memory Tiers Overview

| Memory Tier | Storage Technology | Primary Role |
| :--- | :--- | :--- |
| **Working & Episodic Memory** | SQLite + In-Memory Cache | Immediate conversation turns, user preferences, explicit instructions. |
| **Semantic Vector Store (RAG)** | ChromaDB + FastEmbed (`bge-small-en-v1.5`) | Unstructured document retrieval, PDF parsing, hybrid dense + sparse search. |
| **Knowledge Graph** | Ladybug SQLite Engine | Typed entities, relational predicates, multi-hop fact traversal. |
| **Markdown Notes** | Direct Flat Files (`data/memory/*.md`) | Human-readable notes and structured logs editable directly in markdown. |

---

## In This Section

- [Unified Memory Manager](unified-memory.md) — How Alberto unifies episodic recall with autonomous memory learning.
- [Vector Store & RAG](vector-store.md) — Document ingestion, recursive chunking, embeddings, and hybrid search.
- [Knowledge Graph & Dynamic Ontology](knowledge-graph.md) — Extracting entity-relationship graphs with human review gates.
- [Markdown Memory](markdown-memory.md) — Plaintext markdown memory curation and local file persistence.
