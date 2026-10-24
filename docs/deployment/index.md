# Deployment & Operations Overview

Alberto is designed for predictable, maintainable deployments across local workstations, dedicated home servers, and cloud virtual machines.

---

## Deployment Topologies

```mermaid
graph TD
    subgraph Single Container (Default)
        Container[ghcr.io/oksbwn/alberto:latest]
        Container --> Super[supervisord]
        Super --> App[FastAPI Backend :8000]
        Super --> UI[Next.js Frontend :3000]
        Super --> Worker[Background Task Worker]
        Container <--> DataVol[(/data Volume)]
    end

    subgraph External / Host Services (Optional)
        Ollama[Ollama :11434]
        vLLM[vLLM Inference Server]
        RemoteChroma[Remote ChromaDB]
    end

    Container -.->|host.docker.internal| Ollama
    Container -.->|HTTP| vLLM
    Container -.->|HTTP| RemoteChroma
```

---

## Key Operational Properties

- **Zero Database Setup:** Ships with pre-configured embedded SQLite databases in WAL mode. No external PostgreSQL, MySQL, or Redis instances are required.
- **Single Persistent Volume:** All database files, vectors, model caches, and keys are stored in `/data`.
- **Automatic Migrations:** Database migrations apply automatically during container startup.
- **Fast Startup:** The entire container boots and becomes healthy in under 4 seconds.

---

## In This Section

- [Docker Production Build](docker.md) — Multi-stage Dockerfile architecture, image building, and container runtime layout.
- [Environment Variables](environment-variables.md) — Comprehensive reference of all verified configuration settings and defaults.
- [Health & Monitoring](operations.md) — Liveness probes, logging, OpenTelemetry integration, and routine maintenance.
