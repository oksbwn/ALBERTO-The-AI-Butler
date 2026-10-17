#!/usr/bin/env bash
# Alberto Quality Gate: Linting & Static Analysis
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

# Discover npx / npm
if command -v npx >/dev/null 2>&1; then
  NPX="npx"
elif command -v npx.cmd >/dev/null 2>&1; then
  NPX="npx.cmd"
else
  echo "Error: npx not found." >&2
  exit 1
fi

echo "=========================================="
echo " Alberto Linting & Static Analysis"
echo "=========================================="

echo "--> [1/2] Checking Backend (Ruff)..."
"$PYTHON" -m ruff check "$ROOT_DIR/backend"
echo "    ✓ Backend Ruff checks passed!"

echo "--> [2/2] Checking Frontend (TypeScript)..."
(
  cd "$ROOT_DIR/frontend"
  "$NPX" tsc --noEmit
)
echo "    ✓ Frontend TypeScript checks passed!"

# If ESLint is explicitly configured, run it
if [[ -f "$ROOT_DIR/frontend/.eslintrc" || -f "$ROOT_DIR/frontend/.eslintrc.json" || -f "$ROOT_DIR/frontend/.eslintrc.js" ]]; then
  echo "--> Checking Frontend (ESLint)..."
  (
    cd "$ROOT_DIR/frontend"
    "$NPX" next lint
  )
  echo "    ✓ Frontend ESLint checks passed!"
fi

echo "=========================================="
echo " ✓ ALL LINT CHECKS PASSED"
echo "=========================================="
