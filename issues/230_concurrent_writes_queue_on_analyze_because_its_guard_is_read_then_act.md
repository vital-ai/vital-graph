# Concurrent Writes Queue On ANALYZE Because Its Guard Is Read-Then-Act

## Status: OPEN — root cause established by measurement, no fix attempted. The
## store path already has the mutual exclusion this needs; the other callers of
## `auto_analyze.maybe_analyze` do not use it.

## Summary

Concurrent writes to one space serialise on `ANALYZE {space}_rdf_quad`, which
takes a `ShareUpdateExclusiveLock` — a mode that CONFLICTS WITH ITSELF. The
threshold guard that is supposed to make ANALYZE rare is read-then-act, so a
burst of writers all pass it before any of them finishes, and then queue one at
a time on a table lock.

Found while deleting entity graphs at 100-way concurrency: throughput collapsed
from 14.0 to 1.9 entities/sec WITHIN a single 200-entity run.

## Measured

`pg_stat_activity` and `pg_locks` sampled every 150ms through a 150-entity
delete at 100 effective concurrency, against the local dev database:

    wait events            1,570 samples  Lock | relation        (blocked)
                             425 samples  (running)

    ungranted locks        1,599 samples  ShareUpdateExclusiveLock
                                          on {space}_rdf_quad

    holder of that lock      171 samples  ANALYZE "{space}_rdf_quad"

Nothing else appears. Not `Lock | transactionid` (row locks), not
`Lock | advisory`, and no pool-acquire timeouts — the entity advisory lock is
keyed per entity URI, so distinct entities never contend on it.

From the same run in production, per-entity delete timings:

    min 0.08s   median 1.39s   p90 43.01s   max 102.09s
    1,960s of delete time inside 102s of wall clock

Three facts that together rule out "the work is just big":

  * **The SLOW deletes are SMALLER.** Entities taking >20s averaged 333 quads;
    those under 2s averaged 605. They were waiting, not working.
  * **The slowest queue ~3s apart** — 102.09, 98.97, 95.83, 92.70, 89.55 — which
    is a queue draining, not computation.
  * **Median work is 1.39s.** Everything above it is queue time.

## Why the guard does not hold

`maybe_analyze` fires when a per-space row-change counter crosses
`DEFAULT_ANALYZE_THRESHOLD`, behind two tiers described in
`auto_analyze.py`: a 60s in-process check, and a shared one reading
`pg_stat_user_tables.last_analyze` so the guard survives across workers and ECS
tasks.

Both are READ-THEN-ACT with nothing between the read and the act.
`last_analyze` is only stamped when an ANALYZE COMPLETES, so every writer in a
burst reads the same stale timestamp, every one of them decides to analyse, and
they then serialise on a lock that admits one at a time. The shared tier makes
the guard survive a restart; it does not make it exclusive.

This is the shape of `issues/173` one layer down: N callers read "nobody has
done this yet" before any of them commits.

## The asymmetry, which is the lead

`kg_backend_utils._get_analyze_lock_manager` is documented as "the process lock
manager used to serialise ANALYZE" and is used by `_maybe_analyze_aux_tables` on
the STORE path. Every other caller —
`sparql_sql_space_impl` lines 1599, 1821 and 1944, which cover the delete and
bulk-write paths — calls `auto_analyze.maybe_analyze` directly and takes no such
lock.

So one write path was given mutual exclusion and the others were not. It shows
up exactly where the asymmetry predicts: copying 43,783 entity graphs at
`--parallel 10 --batch 10` runs at a clean 11.2 entities/sec, and DELETING with
identical flags collapses to 1.9 — because the delete endpoint fans out per
entity (`asyncio.gather` over the `uri_list`), turning 10 concurrent requests
into 100 concurrent transactions against one table.

## What a fix has to decide

**Skip, do not queue.** A second caller finding an ANALYZE already in flight
should return immediately. Waiting is strictly worse than not analysing: the
statistics the waiter would produce are the ones the holder is already
producing.

**Where the exclusion lives.** `ProcessLockManager` already exists and is
already used for this on one path, so the smallest change is to route the other
callers through it. Worth confirming it is non-blocking in the "already held"
case rather than a queue by another name.

**Whether the threshold is right at all.** 50,000 row changes is a lot of
writes to buy one ANALYZE, but a bulk migration crosses it repeatedly and every
crossing lands on the same table. Not established whether the fix is exclusion,
a longer minimum interval, or leaving it to autovacuum on bulk paths.

## Not established

  * Whether production shows the same ratio. The lock sampling was done against
    the dev database; the production evidence is the timing distribution above,
    which is consistent with it but does not name the lock.
  * Whether the copy path pays a smaller version of this. It does not fan out,
    so its concurrency is the requested one, and 11.2 entities/sec is the
    measured result — but it crosses the same threshold and takes the same lock.

## Reproduce

Delete entity graphs at high concurrency and sample the catalog:

    SELECT l.mode, c.relname, count(*) FROM pg_locks l
      JOIN pg_stat_activity a ON a.pid = l.pid
      JOIN pg_class c ON c.oid = l.relation
     WHERE NOT l.granted GROUP BY 1,2;

`scripts/delete_kg_entities.py delete --parallel 10 --batch 10` reaches 100
effective concurrency, which is enough.
