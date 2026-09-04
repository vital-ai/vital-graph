# Concurrent Small-Batch Writes Deadlock On The Term Table

## Status: FIXED 2026-09-04. Pre-existing, reproduced on `main` at 7fb3616 —
## not caused by the rdf_stats recompute work and not unmasked by it, verified
## by stashing those changes and re-running the same test (deadlocked either
## way).

## The fix

Three paths locked the term primary key in quad order. All three now insert in
ascending `term_uuid` order, which is the order the bulk path already used.

  * `SparqlSQLSpaceImpl._ensure_terms` (new) resolves a whole batch's distinct
    terms, then inserts them sorted, in one deduplicated `executemany`.
    `_ensure_term` is kept for the single-term case and delegates to a new
    `_term_row`, which builds the row without writing it.
  * `add_rdf_quads_batch` calls it once per batch instead of four times per
    quad — which also collapses 4 statements per quad into one, and stops a
    batch repeating a predicate 10,000 times from inserting it 10,000 times.
  * `add_rdf_quad` uses it for its four terms. One quad is still four locks, and
    two single-quad writers can cycle on them exactly as two batches can.
  * `emit_update._insert_data_sql` collects its term upserts and emits them
    sorted by `term_uuid`, hoisted ahead of the quad inserts.

THE ORDER HAD TO BE `term_uuid` SPECIFICALLY, not merely deterministic per
path. Writers only avoid deadlocking if they agree with each other, and a
SPARQL UPDATE can run concurrently with a batch insert and share predicates and
graph URIs — which nearly every batch does. A per-path convention would pass a
per-path test and still deadlock across paths.

## Tests

  * `tests/integration/test_stats_lock_order.py::test_two_batches_in_opposite_order_do_not_deadlock`
    — the concurrency reproduction, 60 shared predicates in opposite order over
    8 rounds. Deadlocked reliably before, passes now. (It was briefly marked
    `xfail(strict=True)` while the bug was open.)
  * `tests/unit/test_term_insert_lock_order.py` — the deterministic half, and it
    checks the paths TOGETHER against one rule rather than each against itself.
    Verified to fail when the sort is removed.

## Not addressed

`_resolve_datatype_id` also writes (`INSERT ... ON CONFLICT DO UPDATE`) and is
called while building term rows, so it is ordered by first appearance rather
than by key. It is a much smaller surface: datatypes are a tiny fixed
vocabulary, the `SELECT` short-circuits for ones that already exist, so in
steady state it issues no writes at all. Worth knowing about; not worth a
pre-pass.

The bindings-driven `INSERT ... SELECT FROM _upd_bindings` in
`emit_update.py` inserts many term rows in ONE statement, whose lock order is
whatever the SELECT produces. A single statement cannot deadlock against itself,
but two concurrent ones can. Adding `ORDER BY term_uuid` to that SELECT would
close it. Not done here: it needs its own reproduction, and the paths fixed
above are the ones with a measured failure.

## What happens

Two concurrent `add_rdf_quads_batch` calls whose quads share terms, iterated in
different orders, deadlock on the term table's primary key:

    Process A: INSERT INTO {space}_term (term_uuid, ...) ON CONFLICT DO NOTHING
    Process B: INSERT INTO {space}_term (term_uuid, ...) ON CONFLICT DO NOTHING
    CONTEXT: while inserting index tuple in relation "{space}_term"

One transaction is aborted with SQLSTATE 40P01 and its whole batch is discarded.
Nothing retries.

## Why

`SparqlSQLSpaceImpl.add_rdf_quads_batch` resolves terms one at a time, per quad,
in quad order (`sparql_sql_space_impl.py:1213-1216`):

    s_uuid = await self._ensure_term(conn, t, s)
    p_uuid = await self._ensure_term(conn, t, p)
    o_uuid = await self._ensure_term(conn, t, o)
    g_uuid = await self._ensure_term(conn, t, g)

`_ensure_term` (:2580) issues one `INSERT ... ON CONFLICT DO NOTHING` per term.
So the lock order on the term PK is the caller's quad order. Two writers whose
batches share terms in different orders take the same locks in opposite order,
which is a cycle.

## This is issues/115 in a path its fix never reached

issues/115 is exactly this failure on the stats tables. The fix was to sort every
parameter list so all writers share one global lock order. That reasoning was
applied to the BULK path — `add_rdf_quads_batch_bulk` sorts by term_uuid at
`sparql_sql_space_impl.py:1431`, with a comment naming issues/115 — but the
per-quad path at :1213 was left resolving terms in iteration order.

The bulk path's comment states the general rule ("two batches sharing new terms
inserted them in different orders and could deadlock on the term PK the same way
the stats tables did"). It is correct and it applies here too.

## Impact

Same shape as issues/115: the segmentation worker runs `_MAX_CONCURRENT = 4`
with jobs claimed `FOR UPDATE SKIP LOCKED`, so a transient abort is recorded as
a permanent job failure. Any two concurrent writers with overlapping term
vocabulary can hit it — which is normal, since predicates and graph URIs repeat
across almost every batch.

## Reproduction

`tests/integration/test_stats_lock_order.py::test_two_batches_in_opposite_order_do_not_deadlock`,
currently marked `xfail(strict=True)`. Two writers, 60 shared predicates in
opposite order, 8 rounds. Deadlocks reliably.

The test is strict so that fixing this turns it into an XPASS failure, which is
the reminder to remove the marker rather than leave a passing test claiming to
be broken.

## Likely fix

Collect the batch's distinct terms first and insert them sorted by `term_uuid`,
as the bulk path already does, instead of resolving per quad inside the loop.
That also removes 4 round-trips per quad. NOT attempted here: it is a change to
the hot write path, it is unrelated to the recompute work in flight, and it
wants its own measurement.
