# Forge API - FastAPI on the MIT LangChain/LangGraph stack.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # The default local (fastembed) embedder's model is baked into the image at this path
    # (see the pre-download step below); the app reads the same dir at runtime, so ingestion
    # works fully offline with no first-run download. Outside the /app/.data volume, so it's
    # part of the image, not the persisted volume.
    FORGE_FASTEMBED_CACHE_DIR=/app/.fastembed-cache

# Build deps for psycopg/cryptography wheels (kept minimal; most ship manylinux wheels).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Build context is the REPO ROOT (see docker-compose.yml: context: . / dockerfile:
# apps/api/Dockerfile) so we can COPY packages/schemas, which lives above apps/api.
#
# Third-party deps install in a layer keyed only on pyproject.toml + a package stub, so a
# pure forge/ source edit does NOT invalidate this (expensive) layer. The editable install
# just links /app/forge onto sys.path, so overwriting the stub with the real tree afterwards
# needs no reinstall. The BuildKit pip cache mount reuses already-downloaded wheels instead
# of re-hitting PyPI even when the layer does re-run (e.g. a pyproject.toml change), so a
# source edit can never turn into a PyPI round-trip / offline build failure.
COPY backend/pyproject.toml backend/README.md ./
RUN mkdir -p alberto && touch alberto/__init__.py
# Local-first extras: model providers, vectors, knowledge, MCP (zero Postgres/Redis).
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    pip install -e ".[all]"

# Real source over the stub (this layer changes on every edit, but it is AFTER the install).
COPY backend/alberto ./alberto
COPY backend/forge ./forge
COPY backend/alembic.ini ./alembic.ini
COPY backend/migrations ./migrations
# JSON Schemas bake at /app/schemas so config.py's schemas_dir default resolves.
COPY backend/schemas ./schemas

# Pre-download the default local embedder (fastembed) model into the image so the container
# ships self-contained: no ~130MB HuggingFace fetch on the first ingest, and no runtime egress
# to huggingface.co (which a locked-down deploy may block). Keep this model id in sync with
# alberto.knowledge.embeddings._DEFAULT_FASTEMBED. Runs before the chown so the forge user owns it.
RUN python -c "import os; from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir=os.environ.get('ALBERTO_FASTEMBED_CACHE_DIR') or os.environ.get('FORGE_FASTEMBED_CACHE_DIR', '/app/.fastembed-cache'))"

# Run as a non-root user. Pre-create /app/data and /app/.data
# owned by forge: an empty named volume mounted there copies the image mountpoint's ownership on
# first use, so this keeps the volume forge-writable.
RUN useradd --create-home --uid 10001 forge \
    && mkdir -p /app/data /app/.data \
    && chown -R forge:forge /app
USER forge

EXPOSE 8000

# Container healthcheck hits the readiness probe (DB + checkpointer).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/readyz || exit 1

# Apply migrations, then serve. (Schema also self-bootstraps via create_all, but on managed
# Postgres `alembic upgrade head` is the controlled path.)
CMD ["sh", "-c", "alembic upgrade head && uvicorn alberto.main:app --host 0.0.0.0 --port 8000"]
