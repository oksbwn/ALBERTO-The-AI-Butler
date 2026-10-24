# Unified Memory Manager

Implemented in `backend/alberto/services/unified_memory.py`, the **Unified Memory Manager** coordinates knowledge retrieval across episodic memories, vector embeddings, and knowledge graph relationships.

---

## 1. Context Synthesis & Recall Pipeline

When a user submits a query, Alberto triggers a multi-stage recall sequence:

```mermaid
sequenceDiagram
    autonumber
    participant Asn as Assistant Service
    participant UMM as Unified Memory Manager
    participant Episodic as Episodic Store (SQLite)
    participant Chroma as ChromaDB Vector Store
    participant Graph as Ladybug Knowledge Graph

    Asn->>UMM: recall(query="What is my server IP and preferred language?", session_id)
    par Query Episodic Facts
        UMM->>Episodic: fetch_facts(user_id)
        Episodic-->>UMM: [preferred_language: Python]
    and Query Vector Embeddings
        UMM->>Chroma: similarity_search(query, top_k=4)
        Chroma-->>UMM: [Chunk: "Server IP is 192.168.1.50"]
    and Query Knowledge Graph
        UMM->>Graph: query_entities(entities=["server", "language"])
        Graph-->>UMM: [server - HAS_IP -> 192.168.1.50]
    end
    UMM->>UMM: Deduplicate, score, and rank returned facts
    UMM-->>Asn: Assembled Context Block
```

---

## 2. Autonomous Memory Learning & Curation

When the **Memory Learning** toggle is enabled, Alberto automatically learns from conversation turns:

1. **Extraction Pipeline (`memory_curator.py`):** After a conversation turn finishes, an asynchronous worker evaluates the exchange.
2. **Fact Filtering:** Ephemeral greetings and trivial chit-chat are discarded. Only persistent facts, preferences, credentials, and relationship updates are extracted.
3. **Contradiction Resolution:** If a new fact contradicts an older fact (e.g., "I moved to Seattle" vs older "I live in Boston"), the older fact is superseded with a timestamped deprecation flag rather than abruptly deleted.
4. **User Governance:** Users can view, edit, or delete stored facts at any time from the **Knowledge &rarr; Long-Term Memory** screen.
