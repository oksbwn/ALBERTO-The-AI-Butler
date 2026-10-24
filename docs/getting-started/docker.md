# Docker Deployment

Alberto provides an optimized single-container architecture that packages the FastAPI backend, the Next.js frontend, the embedded SQLite database, the Chroma vector database, and the background worker queue into one unified image.

---

## 1. Quick Start with Docker Compose

The simplest way to deploy Alberto is using Docker Compose:

```bash
# Clone the repository
git clone https://github.com/oksbwn/ALBERTO---The-AI-Butler.git
cd ALBERTO---The-AI-Butler

# Build and start the container
docker compose up -d --build
```

### Checking Container Status

```bash
docker compose ps
docker compose logs -f alberto
```

The container starts `supervisord`, which launches both Uvicorn and Next.js. Access the web console at:

[http://localhost:3000](http://localhost:3000)

---

## 2. Docker Compose Architecture

Here is the verified `docker-compose.yml` specification:

```yaml
services:
  alberto:
    build:
      context: .
      dockerfile: docker/Dockerfile
    image: ghcr.io/oksbwn/alberto:latest
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      ALBERTO_ENVIRONMENT: production
      ALBERTO_DATA_DIR: /data
      ALBERTO_DATABASE_URL: sqlite+aiosqlite:///data/db/alberto.db
      ALBERTO_CHECKPOINT_BACKEND: sqlite
      ALBERTO_ENABLE_SCHEDULER: "true"
      ALBERTO_SCHEDULER_LEADER: "true"
      ALBERTO_JWT_SECRET: ${ALBERTO_JWT_SECRET:-alberto-local-secret-key-32chars-min!}
      ALBERTO_BOOTSTRAP_ADMIN_EMAIL: ${ALBERTO_BOOTSTRAP_ADMIN_EMAIL:-admin}
      ALBERTO_BOOTSTRAP_ADMIN_PASSWORD: ${ALBERTO_BOOTSTRAP_ADMIN_PASSWORD:-password}
      ALBERTO_PUBLIC_BASE_URL: http://localhost:8000
      ALBERTO_PUBLIC_CONSOLE_URL: http://localhost:3000
      ALBERTO_CORS_ORIGINS: '["http://localhost:3000"]'
      ALBERTO_EGRESS_ALLOW_PRIVATE_HOSTS: '["host.docker.internal"]'
      OPENAI_API_KEY: ${OPENAI_API_KEY:-}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}
    volumes:
      - alberto-data:/data
    ports:
      - "3000:3000"
      - "8000:8000"

volumes:
  alberto-data:
```

---

## 3. Persistent Storage Configuration

The container maps all persistent application state to a single Docker volume:

`/data`

Inside `/data`, the following directory structure is created and maintained:

```text
/data
├── db/
│   ├── alberto.db          # Main SQLite application database
│   ├── checkpoints.sqlite  # LangGraph durable checkpointer
│   ├── queue.sqlite        # SQLite-backed background task queue
│   └── ladybug/            # Knowledge graph tables
├── chroma/                 # Embedded ChromaDB vector store
├── models/
│   └── fastembed/          # Cached local ONNX embedding weights
└── config/
    └── master.key          # AES-256 encryption key for credentials
```

> [!IMPORTANT]
> Always retain the `alberto-data` volume across image upgrades. Migrating to new releases simply requires pulling or building the latest image and starting the container; Alembic migrations will run automatically against `/data/db/alberto.db`.

---

## 4. Connecting to Host Ollama

To allow the Alberto container to access an Ollama instance running on the host machine (e.g. `http://localhost:11434`):

1. The container defines `extra_hosts: ["host.docker.internal:host-gateway"]`.
2. `ALBERTO_EGRESS_ALLOW_PRIVATE_HOSTS` includes `host.docker.internal`, allowing the outbound guardrail to permit this request.
3. In the Alberto Settings UI, register the Ollama provider using:
   ```text
   http://host.docker.internal:11434
   ```
4. On Linux hosts, ensure Ollama is listening on all interfaces:
   ```bash
   OLLAMA_HOST=0.0.0.0:11434 ollama serve
   ```
