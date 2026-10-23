#!/usr/bin/env bash
# Alberto Isolated Docker E2E Acceptance Test Runner
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.test.yml"
TEST_URL="http://127.0.0.1:8001"

echo "=== Alberto Docker Acceptance Suite ==="
echo "Starting isolated test container on port 8001..."

docker compose -f "$COMPOSE_FILE" up -d --build

cleanup() {
  echo ""
  echo "Tearing down acceptance container..."
  docker compose -f "$COMPOSE_FILE" down
  echo "Container teardown complete."
}
trap cleanup EXIT INT TERM

echo "Waiting for container health check at $TEST_URL/health..."
RETRIES=30
READY=false
for i in $(seq 1 $RETRIES); do
  if curl -sf "$TEST_URL/health" >/dev/null 2>&1; then
    READY=true
    break
  fi
  sleep 2
done

if [ "$READY" != "true" ]; then
  echo "Error: Docker test container failed to become healthy within 60s." >&2
  docker compose -f "$COMPOSE_FILE" logs
  exit 1
fi

echo "✓ Container is healthy. Running Playwright Docker acceptance tests..."
DOCKER_TEST_URL="$TEST_URL" npx --prefix "$ROOT_DIR/frontend" playwright test --config="$ROOT_DIR/tests/e2e/playwright.config.ts" --project=docker
echo "✓ Docker acceptance tests passed successfully!"
