#!/usr/bin/env bash
# ==============================================================================
# Alberto Launcher Script (Linux & macOS)
# Starts FastAPI backend and Next.js frontend concurrently.
# ==============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Starting Alberto AI Home Butler ==="
echo "Repository root: ${REPO_ROOT}"

# ------------------------------------------------------------------------------
# 1. Validate Python
# ------------------------------------------------------------------------------
PYTHON_BIN=""
if [ -f "${REPO_ROOT}/backend/.venv/bin/python" ]; then
  PYTHON_BIN="${REPO_ROOT}/backend/.venv/bin/python"
elif [ -f "${REPO_ROOT}/backend/.venv/Scripts/python.exe" ]; then
  PYTHON_BIN="${REPO_ROOT}/backend/.venv/Scripts/python.exe"
elif [ -f "${REPO_ROOT}/backend/.venv/Scripts/python" ]; then
  PYTHON_BIN="${REPO_ROOT}/backend/.venv/Scripts/python"
elif [ -f "${REPO_ROOT}/.venv/bin/python" ]; then
  PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
elif [ -f "${REPO_ROOT}/.venv/Scripts/python.exe" ]; then
  PYTHON_BIN="${REPO_ROOT}/.venv/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
else
  echo "Error: Python 3 not found. Python >= 3.11 is required." >&2
  exit 1
fi

PY_VER="$("${PYTHON_BIN}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_MAJOR="$("${PYTHON_BIN}" -c 'import sys; print(sys.version_info.major)')"
PY_MINOR="$("${PYTHON_BIN}" -c 'import sys; print(sys.version_info.minor)')"

if [ "${PY_MAJOR}" -lt 3 ] || { [ "${PY_MAJOR}" -eq 3 ] && [ "${PY_MINOR}" -lt 11 ]; }; then
  echo "Error: Python >= 3.11 required (found Python ${PY_VER})." >&2
  exit 1
fi

# Verify core backend dependencies are present without auto-installing
if ! "${PYTHON_BIN}" -c "import fastapi, uvicorn, aiosqlite" >/dev/null 2>&1; then
  echo "Error: Backend dependencies missing (fastapi, uvicorn, aiosqlite) in ${PYTHON_BIN}." >&2
  echo "Install dependencies first:" >&2
  echo "  cd ${REPO_ROOT}/backend" >&2
  echo "  python -m venv .venv && source .venv/bin/activate" >&2
  echo "  pip install -e \".[dev]\"" >&2
  exit 1
fi

# ------------------------------------------------------------------------------
# 2. Validate Node.js & Frontend Package Manager
# ------------------------------------------------------------------------------
if ! command -v node >/dev/null 2>&1; then
  echo "Error: Node.js is required but not installed." >&2
  exit 1
fi

NODE_VER="$(node -v | sed 's/^v//')"
NODE_MAJOR="$(echo "${NODE_VER}" | cut -d. -f1)"
if [ "${NODE_MAJOR}" -lt 18 ]; then
  echo "Error: Node.js >= 18 required (found v${NODE_VER})." >&2
  exit 1
fi

PKG_RUNNER=""
if command -v pnpm >/dev/null 2>&1; then
  PKG_RUNNER="pnpm"
elif command -v npm >/dev/null 2>&1; then
  PKG_RUNNER="npm"
elif command -v yarn >/dev/null 2>&1; then
  PKG_RUNNER="yarn"
else
  echo "Error: No package manager found (pnpm or npm required)." >&2
  exit 1
fi

if [ ! -d "${REPO_ROOT}/frontend/node_modules" ]; then
  echo "Warning: ${REPO_ROOT}/frontend/node_modules not found." >&2
  echo "Install frontend dependencies first:" >&2
  echo "  cd ${REPO_ROOT}/frontend && ${PKG_RUNNER} install" >&2
  exit 1
fi

# ------------------------------------------------------------------------------
# 3. Load Environment Configuration
# ------------------------------------------------------------------------------
if [ -f "${REPO_ROOT}/.env" ]; then
  # Safely export environment variables while ignoring comments and blank lines
  set -a
  # shellcheck disable=SC1090
  source "${REPO_ROOT}/.env"
  set +a
fi

# Configure persistent data root
DATA_DIR="${ALBERTO_DATA_DIR:-${FORGE_DATA_DIR:-${REPO_ROOT}/data}}"
mkdir -p "${DATA_DIR}/db" "${DATA_DIR}/chroma" "${DATA_DIR}/memory" "${DATA_DIR}/logs" "${DATA_DIR}/config"
export ALBERTO_DATA_DIR="${DATA_DIR}"

BACKEND_PORT="${PORT:-${ALBERTO_PORT:-${FORGE_PORT:-8000}}}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

# ------------------------------------------------------------------------------
# 4. Process Management & Clean Termination
# ------------------------------------------------------------------------------
BACKEND_PID=""
FRONTEND_PID=""
CLEANED_UP=0

cleanup() {
  if [ "${CLEANED_UP}" -eq 1 ]; then
    return
  fi
  CLEANED_UP=1
  echo ""
  echo "Shutting down Alberto processes..."

  # Cross-platform cleanup for all child workers, ports, and database locks
  if [ -n "${PYTHON_BIN}" ] && [ -f "${REPO_ROOT}/backend/alberto/util/process_cleanup.py" ]; then
    "${PYTHON_BIN}" "${REPO_ROOT}/backend/alberto/util/process_cleanup.py" \
      --ports "${BACKEND_PORT}" "${FRONTEND_PORT}" \
      --lock-files "${REPO_ROOT}/data/db/ladybug/.owner.lock" 2>/dev/null || true
  fi

  if [ -n "${FRONTEND_PID}" ] && kill -0 "${FRONTEND_PID}" 2>/dev/null; then
    kill -9 "${FRONTEND_PID}" 2>/dev/null || true
  fi
  if [ -n "${BACKEND_PID}" ] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
    kill -9 "${BACKEND_PID}" 2>/dev/null || true
  fi

  echo "Alberto shutdown complete."
}

trap cleanup INT TERM EXIT

# ------------------------------------------------------------------------------
# 5. Start Backend
# ------------------------------------------------------------------------------
# Free any stale process, port conflict, or database lock (cross-platform: Linux, macOS, Windows)
if [ -n "${PYTHON_BIN}" ] && [ -f "${REPO_ROOT}/backend/alberto/util/process_cleanup.py" ]; then
  "${PYTHON_BIN}" "${REPO_ROOT}/backend/alberto/util/process_cleanup.py" \
    --ports "${BACKEND_PORT}" \
    --lock-files "${REPO_ROOT}/data/db/ladybug/.owner.lock" 2>/dev/null || true
fi

echo "Starting FastAPI backend on port ${BACKEND_PORT}..."
export PYTHONPATH="${REPO_ROOT}/backend${PYTHONPATH:+:${PYTHONPATH}}"
"${PYTHON_BIN}" -m uvicorn alberto.main:app --host 0.0.0.0 --port "${BACKEND_PORT}" --reload --reload-dir "${REPO_ROOT}/backend/alberto" &
BACKEND_PID=$!

sleep 1
if ! kill -0 "${BACKEND_PID}" 2>/dev/null; then
  echo "Error: Backend failed to start." >&2
  exit 1
fi

# ------------------------------------------------------------------------------
# 6. Start Frontend
# ------------------------------------------------------------------------------
if [ -n "${PYTHON_BIN}" ] && [ -f "${REPO_ROOT}/backend/alberto/util/process_cleanup.py" ]; then
  "${PYTHON_BIN}" "${REPO_ROOT}/backend/alberto/util/process_cleanup.py" \
    --ports "${FRONTEND_PORT}" 2>/dev/null || true
fi

echo "Starting Next.js frontend on port ${FRONTEND_PORT}..."
(
  cd "${REPO_ROOT}/frontend"
  if [ "${FRONTEND_PORT}" = "3000" ]; then
    "${PKG_RUNNER}" run dev
  else
    "${PKG_RUNNER}" run dev -- -p "${FRONTEND_PORT}"
  fi
) &
FRONTEND_PID=$!

sleep 1
if ! kill -0 "${FRONTEND_PID}" 2>/dev/null; then
  echo "Error: Frontend failed to start." >&2
  exit 1
fi

echo ""
echo "============================================================"
echo "  Alberto AI Home Butler is running!"
echo "  Backend API:  http://localhost:${BACKEND_PORT}"
echo "  API Docs:     http://localhost:${BACKEND_PORT}/docs"
echo "  Frontend UI:  http://localhost:${FRONTEND_PORT}"
echo "============================================================"
echo "Press Ctrl+C to terminate both services."
echo ""

# ------------------------------------------------------------------------------
# 7. Monitor Processes Concurrently
# ------------------------------------------------------------------------------
while kill -0 "${BACKEND_PID}" 2>/dev/null && kill -0 "${FRONTEND_PID}" 2>/dev/null; do
  sleep 1
done

# If one died, capture failure exit code and trigger cleanup
if ! kill -0 "${BACKEND_PID}" 2>/dev/null; then
  wait "${BACKEND_PID}" || EXIT_CODE=$?
  echo "Backend process exited with code ${EXIT_CODE:-0}"
  exit "${EXIT_CODE:-1}"
fi

if ! kill -0 "${FRONTEND_PID}" 2>/dev/null; then
  wait "${FRONTEND_PID}" || EXIT_CODE=$?
  echo "Frontend process exited with code ${EXIT_CODE:-0}"
  exit "${EXIT_CODE:-1}"
fi
