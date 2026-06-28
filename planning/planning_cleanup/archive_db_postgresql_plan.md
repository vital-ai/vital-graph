# Plan: Archive db/postgresql and Clean Up DB Layer Abstractions

## Background

The `vitalgraph/db/` package currently contains multiple backend implementations:

| Package | Role | Status |
|---------|------|--------|
| `db/_archive/postgresql/` | V1 pure-PostgreSQL backend (psycopg, hand-built SPARQL-to-SQL) | **Archived (Phase 1 complete)** |
| `db/sparql_sql/` | V2 pure-PostgreSQL backend (asyncpg, Jena sidecar pipeline) | **Active / replacement** |
| `db/fuseki_postgresql/` | Fuseki hybrid (Fuseki for SPARQL, PostgreSQL for admin/metadata) | **Active — long-term** |
| `db/fuseki/` | Pure Fuseki | Placeholder for future |
| `db/oxigraph/` | Oxigraph | Placeholder for future |
| `db/aurora_postgresql/` | Aurora PostgreSQL | Placeholder for future |
| `db/tidb/` | TiDB | Placeholder for future |
| `db/mock/` | In-memory mock for testing | Active |

The `sparql_sql` backend is now the primary pure-PostgreSQL implementation and supersedes `db/postgresql/`. The goal is to archive the old code safely, then progressively clean up the codebase to establish clean layer separation.

---

## Current State: What Lives Where

### db/_archive/postgresql/ (34 files, ~850K of code — ARCHIVED)

**Top-level files:**
- `postgresql_db_impl.py` (77K) — V1 DbImplInterface, connection pool (psycopg), admin table CRUD, space lifecycle
- `postgresql_space_impl.py` (34K) — V1 SpaceBackendInterface implementation
- `postgresql_sparql_impl.py` (21K) — V1 SPARQL entry point
- `postgresql_log_utils.py`, `postgresql_cache_*.py` — V1 utilities

**space/ subpackage (14 files):**
- Schema, terms, quads, graphs, namespaces, datatypes, queries, transactions, imports, db_objects, db_ops, db_mgmt
- All use psycopg (sync driver) with hand-built SQL

**sparql/ subpackage (10 files):**
- V1 SPARQL-to-SQL: orchestrator (86K), patterns (105K), expressions (128K), core, cache, queries, updates, property paths, global optimizer
- Massive monolithic code — replaced by V2 pipeline

### db/sparql_sql/ (42 files — ACTIVE REPLACEMENT)
- `sparql_sql_db_impl.py` — V2 DbImplInterface (asyncpg pool)
- `sparql_sql_space_impl.py` — V2 SpaceBackendInterface
- `sparql_sql_schema.py` — V2 schema (term, rdf_quad, datatype, edge, stats tables)
- `sparql_sql_db_objects.py` — V2 object/entity CRUD
- V2 SPARQL pipeline: collect, emit_*, generator, ir, var_scope, etc.
- Auxiliary tables: edge, frame_entity, stats sync

### db/fuseki_postgresql/ (18 files)
- `postgresql_db_impl.py` — Fuseki-PG hybrid DbImplInterface
- `postgresql_schema.py` — Admin tables (install, space, graph, user)
- `fuseki_postgresql_space_impl.py` — Space impl delegating SPARQL to Fuseki
- Dual-write coordinator, edge materialization, dataset management, signal manager

### External References to db/postgresql/ — ALL RESOLVED

| File | Former Import | Resolution |
|------|---------------|------------|
| `impl/vitalgraph_impl.py` | `from vitalgraph.db.postgresql.postgresql_db_impl import PostgreSQLDbImpl` | **Removed.** `else` branch now raises `ValueError` directing to `sparql_sql` or `fuseki_postgresql`. |
| `ops/graph_import_op.py` | `from ..db.postgresql.space.postgresql_space_db_import import PostgreSQLSpaceDBImport` | **Replaced with `NotImplementedError`.** TODO: reimplement against active backend's bulk load interface. |
| `db/backend_config.py` (space/sparql) | `from .postgresql.postgresql_space_impl import PostgreSQLSpaceImpl` | **Replaced with `ValueError`.** `BackendType.POSTGRESQL` routes now reject with clear error message. |
| `db/backend_config.py` (signal) | `from .postgresql.postgresql_signal_manager import PostgreSQLSignalManager` | **Redirected** to `fuseki_postgresql.postgresql_signal_manager` (shared). |
| `admin_cmd/vitalgraphdb_admin_cmd.py` | Logger name `vitalgraph.db.postgresql.postgresql_db_impl` | **Updated** to `vitalgraph.db.sparql_sql`. |

Internal cross-references (within `db/_archive/postgresql/` itself) remain but are inert — guarded by `__init__.py` that raises `ImportError`.

### Other db/ Files

| File | Status | Notes |
|------|--------|-------|
| `db/db_inf.py` | Active | `DbImplInterface` — common interface across all backends |
| `db/db_impl_interface.py` | Active (empty) | Intended as the common interface across db backends — concept is relevant, needs implementation |
| `db/space_inf.py` | Active | `SpaceBackendInterface` — common space interface |
| `db/sparql_inf.py` | Active | `SparqlBackendInterface` — common SPARQL interface |
| `db/space_backend_interface.py` | Active | Alternate space interface (consolidate with `space_inf.py`) |
| `db/backend_config.py` | Active | `BackendFactory` — routes to implementations |
| `db/metaql_inf.py` | **Deleted** | Was empty, no references — removed in Phase 1 |

### Dev/Test Directory

`vitalgraph_sparql_sql/` at the repo root is the **dev/test workspace** for the V2 SPARQL-to-SQL pipeline. It contains DAWG test harnesses, benchmarks, and DevDbImpl. It stays as a dev area and is not part of the `vitalgraph` package.

### Admin CLI (vitalgraphdb_admin_cmd.py — 112K)
- Contains **hardcoded schema DDL** for each backend type (fuseki_postgresql, sparql_sql)
- Has inline `_init_fuseki_postgresql_backend()`, `_init_sparql_sql_backend()` methods
- Directly calls `self.db_impl.execute_query()` / `execute_update()` for schema operations
- Should delegate to each implementation's own schema module

---

## End-State Architecture

```
vitalgraph/db/
├── __init__.py
├── db_inf.py                    # DbImplInterface (common)
├── space_inf.py                 # SpaceBackendInterface (common)
├── sparql_inf.py                # SparqlBackendInterface (common)
├── space_backend_interface.py   # (merge with space_inf.py or keep)
├── backend_config.py            # BackendFactory — routes to implementations
├── common/                      # NEW: shared models & admin schema
│   ├── models.py                # Space, Graph, User dataclasses (common model)
│   ├── admin_schema.py          # Shared admin table DDL (install, space, graph, user)
│   └── entity_registry_schema.py  # (moved from entity_registry/)
├── sparql_sql/                  # V2 pure-PostgreSQL implementation
│   ├── sparql_sql_db_impl.py    # DbImplInterface
│   ├── sparql_sql_space_impl.py # SpaceBackendInterface
│   ├── sparql_sql_schema.py     # Per-space schema (term, quad, indexes)
│   ├── sparql_sql_admin.py      # NEW: init/purge/delete/info operations
│   ├── ...                      # V2 pipeline files
│   └── sparql_sql_db_objects.py
├── fuseki_postgresql/           # Fuseki hybrid implementation
│   ├── postgresql_db_impl.py    # DbImplInterface
│   ├── fuseki_postgresql_space_impl.py
│   ├── postgresql_schema.py     # Admin schema variant
│   ├── fuseki_admin.py          # NEW: init/purge/delete/info operations
│   └── ...
├── jena_sparql/                 # Jena sidecar types (shared by sparql_sql)
├── mock/                        # Mock implementation
└── ...                          # NO archived code inside vitalgraph/

# Outside the vitalgraph package (repo root):
archive_vitalgraph_old/
└── db_postgresql/               # Final resting place for V1 code
    ├── postgresql_db_impl.py
    ├── space/
    └── sparql/
```

**Key principles:**
1. Each implementation owns its schema (DDL, indexes, per-space tables)
2. Each implementation provides admin operations (init, purge, delete, info, list)
3. The top-level `db/` package translates from common models (Space, Graph, User) to implementation-specific storage
4. All implementations share PostgreSQL for foundational tables (install, space, graph, user, entity_registry) but differ in per-space tables (terms, quads, indexes)
5. Admin CLI delegates to implementation-specific admin modules — no more inline DDL

---

## Phased Plan

### Phase 1: Archive db/postgresql/ (Non-Breaking) — ✅ COMPLETE

**Goal:** Move the old code out of the active path without breaking anything that currently works.

The archive happens in two steps:
- **Step 1a (this phase):** Move to `vitalgraph/db/_archive/postgresql/` as an interim location. ✅ Done.
- **Step 1b (Phase 4):** Move out of the `vitalgraph` package entirely to `archive_vitalgraph_old/db_postgresql/`.

**Completed steps:**

1. ✅ **`git mv db/postgresql/ db/_archive/postgresql/`** — V1 code moved with history preserved
2. ✅ **`db/_archive/__init__.py`** — Guard raises `ImportError` if anyone tries to import from archive
3. ✅ **`db/_archive/postgresql/__init__.py`** — Guard raises `ImportError` with message directing to `sparql_sql`
4. ✅ **`db/_archive/README.md`** — Documents what's archived and why
5. ✅ **`impl/vitalgraph_impl.py`** — Removed `PostgreSQLDbImpl` import; `else` branch raises `ValueError`
6. ✅ **`ops/graph_import_op.py`** — `_perform_database_import()` raises `NotImplementedError` (TODO: reimplement)
7. ✅ **`db/backend_config.py`** — All 3 factory methods reject `BackendType.POSTGRESQL` with clear errors; signal manager redirected to shared `fuseki_postgresql` impl; default backend changed to `SPARQL_SQL`
8. ✅ **`db/metaql_inf.py`** — Deleted (empty, no references)
9. ✅ **`admin_cmd/vitalgraphdb_admin_cmd.py`** — Updated 2 stale logger name strings
10. ✅ **Verification** — Zero references to `db.postgresql` outside `_archive/`; zero references to `metaql_inf`

### Phase 2: Extract Admin Operations from CLI into Implementations — ✅ COMPLETE

**Goal:** Each backend implementation provides its own admin module so the CLI is a thin dispatcher.

**Completed steps:**

1. ✅ **`db/db_admin_inf.py`** — Created `DbAdminInterface` ABC with 6 abstract methods: `check_admin_tables`, `init_tables`, `purge_tables`, `delete_tables`, `get_info`, `list_spaces`
2. ✅ **`db/sparql_sql/sparql_sql_admin.py`** — `SparqlSQLAdmin` implements the interface; contains all admin table DDL (9 tables: install, space, graph, user, process, agent_type, agent, agent_endpoint, agent_change_log), index definitions, and seed data that were previously inline in the CLI
3. ✅ **`db/fuseki_postgresql/fuseki_admin.py`** — `FusekiPostgreSQLAdmin` implements the interface; delegates schema DDL to existing `FusekiPostgreSQLSchema`
4. ✅ **Admin CLI refactored** — `_get_backend_admin()` returns the correct admin module based on backend type; `cmd_init`, `cmd_purge`, `cmd_delete`, `cmd_info` all delegate to the admin module
5. ✅ **Removed 4 dead private methods** — `_init_fuseki_postgresql_backend`, `_init_sparql_sql_backend`, `_info_fuseki_postgresql_backend`, `_info_sparql_sql_backend` (352 lines removed, CLI reduced from ~2609 to ~2257 lines)
6. ✅ **`cmd_purge` and `cmd_delete` now functional** — Previously were TODO stubs; now fully implemented via admin modules with confirmation prompts and proper error handling

### Phase 3: Common Model Layer + Admin Module Cleanup — ✅ COMPLETE

**Goal:** Create shared data models; ensure admin modules are pure orchestrators with zero DDL.

**Design principle:** Each backend independently owns its schema DDL.  The backends
happen to adhere to a common data model for concepts like space, graph, and user,
but there is **no shared schema module**.  The common models are pure data transfer
objects — they do not define DDL or dictate table structure.

**Completed steps:**

1. ✅ **`db/common/models.py`** — `SpaceData`, `GraphData`, `UserData`, `InstallData`, `ProcessData` dataclasses with `to_dict()` / `from_row()`.  Named `SpaceData` (not `SpaceRecord`) to avoid conflict with runtime `SpaceRecord` in `space/space_manager.py`
2. ✅ **Moved admin DDL into `SparqlSQLSchema`** — admin table DDL (9 tables), index DDL, seed statements, drop/truncate helpers all live in `sparql_sql_schema.py`.  `sparql_sql_admin.py` went from 349→175 lines (pure orchestration)
3. ✅ **Added admin DDL helpers to `FusekiPostgreSQLSchema`** — `ADMIN_TABLE_NAMES`, `ADMIN_SEED_STATEMENTS`, `ADMIN_DROP_ORDER`, `get_admin_seed_sql()`, `drop_admin_tables_sql()`, `truncate_admin_tables_sql()`.  `fuseki_admin.py` went from 166→157 lines (pure orchestration)
4. ✅ **No shared schema** — `db/common/admin_schema.py` was considered and rejected; each backend independently owns its DDL

### Phase 4: Clean Up Remaining Cross-Cutting Concerns — ✅ COMPLETE

**Goal:** Ensure clean package boundaries.

**Completed steps:**

1. ✅ **Consolidated interface files:**
   - Deleted `db_impl_interface.py` (empty, zero importers)
   - Deleted `sparql_inf.py` — `SparqlBackendInterface` already in `space_backend_interface.py`
   - Deleted `space_inf.py` — duplicate `SpaceBackendInterface`, stale `BackendType`/`BackendConfig`/`BackendFactory`
   - Moved `SignalManagerInterface` from `space_inf.py` → `space_backend_interface.py`
   - Updated `backend_config.py` and `fuseki_space_impl.py` imports
   - Canonical interface files: `db_inf.py`, `db_admin_inf.py`, `space_backend_interface.py`

2. ✅ **Entity registry schema** — no action needed, only imported within its own package

3. ✅ **Signal manager** — no action needed, `fuseki_postgresql/postgresql_signal_manager.py` location is appropriate for a PostgreSQL-based signal manager shared by PostgreSQL-backed backends

4. ✅ **Graph import ops** — `graph_import_op.py` already has `raise NotImplementedError` guard; V1 `PostgreSQLSpaceDBImport` ref is dead code after the raise. Future task to re-implement against active backends

5. ✅ **`BackendType.POSTGRESQL`** — kept in enum with `raise ValueError` guards in all three factory methods (space, sparql, signal). Config files referencing it get a clear error

6. ✅ **Moved `_archive/`** — `vitalgraph/db/_archive/postgresql/` → `archive_vitalgraph_old/db_postgresql/`. Deleted empty `vitalgraph/db/_archive/`. V1 code no longer ships with the package

---

## File Size Reference (db/postgresql/ — what's being archived)

| File | Size | Description |
|------|------|-------------|
| `postgresql_db_impl.py` | 77K | V1 main db impl |
| `postgresql_space_impl.py` | 34K | V1 space impl |
| `postgresql_sparql_impl.py` | 21K | V1 SPARQL entry |
| `sparql/postgresql_sparql_orchestrator.py` | 86K | V1 SPARQL orchestrator |
| `sparql/postgresql_sparql_patterns.py` | 105K | V1 pattern translation |
| `sparql/postgresql_sparql_expressions.py` | 128K | V1 expression translation |
| `sparql/postgresql_sparql_core.py` | 44K | V1 SPARQL core |
| `sparql/postgresql_sparql_queries.py` | 33K | V1 query builder |
| `sparql/postgresql_sparql_property_paths.py` | 33K | V1 property paths |
| `sparql/postgresql_sparql_updates.py` | 27K | V1 SPARQL updates |
| `sparql/postgresql_sparql_cache_integration.py` | 28K | V1 term cache |
| `sparql/postgresql_sparql_global_optimizer.py` | 19K | V1 global optimizer |
| `space/postgresql_space_db_import.py` | 94K | V1 RDF import |
| `space/postgresql_space_db_ops.py` | 52K | V1 db operations |
| `space/postgresql_space_db_objects.py` | 31K | V1 object operations |
| `space/postgresql_space_core.py` | 27K | V1 core space ops |
| `space/postgresql_space_queries.py` | 26K | V1 space queries |
| `space/postgresql_space_datatypes.py` | 20K | V1 datatypes |
| `space/postgresql_space_graphs.py` | 18K | V1 graph management |
| `space/postgresql_space_terms.py` | 19K | V1 term management |
| `space/postgresql_space_schema.py` | 13K | V1 schema |
| `space/postgresql_space_db_mgmt.py` | 11K | V1 db management |
| `space/postgresql_space_transaction.py` | 10K | V1 transactions |
| `space/postgresql_space_utils.py` | 10K | V1 utilities |
| `space/postgresql_space_namespaces.py` | 8K | V1 namespaces |
| **Total** | **~1MB** | |

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Breaking sparql_sql backend | Phase 1 only touches imports, not sparql_sql code |
| Breaking fuseki_postgresql backend | No changes to fuseki_postgresql in Phase 1 |
| Admin CLI regressions | Phase 1 doesn't change admin CLI; Phase 2 is additive first |
| Lost git history | `git mv` preserves history; final location is `archive_vitalgraph_old/` at repo root |
| Circular imports | Phase 3 common models are leaf modules with no upward deps |
| Config files referencing `postgresql` backend type | Keep enum value, emit deprecation warning |

---

## Execution Order

1. **Phase 1** — ✅ COMPLETE — Archived `db/postgresql/` to `db/_archive/`, fixed all external imports
2. **Phase 2** — ✅ COMPLETE — Extracted admin ops into `sparql_sql_admin.py` + `fuseki_admin.py`, CLI is now a thin dispatcher
3. **Phase 3** — ✅ COMPLETE — Common data models in `db/common/models.py`; admin modules are pure orchestrators, all DDL in backend schema files
4. **Phase 4** — ✅ COMPLETE — Consolidated interfaces (deleted 3 dead files), moved `_archive/` to `archive_vitalgraph_old/db_postgresql/`, verified all cross-cutting concerns

Each phase is independently shippable and testable.
