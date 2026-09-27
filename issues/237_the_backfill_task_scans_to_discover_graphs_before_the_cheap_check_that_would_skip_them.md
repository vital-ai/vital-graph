# 237 — The backfill task scans to discover graphs before the cheap check that would skip them

## Status: FIXED 2026-09-25 in `backfill_server_properties_task.py`.
## Found on production, where the COST measured below is historical —
## the one space involved has since been emptied. The ORDERING was live, and
## would have returned in full against any populated space.

## The fix, and what it measured

`_refresh_targets` now calls `_discover_graphs_cached`, which re-derives only
when the space's quads changed. The signal is `backfill_state.quad_activity` —
the same free `pg_stat_user_tables` counter the per-graph markers already use,
paired with `stats_reset` so a counter reset is detected rather than inferred.
Reusing it was deliberate: a second invalidation signal is a second thing to get
wrong.

**Measured on a real 74M-quad space** (`sp_lead_synth_100k`, vg stack), five
consecutive cycles:

    cycle 1:  535.8 ms   graphs=1   scans so far=1
    cycle 2:    1.8 ms   graphs=1   scans so far=1
    cycle 3:    1.5 ms   graphs=1   scans so far=1
    cycle 4:    1.6 ms   graphs=1   scans so far=1
    cycle 5:    2.1 ms   graphs=1   scans so far=1

One scan instead of five, same answer, ~300x off each subsequent cycle. The
residual 1.5-2 ms is the counter read.

**Three ways it re-derives anyway**, because skipping too much leaves entities
permanently unstamped and nothing reports it — the same defence-in-depth
`backfill_state` documents, one level up:

  * a nudge (`_force_full_check`) ignores the cache entirely — the caller said
    data arrived, and the statistics view lags commits by design;
  * an entry older than `BACKFILL_DISCOVERY_RECHECK_S` (1 h) is ignored, so a
    missed signal self-heals;
  * any failure to read the signal, or a NULL counter, re-derives and caches
    nothing — "unknown" must not compare equal to "unknown" forever.

**`n_tup_ins` does not move on a DELETE**, so a graph that loses its last
KGEntity can linger until the recheck. That costs a target whose scan finds
nothing, which is the cheap direction, and it is why the recheck is not optional.

**Tests:** `tests/unit/test_backfill_discovery_is_gated_on_writes.py`, 11 cases.
The escape hatches are pinned harder than the saving is. Two worth naming: the
activity signal is read BEFORE the scan, so a write landing mid-scan is not
recorded as already covered (asserted by mutating the counter from inside the
fake discovery); and `_refresh_targets` is asserted by source not to call
`discover_graphs_sql` directly, because the defect was the call site and a cache
nothing routes through fixes nothing.

**Tracked by:** `issues/239` (background work is ~half the production
database — this is one member of that group)

**Related:** `issues/143` (maintenance as a share of database time — same
family, different job), `planning/planning_performance/maintenance_incremental_only_plan.md`
(the binding principle: no recurring full walk), `issues/236` (the same mistake
in the ANALYZE/VACUUM scheduler)

## The defect

`tasks/backfill_server_properties_task.py` runs two steps per cycle, in this
order:

1. **`_refresh_targets()` (`:333-337`)** calls `discover_graphs_sql` for every
   non-excluded space — a `SELECT DISTINCT` over `{space}_rdf_quad` joined to
   `{space}_term` (`kg_server_properties.py:353-367`), with no gate of any kind.
2. **`_iteration()` (`:366-378`)** then checks, per target,
   `backfill_state.is_complete(...)` — which skips a graph whose space has had
   no inserts since it was marked complete. Its own comment prices it: *"Proving
   it idle costs 2,593 ms on the 100k fixture, and that is the cost this
   skips."*

So the cheap "nothing to do" gate exists, works, and is applied **after** the
expensive discovery that it would have made unnecessary. A space where every
graph is already complete still pays for full discovery, every cycle, forever.

It is also self-reinforcing: `_iteration` refreshes targets whenever
`is_complete_cycle()` is true, and a cycle in which every target is skipped
completes almost instantly — so the faster the gate works, the sooner the
scan runs again.

## The measurement, and its caveat

`pg_stat_statements`, 57-day window, production:

    SELECT DISTINCT gt.term_text AS graph_uri
      FROM sp_kg_types_rdf_quad q
      JOIN sp_kg_types_term gt ON gt.term_uuid = q.context_uuid
     WHERE q.predicate_uuid = $1 AND q.object_uuid = $2

    calls   45,336        rows returned      33,751
    min      0.0 ms       mean   2,775.8 ms
    max 59,808.5 ms       stddev 8,163.0 ms
    buffers 754,697,942   (~5.7 TB of buffer traffic)
    total   35.0 hours

**Read the distribution, not the mean.** `stddev` at 3x the mean and a `min` of
0.0 ms say this is bimodal, not uniformly slow: it was expensive while the space
held data and is free now that it does not. Re-run today it returns in 17.6 ms
against a table of 0 rows / 72 kB. The 35 hours and the 754M buffers are real
and were spent; they are not a current rate.

Two further things the numbers say:

  * **`sp_kg_types` is the ONLY space that appears.** No other space has a
    `graph_uri` entry in `pg_stat_statements` at all, which means the others are
    in `exclude_spaces` — so 35 hours of production I/O went to discovering
    graphs in the one space nobody thought to exclude, and that is a fixture
    space.
  * **The exclusion list is the wrong control.** It is a manual opt-out that has
    to be maintained as spaces come and go, and it failed exactly the way an
    opt-out fails: the entry nobody added was the entry that mattered.

## The fix

Gate discovery on the same signal the per-target check already uses, or invert
the order so the cheap check runs first:

  * **Cache the target list** and refresh it on a change signal — a space's quad
    count or `n_mod_since_analyze` moving — rather than at the top of every
    cycle. Graph membership changes far more slowly than the cycle runs.
  * **Or skip discovery for a space in which every known graph is already
    complete**, which `backfill_state` can already answer per graph and could
    answer per space.

Either way the cost stops being proportional to cycles and becomes proportional
to writes, which is what
`planning/planning_performance/maintenance_incremental_only_plan.md` requires of
everything on a loop.

## Not established

  * Why `sp_kg_types` held enough data to cost 59.8s at its worst, and when it
    was emptied. `pg_stat_statements` has no time axis, so the history was not
    reconstructed; the RDS Postgres log (`log_min_duration_statement = 1000`)
    would show it, which is the method `issues/143` documents.
  * Whether the backfill task is still needed at all, or whether its work is
    complete everywhere and the loop is now pure overhead.
  * What the other excluded spaces would cost if re-included — i.e. whether the
    exclusion list is currently hiding this defect rather than the defect being
    small.
