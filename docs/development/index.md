# Developer & Contributor Guide

Welcome to the Alberto development guide. This section provides the technical knowledge needed to navigate the codebase, adhere to coding standards, add new APIs, write tests, and contribute features.

---

## Monorepo Layout

```text
ALBERTO---The-AI-Butler/
├── backend/                  # FastAPI backend service
│   ├── alberto/
│   │   ├── assistant_skills/ # Builtin assistant capabilities
│   │   ├── auth_providers/   # OAuth and identity provider adapters
│   │   ├── channels/         # Channel gateway adapters (Telegram, Slack)
│   │   ├── db/               # SQLAlchemy models and seed data
│   │   ├── engine/           # LangGraph compiler & step execution
│   │   ├── knowledge/        # Vector chunking, extraction, embeddings
│   │   ├── models/           # Pydantic schemas and database entities
│   │   ├── routers/          # FastAPI REST endpoints
│   │   ├── services/         # Core business logic (assistant, runs, tools)
│   │   └── util/             # Security, HTTP, and async utilities
│   ├── alembic/              # Relational migration revisions
│   └── tests/                # Backend pytest test suites
├── frontend/                 # Next.js 14 App Router frontend
│   ├── app/                  # Application routing and SPA layout
│   ├── components/           # UI components, canvas nodes, screens
│   └── lib/                  # API client, graph utilities, models catalog
├── tests/                    # Monorepo testing infrastructure
│   ├── backend/              # Unit and integration pytest suites
│   ├── e2e/                  # Playwright browser end-to-end suites
│   └── docs/                 # Documentation validation & screenshot capture
└── docs/                     # Documentation Markdown sources & assets
```

---

## Core Development Workflows

1. **Local Server:**
   ```bash
   ./start.sh
   ```
2. **Backend Tests:**
   ```bash
   cd backend && pytest
   ```
3. **Frontend Component Tests:**
   ```bash
   cd frontend && npm run test
   ```
4. **End-to-End Tests:**
   ```bash
   npm --prefix frontend run test:e2e
   ```
5. **Documentation Preview:**
   ```bash
   mkdocs serve
   ```

---

## In This Section

- [Contributing Standards](contributing.md) — Code style, pull request workflows, and conventional commit guidelines.
- [Testing Infrastructure](testing.md) — Running Pytest, Vitest, and Playwright E2E suites.
- [Extending Alberto](extending-alberto.md) — Adding custom tools, specialist agents, and workflow node types.
