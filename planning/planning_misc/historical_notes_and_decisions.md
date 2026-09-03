# Historical Notes & Architectural Decisions

**Date:** 2026-06-28
**Source:** Captured from `notes.txt` (root-level scratch notes from early development)

---

## Implemented / Resolved

These items have been completed but are documented here for historical context.

### PostgreSQL Notifications + WebSocket
- **Idea:** Use psycopg3 NOTIFY/LISTEN for changes to spaces, users, graphs
- **Delivery:** React ↔ FastAPI WebSocket for live UI updates
- **Status:** Signal manager exists in `fuseki_postgresql/postgresql_signal_manager.py`; WebSocket endpoint exists

### WordNet Frame Query Optimization
- Early naive SPARQL-to-SQL generation didn't work with complex frame queries
- Optimized down to ~50ms with `sql_scripts/happy_frame_query_17.sql`
- ~200ms end-to-end in Python with UUID batching and caching
- **Techniques adopted:**
  - Text indexes for text queries
  - Materialized view for edge structure (source → destination)
  - Batch UUID→URI resolution via cache
- **Status:** ✅ Implemented as `edge_table`, `frame_entity_table`, term cache

### Materialized Views
- MV for edge structure: ✅ Implemented (`edge_table`)
- MV for type lookups: ✅ Implemented (via `vitaltype` predicate indexing)
- MV for frame-entity relationships: ✅ Implemented (`frame_entity_table`)
- Per-predicate MVs / object URI MVs: Not implemented (current approach sufficient)

### Connection Pool Architecture
- **Problem:** Sharing a single pool between SQLAlchemy (admin), RDF batch/transactions, and RDF dict-cursor queries caused errors
- **Solution:** Separated into distinct pools — SQLAlchemy for admin tables, asyncpg for RDF operations
- **Status:** ✅ Resolved in current architecture (SQLAlchemy for admin, asyncpg for SPARQL-SQL)

### Unlogged Tables
- Used `UNLOGGED` tables during initial development for speed
- Switched to logged tables since unlogged don't survive restarts
- **Status:** ✅ Resolved — production uses logged tables

### Temp Table Import Pattern
- File → temp table → resolve terms → batch load into primary table
- **Status:** ✅ Implemented in import pipeline

### Python Version
- Noted need to upgrade to 3.12
- **Status:** ✅ Running on 3.12

### Auth, Import/Export, Unit Tests
- JWT auth: ✅ Implemented
- File/dataset table + import/export: ✅ Implemented
- Admin/client UI for import/export: ✅ Implemented
- Unit tests: In progress (see testing_plan.md)

---

## Still Relevant / Future Consideration

### Term Reference Counting
- **Idea:** Ref-count terms for cleanup when no quads reference them
- **Decision:** "Seems efficient just to query directly without counting" — orphan cleanup queries the term table directly rather than maintaining counters
- **Status:** Current approach works; revisit only if term table grows excessively

### Function Calling as Query Bridge
- **Idea:** Pre-optimized SQL query templates with "slots" to fill in, as a bridge before full complex SPARQL handling
- **Context:** For cases like frame/slot queries where SPARQL generation was initially naive
- **Status:** Superseded by the V2 SPARQL-to-SQL pipeline which handles complex queries natively. Could still be relevant for ultra-hot-path queries where even SPARQL compilation overhead is too much.

### Celery for Periodic Jobs
- **Idea:** Use Celery for background/periodic jobs
- **Status:** Implemented differently — `vitalgraph/process/process_scheduler.py` uses a built-in async scheduler rather than Celery. Revisit if distributed job execution is needed.

---

## Gotchas (reference)

- **DBeaver:** Chops queries at newlines by default, making it look like queries are faster than they are. Controlled in DBeaver settings.

---

## Why ANALYZE / VACUUM run on a psycopg SYNC connection, not the asyncpg pool

**Added 2026-09-03.** Recorded because this decision has been questioned twice
and its rationale lived only in a docstring, a one-line citation in an unrelated
plan, and an aside in `issues/136`. It is easy to look like leftover code and it
is not.

### The decision

`MaintenanceJob` runs ANALYZE and VACUUM (and the vector REINDEX) through
`_make_sync_connection` — a short-lived **psycopg** connection with
`autocommit=True` — offloaded via `asyncio.to_thread`. The asyncpg versions
(`_async_run_tables`, `_async_reindex_concurrently`) exist only as a fallback
for when no `postgresql_config` was supplied.

The fork is `if self._pg_config:` at three sites (ANALYZE, VACUUM, REINDEX).
`postgresql_config` IS passed in production (`vitalgraphapp_impl.py:546`), so
**the sync path is what runs.** Verified 2026-09-03 from the Postgres log by
fingerprint, not by reading the fork:

    sync   psql.SQL("ANALYZE {}").format(psql.Identifier(t))  ->  ANALYZE "space_rdf_quad"
    async  f"{command} {table}"                               ->  ANALYZE space_rdf_quad

Every ANALYZE and VACUUM in the production log is quoted. That is psycopg's
`Identifier`. There are no bare ones.

### The stated reasons, and which one is actually load-bearing

The docstring says: "so ANALYZE / VACUUM never touch the asyncpg pool or the
event loop". That bundles two claims, and they are not equally strong.

1. **Pool occupancy — this is the real one.** ANALYZE on the big quad table
   measured **50,224 ms** on production. Holding a pooled connection for ~50 s
   every cycle is one fewer connection for user queries for that whole time.
2. **Event-loop blocking — weaker than it reads.** asyncpg is non-blocking;
   `await conn.execute("ANALYZE ...")` yields rather than stalls. Whoever wrote
   the async fallback appears to have thought the same — it sprinkles
   `asyncio.sleep(0)` between tables, which would be pointless if the await
   already yielded, and harmless if it did. The `to_thread` offload is cited as
   prior art by `planning/planning_vector_geo/dedup_thread_offload_plan.md:41`
   ("the same pattern used successfully for the ANALYZE/VACUUM thread-offload
   fix"), and that doc's own problem — ~350 ms stalls from synchronous Redis —
   IS genuine blocking. ANALYZE via asyncpg is not.

A third benefit is incidental but turned out to matter: a dedicated connection
can carry its own fences at CONNECT time, which is exactly what `issues/136`'s
fix does (`maintenance_conn_options`).

### `issues/136` endorsed keeping it

> The docstring ... explains why it is a *separate* connection ... **which is
> correct and was the right call.** What it does not do is notice that a fresh
> connection is not a fresh *configuration*.

136 fixed the configuration and deliberately kept the separate connection. The
RDS parameter group sets `statement_timeout = 60000` database-wide, so a fresh
connection inherits a read-shaped fence; before the fix, **91% of VACUUMs were
cancelled while the job logged "VACUUM complete" each time.**

### If sync is removed, what MUST be preserved

The thread is not the point. The isolation and the fences are.

* **Keep ANALYZE/VACUUM off the shared pool** — a small dedicated asyncpg pool,
  or accept the ~50 s occupancy knowingly.
* **Keep the fences.** Either `maintenance_conn_options` applied at pool init,
  or `maintenance_timeouts` at each call site — the latter landed in `164d9de`
  and now covers the async fallbacks too.

Removing sync without one of those reopens `issues/136` silently, which is the
failure mode that took months to notice the first time: the job reports success
while the work is cancelled.

### Related

- `issues/136` — the fence that was inherited and not cleared
- `issues/149` — the same class of error one layer up: a probe given the
  maintenance budget while the repair it gates was left on the read path's
- `planning/planning_vector_geo/dedup_thread_offload_plan.md` — the offload
  pattern this is cited as prior art for
