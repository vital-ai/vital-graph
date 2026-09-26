# The Request Pool Has No Bulkhead, No Fan-Out Bound, And Is Sized Above The Box

## Status: IN PROGRESS — steps 1 and 2 landed 2026-09-24 with tests; steps 3-5
## open. The bulkhead now exists and the outage path (ANALYZE on request
## connections) is closed; sizing and the QUERY/MUTATION split are not.

## Why this exists

Two production incidents in one day, both during a bulk archive copy, both
traced to the same underlying shape: the application can submit far more
concurrent database work than the database can usefully execute, and nothing
stands between request serving and background work.

  * `issues/229` — a saturated pool made an entity-graph read return FEWER
    entities with HTTP 200 and no error. 113 of 500 entities vanished from a
    copy that reported complete success.
  * `issues/230` — six `ANALYZE "{space}_term"` stacked on a self-conflicting
    lock, each holding a pooled connection, exhausted the pool. Production
    stopped answering. Ordinary query latency went from 0.22s to over 50s.

Both are now fixed as written. Neither fix prevents the next instance of this,
because neither touches the pool.

## The configuration, measured 2026-09-24

    RDS instance           db.r6g.xlarge — 4 vCPU, 32 GB
    shared_buffers         1,007,546 blocks (~7.7 GB)
    max_connections        3,463
    autovacuum_max_workers 3
    statement_timeout      60s      lock_timeout            10s
    idle_in_txn_timeout    60s      pool acquire timeout    15s

    app pool               min 10 / max 30 PER TASK
    prod tasks             2 (`vitalgraph-service`), plus 1 test task
    therefore              up to 90 connections against a 4-vCPU box

## 1. Maintenance shares the request pool — no bulkhead

The clearest breach, and the one that caused the outage. ANALYZE runs on
POOLED REQUEST CONNECTIONS. When six of them stacked on
`ShareUpdateExclusiveLock` — a mode that conflicts with itself — they held six
connections for the duration and user queries could not get one.

Standard practice is bulkhead isolation: long-running maintenance gets its own
small dedicated pool so it CANNOT starve request serving, however badly it
behaves. `issues/230` stops the pile-up forming; it does not stop maintenance
competing with requests for the same 30 connections.

A detail worth keeping, because it cost time during the incident: KILLING THE
CLIENT DID NOT STOP THE WORK. `auto_analyze` runs ANALYZE on separate
background connections, so the queued statements outlived the process that
scheduled them and had to be `pg_cancel_backend`ed by hand.

## 2. Per-request fan-out is unbounded

    19  asyncio.gather sites across vitalgraph/endpoint and vitalgraph/kg_impl
     1  asyncio.Semaphore in the whole codebase — `_VECTOR_CONCURRENCY`,
        and that bounds provider HTTP calls, not database work

    gather(*[_delete_one(u)   for u in uris])         # kgentities_endpoint
    gather(*[_fetch_quads(i)  for i in identifiers])  # kgentities_endpoint
    gather(*[_fetch_frame(u)  for u in frame_uris])   # kgframes_endpoint

Each of these opens one transaction per URI THE CALLER SUPPLIED. A client
passing 500 URIs opens 500 concurrent transactions against a pool of 30. One
request can therefore monopolise the pool, which is `issues/229` seen from the
other side — and it is how `--batch 10` in a migration script became 100
concurrent server-side deletes rather than 10.

The codebase already knows this pattern. It is applied to the embedding
provider and to nothing else.

## 3. The pool is sized above what the instance can use

The long-standing guidance — PostgreSQL wiki, HikariCP — is roughly
`cores * 2 + effective_spindles`, so about 8-10 CONCURRENTLY ACTIVE connections
for 4 vCPU. Past that, more connections buy context switching and lock
contention rather than throughput.

30 per task across 3 tasks is up to 90. `max_connections: 3463` is not
headroom here, it is an invitation: it is the RDS default for the instance
class and says nothing about how much concurrent work the box can do. The pool
is not protecting the database — it is letting the application queue work
inside PostgreSQL, where it is expensive, instead of outside it, where it is
cheap.

This is the substrate under both incidents. Neither would have been possible at
a pool of 10.

## 4. Exhaustion has no backpressure

The acquire timeout is 15s. On exhaustion a request waits, then fails. There is
no 503, no shed load, no signal to the caller that the system is saturated
rather than broken. `issues/229` made the RESULT of that visible; the behaviour
is unchanged.

## 5. Bulk work has no read isolation

MultiAZ, so the standby is not readable. A migration's reads compete with live
writes on the same instance — the archive copy's entity-graph reads were a
large fraction of the load that preceded the first incident. A read replica
would remove that interference entirely, for migrations and for analytics.

## The model this should move to

Today there is ONE asyncpg pool (`self.connection_pool`), shared by every
caller, and NO read/write distinction at acquire time — the single `readonly`
in the tree is a transaction property in `bulk_export`, not a pool. Everything
below is a description of what does not exist yet.

Three classes of work reach PostgreSQL, and they want different guarantees:

    QUERY      read-only, request-driven, latency-sensitive. The thing users
               notice. Must never be starved.
    MUTATION   request-driven writes. Bursty, holds locks, triggers derived-
               table maintenance.
    INTERNAL   background: ANALYZE, VACUUM, backfill, segmentation, auto-sync.
               Can always be deferred. Nothing waits on it interactively.

**Each class gets its own pool.** A class that misbehaves then exhausts only its
own share. That is precisely what was missing on 2026-09-24: ANALYZE (INTERNAL)
consumed the connections QUERY needed, and a bulk copy (MUTATION) did it again
an hour later. With separate pools neither incident reaches a reader.

**Requests stay async end to end.** A request awaiting a connection must never
occupy a worker; N concurrent requests is a number the service chooses, not a
number the pool imposes by blocking.

**Queue in the application, not in PostgreSQL.** This is the point of the whole
exercise. Work queued in the app is cheap, observable, cancellable and
sheddable. Work queued inside PostgreSQL holds a connection, may hold locks,
and is invisible until someone samples `pg_stat_activity`. Admission control
belongs at the edge — bound the in-flight count per class and reject or defer
beyond it — so saturation shows up as a 503 on one class rather than as a
database-wide stall.

**Reads get a reserved floor that the other classes cannot borrow.** A shared
pool with priorities degrades to starvation under sustained write load, because
writes hold connections longer. The floor has to be a partition, not a hint.

**INTERNAL skips rather than queues.** Already true of ANALYZE after
`issues/230`; it should be the rule for every background job. A deferred
ANALYZE costs stale statistics. A queued one costs a connection.

### Two things that make this harder than it looks

**Sizing is GLOBAL, not per task.** The database sees the sum across every task
and every class. Three tasks with 8+4+2 each is 42 connections against a box
whose useful concurrency is ~8-10 — partitioning by class fixes isolation and
does nothing for total load unless the per-task numbers come down as the number
of classes goes up. Per-task pools multiply; the limit does not.

**Classification must be EXPLICIT, never inferred from the HTTP verb.** A
SPARQL update arrives as a POST, and so does a read-only SPARQL query
(`/api/graphs/sparql/query` accepts POST). Routing on method would put updates
in the QUERY pool and destroy the guarantee it exists to provide. The route, or
the parsed operation, has to say.

**And a request can become INTERNAL work after it returns.** There are 56
`create_task`/`to_thread` sites across `endpoint/`, `vectorization/` and
`document/` — auto-sync, segmentation, analyze. Each is a request spawning
background database work, and today every one of them lands in the request
pool. That is the leak that turned a copy into an outage: the write finished,
returned 200, and its consequences kept running on connections readers needed.
Those spawns must take an INTERNAL connection, or the separation is cosmetic.

## Decided: separate pools, and the measurement that would overturn it

SEPARATE POOLS PER CLASS, not a shared limiter. Decided 2026-09-24 on
manageability: a pool per class is a static, legible thing — its size is a
number in config, its exhaustion is attributable to one class, and it cannot
lend a reader's connection to a bulk writer by accident. A limiter that lends
capacity back is strictly more capable and strictly harder to reason about
under exactly the conditions where reasoning matters.

The cost of that choice is real and known: the budget is partitioned
statically, so QUERY can wait while MUTATION and INTERNAL sit idle. That is
the trade being accepted, not overlooked.

**The decision is revisitable, and the metric that would revisit it is one
number**: how much of QUERY's wait time happened while the other classes had
free connections. If QUERY only ever waits when the whole database is busy, a
limiter would have had nothing to lend and static partitioning costs nothing.
If QUERY waits while INTERNAL sits on idle connections, the partition is the
problem and the limiter earns its complexity.

So the logging has to capture the classes TOGETHER, at the same instant.
Per-pool metrics gathered independently cannot answer it — knowing QUERY waited
12s and, separately, that INTERNAL averaged 30% utilisation, says nothing about
whether they overlapped.

### What to log

On every acquire that WAITS (not on every acquire — the fast path must stay
free), one record:

    ts, class, waited_ms, this_pool_in_use, this_pool_size,
    other_classes_idle   -- sum of (size - in_use) across the OTHER pools,
                         -- sampled at the moment the wait began

and periodically, one sample of all pools at once for a utilisation baseline.

`other_classes_idle` is the whole point. It is the capacity a limiter could
have lent, and it is only meaningful if read at the instant of the wait.

### What the analysis answers

    share of QUERY wait-time with other_classes_idle > 0     -> limiter upside
    p99 QUERY waited_ms                                      -> is it hurting
    count of waits with other_classes_idle == 0              -> genuinely full

Near-zero upside means keep the pools and close this. A large share means the
sizes are wrong first — retune them, and only then consider the limiter, since
a badly partitioned budget looks exactly like a missing limiter.

## Landed 2026-09-24

**Step 1 — INTERNAL split. DONE.** A dedicated pool (`internal_pool`, max 3,
`internal_pool_size`) created, registered and closed alongside the request pool.
Routed at it so far: the three `maybe_analyze` sites in
`add_rdf_quads_batch_bulk` / `remove_rdf_quads_batch_bulk` /
`delete_entity_graph_bulk` — THE EXACT STATEMENTS THAT STACKED SIX DEEP ON
2026-09-24 — plus `_maybe_analyze_aux_tables` (both its catalog probe and its
ANALYZE fallback) and `auto_sync._run_sync`. `db_impl._internal_pool` is the
accessor; it falls back to the request pool when absent, so an impl without the
split degrades to today's behaviour rather than failing the write path.

**The wait record. DONE.** `pool_wait` is emitted on acquires that WAIT only —
never on the fast path — carrying `class`, `waited_ms`, `in_use`, `size` and
`other_classes_idle`, the last read BEFORE the wait begins. Read afterwards it
would describe the world at the moment the wait ENDED, by which time the
sibling capacity that would have answered the question has usually been handed
over; that ordering is pinned by a test.

**The mixed pool is `REQUEST`, not `QUERY`.** It still serves reads and writes.
Labelling it QUERY would file every mutation's wait as a reader's wait and the
analysis would report reader starvation that is really writers queueing behind
each other — the wrong fix, from data that looks authoritative. It becomes
QUERY when step 3 genuinely splits it.

**Step 2 — fan-out bound. DONE.** `vitalgraph/utils/bounded_gather.py`,
default 8, applied to five sites:

    kgentities_endpoint   _fetch_quads over `identifiers`   caller list
    kgentities_endpoint   _delete_one  over `uris`          caller list
    kgframes_endpoint     _fetch_frame over `frame_uris`    caller list
    kgentity_list_impl    _fetch       over a page          caller page_size
    kgentity_list_impl    _fetch_entity_graph over a page   caller page_size

The last two were nearly missed. They fan out over QUERY RESULTS rather than a
caller-supplied list, which reads as safe — but `page_size` is a request
parameter and goes straight into the `LIMIT`, so the width is caller-controlled
after all, just one step removed. "Bounded by the page size" is not a bound
when the caller picks the page size.

`bounded_gather` takes FACTORIES rather than coroutines, so nothing is
constructed until a slot is free — `gather(*[f(x) for x in xs])` has already
created every coroutine before any semaphore is consulted.

### Tests

    tests/unit/test_pool_classes_and_wait_record.py        the accounting
    tests/unit/test_background_work_uses_the_internal_pool.py   the routing
    tests/unit/test_bounded_gather.py                      the ceiling
    tests/load/test_query_is_not_starved_by_internal.py    the behaviour

The load test is the one that matters, and it carries a CONTROL: it first
proves it can starve a SHARED pool, because a harness that cannot reproduce the
failure cannot demonstrate its absence. Measured locally, 5 runs, min/med/max
across runs:

    shared pool, one reader waited          1354 / 1360 / 1374 ms
    separate pools, INTERNAL saturated:
      per-run median read latency              1.1 /  1.1 /  2.3 ms
      per-run worst read                       6.0 / 10.8 / 19.4 ms
    separate pools, INTERNAL + MUTATION both saturated:
      per-run worst read                       4.0 /  5.9 / 11.6 ms

Roughly a 600x difference in the worst case and 1000x at the median, and the
spread across runs is small enough that it is the partition doing it rather
than scheduling luck.

It also asserts that QUERY's OWN exhaustion is still logged — isolation must
not be bought by making saturation invisible, which is how `issues/229`
produced a quiet wrong answer.

## Measured 2026-09-25: the bulkhead is INSURANCE, not a speed-up

Run end to end against the local test stack (`test_scripts/perf/pool_bulkhead_ab.sh`),
same image both arms, `DB_INTERNAL_POOL_SIZE=0` as the control:

    CAPACITY-MATCHED, total 7 connections, 10 concurrent writers
                              p50 (min/med/max)     p99 (min/med/max)
    control    pool 7 + 0      43 / 46 /  70 ms     432 /  434 /  699 ms
    treatment  pool 5 + 2      47 / 48 /  98 ms     467 /  766 / 1848 ms

**No benefit at equal capacity.** An earlier UNMATCHED comparison (pool 5 + 0
against pool 5 + 2) showed the treatment winning every run — p50 136 ms down to
42 ms at the median — and that was entirely the two EXTRA connections the
internal pool adds, not isolation. Capacity-matching removes the effect
completely. Anyone re-running this must match the total, or the internal pool
will look like a latency fix.

**`pool_wait` was 0 in every arm**, at a 0.05 s threshold, with a 5-connection
pool and twice that many concurrent writers. That is not missing
instrumentation — the threshold was verified inside the container. Connections
were never the scarce resource: `docker stats` through the load shows PostgreSQL
at up to 300% CPU while the app stays under 100%. Entity writes release their
connection quickly and saturate PG cores instead.

So this workload cannot exercise the bulkhead at all, and partitioning a
resource nobody queues for cannot help. **The failure mode the bulkhead exists
for is work that HOLDS a connection** — the six stacked `ANALYZE` of
`issues/230`, each holding one for the duration — and `create_kgentities` does
not produce that shape however much of it you run.

What this changes:

  * The bulkhead's justification is preventing a specific outage mode, NOT
    throughput or latency. It should not be sold as a performance change.
  * **DECIDED AND IMPLEMENTED 2026-09-25: `internal_pool_size` is CARVED OUT of
    `max_pool_size`, not added to it.** `max_pool_size` is now the whole budget
    for a task across both classes — request = max - internal, total = max — so
    turning the bulkhead on no longer quietly raises the number the database
    sees. It also makes the A/B capacity-matched by construction, so the false
    win cannot reappear: `tests/unit/test_internal_pool_budget_carve_out.py`
    pins the arithmetic, the clamp and the log.
  * The isolation proof is `tests/load/test_query_is_not_starved_by_internal.py`,
    which saturates connections deliberately with `pg_sleep` and carries a
    control proving it can starve a shared pool. That result stands: 1354-1374 ms
    shared against 1.1-2.3 ms median separated.
  * `tests/api/test_query_latency_under_write_load.py` is a REGRESSION GUARD —
    real write load, reads staying correct and interactive — not a bulkhead
    proof. Described that way to stop it being cited as one.

Two harness lessons worth keeping, because both produced confident wrong
results before they were found:

  * **`up -d --wait` is not readiness.** The healthcheck goes green before a
    5.5 s startup warm-up over 141 spaces; a login inside that window fails with
    a bare `ReadError`.
  * **The first run after recreating the container is cold** and is not
    comparable to anything. Identical configuration, back to back: `n=5
    p99=15114 ms` cold against `n=149 p99=454 ms` warm, a 33x spread. The script
    now discards a warm-up run per arm.

## A connection leak on the transaction path — recorded 2026-09-26, NOT fixed

`_SparqlSQLCoreAdapter.create_transaction` (`sparql_sql_space_impl.py:485`) is
five lines with no error handling:

    pool = self._impl._db._pool
    conn = await pool.acquire()
    tr = conn.transaction()
    await tr.start()                  # <-- raises here and `conn` is gone
    return _SparqlSQLTransaction(conn, tr, pool)

**If `tr.start()` fails after `acquire()` succeeded, the connection is never
released.** It leaks for the life of the process — 1/30th of the budget per
occurrence, permanently, and there is no bulkhead to contain it. `issues/229` is
what the resulting exhaustion looks like from outside: fewer results, HTTP 200,
no error. That is the whole reason this belongs here and not in a general
tidy-up: the leak is silent, cumulative, and its symptom is a WRONG ANSWER
rather than a failure.

`SparqlSQLDbImpl.begin_transaction` (`sparql_sql_db_impl.py:435`) already does
it correctly, in the same file tree, and is the model:

    except Exception as e:
        logger.error(...)
        if connection is not None:
            await self._pool.release(connection)
        raise

It also calls `track_connection()` (`utils/resource_manager.py:212`), which the
adapter path does not. That helper IS still live and this backend DOES use it —
at `sparql_sql_db_impl.py:445`, just not on this path — so a transaction opened
through the adapter is invisible to whatever that tracking serves. Two gaps, one
cause: the adapter was written from the archived shape without its error
handling.

Left unfixed deliberately, and sequenced with this issue rather than ahead of
it, because it is pool behaviour and the fix should land with the class split
rather than as a drive-by — `create_transaction` is a MUTATION-class acquire and
which pool it should use is decided by step 3, not now. The difference is also
recorded at the call site in the adapter's own docstring, so it cannot be lost if
this issue is read selectively.

Cheap to fix when its turn comes: wrap in try/except, release on failure, add
`track_connection`. The reason to wait is sequencing, not difficulty.

## TO BE INVESTIGATED AND RESOLVED: what the stalled reads are actually waiting on

**Open. This is the question that decides how much of this issue is worth
doing, and it is not answered.**

### The retraction

Four multi-second stalls were observed on a LIVE space during a bulk delete on
2026-09-26 — 26s, 47s, 10s, 34s, with ordinary reads at 0.05-0.50s in between.
They were attributed, in the moment, to the `ANALYZE` threshold tripping.

**That attribution is wrong and is withdrawn.** `ANALYZE` takes
`ShareUpdateExclusiveLock`, which does NOT conflict with the `ACCESS SHARE` lock
a plain `SELECT` takes. `ANALYZE` does not block readers. It explains the
2026-09-24 OUTAGE — six `ANALYZE` stacked on each OTHER, each holding a pooled
connection, readers unable to acquire one — but it does not explain a single
read stalling for 47 seconds while connections are available.

So the mechanism behind these stalls is currently UNKNOWN, and part of the case
for the remaining work here rested on it.

### What a pool split can and cannot fix

This is the distinction the investigation has to resolve against, because three
different causes produce the same symptom and only one of them is addressed by
anything in this issue.

**Separate pools fix exactly one thing: background work occupying the
connections readers need.** Measured in the outage: six of thirty. A bulkhead
makes that impossible, and that alone justifies step 1.

**They fix none of these:**

  * **Lock conflicts.** Pools allocate connections, not locks. A reader waiting
    on a lock waits exactly as long from a private pool.
  * **PostgreSQL CPU/IO saturation.** If the server is the bottleneck, handing
    the reader a connection sooner just moves its queueing from the application
    into PostgreSQL, where it is more expensive and less visible.
  * **Expensive work per operation.** `issues/238` — the slot-sort delete path
    scans the whole table to remove a handful of rows. 6,810 deletes is 6,810
    full scans, and no pool arrangement makes that cheap.

    **THIS IS THE LEADING HYPOTHESIS, and it is nearly free to test.**
    `issues/238` was FIXED 2026-09-25 but is NOT DEPLOYED to production, so the
    seq scan was live during the 2026-09-26 delete that produced these stalls.
    It was found by production measurement at **59.6 hours across 647,255
    calls, on the write path, inside the entity lock** — which is exactly the
    shape that would stall an unrelated reader through IO and CPU rather than
    through locks or connections. Before instrumenting anything here, deploy it
    and re-run the same bulk delete: if the stalls disappear, this issue's
    remaining scope shrinks to the outage mode alone.

### The evidence so far points AWAY from connections

From the local A/B (`test_scripts/perf/pool_bulkhead_ab.sh`):

    pool_wait records, 0.05s threshold, 5-connection pool, 2x writers:  0
    docker stats through the load: PostgreSQL up to 300% CPU, app under 100%

Connections were not scarce; server capacity was. Sub-second queueing is
excluded as an explanation because the threshold was lowered to 0.05s and
verified inside the container. **If production behaves the same way, the split
will not touch these stalls** — it will still close the outage mode, which is a
different and real failure, but it should not be sold as the fix for what was
observed on 2026-09-26.

### The measurement that settles it

One sample of `pg_stat_activity` taken DURING a stall, not after:

    SELECT pid, state, wait_event_type, wait_event, now() - query_start AS age,
           left(query, 120)
      FROM pg_stat_activity
     WHERE datname = current_database() AND state <> 'idle'
     ORDER BY age DESC;

and, at the same instant, the application's pool occupancy (`pool_wait` records,
or `log_pool_state`). Three outcomes, three different conclusions:

    wait_event_type = 'Lock'        -> the bulkhead is IRRELEVANT here; find the
                                       lock holder and the conflicting mode
    wait_event_type = 'IO' / CPU    -> capacity problem; `issues/238` (already
                                       fixed, awaiting deploy) and a read
                                       replica are the levers, not pools
    waiting on acquire(), pool full -> the bulkhead fixes it directly, and step 3
                                       gets its strongest evidence

Catching it in flight is the hard part: stalls were intermittent and irregular —
two of them 20 minutes apart, then 26 minutes with none, so there is no reliable
period to sample against. A watchdog that samples `pg_stat_activity` on
detecting a slow read, rather than on a timer, is the way to get it; the latency
probe that found these stalls already exists and would only need the sample
bolted onto its breach path.

Note also that the space this was observed against is now empty, so reproducing
it means running a bulk operation deliberately rather than waiting for one.

### Why this blocks sequencing rather than just being interesting

Step 3 (the QUERY/MUTATION split) is the largest remaining piece of work in this
issue. If the stalls are lock- or capacity-bound, step 3 buys isolation against
a failure mode that has been measured ONCE (2026-09-24) and nothing against the
one seen most recently — which would argue for DEPLOYING `issues/238` and doing
step 5 first. Resolve this before committing to that order.

The cheapest possible next action, which costs no new code: deploy `issues/238`,
re-run the bulk delete, and see whether the stalls survive. That is a better
first experiment than any instrumentation, because a negative result removes the
question entirely.

## Order of work, most value first

1. ~~**Split INTERNAL off first**~~ — a dedicated pool of 2-3 connections for
   ANALYZE, VACUUM, backfill, segmentation and auto-sync, and route the 56
   `create_task`/`to_thread` spawn sites at it. Smallest change, prevents the
   outage mode outright, and does not require agreeing on sizing or on how
   QUERY and MUTATION should divide what is left.
2. ~~**Bound the database fan-out**~~ — DONE, see above.
3. **Then split QUERY from MUTATION**, with a reserved floor for QUERY that
   MUTATION cannot borrow, and explicit classification per route rather than by
   HTTP verb. Separate pools, per the decision above — and land the wait
   logging WITH them, not after, or the data needed to revisit the decision is
   never collected.
4. **Reduce the GLOBAL connection budget to ~10-15 across all tasks and classes,
   and measure.** Expected to be counter-intuitive: smaller pools usually raise
   throughput under contention. Must be measured, not assumed — and it is the
   sum that matters, not the per-pool number.
5. **A read replica** for migrations and analytics, which also gives QUERY
   somewhere to go that MUTATION cannot reach at all.

## Not established

  * Whether 10-15 is the right pool size HERE. The guidance is generic; the
    workload is not. Wants an A/B under a realistic mixed load before changing
    production.
  * Whether the three ECS tasks ever run hot simultaneously. 90 connections is
    the ceiling, not an observation — the steady-state sample during a quiet
    period showed 17 idle and 1 active.
  * Whether any fan-out site other than the three now bounded is reachable with
    a caller-controlled list length. The page-driven ones
    (`kgentity_list_impl`, `kg_sparql_query`) fan out over query results, but
    the page SIZE is caller-supplied, so a large `limit` reaches them. Not yet
    bounded; wants the limit checked against what the endpoints actually cap.
  * Whether `command_timeout=60` on the pool and `statement_timeout=60` on the
    server interact badly — two 60s limits on the same statement, from
    different layers.
  * How many of the 56 background spawn sites actually touch the database.
    They were counted, not read. Three ANALYZE paths and auto-sync are now
    routed at INTERNAL; the rest are unexamined, and any one of them that
    takes a request connection reopens the same hole.
  * Whether `internal_pool_size: 3` is right. It is a guess chosen to be small
    enough that INTERNAL cannot matter and large enough that ANALYZE, VACUUM
    and auto-sync do not serialise behind each other. It no longer adds to the
    global budget (carved out, above), so the open question is narrower: 3 of 30
    is 10% of request capacity permanently reserved for work that is by
    definition deferrable, and whether that is the right price is unmeasured.

## Reproduce

Saturate the pool and watch what waits:

    SELECT state, wait_event_type, wait_event, count(*)
      FROM pg_stat_activity WHERE datname=current_database()
     GROUP BY 1,2,3 ORDER BY 4 DESC;

    SELECT l.mode, c.relname, l.granted, count(*)
      FROM pg_locks l JOIN pg_stat_activity a ON a.pid=l.pid
      JOIN pg_class c ON c.oid=l.relation
     WHERE a.datname=current_database() GROUP BY 1,2,3;
