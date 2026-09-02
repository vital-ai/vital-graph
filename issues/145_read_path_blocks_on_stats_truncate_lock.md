# Reads Block 10s at a Time on a TRUNCATE Lock the Maintenance Job Holds

## Status: OPEN — this is the P1. Measured end-to-end against prod 2026-09-02.

## The single measurement that identifies it

A user loaded the last page of an entity listing and reported ~16s. The
application's own timing for that request:

    19:14:03.734  LIST_ENTITIES timing: setup=0ms query=21980ms
    19:14:03.737  GET /api/graphs/kgentities?...&page_size=25&offset=76675

The SQL that request ran, from the Postgres log, same second:

    19:14:03  pid=4666   1851 ms   ... ORDER BY s0.v1 DESC, s0.v0 LIMIT 25 OFFSET 76675

**21,980 ms reported. 1,851 ms of SQL.** The other ~20 seconds is in the
application log, twice, seconds before the query ran:

    19:14:01.761  generator._load_missing_pair_stats - WARNING -
                  semijoin gate: pair stats lookup failed, plan will be chosen ...
                  asyncpg.exceptions.LockNotAvailableError:
                  canceling statement due to lock timeout
    19:14:01.762  semijoin.mark_semijoins - INFO - semijoin: no join rewritten
    19:14:01.814  (the same failure again)

`lock_timeout` on prod is **10000 ms**. Two lookups, each blocking the full ten
seconds and then failing:

    10,000 + 10,000 + 1,851  =  21,851 ms      reported: 21,980 ms

## The mechanism

`_load_missing_pair_stats` (`generator.py:713`) reads `{space}_rdf_stats` on the
READ path to feed the semi-join gate. `_resync_stats_locked` rebuilt that same
table with:

    async with conn.transaction():
        await conn.execute(f"TRUNCATE {t_stats}")
        await conn.execute(f"INSERT INTO {t_stats} ... SELECT ... FROM {t_quad} "
                           f"GROUP BY predicate_uuid, object_uuid ...")

`TRUNCATE` takes an **AccessExclusiveLock**, held until the surrounding
transaction commits — so for the whole duration of that aggregate. It conflicts
with everything, including merely *preparing* a statement against the table,
which is exactly where asyncpg failed (`_get_statement` → `protocol.prepare`).

The function's own docstring describes the scan it holds the lock across:

> This is a TRUNCATE followed by an INSERT that **takes minutes on a large
> space**.

Measured over a 46-minute window, stats sync accounted for 274.7s across 96
statements over one second, with a single statement at 33.1s (`issues/143`), on
a cycle that repeats every 300s.

**Note on a nearby comment, to save the next reader the detour I took.**
`prune_stats_tables` carries a docstring saying "the expensive part runs
concurrently with readers; only the TRUNCATE and the re-insert of a few thousand
rows hold one, and both are fast." That is **correct, and it is about prune** —
which stages its keepers into a temp table before truncating. It is not a
dismissal of this bug; the resync simply never had the equivalent staging. The
fix below gives it the same shape.

## Why this is the P1 and the earlier diagnoses were not

It explains every symptom that survived the previous fixes:

* **Intermittent.** Only requests overlapping the lock window pay. Maintenance
  occupies ~38% of wall-clock (`issues/143`), which matches an error rate that
  is high but far from total.
* **Unaffected by the instance resize.** `db.r6g.xlarge` cannot help a request
  that is asleep waiting on a lock. This is why that change did not move the
  timeouts, and the resize should be judged on other grounds.
* **Fast when run by hand.** Replaying the identical SQL from psql gives
  1.4-1.9s. The lock is not held at that moment, so the wait never happens. This
  is the 11,000x "same query, wildly different time" gap that earlier notes
  attributed to cached plans in worker processes. It was never plan caching.
* **60s statement timeouts.** 20s of lock waiting, plus a plan chosen without
  pair stats (`semijoin: no join rewritten`), plus a cache the maintenance scans
  have just evicted, is how a 1.9s query reaches 60s.
* **Silent.** The failure is caught and the query proceeds with a worse plan.
  Nothing surfaced until the `issues/140` handler was raised to WARNING with
  `exc_info=True` — that change is what made this diagnosable, and this is the
  first incident it has paid for.

## Two fixes, independent, both small

**1. Do not block on an optional lookup.** These reads are *optimisation
inputs*. Waiting 10 seconds to maybe improve a plan is never the right trade;
failing in 100ms and planning without it costs a worse plan, which is what
happens after 10s anyway. `db_provider.execute_query` grew a `lock_timeout_ms`
argument (`STATS_LOCK_TIMEOUT_MS = 100`), applied at **five** read sites:

    generator._load_quad_stats            pred_stats and quad_stats loads
    generator._load_missing_pair_stats    the site in the incident traceback
    generator                             the IN-selectivity lookup
    slot_type_tautology.excludes_nothing  100 of 144 blocked samples on prod

This alone converts a 22s request into a ~2s request. It does not fix the
underlying contention, and it should not wait for the fix that does.

*Not `SET LOCAL`.* `sparql_sql_space_impl.create_transaction()` hands callers a
connection with a transaction already open; asyncpg nests as a savepoint, and
SET LOCAL survives a savepoint RELEASE to the end of the OUTER transaction —
silently imposing 100ms on the caller's remaining statements. The implementation
saves and restores the previous value instead, which is correct either way.

**1b. A precondition, not a tidy-up: do not cache a transient failure.**
`_load_quad_stats` memoised `({}, {})` on ANY exception, so one unlucky lock
window would plan every later query for that space without stats until something
invalidated the cache — and it logged at DEBUG. Lowering the timeout makes that
window likelier to be hit, so the distinction between "absent" and "failed"
had to land with it. Absent still caches; transient now warns and does not.

**2. Aggregate before truncating, not inside the lock.** Locks are taken when a
statement runs, not when its transaction opens, so staging into `ON COMMIT DROP`
temp tables *first* keeps the rebuild in one transaction — preserving the
atomicity `issues/103` is about — while the exclusive lock covers only the
TRUNCATE and a bulk insert from an already-computed table:

    BEGIN;
      CREATE TEMP TABLE _new_stats ON COMMIT DROP AS SELECT ... GROUP BY ...;
      TRUNCATE {t_stats};                     -- lock taken HERE, not before
      INSERT INTO {t_stats} SELECT * FROM _new_stats;
    COMMIT;

This is the pattern `prune_stats_tables` already uses.

**Rejected: build-into-`_new`-and-rename.** It drops the lock further, but
`CREATE TABLE (LIKE ... INCLUDING ALL)` gives indexes generated names, so after
one RENAME the *next* rebuild collides on `{t_stats}_new_pkey`; getting it right
means re-deriving index names, and grants, on every cycle. Against a table with
`issues/103`'s corruption history that is the wrong trade for the remaining
milliseconds. Fix 1 covers the residue.

## Relationship to the other open issues

* `issues/143` — maintenance is 38% of DB wall-clock. Same job, different cost
  (cache eviction and CPU rather than locking). Both are "the maintenance job is
  too expensive for this instance", and fixing the cadence helps both.
* `issues/144` — the sort fast-path table is 0.6% populated, so the listing
  query is O(total). Real and worth fixing, but note the last-page SQL is only
  1.9s: it is a second-order cost behind this one. Fix this first, then 144.
* `issues/140` — the WARNING that exposed this. Vindicated.

## Confirmed by direct observation

Sampling `pg_locks` every 2s during a rebuild, after the analysis above:

    19:28:23  AccessExclusiveLock  rdf_stats  1s  INSERT INTO ..._rdf_stats ...
    19:28:30  AccessExclusiveLock  rdf_stats  8s  (same transaction, still held)
    ... continuous through 19:29:21

144 blocked-reader samples accumulated behind it, every one a stats read: 100
were `slot_type_tautology`'s `_rdf_pred_stats` lookup and 44 the pair-stats
loads. The lock holder reported by `pg_stat_activity` is the INSERT, carrying
the lock its TRUNCATE took earlier in the same transaction.

## Verifying

The reported `query=NNms` in `LIST_ENTITIES timing` should stop exceeding the
Postgres-logged duration for the same request by ~10s multiples. A residual gap
that is a clean multiple of `lock_timeout` means another blocking lookup remains.
