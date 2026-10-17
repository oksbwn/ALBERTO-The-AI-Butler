#!/usr/bin/env bash
# ==============================================================================
# Alberto Docker Entrypoint
# Initializes storage, runs database migrations, and supervises FastAPI & Next.js.
# ==============================================================================

set -eo pipefail

echo "============================================================"
echo " Starting Alberto AI Butler Container"
echo "============================================================"

# If arguments were provided (e.g. bash, python, alembic), execute them directly
if [[ $# -gt 0 && "$1" != "start" ]]; then
  exec "$@"
fi

# 1. Prepare persistent storage directories
DATA_DIR="${ALBERTO_DATA_DIR:-/data}"
echo "Configuring persistent storage at: ${DATA_DIR}"
mkdir -p "${DATA_DIR}/db" "${DATA_DIR}/chroma" "${DATA_DIR}/memory" "${DATA_DIR}/logs" "${DATA_DIR}/config"
export ALBERTO_DATA_DIR="${DATA_DIR}"

# 2. Database Migrations
echo "Running database migrations (Alembic)..."
alembic upgrade head

# 3. Environment defaults
BACKEND_PORT="${PORT:-${ALBERTO_PORT:-8000}}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

# 4. Process management & clean termination
BACKEND_PID=""
FRONTEND_PID=""
SHUTTING_DOWN=0

cleanup() {
  if [[ "$SHUTTING_DOWN" -eq 1 ]]; then
    return
  fi
  SHUTTING_DOWN=1
  echo ""
  echo "Received termination signal. Shutting down Alberto services gracefully..."

  if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill -TERM "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill -TERM "$BACKEND_PID" 2>/dev/null || true
  fi

  # Allow graceful drain
  for i in $(seq 1 10); do
    if (! kill -0 "$BACKEND_PID" 2>/dev/null) && (! kill -0 "$FRONTEND_PID" 2>/dev/null); then
      break
    fi
    sleep 0.5
  done

  # Force kill if still running
  if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill -9 "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill -9 "$BACKEND_PID" 2>/dev/null || true
  fi

  echo "Alberto shutdown complete."
  exit 0
}

trap cleanup SIGINT SIGTERM EXIT

# 5. Start FastAPI Backend
echo "Starting FastAPI backend on port ${BACKEND_PORT}..."
uvicorn alberto.main:app --host 0.0.0.0 --port "${BACKEND_PORT}" &
BACKEND_PID=$!

# Wait for backend readiness before starting frontend
echo "Awaiting backend readiness..."
for i in $(seq 1 30); do
  if curl -s "http://127.0.0.1:${BACKEND_PORT}/readyz" >/dev/null 2>&1; then
    echo "✓ Backend is ready."
    break
  fi
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "❌ Error: Backend process exited prematurely." >&2
    exit 1
  fi
  sleep 1
done

# 6. Start Next.js Frontend (standalone server)
echo "Starting Next.js frontend on port ${FRONTEND_PORT}..."
export PORT="${FRONTEND_PORT}"
export HOSTNAME="0.0.0.0"
node frontend/server.js &
FRONTEND_PID=$!

sleep 1
if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
  echo "❌ Error: Frontend process failed to start." >&2
  exit 1
fi

echo ""
echo "============================================================"
echo "  Alberto AI Home Butler is live!"
echo "  Web UI Console : http://localhost:${FRONTEND_PORT}"
echo "  Backend API    : http://localhost:${BACKEND_PORT}"
echo "  Health probe   : http://localhost:${BACKEND_PORT}/readyz"
echo "============================================================"
echo ""

# 7. Monitor processes concurrently
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 1
done

if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
  wait "$BACKEND_PID" || EXIT_CODE=$?
  echo "Backend process terminated with code ${EXIT_CODE:-0}"
  exit "${EXIT_CODE:-1}"
fi

if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
  wait "$FRONTEND_PID" || EXIT_CODE=$?
  echo "Frontend process terminated with code ${EXIT_CODE:-0}"
  exit "${EXIT_CODE:-1}"
fi
