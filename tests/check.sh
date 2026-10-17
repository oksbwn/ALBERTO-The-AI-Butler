#!/usr/bin/env bash
# Alberto Quality Gate: Complete Pre-Release Validation
# Executes sequentially: lint -> tests -> frontend build
set -eo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$TESTS_DIR/.." && pwd)"

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
echo " Alberto Quality Gate: check.sh"
echo "=========================================="

echo ""
echo "[Step 1/3] Executing Linting Gate..."
if ! "$TESTS_DIR/lint.sh"; then
  echo ""
  echo "❌ FAILED: Linting gate failed in tests/lint.sh" >&2
  exit 1
fi

echo ""
echo "[Step 2/3] Executing Test Suites..."
if ! "$TESTS_DIR/run.sh"; then
  echo ""
  echo "❌ FAILED: Test suite failed in tests/run.sh" >&2
  exit 1
fi

echo ""
echo "[Step 3/3] Executing Frontend Production Build..."
if ! (cd "$ROOT_DIR/frontend" && "$NPM" run build); then
  echo ""
  echo "❌ FAILED: Frontend production build failed" >&2
  exit 1
fi

echo ""
echo "=========================================="
echo " ✓ QUALITY GATE PASSED: ALL CHECKS GREEN"
echo "=========================================="
