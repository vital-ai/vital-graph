# 291 — Auto-sync holds an internal-pool connection across the embedding call

## Status: STEP 1 FIXED IN CODE 2026-10-20 (not yet released): a per-space Postgres queue with bounded consumers. Step 2 (enqueue inside each write's transaction) not done. Found reviewing `issues/290`.

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

## Worse than starvation: a timed-out sync was lost

Every acquire on the internal pool times out after 15 s (`db/pool.py`), and
the sync tasks' own acquires are no exception. A sync that timed out logged
`auto_sync(...) failed:`, with an empty message for a `TimeoutError`, and
nothing retried it. The document's vector, FTS, geo and fuzzy rows then stayed
stale until a reindex. Neither local log showed one, but under a burst on
OpenAI it is the likely outcome.

## Measured before the fix

The vg test stack's own log, during the `issues/285`/`286` API run on the
2026-10-20 image, recorded 9 `pool_wait` records on the INTERNAL pool, all at
3/3 in use: median 1.2 s, max 5.1 s, while 26-27 request connections sat idle.
That stack embeds with the local model, not OpenAI.

## Fix, step 1 — a per-space queue in Postgres, drained by bounded consumers

Decided 2026-10-20: a table, not an in-process queue, so that nothing is lost
on a restart and every app process shares it. Production runs two ECS tasks
and will scale.

- **`{space}_index_sync_queue`**, one row per `(context_uuid, subject_uuid)`
  (`sparql_sql_schema`, `vectorization/index_sync_queue.py`).
  - **A second write merges** into the row, bumping `generation` and recording
    the latest `operation`, so a burst of updates to one document is embedded
    once.
  - **A consumer deletes the row only if the generation is the one it
    claimed.** A write during a sync leaves the row for another pass, from the
    data as it now is.
  - **Claims are `FOR UPDATE SKIP LOCKED` with a lease** (`claimed_until`, 300 s),
    committed at once. Any number of processes share the table without taking
    the same rows; a consumer that dies gives its rows back when the lease
    ends, and a clean shutdown releases them at once.
  - **A failure backs off** (5 s doubling, capped at 10 min) with `last_error`
    recorded. A new write to the row makes it due again at once.
- **`index_sync_worker.IndexSyncWorker`**, one per app process, started and
  stopped with the app. It runs a fixed number of consumers: one less than the
  internal pool, so 2 by default (`VG_INDEX_SYNC_CONSUMERS` overrides).
  - **Woken by NOTIFY** on `vg_index_sync`, sent in the enqueue's transaction,
    on one LISTEN connection outside the pools.
  - **A 10 s sweep** finds rows a notification missed, a retry whose backoff
    ended and an expired lease.
- **`auto_sync.sync_subjects` holds no connection across the embedding.** One
  acquire reads, plans, and does the deletes that need no provider. The
  provider is called with nothing held. A second acquire re-checks that the
  space still exists, then writes vectors, geo, fuzzy and FTS.
- **A provider outage is retried, not recorded as done.** When every text of
  an index fails, after the per-subject fallback, the sync raises
  `EmbeddingUnavailable` and the row is failed for a retry.
- **`schedule_sync` keeps its signature and its 11 call sites.** Its task now
  only enqueues.
  - **A space without the table**, not yet migrated, is synced directly as
    before, with one WARNING per space, so deploy order does not matter.
  - **The segmentation worker** marks a job completed once its subjects have
    drained from the queue (`wait_until_synced`, 600 s). If they have not, it
    says so in the job's error.
  - **`cancel_space_syncs`** still cancels a consumer's in-flight sync for a
    space being deleted.
- **`scripts/migrate_index_sync_queue.py`** creates the table and its index on
  existing spaces, from the schema's own statements. Run on the vg test stack
  (27 spaces) and the host dev cluster (45), 2026-10-20.

## Verified

`tests/integration/test_index_sync_queue.py`, 10 passed.

- **The queue's rules:**
  - a second write merges into one row, with the latest operation;
  - completing removes the row;
  - a write during a sync leaves the row, unclaimed and due;
  - two consumers never claim the same rows (40 rows, two claims of 25);
  - an expired lease gives the rows back;
  - a failure backs off, and a new write cuts the backoff short;
  - a release returns only that consumer's rows.
- **The control:** the old single-connection form, ten syncs at once on a
  3-connection pool with a 1 s provider. An unrelated acquire waits at least
  0.8 s. This is the starvation, reproduced.
- **The fix:** the same burst through the queue with 2 consumers. All ten
  synced, at most 2 embeddings at once, every unrelated acquire under 0.5 s,
  and the queue empty afterwards.
- **A provider outage** leaves the row queued with `EmbeddingUnavailable`
  recorded, no vectors written, claim released.

Plus the unit suite, the schema, rename and lifecycle integration tests, and
the full API suite on the rebuilt vg test stack (below).

## Not done

- **Step 2: enqueue inside each write's transaction.** Today `schedule_sync`
  enqueues just after the write commits, so a crash in that gap still loses
  the sync. Moving `index_sync_queue.enqueue` onto the write's own connection,
  call site by call site, closes it.
- **Monitoring.** `index_sync_queue.stats()` returns depth, claimed, failing
  and the oldest age; nothing reads it yet. The maintenance job, or the admin
  status endpoint, should report a backlog or a failing row.
- **Production:** run `scripts/migrate_index_sync_queue.py --all --apply` after
  the release.
