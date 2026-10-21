# 291 — Auto-sync holds an internal-pool connection across the embedding call

## Status: RELEASED IN v0.0.95, deployed to production 2026-10-21, migrated (`migrate_index_sync_queue.py` 11/11 spaces, 22 triggers enabled, queue depth and failures 0, the direct-sync fallback WARNINGs gone after migration; workers up on both tasks, 4 consumers fleet-wide — reported by the deploy session). STAYS OPEN for the follow-ups under Not done. Step 1, a per-space Postgres queue with bounded consumers (`57d6a9a8`); step 2, a trigger on `rdf_quad` that queues each write's subjects in the write's own transaction. Found reviewing `issues/290`.

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

## Fix, step 2 — a trigger on `rdf_quad` queues each write in its own transaction

Step 1 still enqueued after the write had committed, from the call site. A
crash, deploy or cancelled task in that gap lost the sync. A survey of the
write paths found no single Python function every write passes through while
holding its transaction:

- inserts converge on `add_rdf_quads_batch_bulk`;
- deletes are about ten separate `DELETE FROM rdf_quad` statements;
- SPARQL UPDATE's WHERE-bound subjects never reach Python at all.

Decided 2026-10-20 (option B), including that SPARQL UPDATE, the objects
endpoint and relation writes now keep their indexes in step, which they did not
before. Plan: `planning/planning_vector_geo/index_sync_outbox_trigger_plan.md`
(local).

- **`vectorization/index_sync_trigger.py`:** `{space}_isq_capture()` and the
  triggers `trg_{space}_isq_ins` / `trg_{space}_isq_del`.
  - Each is `AFTER ... REFERENCING NEW|OLD TABLE ... FOR EACH STATEMENT`: one
    `INSERT ... SELECT DISTINCT ... ON CONFLICT` per write statement, in key
    order so writers cannot deadlock on the queue rows.
  - It sends a `pg_notify`, which PostgreSQL deduplicates and delivers at
    commit.
  - Proven first on PostgreSQL 18.4, on a hash-partitioned table, for COPY and
    for dynamic SQL.
  - **The body names no space.** It derives the space from `TG_TABLE_NAME` and
    reaches the queue with dynamic SQL. A body that spelled out
    `{space}_index_sync_queue` would survive a space rename, which renames
    objects but not function bodies, pointing at a table that no longer
    exists. Every write would then fail.
- **The consumer decides the operation from the data**
  (`index_sync_worker.resolve`). A subject with quads left in the graph is
  re-derived; one without is removed. A trigger cannot tell a deleted subject
  from one whose quads were replaced.
- **Geo slots depend on edges.** `geo_slot_handler` attributes a slot to its
  entity through `Edge_hasKGSlot` and `Edge_hasEntityKGFrame`. A changed edge
  among the upserts brings the GEO slots it reaches with it, and no other
  slots, so nothing is re-embedded for nothing.
- **Opt-outs, by `suppress(conn)`** (`SET LOCAL vitalgraph.index_sync = 'off'`).
  It refuses outside a transaction, where `SET LOCAL` would silently do nothing
  (`issues/275`). Used by:
  - the bulk import (COPY) and the incremental import;
  - space restore;
  - `load_wordnet_csv.py`, `generate_scale_data.py` and `perf_seed_data.py`;
  - `repair_grouping_self_link.py`, whose grouping URIs no index text is built
    from.

  Imports and restores never synced before and still do not.
- **Kept ON on purpose:**
  - `clear_graph` / `drop_graph`, which used to leave the graph's index rows
    orphaned and now queue them for removal;
  - the server-property backfill, which sets `hasKGEntityType`, the field that
    decides which index mapping a subject is in;
  - large API loads into an empty space, which synced before.
- **`schedule_sync` after a write is a no-op on a space with the trigger.** The
  check is cached per process for 60 s and registered in
  `CACHE_INVALIDATORS`. It still enqueues for a space without the trigger, so
  deploy order does not matter. `rederive=True` always enqueues; it is for
  re-derivations no trigger sees:
  - KGType description changes (`kgtype_cross_space_sync`);
  - a document type's `auto_vectorize` flip, for its unstamped originals.
- **`scripts/migrate_index_sync_queue.py`** now installs the trigger too, in one
  transaction per space, table before trigger. A trigger without its table
  would fail every write.
- **Test isolation:** the vg test stack's app skips `inttest_*` spaces
  (`VG_INDEX_SYNC_EXCLUDE_PREFIXES`), whose queue rows the in-process
  integration tests assert on directly.
- **The hot bulk paths queue explicitly, once** (`captured_explicitly`). A
  statement-level trigger fires per EXECUTION, and `executemany` executes once
  per row. `add_rdf_quads_batch_bulk` uses it under 500 rows, and
  `remove_rdf_quads_batch_bulk` always does. Measured first, the trigger fired
  44 times for a 44-quad entity graph and added 26% to an insert
  (34 -> 43 ms median) and 30% to a replace (101 -> 132 ms). Those two paths
  now switch the trigger off for their own statements and queue the distinct
  pairs they already hold, in the same transaction. The previous setting is
  restored after, so the rest of a caller's transaction is still captured, and
  an enclosing `suppress` is honoured.
- **Found on the way:** `issues/292`. A text filter on a subject was declared
  empty from a count over objects, and a cached zero outlived the write that
  made it wrong.

Verified step 2: `tests/integration/test_index_sync_trigger.py`, 9 passed.

- New spaces have the trigger.
- An insert, a delete, and a SPARQL DELETE whose subjects are bound by WHERE
  each queue exactly their subjects.
- A rolled-back write queues nothing.
- A suppressed transaction queues nothing, and the next one queues again.
- The consumer resolves upsert and delete from the data.
- An edge change reaches the geo slot it points at.
- The post-write enqueue defers to the trigger, and `rederive=True` still
  enqueues.

The step-1 queue tests pass alongside (19 together).

Write cost, measured 2026-10-20 on the vg stack (scratch space with 2,000 entity
graphs, alternating rounds, 5 per cell, median of each round's per-write
median; `test_scripts/perf/_issue291_trigger_cost_measure.py`, local). The
baseline is no outbox at all (trigger disabled AND the explicit enqueue
skipped):

| write | no outbox | outbox |
|---|---|---|
| insert, 44-quad entity graph | 27.6 ms (26.5-34.1) | 27.2 ms (25.5-31.9) |
| replace (delete + insert) | 84.9 ms (79.6-109.7) | 88.8 ms (82.1-104.8) |
| bulk, ~6,000 quads | 449 ms (383-565) | 450 ms (372-1254) |

Within the noise. Taken with the Mac's load average around 21 from desktop
apps, not this work, and memory 36% free, so the absolute values are
indicative; the alternating A/B is what the comparison rests on.

## Not done

- **The cost was measured on a 2,000-graph scratch space, not at
  `sp_lead_synth_100k` scale.** The trigger's work scales with the statement,
  not the table, but a re-run on a quiet machine at prod scale would firm the
  numbers up.
- **Redundant syncs still re-embed.** A write that changes no embedded text
  (a stamp, a status) re-embeds its subject. Skipping the provider call when
  the text's hash is unchanged would make those nearly free.
- **The dev database has the queue tables but not the trigger.** The dev app
  (:8001) runs code without consumers; install the trigger there with its
  next rebuild.
- **Monitoring.** `index_sync_queue.stats()` returns depth, claimed, failing
  and the oldest age; nothing reads it yet. The maintenance job, or the admin
  status endpoint, should report a backlog or a failing row.
- ~~Production migration~~ — done in v0.0.95, deployed to production 2026-10-21.
