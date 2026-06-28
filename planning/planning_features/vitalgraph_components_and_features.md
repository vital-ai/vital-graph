# VitalGraph — Components & Features

**Date:** 2026-06-28

VitalGraph is a high-performance knowledge graph database built on PostgreSQL with full
SPARQL 1.1 support, a rich KG domain model (entities, frames, slots, relations), vector/geo/fuzzy
search capabilities, and a React admin UI.

---

## Core Components

### 1. SPARQL-to-SQL Engine (`vitalgraph/db/sparql_sql/`)

The primary backend. Translates SPARQL 1.1 algebra into optimized PostgreSQL SQL.

- **Jena sidecar** — Java service (`vitalgraph-jena-sidecar/`) parses SPARQL into an AST; Python consumes it
- **Collect phase** — SPARQL algebra → PlanV2 intermediate representation
- **Emit phase** — PlanV2 IR → SQL with optimizations (filter pushdown, BGP reorder, MV rewrites)
- **Generator** — Orchestrates compilation, caching (term cache, datatype cache, compile cache)
- **Auxiliary tables** — `edge_table`, `frame_entity_table`, `stats` for accelerated joins
- **SPARQL UPDATE** — Full INSERT DATA, DELETE DATA, DELETE/INSERT WHERE support
- **Variable scoping** — text_needed_vars optimization skips unnecessary term JOINs

**Key files:** `generator.py`, `collect.py`, `emit_bgp.py`, `emit_filter.py`, `emit_group.py`, `emit_update.py`, `var_scope.py`, `ir.py`

### 2. RDF Quad Store (`vitalgraph/db/sparql_sql/`)

PostgreSQL-native RDF storage with term-based architecture.

- **Term table** — Deduplicated URIs, literals, blank nodes with UUID primary keys
- **Quad table** — (subject_uuid, predicate_uuid, object_uuid, context_uuid) with indexes
- **Datatype table** — XSD datatype registry
- **Space isolation** — Per-space table prefixes for multi-tenancy
- **Bulk load** — Optimized batch insert with term deduplication

### 3. Knowledge Graph Layer (`vitalgraph/kg_impl/`)

High-level domain model built on top of RDF triples via the VitalSigns ontology.

- **KGEntities** — Primary business objects with typed properties
- **KGFrames** — Structured data containers attached to entities via edges
- **KGSlots** — Typed value holders within frames (text, integer, boolean, URI, etc.)
- **KGTypes** — Schema/type definitions for entities
- **KGRelations** — Typed edges between entities (via Edge classes)
- **KGDocuments** — Document objects with segmentation support
- **Entity graph** — Full subgraph retrieval (entity + frames + slots + edges)
- **Hierarchical frames** — Nested frame structures with proper grouping URI assignment

**Key files:** `kgentity_*.py`, `kgframe_*.py`, `kgslot_*.py`, `kgtypes_*.py`, `kgrelations_*.py`, `kg_backend_utils.py`, `kg_graph_retrieval_utils.py`

### 4. REST API (`vitalgraph/endpoint/`)

FastAPI-based API server with comprehensive CRUD endpoints.

| Endpoint Group | Description |
|----------------|-------------|
| Spaces | Multi-tenant space management |
| KGEntities | Entity CRUD, list, search, entity graph retrieval |
| KGFrames | Frame CRUD with hierarchical support |
| KGTypes | Type schema management |
| KGRelations | Relationship CRUD |
| KGDocuments | Document management + segmentation |
| KGQuery | SPARQL-based structured query builder |
| Objects | Raw VitalSigns object CRUD |
| Triples | Direct triple browser (bypasses SPARQL for speed) |
| SPARQL | Raw SPARQL query/update/insert/delete/graph endpoints |
| Files | File upload/download/management |
| Import/Export | Bulk data import/export (NT, NQ, Turtle, JSONL, VitalSigns Block) |
| Vector Indexes | Vector index lifecycle and configuration |
| FTS Indexes | Full-text search index management |
| Search Mappings | Unified search configuration |
| Fuzzy Mappings | Fuzzy/phonetic search configuration |
| Geo Config/Points | Geospatial configuration and data |
| Users | User management |
| API Keys | API key CRUD |
| Admin | Server administration |
| Metrics | Query and system metrics |
| Ontology | Schema/ontology introspection |
| Entity Registry | Entity dedup/resolution registry |
| Process | Background job management |

### 5. Vector, FTS, Geo & Fuzzy Search (`vitalgraph/vectorization/`)

Integrated search capabilities exposed through SPARQL `vg:` custom functions.

- **Vector search** — pgvector HNSW indexes, cosine similarity, `vg:vectorSimilarity()`
- **Full-text search** — PostgreSQL tsvector/tsquery with BM25 ranking, `vg:textSearch()`
- **Hybrid search** — Combined BM25 + vector fusion, `vg:hybridSearch()`
- **Geo search** — PostGIS-backed radius/bounds/polygon, `vg:withinRadius()`, `vg:withinBounds()`
- **Fuzzy search** — MinHash LSH + RapidFuzz for near-duplicate detection
- **Multi-vector** — Multiple vector indexes per space with different embedding models
- **Search text builder** — Configurable text concatenation for vectorization
- **Auto-sync** — Automatic index population on data changes

**Key files:** `vector_populator.py`, `fts_populator.py`, `geo_populator.py`, `fuzzy_populator.py`, `search_mapping_manager.py`, `vector_index_lifecycle.py`

### 6. Document Segmentation (`vitalgraph/document/`)

Automatic document splitting for RAG (retrieval-augmented generation) workflows.

- **Markdown segmentation** — Splits by headings (configurable depth)
- **Plain text segmentation** — Recursive character splitting with overlap
- **Three-tier model** — Original → Parent Copy → N Segments
- **Auto-segmentation** — Config-driven triggers on document CRUD
- **Dedicated vector index** — `document_segments` index for segment retrieval

### 7. Entity Registry (`vitalgraph/entity_registry/`)

Entity resolution, deduplication, and master data management.

- **Near-duplicate detection** — MinHash LSH + phonetic bands (PostgreSQL-backed)
- **Entity clustering** — DataSketch-based clustering
- **Alias management** — Multiple names per entity
- **Location tracking** — Geo-tagged entity locations
- **Relationship tracking** — Entity-to-entity links
- **Weaviate integration** — Optional vector search backend
- **Category/identifier management** — Structured metadata
- **Change log** — Audit trail for entity changes

### 8. Authentication & Authorization (`vitalgraph/auth/`)

- **JWT authentication** — Token-based auth with refresh
- **API key support** — Long-lived keys for service-to-service
- **Role-based access** — Admin, editor, viewer roles
- **Audit logging** — Request-level audit trail
- **Token version cache** — Revocation support

### 9. Client Libraries

#### Python Client (`vitalgraph/client/`)
- REST API client with session management
- Async support
- Config file loading (YAML)
- All endpoint methods (spaces, entities, frames, types, SPARQL, files, etc.)

#### TypeScript Client (`vitalgraph-client-ts/`)
- Full REST API client for browser/Node.js
- Typed endpoint methods
- VitalSigns model integration

### 10. Web Frontend (`frontend/`)

React + TypeScript admin UI with TailwindCSS.

| Page | Feature |
|------|---------|
| Spaces | Space list, create, detail, graphs |
| KGEntities | Entity list, detail, entity graph |
| KGFrames | Frame list, detail |
| KGTypes | Type schema browser |
| KGRelations | Relation browser |
| KGDocuments | Document list, segmentation controls |
| KGQuery Builder | Visual SPARQL query construction |
| SPARQL | Raw SPARQL editor with results |
| Triples | Triple browser with search |
| Graph Visualization | Force-directed graph rendering |
| Semantic Search | Unified search across vector/FTS/hybrid |
| Vector Indexes | Index management UI |
| FTS Indexes | FTS index management |
| Search Mappings | Search config UI |
| Fuzzy Mappings | Fuzzy search config |
| Files | File upload/management |
| Data Import/Export | Bulk data operations |
| Users | User administration |
| API Keys | Key management |
| Entity Registry | Entity resolution UI |
| Geo Shapes | Geospatial visualization |
| Admin | System administration |
| Metrics | Dashboard |

### 11. CLI Tools (`vitalgraph/cmd/`, `bin/`)

- **`vitalgraphdb`** — Start the server
- **`vitalgraphadmin`** — Database init/purge/delete/info, space management
- **`vitalgraphimport`** — Bulk data import (NT, NQ, Turtle, JSONL, VitalSigns Block)
- **`vitalgraphexport`** — Bulk data export
- **`vitalgraphsearch`** — Search CLI

### 12. Background Jobs & Process Management (`vitalgraph/process/`)

- **Process scheduler** — Cron-like job scheduling
- **Maintenance job** — Index maintenance, vacuum, stats refresh
- **Analytics job** — Space analytics computation
- **Metrics rollup** — Periodic metrics aggregation
- **Import/export cleanup** — Temporary file cleanup
- **Process lock manager** — Distributed locking for job coordination

### 13. Metrics & Observability (`vitalgraph/metrics/`)

- **Query metrics** — Per-query timing, SPARQL pipeline phases
- **PostgreSQL metrics collector** — Connection pool stats, query counts
- **Metrics middleware** — Request-level latency tracking
- **Metrics endpoint** — REST API for metrics retrieval

### 14. Database Administration (`vitalgraph/admin_cmd/`)

- **Schema initialization** — Create all admin + per-space tables
- **Space lifecycle** — Create, list, delete spaces with all artifacts
- **Purge/delete** — Clean database operations
- **Info** — Database status and statistics

---

## Experimental / Secondary Backends

| Backend | Location | Status |
|---------|----------|--------|
| Fuseki + PostgreSQL | `vitalgraph/db/fuseki_postgresql/` | Experimental — Fuseki for SPARQL, PG for admin |
| Pure Fuseki | `vitalgraph/db/fuseki/` | Placeholder |
| Oxigraph | `vitalgraph/db/oxigraph/` | Empty stubs |
| TiDB | `vitalgraph/db/tidb/` | Empty stubs |
| Aurora PostgreSQL | `vitalgraph/db/aurora_postgresql/` | Empty stub |

---

## Key Technical Characteristics

- **Pure PostgreSQL** — No external graph DB required; all RDF stored in PG tables
- **Async throughout** — asyncpg + FastAPI for high concurrency
- **VitalSigns ontology** — Domain model driven by VitalSigns type system
- **Multi-tenant** — Per-space table isolation with shared admin layer
- **SPARQL 1.1 conformant** — W3C DAWG test suite: 314 pass / 0 fail (current)
- **Extensible search** — vg: custom SPARQL functions for vector/FTS/geo
- **JSON-LD native** — All API I/O uses JSON-LD via VitalSigns serialization
- **Docker ready** — Single Dockerfile for server deployment

---

## Architecture Diagram (logical)

```
┌─────────────────────────────────────────────────────────────┐
│                     React Frontend                            │
└────────────────────────────┬────────────────────────────────┘
                             │ REST API
┌────────────────────────────▼────────────────────────────────┐
│                   FastAPI Server                              │
│  ┌──────────┐ ┌───────────┐ ┌──────────┐ ┌──────────────┐  │
│  │ Endpoints│ │ KG Impl   │ │ Auth     │ │ Metrics      │  │
│  └────┬─────┘ └─────┬─────┘ └──────────┘ └──────────────┘  │
│       │              │                                        │
│  ┌────▼──────────────▼──────────────────────────────────┐   │
│  │          SPARQL-to-SQL Engine                         │   │
│  │  (Jena sidecar → collect → emit → SQL)               │   │
│  └────────────────────────┬─────────────────────────────┘   │
│                           │                                   │
│  ┌────────────────────────▼─────────────────────────────┐   │
│  │     PostgreSQL (asyncpg)                              │   │
│  │  ┌────────┐ ┌───────┐ ┌────────┐ ┌───────────────┐  │   │
│  │  │ Terms  │ │ Quads │ │ Vector │ │ FTS/Geo/Fuzzy │  │   │
│  │  └────────┘ └───────┘ └────────┘ └───────────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## Related Planning Documents

| Area | Document |
|------|----------|
| Testing | `planning_cleanup/testing_plan.md` |
| Codebase cleanup | `planning_cleanup/codebase_cleanup_plan.md` |
| Search/Vector/Geo | `planning_vector_geo/vector_geo_plan.md` |
| Semantic search UI | `planning_vector_geo/semantic_search_ui_plan.md` |
| Multi-vector | `planning_multi_vector/multi_vector_query_plan.md` |
| KG Documents | `planning_kgdocument/kgdocument_plan.md` |
| Auth modernization | `planning_auth/authentication_modernization_plan.md` |
| TypeScript client | `planning_client/typescript_client_plan.md` |
| CLI | `planning_vital_cli/cli_implementation_plan.md` |
| UI completion | `planning_ui/ui_completion_plan.md` |
| Import/Export | `planning_import_export/import_export_plan.md` |
| Space analytics | `planning_space_analytics/space_analytics_plan.md` |
| Graph visualization | `planning_visualization/graph_visualization_plan.md` |
| SQL performance | `planning_sql/sparql_sql_v2_performance_plan.md` |
| KG model | `planning_kg_model/kg_model_plan.md` |
