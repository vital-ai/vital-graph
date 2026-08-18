# The Stats Resync Fails With a Duplicate Key on a Large Space

## Status: OPEN — reproduced, worked around, mechanism NOT established

Loading `sp_lead_synth_100k` (50,436,200 quads, 10,467,403 terms) on 2026-08-17
completed its COPY and index rebuild, then died in the auxiliary resync:

    asyncpg.exceptions.UniqueViolationError: duplicate key value violates
    unique constraint "sp_lead_synth_100k_rdf_stats_pkey"
    DETAIL: Key (predicate_uuid, object_uuid)=(10aad51f-…, 0f363ae5-…) already exists

`scripts/repair_stats_tables.py --space sp_lead_synth_100k` reproduces it, and
**the reported key is DIFFERENT every time** — three runs, three pairs. That is
what makes it look like a plan-level effect rather than bad data.

## What is established

* **Serial succeeds.** The same full-rebuild statement, run with
  `max_parallel_workers_per_gather = 0`:

      TRUNCATE …_rdf_stats;
      INSERT INTO …_rdf_stats (predicate_uuid, object_uuid, row_count)
      SELECT predicate_uuid, object_uuid, COUNT(*) FROM …_rdf_quad
      GROUP BY predicate_uuid, object_uuid HAVING COUNT(*) <= 200000;

  → `INSERT 0 16644422`, no error. That is the state the space is in now.

* **The quad table is NOT partitioned** (`relkind='r'`, no children) and
  `enable_partitionwise_aggregate` is `off`, so the obvious explanation — a
  per-partition aggregate emitted without a final merge — is ruled out.

* **It is new to this machine today.** Parallel query did not work on this stack
  at all until `issues/102` was fixed this morning (Docker's 64 MB `/dev/shm`).
  Every stats resync before that ran serially by force. So this path has never
  executed with workers here, and the largest space is the first to provoke a
  parallel plan.

## What is NOT established

**Which statement raises it.** `sync_stats_tables` has three inserts into
`rdf_stats`: the full rebuild after a TRUNCATE (no `ON CONFLICT`, and the one
reproduced serially above), and two per-predicate forms that DO carry
`ON CONFLICT … DO UPDATE`. A conflicting row arriving through an `ON CONFLICT`
insert would raise "cannot affect row a second time", not a plain unique
violation — so the full rebuild is the likely one, and that contradicts it
succeeding when run by hand. The difference between those two runs has not been
isolated.

Capturing it needs the resync re-run against a space whose `rdf_stats` is empty,
with the traceback kept. Once the table is populated the repair script correctly
finds nothing to do and the failure stops reproducing, which is how the
opportunity was lost the first time.

## Why it matters beyond one load

The load reports failure and exits, but **the quads are already committed**. What
is left is a space with 50M quads and a stats table holding 136 rows — which no
check would catch, and which makes every consumer of `rdf_stats` silently wrong
rather than absent: the criterion gate reads pairs as unmeasured, the traversal
direction gate cannot price a constrained end, and the semi-join gate loses its
selectivity input. That is `issues/081` and `issues/099` in a third form — a
fixture that answers plausibly from a degraded configuration.

`rdf_value_stats` was also left at 0 and needed
`scripts/repair_derived_tables.py`, which is the documented recovery and worked.

## What to do

1. Reproduce with the traceback, on a space whose `rdf_stats` has been truncated.
2. If it is the full rebuild, get the plan: `EXPLAIN` the INSERT with workers
   enabled and look for an aggregate above a `Gather` that is not finalised.
3. Either way the load should not report success-then-failure with the quads
   committed and the stats empty — a resync failure needs to leave a mark the
   next reader trips over, the way `issues/099`'s guard does.

## Related

- `issues/102` — parallel query was impossible on this stack until today, which
  is why this had never been reached
- `issues/081` — a benchmark measured against a configuration nobody recorded
- `issues/041` — derived tables going stale, the same class of silent degradation
