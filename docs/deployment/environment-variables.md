# Environment Variables Reference

All configuration in Alberto is driven by environment variables parsed via Pydantic (`backend/alberto/config.py`). Values can be defined in a root `.env` file or passed directly into the container environment.

---

## 1. Core Platform & Directory Paths

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| **`ALBERTO_ENVIRONMENT`** | `development` | Operating environment (`development`, `staging`, `production`). |
| **`ALBERTO_DATA_DIR`** | `./data` | Root path for persistent SQLite, Chroma, and keys. |
| **`ALBERTO_DATABASE_URL`** | `sqlite+aiosqlite:///data/db/alberto.db` | SQLAlchemy connection string for the main database. |
| **`ALBERTO_CHECKPOINT_DB`** | `data/db/checkpoints.sqlite` | SQLite database file for LangGraph durable execution. |
| **`ALBERTO_CHECKPOINT_BACKEND`**| `sqlite` | Checkpointer backend (`sqlite` or `memory` for tests). |
| **`ALBERTO_QUEUE_DB`** | `data/db/queue.sqlite` | SQLite database file for background task queue. |
| **`ALBERTO_CHROMA_PATH`** | `data/chroma` | Directory for embedded ChromaDB collections. |
| **`ALBERTO_LADYBUG_PATH`** | `data/db/ladybug` | Directory for Ladybug knowledge graph tables. |
| **`ALBERTO_FASTEMBED_CACHE_DIR`**| `data/models/fastembed` | Local cache directory for ONNX embedding model weights. |
| **`ALBERTO_SECRET_KEY_FILE`** | `data/config/master.key` | Path to master AES-256 key for secret vault. |

---

## 2. Server Ports & Networking

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| **`ALBERTO_PORT`** / **`PORT`** | `8000` | Port for the FastAPI backend application. |
| **`ALBERTO_HOST`** | `0.0.0.0` | Bind host IP for backend server. |
| **`ALBERTO_PUBLIC_BASE_URL`** | `http://localhost:8000` | Canonical public URL for the backend API. |
| **`ALBERTO_PUBLIC_CONSOLE_URL`**| `http://localhost:3000` | Canonical public URL for the web console. |
| **`ALBERTO_CORS_ORIGINS`** | `["http://localhost:3000"]` | Allowed CORS origins as a JSON string list. |
| **`ALBERTO_EGRESS_ALLOW_PRIVATE_HOSTS`** | `[]` | List of private hosts permitted through the egress filter. |

---

## 3. Security & Authentication

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| **`ALBERTO_SECRET_KEY`** | *auto-generated* | HMAC-SHA256 signing secret for JWTs. |
| **`ALBERTO_JWT_EXPIRE_MINUTES`** | `15` | Access token lifespan in minutes. |
| **`ALBERTO_REFRESH_TOKEN_EXPIRE_DAYS`** | `30` | Refresh token lifespan in days. |
| **`ALBERTO_BOOTSTRAP_ADMIN_EMAIL`** | `admin` | Default email for first-time administrator account. |
| **`ALBERTO_BOOTSTRAP_ADMIN_PASSWORD`** | `password` | Default password for first-time administrator account. |
| **`ALBERTO_AUTH_RATE_LIMIT_PER_MINUTE`**| `10` | Maximum login attempts per IP per minute. |

---

## 4. Background Workers & Schedulers

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| **`ALBERTO_ENABLE_SCHEDULER`** | `true` | Set to `false` to disable cron triggers. |
| **`ALBERTO_SCHEDULER_LEADER`** | `true` | In multi-replica setups, only leader schedules jobs. |
| **`ALBERTO_WORKER_CONCURRENCY`**| `4` | Maximum parallel background jobs processed. |

---

## 5. Model Provider API Keys

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| **`OPENAI_API_KEY`** | *empty* | Default API key for OpenAI model access. |
| **`ANTHROPIC_API_KEY`** | *empty* | Default API key for Anthropic Claude model access. |
| **`GOOGLE_API_KEY`** | *empty* | Default API key for Google Gemini model access. |
| **`OLLAMA_BASE_URL`** | `http://127.0.0.1:11434` | Default endpoint for Ollama local inference. |
