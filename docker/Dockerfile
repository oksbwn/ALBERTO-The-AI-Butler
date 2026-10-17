# ==============================================================================
# Alberto - Single Unified Docker Image
# Multi-stage build assembling FastAPI backend and Next.js frontend.
# Build context MUST be repository root:
#   docker build -f docker/Dockerfile -t alberto:latest .
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Build Next.js Frontend
# ------------------------------------------------------------------------------
FROM node:22-alpine AS frontend-builder
WORKDIR /repo
RUN corepack enable

COPY pnpm-lock.yaml pnpm-workspace.yaml ./
COPY frontend/package.json frontend/package.json
RUN pnpm install --frozen-lockfile || pnpm install

COPY . .
RUN mkdir -p frontend/public

# Server-side proxy target: defaults to local backend at 127.0.0.1:8000
ARG ALBERTO_API_URL=http://127.0.0.1:8000
ENV ALBERTO_API_URL=${ALBERTO_API_URL}
ENV FORGE_API_URL=${ALBERTO_API_URL}
ENV NEXT_OUTPUT=standalone

RUN rm -rf frontend/.next && (pnpm --filter alberto-frontend build || (cd frontend && pnpm build))

# ------------------------------------------------------------------------------
# Stage 2: Unified Production Runtime (Python 3.12 + Node 22 runtime)
# ------------------------------------------------------------------------------
FROM python:3.12-slim AS runner

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NODE_ENV=production \
    FORGE_FASTEMBED_CACHE_DIR=/app/.fastembed-cache \
    ALBERTO_DATA_DIR=/data

# Install runtime utilities, gosu for root-drop, and C++ runtime for Node
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates libstdc++6 build-essential gosu \
    && rm -rf /var/lib/apt/lists/*

# Copy Node binary & standard modules from official node image
COPY --from=node:22-bookworm-slim /usr/local/include/node /usr/local/include/node
COPY --from=node:22-bookworm-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node

# Verify Node runtime works in Debian runner
RUN node --version

WORKDIR /app

# Install Python backend dependencies
COPY backend/pyproject.toml backend/README.md ./
RUN mkdir -p alberto && touch alberto/__init__.py
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    pip install -e ".[all]"

# Copy backend source & schemas
COPY backend/alberto ./alberto
COPY backend/forge ./forge
COPY backend/alembic.ini ./alembic.ini
COPY backend/migrations ./migrations
COPY backend/schemas ./schemas
COPY version.json ./version.json

# Pre-download default local fastembed model for offline operation
RUN python -c "import os; from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir=os.environ.get('ALBERTO_FASTEMBED_CACHE_DIR') or os.environ.get('FORGE_FASTEMBED_CACHE_DIR', '/app/.fastembed-cache'))"

# Copy Next.js standalone application
COPY --from=frontend-builder /repo/frontend/.next/standalone ./
COPY --from=frontend-builder /repo/frontend/.next/static ./frontend/.next/static
COPY --from=frontend-builder /repo/frontend/public ./frontend/public

# Copy entrypoint script
COPY docker/entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# Remove build-essential to slim image after native wheel installs
RUN apt-get purge -y --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/*

# Configure non-root user and persistent directory
RUN useradd --create-home --uid 10001 alberto \
    && mkdir -p /app/data /data \
    && chown -R alberto:alberto /app /data

VOLUME ["/data"]
EXPOSE 3000 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/readyz || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["start"]
