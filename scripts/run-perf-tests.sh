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
#   ./scripts/run-perf-tests.sh --persist             # reuse PG data volume across runs
#   ./scripts/run-perf-tests.sh --reset-data          # wipe persisted volume, start clean
#   ./scripts/run-perf-tests.sh -- -k growth -s       # pass args through to pytest
#
# Regression tracking (see tests/performance/README.md):
#   ./scripts/run-perf-tests.sh --record              # record a run JSON + history entry
#   ./scripts/run-perf-tests.sh --baseline main       # record, then compare vs a baseline
#   ./scripts/run-perf-tests.sh --promote main        # record, then make it the baseline
#   ./scripts/run-perf-tests.sh --api-benches         # + REST latency benches (app up first)
# A regression vs the baseline fails the run even when every assertion passed —
# the inline bounds are absolute floors, the baseline is the drift detector.
#
# --persist layers docker-compose.test.persist.yml (named volume 'vgtest_pgdata')
# so a large loaded dataset (e.g. a prod pg_restore) survives down/up cycles.
# Combine with --skip-build for fast rerun loops; --reset-data clears it.
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

PERSIST_FILE="$PROJECT_ROOT/docker-compose.test.persist.yml"
TEAR_DOWN=true
BUILD_FLAG="--build"
PERSIST=false          # --persist: keep the PG data volume across runs
RESET_DATA=false       # --reset-data: wipe the persisted volume before starting
SEED_DATA=false        # --seed-data: load the realistic benchmark datasets
API_BENCHES=false      # --api-benches: also run the REST latency benches
RECORD=false           # --record: capture a structured run file
RECORD_PATH=""
BASELINE=""            # --baseline NAME: compare the recorded run against it
PROMOTE=""             # --promote NAME: make the recorded run the new baseline
PYTEST_ARGS=()
PASSTHROUGH=false
NEXT=""
for arg in "$@"; do
  if $PASSTHROUGH; then PYTEST_ARGS+=("$arg"); continue; fi
  if [ -n "$NEXT" ]; then
    case "$NEXT" in
      baseline) BASELINE="$arg" ;;
      promote)  PROMOTE="$arg" ;;
      record)   RECORD_PATH="$arg" ;;
    esac
    NEXT=""; continue
  fi
  case "$arg" in
    --no-down)    TEAR_DOWN=false ;;
    --skip-build) BUILD_FLAG="" ;;
    --persist)    PERSIST=true ;;
    --reset-data) PERSIST=true; RESET_DATA=true ;;
    --seed-data)   SEED_DATA=true; PERSIST=true ;;
    --api-benches) API_BENCHES=true; SEED_DATA=true; PERSIST=true ;;
    --record)     RECORD=true ;;
    --record=*)   RECORD=true; RECORD_PATH="${arg#*=}" ;;
    --baseline)   RECORD=true; NEXT=baseline ;;
    --baseline=*) RECORD=true; BASELINE="${arg#*=}" ;;
    --promote)    RECORD=true; NEXT=promote ;;
    --promote=*)  RECORD=true; PROMOTE="${arg#*=}" ;;
    --)           PASSTHROUGH=true ;;
    *)            PYTEST_ARGS+=("$arg") ;;
  esac
done

# Result recording (performance_regression_tracking_plan.md). The suite is inert
# unless VG_PERF_RECORD names an output path.
if $RECORD; then
  RESULTS_DIR="$PROJECT_ROOT/tests/performance/results"
  mkdir -p "$RESULTS_DIR"
  if [ -z "$RECORD_PATH" ]; then
    STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
    COMMIT="$(git -C "$PROJECT_ROOT" rev-parse --short HEAD 2>/dev/null || echo nogit)"
    RECORD_PATH="$RESULTS_DIR/run-${STAMP}-${COMMIT}.json"
  fi
  export VG_PERF_RECORD="$RECORD_PATH"
  echo "📊 Recording results → $VG_PERF_RECORD"
fi

# Compose file set — layer the persist override when --persist/--reset-data.
# With a named volume the DB survives `down` (only `down -v` removes it), so a
# large loaded dataset (e.g. a prod dump) is reused across a series of runs.
COMPOSE_FILES=(-f "$COMPOSE_FILE")
if $PERSIST; then COMPOSE_FILES+=(-f "$PERSIST_FILE"); fi
if $SEED_DATA; then COMPOSE_FILES+=(-f "$PROJECT_ROOT/docker-compose.test.data.yml"); fi

cleanup() {
  if $TEAR_DOWN; then
    # Note: plain `down` (no -v) preserves the named volume under --persist.
    echo "🧹 Tearing down test stack (data volume preserved if --persist)..."
    docker compose "${COMPOSE_FILES[@]}" down --remove-orphans 2>/dev/null || true
  else
    echo "ℹ️  Stack left running (--no-down): docker compose ${COMPOSE_FILES[*]} down"
  fi
}
trap cleanup EXIT

if $RESET_DATA; then
  echo "🗑️  --reset-data: removing persisted PG volume for a clean slate..."
  docker compose "${COMPOSE_FILES[@]}" down -v --remove-orphans 2>/dev/null || true
fi
if $PERSIST; then
  echo "💾 Persistence ON — PG data volume 'vgtest_pgdata' is reused across runs."
fi

# Recorded in the run's env stamp: a clean container DB and a persisted volume
# full of loaded spaces are different measurement environments (see
# perf_record.runner_stamp), and must not be compared to each other.
export VG_PERF_PERSIST="$PERSIST"
export VG_PERF_SEEDED="$SEED_DATA"

echo "🐳 Starting vg-test stack (PostgreSQL 18, sidecar)..."
docker compose "${COMPOSE_FILES[@]}" up -d $BUILD_FLAG postgres sparql-compiler

# Wait for the *target database*, not just pg_isready. The entrypoint reports
# ready once during init, before the init scripts have created
# $VG_TEST_PG_DATABASE — starting pytest in that window makes the perf
# conftest's connectivity probe fail and silently skip the whole suite.
echo "⏳ Waiting for PostgreSQL database '$VG_TEST_PG_DATABASE' on :$VG_TEST_PG_PORT ..."
elapsed=0
until docker exec vitalgraph-test-pg psql -U postgres -d "$VG_TEST_PG_DATABASE" \
        -c 'SELECT 1' >/dev/null 2>&1; do
  [ "$elapsed" -ge "$MAX_WAIT" ] && { echo "❌ PostgreSQL not ready in ${MAX_WAIT}s"; docker compose "${COMPOSE_FILES[@]}" logs postgres | tail -20; exit 1; }
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

# The admin/registry tables (install, space, graph, user, ...) are normally
# created by the app service's VG_AUTO_INIT — which we do not start here. Without
# them every test that creates a real space fails on `relation "space" does not
# exist`, so initialize the schema explicitly.
echo "🗄️  Initializing admin schema in the container DB..."
cd "$PROJECT_ROOT"
"$PYTHON" "$PROJECT_ROOT/scripts/perf_init_db.py"

# Realistic datasets (wordnet_frames). Idempotent — a space that already holds
# quads is left alone, so this is a no-op on every run after the first. Implies
# --persist: a multi-GB load must survive down/up or it is not worth doing.
if $SEED_DATA; then
  # The load runs entirely inside the stack: the datasets are bind-mounted into
  # the containers, the loader runs in the app container (which already has the
  # vitalgraph package), and it writes to the stack's own PostgreSQL over the
  # compose network (postgres:5432). Nothing streams from the host, and no host
  # Python environment is involved.
  echo "📚 Seeding benchmark datasets in the stack (idempotent)..."
  docker compose "${COMPOSE_FILES[@]}" up -d $BUILD_FLAG vitalgraph
  SEED_CMD=(docker compose "${COMPOSE_FILES[@]}" exec -T
            -e VG_TEST_PG_HOST=postgres -e VG_TEST_PG_PORT=5432
            -e VG_TEST_PG_DATABASE="$VG_TEST_PG_DATABASE"
            -e VG_TEST_PG_USER="$VG_TEST_PG_USER"
            -e VG_TEST_PG_PASSWORD="$VG_TEST_PG_PASSWORD"
            -e VG_TEST_SIDECAR_URL=http://sparql-compiler:7070
            vitalgraph python /app/scripts/perf_seed_data.py)
  for ds in wordnet lead; do
    # A dataset whose source files are absent on this machine reports and is
    # skipped (exit 2) — that is a coverage hole to see, not a run to abort.
    "${SEED_CMD[@]}" --dataset "$ds" || {
      rc=$?
      [ "$rc" -eq 2 ] || { echo "❌ seeding '$ds' failed (exit $rc)"; exit "$rc"; }
    }
  done

  # STOP the app before measuring. Its background workers do not idle:
  # `backfill_server_properties_task` continuously patches every space it finds
  # (measured: ~3,600 quads/minute appended to wordnet_frames while the app sat
  # otherwise idle, and it never reaches a terminal state). That both adds write
  # load during the benchmark and silently mutates the benchmark dataset between
  # runs, which makes buffer counts drift and baseline comparisons meaningless.
  # The app is only needed to run the loader; nothing in the perf suite talks to
  # it.
  # API benches (kind="api") need the app; the plan-counter benches want it
  # stopped so background workers cannot mutate the data mid-measurement. Run
  # them in that order — API first while the app is up, then stop it — so one
  # invocation covers both without the two interfering.
  if $API_BENCHES; then
    echo "🌐 Running API benches (app up)..."
    API_RECORD=""
    if $RECORD; then
      API_RECORD="${RECORD_PATH%.json}-api.json"
      export VG_PERF_RECORD="$API_RECORD"
    fi
    "$PYTHON" -m pytest tests/performance -m performance -p no:cacheprovider \
      -k "bench" -q || echo "⚠️  API benches reported failures (continuing)"
    if $RECORD; then export VG_PERF_RECORD="$RECORD_PATH"; fi
  fi

  echo "🛑 Stopping the app container so background workers don't mutate the data..."
  docker compose "${COMPOSE_FILES[@]}" stop vitalgraph >/dev/null 2>&1 || true
fi

echo "🧪 Running integration + performance suites against the container DB..."
# Scope collection to the suites we actually run. pyproject sets
# `testpaths = tests`, so the default selection imports EVERY test module in the
# repo — and pytest treats a collection error as fatal for the whole session. An
# unrelated missing dependency in tests/unit (e.g. bs4) therefore aborts the perf
# run before a single benchmark executes. Naming the paths keeps an unrelated
# breakage from silently costing us the measurement.
TARGET_PATHS=()
for a in "${PYTEST_ARGS[@]}"; do
  if [ -e "$a" ]; then TARGET_PATHS+=("$a"); fi
done
if [ ${#TARGET_PATHS[@]} -eq 0 ]; then
  PYTEST_ARGS=(tests/performance tests/integration "${PYTEST_ARGS[@]}")
fi
# The API benches already ran above with the app up. Deselect them here rather
# than letting them skip: a skip would be recorded as a coverage hole in the
# main run file while the same bench sits recorded 'ok' in the API file.
if $API_BENCHES; then
  PYTEST_ARGS+=(-k "not bench")
fi

PYTEST_STATUS=0
"$PYTHON" -m pytest -m "integration or performance" -p no:cacheprovider "${PYTEST_ARGS[@]}" \
  || PYTEST_STATUS=$?

# Compare / promote before propagating the pytest status: a bench can regress
# without failing an assertion (the inline bounds are floors, the baseline is
# the drift detector) — that is the whole point of recording.
# Merge the API-bench records into the main run file so there is one run, one
# environment stamp and one baseline to compare against.
if $RECORD && $API_BENCHES && [ -f "$RECORD_PATH" ] && [ -f "${RECORD_PATH%.json}-api.json" ]; then
  "$PYTHON" - "$RECORD_PATH" "${RECORD_PATH%.json}-api.json" <<'PYMERGE'
import json, sys
main_path, api_path = sys.argv[1], sys.argv[2]
main = json.load(open(main_path))
api = json.load(open(api_path))
seen = {b["bench_id"] for b in main["benches"]}
main["benches"].extend(b for b in api["benches"] if b["bench_id"] not in seen)
main["benches"].sort(key=lambda b: b["bench_id"])
json.dump(main, open(main_path, "w"), indent=2)
print(f"📊 merged {len(api['benches'])} API bench record(s) into {main_path}")
PYMERGE
fi

COMPARE_STATUS=0
if $RECORD && [ -f "$RECORD_PATH" ]; then
  if [ -n "$PROMOTE" ]; then
    "$PYTHON" "$PROJECT_ROOT/scripts/perf_compare.py" "$RECORD_PATH" --promote "$PROMOTE"
  fi
  if [ -n "$BASELINE" ]; then
    "$PYTHON" "$PROJECT_ROOT/scripts/perf_compare.py" "$RECORD_PATH" \
      --baseline "$BASELINE" || COMPARE_STATUS=$?
  fi
fi

if [ "$PYTEST_STATUS" -ne 0 ]; then
  echo "❌ Perf/integration suites failed (pytest exit $PYTEST_STATUS)"
  exit "$PYTEST_STATUS"
fi
if [ "$COMPARE_STATUS" -ne 0 ]; then
  echo "❌ Performance regression vs baseline '$BASELINE'"
  exit "$COMPARE_STATUS"
fi
echo "✅ Perf/integration suites passed"
