# 327 — Every aux-table ANALYZE opened a database connection it never closed

## Status: RESOLVED 2026-10-28. Verified on the vg test stack rebuilt for the fix: unit, DAWG conformance, integration and API suites; `ResourceWarning: unclosed connection` 0 in the app log (was 24-27 per run).

**Found:** 2026-10-28, reading the app log for `issues/269` / `278`.
**Related:** `issues/230` (why the ANALYZE takes a non-blocking advisory lock at all),
`issues/231` (the INTERNAL pool the ANALYZE runs on).

## What it was

`SparqlSQLBackendAdapter._get_analyze_lock_manager` lazily built a
`ProcessLockManager` — a dedicated asyncpg connection — and kept it on the
ADAPTER. Adapters are built per request (`create_backend_adapter`), so every
write that triggered the post-write ANALYZE opened a new connection, used it for
`pg_try_advisory_lock` / `pg_advisory_unlock`, and never closed it. It went when
the adapter was freed, as

    ResourceWarning: unclosed connection <asyncpg.connection.Connection ...>

on the line after `BACKEND ANALYZE (aux tables)`: 27 per API suite run before
`issues/269`'s fix, 24 after. Each was a full connection setup (TCP, auth,
`_init_conn`) per ANALYZE, and a connection held for as long as the adapter
lived — longer if the adapter sat in a reference cycle, which `269`'s fix (no
more forced collection every 60 s) would have made worse.

## Fix

* ONE lock manager per process and event loop, keyed by the database
  (`_ANALYZE_LOCK_MANAGERS` in `kg_backend_utils.py`). Two first callers racing
  both connect; the loser closes its own.
* A shared connection makes the session-level advisory lock RE-ENTRANT for this
  process's own tasks, so it no longer keeps two of them apart. An in-process
  set (`_ANALYZE_IN_FLIGHT`) does that now: a second ANALYZE of a space already
  running here skips, as one from another process does.

## Verification

`tests/unit/test_analyze_lock_connection_is_shared.py` (3): adapters share one
manager; racing first callers leave one connection open; a second in-process
ANALYZE of the space skips and the lock is released. The existing ANALYZE tests
pass unchanged. On the rebuilt vg test stack the full suite passes and the app
log holds 0 `unclosed connection` warnings and 2 lock-manager connects for the
whole run.
