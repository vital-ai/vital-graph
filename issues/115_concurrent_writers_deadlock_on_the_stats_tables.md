# Concurrent Writers Deadlock on the Stats Tables

## Status: CLOSED 2026-08-21. Deadlock fixed, hold window fixed, and the
## remaining ceiling MEASURED — it is not these tables, so the redesign this
## file proposed is declined with a reason.

Sorted lock order plus a bounded retry. Measured: 60 predicates, two writers
in opposite order, 2 deadlocks in 8 rounds before, 0 after. The
serialization ceiling below is untouched and still open.

Found 2026-08-20 while writing the issues/092 regression test.

Two transactions writing quads to the same space can deadlock on
`{space}_rdf_pred_stats` / `{space}_rdf_stats`, and the loser's work is
discarded. Reproduced against the test stack:

    two writers, same two predicates, opposite order
    T1: DEADLOCK (SQLSTATE 40P01)
    T2: committed

## Why the order is not fixed

`sync_stats_after_insert` and `sync_stats_after_delete` build their parameter
lists from a `Counter`, which iterates in first-seen order. That order comes
from the caller's `quad_rows`, so two batches holding the same predicates in
different order lock the same rows in different order — the textbook deadlock
shape. Nothing sorts, and no lock is taken up front.

## This is not a hypothetical concurrency

- `segmentation_worker` sets `_MAX_CONCURRENT = 4` and dequeues with
  `FOR UPDATE SKIP LOCKED`, which exists precisely so workers run at once.
  All four write to the same space through `add_rdf_quads_batch_bulk`.
- `kgdocuments_endpoint` writes on the request path, so any two HTTP clients
  add more.

## What the loser does

Nothing in the write path retries `40P01`. In the worker it reaches the generic
`except Exception`, which calls `manager.fail(job_id, str(e))` — so a
transient, retryable condition is recorded as a permanent job failure. Expect
it to read as an unexplained intermittent failure under load, which is how
`issues/085` presented before its cause was found.

## Two more consequences of the same design, not yet measured

1. **Hot-row serialization.** `rdf_pred_stats` holds one row per predicate.
   `vitaltype` and `hasKGGraphURI` are on nearly every quad, so every writer
   to a space takes the same row lock and holds it until commit. Four workers
   cannot deliver four times the throughput; the real factor is unmeasured.

   MEASURED LATER, and the framing above was wrong. See "The hold window".

2. **A long delete blocks ingest.** `delete_entity_graph_bulk` syncs stats
   inside the same transaction as the delete, so the locks are held for the
   whole entity-graph delete, not just the stats update.

## Fix (done)

Sorting each parameter list by key gives every transaction one global lock
order and removes this deadlock class outright — cheap, local, no schema
change. It should come with a bounded retry on `40P01`, since sorting cannot
cover a transaction that also locks rows elsewhere (the term inserts upstream
in `add_rdf_quads_batch_bulk` are unordered too and deserve the same look).

Neither of those touches the serialization ceiling. That needs the stats
delta to stop being applied inline — a per-writer delta table rolled up out of
band, or the sync moved after commit — and is a larger decision.

## Reproduction

Two connections, `sync_stats_after_insert` with predicates `[A, B]` and
`[B, A]`, each holding its first lock until both are held. Deterministic.

## What was done

`sync_stats_after_insert` / `sync_stats_after_delete` sort every parameter
list, and the delete path took on the insert path's pruned/unpruned split —
sorting alone would not have lined them up, because a delete sorted across all
pairs still crosses an insert that does every unpruned pair first. Term
inserts in `add_rdf_quads_batch_bulk` are sorted too.

`deadlock_retry.with_deadlock_retry` retries the victim, on the paths that own
their transaction. Sorting settles one batch against another but not two calls
in one transaction — a remove of `{C}` plus an insert of `{B}` takes C then B
while a concurrent update doing the reverse takes B then C — so `update_quads`,
which is exactly that shape and owns its transaction, retries there.

Guarded by `tests/integration/test_stats_lock_order.py`: the reproduction, and
a deterministic assertion on the sort, since the race only catches a lost sort
when it happens to land.

## Still open

The hot-row serialization above. One row per predicate, locked to commit,
means writers to a space queue behind `vitaltype` and `hasKGGraphURI` no
matter how many workers there are. The factor is still unmeasured, and fixing
it means the stats delta stops being applied inline — a per-writer delta table
rolled up out of band, or the sync moved after commit.

## The hold window — measured 2026-08-20, fixed in b43af89

"Locked until commit" is true and was the wrong thing to worry about on its
own. What decides the cost is WHERE in the transaction the sync sits:

    add_rdf_quads_batch_bulk   txn 414 ms, hot row held  32 ms    7.7%
    update_quads shape         txn 667 ms, hot row held 657 ms   98.4%

A plain bulk insert already synced last, so its hold is a tail — the ceiling
it imposes is small, and the original claim that writers queue behind the hot
predicates "no matter how many workers" does not hold for it.

`update_quads` was the real case. It is a remove followed by a full insert in
one transaction, and the remove's sync fired first — ahead even of its own
DELETE — so every concurrent writer touching `vitaltype` or `hasKGGraphURI`
waited out the entire insert.

Fixed by moving the remove path's sync after its DELETE (the decrement needs
only the row list, never the table, so the earlier position bought nothing),
and by giving both bulk paths a `stats_sink` that hands the deltas back
instead of applying them inline. `update_quads` applies them once at the end:

    update_quads shape         txn 740 ms, hot row held  63 ms    8.6%

`test_deferred_stats_match_an_inline_sync_exactly` holds the deferred counts
to what a full resync produces.

## End-to-end write scaling — measured 2026-08-21, and it is not these tables

The in-process figures (1.67x with the sync, 1.97x without) measured the
client: one event loop doing every writer's term classification and dedup.
`test_scripts/perf/write_scaling.py` puts each writer in its own process and
samples `pg_stat_activity` throughout.

    stats | procs | quads/s | scaling | top waits
     on   |   1   |   9,072 |  1.00x  | RUNNING:cpu x27
     on   |   2   |  15,438 |  1.70x  | RUNNING:cpu x56,  Lock:transactionid x9
     on   |   4   |  26,029 |  2.87x  | RUNNING:cpu x134, Lock:transactionid x25
     on   |   8   |  36,246 |  4.00x  | RUNNING:cpu x269, LWLock:BufferContent x68
     off  |   8   |  37,662 |  3.46x  | RUNNING:cpu x260, LWLock:BufferContent x113

Three things follow.

**CPU is the ceiling, not the stats rows.** `RUNNING:cpu` is the top state in
every cell. 4.00x from 8 processes on a 10-core box running both the client
and the server is what CPU saturation looks like, not what lock convoy looks
like.

**The stats sync costs work, not waiting.** Disabling it moves throughput by
17% at one process, 10% at four, 4% at eight — shrinking as CPU binds. That is
the cost of doing the upserts.

**The row-lock waiting that does appear is mostly not ours.**
`Lock:transactionid` reaches 64 samples at 8 processes with the sync on, and
44 with it OFF. Most of it is the shared term inserts: every writer inserts
the same `vitaltype`, `KGEntity` and `hasKGGraphURI` terms, and
`ON CONFLICT DO NOTHING` on a row another transaction has just written waits
for that transaction to commit.

### So the redesign is declined

A per-writer delta table rolled up out of band, or moving the sync after
commit, would buy at most the 4% that separates on from off at 8 processes,
and cost a second write path, a rollup job, and a window where the stats are
knowably stale. Not worth it on this evidence.

Reopen this if the picture changes: a deployment with the client OFF the
database host would move the CPU ceiling and could let the row locks bind
where they do not here. The harness takes `VG_PG_HOST`, so that measurement
is the same command.
