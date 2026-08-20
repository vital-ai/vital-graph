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
#   ./scripts/check.sh perf         # + ALL query benchmarks         ~10m
#   ./scripts/check.sh ingest       # only the data-building benches ~4m
#   ./scripts/check.sh full         # both                           ~16m
#   ./scripts/check.sh unit sparql  # any pytest path/-k, straight through
#
# THE SPLIT IS BUILDS-DATA vs READS-RESIDENT-DATA, not fast vs slow.
#
# Three benches BUILD a throwaway space and drop it again — ingest_throughput,
# per_write_curve, growth_curve, ~234s between them. Their cost is the data they
# create, and NOTHING in the query tier depends on them: that tier reads the
# resident fixtures (sp_lead_synth_*, wordnet_frames, ...) which are already
# loaded. So they get their own baseline and their own schedule.
#
# An earlier version of this split also excluded four EXPENSIVE READS
# (aggregate_growth, slot_value_attachment_on_wordnet, deep_paging,
# relation_traversal, ~247s) purely for being slow, and called the tier
# "ingest". That was wrong twice: they build nothing, and they are the most
# demanding QUERY cases in the suite — the deep-paging bench is where the
# bistable plan in issues/112 lives. A query baseline without them has exactly
# the holes this file argues against, so they are back in the query tier and the
# tier is ~10m rather than ~5.5m.
#
# TWO BASELINES, one per tier: `baselines/query.json` and `baselines/ingest.json`.
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
    run tests/performance -m "not ingest_bench"
    ;;
  ingest)
    # The benches that build their own data. Their own baseline, promoted on
    # their own schedule; the query tier never needs them.
    run tests/performance -m "ingest_bench"
    ;;
  full)
    "$0" pre-commit
    run tests/performance -m "not ingest_bench"
    run tests/performance -m "ingest_bench"
    ;;
  *)
    # Anything else is passed through, so `check.sh tests/unit/sparql_sql -k foo`
    # works without remembering the env-var incantation.
    run "$TIER" "$@"
    ;;
esac
