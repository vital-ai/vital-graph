#!/usr/bin/env bash
# Tiered test runner — pick the smallest tier that can falsify your change.
#
# WHY THIS EXISTS. A full pass is ~17 minutes and it was being run after every
# edit. Measured on 2026-08-20:
#
#     tests/performance   ~600s   60%   <- benchmarks
#     tests/integration    186s   18%
#     tests/api           ~180s   18%
#     tests/unit            22s    2%
#     tests/conformance     17s    2%
#     docker image build    22s    -    (NOT ~8 min; issues/108 said so and it
#                                        is stale — layer caching makes an
#                                        incremental rebuild cheap)
#
# So 60% of the wait is a BENCHMARK suite whose purpose is comparison against a
# promoted baseline. Running it after every edit is a release gate used as a
# feedback loop. It belongs in `full`, before a promotion, not in the edit loop.
#
#   ./scripts/check.sh              # fast:  unit + conformance      ~40s
#   ./scripts/check.sh pre-commit   # + integration + api            ~6m
#   ./scripts/check.sh perf         # + query benchmarks             ~5.5m
#   ./scripts/check.sh ingest       # the slow/ingest benchmarks     ~6.5m
#   ./scripts/check.sh full         # both                           ~16m
#   ./scripts/check.sh unit sparql  # any pytest path/-k, straight through
#
# WHY `perf` IS NOT `full`. Across 111 recorded benches the suite measures only
# ~16 SECONDS of execution_ms — 99% of a 15-minute run is building and scanning
# data, not the plans being measured. Eight benches at 20s+ account for 388s of
# it, and they are marked `slow_bench`. Dropping them: 900s -> 330s.
#
# TWO BASELINES, one per tier: `baselines/query.json` and `baselines/slow.json`.
# Each is COMPLETE for its own tier, so neither run has holes and BOTH are
# promotable independently — which is the point. A single `main` baseline forced
# every promotion to pay the full 16 minutes, and made a query-tier run look like
# eleven regressions because the ingest benches were "missing".
#
# `perf_compare --partial` still exists for an ad-hoc subset (`-k something`),
# where there genuinely is no matching baseline.
#
# PARALLELISM, measured rather than assumed:
#   integration  -n 4  186s -> 136s   OK, with `serial`-marked tests split out
#   api          -n 4  180s -> 144s   16 FAILURES — shared registry state, so no
#   performance         never — parallel load corrupts what a benchmark measures
set -euo pipefail
cd "$(dirname "$0")/.."

# The vg-test stack, explicitly. See devtools/vg-test.env for why sourcing this
# beats relying on the defaults.
set -a; . devtools/vg-test.env; set +a

PY="${PYTHON:-python}"
TIER="${1:-fast}"
shift || true

run() { echo "── $* "; "$PY" -m pytest "$@" -q --tb=short -p no:warnings; }

case "$TIER" in
  fast)
    run tests/unit tests/conformance
    ;;
  pre-commit)
    run tests/unit tests/conformance
    # xdist for integration, then the serial-marked ones on their own: they
    # measure a shared resource (pool capacity) that parallel workers change.
    run tests/integration -n 4 -m "not serial"
    run tests/integration -m "serial"
    run tests/api
    ;;
  perf)
    "$0" pre-commit
    run tests/performance -m "not slow_bench"
    ;;
  ingest)
    # The 20s+ benches, which are dominated by building and scanning data.
    # Their own baseline, promoted on their own schedule.
    run tests/performance -m "slow_bench"
    ;;
  full)
    "$0" pre-commit
    run tests/performance -m "not slow_bench"
    run tests/performance -m "slow_bench"
    ;;
  *)
    # Anything else is passed through, so `check.sh tests/unit/sparql_sql -k foo`
    # works without remembering the env-var incantation.
    run "$TIER" "$@"
    ;;
esac
