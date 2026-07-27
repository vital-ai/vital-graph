# 019 — Concurrent term-insert race poisons pooled connections → reads flake under load

## Status: ✅ FIXED

## Summary

Root cause of the E2E triples "appears in the list via filter" flake (and a class
of intermittent read-after-write failures under concurrency): the SPARQL UPDATE
path emitted a **non-atomic** term insert. Two concurrent `INSERT DATA`
operations that reference the same term — a shared predicate (`hasName`), the
graph URI, a common type URI — both emit an insert for the same deterministic
`term_uuid`, and the emitted `INSERT ... SELECT ... WHERE NOT EXISTS (...)`
existence-check and insert are not atomic. Both pass the check, both insert, the
second raises `UniqueViolationError` on `{space}_term_pkey`.

That duplicate-key error aborts the statement's implicit transaction and
**poisons the pooled connection**; on release, asyncpg's `conn.reset()` stalls,
and under sustained concurrent writes the connection pool bleeds out. Unrelated
reads (e.g. the triples list) then block on `pool.acquire()` or come back empty —
the E2E symptom.

## Fix

`vitalgraph/db/sparql_sql/emit_update.py::_term_upsert` now emits
`INSERT ... VALUES (...) ON CONFLICT (term_uuid) DO NOTHING` instead of
`WHERE NOT EXISTS`. Postgres resolves the race in a single atomic statement, so
no duplicate-key error, no poisoned connection, no pool exhaustion. All 7
term-insert call sites in the update path go through this one helper, so the fix
is complete. (The main REST write path, `_ensure_term`, already used
`ON CONFLICT DO NOTHING` — only the SPARQL-UPDATE emitter was affected.)

Note: the **quad** inserts in the same file keep `WHERE NOT EXISTS` deliberately —
the quad table's only unique constraint is its 5-column PK **including the random
`quad_uuid`**, so `(s,p,o,c)` has no unique constraint; `ON CONFLICT DO NOTHING`
would not dedupe there, and a racing quad insert produces at worst a duplicate row
(no unique violation → no connection poisoning), not the pool-exhaustion failure.

## How it was found

Direct reproductions initially "proved" every path robust (SQL generation, SQL
execution across plan modes, HTTP reads, write+read-back). Those all used raw
`pool.acquire()` + `conn.fetch`, which **bypassed the transaction/pool machinery**
the real code uses. Driving the actual `execute_sparql_update` / `query_quads`
methods under concurrency with a small pool immediately reproduced it:

```
execute_sparql_update failed: duplicate key value violates unique constraint "..._term_pkey"
... hung task: await self._con.reset(timeout=budget)   # connection stuck in pool.release()
HANG: pool exhausted (size=5 idle=0) -> LEAK
```

Lesson (per review feedback): concurrency/transaction bugs must be exercised
through the real code paths at the DB layer — see the regression test below.

## Regression test

`tests/integration/test_read_after_write_concurrency.py` — many concurrent
`INSERT DATA` writers deliberately colliding on shared terms, each reading back
its own write. A/B verified: **fails without the fix** (`N INSERT DATA calls
failed (term race?)` + `UniqueViolationError`), **passes with it**. Uses a
dedicated space_impl with a realistic pool so it exercises the term race rather
than plain pool saturation.

## Follow-ups (not blocking)

- E2E validation requires rebuilding the vg-test app image (it runs a built
  image, not the working tree). The integration test is the authoritative proof.
- Consider whether `conn.reset()` stalling on a poisoned connection warrants a
  pool-level `command_timeout`/reset-timeout hardening so a single bad statement
  can never bleed the pool — defense in depth beyond this specific race.

## Residual flake — RESOLVED (a second, distinct root cause)

After the term-race fix, `triples-crud.spec.ts:64` still flaked ~1/253 under full
E2E concurrency (read returns 0). Reproduced through the real code paths with a
small pool + concurrent SPARQL-UPDATE writers + `add_rdf_quads_batch` REST writers
+ `query_quads` readers + INSERT/DELETE deleters. Symptom was NOT a poison —
**writer failures = 0, read-after-write misses = 0** — the pool simply bled out and
reads hung.

**Real root cause: a connection-pool double-acquire deadlock.** `generate_sql()`
is called *while the caller already holds a pooled connection*; it invokes
`ensure_edge_table` / `ensure_frame_entity_table`, and when the edge/frame table was
empty those helpers did `async with db.get_connection()` — acquiring a **second**
pool connection. Under N concurrent callers each holding one and blocking to acquire
a second, a small pool deadlocks; unrelated reads stall on `pool.acquire()`.
(`db.execute_query(conn=conn)` correctly reuses the caller's connection;
`db.get_connection()` always acquired a fresh one — that asymmetry was the bug.)

**Fix:**
- `ensure_edge_table.py` / `ensure_frame_entity_table.py`: new `_acquire_conn(conn,
  conn_params)` context manager that **reuses the caller's connection** when provided
  and only acquires from the pool when there is none. Applied to the CREATE-table and
  populate blocks. This eliminates the deadlock.
- Defense-in-depth write-path atomicity in `sparql_sql_space_impl.py`:
  `execute_sparql_update` main write + edge/frame sync each wrapped in their own
  `conn.transaction()`; `add_rdf_quad`, owned-connection `add_rdf_quads_batch`, and
  `remove_rdf_quads_batch` wrapped in transactions (externally-passed connections left
  to the caller's transaction). So no failing statement can leave an aborted pooled
  connection.

**Verified:** repro `tests/integration/_repro_019_poison.py` → `REPRODUCED
POISON/STALL: False` (0 stalls/misses/failures, stable across runs; was hanging to
the 240s timeout with 33 stalls). Regression test still 2 passed; +29 API and +73
integration tests pass. E2E re-run confirms `triples-crud` stable.
