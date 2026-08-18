# The Stats Resync Fails With a Duplicate Key on a Large Space

## Status: FIXED 2026-08-18 — two concurrent rebuilds, serialised by an advisory lock

The mechanism is concurrency, not parallelism, and it is SELF-TRIGGERING.

`resync_stats_tables` is a TRUNCATE followed by an INSERT that takes minutes on a
large space. `maintenance_job._audit_stats`, running in the app container, samples
the largest recorded pairs and rebuilds any space whose counts disagree with the
quad table. Mid-rebuild they always disagree — the TRUNCATE is what makes them
disagree — so a load's own resync invites the maintenance job to start a
competing one, and the second INSERT meets rows the first has already written.

That accounts for every observation: the differing key each run (whichever row
the two collided on), why only the 50M-quad space showed it (a seconds-long
window on smaller spaces never overlaps), and why running the statement by hand
always worked (nothing else was rebuilding at that moment).

**Both earlier hypotheses were wrong and are struck through below.** Parallelism
is not involved: the same statement with `max_parallel_workers_per_gather = 2`
succeeds. The clue that broke it open was a row count that CHANGED between two
runs minutes apart — 16,644,422 then 16,644,597 — which meant something else was
writing.

### The fix

A per-space advisory lock (`pg_advisory_lock(hashtext('vitalgraph.stats.<space>'))`)
around the whole rebuild. It BLOCKS rather than skipping: skipping would return
while another rebuild is in flight, and that rebuild may have started before this
caller's writes landed, leaving stats silently stale rather than merely late.
Waiting costs one redundant rebuild and is always correct.

Verified both ways on `sp_graph_forms_20k`, three concurrent resyncs:

    without the lock   A FAILED, B ok, C FAILED   (the exact duplicate key)
    with the lock      15.9s / 29.4s / 41.2s, all ok, identical 1,488,108 rows

### Still worth doing separately

The load reports failure with the quads already committed and the stats table
empty. Nothing checks for that, so the space stays silently degraded — which is
how this was noticed at all. A resync failure should leave a mark the next reader
trips over.

### Superseded reasoning, kept because it was wrong in a useful way

Loading `sp_lead_synth_100k` (50,436,200 quads, 10,467,403 terms) on 2026-08-17
completed its COPY and index rebuild, then died in the auxiliary resync:

    asyncpg.exceptions.UniqueViolationError: duplicate key value violates
    unique constraint "sp_lead_synth_100k_rdf_stats_pkey"
    DETAIL: Key (predicate_uuid, object_uuid)=(10aad51f-…, 0f363ae5-…) already exists

`scripts/repair_stats_tables.py --space sp_lead_synth_100k` reproduces it, and
**the reported key is DIFFERENT every time** — three runs, three pairs. That is
what makes it look like a plan-level effect rather than bad data.

#### What was established at the time

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

#### What was not established at the time

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
