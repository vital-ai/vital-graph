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
