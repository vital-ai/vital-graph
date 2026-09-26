#!/usr/bin/env bash
# The bulkhead A/B, through the running service. `issues/231`.
#
# WHY THIS EXISTS. The API load test asserts an absolute latency budget, and at
# a 30-connection pool it passes with no `pool_wait` records at all — nothing
# ever queues, so the run cannot distinguish "the bulkhead works" from "the load
# was too light for it to matter". A budget that passes for the wrong reason is
# worse than no budget, because it reads as evidence.
#
# So: same load, same image, two configurations, one variable.
#
#   CONTROL    DB_INTERNAL_POOL_SIZE=0  — background work on the request pool,
#                                        i.e. the behaviour that caused the
#                                        2026-09-24 outage
#   TREATMENT  DB_INTERNAL_POOL_SIZE=2  — background work isolated
#
# Both arms spend the SAME total, because the internal pool is carved out of
# `max_pool_size` rather than added to it. Without that, the treatment wins on
# extra capacity and the result says nothing about isolation.
#
# and a SMALL request pool in both arms, because contention is only reachable
# there. At max_size=30 on a laptop the database is never the constraint.
#
# Reads the metrics off the test's own stdout and the `pool_wait` count out of
# the container log, which is the record that says whether anything queued.
#
#   ./test_scripts/perf/pool_bulkhead_ab.sh [runs_per_arm]
#
# Requires the test stack image to be built with the current code:
#   docker compose -f docker-compose.test.yml build
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1

RUNS="${1:-3}"
POOL="${DB_MAX_POOL_SIZE:-5}"
# Offered concurrency must EXCEED the pool or nothing queues and neither arm
# measures anything. Default chosen as ~2x the pool for that reason.
export VG_LOAD_WRITERS="${VG_LOAD_WRITERS:-$((POOL * 2))}"
# See sub-second queueing; the 1.0s production threshold reports nothing here.
export VG_SLOW_ACQUIRE_SECONDS="${VG_SLOW_ACQUIRE_SECONDS:-0.05}"
COMPOSE="docker compose -f docker-compose.test.yml"

export LOCAL_CLIENT_SERVER_URL=http://localhost:8002
export VG_TEST_PG_PORT=5433
export VG_TEST_PG_PASSWORD=testpass
export VG_RUN_LOAD_TEST=1

run_arm() {
  local label="$1" internal="$2" pool="${3:-$POOL}"

  echo ""
  echo "=================================================================="
  echo " $label — budget $pool, internal $internal (request $((pool - internal))), writers $VG_LOAD_WRITERS"
  echo "=================================================================="

  # DB_POOL_SIZE (the min) must come down with the max. asyncpg refuses a pool
  # whose min exceeds its max, and the refusal surfaces as a NoneType error from
  # startup rather than anything about pools — which is exactly how the first
  # run of this script produced four silent failures and two empty arms.
  # VG_SLOW_ACQUIRE_SECONDS is read by the SERVER, so it has to reach the
  # container through compose — exporting it in this shell would only configure
  # the pytest client, which owns no pool.
  DB_POOL_SIZE=1 DB_MAX_POOL_SIZE="$pool" DB_INTERNAL_POOL_SIZE="$internal" \
  VG_SLOW_ACQUIRE_SECONDS="$VG_SLOW_ACQUIRE_SECONDS" \
    $COMPOSE up -d --wait >/dev/null 2>&1 || {
      echo "  FAILED to bring the stack up"; return 1; }

  # WAIT FOR REAL READINESS, not for the healthcheck. `up -d --wait` goes green
  # before the app finishes its startup warm-up — measured at 5,558ms over 141
  # spaces — and a login during that window fails with a bare ReadError. A
  # `sleep 2` here is what made the treatment arm report two BROKEN runs while
  # the control passed on timing luck.
  local ready=""
  for _ in $(seq 1 60); do
    if curl -s --max-time 5 -X POST "$LOCAL_CLIENT_SERVER_URL/api/login" \
         -H 'Content-Type: application/x-www-form-urlencoded' \
         -d 'username=admin&password=admin' 2>/dev/null | grep -q access_token; then
      ready=yes; break
    fi
    sleep 2
  done
  if [ -z "$ready" ]; then
    echo "  ABORT: server never became ready (login kept failing)"; return 1
  fi

  # Confirm the arm IS the arm, scoped to THIS container's log. The previous
  # version grepped the whole log and read a stale line from an earlier
  # container, so it reported the control as having an internal pool — the
  # check built to prevent running one arm twice could not see which arm it
  # was in.
  local state
  state=$(docker logs vitalgraph-test-app 2>&1 \
            | grep -E "INTERNAL pool (created|DISABLED)" | tail -1)
  if [ "$internal" = "0" ]; then
    case "$state" in
      *DISABLED*) ;;
      *) echo "  ABORT: asked for internal=0 but log says: $state"; return 1 ;;
    esac
  else
    case "$state" in
      *"created: max_size=$internal"*) ;;
      *) echo "  ABORT: asked for internal=$internal but log says: $state"; return 1 ;;
    esac
  fi
  echo "  arm confirmed: $(echo "$state" | sed 's/.*- connect - //')"

  # DISCARDED WARM-UP RUN. Each arm recreates the container, so run 1 pays the
  # 141-space startup warm-up, the first-touch of a brand-new test space
  # (ensure_edge_table, stats loading) and a cold PostgreSQL cache. Measured
  # back-to-back in an IDENTICAL configuration, cold gave n=5 p99=15114ms and
  # warm gave n=149 p99=454ms — a 33x spread that has nothing to do with which
  # arm it is. Comparing a cold control against a warm treatment (or the
  # reverse) is how this harness produced a result that looked like the bulkhead
  # made things worse.
  echo "  warm-up (discarded)..."
  VG_LOAD_SECONDS=8 timeout 600 python -m pytest \
    tests/api/test_query_latency_under_write_load.py \
    -q -s -p no:randomly -W ignore::DeprecationWarning >/dev/null 2>&1

  for i in $(seq 1 "$RUNS"); do
    # Zero the log window so the pool_wait count belongs to THIS run only.
    local since
    since=$(date -u +%Y-%m-%dT%H:%M:%S)
    local out
    out=$(timeout 600 python -m pytest \
            tests/api/test_query_latency_under_write_load.py \
            -q -s -p no:randomly -W ignore::DeprecationWarning 2>&1)
    local status="pass"
    echo "$out" | grep -qE "^(FAILED|ERROR)" && status="FAIL"
    # A run with no metrics line did not measure anything — the stack is
    # misconfigured, not slow. Say so instead of printing an empty FAIL.
    if ! echo "$out" | grep -q "reads n="; then
      echo "  run $i [BROKEN — no metrics; stack did not serve]"
      echo "$out" | grep -iE "error|assert|Exception" | head -2 | sed "s/^/       /"
      continue
    fi
    local waits
    waits=$(docker logs --since "$since" vitalgraph-test-app 2>&1 | grep -c "pool_wait")
    printf "  run %d [%s]  %s  pool_wait=%s\n" \
      "$i" "$status" "$(echo "$out" | grep 'reads n=' | sed 's/^ *//')" "$waits"
  done

}

# CAPACITY-MATCHED BY CONSTRUCTION, since 2026-09-25: `internal_pool_size` is
# carved OUT of `max_pool_size` rather than added to it, so both arms run on the
# same total budget and the only difference is whether it is partitioned.
#
#   control    budget N, internal 0  ->  request N,     total N
#   treatment  budget N, internal 2  ->  request N - 2, total N
#
# This matters because the earlier, additive behaviour made the treatment look
# 3x better on p50 purely by spending two extra connections; matching the totals
# by hand removed the effect entirely. Now it cannot reappear.
INTERNAL=2
run_arm "CONTROL   (pre-split behaviour)" 0          "$POOL"
run_arm "TREATMENT (bulkhead)"            "$INTERNAL" "$POOL"

echo ""
echo "Restoring the stack to its normal configuration."
# Explicitly, not by omission. This shell EXPORTS VG_SLOW_ACQUIRE_SECONDS, so a
# bare `up` re-interpolates 0.05 and leaves the stack logging a pool_wait for
# every acquire over 50ms — measurement settings quietly left on a stack that is
# back to serving.
env -u VG_SLOW_ACQUIRE_SECONDS -u DB_POOL_SIZE -u DB_MAX_POOL_SIZE \
    -u DB_INTERNAL_POOL_SIZE -u VG_LOAD_WRITERS \
  $COMPOSE up -d --wait >/dev/null 2>&1
echo "  restored: $(docker exec vitalgraph-test-app printenv \
  | grep -E "DB_MAX_POOL_SIZE|DB_INTERNAL_POOL_SIZE|VG_SLOW_ACQUIRE_SECONDS" \
  | tr '\n' ' ')"

echo ""
echo "READ IT THIS WAY: the control must show pool_wait > 0 — if it does not,"
echo "the load never reached contention and NEITHER arm proves anything. Only"
echo "once the control queues does the treatment's latency mean something."
