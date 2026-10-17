#!/usr/bin/env bash
# Alberto Test & Lint Runner
set -eo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

RUN_LINT=true
RUN_BACKEND=true
RUN_FRONTEND=true

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --lint|--lint-only)
      RUN_BACKEND=false
      RUN_FRONTEND=false
      shift
      ;;
    --backend|--backend-only)
      RUN_LINT=false
      RUN_FRONTEND=false
      shift
      ;;
    --frontend|--frontend-only)
      RUN_LINT=false
      RUN_BACKEND=false
      shift
      ;;
    --no-lint)
      RUN_LINT=false
      shift
      ;;
    --help|-h)
      echo "Alberto Test & Lint Runner"
      echo "Usage: ./test.sh [options]"
      echo ""
      echo "Options:"
      echo "  --lint, --lint-only        Run only linters (Ruff + TypeScript)"
      echo "  --backend, --backend-only  Run only backend tests (Pytest)"
      echo "  --frontend, --frontend-only Run only frontend tests (Vitest)"
      echo "  --no-lint                  Skip linting and run only tests"
      echo "  --help, -h                 Show this help message"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

# Resolve Python interpreter
if [[ -f "$ROOT_DIR/backend/.venv/bin/python" ]]; then
  PYTHON="$ROOT_DIR/backend/.venv/bin/python"
elif [[ -f "$ROOT_DIR/backend/.venv/Scripts/python.exe" ]]; then
  PYTHON="$ROOT_DIR/backend/.venv/Scripts/python.exe"
elif [[ -f "$ROOT_DIR/backend/.venv/Scripts/python" ]]; then
  PYTHON="$ROOT_DIR/backend/.venv/Scripts/python"
else
  PYTHON="python"
fi

echo "=========================================="
echo " Alberto Test & Quality Suite"
echo "=========================================="

# 1. Linting
if [[ "$RUN_LINT" == true ]]; then
  echo ""
  echo "--> [1/3] Running Linters..."
  
  echo "    Checking Backend (Ruff)..."
  "$PYTHON" -m ruff check backend/

  echo "    Checking Frontend (TypeScript tsc)..."
  (cd "$ROOT_DIR/frontend" && npx tsc --noEmit)

  echo "    ✓ All linters passed!"
fi

# 2. Backend Tests
if [[ "$RUN_BACKEND" == true ]]; then
  echo ""
  echo "--> [2/3] Running Backend Tests (pytest)..."
  "$PYTHON" -m pytest tests/backend/ --quiet || {
    echo "    Backend pytest failed!"
    exit 1
  }
  echo "    ✓ Backend tests passed!"
fi

# 3. Frontend Tests
if [[ "$RUN_FRONTEND" == true ]]; then
  echo ""
  echo "--> [3/3] Running Frontend Tests (Vitest)..."
  (cd "$ROOT_DIR/frontend" && npm test)
  echo "    ✓ Frontend tests passed!"
fi

echo ""
echo "=========================================="
echo " ✓ ALL CHECKS PASSED SUCCESSFULLY"
echo "=========================================="
