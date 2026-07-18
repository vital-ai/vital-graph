#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# run-perf-tests.sh — integration + performance suites in the ephemeral
# vg-test Docker stack (clean, PG-18, torn down after).
#
# The pytest analog of e2e/run-tests.sh: spins up the vg-test stack (own
# PostgreSQL on :5433, sidecar on :7071), points the suites at the container
# DB, runs `pytest -m "integration or performance"`, and tears down. This is
# the standard L1/L2 validation cycle for the scaling work — every run tests
# the *built* code against a clean, version-pinned DB, so plan-shape / buffer
# assertions are reproducible.
#
# Usage:
#   ./scripts/run-perf-tests.sh                       # up --build → test → down
#   ./scripts/run-perf-tests.sh --no-down             # leave stack up for debugging
#   ./scripts/run-perf-tests.sh --skip-build          # faster reruns
#   ./scripts/run-perf-tests.sh -- -k growth -s       # pass args through to pytest
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.test.yml"
PYTHON="${PYTHON:-/opt/homebrew/anaconda3/envs/vital-graph/bin/python}"
MAX_WAIT=90

# Point the suites at the vg-test container services (see docker-compose.test.yml).
export VG_TEST_PG_HOST=localhost
export VG_TEST_PG_PORT=5433
export VG_TEST_PG_DATABASE=sparql_sql_graph
export VG_TEST_PG_USER=postgres
export VG_TEST_PG_PASSWORD=testpass
export VG_TEST_SIDECAR_URL=http://localhost:7071

TEAR_DOWN=true
BUILD_FLAG="--build"
PYTEST_ARGS=()
PASSTHROUGH=false
for arg in "$@"; do
  if $PASSTHROUGH; then PYTEST_ARGS+=("$arg"); continue; fi
  case "$arg" in
    --no-down)    TEAR_DOWN=false ;;
    --skip-build) BUILD_FLAG="" ;;
    --)           PASSTHROUGH=true ;;
    *)            PYTEST_ARGS+=("$arg") ;;
  esac
done

cleanup() {
  if $TEAR_DOWN; then
    echo "🧹 Tearing down test stack..."
    docker compose -f "$COMPOSE_FILE" down --remove-orphans 2>/dev/null || true
  else
    echo "ℹ️  Stack left running (--no-down): docker compose -f docker-compose.test.yml down"
  fi
}
trap cleanup EXIT

echo "🐳 Starting vg-test stack (PostgreSQL 18, sidecar)..."
docker compose -f "$COMPOSE_FILE" up -d $BUILD_FLAG postgres sparql-compiler

echo "⏳ Waiting for PostgreSQL on :$VG_TEST_PG_PORT ..."
elapsed=0
until docker exec vitalgraph-test-pg pg_isready -U postgres >/dev/null 2>&1; do
  [ "$elapsed" -ge "$MAX_WAIT" ] && { echo "❌ PostgreSQL not ready in ${MAX_WAIT}s"; docker compose -f "$COMPOSE_FILE" logs postgres | tail -20; exit 1; }
  sleep 2; elapsed=$((elapsed + 2))
done
echo "✅ PostgreSQL ready (${elapsed}s)"

echo "⏳ Waiting for sidecar on :7071 ..."
elapsed=0
until curl -sf -X POST "$VG_TEST_SIDECAR_URL/v1/sparql/compile" \
      -H 'Content-Type: application/json' \
      -d '{"sparql":"SELECT ?s WHERE { ?s ?p ?o } LIMIT 1"}' >/dev/null 2>&1; do
  [ "$elapsed" -ge "$MAX_WAIT" ] && { echo "❌ sidecar not ready in ${MAX_WAIT}s"; exit 1; }
  sleep 2; elapsed=$((elapsed + 2))
done
echo "✅ sidecar ready (${elapsed}s)"

echo "🧪 Running integration + performance suites against the container DB..."
cd "$PROJECT_ROOT"
"$PYTHON" -m pytest -m "integration or performance" -p no:cacheprovider "${PYTEST_ARGS[@]}"

echo "✅ Perf/integration suites passed"
