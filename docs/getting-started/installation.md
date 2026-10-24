# Development Installation

This guide walks through configuring a bare-metal local development environment for the Alberto monorepo without Docker.

---

## Repository Structure

The Alberto repository is organized as a unified monorepo:

```text
ALBERTO---The-AI-Butler/
├── backend/            # FastAPI backend application, services, and database models
│   ├── alberto/        # Core Python package (routers, services, engine, memory)
│   ├── alembic/        # Database schema migrations
│   ├── pyproject.toml  # Python package specifications and tooling
│   └── requirements.txt
├── frontend/           # Next.js 14 App Router single-page application
│   ├── app/            # App routes and page layout
│   ├── components/     # UI design system, canvas, and subsystem screens
│   ├── lib/            # API client, graph compiler, and model utilities
│   └── package.json    # TypeScript dependencies and build scripts
├── tests/              # Multi-tier testing suite (backend unit, frontend, and e2e)
│   ├── backend/        # Pytest test suites
│   ├── e2e/            # Playwright end-to-end integration tests
│   └── docs/           # Documentation validation and screenshot capture tools
├── data/               # Default local persistent data directory (SQLite, Chroma, keys)
└── docs/               # Markdown source for this documentation portal
```

---

## 1. Backend Environment Setup

Alberto requires Python 3.11 or 3.12. Ensure you have the `python3-venv` package installed on Debian/Ubuntu systems.

### Create and Activate Virtual Environment

=== "Linux & macOS"
    ```bash
    cd backend
    python3 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    ```

=== "Windows (PowerShell)"
    ```powershell
    cd backend
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    ```

### Environment Configuration

Copy the example environment configuration into the root or `backend/` directory:

```bash
cp ../.env.example ../.env
```

Key environment settings to verify:

```ini
# Persistence Directory (defaults to ./data relative to repo root)
ALBERTO_DATA_DIR=data

# Application Ports
ALBERTO_PORT=8000
PORT=8000

# Authentication Defaults (used during first database initialization)
ALBERTO_BOOTSTRAP_ADMIN_EMAIL=admin
ALBERTO_BOOTSTRAP_ADMIN_PASSWORD=password
ALBERTO_SECRET_KEY=generate_a_secure_random_string_32_chars_min

# Local Checkpointer
ALBERTO_CHECKPOINT_BACKEND=sqlite
```

### Initialize Database & Migrations

Alberto automatically runs database migrations and seeds bootstrap data upon startup, but you can also manually verify migrations:

```bash
cd backend
alembic upgrade head
```

### Launch Backend Server

```bash
uvicorn alberto.main:app --host 127.0.0.1 --port 8000 --reload
```

Verify backend health:
```bash
curl http://127.0.0.1:8000/health
# Returns: {"status":"ok","version":"0.1.0"}
```

---

## 2. Frontend Environment Setup

The Alberto frontend is built with Next.js 14, React 18, and `@xyflow/react`.

### Install Node Dependencies

```bash
cd frontend
npm install
```

### Configure Frontend Environment

Create `frontend/.env.local` if you need custom API URLs:

```ini
NEXT_PUBLIC_ALBERTO_API_URL=http://127.0.0.1:8000
```

### Launch Development Server

```bash
npm run dev
```

The frontend will start on [http://localhost:3000](http://localhost:3000).

---

## 3. Verify Running Services

With both services active, navigate to [http://localhost:3000](http://localhost:3000) in your browser. You will be greeted by the login screen or direct workspace view.
