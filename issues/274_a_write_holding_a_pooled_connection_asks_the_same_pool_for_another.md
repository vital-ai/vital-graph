# 274 — A write holding a pooled connection asks the same pool for another

## Status: FIXED 2026-10-17 (not yet released). Latent: not seen in production.

**Related:** `issues/231` (the request/internal pool split), `issues/253`
(work inside a write transaction that should not be), `issues/271`.

## What happened

Benchmarking writes in-process on the test stack (2026-10-17), every 7k-quad
upsert took 16-19 s against ~1 s normally. The phases put the time in the
write step but outside the bulk insert, and the cause was:

    execute_query RAISED TimeoutError
    execute_query 15.00s  SELECT graph_uri FROM graph WHERE space_id = $1

The script's pool was configured `max_pool_size=3`, which leaves a REQUEST pool
of one connection after the internal carve-out. `upsert_objects_atomic` held
that connection for its write transaction, and inside it
`add_rdf_quads_batch_bulk` → `_ensure_graphs_registered` asked the same pool for
a second connection (`self._db.execute_query`). It waited the full acquire
timeout, failed, logged a WARNING and the write carried on without it. Same
upsert with `max_pool_size=10`: 1.04 s.

## Why it matters in production

The shape is a nested acquisition: a caller holds connection 1 and needs
connection 2 from the same pool before it can release 1. With a request pool of
N and N concurrent writers each holding one, every writer waits the acquire
timeout (15 s) at once — a stall for every write in the burst, then each skips
graph registration (`_ensure_graphs_registered` swallows the error). A smaller
burst does not deadlock but still makes writes queue for connections they would
not need. Production: request pool of ~30 per task; a 14-day log search found
no `_ensure_graphs_registered` failure, so it has not happened — it needs a
burst of concurrent writes equal to the pool.

Secondary effects of the same design:

* the registration is OUTSIDE the write transaction, so a rolled-back write
  still leaves its graph registered;
* when it fails, the data lands in a graph with no catalog row and nothing says
  so beyond the WARNING;
* every write pays a catalog round trip (`SELECT graph_uri FROM graph WHERE
  space_id = …`, all of the space's graphs) to learn what is almost always
  already known.

Call sites: `add_rdf_quad` (`sparql_sql_space_impl.py:1090`),
`add_rdf_quads_batch` (`:1375`), `add_rdf_quads_batch_bulk` (`:1494`). The two
batch writers accept `connection=` and still register through the pool.

## Fixed

`_ensure_graphs_registered(space_id, quads, connection=None)`:

1. With a caller connection — `add_rdf_quads_batch(connection=)` and the bulk
   path, which now registers inside `_do_bulk` on the write's own connection —
   it registers there, inside the write's transaction: no second acquisition,
   the registration rolls back with the write, and a failure fails the write.
   Without one (`add_rdf_quad`, a batch write with no connection) it acquires
   its own, sequentially, never while holding another, and keeps the WARNING.
2. One statement, `INSERT … SELECT FROM unnest(uris, names) ON CONFLICT DO
   NOTHING`, instead of reading every graph of the space and inserting each
   missing one.
3. NO per-process cache of registered graphs, as first proposed: a graph can be
   deleted by another process (the admin command, another task), and a stale
   cache would write into it with no catalog row. The single statement is the
   cheaper half of what the cache would have saved.

## Verification

`tests/integration/test_a_write_takes_one_connection.py` (4), on a space impl
whose request pool is ONE connection: an entity upsert, a bulk write and a batch
write on a caller connection each complete in well under the 15 s acquire
timeout and register their graph; a rolled-back write leaves no graph behind (on
a normal pool, where the old code registered on a second connection). All four
fail on the previous code. The graph, named-graph, bulk-load and blank-node
integration files (15) pass.

Side effect visible in profiling: an in-process write on a small pool went from
16-19 s to ~1 s (the stall this issue describes).
