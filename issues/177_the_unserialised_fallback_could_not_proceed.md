# 177 — The "proceeding UNSERIALISED" fallback could not proceed

**Status:** fixed 2026-09-08, pinned by test
**Raised:** 2026-09-08, from the v0.0.60 production rollout
**Related:** issues/174 (the grouping locks this degrades), issues/173 (the race
they exist to prevent), `vitalgraph/db/sparql_sql/sparql_sql_space_impl.py`,
`vitalgraph/db/sparql_sql/update_lock.py`

## The defect

issues/174 gave SPARQL updates a grouping lock, with a deliberate best-effort
degradation: if the lock cannot be taken, log a warning and run the write
unserialised, on the reasoning that an unserialised write beats a failed write.

The degradation did not work. It could never have worked.

```python
try:
    _locked = await acquire_update_locks(conn, space_id, gen.update_lock_plans)
except Exception as _le:
    logger.warning("... proceeding UNSERIALISED ...")
# ... and then, on the same connection:
await conn.execute(sql)      # InFailedSQLTransactionError
```

`lock_timeout` is enforced by the SERVER. It does not raise a client-side
timeout that leaves the session intact — it aborts the transaction. Every
statement afterwards fails with `InFailedSQLTransactionError` until rollback.
So the except clause caught the error, logged its reassuring warning, and then
the write failed anyway, with a *different* and far more confusing error than
the one the fallback existed to prevent.

The log line made this worse rather than better. It says the write is
proceeding. The write is not proceeding. Anyone reading the logs during an
incident would have taken the warning at face value and looked elsewhere.

## How it surfaced

During the v0.0.60 rollout. An update contended with the draining previous
generation, timed out on the grouping lock, and died at
`sparql_sql_space_impl.py:2481` with `InFailedSQLTransactionError` — a stack
that names neither locking nor timeouts, several frames from the cause.

## Why it was not caught

The fallback path had no test. It is by construction the path that only runs
under contention, and contention is exactly what a single-threaded test suite
does not produce by accident. Every test exercised the branch where the lock is
acquired successfully; the `except` was written, reviewed, and shipped without
ever executing.

## The fix

A SAVEPOINT around the acquisition. `ROLLBACK TO SAVEPOINT` discards the failed
acquisition and leaves the transaction usable, so the write can genuinely
proceed; `RELEASE SAVEPOINT` on success keeps any locks taken, because an
advisory *xact* lock lives until the transaction ends and is not scoped to the
savepoint that took it.

In asyncpg a nested `conn.transaction()` compiles to a SAVEPOINT, so this needs
no new machinery — just the nesting, and the knowledge of what it does.

## What this was worth writing down for

**A degradation path is a code path.** "Best effort" describes an intent, not a
behaviour. This one was unreachable in practice, and the thing that hid it was
that its failure mode looked like success in the logs.

**Both PostgreSQL facts the fix rests on are now pinned by tests**, in
`tests/integration/test_update_lock_fallback_can_proceed.py`, because the fix
is worthless if either is false and neither is self-evident from reading the
code:

  * an advisory xact lock survives `RELEASE SAVEPOINT` — if it did not, the
    wrapper would serialise nothing while appearing correct;
  * the transaction is usable after `ROLLBACK TO SAVEPOINT` following a lock
    timeout — this is the property that makes "proceed unserialised" possible
    at all.

**The first version of the structural test passed with the fix removed.** It
searched a window before the call for `conn.transaction()` and matched the
*enclosing* transaction. It was rewritten to anchor on `_sp.rollback()`, which
exists for no other purpose, and then verified by deleting the savepoint and
watching it fail. A check that cannot fail is not a check — the same lesson as
the `PYTEST_EXIT` sentinel in the runbook, arrived at from the other direction.
