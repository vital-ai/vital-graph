# VitalGraph Codebase Simplification Plan

**Date:** 2026-03-11
**Scope:** `vitalgraph/` package — identify dead code, empty stubs, unused modules, and simplification opportunities.

---

## 1. Empty Stub Files (Non-`__init__.py`)

**21 files** with zero content that add noise and false IDE/import signals.

### Backend stubs (never implemented)

| File | Notes |
|------|-------|
| `db/aurora_postgresql/aurora_postgresql_db_impl.py` | Empty; no plan to implement |
| `db/oxigraph/oxigraph_notification_impl.py` | Empty |
| `db/oxigraph/oxigraph_signal_impl.py` | Empty |
| `db/oxigraph/oxigraph_space_impl.py` | Empty |
| `db/oxigraph/oxigraph_sparql_impl.py` | Empty |
| `db/tidb/tidb_db_impl.py` | Empty |

**Action:** Delete `db/aurora_postgresql/`, `db/oxigraph/`, `db/tidb/` entirely. Remove corresponding `BackendType.OXIGRAPH` enum value and factory branches in `backend_config.py` if they only route to these stubs.

### Endpoint impl stubs

| File | Notes |
|------|-------|
| `endpoint/impl/data_export_impl.py` | Empty |
| `endpoint/impl/data_import_impl.py` | Empty |
| `endpoint/impl/graphs_impl.py` | Empty |
| `endpoint/impl/metaql_query_impl.py` | Empty |
| `endpoint/impl/metaql_update_impl.py` | Empty |
| `endpoint/impl/spaces_impl.py` | Empty |
| `endpoint/impl/sparql_impl.py` | Empty |
| `endpoint/impl/triples_impl.py` | Empty |
| `endpoint/impl/users_impl.py` | Empty |

**Action:** Delete all empty files in `endpoint/impl/`. If the directory becomes empty (or only has `__init__.py`), delete the directory.

### Endpoint stubs

| File | Notes |
|------|-------|
| `endpoint/metaql_query_endpoint.py` | Empty |
| `endpoint/metaql_update_endpoint.py` | Empty |

**Action:** Delete both.

### Utils

| File | Notes |
|------|-------|
| `utils/log_utils.py` | Empty |

**Action:** Delete.

---

## 2. Entirely Unused Modules

These packages have **zero external imports** — nothing in the codebase references them.

| Module | Contents | Lines | Notes |
|--------|----------|-------|-------|
| `task/` | `task_inf.py` (stub `TaskInf` class), `task_manager.py` (stub `TaskManager` class) | ~40 | Placeholder for Celery integration that was never built |
| `index/` | Just empty `__init__.py` | 0 | Completely empty package |
| `transfer/` | `transfer_utils.py` (16K) | ~400 | Never imported by anything |
| `service/graph/` | `vitalgraph_service_impl.py` (2406 lines) | ~2400 | Never imported outside its own directory. Large file, zero consumers |

**Action:** Delete `task/`, `index/`. Investigate `transfer/` and `service/graph/` — if genuinely unused, delete. If intended for future use, move to a `_planned/` directory outside the package or add a clear `# TODO: not yet integrated` header.

---

## 3. Impl Files in `impl/`

| File | Size | Purpose |
|------|------|---------|
| `impl/vitalgraph_impl.py` | 241 lines | Lightweight config/db-init helper — used by admin CLI and as a base for the app impl |
| `impl/vitalgraphapp_impl.py` | 688 lines | Full FastAPI application impl with endpoints, auth, websocket, etc. |

These serve **different purposes** and should remain separate. No action needed.

---

## 4. `db/mock/` vs `mock/`

Two separate mock directories:
- `db/mock/` — just an empty `__init__.py`
- `mock/` — the real mock client implementation (24 items)

**Action:** Delete `db/mock/` (empty). Verify `backend_config.py`'s `BackendType.MOCK` factory branch imports from `mock/`, not `db/mock/`.

---

## 5. Large Files — Splitting Candidates

| File | Lines | Notes |
|------|-------|-------|
| `endpoint/kgframes_endpoint.py` | 2734 | Largest endpoint |
| `endpoint/kgentities_endpoint.py` | 2285 | Second largest |
| `admin_cmd/vitalgraphdb_admin_cmd.py` | 2257 | CLI REPL |
| `client/vitalgraph_client.py` | 1871 | Client class |
| `sparql/kg_query_builder.py` | 1380 | Query builder |

These are not dead code but are candidates for decomposition if they contain logically distinct sections. **Low priority** — address only if maintenance cost is high.

---

## 6. `utils/test_data.py` in Production Code

`utils/test_data.py` (19K) contains test fixtures/data but lives inside the production `vitalgraph` package.

**Action:** Move to a test-only location (e.g., `vitalgraph_client_test/` or a dedicated `test_utils/` at the repo root). Verify it's not imported by production code.

---

## 7. Signal/Notification Overlap in `db/fuseki/`

| File | Size | Status |
|------|------|--------|
| `db/fuseki/fuseki_notification_impl.py` | Empty | Stub |
| `db/fuseki/fuseki_signal_impl.py` | Empty | Stub |
| `db/fuseki/fuseki_signal_manager.py` | Non-empty | Active no-op impl |

**Action:** Delete the two empty stubs. `fuseki_signal_manager.py` is the active implementation and should remain.

---

## 8. `graph_import_op.py` — Dead V1 Code

`ops/graph_import_op.py` (473 lines) has a `raise NotImplementedError` guard at line 299. Everything after line 299 is dead code referencing the archived `PostgreSQLSpaceDBImport`.

**Action:** Trim dead code after the `NotImplementedError`. Keep the validation/file-parsing logic that works. ~150 lines of dead import logic can be removed.

---

## Execution Order

| Phase | Scope | Risk | Effort |
|-------|-------|------|--------|
| **A** | Delete empty stubs (Sections 1, 4, 7) | Very low — zero-content files | 15 min |
| **B** | Delete unused modules (Section 2) | Low — verify zero imports first | 15 min |
| **C** | Merge dual impl (Section 3) | Medium — two active import sites | 30 min |
| **D** | Trim dead code in graph_import_op (Section 8) | Low | 10 min |
| **E** | Move test_data.py (Section 6) | Low — verify no production imports | 10 min |
| **F** | Large file decomposition (Section 5) | Medium-high — refactoring | Future |

Phases A–E are independently shippable. Phase F is optional/future.
