<div align="center">

  <img src="docs/assets/alberto_icon.png" alt="Alberto Logo" width="128" height="128" style="border-radius: 28px; box-shadow: 0 10px 25px rgba(0,0,0,0.3); margin-bottom: 12px;" />

  # Alberto — The AI Butler & Visual Agentic Orchestrator

  **Privacy-conscious, local-first conversational home concierge and visual multi-agent workflow platform.**

  [![CI](https://github.com/oksbwn/ALBERTO---The-AI-Butler/actions/workflows/ci.yml/badge.svg)](https://github.com/oksbwn/ALBERTO---The-AI-Butler/actions/workflows/ci.yml)
  [![Release](https://github.com/oksbwn/ALBERTO---The-AI-Butler/actions/workflows/release.yml/badge.svg)](https://github.com/oksbwn/ALBERTO---The-AI-Butler/actions/workflows/release.yml)
  [![Version](https://img.shields.io/github/v/tag/oksbwn/ALBERTO---The-AI-Butler?color=0070f3&label=version&logo=github)](https://github.com/oksbwn/ALBERTO---The-AI-Butler/releases)
  [![Docker Image](https://img.shields.io/badge/docker-ghcr.io-2496ED?logo=docker&logoColor=white)](https://github.com/oksbwn/ALBERTO---The-AI-Butler/pkgs/container/alberto)
  [![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-3776AB?logo=python&logoColor=white)](https://python.org)
  [![Next.js](https://img.shields.io/badge/next.js-14.2-black?logo=next.js&logoColor=white)](https://nextjs.org)
  [![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
  [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

---

## Overview

**Alberto** pairs an interactive, split-screen conversational assistant with a high-performance node-based canvas for designing, compiling, and executing multi-agent workflows. 

Engineered with **zero external infrastructure dependencies**, Alberto runs completely self-contained out of the box using embedded SQLite, an in-process ChromaDB vector store, and a native asynchronous task scheduler.

---

## Key Capabilities

- 🤖 **Interactive AI Home Butler & Live Console**: Split-screen dashboard with real-time home metrics, event feeds, quick-launch actions, and streaming conversational chat with generative UI widgets.
- 🎨 **Visual Workflow Builder (React Flow)**: Drag-and-drop node graph canvas (`@xyflow/react`) supporting complex DAG topologies:
  - *Nodes*: Agent, LLM, Router, Classifier, Subworkflow, Loop, Parallel Fan-out, Join, Human-in-the-Loop Input, Event Triggers, Webhooks, and Handoffs.
- 🔒 **Local-First & Zero-Infra Architecture**:
  - Embedded SQLite (WAL mode + concurrency locks) for relational application data and LangGraph checkpoint states.
  - In-process ChromaDB vector store for RAG, document grounding, and semantic long-term memory.
  - Asynchronous background task queue and cron scheduler without external message brokers (no Redis or Kafka required).
- 🧠 **Extensible Multi-Provider Model Hub**: First-class support for OpenAI, Anthropic, Google Gemini, Ollama, and local OpenAI-compatible endpoints with strict routing and no hidden cloud telemetry.
- 🔌 **MCP & Sandboxed Tool Ecosystem**: Native integration with Model Context Protocol (MCP) servers, builtin sandboxed tools (Python, REST, Calculator, Recall), and capability-based authorization gates (`required_entitlements`).
- 🛡️ **Enterprise Security Hardening**: At-rest Fernet encryption for credentials and API keys, SSRF-guarded outbound proxies, granular role-based access control (RBAC), and automatic error recovery.
- 📦 **Single Unified Container Image**: Multi-stage Docker image orchestrating both FastAPI (backend) and Next.js (frontend) behind an unprivileged service supervisor with persistent storage mapped to `/data`.

---

## System Architecture

```text
Alberto/
├── backend/            # FastAPI backend & LangGraph execution engine
│   ├── alberto/        # Core engine (API routers, memory, tools, agent graphs)
│   ├── migrations/     # Alembic database migrations
│   └── schemas/        # JSON schemas for node specifications & graph validation
├── frontend/           # Next.js 14 web console
│   ├── app/            # App router pages, layouts, and API proxies
│   ├── components/     # UI widgets, React Flow canvas nodes, generative components
│   └── lib/            # Client SDK, graph utilities, and state stores
├── docker/             # Unified container packaging
│   ├── Dockerfile      # Multi-stage production build (FastAPI + Next.js standalone)
│   └── entrypoint.sh   # Runtime supervisor, storage initializer, and privilege dropper
├── data/               # Persistent storage mount point (/data)
│   ├── db/             # SQLite databases (alberto.db, checkpoints.sqlite)
│   ├── chroma/         # Vector embeddings & collections
│   ├── memory/         # Long-term agent memory markdown files
│   ├── logs/           # Application execution logs
│   └── config/         # Master encryption key (master.key)
├── tests/              # Unified test suites & reusable quality gates
│   ├── lint.sh         # Ruff (backend) + tsc --noEmit (frontend)
│   ├── run.sh          # Pytest (backend) + Vitest (frontend)
│   └── check.sh        # Consolidated sequential quality gate
├── release.sh          # Official release pipeline automation
└── docker-compose.yml  # Single-service container stack definition
```

---

## Quickstart

### Option 1: Docker (Recommended)

Run Alberto via Docker Compose or direct container launch:

```bash
# Using Docker Compose
docker compose up -d

# Or run official GHCR unified image directly
docker run -d \
  --name alberto \
  -p 3000:3000 \
  -p 8000:8000 \
  -v alberto_data:/data \
  -e ALBERTO_JWT_SECRET="your-secure-jwt-secret-at-least-32-chars-long" \
  ghcr.io/oksbwn/alberto:latest
```

Open your browser:
- **Web Console**: [http://localhost:3000](http://localhost:3000)
- **API Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Health Check**: [http://localhost:8000/readyz](http://localhost:8000/readyz)

**Default Credentials**:
- **Email / Username**: `admin@alberto.local` (or `admin`)
- **Password**: `alberto-admin` (or `password`)

---

### Option 2: Quickstart Script (Bare-Metal Local)

1. Clone repository and create local environment config:
   ```bash
   cp .env.example .env
   ```

2. Execute the launcher script:
   ```bash
   chmod +x start.sh
   ./start.sh
   ```

The script verifies system dependencies, runs Alembic database migrations, and concurrently starts both backend and frontend servers.

---

### Option 3: Manual Development Setup

#### Backend Setup

```bash
cd backend
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate
# On Windows (PowerShell):
# .venv\Scripts\Activate.ps1

pip install -e ".[all,dev]"
alembic upgrade head
uvicorn alberto.main:app --reload --port 8000
```

#### Frontend Setup

```bash
cd frontend
pnpm install    # or npm install
pnpm dev        # or npm run dev
```

---

## Quality Gate & Testing

Alberto enforces a strict quality gate locally and in CI:

```bash
# Run linting (Ruff + TypeScript typecheck)
./tests/lint.sh

# Run test suites (Pytest + Vitest)
./tests/run.sh

# Run complete quality gate (Lint -> Tests -> Next.js Build)
./tests/check.sh
```

---

## Release Pipeline (`release.sh`)

Official releases are managed using the automated release pipeline:

```bash
# Dry run simulation
./release.sh patch --dry-run

# Official release (patch, minor, or major)
./release.sh patch
```

`./release.sh` executes preflight safeguards, runs `./tests/check.sh`, updates `version.json`, commits uncommitted workspace changes into `chore(release): vX.Y.Z`, creates an annotated tag, and pushes to `origin`.

---

## Acknowledgements & Credits

Alberto builds upon the pioneering architecture and concepts of [Forge](https://github.com/nihalashetty/Forge), created by [Nihal A Shetty](https://github.com/nihalashetty).

Special thanks and credit go to **Nihal A Shetty** for the original workflow canvas design, graph compilation paradigms, and agent orchestration patterns that laid the bedrock for Alberto's workflow engine.

---

## License

This project is open-source and licensed under the [MIT License](LICENSE).
