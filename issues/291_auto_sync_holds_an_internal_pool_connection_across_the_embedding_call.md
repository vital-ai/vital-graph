# 291 — Auto-sync holds an internal-pool connection across the embedding call

## Status: OPEN 2026-10-20. Found reviewing `issues/290`; not yet measured as a fix.

**Related:** `issues/290` (the symptom: a worker's second acquire timed out),
`issues/231` (the internal pool, its size of 3, and "whether 3 is right" left
open), `issues/274` (a holder asking its own pool for another connection),
`issues/037` (batched embedding).

## What it is

`auto_sync._run_sync` takes one internal-pool connection and keeps it for the
whole sync: the property fetch, the scope and opt-out lookups, **the embedding
provider call**, the vector upserts, then geo, fuzzy and FTS. The provider call
is an HTTP round trip to OpenAI on the dev server and on AWS. That is seconds
per batch, against milliseconds for the SQL on either side of it, so for most of
its life the connection sits idle in a transaction-free session waiting for a
remote API.

`schedule_sync` puts no bound on how many sync tasks are spawned. Every document
write schedules one, and so does each segmentation job's vectorization step.

The internal pool has **3** connections (`DB_INTERNAL_POOL_SIZE`, default `3`;
the dev app and the vg test stack both run the default). A burst of N document
uploads queues up about 2N sync tasks behind those 3 connections, each holding
its connection for the length of an OpenAI call. Everything else on the
internal pool waits behind them: the segmentation worker, ANALYZE and the
maintenance job.

## Why this explains 290 without the backfills

The worker processes jobs **one at a time**. `_poll_space` awaits each job
inline, so `_MAX_CONCURRENT = 4` never binds. Before 290's fix, each job held
one internal connection and asked for a second. With 11 uploads in flight, the
other two connections were held by auto-sync tasks waiting on OpenAI, so the
second acquire waited its full 15 s and timed out, on 9 of 11 jobs.

290 credited "derived-table backfills and maintenance". The backfills, though,
ran as scripts on their own connections, not on the app's pool. At most they
slowed the queries the holders ran. The holding pattern alone is enough.

290 also said "AWS's pool is larger". Nothing in this repo supports that: the
default is the same 3, and the deploy configuration lives elsewhere. Why AWS
test did not show the symptom (fewer concurrent writes, lower OpenAI latency
from AWS, or a configured size) is **unverified**.

## What a fix looks like (not built)

* **Release the connection across the provider call.** Fetch and decide on one
  acquire, release it, embed, then acquire again for the upserts and the
  geo/fuzzy/FTS steps. A sync then occupies a connection for its SQL alone.
  * The writes must re-check that the space still exists after the second
    acquire, since `cancel_space_syncs` reaches only this process.
* **Bound the task fan-out**, for example with a semaphore around
  `_run_sync`, so a burst queues in memory instead of on the pool.
* Only then revisit the size of 3 (`issues/231`'s open question). Its
  measurement used a fast local embedding provider, and that is the condition
  under which holding across the call costs nothing.

## Not done

Everything above. 290's own fix stands regardless: the worker no longer takes
a second connection, and it fails closed.
