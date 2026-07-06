#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# run-tests.sh — One-shot E2E test runner
#
# Starts the test Docker stack, waits for health, seeds data,
# runs Playwright tests, and tears down the stack.
#
# Usage:
#   ./e2e/run-tests.sh                              # full cycle (up → test → down)
#   ./e2e/run-tests.sh --no-down                    # leave stack running for debugging
#   ./e2e/run-tests.sh --skip-build                 # skip docker build (faster reruns)
#   ./e2e/run-tests.sh --no-down -- tests/foo.spec.ts  # run specific test file(s)
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.test.yml"
BASE_URL="${VG_TEST_URL:-http://localhost:8002}"
MAX_WAIT=60

# Parse flags
TEAR_DOWN=true
BUILD_FLAG="--build"
PLAYWRIGHT_ARGS=()
PASSTHROUGH=false
for arg in "$@"; do
  if $PASSTHROUGH; then
    PLAYWRIGHT_ARGS+=("$arg")
    continue
  fi
  case "$arg" in
    --no-down)    TEAR_DOWN=false ;;
    --skip-build) BUILD_FLAG="" ;;
    --)           PASSTHROUGH=true ;;
    *)            PLAYWRIGHT_ARGS+=("$arg") ;;
  esac
done

cleanup() {
  if $TEAR_DOWN; then
    echo "🧹 Tearing down test stack..."
    docker compose -f "$COMPOSE_FILE" down --remove-orphans 2>/dev/null || true
  else
    echo "ℹ️  Stack left running (--no-down). Tear down manually:"
    echo "   docker compose -f docker-compose.test.yml down"
  fi
}
trap cleanup EXIT

# ── 1. Start test stack ──────────────────────────────────────────────
echo "🐳 Starting test stack..."
docker compose -f "$COMPOSE_FILE" up -d $BUILD_FLAG

# ── 2. Wait for VitalGraph health ────────────────────────────────────
echo "⏳ Waiting for VitalGraph at $BASE_URL/health ..."
elapsed=0
until curl -sf "$BASE_URL/health" > /dev/null 2>&1; do
  if [ "$elapsed" -ge "$MAX_WAIT" ]; then
    echo "❌ Server did not become healthy within ${MAX_WAIT}s"
    docker compose -f "$COMPOSE_FILE" logs vitalgraph | tail -30
    exit 1
  fi
  sleep 2
  elapsed=$((elapsed + 2))
done
echo "✅ Server healthy (${elapsed}s)"

# ── 3. Seed test data ───────────────────────────────────────────────
echo "🌱 Seeding test data..."
cd "$PROJECT_ROOT"
${PYTHON:-/opt/homebrew/anaconda3/envs/vital-graph/bin/python} -m tests.shared.seed_ui_test_data --server-url "$BASE_URL"

# ── 4. Run Playwright tests ─────────────────────────────────────────
echo "🎭 Running Playwright tests..."
cd "$SCRIPT_DIR"
npx playwright test --reporter=list "${PLAYWRIGHT_ARGS[@]}"

echo "✅ All tests passed"
