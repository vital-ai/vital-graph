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
#   ./scripts/check.sh perf         # + benchmarks minus slow_bench  ~5.5m
#   ./scripts/check.sh full         # + the slow benchmarks          ~16m
#   ./scripts/check.sh unit sparql  # any pytest path/-k, straight through
#
# WHY `perf` IS NOT `full`. Across 111 recorded benches the suite measures only
# ~16 SECONDS of execution_ms — 99% of a 15-minute run is building and scanning
# data, not the plans being measured. Eight benches at 20s+ account for 388s of
# it, and they are marked `slow_bench`. Dropping them: 900s -> 330s.
#
# A `perf` run is therefore PARTIAL, and `perf_compare --partial` reports a bench
# it did not run as "not run in this tier" rather than a regression. Promoting a
# partial run is refused outright — it would bake the missing benches in as holes
# (issues/081).
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
  full)
    "$0" pre-commit
    run tests/performance
    ;;
  *)
    # Anything else is passed through, so `check.sh tests/unit/sparql_sql -k foo`
    # works without remembering the env-var incantation.
    run "$TIER" "$@"
    ;;
esac
