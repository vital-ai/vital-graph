# 345 — The covering bench fails inside the core suite, and runs in the wrong tier

## Status: OPEN, 2026-11-15

## Found

Recording the per-volume query baselines (`issues/306`, `tests/performance/README.md`
"One baseline per dataset volume"), `query.covering.advantage_growth`
(`tests/performance/test_covering_benchmark.py`) failed its validity guard in both full
`vgtest_core` runs:

    index-only scan did 1000 heap fetches at n=100000 — the visibility map is stale,
    so buffers overstate the cost
    assert 1000 == 0

| where | result |
|---|---|
| full suite on `vgtest_core`, API phase (2026-11-15 18:47, 19:17 UTC) | **failed** both times |
| full suite on `vgdata_lead100k`, API phase (18:09 UTC) | ok |
| the test alone on `vgtest_core`, app up, 3 runs | ok, ok, ok (161-176 s each) |

So it is not random: something that runs earlier in the full suite on `vgtest_core`
leaves the bench's fresh `perf_covbench` space without an all-visible visibility map at
n=100,000. Not yet identified. Candidates:
- a transaction holding back the xmin horizon while the bench VACUUMs. The app's
  maintenance job works on the non-excluded spaces of `vgtest_core`; `perf_covbench` is
  not in `VG_MAINTENANCE_EXCLUDE_SPACES`;
- an earlier bench's open snapshot.

Two `backend_xmin` holders (app queries) were visible during the standalone runs, so the
mere presence of app traffic is not enough.

## Second problem: it is an ingest-tier bench in a query-tier run

The file is marked `ingest_bench` (it drops an index and drops its space). It still
lands in the QUERY run because `scripts/run-perf-tests.sh` runs its API phase as
`pytest tests/performance -m performance -k "bench"`, with no tier filter. `-k bench`
matches the FILE NAME `test_covering_benchmark.py`, and the API record is then merged
into the query run. Any `*bench*` file of any tier is pulled in the same way.

## Effect on the baselines

`baselines/query.json` (vgtest_core, promoted 2026-11-15) records this cell as failed: a
known hole, written into its reason. `query_lead100k` recorded it ok.

## To do

1. Make the API phase select API benches by their kind or marker, and filter by the
   tier's mark expression, instead of `-k "bench"`.
2. Find the xmin holder: log `pg_stat_activity` (`backend_xmin`, `xact_start`) and
   `pg_visibility_map_summary` around the bench's VACUUM inside a full core run.
   Consider excluding `perf_*` bench spaces from the maintenance job.
