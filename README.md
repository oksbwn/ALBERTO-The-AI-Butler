# Alberto — Local-First AI Home Butler & Agentic Workflow Platform

**Alberto** is a privacy-conscious, local-first AI Home Butler and visual agentic workflow orchestration platform. It pairs an interactive, split-screen conversational assistant with a powerful node-based canvas for designing, compiling, and running resilient multi-agent automation workflows.

Designed with zero external infrastructure overhead, Alberto runs self-contained out of the box using embedded SQLite, ChromaDB, and an in-process async task scheduler.

---

## Key Features

- **Interactive AI Home Butler & Dashboard**: Split-screen interface featuring live metrics, recent events, quick-launch actions, and streaming chat with generative UI components.
- **Visual Workflow Builder (React Flow)**: Drag-and-drop node graph canvas (`@xyflow/react`) supporting complex DAG topologies:
  - *Nodes*: Agent, LLM, Router, Classifier, Subworkflow, Loop, Parallel Fan-out, Join, Human-in-the-Loop Input, Event Triggers, Webhooks, and Handoffs.
- **Local-First & Zero-Infra Architecture**:
  - Embedded SQLite for application relational data and LangGraph checkpoint persistence.
  - In-process ChromaDB vector store for RAG and semantic long-term memory.
  - Native asynchronous task queue and cron scheduler without Redis or external message brokers.
- **Extensible Model Registry**: First-class support for OpenAI, Anthropic, Google Gemini, Ollama, and local OpenAI-compatible endpoints with strict routing and no hidden cloud fallbacks.
- **MCP & Tooling Ecosystem**: Integration with Model Context Protocol (MCP) servers, builtin sandboxed tools (Python, REST, Calculator, Recall), and capability-based authorization gates (`required_entitlements`).
- **Security & Reliability Hardening**: At-rest Fernet encryption for secrets, SSRF-protected egress proxies, granular role-based access control, and automatic error handling.

---

## Repository Structure

```text
Alberto/
├── backend/            # FastAPI backend & LangGraph execution engine
│   ├── alberto/        # Core application modules (engine, API, tools, memory, services)
│   ├── migrations/     # Alembic database migration scripts
│   ├── schemas/        # JSON schemas for node specifications & workflow validation
│   └── Dockerfile      # Backend container definition
├── frontend/           # Next.js 14 web console
│   ├── app/            # App router pages & layouts
│   ├── components/     # UI screens, React Flow canvas nodes, and generative components
│   ├── lib/            # API client, graph utilities, and model definitions
│   └── Dockerfile      # Frontend container definition
├── data/               # Local persistent storage root
│   ├── db/             # SQLite databases (alberto.db, checkpoints.sqlite)
│   ├── chroma/         # Vector embeddings & collections
│   ├── memory/         # Long-term agent memory
│   ├── logs/           # Application execution logs
│   └── config/         # Master encryption key (master.key)
├── docs/               # System architecture, security audits, and migration guides
├── tests/              # Backend (pytest) and frontend (vitest) test suites
├── docker-compose.yml  # Multi-container orchestration definition
├── start.sh            # Root launcher script (concurrent backend + frontend)
├── test.sh             # Unified test runner
└── README.md           # Project documentation
```

---

## Prerequisites

- **Python**: `>= 3.11` (Python 3.11–3.13 supported)
- **Node.js**: `>= 18.0` (`pnpm` or `npm`)
- **Docker & Docker Compose** *(optional for containerized deployment)*

---

## Getting Started

### Option 1: Quickstart via Root Launcher Script

1. **Clone the repository and copy environment defaults**:
   ```bash
   cp .env.example .env
   ```

2. **Run the launcher**:
   ```bash
   chmod +x start.sh
   ./start.sh
   ```

The script verifies dependencies, applies database migrations, and launches:
- **Frontend Web Console**: [http://localhost:3000](http://localhost:3000)
- **Backend API & Swagger Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)

**Default Credentials**:
- **Email / Username**: `admin@alberto.local` (or `admin`)
- **Password**: `alberto-admin` (or `password`)

---

### Option 2: Docker Compose

Spin up the entire stack with a single command:

```bash
docker compose up --build
```

Persistent volumes are mapped to preserve SQLite databases, ChromaDB embeddings, and encryption keys across restarts.

---

### Option 3: Manual Local Development

#### Backend Setup

```bash
cd backend
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate
# On Windows (PowerShell):
# .venv\Scripts\Activate.ps1

pip install -e ".[dev,vectors,providers]"
alembic upgrade head
uvicorn alberto.main:app --reload --port 8000
```

#### Frontend Setup

```bash
cd frontend
pnpm install   # or npm install
pnpm dev       # or npm run dev
```

---

## Running Tests

Execute the full regression and unit test suite:

```bash
# Unified runner
chmod +x test.sh
./test.sh

# Or backend tests directly
pytest tests/backend/ -v

# Or frontend component and smoke tests
cd frontend && pnpm test
```

---

## Acknowledgements & Credits

Alberto builds upon the pioneering architecture and concepts of [Forge](https://github.com/nihalashetty/Forge), created by [Nihal A Shetty](https://github.com/nihalashetty).

Special thanks and credit go to **Nihal A Shetty** for the original workflow canvas design, graph compilation paradigms, and agent orchestration patterns that laid the bedrock for Alberto's workflow engine.

---

## License

This project is open-source and licensed under the [MIT License](LICENSE).
