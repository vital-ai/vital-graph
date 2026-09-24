# The Request Pool Has No Bulkhead, No Fan-Out Bound, And Is Sized Above The Box

## Status: OPEN — three structural gaps behind `issues/229` and `issues/230`,
## each measured, none fixed. Those two issues fixed the symptoms they surfaced
## as; this is the substrate they both stand on, and it will produce the next
## one in a different disguise.

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

## Order of work, most value first

1. **Split INTERNAL off first** — a dedicated pool of 2-3 connections for
   ANALYZE, VACUUM, backfill, segmentation and auto-sync, and route the 56
   `create_task`/`to_thread` spawn sites at it. Smallest change, prevents the
   outage mode outright, and does not require agreeing on sizing or on how
   QUERY and MUTATION should divide what is left.
2. **Bound the database fan-out** — a semaphore per request, sized well under
   the pool, on the `gather` sites above.
3. **Then split QUERY from MUTATION**, with a reserved floor for QUERY that
   MUTATION cannot borrow, and explicit classification per route rather than by
   HTTP verb.
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
  * Whether any fan-out site other than the three named above is reachable with
    a caller-controlled list length. 19 sites were counted; three were read.
  * Whether `command_timeout=60` on the pool and `statement_timeout=60` on the
    server interact badly — two 60s limits on the same statement, from
    different layers.
  * How many of the 56 background spawn sites actually touch the database.
    They were counted, not read. The number bounds the work of routing them
    at an INTERNAL pool; it does not describe it.
  * Whether a reserved QUERY floor is achievable with separate asyncpg pools
    or needs a shared limiter above them. Separate pools give isolation but
    partition the budget statically; a limiter can lend capacity back when a
    class is idle. Which is right here is not established.

## Reproduce

Saturate the pool and watch what waits:

    SELECT state, wait_event_type, wait_event, count(*)
      FROM pg_stat_activity WHERE datname=current_database()
     GROUP BY 1,2,3 ORDER BY 4 DESC;

    SELECT l.mode, c.relname, l.granted, count(*)
      FROM pg_locks l JOIN pg_stat_activity a ON a.pid=l.pid
      JOIN pg_class c ON c.oid=l.relation
     WHERE a.datname=current_database() GROUP BY 1,2,3;
