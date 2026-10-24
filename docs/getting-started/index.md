# Getting Started with Alberto

This guide walks you through installing, configuring, and verifying your first running Alberto deployment.

---

## Prerequisites

Before setting up Alberto, ensure your host environment meets the following baseline requirements:

| Component | Minimum Specification | Recommended Specification |
| :--- | :--- | :--- |
| **Operating System** | Linux (Ubuntu 22.04+), macOS 13+, Windows 11 (WSL2 or PowerShell) | Linux x86_64 / arm64 or macOS Apple Silicon |
| **Python** | Python 3.11 or 3.12 | Python 3.12 with `venv` |
| **Node.js** | Node.js 18.x or 20.x | Node.js 20 LTS with `npm` or `pnpm` |
| **Memory (RAM)** | 4 GB (without local LLM) | 16 GB - 32 GB (if running local Ollama/vLLM) |
| **Disk Space** | 2 GB free disk space | 20+ GB SSD (for vector embeddings and models) |
| **Container Engine** | Docker 24+ & Docker Compose (optional) | Docker 26+ with Buildx |

---

## Quick Start (Pre-Built Single Script)

If you have already cloned the Alberto repository, you can launch both backend and frontend environments in development mode with the root launcher:

=== "Linux & macOS"
    ```bash
    git clone https://github.com/oksbwn/ALBERTO---The-AI-Butler.git
    cd ALBERTO---The-AI-Butler
    ./start.sh
    ```

=== "Windows (PowerShell)"
    ```powershell
    git clone https://github.com/oksbwn/ALBERTO---The-AI-Butler.git
    cd ALBERTO---The-AI-Butler
    # Start backend
    .\backend\.venv\Scripts\python.exe -m uvicorn alberto.main:app --host 127.0.0.1 --port 8000
    # In another terminal, start frontend
    cd frontend
    npm.cmd run dev
    ```

Once running:
- **Web Console:** Open [http://localhost:3000](http://localhost:3000)
- **FastAPI Documentation:** Open [http://localhost:8000/api/docs](http://localhost:8000/api/docs)
- **Health Check:** `curl http://localhost:8000/health`

---

## Next Steps

Follow the detailed walkthroughs to customize your deployment:

1. [Development Installation](installation.md) — Set up virtual environments, install Python & TypeScript dependencies.
2. [Docker Deployment](docker.md) — Run Alberto as an isolated single container.
3. [First Admin Setup & Login](first-admin-and-login.md) — Authenticate, manage workspace tenants, and explore security roles.
4. [Configuring First LLM](first-llm.md) — Connect local Ollama or cloud providers (OpenAI, Anthropic, Gemini).
5. [Creating Specialist Agents](first-agent.md) — Build custom AI specialists with dedicated tools.
6. [First Butler Conversation](first-conversation.md) — Chat with Alberto and observe episodic memory learning.
7. [Connecting Integrations & MCP](first-integration.md) — Register REST tools and Model Context Protocol servers.
8. [Building First Visual Workflow](first-workflow.md) — Design a multi-agent automation DAG on the visual canvas.
9. [Troubleshooting Setup](troubleshooting.md) — Resolve port collisions, database locks, and dependency errors.
