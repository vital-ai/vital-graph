# SPARQL-SQL V2 Backend Integration Plan

Integrating the V2 SPARQL-to-SQL pipeline as a new backend (`sparql_sql`) in the VitalGraph service.

**Date**: 2026-03-06
**Source**: `vitalgraph_sparql_sql/` (standalone test/dev package)
**Target**: `vitalgraph/db/sparql_sql/` (service backend)
**Status**: In Progress — pipeline migrated, backend interfaces next

---

## 1. Architecture Analysis

### 1.1 Current Call Chain (fuseki_postgresql)

```
main.py
  → VitalGraphAppImpl(app, config)
    → VitalGraphImpl(config)
      → reads BACKEND_TYPE env var (default: "fuseki_postgresql")
      → BackendFactory.create_space_backend() → FusekiPostgreSQLSpaceImpl
      → SpaceManager(db_impl=..., space_backend=...)

Endpoint request flow:
  → endpoint (e.g. kgentities_endpoint.py)
    → space_record = space_manager.get_space(space_id)
    → backend_impl = space_record.space_impl.get_db_space_impl()
    → backend_adapter = create_backend_adapter(backend_impl)
       → returns FusekiPostgreSQLBackendAdapter(backend_impl)
    → processor = KGEntityListProcessor(...)
    → processor.list_entities(backend_adapter=backend_adapter, ...)
      → backend_adapter.execute_sparql_query(space_id, sparql)
         → Fuseki HTTP query
```

### 1.2 Key Interfaces

| Interface | File | Purpose |
|-----------|------|---------|
| `SpaceBackendInterface` | `db/space_backend_interface.py` | Space lifecycle, quad ops, term ops |
| `SparqlBackendInterface` | `db/sparql_inf.py` | `execute_sparql_query()`, `execute_sparql_update()` |
| `DbImplInterface` | `db/db_inf.py` | Low-level DB: connect, disconnect, transactions |
| `KGBackendInterface` | `kg_impl/kg_backend_utils.py` | High-level KG: store_objects, execute_sparql, update_quads |
| `BackendType` enum | `db/backend_config.py` | Backend selection: POSTGRESQL, FUSEKI, FUSEKI_POSTGRESQL, etc. |
| `BackendFactory` | `db/backend_config.py` | Factory methods for space/sparql/signal backends |

### 1.3 How Endpoints Consume Backends

Every endpoint follows this pattern (from code inspection):

```python
# In endpoint method:
space_record = self.space_manager.get_space(space_id)
space_impl = space_record.space_impl
backend_impl = space_impl.get_db_space_impl()  # returns the SpaceBackendInterface

# Then one of:
backend_adapter = create_backend_adapter(backend_impl)  # → KGBackendInterface
# or:
backend = FusekiPostgreSQLBackendAdapter(backend_impl)   # hardcoded adapter
```

The `create_backend_adapter()` factory in `kg_backend_utils.py` currently always returns
`FusekiPostgreSQLBackendAdapter` regardless of backend type. This must be updated.

### 1.4 What the kg_impl Layer Uses

The `KGBackendInterface` (consumed by all kg_impl processors) requires:

| Method | Used By | Notes |
|--------|---------|-------|
| `store_objects(space_id, graph_id, objects)` | Create/update processors | VitalSigns → RDF quads → backend |
| `object_exists(space_id, graph_id, uri)` | Create/delete processors | SPARQL ASK query |
| `delete_object(space_id, graph_id, uri)` | Delete processors | SPARQL UPDATE or quad removal |
| `execute_sparql_query(space_id, query)` | All read processors, SPARQL query processor | SELECT/CONSTRUCT/ASK |
| `validate_parent_connection(...)` | Frame creation | SPARQL ASK |
| `update_quads(space_id, graph_id, delete_quads, insert_quads)` | Update processors | Atomic delete+insert |

Additional methods on `FusekiPostgreSQLBackendAdapter` (not in abstract interface):
- `get_entity()`, `get_entity_graph()`, `get_object()`
- `_triples_to_vitalsigns()`
- Uses `GraphObjectRetriever` for centralized triple retrieval

### 1.5 Current fuseki_postgresql Architecture

```
FusekiPostgreSQLSpaceImpl (implements SpaceBackendInterface)
├── FusekiDatasetManager     — Fuseki HTTP API for datasets
├── FusekiPostgreSQLDbImpl   — PostgreSQL via asyncpg (DbImplInterface)
├── DualWriteCoordinator     — Syncs Fuseki + PostgreSQL writes
├── SPARQLUpdateParser       — Parses SPARQL updates via rdflib
├── FusekiPostgreSQLSpaceGraphs — Graph management
├── PostgreSQLSignalManager  — PostgreSQL LISTEN/NOTIFY signals
├── EntityLockManager        — Advisory locks for entities
├── FusekiPostgreSQLDbObjects — Object-level DB operations
└── FusekiPostgreSQLDbOps    — Low-level quad operations
```

### 1.6 V2 Pipeline Architecture (what gets copied)

```
vitalgraph_sparql_sql/
├── jena_sparql/               — Canonical Jena sidecar interface (copied as a unit)
│   ├── jena_types.py          — Shared AST types (Op, UpdateOp, Expr, etc.)
│   ├── jena_ast_mapper.py     — Sidecar JSON → Python Op tree
│   └── jena_sidecar_client.py — HTTP client to Jena sidecar
├── jena_sparql_orchestrator.py — Compile → generate → execute orchestrator
├── db.py                      — asyncpg connection pool + query utilities
└── sparql_sql/                — V2 SQL generation pipeline
    ├── generator.py           — Main entry: Op tree → SQL
    ├── ir.py                  — Internal representation (PlanV2, TableRef, etc.)
    ├── collect.py             — Collect variable metadata from Op tree (singledispatch)
    ├── var_scope.py           — Variable scope analysis
    ├── emit.py                — Main emit dispatcher
    ├── emit_bgp.py            — BGP → SQL
    ├── emit_expressions.py    — SPARQL expressions → SQL
    ├── emit_update.py         — SPARQL UPDATE → SQL
    ├── emit_*.py              — Other emitters (join, union, filter, etc.)
    ├── rewrite_*.py           — MV rewrite optimizations
    ├── filter_pushdown.py     — Filter pushdown optimization
    ├── sql_type_*.py          — Type binding/generation
    ├── db_provider.py         — Shim decoupling pipeline from specific db module
    └── ... (37 files total)
```

**Note**: `jena_sparql/` is the single canonical source of truth for all Jena
AST types. Both `sparql_sql/` and parent-level files import from it via
`from ..jena_sparql.jena_types import ...` or `from .jena_sparql.jena_types import ...`.
This ensures a single class identity for `singledispatch` and `isinstance` checks.

---

## 2. New Backend: `sparql_sql`

### 2.1 Key Differences from fuseki_postgresql

| Aspect | fuseki_postgresql | sparql_sql |
|--------|------------------|------------|
| **SPARQL queries** | Fuseki HTTP endpoint | V2 pipeline: SPARQL → SQL → PostgreSQL |
| **SPARQL updates** | DualWriteCoordinator → Fuseki + PG | V2 pipeline: SPARQL → SQL → PostgreSQL |
| **Data writes** | Dual-write (Fuseki + PostgreSQL) | PostgreSQL only |
| **External deps** | Fuseki server + Jena sidecar | Jena sidecar only |
| **Schema** | Same `{space_id}_term` + `{space_id}_rdf_quad` | Same schema (compatible) |
| **Connection lib** | asyncpg | asyncpg (async only) |
| **Query execution** | Async (Fuseki HTTP) | Native async (asyncpg) |

### 2.2 Current Directory Structure (✅ MIGRATED)

The V2 pipeline has been migrated into the main `vitalgraph` package.
The original source files have been removed from `vitalgraph_sparql_sql/`
(only test files and dev helpers remain there).

```
vitalgraph/db/
├── jena_sparql/                   — ✅ Jena sidecar types + client (migrated)
│   ├── __init__.py
│   ├── jena_types.py              — Shared AST types (Op, Expr, UpdateOp, etc.)
│   ├── jena_ast_mapper.py         — Sidecar JSON → Python Op tree
│   └── jena_sidecar_client.py     — Async HTTP client to Jena sidecar
│
├── sparql_sql/                    — ✅ V2 pipeline + backend implementation
│   ├── __init__.py
│   ├── sparql_sql_db_impl.py      — ✅ SparqlSQLDbImpl (DbImplInterface, owns asyncpg pool)
│   ├── db_provider.py             — ✅ Imports DbImplInterface from ..db_inf, configured at startup
│   ├── generator.py               — Main entry: CompileResult → SQL
│   ├── ir.py                      — PlanV2 IR, AliasGenerator
│   ├── collect.py                 — Op tree → PlanV2 IR
│   ├── emit.py                    — PlanV2 → SQL dispatcher
│   ├── emit_bgp.py                — BGP → SQL
│   ├── emit_expressions.py        — SPARQL expressions → SQL
│   ├── emit_update.py             — SPARQL UPDATE → SQL
│   ├── emit_*.py                  — Other emitters (join, union, filter, etc.)
│   ├── rewrite_*.py               — MV rewrite optimizations
│   ├── filter_pushdown.py         — Filter pushdown optimization
│   ├── sql_type_binding.py        — SQL ↔ SPARQL type binding
│   ├── sql_type_generation.py     — TypeRegistry, ColumnInfo, TypedExpr
│   ├── var_scope.py               — Variable scope analysis
│   ├── ensure_mv.py               — Materialized view management
│   ├── reorder_bgp.py             — BGP join reordering
│   │
│   │ # NOT YET IMPLEMENTED (service integration):
│   ├── sparql_sql_space_impl.py   — TODO: SpaceBackendInterface implementation
│   ├── sparql_sql_sparql_impl.py  — TODO: SparqlBackendInterface wrapper
│   ├── sparql_sql_schema.py       — TODO: Space table DDL
│   └── sparql_sql_backend_adapter.py — TODO: KGBackendInterface adapter
```

**Remaining in `vitalgraph_sparql_sql/`** (dev/test only):
- `db.py` — Dev asyncpg pool + `DevDbImpl` (DbImplInterface for DAWG tests)
- `jena_sparql_orchestrator.py` — Dev orchestrator (uses vitalgraph.db.* imports)
- `dawg_test_impl/` — DAWG test harness (updated to import from vitalgraph.db.*)
- `sparql_sql/test_*.py` — Unit tests
- `sparql_sql/debug_sparql.py` — Debug CLI tool

### 2.3 Migration (✅ COMPLETED)

The migration has been completed. The original pipeline files have been **removed**
from `vitalgraph_sparql_sql/sparql_sql/` and `vitalgraph_sparql_sql/jena_sparql/`.

### 2.4 Import Structure (✅ VERIFIED)

All imports verified at runtime and DAWG tests pass (313/338, 100% pass rate).

**Within `vitalgraph/db/sparql_sql/`** (pipeline files):
- `from ..jena_sparql.jena_types import ...` — sibling package under `db/`
- `from ..db_inf import DbImplInterface` — parent `db/` package
- `from .ir import ...`, `from .emit_context import ...` — intra-package

**Within `vitalgraph/db/jena_sparql/`:**
- `from .jena_types import ...` — internal only, no external imports

**DAWG test harness** (`vitalgraph_sparql_sql/dawg_test_impl/`):
- Uses absolute imports: `from vitalgraph.db.sparql_sql.generator import ...`
- Uses absolute imports: `from vitalgraph.db.jena_sparql.jena_types import ...`
- Uses `from vitalgraph.db.sparql_sql import db_provider` for pipeline DB access
- Uses `from ..db import DevDbImpl` for dev pool creation

**Dev orchestrator** (`vitalgraph_sparql_sql/jena_sparql_orchestrator.py`):
- Uses `from vitalgraph.db.jena_sparql.* import ...`
- Uses `from vitalgraph.db.sparql_sql import db_provider`
- Uses `from vitalgraph.db.sparql_sql.generator import ...`

**Test files** (`test_*.py`) remain in `vitalgraph_sparql_sql/sparql_sql/`.

---

## 3. Interface Implementation Guide

This section maps each service interface to the concrete methods the `sparql_sql`
backend must implement, with the handoff chain that connects them.

### 3.0 Full Handoff Chain

```
Startup:
  VitalGraphImpl.__init__()                   # vitalgraph/impl/vitalgraph_impl.py
    → BackendFactory.create_space_backend()   # vitalgraph/db/backend_config.py
      → SparqlSQLSpaceImpl(config)            # NEW: vitalgraph/db/sparql_sql/sparql_sql_space_impl.py
    → SpaceManager(db_impl=..., space_backend=space_impl)
    
  VitalGraphImpl.connect_database()
    → space_backend.connect()                 # asyncpg pool init + sidecar health check
    → space_manager.initialize_from_database()
      → space_backend.list_spaces()
      → SpaceImpl(space_id, backend=space_backend) per space

Request:
  Endpoint handler
    → space_record = space_manager.get_space(space_id)
    → backend_impl = space_record.space_impl.get_db_space_impl()   # returns SparqlSQLSpaceImpl
    → adapter = create_backend_adapter(backend_impl)               # returns SparqlSQLBackendAdapter
    → adapter.execute_sparql_query(space_id, sparql)
      → space_impl.query_quads(space_id, sparql)
        → sparql_impl.execute_sparql_query(space_id, sparql)
          → SparqlOrchestrator.execute(sparql)                     # V2 pipeline
```

### 3.1 Interface: `SpaceBackendInterface` → `SparqlSQLSpaceImpl`

**Source**: `vitalgraph/db/space_backend_interface.py`
**Target**: `vitalgraph/db/sparql_sql/sparql_sql_space_impl.py`

This is the **main backend class**. It is the object that `SpaceManager` holds as
`space_backend` and that `SpaceImpl` holds as `backend`. Every endpoint ultimately
delegates to this object.

```python
from ..space_backend_interface import SpaceBackendInterface, SparqlBackendInterface

class SparqlSQLSpaceImpl(SpaceBackendInterface):
    """PostgreSQL-only space backend using V2 SPARQL-to-SQL pipeline."""
    
    def __init__(self, postgresql_config: dict, sidecar_config: dict):
        self.postgresql_config = postgresql_config
        self.sidecar_config = sidecar_config
        self.pool = None           # asyncpg.Pool
        self.orchestrator = None   # SparqlOrchestrator (V2 pipeline)
        self.connected = False
```

**Required abstract methods** (grouped by category):

#### Connection & Lifecycle

| Method | Notes |
|--------|-------|
| `async connect() -> bool` | Create `asyncpg.create_pool()`, init `SparqlOrchestrator`, verify sidecar health |
| `async disconnect() -> bool` | Close asyncpg pool, close sidecar httpx client |
| `close() -> None` | Sync close (call `disconnect()` via `asyncio`) |
| `async get_db_connection()` | `@asynccontextmanager` — yield `self.pool.acquire()` |

#### Space Management

| Method | V2 Pipeline Equivalent | Notes |
|--------|----------------------|-------|
| `async create_space_storage(space_id) -> bool` | DDL from DAWG `dawg_space_manager.create_space_tables()` | CREATE `{space_id}_term`, `{space_id}_rdf_quad`, indexes |
| `async delete_space_storage(space_id) -> bool` | DDL DROP | DROP tables + remove from admin table |
| `async space_exists(space_id) -> bool` | — | Check `pg_tables` or admin table |
| `async list_spaces() -> List[str]` | — | Query admin table → `[{'space_id': ...}, ...]` |
| `async get_space_info(space_id) -> Dict` | — | Quad count, table sizes, etc. |
| `async create_space_metadata(space_id, metadata) -> bool` | — | Insert into admin table (space_name, description, tenant) |

#### Term Management

| Method | Notes |
|--------|-------|
| `async add_term(space_id, term_text, term_type, lang=None, datatype_id=None) -> Optional[str]` | INSERT INTO `{space_id}_term` RETURNING `term_uuid` |
| `async get_term_uuid(space_id, term_text, term_type, lang=None, datatype_id=None) -> Optional[str]` | SELECT `term_uuid` FROM `{space_id}_term` WHERE ... |
| `async delete_term(space_id, term_text, term_type, ...) -> bool` | DELETE FROM `{space_id}_term` |

#### RDF Quad Operations

| Method | Notes |
|--------|-------|
| `async add_rdf_quad(space_id, quad) -> bool` | Single quad insert — ensure terms, insert quad |
| `async remove_rdf_quad(space_id, s, p, o, g) -> bool` | DELETE by term_text lookups |
| `async get_rdf_quad(space_id, s, p, o, g) -> bool` | EXISTS check |
| `async get_rdf_quad_count(space_id, graph_uri=None) -> int` | COUNT(*) on `{space_id}_rdf_quad` |
| `async add_rdf_quads_batch(space_id, quads, ...) -> int` | **Critical path** — bulk term + quad insert, adapt from `fuseki_postgresql_db_ops.py` |
| `async remove_rdf_quads_batch(space_id, quads) -> int` | Bulk delete |
| `async quads(space_id, quad_pattern, context=None)` | Generator — pattern match via SQL |

#### Namespace Management

| Method | Notes |
|--------|-------|
| `async add_namespace(space_id, prefix, namespace_uri) -> Optional[int]` | INSERT into namespace table (create if needed) |
| `async get_namespace_uri(space_id, prefix) -> Optional[str]` | SELECT |
| `async list_namespaces(space_id) -> List[Dict]` | SELECT all |

#### SPARQL Integration

| Method | Notes |
|--------|-------|
| `get_sparql_impl(space_id) -> SparqlBackendInterface` | Return `self` (implements SPARQL interface directly) |
| `async execute_sparql_query(space_id, query) -> Dict` | Delegate to V2 pipeline (see §3.2) |
| `async execute_sparql_update(space_id, update) -> bool` | Delegate to V2 pipeline |
| `async query_quads(space_id, sparql_query) -> List[tuple]` | **Used by KG adapter** — SPARQL → V2 → results |

#### Utility

| Method | Notes |
|--------|-------|
| `get_manager_info() -> Dict` | Return `{'backend_type': 'sparql_sql', ...}` |
| `async drop_indexes_for_bulk_load(space_id) -> bool` | DROP indexes on quad/term tables |
| `async recreate_indexes_after_bulk_load(space_id) -> bool` | CREATE INDEX CONCURRENTLY |

### 3.2 Interface: `SparqlBackendInterface` → built into `SparqlSQLSpaceImpl`

**Source**: `vitalgraph/db/space_backend_interface.py` (lines 397–434)

The `SparqlSQLSpaceImpl` implements `SparqlBackendInterface` directly
(returns `self` from `get_sparql_impl()`).

```python
# In SparqlSQLSpaceImpl:

async def execute_sparql_query(self, space_id: str, query: str, **kwargs) -> Dict[str, Any]:
    """Execute SPARQL query via V2 pipeline."""
    from .jena_sparql_orchestrator import SparqlOrchestrator
    # orchestrator is initialized during connect() with space_id, pool, sidecar
    result = await self.orchestrator.execute(query)
    # Convert SparqlResults → SPARQL JSON Results format
    return self._format_sparql_results(result)

async def execute_sparql_update(self, space_id: str, update: str, **kwargs) -> bool:
    """Execute SPARQL UPDATE via V2 pipeline."""
    from .sparql_sql_pipeline.generator import generate_sql
    from .jena_sparql.jena_ast_mapper import map_compile_response
    from .jena_sparql.jena_sidecar_client import AsyncSidecarClient
    # compile → generate → execute SQL in transaction
    ...
```

Only 2 abstract methods:
- `execute_sparql_query(space_id, query, **kwargs) -> Dict[str, Any]`
- `execute_sparql_update(space_id, update, **kwargs) -> bool`

### 3.3 Interface: `DbImplInterface` → `SparqlSQLDbImpl`

**Source**: `vitalgraph/db/db_inf.py`
**Target**: `vitalgraph/db/sparql_sql/sparql_sql_db_impl.py`

Required by `VitalGraphImpl` as `self.db_impl`. Used by `SpaceManager` and
`SignalManager`. Wraps the asyncpg pool with the standard service interface.

```python
from ..db_inf import DbImplInterface

class SparqlSQLDbImpl(DbImplInterface):
    """Pure-PostgreSQL database implementation for the sparql_sql backend.
    
    Owns its own asyncpg pool — no Fuseki dependency.
    The pipeline's db_provider.configure() accepts this instance and
    uses connection_pool for all SQL operations.
    """
    
    def __init__(self, postgresql_config: dict):
        self.config = postgresql_config
        self.connection_pool = None  # asyncpg.Pool — required by db_provider
        self._connected = False
        self._signal_manager = None
```

| Method | Notes |
|--------|-------|
| `async connect() -> bool` | `asyncpg.create_pool(dsn)` |
| `async disconnect() -> bool` | `pool.close()` |
| `async is_connected() -> bool` | Return `self._connected` |
| `async execute_query(query, params=None) -> List[Dict]` | `pool.fetch(query, *params)` → list of dicts |
| `async execute_update(query, params=None) -> bool` | `pool.execute(query, *params)` |
| `async begin_transaction() -> Any` | `conn = pool.acquire(); txn = conn.transaction()` |
| `async commit_transaction(txn) -> bool` | `txn.commit()` |
| `async rollback_transaction(txn) -> bool` | `txn.rollback()` |
| `get_connection_info() -> Dict` | Return host, port, dbname |

**Additional methods** used by VitalGraphImpl:
- `set_signal_manager(sm)` / `get_signal_manager()` — store/return signal manager
- `is_connected()` — sync version (used by SpaceManager init check)

**Key design**: `SparqlSQLDbImpl` and `SparqlSQLSpaceImpl` should **share** the
same asyncpg pool. Either `SparqlSQLSpaceImpl` owns the pool and passes it to
`SparqlSQLDbImpl`, or `SparqlSQLDbImpl` owns it and `SparqlSQLSpaceImpl`
references it.

### 3.4 Interface: `KGBackendInterface` → `SparqlSQLBackendAdapter`

**Source**: `vitalgraph/kg_impl/kg_backend_utils.py`
**Target**: `vitalgraph/db/sparql_sql/sparql_sql_backend_adapter.py`

This adapter is created by `create_backend_adapter()` and consumed by all
`kg_impl` processors (KGEntity, KGFrame, KGType, Objects endpoints).

```python
from ..kg_impl.kg_backend_utils import KGBackendInterface, BackendOperationResult
from ..kg_impl.kg_graph_retrieval_utils import GraphObjectRetriever

class SparqlSQLBackendAdapter(KGBackendInterface):
    """Adapter for sparql_sql backend, consumed by kg_impl processors."""
    
    def __init__(self, backend_impl: SparqlSQLSpaceImpl):
        self.backend = backend_impl
        self.retriever = GraphObjectRetriever(backend_impl)
```

| Method | Delegation | Notes |
|--------|-----------|-------|
| `store_objects(space_id, graph_id, objects)` | VitalSigns→RDF→quads→`backend.add_rdf_quads_batch()` | Convert objects to RDF quads, bulk insert |
| `object_exists(space_id, graph_id, uri)` | SPARQL ASK via `backend.query_quads()` | |
| `delete_object(space_id, graph_id, uri)` | SPARQL UPDATE DELETE or direct quad removal | |
| `execute_sparql_query(space_id, query)` | `backend.execute_sparql_query()` → SPARQL JSON Results | |
| `validate_parent_connection(space_id, graph_id, parent, child)` | SPARQL ASK | |
| `update_quads(space_id, graph_id, delete_quads, insert_quads)` | Transaction: `remove_rdf_quads_batch` + `add_rdf_quads_batch` | |

**Additional methods** (not in abstract interface, used by endpoints):
- `get_entity(space_id, graph_id, uri)` → uses `GraphObjectRetriever`
- `get_entity_graph(space_id, graph_id, uri)` → uses `GraphObjectRetriever`
- `get_object(space_id, graph_id, uri)` → uses `GraphObjectRetriever`

### 3.5 Registration Points (existing files to modify)

#### `vitalgraph/db/backend_config.py` — BackendType + BackendFactory

```python
# Add to BackendType enum:
SPARQL_SQL = "sparql_sql"

# Add to BackendFactory.create_space_backend():
elif config.backend_type == BackendType.SPARQL_SQL:
    from .sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl
    return SparqlSQLSpaceImpl(**config.connection_params)

# Add to BackendFactory.create_sparql_backend():
elif config.backend_type == BackendType.SPARQL_SQL:
    from .sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl
    space_impl = SparqlSQLSpaceImpl(**config.connection_params)
    return space_impl  # implements SparqlBackendInterface directly

# Add to BackendFactory.create_signal_manager():
elif config.backend_type == BackendType.SPARQL_SQL:
    from .sparql_sql.sparql_sql_signal_manager import SparqlSQLSignalManager
    return SparqlSQLSignalManager(**signal_config)
```

#### `vitalgraph/impl/vitalgraph_impl.py` — Backend initialization

```python
elif backend_type == 'sparql_sql':
    sparql_sql_config = self.config.get_sparql_sql_config()
    backend_config_obj = BackendConfig(
        backend_type=BackendType.SPARQL_SQL,
        connection_params=sparql_sql_config
    )
    self.space_backend = BackendFactory.create_space_backend(backend_config_obj)
    # db_impl wraps the same asyncpg pool
    self.db_impl = self.space_backend.db_impl
```

In `connect_database()`, after the pool is connected, configure the pipeline's
`db_provider` with the service's `DbImplInterface` implementation directly:

```python
# After space_backend.connect() succeeds:
from vitalgraph_sparql_sql.sparql_sql import db_provider
db_provider.configure(self.space_backend.db_impl)
# SparqlSQLDbImpl implements DbImplInterface and owns its own asyncpg pool
```

No adapter class needed — `db_provider.py` imports `DbImplInterface` from
`vitalgraph.db.db_inf` and uses the implementation's `connection_pool`
(asyncpg.Pool) directly for all SQL operations.  `SparqlSQLDbImpl` is the
new pure-PostgreSQL backend's own `DbImplInterface` implementation — it has
no Fuseki dependency.

#### `vitalgraph/kg_impl/kg_backend_utils.py` — Adapter factory

```python
def create_backend_adapter(backend_impl) -> KGBackendInterface:
    backend_type = type(backend_impl).__name__
    if 'SparqlSQL' in backend_type:
        from ..db.sparql_sql.sparql_sql_backend_adapter import SparqlSQLBackendAdapter
        return SparqlSQLBackendAdapter(backend_impl)
    elif 'FusekiPostgreSQL' in backend_type:
        return FusekiPostgreSQLBackendAdapter(backend_impl)
    else:
        return FusekiPostgreSQLBackendAdapter(backend_impl)
```

#### `vitalgraph/config/config_loader.py` — Config section

```python
def get_sparql_sql_config(self) -> dict:
    return {
        'database': {
            'host': self._get_profile_env('DB_HOST', 'localhost'),
            'port': int(self._get_profile_env('DB_PORT', '5432')),
            'database': self._get_profile_env('DB_NAME', 'vitalgraph'),
            'username': self._get_profile_env('DB_USERNAME', 'postgres'),
            'password': self._get_profile_env('DB_PASSWORD', ''),
        },
        'sidecar': {
            'url': self._get_profile_env('SIDECAR_URL', 'http://localhost:7070'),
        },
    }
```

### 3.6 `sparql_sql_schema.py` — Space DDL

Helper for creating/dropping per-space tables. Not an interface implementation.

```python
class SparqlSQLSchema:
    """DDL management for sparql_sql backend spaces."""
    
    async def create_space_tables(self, conn, space_id: str) -> bool:
        # CREATE {space_id}_term (term_uuid, term_text, term_type, lang, dataset)
        # CREATE {space_id}_rdf_quad (subject_uuid, predicate_uuid, object_uuid, context_uuid, ...)
        # CREATE indexes
        ...
    
    async def drop_space_tables(self, conn, space_id: str) -> bool: ...
    async def space_tables_exist(self, conn, space_id: str) -> bool: ...
    async def create_admin_tables(self, conn) -> bool:
        # CREATE vitalgraph_spaces (space_id, space_name, description, tenant, created_at)
        ...
```

### 3.7 `sparql_sql_signal_manager.py` — Signal Manager (deferred)

Implements `SignalManagerInterface`. Uses PostgreSQL LISTEN/NOTIFY (same as
fuseki_postgresql). Can be deferred to Phase 7 — the service works without it,
signals just won't fire.

---

## 4. Integration Points (Existing Files to Modify)

See §3.5 for concrete code changes to each file. Summary of files:

| File | Change |
|------|--------|
| `vitalgraph/db/backend_config.py` | Add `SPARQL_SQL` to `BackendType`, add factory branches |
| `vitalgraph/impl/vitalgraph_impl.py` | Add `elif backend_type == 'sparql_sql'` init block |
| `vitalgraph/kg_impl/kg_backend_utils.py` | Add `SparqlSQL` branch to `create_backend_adapter()` |
| `vitalgraph/config/config_loader.py` | Add `get_sparql_sql_config()` method |
| `vitalgraph/db/space_inf.py` | Add `SPARQL_SQL` to duplicate `BackendType` enum (if still used) |

---

## 5. Configuration

### 5.1 Environment Variables

```bash
# Select the sparql_sql backend
BACKEND_TYPE=sparql_sql

# PostgreSQL connection (same as fuseki_postgresql)
DB_HOST=localhost
DB_PORT=5432
DB_NAME=vitalgraph
DB_USERNAME=postgres
DB_PASSWORD=...

# Jena sidecar (SPARQL → AST compilation)
SIDECAR_URL=http://localhost:7070
```

### 5.2 No Fuseki Required

The `sparql_sql` backend does **not** require a Fuseki server. It requires:
1. **PostgreSQL** database (same instance as fuseki_postgresql uses)
2. **Jena sidecar** for SPARQL → algebra compilation

---

## 6. Async-Only Migration (COMPLETED)

### 6.1 Decision

**Async-only with asyncpg**: The V2 pipeline has been fully migrated to use
**asyncpg** exclusively. All sync code and psycopg3 dependencies have been
removed from the core pipeline. Sync functions were removed, and `async_*`
prefixed functions were renamed to their primary names (prefix dropped).

### 6.2 Library

| Layer | Library | Why |
|-------|---------|-----|
| **DB (all operations)** | asyncpg | Faster (C extension, binary protocol), LISTEN/NOTIFY, matches fuseki_postgresql backend |
| **Async HTTP** | httpx.AsyncClient | Sidecar compiler calls |

### 6.3 Async Components (primary names — no `async_` prefix)

| File | Functions/Classes |
|------|-------------------|
| `db.py` | `get_pool()`, `get_connection()`, `execute_query()`, `execute_scalar()`, `close_pool()`, `_pg_params_to_asyncpg()` |
| `jena_sparql/jena_sidecar_client.py` | `AsyncSidecarClient` (httpx.AsyncClient) |
| `sparql_sql/generator.py` | `generate_sql()`, `materialize_constants()`, `warm_stats_cache()` |
| `sparql_sql/ensure_mv.py` | `ensure_edge_mv()`, `ensure_frame_entity_mv()` |
| `sparql_sql/emit_update.py` | `update_to_sql()`, `_dispatch_one()`, `_modify_sql()`, `_delete_where_sql()` |
| `jena_sparql_orchestrator.py` | `SparqlOrchestrator` (was `AsyncSparqlOrchestrator`) |
| `sparql_sql/db_provider.py` | `execute_query()`, `execute_scalar()`, `get_connection()` (shim delegates) |

### 6.4 Architecture

The collect/emit pipeline is **pure** (zero DB calls) — no async needed there.
Only 5 DB-touching layers are async:
1. Connection pool (`db.py`) — `asyncpg.create_pool()`
2. Sidecar HTTP client — `httpx.AsyncClient`
3. Constant materialization + stats + datatype loading (`generator.py`)
4. MV existence checks + DDL creation (`ensure_mv.py`)
5. UPDATE WHERE clause compilation (`emit_update.py`)

Note: `db.py` includes `_pg_params_to_asyncpg()` which auto-converts `%s`
placeholders to `$1, $2, ...` so pipeline callers don't need to change.

### 6.5 Service Integration

The `sparql_sql_sparql_impl.py` (to be created) will use
`SparqlOrchestrator` directly — no `asyncio.to_thread()` wrapper needed.

```python
async def execute_sparql_query(self, space_id, sparql_query):
    result = await self.orchestrator.execute(sparql_query)
    return result
```

---

## 7. Schema Compatibility

The V2 pipeline expects these tables per space:

```sql
{space_id}_term (
    term_uuid  UUID PRIMARY KEY,
    term_text  TEXT NOT NULL,
    term_type  CHAR(1) NOT NULL,  -- 'U', 'L', 'B'
    lang       VARCHAR(20),
    dataset    VARCHAR(50) DEFAULT 'primary'
)

{space_id}_rdf_quad (
    subject_uuid   UUID NOT NULL,
    predicate_uuid UUID NOT NULL,
    object_uuid    UUID NOT NULL,
    context_uuid   UUID NOT NULL,
    quad_uuid      UUID DEFAULT gen_random_uuid(),
    dataset        VARCHAR(50) DEFAULT 'primary'
)
```

This is the **same schema** used by the existing PostgreSQL backend and the DAWG
test runner. Spaces created by either backend are compatible — data stored by
`fuseki_postgresql` can be queried by `sparql_sql` and vice versa.

---

## 8. Implementation Phases

### Phase 1: Copy and Verify Pipeline (1 day)

- [ ] Create `vitalgraph/db/sparql_sql/sparql_sql_pipeline/` directory
- [ ] Copy V2 pipeline files with `cp` (exclude test_*.py)
- [ ] Copy `jena_sparql/` directory (jena_types, jena_ast_mapper, jena_sidecar_client)
- [ ] Copy shared infrastructure files (jena_sparql_orchestrator, db)
- [ ] Rewire `db_provider.py` shim to point at service db module
- [ ] Verify imports resolve: `python -c "from vitalgraph.db.sparql_sql.sparql_sql_pipeline.generator import generate_sql"`

### Phase 2: Database + Schema Layer (1 day)

- [ ] Implement `sparql_sql_db_impl.py` — psycopg3 connection pool, DbImplInterface
- [ ] Implement `sparql_sql_schema.py` — space table DDL (CREATE/DROP/EXISTS)
- [ ] Implement admin tables for space registry
- [ ] Test: create a space, verify tables exist, drop it

### Phase 3: SPARQL Implementation (1-2 days)

- [ ] Implement `sparql_sql_sparql_impl.py` — wrap V2 pipeline
- [ ] Wire sidecar client → AST mapper → generator → SQL execution
- [ ] Handle SELECT result formatting (V2 returns raw rows → convert to SPARQL JSON bindings)
- [ ] Handle UPDATE execution (V2 generates SQL → execute in transaction)
- [ ] Handle ASK, CONSTRUCT query types
- [ ] Test: execute SPARQL queries against a test space

### Phase 4: Space Backend (1 day)

- [ ] Implement `sparql_sql_space_impl.py` — full SpaceBackendInterface
- [ ] Implement RDF quad batch operations (add/remove)
- [ ] Implement term management operations
- [ ] Implement space lifecycle (create/delete/exists/list)
- [ ] Wire `get_sparql_impl()` to return the SPARQL implementation

### Phase 5: KG Backend Adapter (1 day)

- [ ] Implement `sparql_sql_backend_adapter.py` — KGBackendInterface
- [ ] Implement `store_objects()` — VitalSigns → RDF → quads → PostgreSQL
- [ ] Implement `execute_sparql_query()` — SPARQL → V2 pipeline → results
- [ ] Implement `update_quads()` — atomic delete+insert via PostgreSQL transaction
- [ ] Implement `object_exists()`, `delete_object()`, `validate_parent_connection()`
- [ ] Update `create_backend_adapter()` factory in `kg_backend_utils.py`

### Phase 6: Config + Factory Integration (0.5 day)

- [ ] Add `SPARQL_SQL` to `BackendType` enum
- [ ] Add factory methods in `BackendFactory`
- [ ] Add `sparql_sql` config section to `config_loader.py`
- [ ] Add `sparql_sql` handling in `vitalgraph_impl.py`
- [ ] Test: start server with `BACKEND_TYPE=sparql_sql`, verify startup

### Phase 7: End-to-End Testing (1-2 days)

- [ ] Start service with `sparql_sql` backend
- [ ] Create a space via REST API
- [ ] Create KGTypes, KGEntities, KGFrames via REST API
- [ ] Query entities via REST API (verify SPARQL → SQL → results)
- [ ] Update and delete entities
- [ ] Verify all kg_impl operations work through the adapter
- [ ] Cross-backend compatibility: read fuseki_postgresql data with sparql_sql

---

## 9. Risk Areas

### 9.1 SPARQL Result Format

The V2 pipeline returns SQL result rows. The kg_impl layer expects SPARQL JSON
binding format (`{'var': {'type': 'uri', 'value': '...'}}` or similar).
The `SparqlSQLSparqlImpl` must translate between these formats.

The existing `FusekiPostgreSQLBackendAdapter.execute_sparql_query()` delegates to
Fuseki which returns standard SPARQL JSON Results. The new `SparqlSQLBackendAdapter`
must produce the same format from V2 pipeline output (pure PostgreSQL, no Fuseki).

### 9.2 SPARQL Query Patterns from kg_impl

The kg_impl layer generates SPARQL queries using `KGSparqlQueryBuilder` and
`KGSparqlUtils`. These queries use patterns like:
- `GRAPH <uri> { ... }` — named graph scoping
- `SELECT DISTINCT ?subject WHERE { ... } ORDER BY ?subject LIMIT N OFFSET M`
- `ASK { GRAPH <g> { <uri> ?p ?o } }`
- `CONSTRUCT { ?s ?p ?o } WHERE { GRAPH <g> { ?s ?p ?o } }`

The V2 pipeline handles all these patterns. GRAPH clause support is fully
implemented in `collect.py` (`@collect.register(OpGraph)`) handling both
`GRAPH <uri>` and `GRAPH ?var` with proper `context_uuid` scoping. Property
paths inside GRAPH are also supported via `emit_path.py` graph_uri/graph_var
propagation. The DAWG tests that were skipped for GRAPH features were skipped
due to the pyoxigraph oracle limitation, not a V2 pipeline gap.

### 9.3 Connection Management

The V2 pipeline currently uses a simple `psycopg.connect()` call per operation.
For the service backend, we need a connection pool to handle concurrent requests.
`psycopg_pool.ConnectionPool` is the appropriate choice.

### 9.4 Quad Write Operations

The fuseki_postgresql backend uses `DualWriteCoordinator` which converts
VitalSigns objects to RDF quads and inserts them. The sparql_sql backend needs
equivalent functionality but writing only to PostgreSQL. The quad insertion logic
from `fuseki_postgresql_db_ops.py` can be adapted.

---

## 10. Open Questions for Discussion

1. ~~**Async strategy**~~: **RESOLVED** — Native async implemented in V2 pipeline.
   See §6 for details.

2. **Signal manager**: The fuseki_postgresql backend has `PostgreSQLSignalManager`
   for LISTEN/NOTIFY. Should the sparql_sql backend also support this, or defer?

3. **Entity lock manager**: Should the sparql_sql backend support advisory locks
   for concurrent entity updates, or defer?

4. **Graph management**: The fuseki_postgresql backend has
   `FusekiPostgreSQLSpaceGraphs` for named graph tracking. Does the sparql_sql
   backend need equivalent functionality?

5. **Edge materialized views**: The V2 pipeline supports `frame_entity_mv` and
   `edge_mv` rewrites for performance. Should `create_space_storage()` also
   create these MVs, or defer until performance testing?

6. **Shared code vs copied code**: The V2 pipeline files are copied (not imported)
   to maintain independence. Should we eventually refactor to a shared package,
   or keep the copy-based approach?

---

## 11. Success Criteria

- [ ] Server starts with `BACKEND_TYPE=sparql_sql`
- [ ] Space CRUD operations work via REST API
- [ ] KGType CRUD operations work via REST API
- [ ] KGEntity CRUD operations work via REST API (including entity graphs)
- [ ] KGFrame CRUD operations work via REST API
- [ ] KGRelation CRUD operations work via REST API
- [ ] SPARQL queries from kg_impl produce correct results
- [ ] SPARQL updates from kg_impl execute correctly
- [ ] No regressions when running with fuseki_postgresql backend

---

## 12. Completion Tracking

### Phase 1: Pipeline Migration (✅ COMPLETE — 2026-03-06)

| Step | Status | Notes |
|------|--------|-------|
| Copy `jena_sparql/` → `vitalgraph/db/jena_sparql/` | ✅ | 4 files, no import changes needed |
| Copy `sparql_sql/` pipeline → `vitalgraph/db/sparql_sql/` | ✅ | 31 files (excluding test_*.py) |
| Implement `SparqlSQLDbImpl` | ✅ | `vitalgraph/db/sparql_sql/sparql_sql_db_impl.py` — owns asyncpg pool |
| Fix `db_provider.py` import | ✅ | `from ..db_inf import DbImplInterface` (relative) |
| Fix `debug_sparql.py` imports | ✅ | Uses `vitalgraph.db.*` absolute imports |
| Update DAWG test runner | ✅ | `dawg_test_runner.py`, `dawg_sql_v2_executor.py` — absolute imports |
| Update dev orchestrator | ✅ | `jena_sparql_orchestrator.py` — absolute imports to `vitalgraph.db.*` |
| Remove old source files | ✅ | `sparql_sql/` pipeline files + `jena_sparql/` dir removed |
| Verify DAWG tests pass | ✅ | 313/338 passed, 0 failures, 100% pass rate |

### Phase 2: Service Integration (✅ COMPLETE — 2026-03-06)

| Step | Status | Notes |
|------|--------|-------|
| Add `SPARQL_SQL` to `BackendType` enum | ✅ | `vitalgraph/db/backend_config.py` |
| Implement `SparqlSQLSchema` | ✅ | `sparql_sql_schema.py` — DDL + indexes + datatype seeds |
| Implement `SparqlSQLSpaceImpl` | ✅ | `SpaceBackendInterface` + `SparqlBackendInterface` in one class |
| SPARQL JSON bindings output | ✅ | `_rows_to_sparql_bindings()` — V2 rows → standard format |
| Implement `SparqlSQLBackendAdapter` | ✅ | `KGBackendInterface` in `kg_backend_utils.py` |
| Wire into `BackendFactory` | ✅ | All 3 factory methods (space, sparql, signal manager) |
| Wire into `create_backend_adapter()` | ✅ | Dispatches on `SparqlSQL` class name |
| Dedicated `sparql_sql_graph` database | ✅ | Separate from `fuseki_sql_graph`, with `pg_trgm` extension |
| Copy wordnet test data | ✅ | 1.85M terms, 7M quads, MVs, indexes |
| Sidecar URL as config param | ✅ | `self.sidecar_url` from `sidecar_config['url']` |

### Phase 3: End-to-End Testing with Static Data (TODO)

Initial integration testing uses static/pre-loaded data (e.g. wordnet_exp).
MVs are built once after bulk load — no incremental maintenance needed yet.

| Step | Status | Notes |
|------|--------|-------|
| Server starts with `BACKEND_TYPE=sparql_sql` | ☐ | Config file + startup test |
| REST API: list spaces | ☐ | Returns `wordnet_exp` from admin tables |
| REST API: SPARQL query | ☐ | V2 pipeline end-to-end via REST |
| REST API: entity CRUD | ☐ | Via `SparqlSQLBackendAdapter` |
| REST API: graph management | ☐ | Create/list/drop graphs |
| Verify `GraphObjectRetriever` works | ☐ | SPARQL JSON bindings → RDFLib triples → VitalSigns |

### Phase 3.5: Admin CLI Support for sparql_sql (TODO)

Add `sparql_sql` backend support to the admin CLI (`vitalgraphdb_admin_cmd.py` / `bin/vitalgraphadmin`)
so that database initialization, space management, and data import work for the new backend.

| Step | Status | Notes |
|------|--------|-------|
| Detect `BACKEND_TYPE=sparql_sql` in admin CLI | ☐ | Use same config loader / `.env` profiles |
| `init-db` command creates admin tables + `pg_trgm` | ☐ | Replaces manual `init-sparql-sql.sql` execution |
| `create-space` creates per-space tables via `SparqlSQLSchema` | ☐ | Term, rdf_quad, datatype, indexes, datatype seeds |
| `drop-space` drops per-space tables | ☐ | Via `SparqlSQLSchema.drop_space()` |
| `import` command works with sparql_sql backend | ☐ | Bulk load quads, rebuild MVs/stats after import |
| `list-spaces` / `list-graphs` work against admin tables | ☐ | Shared schema, should work as-is |

### Phase 3.6: Stats & Materialized View Build Scripts (TODO)

After bulk data import, the optimizer requires populated stats tables and materialized views.
These should be runnable as standalone scripts and/or via admin CLI commands.

| Step | Status | Notes |
|------|--------|-------|
| `rebuild-stats` populates `rdf_pred_stats` | ☐ | `GROUP BY predicate_uuid` over `rdf_quad` |
| `rebuild-stats` populates `rdf_stats` | ☐ | Predicate × object counts for `rdf:type` triples |
| `rebuild-mv` builds/refreshes `edge_mv` | ☐ | Currently a materialized view; may convert to table (Phase 4) |
| `rebuild-mv` builds/refreshes `frame_entity_mv` | ☐ | Depends on `edge_mv`; requires slot predicate UUIDs |
| Attach to admin CLI (`vitalgraphadmin -c rebuild-stats -s <space>`) | ☐ | Non-interactive, per-space |
| Attach to admin CLI (`vitalgraphadmin -c rebuild-mv -s <space>`) | ☐ | Non-interactive, per-space |
| Standalone Python scripts in `scripts/` | ☐ | For use outside admin CLI (e.g. CI, one-off rebuilds) |
| Post-import hook: auto-run stats+MV after `import` command | ☐ | Optional `--rebuild-stats` flag on import |

**Notes:**
- `edge_mv` and `frame_entity_mv` are currently materialized views but may be converted to
  regular tables with incremental maintenance in Phase 4.
- Stats tables are small and fast to rebuild (~seconds even for 7M quads).
- MV rebuild is heavier (edge_mv: ~570K rows for wordnet, ~10s).

### Phase 4: Incremental MV → Table Conversion (TODO)

Convert materialized views to regular tables with incremental maintenance,
enabling support for data churn without expensive full-refresh cycles.

**Motivation:** MVs require `REFRESH MATERIALIZED VIEW` which rebuilds the
entire view (~11s for wordnet_exp). With write traffic, this blocks reads
or produces stale results. Regular tables support incremental INSERT/DELETE.

| Step | Status | Notes |
|------|--------|-------|
| Convert `edge_mv` to regular table | ☐ | Same schema, `CREATE TABLE` instead of `CREATE MATERIALIZED VIEW` |
| Incremental edge maintenance on quad insert | ☐ | If predicate is `hasEdgeSource`/`hasEdgeDest`, insert edge row |
| Incremental edge maintenance on quad delete | ☐ | `DELETE FROM edge WHERE edge_uuid = $1` |
| Bulk rebuild command for edge table | ☐ | `TRUNCATE` + `INSERT ... SELECT` for initial load |
| Convert `frame_entity_mv` to regular table | ☐ | More complex — depends on edge table + slot pattern |
| Incremental frame-entity maintenance | ☐ | On edge row insert, check slot pattern → insert frame row |
| Update `ensure_mv.py` for table-based checks | ☐ | Check `pg_tables` instead of `pg_matviews` |
| Stale-tracking / lazy rebuild option | ☐ | Fallback for bulk operations |

### Phase 5: Production Readiness (TODO)

| Step | Status | Notes |
|------|--------|-------|
| Signal manager integration | ☐ | LISTEN/NOTIFY for real-time updates |
| Entity lock manager | ☐ | Advisory locks for concurrent writes |
| `REFRESH CONCURRENTLY` support (interim) | ☐ | Before Phase 4, for non-blocking MV refresh |
| Load testing | ☐ | Compare with fuseki_postgresql |
