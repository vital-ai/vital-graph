# 294 — An index-sync consumer and a stamped write deadlock on the queue

## Status: FIXED 2026-10-22, not yet released: the consumer never waits on a row lock. The defect is in v0.0.95, deployed to production 2026-10-21; production logs not yet checked.

**Related:** `issues/291` (the queue, its trigger and consumers; its "in key
order so writers cannot deadlock on the queue rows" is what this contradicts),
`issues/115` (the earlier writer/writer deadlocks and `with_deadlock_retry`),
`issues/173`/`174` (entity locks on the write paths).

## Found

During the `tests/api` run for `issues/293`, on the vg test stack:

    tests/api/test_entity_frames_api.py::TestEntityFramesCrud::test_delete_entity_frame
    DeleteResponse(error_code=11, 'Frame delete failed, nothing was deleted: deadlock detected ...')

It passed 3/3 when run alone. Its own test does not race; a queue consumer
finishing the previous write to the same entity does.

The Postgres log of the test stack has **15 deadlocks between 2026-10-20 21:43
and 2026-10-22 04:16 UTC**, every one with the same pair of statements:

    Process A: DELETE FROM <space>_index_sync_queue q USING unnest($1::uuid[], $2::uuid[], $3::bigint[])
               AS d(c, s, g) WHERE q.context_uuid = d.c AND q.subject_uuid = d.s AND q.generation = d.g
    Process B: DELETE FROM <space>_rdf_quad WHERE subject_uuid = $1 AND predicate_uuid = $2 AND context_uuid = $3
      CONTEXT: ... INSERT INTO <space>_index_sync_queue ... ON CONFLICT (context_uuid, subject_uuid)
               DO UPDATE SET generation = q.generation + 1 ...   (PL/pgSQL <space>_isq_capture())

Process A is the consumer's `complete()` (`vectorization/index_sync_queue.py`).
Process B is `_stamp_subject` (`kg_impl/kg_backend_utils.py`) replacing a
modification stamp, firing the queue trigger. The consumer was the victim 14
times, the writer once.

## Mechanism: key order holds within a statement, not across a transaction

`delete_frame_subtrees` is one transaction:

1. `DELETE FROM rdf_quad WHERE subject_uuid = ANY(...)` fires the trigger,
   which upserts the queue rows of the deleted frames, slots and edges
   **sorted by key** and holds their row locks.
2. The prop-sort recomputes run, still holding them.
3. `_stamp_subject(owner_entity)` fires the trigger again and wants the
   **entity's** queue row. It is not in the first set, so it is locked after
   them, whatever its key.

Meanwhile a consumer finishes the batch the PREVIOUS write to that entity
queued (the frame create, which also stamped the entity): the entity's row
and some frame rows. Its single DELETE takes the entity row, then waits on a
frame row the writer holds. The writer's stamp then waits on the entity row.

The trigger's `ORDER BY` orders one statement's rows. Two statements of one
transaction, and a second party with its own scan order (a hash-join DELETE
follows heap order), are outside what it can order.

The same shape: the slot delete (stamps the frame), `update_subjects_graph`
and the frame create when they stamp a subject outside the written set, and in
principle any multi-statement SPARQL UPDATE.

## Impact

- **Writer killed:** the whole write rolls back and is reported failed
  ("Frame delete failed, nothing was deleted"). Nothing retries it: these
  paths are not wrapped in `with_deadlock_retry`.
- **Consumer killed:** `complete()` rolls back; its rows stay claimed until the
  300 s lease expires, then re-sync. No index update is lost; up to 5 minutes
  of index lag, a duplicate re-embed, and an ERROR line.
- Production runs the same code with consumers on by default. The exposure is
  two writes to one entity in quick succession, the second landing while a
  consumer finishes the first. To size it: prod logs for
  `index sync consumer .* DeadlockDetectedError` and
  `Frame delete failed: deadlock detected` since the 2026-10-21 deploy.

## Fix: the consumer never waits

`complete`, `fail` and `release` first lock their rows with
`SELECT ... ORDER BY key FOR UPDATE SKIP LOCKED`, then delete or update only
the rows they hold. A transaction that never waits on a lock cannot be part of
a cycle, whatever any writer does: stamps, replaces, SPARQL UPDATE, and paths
not written yet. A writer may still wait briefly on the consumer's short
transaction, which is harmless.

A row a writer holds is told apart from a row that is gone by a plain read
(reads do not wait on row locks). Held rows are retried 4 times outside the
transaction (50, 100, 200, 400 ms). A row still held after that keeps its
claim and is synced again when the lease runs out: the writer is bumping it,
so it would have stayed queued anyway. Duplicate, never lost.

Tests (`tests/integration/test_index_sync_queue.py`, the real interleaving on
two connections):

- `complete` returns while a writer's open transaction holds one of its rows;
  the held row keeps its claim; the writer's later statement, the stamp, then
  takes the entity row without waiting. Before the fix that is the deadlock.
- a writer committing during the retries: its bump survives and the row is
  released, claimable at once;
- `fail` and `release` do not wait either, and release the row once the writer
  is gone.

## Verified (vg test stack, 2026-10-22)

- `tests/integration/test_index_sync_queue.py` + `test_index_sync_trigger.py`:
  22 passed, including the three new interleaving tests. One run failed
  `test_a_burst_is_bounded_and_does_not_starve_the_pool` (assertion not
  captured; it asserts an unrelated pool acquire waits < 0.5 s, and the Mac was
  swapping hard). It then passed 7 times: alone x3, its file x2, both files x2.
- `tests/api` against an image rebuilt with the fix: **677 passed, 9 skipped,
  0 failed**, including `test_delete_entity_frame`. **No `deadlock detected`
  in the app or Postgres logs** over the run, against several in the same
  suite before the fix.

## Not done

- **Writer-side retry as a backstop** (`with_deadlock_retry` on the frame
  delete, the slot delete and stamped `update_subjects_graph` where they own
  the transaction). With the consumer not waiting there is no known cycle left
  to retry. These paths carry entity locks, a write deadline (`wait_for`) and
  caller-supplied transactions, so a retry wrapper needs care; left until a
  writer/writer case shows up.
- Production logs not checked.
