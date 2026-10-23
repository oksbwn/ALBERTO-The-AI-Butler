#!/usr/bin/env bash
# Alberto Test & Lint Runner
set -eo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

RUN_LINT=true
RUN_BACKEND=true
RUN_FRONTEND=true
RUN_E2E=false
E2E_FLAGS=""

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --lint|--lint-only)
      RUN_BACKEND=false
      RUN_FRONTEND=false
      RUN_E2E=false
      shift
      ;;
    --backend|--backend-only)
      RUN_LINT=false
      RUN_FRONTEND=false
      RUN_E2E=false
      shift
      ;;
    --frontend|--frontend-only)
      RUN_LINT=false
      RUN_BACKEND=false
      RUN_E2E=false
      shift
      ;;
    --e2e|--e2e-only)
      RUN_LINT=false
      RUN_BACKEND=false
      RUN_FRONTEND=false
      RUN_E2E=true
      E2E_FLAGS="--project=e2e"
      shift
      ;;
    --e2e-headed)
      RUN_LINT=false
      RUN_BACKEND=false
      RUN_FRONTEND=false
      RUN_E2E=true
      E2E_FLAGS="--project=e2e --headed"
      shift
      ;;
    --e2e-live)
      RUN_LINT=false
      RUN_BACKEND=false
      RUN_FRONTEND=false
      RUN_E2E=true
      E2E_FLAGS="--project=live"
      shift
      ;;
    --e2e-docker)
      RUN_LINT=false
      RUN_BACKEND=false
      RUN_FRONTEND=false
      RUN_E2E=true
      E2E_FLAGS="--project=docker"
      shift
      ;;
    --e2e-report)
      (cd "$ROOT_DIR/frontend" && npx playwright show-report ../playwright-report)
      exit 0
      ;;
    --all)
      RUN_LINT=true
      RUN_BACKEND=true
      RUN_FRONTEND=true
      RUN_E2E=true
      E2E_FLAGS="--project=e2e"
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
      echo "  --e2e, --e2e-only          Run Playwright E2E suite"
      echo "  --e2e-headed               Run Playwright E2E suite with visible browser"
      echo "  --e2e-live                 Run live LLM integration tests"
      echo "  --e2e-docker               Run Docker acceptance tests"
      echo "  --e2e-report               Open HTML test report"
      echo "  --all                      Run all linters, backend, frontend, and E2E tests"
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
  echo "--> [3/4] Running Frontend Tests (Vitest)..."
  (cd "$ROOT_DIR/frontend" && npm test)
  echo "    ✓ Frontend tests passed!"
fi

# 4. Playwright E2E Tests
if [[ "$RUN_E2E" == true ]]; then
  echo ""
  echo "--> [4/4] Running Playwright E2E Tests..."
  (cd "$ROOT_DIR/frontend" && npx playwright test --config="../tests/e2e/playwright.config.ts" $E2E_FLAGS)
  echo "    ✓ Playwright E2E tests passed!"
fi

echo ""
echo "=========================================="
echo " ✓ ALL CHECKS PASSED SUCCESSFULLY"
echo "=========================================="
