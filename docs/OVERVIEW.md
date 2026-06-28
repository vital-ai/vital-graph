# VitalGraph System Overview

VitalGraph is a high-performance knowledge graph database built on PostgreSQL.
It provides full SPARQL 1.1 support, a rich domain model (entities, frames,
slots, relations, documents), integrated vector/FTS/geo/fuzzy search, and a
React admin UI.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     React Frontend                           │
└────────────────────────────┬────────────────────────────────┘
                             │ REST API (JSON-LD)
┌────────────────────────────▼────────────────────────────────┐
│                   FastAPI Server                             │
│  ┌──────────┐ ┌───────────┐ ┌──────────┐ ┌─────────────┐  │
│  │ Endpoints│ │ KG Impl   │ │ Auth     │ │ Metrics     │  │
│  └────┬─────┘ └─────┬─────┘ └──────────┘ └─────────────┘  │
│       │              │                                       │
│  ┌────▼──────────────▼─────────────────────────────────┐   │
│  │          SPARQL-to-SQL Engine                        │   │
│  │  (Jena sidecar → collect → emit → SQL)              │   │
│  └────────────────────────┬────────────────────────────┘   │
│                           │                                  │
│  ┌────────────────────────▼────────────────────────────┐   │
│  │     PostgreSQL (asyncpg)                             │   │
│  │  ┌───────┐ ┌───────┐ ┌────────┐ ┌──────────────┐   │   │
│  │  │ Terms │ │ Quads │ │ Vector │ │ FTS/Geo/Fuzzy│   │   │
│  │  └───────┘ └───────┘ └────────┘ └──────────────┘   │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## Components

### SPARQL-to-SQL Engine

Translates SPARQL 1.1 algebra into optimized PostgreSQL SQL via a three-phase
pipeline: parse (Jena sidecar) → collect (algebra → IR) → emit (IR → SQL).
Includes compile caching, term caching, auxiliary table rewrites, and full
SPARQL UPDATE support.

### RDF Quad Store

PostgreSQL-native storage using a term table (deduplicated URIs/literals with
UUID keys) and a quad table (subject, predicate, object, context UUIDs).
Per-space table isolation for multi-tenancy. Optimized bulk load via temp
tables and COPY.

### Knowledge Graph Layer

High-level domain model on top of RDF via the VitalSigns ontology:

- **KGEntities** — Primary business objects
- **KGFrames** — Structured data containers attached to entities
- **KGSlots** — Typed value holders within frames
- **KGTypes** — Schema/type definitions
- **KGRelations** — Typed edges between entities
- **KGDocuments** — Documents with segmentation for RAG workflows

### REST API

FastAPI-based with comprehensive endpoints: spaces, KG CRUD (entities, frames,
types, relations, documents), SPARQL query/update, triples browser, files,
import/export, vector/FTS/geo/fuzzy index management, users, API keys, metrics,
and admin.

### Search & Retrieval

Integrated search exposed through SPARQL `vg:` custom functions:

- **Vector** — pgvector HNSW indexes, cosine similarity
- **Full-text** — PostgreSQL tsvector/tsquery with BM25 ranking
- **Hybrid** — Combined BM25 + vector fusion
- **Geo** — PostGIS radius/bounds/polygon queries
- **Fuzzy** — MinHash LSH + RapidFuzz for near-duplicate detection

### Document Segmentation

Automatic splitting for RAG: markdown heading-based and plain recursive
character splitting. Three-tier model (original → parent → segments) with
dedicated vector index.

### Entity Registry

Entity resolution and deduplication: MinHash LSH + phonetic near-duplicate
detection, entity clustering, alias management, location tracking, Weaviate
integration, and change log.

### Authentication & Authorization

JWT tokens with refresh, API key support, role-based access (admin/editor/viewer),
audit logging, and token revocation.

### Client Libraries

- **Python** (`vitalgraph/client/`) — Async REST client with typed responses
- **TypeScript** (`vitalgraph-client-ts/`) — Full browser/Node.js client

### Web Frontend

React + TypeScript + TailwindCSS admin UI with pages for all major features:
spaces, entities, frames, types, relations, documents, SPARQL editor, triple
browser, graph visualization, search, vector/FTS/geo/fuzzy config, files,
import/export, users, API keys, entity registry, metrics, and admin.

### CLI Tools

- `vitalgraphdb` — Start the server
- `vitalgraphadmin` — Database init, purge, space management
- `vitalgraphimport` — Bulk data import
- `vitalgraphexport` — Bulk data export
- `vitalgraphsearch` — Search CLI

### Background Jobs

Process scheduler with maintenance (vacuum, stats), analytics computation,
metrics rollup, import/export cleanup, and distributed locking.

### Metrics & Observability

Per-query timing, SPARQL pipeline phase instrumentation, PostgreSQL pool stats,
request-level latency tracking, and a REST metrics endpoint.

---

## Key Technical Characteristics

- **Pure PostgreSQL** — No external graph DB; all RDF in PG tables
- **Async throughout** — asyncpg + FastAPI for high concurrency
- **VitalSigns ontology** — Domain model driven by VitalSigns type system
- **Multi-tenant** — Per-space table isolation with shared admin layer
- **SPARQL 1.1 conformant** — W3C DAWG test suite validated
- **Extensible search** — `vg:` custom SPARQL functions
- **JSON-LD native** — All API I/O via VitalSigns serialization
- **Docker ready** — Single Dockerfile for deployment

---

## Directory Structure (top-level)

```
vitalgraph/              Main Python package
├── db/sparql_sql/       SPARQL-to-SQL engine + RDF storage
├── kg_impl/             Knowledge graph layer
├── endpoint/            REST API endpoints
├── auth/                Authentication & authorization
├── client/              Python client library
├── entity_registry/     Entity resolution service
├── document/            Document segmentation
├── vectorization/       Vector/FTS/geo/fuzzy search
├── process/             Background jobs
├── metrics/             Observability
├── model/               Pydantic API models
├── cmd/                 CLI entry points
└── admin_cmd/           Admin operations

vitalgraph-jena-sidecar/ Jena SPARQL parser (Java)
vitalgraph-client-ts/    TypeScript client
frontend/                React admin UI
apps/                    Standalone apps (entity/agent registry tools)
planning/                Planning & design documents
archive/                 Archived historical code and docs
bin/                     CLI scripts
```

---

## Further Documentation

This document will be expanded as the system evolves. For detailed planning
and design documents, see the `planning/` directory.
