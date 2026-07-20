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
