#!/usr/bin/env bash
# Alberto Quality Gate: Test Suite Runner (Backend Pytest + Frontend Vitest)
set -eo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$TESTS_DIR/.." && pwd)"

# Discover Python
if [[ -n "$VIRTUAL_ENV" && -f "$VIRTUAL_ENV/bin/python" ]]; then
  PYTHON="$VIRTUAL_ENV/bin/python"
elif [[ -n "$VIRTUAL_ENV" && -f "$VIRTUAL_ENV/Scripts/python.exe" ]]; then
  PYTHON="$VIRTUAL_ENV/Scripts/python.exe"
elif [[ -f "$ROOT_DIR/backend/.venv/bin/python" ]]; then
  PYTHON="$ROOT_DIR/backend/.venv/bin/python"
elif [[ -f "$ROOT_DIR/backend/.venv/Scripts/python.exe" ]]; then
  PYTHON="$ROOT_DIR/backend/.venv/Scripts/python.exe"
elif [[ -f "$ROOT_DIR/backend/.venv/Scripts/python" ]]; then
  PYTHON="$ROOT_DIR/backend/.venv/Scripts/python"
elif [[ -f "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON="$ROOT_DIR/.venv/bin/python"
elif [[ -f "$ROOT_DIR/.venv/Scripts/python.exe" ]]; then
  PYTHON="$ROOT_DIR/.venv/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON="python"
else
  echo "Error: Python interpreter not found." >&2
  exit 1
fi

# Discover frontend runner (npm / pnpm)
if command -v npm >/dev/null 2>&1; then
  NPM="npm"
elif command -v npm.cmd >/dev/null 2>&1; then
  NPM="npm.cmd"
else
  echo "Error: npm not found." >&2
  exit 1
fi

echo "=========================================="
echo " Alberto Test Suites"
echo "=========================================="

echo "--> [1/2] Running Backend Tests (pytest)..."
"$PYTHON" -m pytest "$ROOT_DIR/tests/backend" --quiet || {
  echo "Error: Backend tests failed!" >&2
  exit 1
}
echo "    ✓ Backend tests passed!"

echo "--> [2/2] Running Frontend Tests (Vitest)..."
(
  cd "$ROOT_DIR/frontend"
  "$NPM" test
) || {
  echo "Error: Frontend tests failed!" >&2
  exit 1
}
echo "    ✓ Frontend tests passed!"

if [[ "${1:-}" == "--e2e" || "${1:-}" == "--all" ]]; then
  echo ""
  echo "--> [3/3] Running Playwright E2E Tests..."
  (
    cd "$ROOT_DIR/frontend"
    npx playwright test --config="../tests/e2e/playwright.config.ts" --project=e2e
  ) || {
    echo "Error: Playwright E2E tests failed!" >&2
    exit 1
  }
  echo "    ✓ Playwright E2E tests passed!"
fi

echo "=========================================="
echo " ✓ ALL TEST SUITES PASSED"
echo "=========================================="
