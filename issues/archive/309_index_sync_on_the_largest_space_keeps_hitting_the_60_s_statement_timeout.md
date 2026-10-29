# 309 — Index sync on the largest space keeps hitting production's 60 s statement timeout

## Status: RESOLVED — released in v0.0.97 and verified on production 2026-10-29: 0 index-sync statement timeouts on the new tasks over 14:23-15:50Z (65 min steady state from 14:45), against 50-85 an hour before.
##
## Was: FIXED 2026-10-25, not yet released (verified read-only against production). Open for: the post-deploy check (`pg_stat_statements` for the lookup, the worker's timeout warnings).

**Related:** `issues/291` (the index-sync queue and its trigger), `issues/294`
(the consumer deadlock, fixed: 17 `DeadlockDetectedError` in the 29 h before
v0.0.96, 0 after), `issues/136` (the same RDS `statement_timeout = 60 s` killing
VACUUMs on the big quad table).

## Found

Production CloudWatch, `/ecs/vitalgraph-prod`, streams `ecs/vitalgraph/`, the
29 h after v0.0.96 went live (2026-10-24 08:41 EDT to 2026-10-25 08:37).
Extracts in `internal_data/prod_logs_20261025/` (gitignored).

The main KG space (76.2M quads, 37 GB with indexes, the largest) fails its
index sync continuously:

| message (`index_sync_worker`) | 29 h before v0.0.96 | 29 h after |
|---|---|---|
| `N subject(s) failed (attempt k), retrying in Ns: QueryCanceledError: canceling statement due to statement timeout` (WARNING, k < 5) | 1,313 | 893 |
| the same at ERROR (k >= 5) | 41 | 18 |
| `index sync sweep failed: TimeoutError` | 224 | 186 |
| `index sync consumer N on <space>: TimeoutError` | 5 | 9 |

- Every one of the 24 hours after the deploy has failures, about 50-85 an
  hour. Only that space appears.
- Batches of 100 subjects fail, and so do batches of 5, 13, 47 and 58, so a
  single statement can exceed 60 s whatever the batch size. That points at the
  statement's plan or the work per subject on this space, not at load.
- Retries back off 5 s, 10 s, ... 80 s, 160 s (attempt 6 seen) and never give
  up (`index_sync_worker.py`: ERROR from attempt 5). The queue is drained
  eventually: `vgs_<key>_index_sync_queue` for that space held **0 rows** at
  2026-10-25 ~08:45 (read-only check). So the search indexes LAG during write
  bursts, by minutes, rather than falling permanently behind. The repeated
  60 s statements are load on the shared instance meanwhile.

The same space's maintenance also times out:

| message | before | after |
|---|---|---|
| `aux-table ANALYZE(<space>) task failed` | 13 | 5 |
| `auto_analyze(<space>) task failed` | 0 | 3 |
| `edge_integrity: drift probe TIMED OUT for <space> (QueryCanceledError)` | 1 | 5 |

Not from v0.0.96: every index-sync line was present before the deploy, and
the counts fell after it.

## Other pre-existing noise in the same window (not this issue)

Recorded so it is not rediscovered as new. All present before v0.0.96, all
lower after: `auto_sync task failed` (323 -> 208), the segmentation worker's
`Error polling space` for every space (172 -> 149), `space_prewarm` failed
(42 -> 39), internal-pool `pool_wait` / `acquire timed out` (2,747 / 969 ->
1,922 / 770), event-loop stalls (6,388 -> 3,527) and GC pauses
(3,471 -> 2,948). The ERROR lines for `auto_sync` and the segmentation worker
carry no exception text after the colon, so their cause is not in the log;
that is a logging defect worth its own fix.

## Next

1. Identify the statement that times out. The warning names only the
   exception. Either log the statement (or its kind) with it, or reproduce on
   a copy of that space at prod scale and EXPLAIN the sync's queries for one
   batch.
2. Decide by what it is: a plan fix (a subject-batch lookup that scans), a
   per-session `statement_timeout` for the worker's own connection (as the
   loader and the `object_count` migration do, `issues/304`), or smaller work
   per statement.
3. Measure lag directly: the age of the oldest queued row over a write burst.

## Root cause (2026-10-25): a generic cached plan for the geo-slot lookup

**The statement.** RDS's own log (`log_min_duration_statement = 1000`, and a
cancelled statement is logged with its text) for the 25 h after the deploy,
downloaded to `internal_data/prod_logs_20261025/rds/`: **946** statement-timeout
cancels, all as `vitalgraph_user`. **926** are one statement,
`index_sync_worker._GEO_SLOTS_OF_EDGES_SQL`, the geo-slot lookup in
`resolve()`, on this space's quad table (916 under its storage key, 10 under
its old name just before the re-key). The other 20 are maintenance probes and
a stats recompute: the maintenance timeouts above.

**Its cost.** `pg_stat_statements` (since 2026-10-21): **26,954** completed
calls, mean **4,373 ms**, max 59,972 ms, **0 rows every call**, about
**3,749,808 buffers per call**. That is roughly 33 hours of execution in four
days on the shared instance, plus the cancelled runs. Completed runs in the
RDS log take 1-52 s. It always returns nothing: this space has no geo slots
at all (no `vitaltype = KGGeoLocationSlot` quad in any graph).

**Not the data, the subjects or the settings.** Replayed read-only:

- sampled edge, slot-edge and non-edge subjects at batch sizes 1, 5, 13, 47,
  100: 0.2-9 ms, 5 buffers;
- the exact batches the worker had claimed, captured from the queue while it
  ran (`queue_batches.json`), including a 50-subject batch that then failed
  with the timeout in production: **3.9 ms, 5 buffers**;
- session settings our code uses (`join_collapse_limit = 1`, `enable_sort =
  off`, `jit = off`, ...): at most 211 ms.

**Reproduced: the generic plan.** asyncpg prepares a statement once per
connection and reuses it. Under the default `plan_cache_mode = auto`,
PostgreSQL may switch a prepared statement to a GENERIC plan (planned without
the parameter values) after five custom ones. With the failed batch:

| plan | result |
|---|---|
| custom (`force_custom_plan`) | 3.3 ms |
| generic (`PREPARE` + `force_generic_plan` + `EXPLAIN ANALYZE EXECUTE`) | **timeout (> 90 s)** |

Every parameter is passed as `$N`, including the six constants (`$3`-`$8`:
vitaltype, the two edge types, the edge source/destination predicates, the geo
slot type). Without values, the generic plan estimates each type lookup at
~11 rows by default selectivity. It nests loops through `qt`
(`vitaltype = Edge_hasKGSlot`, really 3,984,555 rows) per frame, and joins
`g` (the geo-slot check) as a Materialize with a join FILTER on
`g.subject_uuid = d.dest`. That loses the custom plan's early exit, where the
empty geo-slot side is read first and the statement stops. A worker
connection lives for hours, so once a connection switches, every later call
on it pays the full cost.

(A first check of the generic plan prepared the `EXPLAIN` through asyncpg.
PostgreSQL then plans the inner query with the values known, so that check
showed the custom plan both times. Only a SQL-level `PREPARE` reproduces the
generic plan.)

## Fix (proposed)

1. Write the six constants into the SQL as literals (they are fixed per
   process), leaving only the graph (`$1`) and the subjects (`$2`) as
   parameters. A generic plan then knows the types and their sizes.
2. Run the statement with `SET LOCAL plan_cache_mode = force_custom_plan`
   anyway; planning it per call costs well under a millisecond.
3. Skip the lookup when the space has no geo slots (no `(vitaltype,
   KGGeoLocationSlot)` pair in the loaded stats): most spaces, including this
   one, so roughly 6,700 calls a day disappear.

Validation: a unit test that the SQL carries the constants as literals; a
generic-plan check on the vg test stack at prod scale (`sp_lead_synth_100k`
holds 5.3M edges) with `PREPARE` + `force_generic_plan`; after deploy,
`pg_stat_statements` for this statement and the worker's timeout warnings.

Follow-up audit: other asyncpg-prepared statements on the quad tables that
pass constants as parameters (the worker, `auto_sync`, maintenance) share the
risk.

## Fix as built (2026-10-25)

`index_sync_worker`:

- `_GEO_SLOTS_OF_EDGES_TEMPLATE` / `_geo_slots_of_edges_sql(quad)`: the six
  types are literal uuids, built once per quad table (`lru_cache`), so only
  `$1` (graph) and `$2` (subjects) are parameters.
- A top-level `WHERE EXISTS (geo slot of type KGGeoLocationSlot in $1)`:
  uncorrelated, one InitPlan evaluated first, so a graph without geo slots
  skips the statement whatever plan it gets.
- `resolve()` runs it in a transaction with `SET LOCAL plan_cache_mode =
  force_custom_plan`.

**Verified, read-only against production**, with the 50-subject batch that
timed out there, SQL `PREPARE` + `EXPLAIN (ANALYZE, BUFFERS) EXECUTE`:

| | old SQL | new SQL |
|---|---|---|
| custom plan | 3.3 ms | 5.5 ms, 8 buffers |
| generic plan | **> 90 s (timeout)** | **2.1 ms, 5 buffers** |

No production space has any geo slots (checked every space), so there the
guard ends every call. A space with geo slots runs the full lookup with the
types known to the planner. Its correctness is pinned by
`test_an_edge_change_reaches_the_geo_slot_it_points_at`; its speed at scale
could not be measured, because no space here or on production has geo slots.

Tests: `tests/unit/test_index_sync_geo_lookup.py` (literals, parameters, the
guard); `test_index_sync_trigger.py` and `test_index_sync_queue.py`, 22
passed; the vectorization / index-sync integration set, 27 passed.

After deploy: `pg_stat_statements` for the lookup (mean was 4,373 ms over
26,954 calls) and the worker's `QueryCanceledError` warnings (about 900 per
29 h) should both drop to near zero.

## Audit: the same trap elsewhere (2026-10-25)

Production `pg_stat_statements`, `vitalgraph_user`, parameterized statements
on the quad / term / edge / frame_slot tables, by total execution time since
2026-10-21:

| # | statement (code) | calls | total | mean | max |
|---|---|---|---|---|---|
| 1 | `entity_slot_sort_coverage` (`sync_entity_slot_sort.py`) | 41,430 | 40.1 h | 3.5 s | 310 s |
| 2 | `discover_graphs_sql` (`kg_server_properties.py`) | 64,147 | 35.3 h | 2.0 s | 59.8 s |
| 3 | the geo-slot lookup (fixed above) | 27,334 | 33.2 h | 4.4 s | 60 s |
| 4 | edge-integrity dangling counts (`sync_edge_table.py`) | 9,086 | 29.3 h | 11.6 s | 59 s |
| 5 | edge-type agreement (`edge_type_agreement.py`) | 2,675 | 21.4 h | 28.7 s | 298 s |
| 6 | the `entity_slot_sort` `WITH slots ... has_value` scan, per space | ~817 each | 2.8-13.9 h | 12-61 s | 330 s |
| 7 | `count_entities_needing_backfill_sql` (`kg_server_properties.py`) | 26,527 | 5.3 h | 722 ms | 59.5 s |
| 8 | `check_subjects_exist` (`sparql_sql_space_impl.py`) | 136,674 | 2.5 h | 65 ms | 8 s |

#4-#6 are maintenance scans of whole tables by design: slow on large spaces
whatever the plan. They are the "maintenance timeouts" above.

The targeted ones, replayed read-only on the largest space as SQL `PREPARE`
with the exact SQL and arguments each function sends (captured through a stub
connection), custom vs generic plan:

| # | custom | generic | verdict |
|---|---|---|---|
| 1 coverage probe | 3.2 s, 867,678 buf | **51.0 s, 3,299,947 buf** | the trap: **fixed** |
| 2 discover_graphs | 57 ms | 27 ms | fine either way |
| 7 backfill count | **17.6 s** | 2.6 s | the opposite: the CUSTOM plan is 7x worse |
| 8 check_subjects_exist | 14 ms | 1 ms | fine |

**#1 fixed:** `entity_slot_sort_coverage`'s four values are fixed constants
(the entity-type predicate URI, `vitaltype`, the frame-edge type,
`hasEdgeSource`). As literals the statement has NO parameters, so its generic
plan is its custom plan; no `SET LOCAL` needed, which matters because it runs
inside a caller's transaction. Verified on production: no parameters, 867,678
buffers (the custom plan's exactly). Unit: `test_the_coverage_probe_takes_no_parameters`;
the existing `test_slot_sort_coverage_probe.py` passes. Its integration tests
(`test_slot_sort_coverage_frameless.py`, `test_slot_sort_shortfall_is_visible.py`)
could not run: the vg test stack was stopped for the planner stack. Run them
before this ships.

**Not a blanket fix.** #7 shows why `plan_cache_mode = force_custom_plan` must
not be set for the whole internal pool: there the generic plan is the better
one. Each statement needs its own measurement.

**Found on the way, not the generic-plan trap (follow-ups):**

- #7 `count_entities_needing_backfill_sql` is heavy by construction (four
  `NOT EXISTS` over every KGEntity of a graph: 17.6 s custom on the largest
  space) and runs 26,527 times in four days.
- #2 `discover_graphs_sql` runs 64,147 times in four days (about one every
  5 s). Its production mean of 2.0 s is not its plan (27-57 ms here on the
  largest space), so the cost is elsewhere: other spaces, or contention.
- Both belong to the server-properties backfill; how often it runs, and
  whether it needs to rediscover graphs every cycle, is the question.
- The coverage probe (#1) also runs ~10,000 times a day: frequency, not just
  plan.

## Verified on production, 2026-10-29

Production, v0.0.97 (live 2026-10-29 14:23Z), checked read-only in CloudWatch `/ecs/vitalgraph-prod`, streams `ecs/vitalgraph/`, scoped to the two new tasks (the old tasks drained until ~14:29 and their lines are indistinguishable for this message).

- **0** `index_sync_worker` statement-timeout lines from either new task, boot
  to 15:50Z. The 6 seen in the first minutes came from the two OLD tasks while
  they drained (last at 14:29:11), not from catch-up on the new code.
- The one timeout on a new task in that window (14:35:59) is the maintenance
  `edge_integrity` drift probe on the main space — audit item 4 above, a
  whole-table scan by design, not this issue.
