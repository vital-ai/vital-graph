# Concurrent Writers Deadlock on the Stats Tables

## Status: PARTLY FIXED 2026-08-20 (60d37f2, b43af89) — deadlock closed,
## hold window closed, end-to-end scaling still unmeasured

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

## Still open — end-to-end write scaling

Four concurrent writers reached 1.67x with the stats sync and 1.97x without.
Both are far short of 4x, and the gap is mostly NOT the stats tables: that
harness drives every writer from one event loop, so the Python-side work
(term classification, dedup) serialises before Postgres is ever involved.
Neither figure should be quoted as the ceiling.

Measuring this properly needs a multi-process client. Worth doing before any
further work here, because the two candidate designs — a per-writer delta
table rolled up out of band, or moving the sync after commit — are only worth
their complexity if the stats tables turn out to be what is actually binding.
