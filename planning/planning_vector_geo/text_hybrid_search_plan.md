# Full-Text Search & Hybrid Search — SPARQL Function Implementation

## 1. Overview

This document covers the addition of `vg:textSearch` and `vg:hybridSearch` as SPARQL custom functions in the VitalGraph SQL pipeline.  These complete the search story defined in `vector_geo_plan.md` §5.6 ("Unified Search Table Architecture") by providing ranked full-text search (BM25) and single-table BM25+vector hybrid search through the same SPARQL execution path used by `vg:vectorSimilarity`, `vg:geoDistance`, etc.

### Design Principle

All search modes — keyword, FTS, vector, hybrid — execute through the **SPARQL pipeline**.  There are no standalone Python search modules with raw SQL.  Callers build a SPARQL query using the appropriate `vg:` function, and the SQL emitter + orchestrator handle everything: SQL generation, vectorization, placeholder substitution, and execution.

---

## 2. New SPARQL Functions

### 2.1 `vg:textSearch`

Full-text search using PostgreSQL `tsvector` + GIN index.  Returns a BM25-style relevance rank.

**SPARQL syntax:**
```sparql
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>

BIND(vg:textSearch(?entity, "search text", "index_name") AS ?score)
```

**Arguments:**
| # | Type | Description |
|---|------|-------------|
| 0 | Variable | Entity variable (must have a resolved `uuid_col` in the type registry) |
| 1 | String literal | Search text |
| 2 | String literal | Vector index name (e.g. `"kgtype_default"`, `"entity_default"`) |

**Generated SQL:**
```sql
(SELECT ts_rank_cd(tsv, plainto_tsquery('english', 'search text'))
 FROM {space}_vec_{index_name}
 WHERE subject_uuid = {uuid_col}
   AND tsv @@ plainto_tsquery('english', 'search text')
 LIMIT 1)
```

**Characteristics:**
- Pure PostgreSQL — no vectorization API call needed
- Uses the GIN tsvector index on the vector data table
- Returns `NULL` when the entity has no tsvector match → use `FILTER(BOUND(?score))` to exclude non-matches
- Type: `xsd:double`

### 2.2 `vg:hybridSearch`

Single-table fusion of BM25 + vector similarity, matching the architecture in `vector_geo_plan.md` §5.6.

**SPARQL syntax:**
```sparql
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>

BIND(vg:hybridSearch(?entity, "search text", "index_name", 0.5) AS ?score)
```

**Arguments:**
| # | Type | Description |
|---|------|-------------|
| 0 | Variable | Entity variable |
| 1 | String literal | Search text |
| 2 | String literal | Vector index name |
| 3 | Numeric literal | Alpha (0.0 = pure BM25, 1.0 = pure vector) |

**Generated SQL:**
```sql
(SELECT 0.500000 * ts_rank_cd(tsv, plainto_tsquery('english', 'text'))
      + 0.500000 * (1 - (embedding <=> '__VG_EMBED_12345__'::vector))
 FROM {space}_vec_{index_name}
 WHERE subject_uuid = {uuid_col}
   AND (tsv @@ plainto_tsquery('english', 'text')
        OR (embedding <=> '__VG_EMBED_12345__'::vector) < 0.6)
 LIMIT 1)
```

**Characteristics:**
- Single-table operation: both `tsv` and `embedding` live in the same `{space}_vec_{idx}` row
- Records a `VectorRequest` → the orchestrator (`vg_resolve.py`) vectorizes the search text and replaces the `__VG_EMBED_*__` placeholder before SQL execution
- The `WHERE` clause uses OR to include candidates from either BM25 or vector similarity
- The 0.6 distance threshold prevents a full table scan on the vector side
- Type: `xsd:double`
- Context scoping: `AND context_uuid = (...)` appended when `graph_lock_uri` is set

---

## 3. Implementation Details

### 3.1 Files Modified

| File | Changes |
|------|---------|
| `vitalgraph/db/sparql_sql/vg_functions.py` | Added `VG_TEXT_SEARCH`, `VG_HYBRID_SEARCH` IRIs; `VG_TEXT_FUNCTIONS` frozenset; `is_vg_text_function()` detector; `TextSearchArgs` dataclass; `extract_text_search_args()` extractor; `text_search_sql()` and `hybrid_search_sql()` SQL generators |
| `vitalgraph/db/sparql_sql/emit_expressions.py` | Added `VG_TEXT_SEARCH`, `VG_HYBRID_SEARCH` to imports; added dispatch cases in `_vg_function_to_sql()` |
| `vitalgraph/db/sparql_sql/sql_type_generation.py` | Added `VG_TEXT_SEARCH`, `VG_HYBRID_SEARCH` to the `xsd:double` return type set in `_infer_function_type()` |
| `vitalgraph/kg_impl/kgtypes_read_impl.py` | Rewrote `search_types()` to build SPARQL with `vg:` functions; removed all raw SQL; removed `conn` parameter |
| `vitalgraph/endpoint/kgtypes_endpoint.py` | Simplified `_search_types()` — removed `_acquire_conn()` / `_release_conn()` helpers since everything goes through SPARQL now |

### 3.2 Files Deleted

| File | Reason |
|------|--------|
| `vitalgraph/vectorization/vector_search.py` | Standalone raw-SQL search module — redundant with `vg:` SPARQL functions |
| `vitalgraph/vectorization/kgtype_index_setup.py` | KGType-specific index setup — replaced by general `vector_index_lifecycle.py` |

### 3.3 Files Kept (unchanged)

| File | Purpose |
|------|---------|
| `vitalgraph/vectorization/vector_index_lifecycle.py` | General-purpose setup/teardown/swap for any named vector index |
| `vitalgraph/vectorization/mapping_manager.py` | General CRUD for `vector_mapping` + `vector_mapping_property` rows |
| `vitalgraph/vectorization/vector_populator.py` | General population pipeline (build search_text → vectorize → store) |
| `vitalgraph/db/sparql_sql/vg_resolve.py` | Resolves `VectorRequest` placeholders by calling vectorization providers |
| `vitalgraph/db/sparql_sql/vg_optimize.py` | Query planner heuristics (top-K driving, threshold pushdown) |

---

## 4. KGType Search Integration

The KGType search endpoint (`/api/graphs/kgtypes/search`) now supports four modes, all going through SPARQL:

| Mode | SPARQL Function | Vector Index Required | Vectorization Call |
|------|----------------|----------------------|-------------------|
| `keyword` | `FILTER(CONTAINS(...))` | No | No |
| `fts` | `vg:textSearch(?s, text, "kgtype_default")` | Yes | No |
| `vector` | `vg:vectorSimilarity(?s, text, "kgtype_default")` | Yes | Yes |
| `hybrid` | `vg:hybridSearch(?s, text, "kgtype_default", 0.5)` | Yes | Yes |

### 4.1 SPARQL Query Pattern (FTS/vector/hybrid modes)

```sparql
PREFIX vc: <http://vital.ai/ontology/vital-core#>
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>

SELECT ?s ?name ?vitaltype ?description ?score WHERE {
  ?s vc:vitaltype ?vt . VALUES ?vt { <...KGType URIs...> }
  ?s vc:vitaltype ?vitaltype .
  ?s vc:hasName ?name .
  OPTIONAL { ?s <http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription> ?description . }
  BIND(vg:textSearch(?s, "search text", "kgtype_default") AS ?score)
  FILTER(BOUND(?score))
}
ORDER BY DESC(?score)
LIMIT 100
```

The `FILTER(BOUND(?score))` excludes entities with no match (NULL score).  `ORDER BY DESC(?score)` ranks by relevance.

### 4.2 Keyword Mode (fallback)

Uses standard SPARQL `CONTAINS` with `LCASE` — no vector index required:

```sparql
FILTER(
  CONTAINS(LCASE(?name), LCASE("search text"))
  || CONTAINS(LCASE(COALESCE(?description, "")), LCASE("search text"))
)
```

---

## 5. Complete vg: Function Reference

Updated summary of all `vg:` functions now supported in the SPARQL pipeline:

| Function | IRI | Return Type | Needs Resolve | SQL Target | Status |
|----------|-----|-------------|--------------|------------|--------|
| `vg:textSearch` | `vitalgraph#textSearch` | `xsd:double` | No | `{space}_fts_{idx}` (GIN tsvector) | ✅ |
| `vg:hybridSearch` | `vitalgraph#hybridSearch` | `xsd:double` | Yes (vectorize) | `{space}_fts_{idx}` JOIN `{space}_vec_{idx}` | ✅ |
| `vg:vectorSimilarity` | `vitalgraph#vectorSimilarity` | `xsd:double` | Yes (vectorize) | `{space}_vec_{idx}` (HNSW) | ✅ |
| `vg:vectorNearby` | `vitalgraph#vectorNearby` | `xsd:double` | No (pre-computed) | `{space}_vec_{idx}` (HNSW) | ✅ |
| `vg:multiVectorSimilarity` | `vitalgraph#multiVectorSimilarity` | `xsd:double` | Yes (vectorize) | Multiple `{space}_vec_{idx}` (CTE fusion) | ✅ |
| `vg:multiVectorNearby` | `vitalgraph#multiVectorNearby` | `xsd:double` | No (pre-computed) | Multiple `{space}_vec_{idx}` (CTE fusion) | ✅ |
| `vg:trigramSimilarity` | `vitalgraph#trigramSimilarity` | `xsd:double` | No | `{space}_term` (GIN trigram, inline `word_similarity`) | ✅ |
| `vg:fuzzyMatch` | `vitalgraph#fuzzyMatch` | `xsd:double` | Yes (MinHash+RapidFuzz) | `{space}_fuzzy_*` (LSH bands) | ✅ |
| `vg:geoDistance` | `vitalgraph#geoDistance` | `xsd:double` | No | `{space}_geo` (PostGIS ST_Distance) | ✅ |
| `vg:withinRadius` | `vitalgraph#withinRadius` | `xsd:boolean` | No | `{space}_geo` (PostGIS ST_DWithin) | ✅ |
| `vg:withinBounds` | `vitalgraph#withinBounds` | `xsd:boolean` | No | `{space}_geo` (PostGIS ST_Within) | ✅ |
| `vg:withinPolygon` | `vitalgraph#withinPolygon` | `xsd:boolean` | No | `{space}_geo` (PostGIS ST_Within) | ✅ |

---

## 6. Relationship to vector_geo_plan.md

This implementation completes the following items from the main plan:

- **§5.6 "Pure Full-Text Search"** — now implemented as `vg:textSearch` with identical SQL pattern
- **§5.6 "Hybrid Search: Single-Table Operation"** — now implemented as `vg:hybridSearch` with identical single-table fusion SQL
- **§5.6 "Three Distinct Text Search Use Cases"** — use case 3 (ranked full-text / hybrid in vector table) is now fully wired into the SPARQL pipeline
- **Phase 5 item "Switch all search queries to PostgreSQL"** — KGType search now uses `vg:textSearch` / `vg:vectorSimilarity` / `vg:hybridSearch` instead of SPARQL CONTAINS for non-keyword modes

### §6.1 FTS Decoupling — Implementation Status

- ✅ **Phase 6A: Schema & Core** — shared search mapping tables, FTS index registry, FTS data table DDL with multi-language triggers, search_mapping_manager, fts_index_lifecycle, fts_populator, auto_sync integration, migration script. **Complete.**
- ✅ **Phase 6B: SPARQL function updates** (tasks 9–18) — `vg:textSearch` queries `_fts_` tables, `vg:hybridSearch` JOINs `_fts_` + `_vec_`, Top-K optimizer extended, `alpha` REST param, `search_text`/`tsv` removed from vector tables. **Complete.**
- ✅ **Phase 6C: REST & Client** (tasks 19–22) — Pydantic models, `/api/search-mappings` (CRUD + properties), `/api/fts-indexes` (CRUD + stats + languages + populate), wired into app. **Server-side complete.** All tasks complete (19–26).
- ✅ **Phase 6D: Migration & Backward Compatibility** (tasks 27–32) — `migrate_fts_decoupling.py` copies mapping data + FTS data, registers FTS indexes, bootstraps FTS on space creation. Integration tests: 52/52 pass (`test_fts_decoupling.py`). **Complete.**
- ✅ **Phase 6E: Admin UI** — SearchMappings page (CRUD, filters, toggle enabled), FtsIndexes page (CRUD, stats modal, populate modal, language display), sidebar reorganization under "Vector, Geo & Search". **Complete.**
- ✅ **Phase 6F: Integration Testing** — Extended `test_fts_decoupling.py` (52 tests: schema DDL, search_text_builder, lifecycle, SQL decoupling, SearchMappingManager CRUD+properties, Pydantic validation, FTS populator pipeline). Live-server endpoint test `test_fts_search_mapping_endpoints.py` (28/28 pass: FTS index CRUD+stats+languages, search mapping CRUD+properties+filters, error cases). **Complete.**
- ✅ **`vg:trigramSimilarity`** (§5.6 use case 2) — fuzzy name matching via `word_similarity()` on the term table's GIN trigram index (`pg_trgm`). Inline scalar expression, no subquery. Distinct from `vg:fuzzyMatch` (MinHash LSH bands). **Complete.** 77/77 tests pass.

---

## 6.1 FTS Decoupling from Vector Infrastructure

### Design Principle

**Full-text search is its own independent subsystem**, separate from both vector
search and fuzzy search.  Each of the four search systems manages its own
tables, mappings, indexes, populators, REST endpoints, client methods, and
admin UI:

| System | Purpose | Key Tables |
|--------|---------|------------|
| **Vector** | Embedding similarity (semantic) | `{space}_vec_{idx}`, `vector_index`, `vector_mapping` |
| **FTS** | Ranked keyword search (BM25/stemming) | `{space}_fts_{idx}`, `fts_index`, `fts_mapping` |
| **Fuzzy** | Name deduplication (MinHash LSH + phonetic) | `{space}_fuzzy_band`, `fuzzy_mapping` |
| **Geo** | Geospatial distance/radius | `{space}_geo`, `geo_config` |

There is no dependency between these systems.  A space can have FTS without
vector, vector without FTS, or both.  `vg:hybridSearch` bridges FTS + vector
via a JOIN when both are present.

### Problem

FTS is currently coupled to the vector index infrastructure: `vg:textSearch`
queries the `{space}_vec_{index_name}` table and relies on a `tsv` column
that is auto-generated from `search_text` alongside the `embedding` column.
This means:

1. **Can't do FTS without a vector provider** — creating a `vector_index`
   row requires `dimensions`, `embedding_provider`, `embedding_model`.
   Pure text search shouldn't need any of this.
2. **Wasted storage** — every row carries a `vector(N)` column (~6 KB for
   1536-dim) even when only BM25 is needed.
3. **Wasted compute** — the populator vectorizes every `search_text` via an
   embedding API even when the user only wants keyword/FTS.
4. **No independent configuration** — the same `vector_mapping` controls
   which predicates feed both FTS and embeddings. Different text may be
   optimal for each.
5. **Confusing naming** — `_vec_` tables holding full-text search data.

### Target Architecture: Shared Search Mappings

**Key insight**: FTS and vector search share the same mapping configuration
(which entity types, which predicates, what separator, etc.).  Rather than
duplicating mappings per system, we introduce a **shared search mapping**
layer.  The association between a mapping and concrete indexes (vector, FTS,
or both) is managed via an explicit **junction table**
`{space}_search_mapping_index`.  A given mapping can have:

- **No indexes** — mapping defined but not yet activated (no junction rows)
- **FTS only** — junction row with `index_type='fts'`
- **Vector only** — junction row with `index_type='vector'`
- **Both (hybrid-ready)** — junction rows for both; `vg:hybridSearch` pairs them

This eliminates the need for separate `fts_mapping` and `vector_mapping`
tables, ensures hybrid search always has a consistent pairing, and makes
the relationship between mappings and indexes **explicit in the database**
rather than relying on a shared-name convention.

| Concern | Before (coupled) | After (shared mappings) |
|---------|-------------------|-------------------------|
| Mapping config | `{space}_vector_mapping` + `_property` | `{space}_search_mapping` + `_property` (shared) |
| FTS data table | `{space}_vec_{idx}` | `{space}_fts_{idx}` |
| FTS registry | (none — embedded in `vector_index`) | `{space}_fts_index` — `index_name`, `languages[]` |
| Vector data table | `{space}_vec_{idx}` (embedding + search_text + tsv) | `{space}_vec_{idx}` — embedding only |
| Vector registry | `{space}_vector_index` (dims + provider + model) | `{space}_vector_index` — unchanged, references `search_mapping` |
| FTS populator | `vector_populator.py` (one pass) | `fts_populator.py` — builds `search_text`, trigger handles `tsv` |
| `vg:textSearch` SQL | `FROM {space}_vec_{idx}` | `FROM {space}_fts_{idx}` |
| `vg:hybridSearch` SQL | Single-table subquery | JOIN: `{space}_fts_{idx} f JOIN {space}_vec_{idx} v ON f.subject_uuid = v.subject_uuid` |

The hybrid search JOIN is O(1) per candidate since both tables share the
same primary key `(subject_uuid, context_uuid)`.  Hybrid search resolves
the FTS and vector indexes by looking up the mapping's `index_name` in the
`search_mapping_index` junction table — the concrete FTS and vector index
names do NOT need to match each other or the mapping name.

### Multi-Language Support

PostgreSQL ships with stemmer/stop-word configs for many languages:
`english`, `spanish`, `french`, `german`, `portuguese`, `italian`, `dutch`,
`russian`, `swedish`, `norwegian`, `danish`, `finnish`, `hungarian`,
`turkish`, `romanian`, `simple` (no stemming — tokenize + lowercase only).

**Design**: Each FTS index stores a list of languages (e.g. `['english', 'spanish']`).
The tsvector is built by **concatenating** the output of each language's stemmer:

```sql
-- For languages = ['english', 'spanish']:
tsv = to_tsvector('english'::regconfig, COALESCE(search_text, ''))
   || to_tsvector('spanish'::regconfig, COALESCE(search_text, ''))
```

This means:
- The text "running" produces lexemes `run` (English stemmer) and `running` (Spanish stemmer treats it as foreign)
- The text "corriendo" produces lexemes `corriendo` (English) and `corr` (Spanish stemmer)
- A query in either language will match because the GIN index contains lexemes from **all** configured stemmers

**Why concatenation, not per-row language?** RDF entities in VitalGraph typically
don't have a per-row language tag.  A single entity's `search_text` may contain
mixed-language content (e.g., an organization name in English with a Spanish
description).  Concatenating stemmers handles this transparently.

**Query-side**: `vg:textSearch` uses `plainto_tsquery` with the **first**
configured language.  For mixed-language queries, the populator has already
indexed lexemes from all configured stemmers, so matches work regardless of
which query language is used.  If needed, the query can be extended to
OR multiple tsqueries:

```sql
-- Multi-language query (generated when index has multiple languages)
WHERE tsv @@ (plainto_tsquery('english'::regconfig, $q)
           || plainto_tsquery('spanish'::regconfig, $q))
```

**Trade-off**: Concatenating N language stemmers increases tsvector storage
by ~N×.  For 2 languages this is negligible; for 5+ it may matter.  The
`simple` config (no stemming) can be used as a lightweight catch-all.

**Why not `GENERATED ALWAYS`?**  The `GENERATED ALWAYS AS (to_tsvector(...))
STORED` approach requires a compile-time-constant expression.  Since the
language list is configurable per-index and may contain multiple languages,
we use a **trigger** instead:

```sql
-- Trigger function (created per FTS data table)
CREATE OR REPLACE FUNCTION {space}_fts_{idx}_tsv_trigger() RETURNS trigger AS $$
BEGIN
    NEW.tsv := to_tsvector('english'::regconfig, COALESCE(NEW.search_text, ''))
            || to_tsvector('spanish'::regconfig, COALESCE(NEW.search_text, ''));
    RETURN NEW;
END
$$ LANGUAGE plpgsql IMMUTABLE;

CREATE TRIGGER trg_{space}_fts_{idx}_tsv
    BEFORE INSERT OR UPDATE ON {space}_fts_{idx}
    FOR EACH ROW EXECUTE FUNCTION {space}_fts_{idx}_tsv_trigger();
```

The trigger function body is dynamically generated by `fts_index_lifecycle.py`
based on the index's `languages` array.  When languages are changed, the
trigger function is recreated and existing rows can be refreshed with
`UPDATE {table} SET search_text = search_text`.

### DDL: Shared Search Mapping + FTS Tables

```sql
-- ═══════════════════════════════════════════════════════
-- Shared search mapping (used by BOTH FTS and vector)
-- Replaces the existing {space}_vector_mapping tables
-- ═══════════════════════════════════════════════════════

-- Search mapping (which entity types get indexed, which predicates)
-- index_name is the mapping's LOGICAL IDENTIFIER, used in SPARQL functions
-- (vg:hybridSearch, vg:textSearch, vg:vectorSimilarity).  It does NOT need
-- to match the name of any concrete vector or FTS index.  The association
-- to concrete indexes is managed via the junction table below.
CREATE TABLE IF NOT EXISTS {space}_search_mapping (
    mapping_id      SERIAL PRIMARY KEY,
    mapping_type    VARCHAR(64) NOT NULL,       -- e.g. 'kgentity', 'kgtype', 'kgdocument'
    type_uri        VARCHAR(512),               -- optional RDF type filter
    index_name      VARCHAR(255) NOT NULL,       -- logical name (SPARQL reference)
    enabled         BOOLEAN DEFAULT TRUE,
    source_type     VARCHAR(20) NOT NULL DEFAULT 'default',
    separator       VARCHAR(32) DEFAULT '. ',
    include_pred_name   BOOLEAN DEFAULT FALSE,
    include_type_desc   BOOLEAN DEFAULT TRUE,
    created_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Junction table: associates mappings → concrete indexes (vector and/or FTS)
CREATE TABLE IF NOT EXISTS {space}_search_mapping_index (
    id              SERIAL PRIMARY KEY,
    mapping_id      INTEGER NOT NULL,
    index_type      VARCHAR(10) NOT NULL CHECK (index_type IN ('vector', 'fts')),
    index_name      VARCHAR(255) NOT NULL,
    created_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (mapping_id, index_type, index_name),
    FOREIGN KEY (mapping_id) REFERENCES {space}_search_mapping(mapping_id) ON DELETE CASCADE
);

-- Search mapping properties (child predicates — shared by FTS + vector)
CREATE TABLE IF NOT EXISTS {space}_search_mapping_property (
    property_id     SERIAL PRIMARY KEY,
    mapping_id      INT NOT NULL,
    property_uri    VARCHAR(512) NOT NULL,
    property_role   VARCHAR(32) DEFAULT 'include',
    ordinal         INT DEFAULT 0,
    FOREIGN KEY (mapping_id) REFERENCES {space}_search_mapping(mapping_id) ON DELETE CASCADE
);

-- ═══════════════════════════════════════════════════════
-- FTS index (references search_mapping via index_name)
-- ═══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS {space}_fts_index (
    index_id        SERIAL PRIMARY KEY,
    index_name      VARCHAR(255) NOT NULL UNIQUE,
    languages       VARCHAR(64)[] NOT NULL DEFAULT '{english}',
    created_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- FTS data table (one per named index)
CREATE TABLE IF NOT EXISTS {space}_fts_{index_name} (
    subject_uuid    UUID NOT NULL,
    context_uuid    UUID NOT NULL,
    search_text     TEXT,
    tsv             tsvector,   -- populated by trigger, not GENERATED ALWAYS
    updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (subject_uuid, context_uuid)
);

CREATE INDEX IF NOT EXISTS idx_{space}_fts_{index_name}_tsv
    ON {space}_fts_{index_name} USING gin (tsv);
CREATE INDEX IF NOT EXISTS idx_{space}_fts_{index_name}_ctx
    ON {space}_fts_{index_name} (context_uuid);

-- Trigger: multi-language tsvector generation (dynamically generated)
-- See "Multi-Language Support" section above for trigger function template

-- ═══════════════════════════════════════════════════════
-- Vector index (references search_mapping via index_name)
-- No changes to existing DDL except: no more search_text/tsv columns
-- ═══════════════════════════════════════════════════════

-- {space}_vector_index stays as-is (dimensions, provider, model, index_name)
-- {space}_vec_{index_name} keeps only: subject_uuid, context_uuid, embedding, updated_time
```

### Batch Population Performance

During full population (`fts_populator.py`), the tsvector trigger fires
per-row on INSERT/UPDATE, which is inefficient for bulk loads.  The
populator should:

1. **Disable the trigger** before bulk insert
2. **Batch-compute `tsv`** in SQL: `UPDATE {table} SET tsv = to_tsvector(...) || to_tsvector(...) WHERE tsv IS NULL`
3. **Re-enable the trigger** after population

This is the same pattern used by the fuzzy populator's index management
and the Tier 3 WordNet loader's index disable/rebuild strategy.

### Implementation Tasks

#### Phase 6A: Schema & Core (High priority)

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 1 | Add shared search mapping DDL (`search_mapping`, `search_mapping_property`) | `sparql_sql_schema.py` | ✅ Done |
| 2 | Add FTS table DDL (`fts_index`, `fts_{idx}` data table + trigger template) | `sparql_sql_schema.py` | ✅ Done |
| 3 | Add FTS tables to `drop_space_tables_sql` and `drop_space_indexes_sql` | `sparql_sql_schema.py` | ✅ Done |
| 4 | Create `search_mapping_manager.py` — CRUD for shared `search_mapping` + `search_mapping_property` | `vectorization/search_mapping_manager.py` | ✅ Done |
| 5 | Create `fts_index_lifecycle.py` — create/drop/list FTS data tables; generate multi-language trigger functions from `languages[]` | `vectorization/fts_index_lifecycle.py` | ✅ Done |
| 6 | Create `fts_populator.py` — build `search_text` from shared mapping config, write to `fts_{idx}` table; batch tsvector computation (disable trigger → bulk INSERT → batch UPDATE tsv → re-enable trigger) | `vectorization/fts_populator.py` | ✅ Done |
| 7 | Wire FTS population into `auto_sync.py` alongside vector + fuzzy + geo (FTS runs independently, can run in parallel with vector) | `vectorization/auto_sync.py` | ✅ Done |
| 8 | Migration: add shared search mapping + FTS tables to existing spaces; migrate `vector_mapping` data to `search_mapping` | `db/migrations/migrate_vector_geo_schema.py` | ✅ Done |

##### Phase 6A Implementation Notes

**Files modified:**
- `vitalgraph/db/sparql_sql/sparql_sql_schema.py` — Added `search_mapping`, `search_mapping_property`, `fts_index` to `get_table_names()`; added DDL in `create_space_tables_sql()`; added drop statements in `drop_space_tables_sql()`; added `fts_table_name()`, `create_fts_data_table_sql()`, `drop_fts_data_table_sql()`, `_build_tsv_concat_expr()`, `build_tsv_batch_expr()` methods
- `vitalgraph/vectorization/search_text_builder.py` — Added `resolve_search_mapping()` that reads from shared `search_mapping` tables (parallel to existing `resolve_mapping()` for `vector_mapping`)
- `vitalgraph/vectorization/auto_sync.py` — Added `_sync_fts_for_subjects()` wired into `_run_sync()` alongside vector, geo, fuzzy
- `vitalgraph/db/migrations/migrate_vector_geo_schema.py` — Added migration steps 7–9 for `search_mapping`, `search_mapping_property`, `fts_index`

**Files created:**
- `vitalgraph/vectorization/search_mapping_manager.py` — `SearchMappingManager` with full CRUD for shared `search_mapping` + `search_mapping_property`; `SearchMappingDTO`, `SearchMappingPropertyDTO` DTOs (same pattern as `MappingManager`)
- `vitalgraph/vectorization/fts_index_lifecycle.py` — `ensure_fts_index()`, `teardown_fts_index()`, `list_fts_indexes()`, `get_fts_index()`, `update_fts_languages()`, `get_fts_stats()`
- `vitalgraph/vectorization/fts_populator.py` — `populate_fts_index()` with batch mode (disable trigger → bulk INSERT → batch UPDATE tsv → re-enable trigger); `update_subject_fts()`, `delete_subject_fts()` for incremental auto-sync

**Key design decisions:**
- FTS data table `tsv` column is **trigger-based** (not `GENERATED ALWAYS`) for configurable multi-language support
- Batch population disables trigger, inserts with `tsv IS NULL`, then batch-computes tsvectors in a single `UPDATE ... SET tsv = to_tsvector(...) || to_tsvector(...) WHERE tsv IS NULL`
- `resolve_search_mapping()` in `search_text_builder.py` mirrors `resolve_mapping()` but reads from `search_mapping` tables — both FTS and vector populators can use it
- Auto-sync FTS is wired in after fuzzy sync in `_run_sync()`, following the same pattern (discover indexes → iterate subjects × indexes)

#### Phase 6B: SPARQL Function Updates (High priority — after 6D migration)

> **Ordering constraint**: Tasks 14–16 (removing `tsv`/`search_text` from
> vector tables) are **breaking changes** for any queries still targeting
> `_vec_` tables.  These must be done **after** Phase 6D migration has
> moved data to `_fts_` tables and updated all references.

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 9 | Update `text_search_sql()` to query `{space}_fts_{idx}` instead of `{space}_vec_{idx}`; generate multi-language `plainto_tsquery` OR clause from index's `languages[]` | `vg_functions.py` | ✅ Done |
| 10 | Update `hybrid_search_sql()` to JOIN `fts` + `vec` tables; use configurable alpha (already 4th arg in SPARQL function) | `vg_functions.py` | ✅ Done |
| 11 | Add index-name resolution logic: `text_search_sql()` looks up `fts_index` registry; `hybrid_search_sql()` resolves both `fts_index` and `vector_index` by shared `index_name` | `vg_functions.py`, `emit_context.py`, `generator.py` | ✅ Done |
| 12 | Top-K optimization for `textSearch`/`hybridSearch`: extend `vg_optimize.py` to recognize BIND+ORDER+LIMIT patterns for GIN-driving subqueries | `vg_optimize.py`, `vg_functions.py` | ✅ Done |
| 13 | Expose configurable alpha as REST query param in KGType search endpoint (in addition to SPARQL 4th arg) | `kgtypes_endpoint.py`, `kgtypes_read_impl.py` | ✅ Done |
| 14 | Remove `tsv` / `search_text` columns from vector data table DDL (**after 6D**) | `sparql_sql_schema.py` | ✅ Done |
| 15 | Remove GIN tsvector index from vector data table DDL (**after 6D**) | `sparql_sql_schema.py` | ✅ Done |
| 16 | Update `vector_populator.py` to stop writing `search_text` (embedding only); also updated `vector_indexes_endpoint.py` upsert/get queries | `vector_populator.py`, `vector_indexes_endpoint.py` | ✅ Done |
| 17 | Update vg function reference table in this doc | This file | ✅ Done |
| 18 | Update unit tests for new SQL targets + multi-language queries + alpha config + trigram | `test_vg_functions.py` | ✅ Done (77/77 pass) |

##### Phase 6B Implementation Notes

**Files modified:**
- `vitalgraph/db/sparql_sql/vg_functions.py` — Added `_resolve_fts_languages()` and `_build_tsquery_expr()` helpers; rewrote `text_search_sql()` to query `_fts_` tables with multi-language tsquery OR clause and top-K/threshold optimizer hints; rewrote `hybrid_search_sql()` to JOIN `_fts_` + `_vec_` tables with aliased context clauses; updated module docstring
- `vitalgraph/db/sparql_sql/emit_context.py` — Added `fts_index_meta` dict to `EmitContext`; propagated to child contexts
- `vitalgraph/db/sparql_sql/generator.py` — Pre-loads `fts_index_meta` from `{space}_fts_index` table (Stage 2e) and wires into `EmitContext`
- `vitalgraph/db/sparql_sql/vg_optimize.py` — Extended `_annotate_vector_top_k()` and `_find_vg_extend()` to also recognize `vg:textSearch` / `vg:hybridSearch` for SLICE→ORDER→EXTEND top-K and FILTER threshold pushdown patterns
- `vitalgraph/endpoint/kgtypes_endpoint.py` — Added `alpha` query parameter (Optional[float]) to search_types endpoint
- `vitalgraph/kg_impl/kgtypes_read_impl.py` — Added `alpha` parameter to `search_types()` and `_search_types_vg()`; uses it in hybrid BIND clause instead of hardcoded 0.5

**Key design decisions:**
- FTS index language metadata is pre-loaded in generator Stage 2e (same pattern as `vector_index_meta`) and stored on `EmitContext.fts_index_meta`
- `_resolve_fts_languages()` falls back to `['english']` when metadata is unavailable
- Multi-language tsquery uses `||` operator to OR multiple `plainto_tsquery()` calls
- `hybrid_search_sql()` uses table aliases (`f` for FTS, `v` for vector) and JOINs on `(subject_uuid, context_uuid)`
- Top-K and threshold optimizer hints are now recognized for all vg: BIND functions (vector, text, hybrid)
- Alpha REST parameter only applies to hybrid mode; defaults to 0.5 when not specified

#### Phase 6C: REST & Client (Medium priority)

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 19 | Create Pydantic models for shared search mappings + FTS indexes (including `languages: List[str]`) | `model/search_mappings_model.py`, `model/fts_index_model.py` | ✅ Done |
| 20 | Create shared search mappings REST endpoint (`/api/search-mappings`) — CRUD + properties | `endpoint/search_mappings_endpoint.py` | ✅ Done |
| 21 | Create FTS indexes REST endpoint (`/api/fts-indexes`) — CRUD + stats + populate | `endpoint/fts_indexes_endpoint.py` | ✅ Done |
| 22 | Wire endpoints into `vitalgraphapp_impl.py` | `vitalgraphapp_impl.py` | ✅ Done |
| 23 | Python client: `client.search_mappings.*` | `client/endpoint/search_mappings_endpoint.py` | ✅ Done |
| 24 | Python client: `client.fts_indexes.*` | `client/endpoint/fts_indexes_endpoint.py` | ✅ Done |
| 25 | TypeScript client: `client.searchMappings.*` | `SearchMappingsEndpoint.ts` | ✅ Done |
| 26 | TypeScript client: `client.ftsIndexes.*` | `FtsIndexesEndpoint.ts` | ✅ Done |

#### Phase 6D: Migration & Backward Compatibility (Medium priority — before 6B tasks 14–16)

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 27 | Migrate existing `vector_mapping` + `vector_mapping_property` data to `search_mapping` + `search_mapping_property` | `migrate_fts_decoupling.py` | ✅ Done |
| 28 | Migrate existing `search_text`/`tsv` data from `vec` tables to new `fts` tables | `migrate_fts_decoupling.py` | ✅ Done |
| 29 | Register FTS indexes in `fts_index` registry mirroring existing `vector_index` entries | `migrate_fts_decoupling.py` | ✅ Done |
| 30 | KGType search: `kgtype_default` shared index name works for both FTS and vector (no change needed) | `kgtypes_read_impl.py` | ✅ Done |
| 31 | Bootstrap: create FTS indexes for bootstrapped vector indexes on space creation | `sparql_sql_schema.py` | ✅ Done |
| 32 | Integration tests for decoupled FTS (single-language + multi-language) | `test_fts_decoupling.py` | ✅ Done |

##### Phase 6D Implementation Notes

**Files created:**
- `vitalgraph/db/migrations/migrate_fts_decoupling.py` — Standalone migration script (Phase 6D). Per space: (1) copies `vector_mapping` → `search_mapping` (deduped by index_name+mapping_type+type_uri), (2) copies `vector_mapping_property` → `search_mapping_property` (mapped via new mapping_ids), (3) for each `vector_index`: registers matching `fts_index` entry, creates `_fts_` data table + trigger, copies `search_text`/`tsv` from `_vec_` table with trigger disabled for performance. Idempotent (ON CONFLICT DO NOTHING). Supports `--dry-run`.

**Files modified:**
- `vitalgraph/db/sparql_sql/sparql_sql_schema.py` — `create_space()` now bootstraps FTS indexes for any registered vector indexes after document_segments setup
- `vitalgraph/kg_impl/kgtypes_read_impl.py` — Updated `KGTYPE_INDEX_NAME` comment to reflect shared index name

**Key design decisions:**
- Migration copies `tsv` as-is from `_vec_` (GENERATED ALWAYS english-only) to `_fts_` (trigger-based). Future `populate_fts_index()` calls will recompute with multi-language if configured.
- FTS index bootstrap in `create_space` runs after document_segments vector bootstrap, creating FTS indexes for all registered vector indexes.
- Migration is idempotent and safe to re-run — uses ON CONFLICT DO NOTHING everywhere.
- Prerequisite: run `migrate_vector_geo_schema` first to ensure `search_mapping`, `search_mapping_property`, and `fts_index` tables exist.

#### Phase 6E: Admin UI ✅ COMPLETE

> UI details consolidated in `planning_vector_geo/search_ui_plan.md` §2, §9–§11.

### Open Questions — Resolved

| # | Question | Decision |
|---|----------|----------|
| 1 | Multi-language FTS support | `languages[]` array per FTS index; tsvector built by concatenating all configured stemmers via trigger |
| 2 | `GENERATED ALWAYS` vs trigger | Trigger — required for configurable multi-language |
| 3 | Configurable alpha in hybrid search | Both: SPARQL 4th arg (already supported) AND REST query param |
| 4 | Top-K optimization timing | Phase 6B — extend `vg_optimize.py` for textSearch/hybridSearch |
| 5 | `vg:trigramSimilarity` vs `vg:fuzzyMatch` | Both needed — `trigramSimilarity` uses the term table's GIN trigram index (`pg_trgm`) always; `fuzzyMatch` uses MinHash LSH bands. Different algorithms, different indexes, different use cases |
| 6 | FTS/vector index naming & pairing | Shared search mappings — mappings declared once, FTS and vector indexes reference them by `index_name`. Hybrid search naturally pairs via shared name |
| 7 | Trigger performance on bulk population | Batch mode — disable trigger, bulk INSERT, batch UPDATE tsv, re-enable trigger |
| 8 | Phase ordering | 6A (schema) → 6D (migration) → 6B tasks 14–16 (remove vec columns). 6B tasks 9–13 + 6C + 6E can start after 6A |
| 9 | Admin UI | Full admin UI: shared Search Mappings page + FTS Indexes page; sidebar reorganized under "Search" |

### Benefits After Decoupling

- **FTS without embeddings** — create an FTS index with just `languages: ['english']`, no provider/dimensions needed. Pure PostgreSQL, zero API calls, zero cost.
- **Multi-language support** — configure multiple stemmers per index (e.g., `['english', 'spanish']`); text is indexed through all configured stemmers so queries in any language match.
- **Shared search mappings** — declare predicates once, use them for FTS, vector, or both. No duplication, guaranteed hybrid pairing.
- **Configurable hybrid alpha** — tunable via SPARQL 4th arg or REST query param.
- **Smaller vector tables** — no `search_text`/`tsv` columns or GIN index in `_vec_` tables reduces storage and write amplification.
- **Batch population** — tsvector computed in bulk SQL, not per-row trigger, matching the performance patterns of the fuzzy and Tier 3 loaders.
- **Cleaner architecture** — each search system (vector, FTS, fuzzy, geo) manages its own index tables and populators, sharing mapping configuration where appropriate.
- **Full admin UI** — manage search mappings, FTS indexes, and vector indexes through the admin interface under a unified "Search" section.

---

## 7. Testing

### 7.1 Syntax Verification

All modified files pass `py_compile`:
- `vg_functions.py` ✅
- `emit_expressions.py` ✅
- `sql_type_generation.py` ✅
- `kgtypes_read_impl.py` ✅
- `kgtypes_endpoint.py` ✅
- `vector_index_lifecycle.py` ✅

**Phase 6A files** (all pass `py_compile`):
- `sparql_sql_schema.py` ✅
- `search_mapping_manager.py` ✅
- `fts_index_lifecycle.py` ✅
- `fts_populator.py` ✅
- `auto_sync.py` ✅
- `search_text_builder.py` ✅

**Phase 6B files** (all pass `py_compile`):
- `vg_functions.py` ✅
- `emit_context.py` ✅
- `generator.py` ✅
- `vg_optimize.py` ✅
- `kgtypes_endpoint.py` ✅
- `kgtypes_read_impl.py` ✅

**Phase 6D files** (all pass `py_compile`):
- `migrate_fts_decoupling.py` ✅
- `sparql_sql_schema.py` ✅
- `migrate_vector_geo_schema.py` ✅

### 7.2 Unit Test Results ✅ ALL PASS (67/67)

Tests are in the existing `test_scripts_misc/test_vg_functions.py`, following
the same helpers (`_lit`, `_var`, `_make_ctx`) and class-per-concern pattern.

**File:** `test_scripts_misc/test_vg_functions.py`

**Run:** `python -m pytest test_scripts_misc/test_vg_functions.py -v`

**Result:** 67 passed, 0 failed

#### Test classes added

| Class | Tests | What it verifies |
|-------|-------|-----------------|
| `TestTextFunctionDetection` | `test_is_vg_text_function`, `test_text_not_vector`, `test_all_functions_count`, `test_text_functions_set` | `is_vg_text_function()` returns True for textSearch/hybridSearch; these are NOT detected by `is_vg_vector_function()`; `VG_ALL_FUNCTIONS` now has 8 members |
| `TestExtractTextSearchArgs` | `test_textSearch_args`, `test_hybridSearch_args`, `test_hybridSearch_wrong_arg_count`, `test_textSearch_first_arg_not_var`, `test_textSearch_missing_index` | `extract_text_search_args()` correctly parses both signatures; rejects bad input |
| `TestTextSearchSQL` | `test_textSearch_generates_fts_subquery`, `test_textSearch_context_scoping`, `test_textSearch_no_context_without_lock`, `test_textSearch_escapes_single_quotes` | `text_search_sql()` produces correct SQL with `ts_rank_cd`, `plainto_tsquery`, correct table name, `tsv @@` filter; adds `context_uuid` clause when `graph_lock_uri` is set; escapes single quotes |
| `TestHybridSearchSQL` | `test_hybridSearch_generates_fusion_subquery`, `test_hybridSearch_creates_vector_request`, `test_hybridSearch_context_scoping`, `test_hybridSearch_alpha_reflected_in_sql`, `test_hybridSearch_alpha_zero_is_pure_bm25_weight` | `hybrid_search_sql()` produces fusion SQL with both BM25 and cosine terms; records a `VectorRequest`; alpha weights appear in SQL; context scoping works |
| `TestTextSearchTypeInference` | `test_textSearch_inferred_as_double`, `test_hybridSearch_inferred_as_double` | `_infer_function_type()` returns `xsd:double` for both |
| `TestTextSearchEmitIntegration` | `test_is_numeric_recognizes_text_functions`, `test_emit_dispatches_textSearch`, `test_emit_dispatches_hybridSearch` | `_is_numeric_expr` recognizes them as numeric; `_vg_function_to_sql` dispatches correctly and records VectorRequest for hybrid |

#### Bugs found and fixed during testing

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| `_is_numeric_expr` didn't recognize `vg:textSearch`/`vg:hybridSearch` | Only `VG_VECTOR_SIMILARITY`, `VG_VECTOR_NEARBY`, `VG_GEO_DISTANCE` were listed | Added `VG_TEXT_SEARCH`, `VG_HYBRID_SEARCH` to the tuple in `emit_expressions.py:160-163` |
| `TestMultiVectorSQL` tests threw `TypeError: '<' not supported between instances of 'int' and 'MagicMock'` | `_make_ctx()` mock didn't set `multi_vector_config` or `vector_index_meta`, so `getattr(ctx, ...)` returned MagicMock attributes | Added `ctx.multi_vector_config = {}` and `ctx.vector_index_meta = {}` to `_make_ctx()` |

### 7.3 Integration Test Plan (requires DB)

| Test | Description | Prerequisites |
|------|-------------|--------------|
| FTS search via endpoint | `search_mode=fts`, verify ranked results from `kgtype_default` tsvector | Populated `kgtype_default` index |
| Vector search via endpoint | `search_mode=vector`, verify `vectorSimilarity` returns results with embeddings | Populated `kgtype_default` index |
| Hybrid search via endpoint | `search_mode=hybrid`, verify fusion scoring | Populated `kgtype_default` index |
| Keyword fallback | `search_mode=keyword`, verify CONTAINS works without any vector index | KG types loaded |
| Score ordering | Results sorted by DESC(?score) | Populated data with varying relevance |
| Type filter | `type=frame`, verify vitaltype filter applied | Mixed type data |
