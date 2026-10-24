# Platform Glossary

A comprehensive terminology glossary for Alberto concepts, architectures, and components.

---

### A
- **Agent:** An autonomous entity with an LLM reasoning backend, system instructions, and tool whitelist.
- **Alembic:** Python database migration tool used by Alberto to manage SQLite relational schema revisions.
- **AsyncSqliteSaver:** LangGraph's asynchronous SQLite checkpointer saving execution thread snapshots.
- **Audit Middleware:** Request interceptor recording endpoint, user ID, status code, and latency in `audit_logs`.
- **Automate:** Alberto's visual workflow designer and execution engine powered by React Flow and LangGraph.

### B
- **BM25:** Sparse lexical ranking algorithm used in hybrid retrieval alongside dense vector embeddings.
- **Butler:** Alberto's conversational Master Coordinator persona (`assistant.py`).

### C
- **Channel Gateway:** Inbound messaging adapter managing Telegram, Slack, and webhook integrations.
- **Checkpointer:** The SQLite persistence layer that stores LangGraph thread execution snapshots after each node.
- **ChromaDB:** Local embedded vector database used by Alberto for semantic document retrieval.

### D
- **DAG (Directed Acyclic Graph):** Graph topology where nodes connect directionally without closed loops.
- **Danger Level:** Tool safety categorization (`read_only`, `idempotent`, `destructive`).
- **Dynamic Ontology:** An entity-relationship schema that grows dynamically through conversational extraction.

### E
- **Episodic Memory:** Stored factual statements and user preferences learned over time.
- **FastEmbed:** Local ONNX-based vector embedding generation library requiring zero cloud APIs.

### H
- **HITL (Human-In-The-Loop):** Execution pause requiring an operator approval token before a destructive tool runs.

### L
- **Ladybug:** SQLite-backed graph database engine utilized by Alberto for dynamic knowledge graph storage.
- **LangGraph:** MIT-licensed cyclic graph and state engine used for Alberto's agent loops and workflows.

### M
- **Master Coordinator:** The root conversational assistant node that analyzes user queries and delegates tasks.
- **MCP (Model Context Protocol):** Anthropic's open protocol for connecting LLMs to external tools over stdio/SSE.

### R
- **ReAct (Reason + Act):** Cyclical agent pattern alternating between model reasoning and tool execution.
- **RRF (Reciprocal Rank Fusion):** Algorithm for merging and re-scoring dense and sparse search results.

### S
- **Specialist Agent:** Dedicated subagent configured with specific tools, custom prompts, and model backends.
- **SSE (Server-Sent Events):** HTTP streaming standard used by Alberto for real-time token delivery.

### W
- **WAL (Write-Ahead Logging):** SQLite journal mode permitting concurrent readers without blocking writers.
