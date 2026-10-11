# 255 — `_load_missing_pair_stats` has one unfenced read, and its own cost is unmeasured

## Status: FIXED 2026-10-11 — items 1 and 2 in `85b5dfa3`, item 3 (uncommitted).
##
## Was: FIXED 2026-10-11, items 1 and 2 (`85b5dfa3`, not yet released). Item 3,
## measuring the loader's 7,710 ms, is still open.
##
## Found: filed 2026-10-02 from a production monitoring review. Nothing
## here is fixed. The LOCK-BLOCKING half of this path is `issues/145` and is
## fixed and deployed; what follows is the part that fix did not cover.

## Update 2026-10-10 — the eight production failures were the FENCED read

`264` matched all 8 `pair stats lookup failed ... lock timeout` lines from
2026-10-01 to 10-10 to a `recompute_stats_tables` completing 100-190 ms later.
The recompute's TRUNCATE locks `rdf_stats`, not `rdf_quad`, so every one was
the 100 ms-fenced `rdf_stats` read doing what `145` designed it to do, not this
issue's unfenced `rdf_quad` count. That answers the ambiguity raised in `145`'s
2026-10-02 note for those eight, and `264` removed the TRUNCATE (`e0828f8d`).
**This issue's own defect is unchanged:** the `rdf_quad` count at
`generator.py:1145` is still unfenced. It simply was not involved.

## Why this is not just `issues/145` again

`issues/145` bounded the stats reads that feed the planner to
`STATS_LOCK_TIMEOUT_MS = 100`, so they fail fast instead of parking behind a
writer. It landed in `49a63fb4` on 2026-09-02 and has been deployed for a month.
Six sites in `generator.py` carry `lock_timeout_ms=STATS_LOCK_TIMEOUT_MS`,
including the pair-stats read at `generator.py:1120`.

**`_load_missing_pair_stats` has a SECOND read, and it is not fenced**
(`generator.py:1145`). When `rdf_stats` does not hold a pair — which the
surrounding comment says is the normal case for an anchor's
`(vitaltype, KGEntity)` — the loader counts it directly:

    crows = await db.execute_query(
        f"SELECT count(*) AS n FROM (SELECT 1 FROM {space_id}_rdf_quad "
        f"WHERE predicate_uuid = ... AND object_uuid = ..."
        f"{_ctx_filter(space_id, _lock)} "
        f"LIMIT {_PAIR_COUNT_CAP}) s",
        conn=conn, conn_params=conn_params)          # <- no lock_timeout_ms

`execute_query`'s `lock_timeout_ms` defaults to `None`, so this inherits the
database-level `lock_timeout = 10s` (`ALTER DATABASE vitalgraphdb`, per
`issues/136`). It is the same kind of read as the six that are fenced — an
optimisation input whose failure only leaves a leaf unpriced — and it can block
a user request for ten seconds.

**And `rdf_quad` does take an exclusive lock.** `bulk_export.py` holds ACCESS
EXCLUSIVE on the core tables until its caller commits, by its own docstring. So
the conflict is real, not theoretical — it is simply a different table and a
different holder than the `rdf_stats` TRUNCATE that `issues/145` chased.

**Why no test caught it.** `test_every_stats_read_bounds_its_lock_wait` exists
precisely to stop an unfenced stats read being added, and it would not see this
one: it counts references to `_rdf_stats ` and `_rdf_pred_stats`, and this read
is against `_rdf_quad`. The guard is scoped to the stats tables; the hazard is
the read's ROLE on the request path, which this read shares and that table name
does not express.

## What was observed, and what the observation does NOT establish

Production, 2026-10-02, one occurrence in a 12.8h window across 380,585 events —
the only problem line in it:

    generator - _load_missing_pair_stats - WARNING -
      semijoin gate: pair stats lookup failed, plan will be chosen
      without leaf statistics: canceling statement due to lock timeout

It degraded as designed: the plan was chosen without leaf statistics and the
caller got a worse plan, not an error.

**WHICH read blocked is not established, and the difference is three orders of
magnitude.** The warning is raised by the `except` at `generator.py:1386`, which
wraps the whole function — the fenced `rdf_stats` read at `:1120`, the unfenced
`rdf_quad` count at `:1145`, and `_load_value_stats_cached`. It carries no
duration. So:

  * if it was the fenced site, the request paid ~100ms and `issues/145`'s fix
    is working exactly as designed;
  * if it was `:1145`, the request paid the full 10s.

The monitoring review that surfaced this read it as "waited past the 10s lock
fence". That is an inference, not a measurement, and for the fenced site it is
wrong by 100x. **The log line cannot answer it, which is the first thing to
fix:** this warning should report the elapsed wait and which read failed.
Without that, every future occurrence is equally unattributable.

## The cost half: pair-stats loading is expensive in its own right

Separately from locking, this path was measured at **7,710 ms** inside a 7.9s
cold-cache query generation (reported 2026-10-01; the measurement is cited here,
not reproduced). So the loader both dominates a slow query and is a plausible
candidate for losing a lock race.

**It produces no errors when it is merely slow.** The lock failure at least logs
a WARNING; the expensive-but-successful case logs nothing comparable, so a
7.7s planning cost is invisible unless someone is already looking at a slow
query. That is the reason to file it rather than watch it.

Not established, and each matters for the fix:

  * **Which part of the 7,710 ms it is.** The bounded count at `:1145` runs once
    per still-missing pair, in a `for` loop, each a separate round trip — so a
    query with several unpriced pairs pays several. Whether the cost is the
    round trips, the scans, or `_load_value_stats_cached` is unmeasured.
  * **Whether `_ctx_filter` is indexed.** The count filters by graph on top of
    `(predicate_uuid, object_uuid)`. If that composite is not covered, a
    `LIMIT`-capped count still scans to find its rows, and `_PAIR_COUNT_CAP`
    bounds the output, not the work. This is a hypothesis; it has not been
    EXPLAINed.
  * **Hit rate of `_pair_count_cache`.** It is per-process and keyed by
    `(space, pred, obj, lock_graph)`. If the keys are effectively unique per
    query, the cache never pays and every query pays the full loop.

## The fix, in the order the evidence supports

1. **Make the warning attributable** — log the elapsed wait and the failing
   read. Cheap, and without it the next occurrence is as ambiguous as this one.
   Do this first regardless of the rest.
2. **Fence `:1145`** with `STATS_LOCK_TIMEOUT_MS`, same as its six siblings, and
   widen `test_every_stats_read_bounds_its_lock_wait` so it is scoped to the
   loader's reads rather than to tables whose names contain `stats`. This is the
   same one-line trade `issues/145` already decided: waiting 10s to maybe price
   a leaf is never right, because after 10s the leaf is unpriced anyway.
3. **Measure the 7,710 ms before optimising it.** Which of the three candidates
   above dominates decides whether the answer is batching the per-pair counts
   into one round trip, an index, or a better cache key. `issues/238` is the
   standing reminder that a plausible-looking fix to a traversal cost can be an
   IO disaster.

1 and 2 are small and independent of 3.

## Not a regression, and not caused by the current release

The release deployed 2026-10-01 is clean on every failure mode it targets. This
path predates it: the fence it lacks was added a month earlier for its sibling
reads, and the loader's cost is older still. It is filed because it is the most
plausible next source of query-latency surprises and it degrades silently, not
because anything in the deploy moved it.

## Reproduce

    grep -n "lock_timeout_ms" vitalgraph/db/sparql_sql/generator.py

Six hits. `_load_missing_pair_stats` spans `:1063`-`:1163`; the read at `:1120`
is in that list and the one at `:1145` is not.

**Related:** `issues/145` (the sibling reads, fixed and deployed — this is the
same trade at the site it missed), `issues/136` (where the 10s database-level
`lock_timeout` comes from), `issues/140` (the handler that makes this path
visible at all), `issues/138`/`issues/090`/`issues/101` (pair stats and the
gate's DECISION, as distinct from the cost of loading them)

## Fix, 2026-10-11 — items 1 and 2

1. **The warning names the read and the wait.** `_load_missing_pair_stats`
   records which read is running and since when, and the failure warning now
   reads `pair stats lookup failed during pair count (rdf_quad) after 10003 ms`
   (or `during pair stats (rdf_stats) after 101 ms`). The stages are: pair stats
   (rdf_stats), pair count (rdf_quad), value stats, range count (rdf_quad), text
   term count (term), text count (rdf_quad).
2. **Every read in the loader is fenced**, not just `:1145`. The same function
   had four more unfenced reads of the same kind: the range count, the term-size
   read, and the two text counts. All five now take
   `lock_timeout_ms=STATS_LOCK_TIMEOUT_MS`.

Tests (`tests/unit/sparql_sql/test_stats_lock_timeout.py`, 11 pass):
`test_every_stats_read_bounds_its_lock_wait` now expects 11 fenced sites (was 6);
new `test_every_read_in_the_pair_stats_loader_bounds_its_lock_wait` walks the
loader's AST and fails on ANY `execute_query` without the fence, which scopes the
guard by the read's role rather than by table name, as this issue asked; new
`test_the_failure_warning_names_the_read_and_the_wait` raises a lock timeout on
the rdf_quad count and checks the warning says so. Both new tests fail against
the old generator.

**Still open: item 3.** The 7,710 ms loader cost is unmeasured and unchanged.

## Item 3, 2026-10-11 — measured, and the cost was not the loader's reads

**Production's 7,710 ms came from the boot warm-up query**
(`SELECT ?s WHERE { GRAPH <g> { ?s ?p ?o } } LIMIT 1`, `issues/258`): a cold
PROCESS. Reproduced locally by running that query in a fresh process
(`test_scripts/perf/_issue255_loader_cold.py`), with the loader now logging
per-read time:

| space | cold process | of which | warm |
|---|---|---|---|
| `nurture_typed` | 2,551 / 2,468 ms gen (51 s with the DB cache cold too) | **value stats freshness 2,221 / 2,240 ms** (50,212 ms) | 4 ms |
| `sp_lead_synth_100k` | 257-345 ms gen | loader 4-5 ms | 4 ms |
| `wordnet_frames` | 144-192 ms gen | loader 2-3 ms | 2 ms |

**The cost was `apply_freshness`**, which ran over EVERY histogram in the space
for every query, though its verdicts are read only by range estimates; the boot
warm-up has no range leaf at all. Its shape probe scans each drifted predicate's
rows and is cached only per process, so every fresh process paid it in full.

**Fix:** freshness runs only for the predicates the query estimates ranges on
(the subset shares the cached entry dicts, so verdicts still land in the cache),
and not at all without a range leaf. After: `nurture_typed` cold loader
**2-4 ms**, cold warm-up query ~0.3 s total (was ~2.7 s).

The loader now accumulates time per read and logs a breakdown at INFO when a load
takes at least `VG_PAIR_STATS_SLOW_MS` (500 ms), so production can say which read
a slow load spent its time on. Test:
`test_freshness_runs_only_for_the_querys_range_predicates` (both cases fail
against the previous generator).
