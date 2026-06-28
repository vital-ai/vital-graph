# Vector & Geo Integration Plan for SPARQL-SQL Backend

## 1. Overview

Incorporate **pgvector** (vector similarity search) and **PostGIS** (geospatial queries) into the VitalGraph sparql_sql backend. Both extensions are supported on AWS RDS PostgreSQL and will enable:

- **Vector**: Similarity search over embeddings (entity search, slot-level semantic matching, KG type matching)
- **Geo**: Lat/long distance queries ("find entities within N km of a point")

This **replaces** the current Weaviate-based vector + geo search with a unified PostgreSQL-native approach. Weaviate will be fully removed once pgvector/PostGIS parity is achieved.

---

## 2. AWS RDS Compatibility

### 2.1 pgvector on RDS

- **Supported**: pgvector 0.8.0 on RDS PostgreSQL 17.1+, 16.5+, 15.9+, 14.14+, 13.17+
- **Installation**: `CREATE EXTENSION IF NOT EXISTS vector;`
- **Key features in 0.8.0**:
  - HNSW and IVFFlat index types
  - Iterative index scans (prevents overfiltering)
  - Improved WHERE clause filtering with vector indexes
  - Up to 2,000 dimensions per indexed column (16,000 for storage without index)
  - Half-precision vectors (`halfvec`) for reduced storage (up to 4,000 dims indexed)
  - Sparse vectors (`sparsevec`)
  - Binary vectors (`bit`)

### 2.2 PostGIS on RDS

- **Supported**: PostGIS 3.4.x on RDS PostgreSQL 15+, 16+, 17+
- **Installation**: `CREATE EXTENSION IF NOT EXISTS postgis;`
- **Key features**:
  - `geography` type for lat/long (uses meters/spheroid math, no SRID confusion)
  - `ST_DWithin(geog_a, geog_b, distance_meters)` — index-accelerated radius queries
  - `ST_Distance(geog_a, geog_b)` — exact distance computation
  - `ST_MakePoint(lon, lat)` — point construction
  - GiST indexes on `geography` columns for fast spatial lookups

### 2.3 Required RDS Configuration

```sql
-- Enable extensions (one-time, requires rds_superuser)
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS postgis;
-- pg_trgm is already enabled for text search
```

No custom parameter group changes required. Both extensions are standard on RDS.

---

## 3. Storage Design

### 3.1 Vector Storage

Vectors of different dimensionalities need separate columns or tables because pgvector requires fixed dimensions per column. Since we may have N different embedding models (entity embeddings, slot-type-specific embeddings, etc.), we use a **per-space vector table** with a named index approach.

#### Option A: Separate vector table per space (Recommended)

```sql
-- Per-space vector index registry
CREATE TABLE IF NOT EXISTS {space_id}_vector_index (
    index_id        SERIAL PRIMARY KEY,
    index_name      VARCHAR(255) NOT NULL UNIQUE,  -- e.g. 'entity_default', 'slot_description_384'
    dimensions      INT NOT NULL,                   -- e.g. 384, 768, 1536
    distance_metric VARCHAR(20) NOT NULL DEFAULT 'cosine',  -- cosine, l2, inner_product
    provider        VARCHAR(50) NOT NULL DEFAULT 'vitalsigns',  -- see §5.5
    model_name      VARCHAR(255),                   -- e.g. 'text-embedding-3-small', 'paraphrase-multilingual-MiniLM-L12-v2'
    provider_config JSONB,                          -- provider-specific config (see §5.5)
    description     TEXT,
    created_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Per-space vector data table
CREATE TABLE IF NOT EXISTS {space_id}_vector_data (
    subject_uuid    UUID NOT NULL,       -- references term table (the entity/slot/type URI)
    index_id        INT NOT NULL REFERENCES {space_id}_vector_index(index_id),
    embedding       vector({dimensions}),-- pgvector column — see note below
    context_uuid    UUID NOT NULL,       -- graph context (same as rdf_quad)
    updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (subject_uuid, index_id)
);
```

**Dimension challenge**: pgvector requires a fixed dimension per column in the DDL. Options:
1. **Partitioned tables**: One partition per index_id, each with its own dimension — complex but clean
2. **Dynamic column creation**: Add a new `vector(N)` column for each registered index — simple but messy
3. **Separate table per vector index**: `{space_id}_vec_{index_name}` — simplest, most flexible

**Recommendation**: **Option 3 — separate table per vector index**. Each named vector index gets its own table with the correct dimension. This allows independent HNSW/IVFFlat index management, vacuuming, and avoids the partitioning complexity.

```sql
-- Created dynamically when a vector index is registered
CREATE TABLE IF NOT EXISTS {space_id}_vec_{index_name} (
    subject_uuid    UUID NOT NULL,
    context_uuid    UUID NOT NULL,
    embedding       vector({dimensions}) NOT NULL,
    search_text     TEXT,                -- source text used for vectorization (enables re-vectorization & FTS)
    tsv             tsvector GENERATED ALWAYS AS (
                        to_tsvector('english'::regconfig, COALESCE(search_text, ''))
                    ) STORED,
    updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (subject_uuid, context_uuid)
);

-- HNSW index for ANN vector search
CREATE INDEX IF NOT EXISTS idx_{space_id}_vec_{index_name}_hnsw
    ON {space_id}_vec_{index_name}
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);

-- GIN index for full-text search (BM25-style ranked retrieval)
CREATE INDEX IF NOT EXISTS idx_{space_id}_vec_{index_name}_fts
    ON {space_id}_vec_{index_name}
    USING gin (tsv);

-- Context index for graph-scoped queries
CREATE INDEX IF NOT EXISTS idx_{space_id}_vec_{index_name}_ctx
    ON {space_id}_vec_{index_name} (context_uuid);
```

#### AWS RDS PostgreSQL Compatibility

All features used are confirmed available on AWS RDS PostgreSQL 15+:

| Feature | Minimum Version | RDS Status |
|---------|----------------|-----------|
| `pgvector` extension (HNSW, vector type) | pgvector 0.5.0+ (PG 15+) | ✅ Supported since 2023, v0.8.0 as of Nov 2024 |
| `PostGIS` extension (geography, ST_DWithin) | PG 12+ | ✅ Long-supported on RDS |
| `GENERATED ALWAYS AS ... STORED` columns | PG 12+ | ✅ Supported |
| `tsvector` / `to_tsvector` / `ts_rank_cd` | PG 8.x+ | ✅ Core PostgreSQL (no extension needed) |
| GIN index on `tsvector` | PG 8.x+ | ✅ Core PostgreSQL |
| `pg_trgm` extension (GIN trigram) | PG 9.x+ | ✅ Already in use |
| `plainto_tsquery` / `@@` operator | PG 8.x+ | ✅ Core PostgreSQL |

**Important**: The `to_tsvector` call in the GENERATED column MUST use `'english'::regconfig` (explicit regconfig cast), not `'english'` (text). The text-argument form of `to_tsvector(text, text)` is NOT immutable — PostgreSQL requires generated column expressions to be immutable. The `to_tsvector(regconfig, text)` form IS immutable and works correctly in generated columns on all PostgreSQL versions 12+.

**Alternative** (if multi-language support is needed later): Replace the generated column with a trigger that calls `to_tsvector(config_name, search_text)` with a per-row language setting. This is more flexible but slightly more code.

#### Why search_text + tsvector Live in the Vector Table

The vector table already has one row per indexed entity. By co-locating full-text search (tsvector) with the vector embedding in the same table, we enable **single-table hybrid search** — BM25 ranking + vector similarity are computed in one query without cross-table JOINs. See §5.6 for details.

#### Vector Index Registry (stored in PostgreSQL, not config files)

```sql
-- Example: VitalSigns built-in model (local, no API key needed)
INSERT INTO {space_id}_vector_index
  (index_name, dimensions, distance_metric, provider, model_name, description)
VALUES ('entity_default', 384, 'cosine', 'vitalsigns',
        'paraphrase-multilingual-MiniLM-L12-v2', 'Default entity embeddings');

-- Example: OpenAI provider
INSERT INTO {space_id}_vector_index
  (index_name, dimensions, distance_metric, provider, model_name, provider_config, description)
VALUES ('entity_openai', 1536, 'cosine', 'openai',
        'text-embedding-3-small',
        '{"api_key_env": "OPENAI_API_KEY"}'::jsonb,
        'OpenAI embeddings for entity search');
```

### 3.2 Geo Storage

#### Why a Separate Table is Required

PostGIS spatial queries (`ST_DWithin`, `ST_Distance`) require a `geography(Point, 4326)` column with a **GiST index**. This is a fundamentally different data type from the `TEXT` values stored in the term table. The GiST index operates on the binary geography representation — you cannot run `ST_DWithin` against a text string like `"40.730610"`. Therefore a separate geo table is necessary to hold the PostGIS-native column and index.

The RDF data (lat/long as literal triples) remains in the standard term/quad tables unchanged. The geo table is a **derived side-table** that extracts and indexes spatial data from those triples, linked back via `subject_uuid`.

#### Geo Table DDL

```sql
-- Per-space geo side-table
CREATE TABLE IF NOT EXISTS {space_id}_geo (
    subject_uuid    UUID NOT NULL,       -- the entity/slot subject in the term table
    predicate_uuid  UUID,                -- which predicate pair produced this point
    location        geography(Point, 4326) NOT NULL,  -- PostGIS native type
    latitude        DOUBLE PRECISION NOT NULL,  -- denormalized for non-spatial access
    longitude       DOUBLE PRECISION NOT NULL,  -- denormalized for non-spatial access
    context_uuid    UUID NOT NULL,       -- graph context (same as rdf_quad)
    updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (subject_uuid, context_uuid)
);

-- GiST index — required for ST_DWithin / ST_Distance to use index scan
CREATE INDEX IF NOT EXISTS idx_{space_id}_geo_gist
    ON {space_id}_geo USING gist (location);

-- B-tree for subject lookups (JOIN to quad table)
CREATE INDEX IF NOT EXISTS idx_{space_id}_geo_subj
    ON {space_id}_geo (subject_uuid);
```

#### Linking to the RDF Tables

The geo table links to the main RDF storage at two levels:

1. **`subject_uuid`** — matches `term.term_uuid` for the entity/slot URI. This is the primary join key used when the SPARQL-to-SQL pipeline needs to combine spatial filtering with regular triple pattern matching:

```sql
-- Generated SQL: find entities of type KGEntity within 10km of a point
SELECT q1.subject_uuid
FROM {space_id}_rdf_quad q1
JOIN {space_id}_term t1 ON q1.predicate_uuid = t1.term_uuid
  AND t1.term_text = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
JOIN {space_id}_term t2 ON q1.object_uuid = t2.term_uuid
  AND t2.term_text = 'http://vital.ai/ontology/haley-ai-kg#KGEntity'
JOIN {space_id}_geo geo ON geo.subject_uuid = q1.subject_uuid
  AND geo.context_uuid = q1.context_uuid
WHERE ST_DWithin(geo.location, ST_MakePoint(-73.935242, 40.730610)::geography, 10000)
```

2. **`context_uuid`** — ensures the geo data is scoped to the same graph as the RDF query. An entity may exist in multiple graphs; the geo join respects graph boundaries.

#### Geo Data Lifecycle

The geo table is maintained automatically (like the edge table):

| Event | Action |
|-------|--------|
| Quad INSERT with lat/long predicates | Extract lat/long pair → `INSERT INTO geo` with `ST_MakePoint(lon,lat)::geography` |
| Quad UPDATE on lat/long | Update the geo row for that subject |
| Quad DELETE on lat/long | Delete the geo row for that subject |
| Space deletion | `DROP TABLE {space_id}_geo` (cascades with space) |
| Admin rebuild | Scan all quads for lat/long predicates → repopulate geo table |

**Predicate detection**: The system recognizes these predicates as geo source data:
- `http://www.w3.org/2003/01/geo/wgs84_pos#lat` / `wgs84_pos#long` (WGS84 standard)
- `http://vital.ai/ontology/haley-ai-kg#hasLatitude` / `hasLongitude` (VitalGraph ontology)
- Configurable additional predicates via the vector/geo config

A complete geo point requires **both** lat and long for the same subject. The sync logic waits for both values before inserting into the geo table.

#### Why Not Add geography to the Term Table

The term table stores all RDF terms (URIs, literals, blank nodes). Adding a `geography` column would:
- Waste space (NULL for 99.9%+ of rows)
- Pollute the generic term table with domain-specific concerns
- Make the GiST index inefficient (indexing mostly NULLs)
- Couple PostGIS extension availability to basic RDF storage

#### Geo operations supported:

```sql
-- Find subjects within 10km of a point
SELECT subject_uuid
FROM {space_id}_geo
WHERE ST_DWithin(location, ST_MakePoint(-73.935242, 40.730610)::geography, 10000);

-- Get distance in meters
SELECT subject_uuid, ST_Distance(location, ST_MakePoint(-73.935242, 40.730610)::geography) AS distance_m
FROM {space_id}_geo
WHERE ST_DWithin(location, ST_MakePoint(-73.935242, 40.730610)::geography, 10000)
ORDER BY distance_m;
```

### 3.3 Integration with Existing Schema

The `sparql_sql_schema.py` `get_table_names()` will be extended:

```python
@staticmethod
def get_table_names(space_id: str) -> Dict[str, str]:
    return {
        # ... existing tables ...
        'vector_index': f'{space_id}_vector_index',
        'geo': f'{space_id}_geo',
        # Vector data tables are dynamic: {space_id}_vec_{index_name}
    }
```

---

## 4. SPARQL Integration: Magic Properties vs. Functions

### 4.1 The Design Decision

We use **Jena (via the sidecar)** for SPARQL parsing. Jena supports two extension mechanisms:

| Mechanism | Pros | Cons |
|-----------|------|------|
| **Magic Properties** (property functions) | Standard triple pattern syntax; Jena parses natively; easy to express "find me things similar to X" | Hard to pass multiple parameters (distance, limit, metric); subject/object semantics can be confusing |
| **Custom Functions** (filter/BIND functions) | Flexible parameter passing; natural for computed values like distance; composable in FILTER expressions | Non-standard; other SPARQL parsers can't parse them; not truly SPARQL-portable |
| **GeoSPARQL Standard** | OGC standard; Jena has built-in GeoSPARQL support; portable across SPARQL engines | Requires GeoSPARQL ontology structure (Feature→Geometry→GeometryLiteral); heavier than we need for simple lat/long |

### 4.2 Recommended Approach: Hybrid

#### For Geo: Use GeoSPARQL-compatible property functions

Jena already supports `spatial:nearby` as a property function:

```sparql
PREFIX spatial: <http://jena.apache.org/spatial#>

# Find features near a point (lat, lon, radius_km)
?feature spatial:nearby (40.730610 -73.935242 10) .
```

This is already parseable by Jena. Our SQL translator would detect this property function pattern and translate it to PostGIS SQL:

```sql
-- Generated SQL for spatial:nearby
JOIN {space_id}_geo geo_1
  ON geo_1.subject_uuid = q1.subject_uuid
  AND ST_DWithin(geo_1.location, ST_MakePoint(-73.935242, 40.730610)::geography, 10000)
```

**Advantage**: Uses existing Jena spatial vocabulary. Any SPARQL parser with Jena extensions can parse it.

**Alternative GeoSPARQL function form** (also supported by Jena):

```sparql
PREFIX geof: <http://www.opengis.net/def/function/geosparql/>
PREFIX uom: <http://www.opengis.net/def/uom/OGC/1.0/>

FILTER(geof:distance(?point1, ?point2, uom:kilometre) < 10)
```

#### For Vector: Use custom property functions

Vector similarity doesn't have a SPARQL standard. We define our own property function namespace:

```sparql
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>

# Find subjects similar to a text query (returns bindings with score)
?entity vg:similarTo ("search text here" 10 "entity_default") .
# Parameters: (query_text, limit, index_name)

# Or with a pre-computed vector:
?entity vg:nearVector ("[0.1, 0.2, ...]" 10 "entity_default") .
# Parameters: (vector_literal, limit, index_name)
```

Jena will parse these as property functions (the predicate is a known URI with list arguments). Our SPARQL-to-SQL translator intercepts them and generates:

```sql
-- Generated SQL for vg:similarTo
JOIN LATERAL (
    SELECT subject_uuid, 1 - (embedding <=> $vector_param) AS score
    FROM {space_id}_vec_entity_default
    ORDER BY embedding <=> $vector_param
    LIMIT 10
) vec_1 ON vec_1.subject_uuid = q1.subject_uuid
```

### 4.3 SPARQL-to-SQL Pipeline Integration Points

The v2 pipeline processes SPARQL in these stages:
1. **Jena sidecar** parses SPARQL → JSON AST (Op tree)
2. **jena_ast_mapper** maps JSON → Python Op tree
3. **collect.py** builds PlanV2 IR
4. **emit_*.py** emits SQL from IR

**New handling needed**:

- **jena_ast_mapper**: Detect property function Ops (Jena emits these as `OpPropFunc` or similar) and map to new `VectorSearchOp` / `GeoNearbyOp` IR nodes
- **collect.py**: Handle new Op types, add them to PlanV2 IR
- **emit_vector.py** (new): Emit LATERAL JOIN for vector similarity
- **emit_geo.py** (new): Emit JOIN + ST_DWithin for geo queries
- **generator.py**: Wire new emitters into the pipeline

### 4.4 Decision: Open Questions

1. **Should we also support FILTER-based vector search?**
   - e.g., `FILTER(vg:cosineSimilarity(?entity, "search text") > 0.8)`
   - Pro: More composable. Con: Harder to translate efficiently (can't push to index).
   - **Recommendation**: Start with property functions only (index-friendly). Add filter functions later if needed.

2. **Should we use GeoSPARQL standard or simplified property functions?**
   - GeoSPARQL requires Feature→Geometry→GeometryLiteral structure which we don't use
   - Jena's `spatial:nearby` is simpler and already Jena-parseable
   - **Recommendation**: Use Jena `spatial:nearby` / `spatial:withinCircle` which are already parseable. Our geo data is simple points, not complex geometries.

3. **How does the Jena sidecar handle property functions?**
   - **Research needed**: Verify what Op node Jena produces for property functions like `spatial:nearby`. The sidecar sends a JSON AST — we need to confirm property functions appear in that AST. If Jena evaluates them server-side (which it would for its own datasets), we may need to configure the sidecar to pass them through as unevaluated Ops.
   - **Fallback**: If the sidecar doesn't pass through property functions, we can register custom functions instead (Jena ARQ filter functions), which will appear in the AST as function calls in FILTER/BIND expressions.

---

## 5. Vector Operations to Support

### 5.1 Core Operations

| Operation | SPARQL Syntax | SQL Translation |
|-----------|--------------|-----------------|
| **Vector similarity (by text)** | `BIND(vg:vectorSimilarity(?s, "query", "idx") AS ?score)` | Vectorize text → `1 - (embedding <=> $vec)` |
| **Vector similarity (by vector)** | `BIND(vg:vectorNearby(?s, "[0.1,...]", "idx") AS ?score)` | Direct `1 - (embedding <=> $vec)` |
| **Full-text search (ranked)** | `BIND(vg:textSearch(?s, "query", "idx") AS ?rank)` | `ts_rank_cd(tsv, plainto_tsquery($q))` |
| **Hybrid search (BM25 + vector)** | `BIND(vg:hybridSearch(?s, "query", "idx", 0.5) AS ?score)` | Fused: `(1-α)·ts_rank + α·(1-distance)` |
| **Geo distance** | `BIND(vg:geoDistance(?s, lat, lon) AS ?dist)` | `ST_Distance(location, point)` |
| **Geo radius filter** | `FILTER(vg:withinRadius(?s, lat, lon, meters))` | `ST_DWithin(location, point, meters)` |

All vector/text/hybrid operations hit the **same table** (`{space}_vec_{idx}`) — see §5.6.

### 5.2 Distance Metrics

| Metric | pgvector Operator | Index Ops Class | Use Case |
|--------|-------------------|-----------------|----------|
| **Cosine distance** | `<=>` | `vector_cosine_ops` | Default for text embeddings |
| **L2 (Euclidean)** | `<->` | `vector_l2_ops` | Image embeddings, spatial |
| **Inner product** | `<#>` | `vector_ip_ops` | Normalized embeddings |

Default: **cosine distance** (matches current Weaviate config).

### 5.3 Index Types

| Type | Pros | Cons | When to Use |
|------|------|------|-------------|
| **HNSW** | Better recall, no training step, good for updates | More memory, slower build | Default for most cases |
| **IVFFlat** | Less memory, faster build | Needs training data (>1000 rows), lower recall | Large static datasets |

Default: **HNSW** with `m=16, ef_construction=200`.

### 5.4 Vector Population

Vectors are populated via:
1. **Bulk import**: During data load, compute vectors and insert into vector tables
2. **Incremental**: On entity/slot create/update, compute and upsert vector
3. **Re-index**: Admin operation to re-vectorize all subjects for an index
4. **Direct client upsert** (✅ Implemented): Client provides pre-computed embeddings via REST API — no server-side vectorization. Useful for testing or when the client has its own embedding pipeline.

#### 5.4.1 Direct Vector Upsert / Get API

Routes (under `/api/vector-indexes/vectors`):

```
POST /api/vector-indexes/vectors?space_id=...&index_name=...   — upsert vectors
GET  /api/vector-indexes/vectors?space_id=...&index_name=...&subject_uri=...  — get vectors
```

**Upsert** (batch, up to 1000 per call):
```json
POST /api/vector-indexes/vectors?space_id=my_space&index_name=entity_default
{
  "vectors": [
    {
      "subject_uri": "urn:entity:acme-corp",
      "graph_uri": "urn:graph:main",
      "embedding": [0.1, 0.2, ...],
      "search_text": "Acme Corp renewable energy"
    }
  ]
}
```

- Validates dimensions match the index
- Uses `ON CONFLICT ... DO UPDATE` (idempotent)
- `search_text` is optional — enables hybrid search for that entry

**Get** (by subject URI and/or graph URI):
```json
GET /api/vector-indexes/vectors?space_id=my_space&index_name=entity_default&subject_uri=urn:entity:acme-corp

{
  "vectors": [
    {
      "subject_uri": "urn:entity:acme-corp",
      "graph_uri": "urn:graph:main",
      "embedding": [0.1, 0.2, ...],
      "search_text": "Acme Corp renewable energy",
      "updated_time": "2026-06-09T16:50:00"
    }
  ],
  "total_count": 1
}
```

- At least one of `subject_uri` or `graph_uri` required
- Returns up to 100 results
- Resolves UUIDs back to URIs via the term table

The vectorizer component (currently `entity_vectorizer.py`) will be generalized into a provider-based architecture (see §5.5). Once pgvector is operational, all vectorization targets PostgreSQL exclusively.

### 5.5 Vectorization Providers

Three sources of vectors are supported. Each vector index is associated with a provider via the `provider` column in the index registry.

#### Source 1: Pre-computed vector passed in

The caller provides the vector directly — no server-side vectorization needed. Used when:
- The client has its own embedding pipeline
- Vectors are pre-computed during batch import
- The SPARQL query uses `vg:nearVector` with a literal vector

```sparql
# Client passes vector directly — no provider involved
?entity vg:nearVector ("[0.1, 0.2, ...]" 10 "entity_default") .
```

#### Source 2: External provider API (OpenAI, Cohere, etc.)

The server calls an external embedding API to vectorize text at query time or during data population.

| Provider | Model Examples | Dimensions | Notes |
|----------|---------------|------------|-------|
| `openai` | `text-embedding-3-small` | 1536 | Most popular, good quality |
| `openai` | `text-embedding-3-large` | 3072 (or reduced) | Higher quality, supports dimension reduction |
| `cohere` | `embed-english-v3.0` | 1024 | Good for English |
| `anthropic` | (future) | TBD | If/when embedding API is available |

**Configuration**: API keys stored as environment variable references (never in DB):

```json
// provider_config JSONB in vector_index table
{
  "api_key_env": "OPENAI_API_KEY",   // env var name containing the key
  "base_url": null,                   // optional custom endpoint
  "batch_size": 100,                  // max texts per API call
  "rate_limit_rpm": 3000              // optional rate limiting
}
```

#### Source 3: VitalSigns built-in model (local)

VitalSigns ships with a small local model that runs without external API calls. Used as the default / fallback when no external provider is configured.

- **Model**: `paraphrase-multilingual-MiniLM-L12-v2` (384 dimensions)
- **Runs on**: CPU (or MPS/CUDA if available)
- **No API key needed**
- **Trade-off**: Smaller model = lower quality than OpenAI, but zero latency/cost for API calls

```json
// provider_config for vitalsigns (minimal — model is bundled)
{
  "device": "auto"   // auto-detect: cuda > mps > cpu
}
```

#### Provider Interface

```python
class VectorizationProvider(ABC):
    """Abstract base for all vectorization providers."""

    @abstractmethod
    async def vectorize_text(self, text: str) -> List[float]:
        """Vectorize a single text string."""
        ...

    @abstractmethod
    async def vectorize_texts(self, texts: List[str]) -> List[List[float]]:
        """Vectorize a batch of text strings."""
        ...

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Return the output dimension of this provider's model."""
        ...


class VitalSignsProvider(VectorizationProvider):
    """Local model via VitalSigns (no API calls)."""
    ...

class OpenAIProvider(VectorizationProvider):
    """OpenAI embedding API."""
    ...

class CohereProvider(VectorizationProvider):
    """Cohere embedding API."""
    ...
```

#### Provider Registry

A global registry maps provider names to classes. Initialized at startup, providers are instantiated per-index (each index can use a different model/config).

```python
PROVIDER_REGISTRY: Dict[str, Type[VectorizationProvider]] = {
    'vitalsigns': VitalSignsProvider,
    'openai': OpenAIProvider,
    'cohere': CohereProvider,
}
```

#### Query-Time Vectorization Flow

When a SPARQL query contains `vg:similarTo ("search text" ...)` referencing an index:

1. **SPARQL-to-SQL pipeline** detects the vector search Op
2. Looks up the index in `{space_id}_vector_index` → gets `provider`, `model_name`, `provider_config`
3. Instantiates the provider (cached per index) and calls `vectorize_text(query_text)`
4. Passes the resulting vector as a SQL parameter: `ORDER BY embedding <=> $1::vector`
5. If the caller passes a raw vector (`vg:nearVector`), step 3 is skipped

This happens **Python-side, before SQL execution** — the database never calls external APIs.

### 5.6 Unified Search Table Architecture

#### Two Layers of Text Search

The system maintains two distinct text search mechanisms, each optimized for its use case:

| Layer | Location | Index Type | Purpose |
|-------|----------|-----------|---------|
| **Basic keyword** | `{space}_term` table | GIN trigram (`gin_trgm_ops`) | SPARQL pattern matching: `CONTAINS`, `STRSTARTS`, `REGEX` on individual RDF literal values |
| **Full-text + vector** | `{space}_vec_{idx}` table | GIN tsvector + HNSW vector | Ranked full-text search with stemming, hybrid search, semantic search |

**Why two layers?**

- The **term table** stores every RDF literal independently (names, URIs, numbers, dates). Its GIN trigram index supports arbitrary substring matching (`LIKE '%John%'`). This is the correct tool for SPARQL-level text pattern matching — it's boolean (match/no-match) and operates on individual property values.

- The **vector table** stores one row per *indexed entity* with a composite `search_text` built from multiple properties (name + description + categories + ...). Its tsvector provides ranked full-text search with stemming, stop-word removal, and relevance scoring. This is the correct tool for "find entities relevant to X" queries.

#### What Goes Into search_text

**Default case (no mapping override):** For KGEntity, KGDocument, and KGFrame objects, the value of `hasKGraphDescription` is used directly as the `search_text`. If the object also has a type reference (e.g., `hasKGEntityType`), the pipeline resolves the type, fetches its description, and appends it. See §7.1.1 for full details.

```python
# Default: hasKGraphDescription + type description enrichment
search_text = f"{kg_graph_description}. {kg_entity_type_description}"
```

**Override case (mapping exists):** When a `vector_mapping` entry exists for the object's type, its `source_type` + child `vector_mapping_property` rows control which properties or slot values are concatenated:

```python
# Override: concatenate specified properties
search_text = f"{entity_name}. {entity_description}. {type_label}. {category_labels}"
```

This composite text is used for:
1. **Vectorization** — passed to the embedding provider to generate the embedding
2. **Full-text search** — PostgreSQL automatically computes the `tsv` column via the `GENERATED ALWAYS` expression
3. **Debugging/re-indexing** — stored as-is for inspection and re-vectorization without re-reading source data

#### Hybrid Search: Single-Table Operation

Because `embedding` and `tsv` live in the same row, hybrid search is a single-table query:

```sql
-- vg:hybridSearch(?entity, "renewable energy", "entity_default", 0.5)
-- alpha = 0.5 → equal weight BM25 + vector
SELECT subject_uuid,
    (1 - :alpha) * ts_rank_cd(tsv, plainto_tsquery(:query_text)) +
    :alpha * (1 - (embedding <=> :query_vector))
    AS hybrid_score
FROM {space_id}_vec_entity_default
WHERE context_uuid = :graph_uuid
  AND (
    tsv @@ plainto_tsquery(:query_text)       -- GIN index narrows BM25 candidates
    OR (embedding <=> :query_vector) < 0.6    -- HNSW narrows vector candidates
  )
ORDER BY hybrid_score DESC
LIMIT 20
```

This is equivalent to Weaviate's `hybrid(query, alpha)` but runs entirely in PostgreSQL with no external service.

#### Pure Full-Text Search

```sql
-- vg:textSearch(?entity, "renewable energy", "entity_default")
SELECT subject_uuid,
    ts_rank_cd(tsv, plainto_tsquery(:query_text)) AS rank
FROM {space_id}_vec_entity_default
WHERE context_uuid = :graph_uuid
  AND tsv @@ plainto_tsquery(:query_text)
ORDER BY rank DESC
LIMIT 20
```

Equivalent to Weaviate's `bm25(query)` — keyword search with relevance ranking, stemming, and stop-word handling.

#### Comparison with Weaviate Operations

| Weaviate Operation | pgvector/PostGIS Equivalent | Table Used | Notes |
|--------------------|-----------------------------|-----------|-------|
| `near_text(query)` | `vg:vectorSimilarity(?s, "text", "idx")` | `{space}_vec_{idx}` | Provider vectorizes text → HNSW |
| `hybrid(query, alpha)` | `vg:hybridSearch(?s, "text", "idx", alpha)` | `{space}_vec_{idx}` | Single-table BM25+vector fusion |
| `bm25(query, properties)` | `vg:textSearch(?s, "text", "idx")` | `{space}_vec_{idx}` | GIN tsvector ranked search |
| `fetch_objects(filters)` | Regular SPARQL BGP triple patterns | `{space}_rdf_quad` + `{space}_term` | Already works |
| `within_geo_range(coord, dist)` | `FILTER(vg:withinRadius(?s, lat, lon, m))` | `{space}_geo` | PostGIS ST_DWithin |
| Property filters | SPARQL triple patterns + FILTER | `{space}_rdf_quad` + `{space}_term` | Already works |

#### Three Distinct Text Search Use Cases

The system supports three text search patterns, each with different characteristics:

| # | Use Case | Where | Index | How It Works |
|---|----------|-------|-------|-------------|
| 1 | **SPARQL pattern matching** | `{space}_term` | GIN trigram | `LIKE`, `ILIKE`, `REGEX` on individual literal values |
| 2 | **Fuzzy name search** | `{space}_term` | GIN trigram | `word_similarity()` / `%` operator for misspelled names |
| 3 | **Ranked full-text / hybrid** | `{space}_vec_{idx}` | GIN tsvector + HNSW | Stemmed, ranked, fuseable with vector similarity |

**Use case 1 — SPARQL pattern matching** (existing, stays as-is):
```sql
-- FILTER(CONTAINS(?name, "John")) → pushdown to term table
q.object_uuid IN (SELECT term_uuid FROM {space}_term WHERE term_text LIKE '%John%')
-- Uses GIN trigram index for fast substring matching
```

**Use case 2 — Fuzzy name search** (trigram similarity for misspellings):
```sql
-- Find entities whose name is similar to a misspelled query
-- Uses pg_trgm similarity operators (same GIN trigram index)
SELECT term_uuid, term_text, word_similarity('Jonh Smth', term_text) AS sim
FROM {space}_term
WHERE term_text % 'Jonh Smth'          -- trigram similarity > pg_trgm.similarity_threshold
  AND term_type = 'L'                   -- literals only
ORDER BY word_similarity('Jonh Smth', term_text) DESC
LIMIT 10
```

This is a distinct use case from full-text search: trigram similarity finds "John Smith" when the user types "Jonh Smth" — no stemming or language understanding, just character-level fuzzy matching. It leverages the **same GIN trigram index** already on the term table.

**Use case 3 — Ranked full-text / hybrid** (new, in vector table):
```sql
-- vg:textSearch or vg:hybridSearch → vector table only
SELECT subject_uuid, ts_rank_cd(tsv, plainto_tsquery('renewable energy')) AS rank
FROM {space}_vec_entity_default
WHERE tsv @@ plainto_tsquery('renewable energy')
```

#### Bloat and Performance Considerations

**Term table GIN trigram index**:
- The GIN trigram index on `{space}_term` is the **only** additional index needed for both use cases 1 and 2 — no new indexes required
- GIN trigram index size is typically 2-5x the source text size (but only indexes literals, not the full row)
- The term table contains ALL RDF terms (URIs, literals, blank nodes) — most are URIs which are short strings
- **Mitigation**: The `term_type = 'L'` filter in fuzzy search narrows the scan to literals only; for pattern matching, the pushdown already produces a UUID set

**Vector table GIN tsvector index**:
- Only exists on per-index vector tables (e.g., `{space}_vec_entity_default`)
- Much smaller table — one row per indexed entity (thousands to millions), not per-term (millions to tens of millions)
- tsvector GIN index is compact: stores lexemes (stemmed, deduplicated), not raw text
- `search_text` is a single TEXT column per entity — typically 200-500 bytes

**What we explicitly DON'T do** (to avoid bloat):
- ❌ No tsvector on the term table (it has millions of rows with short strings — tsvector would be wasteful)
- ❌ No trigram index on the vector table (fuzzy matching belongs at the term level)
- ❌ No duplicate indexes — each table has exactly the indexes it needs for its use cases

**Performance characteristics**:

| Operation | Table Scanned | Index Used | Rows Examined |
|-----------|--------------|-----------|---------------|
| SPARQL `CONTAINS(?x, "text")` | term (via pushdown) | GIN trigram | Small UUID set → drives quad join |
| Fuzzy name search | term (direct query) | GIN trigram | `%` operator uses index, top-K by similarity |
| Full-text search | vec_{idx} | GIN tsvector | `@@` operator uses index, ranked by ts_rank |
| Vector search | vec_{idx} | HNSW | ANN scan, top-K by distance |
| Hybrid search | vec_{idx} | GIN tsvector + HNSW | Both indexes, single-table fusion |

The key insight: **each table carries only the indexes for its use cases**, and neither table is overloaded with indexes it doesn't need.

#### SPARQL Syntax for Fuzzy Search

```sparql
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
# Find entities with names similar to a misspelled query (trigram fuzzy)
SELECT ?entity ?name ?similarity WHERE {
    ?entity <http://vital.ai/ontology/vital-core#hasName> ?name .
    BIND(vg:trigramSimilarity(?name, "Jonh Smth") AS ?similarity)
    FILTER(?similarity > 0.3)
}
ORDER BY DESC(?similarity)
LIMIT 10
```

This translates to a term-table trigram query, NOT a vector table query. ✅ **Implemented** — `trigram_similarity_sql()` in `vg_functions.py` generates inline `word_similarity()`.

#### Design Decision Summary

| Search Type | Table | Index | SPARQL Function | Status |
|-------------|-------|-------|----------------|--------|
| **Pattern matching** (substring) | `{space}_term` | GIN trigram | SPARQL `CONTAINS`/`REGEX`/`STRSTARTS` (existing) | ✅ |
| **Fuzzy matching** (misspellings) | `{space}_term` | GIN trigram (same) | `vg:trigramSimilarity(?var, "text")` | ✅ |
| **Ranked full-text** (BM25) | `{space}_fts_{idx}` | GIN tsvector | `vg:textSearch(?s, "text", "idx")` | ✅ |
| **Vector similarity** (semantic) | `{space}_vec_{idx}` | HNSW | `vg:vectorSimilarity(?s, "text", "idx")` | ✅ |
| **Hybrid** (BM25 + vector) | `{space}_fts_{idx}` + `{space}_vec_{idx}` | GIN tsvector + HNSW | `vg:hybridSearch(?s, "text", "idx", alpha)` | ✅ |

> **Note:** After FTS decoupling (§6.1), full-text search moved from `_vec_` tables to dedicated `_fts_` tables. Hybrid search JOINs both tables on `(subject_uuid, context_uuid)`.

---

## 6. Geo Operations to Support

### 6.1 Core Operations

| Operation | SPARQL Syntax | SQL Translation |
|-----------|--------------|-----------------|
| **Within radius** | `?s spatial:nearby (lat lon radius_km)` | `ST_DWithin(location, ST_MakePoint(lon,lat)::geography, radius_m)` |
| **Distance** | `BIND(vg:geoDistance(?s, lat, lon) AS ?dist)` | `ST_Distance(location, ST_MakePoint(lon,lat)::geography)` |
| **Within box** | `?s spatial:withinBox (south west north east)` | `ST_Within(location, ST_MakeEnvelope(west,south,east,north,4326))` |
| **Nearest N** | `?s spatial:nearby (lat lon -1 limit)` | `ORDER BY location <-> ST_MakePoint(lon,lat)::geography LIMIT N` |

### 6.2 Geo Data Population

Geo data is populated from:
1. **KGEntity properties**: Entities with lat/long slot values
2. **KGFrame slot values**: Frame slots of geo type (KGGeoSlot or similar)
3. **Explicit RDF triples**: WGS84 `wgs:lat` / `wgs:long` predicates

The geo table is maintained as a **synchronized side-table** (similar to the edge table):
- On quad INSERT containing lat/long predicates → populate geo table
- On quad DELETE → remove from geo table
- Admin rebuild operation available

---

## 7. KG-Level Integration

### 7.1 Vector Integration with KG Types and Slots

At the KG level, vector indexes are associated with specific use cases:

| Use Case | Index Name | Source | Dimensions |
|----------|-----------|--------|------------|
| Entity search | `entity_default` | Concatenated entity properties | 384 (MiniLM) |
| Slot semantic search | `slot_{slot_type}` | Slot value text | Varies |
| KG type matching | `kgtype_default` | Type description + properties | 384 |

**Mapping storage** (normalized tables in PostgreSQL, not config files):

```sql
-- Parent: one row per mapping rule (which KG concept → which vector index, how to build text)
CREATE TABLE IF NOT EXISTS {space_id}_vector_mapping (
    mapping_id          SERIAL PRIMARY KEY,
    mapping_type        VARCHAR(50) NOT NULL,       -- 'kgentity', 'kgdocument', 'kgframe', 'kgslot'
    type_uri            VARCHAR(500),               -- specific KG Type URI (NULL = class-level)
    index_name          VARCHAR(255) NOT NULL REFERENCES {space_id}_vector_index(index_name),
    enabled             BOOLEAN NOT NULL DEFAULT TRUE,  -- on/off switch at class or type level
    source_type         VARCHAR(20) NOT NULL DEFAULT 'default',  -- 'default', 'properties', 'slots'
    separator           VARCHAR(20) DEFAULT '. ',
    include_pred_name   BOOLEAN DEFAULT FALSE,
    include_type_desc   BOOLEAN DEFAULT TRUE,
    created_time        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Child: which predicates or slot type URIs feed this mapping
CREATE TABLE IF NOT EXISTS {space_id}_vector_mapping_property (
    property_id     SERIAL PRIMARY KEY,
    mapping_id      INTEGER NOT NULL REFERENCES {space_id}_vector_mapping(mapping_id) ON DELETE CASCADE,
    property_uri    VARCHAR(500) NOT NULL,           -- predicate URI or slot type URI
    property_role   VARCHAR(20) NOT NULL DEFAULT 'include',  -- 'include' or 'exclude'
    ordinal         INTEGER DEFAULT 0,               -- controls concatenation order in search_text
    UNIQUE (mapping_id, property_uri)
);
```

- **`enabled`**: Controls whether vectorization is active for this class or type. Setting `enabled=false` at the class level disables vectorization for all instances of that class (unless overridden by an `enabled=true` type-level mapping).
- **`source_type = 'default'`**: Uses `hasKGraphDescription` + type description. No child rows needed.
- **`source_type = 'properties'`**: Child rows list predicate URIs to include/exclude in search_text.
- **`source_type = 'slots'`**: Child rows list slot type URIs whose values provide the text.

### 7.1.1 Vectorizable KG Classes

The following KG object classes support vectorization:

| KG Class | `mapping_type` value | Default Property | Type Ref Property | Notes |
|----------|---------------------|------------------|-------------------|-------|
| KGEntity | `kgentity` | `hasKGraphDescription` | `hasKGEntityType` | Core searchable objects |
| KGDocument | `kgdocument` | `hasKGraphDescription` | `hasKGDocumentType` | Document-level search |
| KGFrame | `kgframe` | `hasKGraphDescription` | `hasKGFrameType` | Can also include child slot values |
| KGSlot | `kgslot` | `hasKGraphDescription` | `hasKGSlotType` | Individual slot values (e.g., descriptions) |

The property `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription` is the **canonical source** for vectorization text. When a KG object is inserted or updated, the value of this property is used directly as the `search_text` — no property concatenation is needed in the default case.

#### Enabling/Disabling Vectorization

Vectorization is controlled at **two levels** via the `enabled` column in `vector_mapping`:

| Level | `mapping_type` | `type_uri` | `enabled` | Effect |
|-------|---------------|-----------|----------|--------|
| Class-level | `'kgentity'` | `NULL` | `true` | Vectorize **all** KGEntity instances |
| Class-level | `'kgslot'` | `NULL` | `false` | Disable vectorization for **all** KGSlot instances |
| Type-level | `'kgslot'` | `'urn:slot-type:product-description'` | `true` | Enable vectorization for **only** this slot type |
| Type-level | `'kgframe'` | `'urn:frame-type:ProductFrame'` | `true` | Enable for only ProductFrame instances |

**Resolution order** (first match wins, then check `enabled`):
1. **Type-level mapping** — `mapping_type` + `type_uri` match → use this row's `enabled` + `source_type`
2. **Class-level mapping** — `mapping_type` match, `type_uri IS NULL` → use this row's `enabled` + `source_type`
3. **No mapping found** — class is not vectorized (opt-in model)

> **Key design**: Without any mapping rows, a class is **not vectorized**. To enable vectorization, you must insert at least a class-level row with `enabled=true`. This avoids accidentally vectorizing every KGSlot when you only want "product description" slots.

#### Type Description Enrichment

KG objects carry a type reference property (e.g., `hasKGEntityType`, `hasKGDocumentType`, `hasKGFrameType`, `hasKGSlotType`) that points to a KG Type URI. The population pipeline enriches the object by:

1. **Looking up the referenced KG Type** via its type property (e.g., `hasKGEntityType → urn:kgtype:company`)
2. **Fetching the type's description text** from the KG Type's own properties
3. **Populating a type description property** on the object (e.g., `hasKGEntityTypeDescription`)
4. **Including the type description in the vector** — the `search_text` can incorporate both the graph description and the type description for richer semantic search

```
Entity properties (stored as RDF quads):
  hasKGEntityType       → urn:kgtype:company
  hasKGraphDescription  → "Acme Corp manufactures renewable energy panels"

Pipeline enrichment (at vectorization time):
  1. Resolve urn:kgtype:company → KGType with description "Company or corporation entity"
  2. Set hasKGEntityTypeDescription = "Company or corporation entity"
  3. Build search_text = "Acme Corp manufactures renewable energy panels. Company or corporation entity"
  4. Vectorize search_text → embedding
```

**Prerequisite**: KG objects must have `hasKGraphDescription` populated at insert time. Objects without this property are skipped during default vectorization (no error, just not indexed).

#### Mapping Overrides

> **Lineage note:** This override mechanism is the PostgreSQL equivalent of the existing Weaviate collection config in `entity_weaviate_schema.py`, where each property has a `skip_vectorization` flag and `entity_vectorizer.py` maintains `ENTITY_SKIPPED_PROPS` / `LOCATION_SKIPPED_PROPS` sets. The normalized `vector_mapping` + `vector_mapping_property` tables replace both: `property_role='include'` is the inverse of `skip_vectorization`, and `source_type='slots'` extends the model to slot-based text extraction. The `enabled` column provides explicit on/off control that Weaviate lacked.

#### Concrete Examples

**Example A: Vectorize ALL KGEntities (class-level on)**
```sql
-- Turn on vectorization for all KGEntity instances using default hasKGraphDescription
INSERT INTO {space}_vector_mapping
    (mapping_type, type_uri, index_name, enabled, source_type)
VALUES ('kgentity', NULL, 'entity_default', true, 'default');
```

**Example B: Vectorize ONLY "product description" KGSlots (type-level on, class off)**
```sql
-- Class-level: disable vectorization for all KGSlot instances
INSERT INTO {space}_vector_mapping
    (mapping_type, type_uri, index_name, enabled, source_type)
VALUES ('kgslot', NULL, 'entity_default', false, 'default');

-- Type-level override: enable ONLY for product-description slots
INSERT INTO {space}_vector_mapping
    (mapping_type, type_uri, index_name, enabled, source_type)
VALUES ('kgslot', 'urn:slot-type:product-description', 'entity_default', true, 'default');
```
Result: Only KGSlot instances with `hasKGSlotType = urn:slot-type:product-description` are vectorized. All other slots are skipped.

**Example C: Vectorize ProductFrame frames, including specific child slot values**
```sql
-- Class-level: disable vectorization for all KGFrames by default
INSERT INTO {space}_vector_mapping
    (mapping_type, type_uri, index_name, enabled, source_type)
VALUES ('kgframe', NULL, 'entity_default', false, 'default');

-- Type-level override: enable for ProductFrame, build text from child slot values
INSERT INTO {space}_vector_mapping
    (mapping_type, type_uri, index_name, enabled, source_type, separator, include_type_desc)
VALUES ('kgframe', 'urn:frame-type:ProductFrame', 'entity_default', true, 'slots', '. ', false);
-- mapping_id = 3

-- Which child slot types provide the text (concatenated in ordinal order)
INSERT INTO {space}_vector_mapping_property (mapping_id, property_uri, property_role, ordinal) VALUES
    (3, 'urn:slot-type:product-name',        'include', 1),
    (3, 'urn:slot-type:product-description',  'include', 2),
    (3, 'urn:slot-type:product-attributes',   'include', 3);
```
Result: Only ProductFrame KGFrame instances are vectorized. The search_text is built by concatenating the values of the product-name, product-description, and product-attributes child slots.

**Example D: Override specific KGEntity type with custom properties**
```sql
-- KGEntities are already enabled at class level (Example A).
-- Override "company" entities to use specific properties instead of hasKGraphDescription.
INSERT INTO {space}_vector_mapping
    (mapping_type, type_uri, index_name, enabled, source_type, separator, include_type_desc)
VALUES ('kgentity', 'urn:kgtype:company', 'entity_default', true, 'properties', '. ', true);
-- mapping_id = 4

INSERT INTO {space}_vector_mapping_property (mapping_id, property_uri, property_role, ordinal) VALUES
    (4, 'http://vital.ai/ontology/haley-ai-kg#hasName',              'include', 1),
    (4, 'http://vital.ai/ontology/haley-ai-kg#hasDescription',       'include', 2),
    (4, 'http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription', 'include', 3);
```

#### Resolution Precedence (summary)

| Priority | Match | `enabled` check | What happens |
|----------|-------|-----------------|-------------|
| 1 | Type-level mapping (e.g., `kgslot` + `urn:slot-type:product-description`) | Row's `enabled` | If true → vectorize with row's `source_type`; if false → skip |
| 2 | Class-level mapping (e.g., `kgslot` + `NULL`) | Row's `enabled` | If true → vectorize with row's `source_type`; if false → skip |
| 3 | No mapping found | N/A | **Not vectorized** (opt-in model) |

#### Mapping Management API

Mappings must be manageable both programmatically and via REST:

**Python API** (for internal / admin scripts):
```python
# Create a mapping with properties
mapping_id = await mapping_manager.create_mapping(
    space_id="my_space",
    mapping_type="kgtype",
    type_uri="urn:kgtype:company",
    index_name="entity_default",
    source_type="properties",
)
await mapping_manager.add_property(space_id="my_space", mapping_id=mapping_id,
    property_uri="http://vital.ai/ontology/haley-ai-kg#hasName", ordinal=1)
await mapping_manager.add_property(space_id="my_space", mapping_id=mapping_id,
    property_uri="http://vital.ai/ontology/haley-ai-kg#hasDescription", ordinal=2)

# List, update, delete
mappings = await mapping_manager.list_mappings(space_id="my_space")
await mapping_manager.remove_property(space_id="my_space", mapping_id=mapping_id,
    property_uri="http://vital.ai/ontology/haley-ai-kg#hasDescription")
await mapping_manager.delete_mapping(space_id="my_space", mapping_id=mapping_id)
```

**REST API** endpoints (for external tools / UI):
```
# Mapping CRUD
POST   /api/v1/spaces/{space_id}/vector-mappings                — create mapping
GET    /api/v1/spaces/{space_id}/vector-mappings                — list all mappings (with properties)
GET    /api/v1/spaces/{space_id}/vector-mappings/{id}           — get mapping + properties
PUT    /api/v1/spaces/{space_id}/vector-mappings/{id}           — update mapping fields
DELETE /api/v1/spaces/{space_id}/vector-mappings/{id}           — delete mapping (CASCADE deletes properties)

# Property CRUD (child rows)
POST   /api/v1/spaces/{space_id}/vector-mappings/{id}/properties       — add property
DELETE /api/v1/spaces/{space_id}/vector-mappings/{id}/properties/{pid} — remove property

# Index operations
POST   /api/v1/spaces/{space_id}/vector-indexes/{index}/reindex — trigger re-index with current mappings
```

### 7.2 Geo Integration with KG

KGEntities and KGFrameSlots can have geo data:

- **KGGeoSlot**: A slot type that holds lat/long values → auto-populated into geo table
- **KGEntity with location properties**: Entities with `hasLatitude`/`hasLongitude` → auto-populated
- **Entity Registry locations**: Already have lat/long → can share the geo table

### 7.3 KG Query Integration

The `KGQueryCriteriaBuilder` will be extended to support:

```python
# Vector similarity criterion
EntityQueryCriteria(
    vector_search=VectorSearchCriteria(
        query_text="renewable energy company",
        index_name="entity_default",
        min_similarity=0.7,
        limit=20
    )
)

# Geo radius criterion
EntityQueryCriteria(
    geo_filter=GeoFilterCriteria(
        latitude=40.7128,
        longitude=-74.0060,
        radius_km=50
    )
)
```

These translate to the SPARQL property functions described in §4.

---

## 8. Migration from Weaviate

### 8.1 Current Weaviate Usage

From `entity_weaviate_schema.py`:
- **EntityIndex**: Text vectorization of entity properties (name, description, type, categories)
- **LocationIndex**: Geo coordinates + text vectorization of location properties
- **Cross-references**: Entity ↔ Location bidirectional
- **Vectorizer**: `text2vec-transformers` with `paraphrase-multilingual-MiniLM-L12-v2` (384 dims)
- **Geo**: Weaviate `GEO_COORDINATES` type with `geoRange` filters

### 8.2 Migration Path

1. **Phase 1**: Create pgvector/PostGIS tables and populate from existing data
2. **Phase 2**: Switch search queries to PostgreSQL
3. **Phase 3**: Remove Weaviate dependency entirely — delete Weaviate code, config, and infrastructure

### 8.3 What Stays, What Changes

| Aspect | Weaviate | pgvector/PostGIS |
|--------|----------|------------------|
| Vector storage | Weaviate collection | Per-index table with `vector(N)` column |
| Geo storage | `GEO_COORDINATES` property | `geography(Point, 4326)` column |
| Vector search | `near_text` / `near_vector` | `ORDER BY embedding <=> vector` |
| Geo search | `geoRange` filter | `ST_DWithin()` |
| Text vectorization | `text2vec-transformers` container | Local vectorizer or API call |
| Index config | Weaviate collection schema | PostgreSQL tables |
| Cross-references | Weaviate refs | SQL JOINs (already have subject_uuid linking) |

### 8.4 Weaviate Removal Scope

Once pgvector/PostGIS achieves full parity, the following will be deleted:

- `vitalgraph/entity_registry/entity_weaviate.py` — Weaviate index class
- `vitalgraph/entity_registry/entity_weaviate_schema.py` — Weaviate collection schemas
- `vitalgraph/entity_registry/entity_weaviate_ops.py` — Weaviate sync mixin
- `vitalgraph/entity_registry/entity_vectorizer.py` — refactored (keep vectorization logic, remove Weaviate-specific text building)
- `entity_registry/weaviate_sync.py` — CLI sync script
- `entity_registry/weaviate_admin.py` — CLI admin script
- `entity_registry/entity_export_jsonl.py` — Weaviate export
- All `WEAVIATE_*` and `ENTITY_WEAVIATE_*` environment variables
- Weaviate Docker/container infrastructure
- Keycloak JWT auth for Weaviate

### 8.5 Entity Registry CLI (✅ Complete — Weaviate fully removed)

The old `entity_registry/entity_admin.py` has been **superseded** by a new Entity
Registry CLI:

```
vitalgraph/entity_registry_cmd/
├── __init__.py
└── vitalgraph_entity_registry_cmd.py   # ~2090 lines, 39 commands
```

- **Entry point**: `vitalgraphentityregistry` (pyproject.toml console_scripts)
- **Dual mode**: REPL (`vitalgraphentityregistry`) and non-interactive (`-c <command>`)
- **prompt_toolkit**: Tab completion, history, CTRL-C handling

#### Implemented commands (39 — Weaviate-free)

| Category | Commands |
|----------|----------|
| Entity Types | `list-types`, `create-type` |
| Entities | `list-entities`, `get-entity`, `create-entity`, `update-entity`, `delete-entity` |
| Aliases | `list-aliases`, `add-alias`, `retract-alias` |
| Identifiers | `list-identifiers`, `add-identifier`, `lookup-identifier` |
| Categories | `list-categories`, `assign-category`, `remove-category` |
| Relationships | `list-relationship-types`, `list-relationships`, `create-relationship` |
| Same-As | `resolve` |
| Search | `search`, `search-similar` |
| Info | `stats`, `stats-types`, `changelog` |
| Data | `export`, `delete-by-prefix` |
| Dedup | `dedup-status`, `dedup-check` |
| Vector | `vector-status`, `vector-check`, `vector-rebuild`, `vector-sync` |
| Semantic Search | `search-topic` |
| Geo | `geo-status`, `geo-populate`, `geo-check` |
| Schema | `migrate` (with `--dry-run`) |

#### Vector commands (all require `--space <space_id>`)

| Command | Description |
|---------|-------------|
| `vector-status` | Per-space vector index stats (dimensions, row count, provider, model) |
| `vector-check [--index N]` | Consistency check: distinct subjects vs embedding count per index |
| `vector-rebuild --graph <uri> [--index N]` | Drop and re-populate all embeddings via `populate_index()` |
| `vector-sync --graph <uri> [--subject U]` | Incremental re-vectorize (single entity or full) |

#### Semantic search

| Command | Description |
|---------|-------------|
| `search-topic --space S --query <text> [--index N] [--limit N]` | pgvector cosine similarity search using vectorization provider |

Embeds query text via the provider registered in `{space}_vector_index`, then
executes `ORDER BY embedding <=> $1::vector LIMIT N` with LEFT JOIN to `{space}_term`
for subject URI resolution.

#### Geo commands (all require `--space <space_id>`)

| Command | Description |
|---------|-------------|
| `geo-status` | Show `geo_config` settings (enabled, auto_sync, predicates) + geo table row count |
| `geo-populate --graph <uri>` | Run `populate_geo()` for a space/graph context |
| `geo-check` | Consistency check: subjects with lat/lon predicates vs geo table rows |

#### Weaviate removal (✅ Done)

All Weaviate references have been removed from the CLI:
- ✅ Removed `self.weaviate` attribute from `EntityRegistryCLI.__init__`
- ✅ Removed `EntityWeaviateIndex.from_env()` initialization in `_connect()`
- ✅ Removed `self.weaviate.close()` in `_disconnect()`
- ✅ Removed `cmd_weaviate_status` and `cmd_weaviate_check` methods
- ✅ Removed `weaviate-status` / `weaviate-check` from dispatch table
- ✅ Removed `logging.getLogger('weaviate').setLevel(logging.WARNING)`
- ✅ Removed "weaviate" from connection extras display

#### Method name fixes applied during implementation

| CLI calls | Actual mixin method |
|-----------|---------------------|
| `retract_alias` | `remove_alias` |
| `assign_category` | `add_entity_category` |
| `remove_category` | `remove_entity_category` |

Other notes:
- `get_change_log` returns `Tuple[List, int]` — properly unpacked
- `EntityDedupIndexPG(pool)` — requires pool as constructor arg

#### Remaining cleanup (optional)

- `entity_registry/entity_admin.py` — archive or delete (superseded by new CLI)
- `entity_registry/weaviate_admin.py` — delete (superseded)
- `entity_registry/weaviate_sync.py` — delete (superseded)

### 8.6 Auto-Sync Hooks (Implemented)

Automatic re-vectorization and geo population triggered by CRUD operations on
entities, frames, and slots. Changes are processed as **fire-and-forget background
tasks** so the REST response is never blocked.

#### Core module

`vitalgraph/vectorization/auto_sync.py` — provides `schedule_sync()`:

```python
schedule_sync(
    db_impl=backend_impl.db_impl,
    space_id=space_id,
    subject_uris=["http://example.org/entity1"],
    graph_uri=graph_id,
    operation="upsert",  # or "delete"
)
```

- Acquires an asyncpg connection from the pool
- For each subject UUID, calls `update_subject_vector()` / `delete_subject_vectors()`
  across all vector indexes in the space
- Calls `update_subject_geo()` / `delete_subject_geo()` if geo is enabled
  **and** `auto_sync` is true in the `geo_config` table
- All errors are logged but swallowed (never breaks the write path)

#### Integration points

| Endpoint | Method | Operation | File |
|----------|--------|-----------|------|
| KGEntities | `_create_or_update_entities` | upsert (CREATE/UPSERT) | `kgentities_endpoint.py` |
| KGEntities | `_handle_update_mode` | upsert (UPDATE) | `kgentities_endpoint.py` |
| KGEntities | `_handle_entity_only_update` | upsert (ENTITY_ONLY) | `kgentities_endpoint.py` |
| KGEntities | `_delete_entity_by_uri` | delete | `kgentities_endpoint.py` |
| KGEntities | `_delete_entities_by_uris` | delete (batch) | `kgentities_endpoint.py` |
| KGFrames | `_create_frames` | upsert (all modes) | `kgframes_endpoint.py` |
| KGFrames | `_delete_frame_by_uri` | delete | `kgframes_endpoint.py` |
| KGFrames | `_delete_frames_by_uris` | delete (batch) | `kgframes_endpoint.py` |
| KGFrames | `_create_frame_slots` | upsert | `kgframes_endpoint.py` |
| KGFrames | `_update_frame_slots` | upsert | `kgframes_endpoint.py` |
| KGFrames | `_delete_frame_slots` | delete | `kgframes_endpoint.py` |

Each endpoint class has a `_schedule_auto_sync()` helper that extracts `db_impl`
from the backend implementation and delegates to `schedule_sync()`.

#### Design decisions

- **Background task**: Uses `asyncio.create_task()` so the HTTP response is
  returned immediately; sync happens after.
- **Opt-in for vectors**: Only subjects with active vector mappings (in the
  `vector_mapping` table) are re-vectorized. No mapping = no work.
- **Opt-in for geo**: Requires both `enabled=true` and `auto_sync=true` in the
  per-space `geo_config` table.
- **Deterministic UUIDs**: Subject and graph URIs are converted to UUIDs using
  the same `uuid5` algorithm as `sparql_sql_space_impl.py`.

---

## 9. Jena Sidecar Considerations

### 9.1 Current Architecture

The Jena sidecar (`vitalgraph-jena-sidecar/`) parses SPARQL queries via `Algebra.compile(query)` and serializes the Op tree to JSON using `OpSerializer`. The v2 pipeline translates this JSON AST to SQL.

### 9.2 Current Serializer Analysis

**OpSerializer** (`OpSerializer.java`) handles 18+ Op types with structured serialization, plus a **fallback** (line 209) that captures any unknown Op type:

```java
} else {
    result.put("type", op.getClass().getSimpleName());
    result.put("string", op.toString());
}
```

This means if Jena produces `OpPropFunc` for a property function, it would be serialized as `{"type": "OpPropFunc", "string": "..."}` — captured but not structurally parsed.

**ExprSerializer** (`ExprSerializer.java`) handles `ExprFunction1`, `ExprFunction2`, `ExprFunction3`, `ExprFunctionN` — all with `functionIRI` field. Custom FILTER/BIND functions (unknown URIs) will appear as one of these `ExprFunctionN` types with the full IRI, structured args, and proper serialization.

### 9.3 The Two Questions to Test

**Question A: Property functions** — When Jena parses `?s vg:similarTo ("text" 10)`, does `Algebra.compile()` produce:
  1. An `OpPropFunc` node (property function recognized)?
  2. A regular `OpBGP` triple pattern (property function NOT recognized, treated as data)?
  3. A parse error?

Jena only produces `OpPropFunc` if the property function URI is **registered** with the ARQ PropertyFunctionRegistry. Unregistered URIs are likely compiled as regular triple patterns.

**Question B: Custom FILTER/BIND functions** — When Jena parses `FILTER(<http://vital.ai/fn#withinRadius>(?s, 40.73, -73.93, 10.0))`, does it:
  1. Produce an `E_Function` / `ExprFunctionN` node with the IRI and args (expected)?
  2. Fail because the function is unknown?

Jena ARQ is lenient with unknown function URIs in FILTER/BIND — it should produce `E_Function` nodes without evaluation.

### 9.4 Test Plan: Java Test Script

Add a new test class to the sidecar to verify both mechanisms:

**File**: `src/test/java/ai/vital/sparqlcompiler/VectorGeoSparqlTest.java`

```java
package ai.vital.sparqlcompiler;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;

/**
 * Test how the sidecar handles vector/geo SPARQL extensions.
 *
 * Tests two mechanisms:
 * A) Property functions (magic properties): ?s vg:similarTo ("text" 10)
 * B) Custom FILTER/BIND functions: FILTER(vg:withinRadius(...))
 *
 * Results determine which SPARQL syntax we use for vector/geo queries.
 */
class VectorGeoSparqlTest {

    private static SparqlCompiler compiler;
    private static final ObjectMapper mapper = new ObjectMapper();

    @BeforeAll
    static void setUp() {
        compiler = new SparqlCompiler(5000);
    }

    private CompileRequest makeRequest(String sparql) {
        CompileRequest req = new CompileRequest();
        req.sparql = sparql;
        req.phases = new CompileRequest.Phases();
        req.phases.parsedQuery = true;
        req.phases.syntaxTree = true;
        req.phases.algebraCompiled = true;
        req.phases.algebraOptimized = false;
        req.phases.normalizedSparql = true;
        req.phases.updateOperations = false;
        req.trace = new CompileRequest.Trace();
        req.trace.includeTiming = true;
        req.trace.includeWarnings = true;
        req.trace.includePretty = true;
        req.optimize = new CompileRequest.Optimize();
        return req;
    }

    // ================================================================
    // A) Property function tests
    // ================================================================

    @Test
    void testPropertyFunction_UnregisteredURI() {
        // Test: unregistered property function URI
        // Expected: parsed as regular triple pattern (OpBGP), NOT OpPropFunc
        String sparql = """
            PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
            SELECT ?entity WHERE {
                ?entity vg:similarTo "search text" .
            }
            """;
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        System.out.println("=== Property Function (unregistered URI) ===");
        System.out.println("ok: " + resp.ok);
        if (resp.ok) {
            System.out.println("algebra: " + resp.phases.get("algebraCompiled"));
            System.out.println("pretty: " +
                ((Map)resp.phases.get("algebraCompiled")).get("pretty"));
        } else {
            System.out.println("error: " + resp.error);
        }
        // Document result — don't assert yet, we're exploring
    }

    @Test
    void testPropertyFunction_ListArgs() {
        // Test: property function with list arguments (Jena syntax)
        // This is the form used by spatial:nearby etc.
        String sparql = """
            PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
            SELECT ?entity WHERE {
                ?entity vg:similarTo ("search text" 10 "entity_default") .
            }
            """;
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        System.out.println("=== Property Function (list args) ===");
        System.out.println("ok: " + resp.ok);
        if (resp.ok) {
            System.out.println("algebra: " + resp.phases.get("algebraCompiled"));
            System.out.println("pretty: " +
                ((Map)resp.phases.get("algebraCompiled")).get("pretty"));
        } else {
            System.out.println("error: " + resp.error);
        }
    }

    @Test
    void testPropertyFunction_JenaSpatialNearby() {
        // Test: Jena's built-in spatial:nearby — this IS registered in Jena
        String sparql = """
            PREFIX spatial: <http://jena.apache.org/spatial#>
            SELECT ?feature WHERE {
                ?feature spatial:nearby (40.730610 -73.935242 10) .
            }
            """;
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        System.out.println("=== Jena spatial:nearby ===");
        System.out.println("ok: " + resp.ok);
        if (resp.ok) {
            System.out.println("algebra: " + resp.phases.get("algebraCompiled"));
            System.out.println("pretty: " +
                ((Map)resp.phases.get("algebraCompiled")).get("pretty"));
        } else {
            System.out.println("error: " + resp.error);
        }
    }

    // ================================================================
    // B) Custom FILTER/BIND function tests
    // ================================================================

    @Test
    void testFilterFunction_CustomURI() {
        // Test: unknown function URI in FILTER
        // Expected: E_Function / ExprFunctionN node with IRI and args
        String sparql = """
            PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
            SELECT ?entity WHERE {
                ?entity a <http://example.org/Entity> .
                FILTER(vg:withinRadius(?entity, 40.73, -73.93, 10.0))
            }
            """;
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        System.out.println("=== FILTER function (custom URI) ===");
        System.out.println("ok: " + resp.ok);
        if (resp.ok) {
            System.out.println("algebra: " + resp.phases.get("algebraCompiled"));
            System.out.println("pretty: " +
                ((Map)resp.phases.get("algebraCompiled")).get("pretty"));
        } else {
            System.out.println("error: " + resp.error);
        }
        // This SHOULD work — Jena is lenient with unknown filter functions
        assertTrue(resp.ok, "Custom FILTER function should parse successfully");
    }

    @Test
    void testBindFunction_CustomURI() {
        // Test: unknown function URI in BIND
        // Expected: OpExtend with E_Function expression
        String sparql = """
            PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
            SELECT ?entity ?score WHERE {
                ?entity a <http://example.org/Entity> .
                BIND(vg:cosineSimilarity(?entity, "search text", "idx") AS ?score)
            }
            """;
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        System.out.println("=== BIND function (custom URI) ===");
        System.out.println("ok: " + resp.ok);
        if (resp.ok) {
            System.out.println("algebra: " + resp.phases.get("algebraCompiled"));
            System.out.println("pretty: " +
                ((Map)resp.phases.get("algebraCompiled")).get("pretty"));
        } else {
            System.out.println("error: " + resp.error);
        }
        assertTrue(resp.ok, "Custom BIND function should parse successfully");
    }

    @Test
    void testFilterFunction_VectorSearch() {
        // Test: realistic vector search SPARQL
        String sparql = """
            PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?entity ?score WHERE {
                ?entity rdf:type <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                BIND(vg:vectorSimilarity(?entity, "renewable energy", "entity_default") AS ?score)
                FILTER(?score > 0.7)
            }
            ORDER BY DESC(?score)
            LIMIT 20
            """;
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        System.out.println("=== Realistic vector search ===");
        System.out.println("ok: " + resp.ok);
        if (resp.ok) {
            System.out.println("pretty: " +
                ((Map)resp.phases.get("algebraCompiled")).get("pretty"));
        } else {
            System.out.println("error: " + resp.error);
        }
        assertTrue(resp.ok, "Realistic vector search should parse successfully");
    }

    @Test
    void testFilterFunction_GeoSearch() {
        // Test: realistic geo search SPARQL
        String sparql = """
            PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?entity ?distance WHERE {
                ?entity rdf:type <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                BIND(vg:geoDistance(?entity, 40.7128, -74.0060) AS ?distance)
                FILTER(?distance < 50000)
            }
            ORDER BY ?distance
            LIMIT 50
            """;
        CompileRequest req = makeRequest(sparql);
        CompileResponse resp = compiler.compile(req);

        System.out.println("=== Realistic geo search ===");
        System.out.println("ok: " + resp.ok);
        if (resp.ok) {
            System.out.println("pretty: " +
                ((Map)resp.phases.get("algebraCompiled")).get("pretty"));
        } else {
            System.out.println("error: " + resp.error);
        }
        assertTrue(resp.ok, "Realistic geo search should parse successfully");
    }
}
```

**Run with**: `cd vitalgraph-jena-sidecar && mvn test -Dtest=VectorGeoSparqlTest -pl .`

### 9.5 Test Results (✅ 9/9 tests pass)

Tests run on 2026-06-07 via `mvn test -Dtest=VectorGeoSparqlTest`. All 9 pass, 0 failures, 0.4s.

#### A) Property functions — NOT usable without registration

| Test | Result | Jena Op |
|------|--------|---------|
| Unregistered URI (`?entity vg:similarTo "search text"`) | Parsed as regular `OpBGP` triple | `(bgp (triple ?entity vg:similarTo "search text"))` |
| List args (`?entity vg:similarTo ("text" 10 "idx")`) | Decomposed to `rdf:first`/`rdf:rest` chain | `(bgp (triple ?entity vg:similarTo ??0) (triple ??0 rdf:first "search text") ...)` |
| Jena `spatial:nearby` (built-in) | Also decomposed to `rdf:first`/`rdf:rest` (not registered in our build) | Same list decomposition pattern |

**Verdict**: Unregistered property function URIs are treated as plain data triple patterns. List arguments are expanded into RDF list triples. **Not usable** for vector/geo without registering custom property functions in Jena.

#### B) Custom FILTER/BIND functions — ✅ Fully structured, clean JSON AST

| Test | Result | Jena Op → JSON |
|------|--------|----------------|
| `FILTER(vg:withinRadius(?entity, 40.73, -73.93, 10.0))` | ✅ `OpFilter` → `ExprFunctionN` | `functionIRI: "...#withinRadius"`, 4 typed args |
| `BIND(vg:cosineSimilarity(?entity, "text", "idx") AS ?score)` | ✅ `OpExtend` → `ExprFunctionN` | `functionIRI: "...#cosineSimilarity"`, 3 args |
| `BIND(vg:vectorSimilarity(...) AS ?score) FILTER(?score > 0.7) ORDER BY DESC(?score) LIMIT 20` | ✅ Full Op tree: `OpSlice` → `OpProject` → `OpOrder` → `OpFilter` → `OpExtend` → `OpBGP` | All components cleanly serialized |
| `BIND(vg:vectorNearby(?entity, "[0.1,0.2,0.3,0.4]", "idx") AS ?score) FILTER(?score > 0.8)` | ✅ Pre-computed vector string passed through | Same `ExprFunctionN` with string literal arg |
| `BIND(vg:geoDistance(?entity, lat, lon) AS ?distance) FILTER(?distance < 50000) ORDER BY ?distance LIMIT 50` | ✅ Full geo search Op tree | `OpSlice` → `OpProject` → `OpOrder` → `OpFilter` → `OpExtend` → `OpBGP` |
| `FILTER(vg:withinRadius(?entity, 40.7128, -74.0060, 10000))` (geo-only) | ✅ Clean `OpFilter` | `ExprFunctionN` with `functionIRI` + 4 decimal/integer args |

#### Key JSON AST structure (confirmed)

Custom functions appear as `ExprFunctionN` nodes with:
- `"type": "ExprFunctionN"` — always this type (even for 2-3 args)
- `"functionIRI": "http://vital.ai/ontology/vitalgraph#vectorSimilarity"` — full IRI
- `"args": [...]` — array of `ExprVar` or `NodeValue` with datatype info

Numeric literals carry `xsd:decimal` or `xsd:integer` datatype. String literals have no datatype. Variable refs are `ExprVar` with `"var": "entity"`.

#### Decision (confirmed)

- ✅ **FILTER/BIND is the primary syntax**. `ExprSerializer` already serializes all custom functions cleanly. The Python AST mapper only needs to pattern-match on `ExprFunctionN` nodes with `vg:` IRIs.
- ❌ **Property functions NOT viable** without Java-side registration. Deferred to optional Phase 3 (§9.7).
- ✅ **No sidecar Java changes needed** for the primary path.

### 9.6 Sidecar Changes Needed (✅ Confirmed — none)

FILTER/BIND custom functions work perfectly (confirmed by test results in §9.5):

1. **No sidecar Java changes needed** — `ExprSerializer` already handles `ExprFunctionN` with IRI and args
2. **Python-side only**: `jena_ast_mapper.py` needs to recognize `ExprFunctionN` nodes with `vg:` IRIs and map them to `VectorSearchExpr` / `GeoFilterExpr` IR nodes
3. **If we later want property functions**: Add `OpPropFunc` handling to `OpSerializer.java` (structured serialization instead of fallback)

### 9.7 If Property Functions Are Desired Later

To register custom property functions in the sidecar:

```java
// In SparqlCompiler.java or a new initializer
import org.apache.jena.sparql.pfunction.PropertyFunctionRegistry;

// Register a no-op property function that just passes through the Op
PropertyFunctionRegistry.get().put(
    "http://vital.ai/ontology/vitalgraph#similarTo",
    new VitalGraphPropFuncFactory()
);
```

Then add `OpPropFunc` handling to `OpSerializer`:

```java
} else if (op instanceof OpPropFunc propFunc) {
    result.put("type", "OpPropFunc");
    result.put("uri", propFunc.getProperty().getURI());
    result.put("subjectArgs", serializeNodeList(propFunc.getSubjectArgs()));
    result.put("objectArgs", serializeNodeList(propFunc.getObjectArgs()));
    result.put("subOp", serialize(propFunc.getSubOp()));
}
```

This is Phase 3 work — only needed if we want the `?s vg:similarTo ("text" 10)` triple-pattern syntax in addition to FILTER/BIND.

### 9.8 Query Optimization: FILTER Does NOT Mean Post-Filter

**Critical design principle**: The SPARQL FILTER/BIND syntax is purely a parsing convenience. At SQL generation time, our pipeline performs **semantic rewriting** — it does NOT naively translate `FILTER(vg:geoDistance(...) < 50000)` into a SQL `WHERE` clause that runs after fetching all rows.

#### The Optimization Pipeline

```
SPARQL source          → Jena sidecar        → JSON AST
                                                  ↓
                                          jena_ast_mapper.py
                                          (recognizes vg: function IRIs)
                                                  ↓
                                          PlanV2 IR with VectorOp / GeoOp nodes
                                          (EXTRACTED from OpFilter/OpExtend)
                                                  ↓
                                          emit_vector.py / emit_geo.py
                                          (generates OPTIMIZED SQL)
                                                  ↓
                                          SQL with LATERAL JOINs, pushed-down
                                          WHERE clauses on side-tables
```

#### What the AST Mapper Does (Extraction + Rewrite)

When `jena_ast_mapper.py` encounters:
```json
{
  "type": "OpFilter",
  "exprs": [{
    "type": "ExprFunction2",
    "name": "<",
    "args": [
      {"type": "ExprFunctionN", "functionIRI": "http://vital.ai/ontology/vitalgraph#geoDistance", "args": [...]},
      {"type": "NodeValue", "node": {"value": "50000"}}
    ]
  }],
  "subOp": { "type": "OpBGP", ... }
}
```

It does NOT produce: `WHERE vg_geo_distance(...) < 50000` (post-filter).

It produces an IR node:
```python
GeoDistanceFilter(
    subject_var="entity",
    lat=40.7128, lon=-74.0060,
    max_distance_m=50000,        # extracted from the comparison
    result_var="distance",        # from the BIND if present
    join_to=bgp_plan             # knows which BGP to attach to
)
```

#### Optimized SQL Patterns

**Geo radius (pushed into JOIN)**:
```sql
-- NOT: SELECT ... WHERE post_filter_distance < 50000
-- YES: JOIN with ST_DWithin in the ON/WHERE (uses GiST index)
SELECT q1.subject_uuid, geo.latitude, geo.longitude,
       ST_Distance(geo.location, ST_MakePoint(-74.0060, 40.7128)::geography) AS distance
FROM {space_id}_rdf_quad q1
JOIN {space_id}_geo geo
  ON geo.subject_uuid = q1.subject_uuid
  AND geo.context_uuid = q1.context_uuid
  AND ST_DWithin(geo.location, ST_MakePoint(-74.0060, 40.7128)::geography, 50000)
ORDER BY distance
LIMIT 50
```

**Vector similarity (LATERAL subquery with index scan)**:
```sql
-- NOT: SELECT *, similarity_score WHERE similarity_score > 0.7
-- YES: LATERAL join that uses HNSW index for ANN search
SELECT q1.subject_uuid, vec.score
FROM {space_id}_rdf_quad q1
JOIN {space_id}_term t_type ON q1.predicate_uuid = t_type.term_uuid
  AND t_type.term_text = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
JOIN LATERAL (
    SELECT subject_uuid, 1 - (embedding <=> $1::vector) AS score
    FROM {space_id}_vec_entity_default
    WHERE subject_uuid = q1.subject_uuid
) vec ON vec.score > 0.7
ORDER BY vec.score DESC
LIMIT 20
```

**Vector top-K (drives the query)**:
```sql
-- When vector search is the primary constraint (no type filter first),
-- the vector table drives the query and main tables JOIN to it
SELECT vec.subject_uuid, vec.score, t_name.term_text AS name
FROM (
    SELECT subject_uuid, 1 - (embedding <=> $1::vector) AS score
    FROM {space_id}_vec_entity_default
    ORDER BY embedding <=> $1::vector
    LIMIT 20
) vec
JOIN {space_id}_rdf_quad q1 ON q1.subject_uuid = vec.subject_uuid
JOIN {space_id}_term t_pred ON q1.predicate_uuid = t_pred.term_uuid
  AND t_pred.term_text = 'http://vital.ai/ontology/vital-core#hasName'
JOIN {space_id}_term t_name ON q1.object_uuid = t_name.term_uuid
```

#### Optimization Strategies by Query Pattern

| Pattern | Optimization | Index Used |
|---------|-------------|-----------|
| `FILTER(vg:geoDistance(?s, lat, lon) < N)` | Rewritten to `ST_DWithin` JOIN → eliminates post-filter | GiST on `{space}_geo.location` |
| `BIND(vg:geoDistance(?s, lat, lon) AS ?d)` alone | JOIN with `ST_Distance` in SELECT | GiST (distance computation) |
| `BIND(vg:vectorSimilarity(?s, ...) AS ?score) FILTER(?score > 0.7)` | LATERAL JOIN with threshold in subquery | HNSW on `{space}_vec_{idx}.embedding` |
| `vg:similarTo ("text" 10 "idx")` (property func style) | Subquery drives with `ORDER BY ... LIMIT 10` | HNSW index scan |
| Vector + type constraint | Determine which table to drive from based on selectivity | Both indexes |
| Geo + vector combined | Two JOINs to side-tables, planner picks best path | GiST + HNSW |

#### Query Planner Heuristics

The emitter should apply these heuristics to decide which table "drives" the query:

1. **Vector top-K with no other filters**: Vector table drives (subquery with LIMIT), main tables join to results
2. **Vector + type filter**: If type is highly selective, main table drives with LATERAL vector join. If type is broad, vector drives.
3. **Geo radius with type filter**: Main table drives, geo table JOINs with `ST_DWithin` pushed into ON clause
4. **Geo top-K (nearest N)**: Geo table drives with `ORDER BY <-> LIMIT N`, main tables join to results
5. **Combined vector + geo**: Most selective operation drives, other joins as secondary filters

These heuristics can be refined based on table statistics (row counts, index selectivity) if needed.

#### Why This Works Despite FILTER/BIND Syntax

The key insight: **our pipeline is NOT a generic SPARQL evaluator**. We don't treat FILTER as "evaluate expression for each row." Instead:

1. We **pattern-match** on function IRIs during AST mapping
2. We **extract parameters** (lat, lon, radius, vector, limit, threshold) into structured IR nodes
3. We **plan the query** with full knowledge of which tables and indexes exist
4. We **emit optimized SQL** that uses JOINs, LATERAL subqueries, and pushed-down predicates

The SPARQL FILTER/BIND syntax is merely the transport format for getting vector/geo operations through Jena's parser. The SQL output is completely decoupled from how the SPARQL was syntactically expressed.

---

## 10. Implementation Phases

### Phase 0: Jena Sidecar Validation ✅ COMPLETE
- [x] Create `VectorGeoSparqlTest.java` (see §9.4)
- [x] Run tests: all 9 pass — FILTER/BIND custom functions work perfectly
- [x] Document results: `ExprFunctionN` with `functionIRI` and structured `args` in JSON AST
- [x] **Decision**: FILTER/BIND is the primary syntax. No sidecar changes needed.
- [x] Property functions (list args): parse as rdf:first/rdf:rest BGP triples (not OpPropFunc) — not useful without registration

### Phase 0.5: Vectorization Providers ✅ COMPLETE
- [x] Implement vectorization provider interface and registry (`vectorization/base.py`, `registry.py`)
- [x] Implement `VitalSignsProvider` (`vitalsigns_provider.py` — ✅ migrated to ONNX: `vital-model-paraphrase-MiniLM-onnx`, 384 dims, CPU-only via ONNXRuntime, no HuggingFace downloads or network access)
- [x] Implement `OpenAIProvider` (`openai_provider.py` — `text-embedding-3-small`, 1536 dims)
- [x] Unit tests: verify each provider produces correct-dimension embeddings

### Phase 1: Foundation (pgvector + PostGIS setup) ✅ COMPLETE
- [x] Add `CREATE EXTENSION IF NOT EXISTS vector` and `postgis` to service initialization
- [x] Design and implement vector index registry table (with `provider`, `provider_config`)
- [x] Design and implement per-index vector data tables (with `search_text` + `tsv` columns, §5.6)
- [x] Design and implement geo side-table (with `subject_uuid` + `context_uuid` linking)
- [x] Add tables to `sparql_sql_schema.py`
- [x] Add tables to space creation/deletion lifecycle
- [x] Test on local PostgreSQL and AWS RDS

### Phase 2: Data Population ✅ COMPLETE
- [x] Implement `search_text` builder (`vectorization/search_text_builder.py`)
- [x] Implement default vectorization: use `hasKGraphDescription` for KGEntity/KGDocument/KGFrame (§7.1.1)
- [x] Implement type description enrichment: resolve `hasKGEntityType` → KG Type description (§7.1.1)
- [x] Implement mapping override resolution: check vector_mapping + vector_mapping_property (`mapping_manager.py`)
- [x] Implement vector population pipeline (`vector_populator.py` — build search_text → vectorize → store embedding)
- [x] Implement geo population pipeline (`geo_populator.py` — extract lat/long → geo table, §3.2)
- [x] Add auto-sync on entity/slot create/update/delete (`auto_sync.py` + endpoint hooks in §8.6)
- [x] Implement admin re-index commands (CLI: `vector-rebuild`, `vector-sync`, `geo-populate` in §8.5)

### Phase 3: SPARQL Integration ✅ COMPLETE
- [x] Implement `vg_functions.py` — constants (`VG_NS`, 4 function IRIs), argument extraction (`extract_vector_args`, `extract_geo_args`), SQL generation helpers (`vector_similarity_sql`, `geo_distance_sql`, `within_radius_sql`), and `VectorRequest` dataclass for deferred vectorization
- [x] Implement `ExprFunctionN` recognition in `emit_expressions.py` — `_function_to_sql()` dispatches `vg:` IRIs to `_vg_function_to_sql()`, which delegates to the appropriate SQL generator in `vg_functions.py`
- [x] Implement `_is_numeric_expr()` recognition — vector similarity/nearby/geoDistance treated as numeric expressions
- [x] Implement type inference in `sql_type_generation.py` — `_infer_function_type()` returns `xsd:double` for vector/geo distance functions, `xsd:boolean` for `withinRadius`
- [x] Add `VectorRequest` tracking to `EmitContext` — `add_vector_request()` method, `vector_requests` property, shared across parent/child contexts
- [x] Wire `vector_requests` into `GenerateResult` + `generator.py` — orchestrator can inspect pending vectorization requests after SQL generation
- [x] Implement orchestrator vectorization (`vg_resolve.py`): look up vector index → provider, vectorize search text, replace `__VG_EMBED_*__` placeholders with actual embedding literals before SQL execution
- [x] Wire vectorization into both execution paths: `SparqlOrchestrator.execute()` (Phase 3b) and `SparqlSQLSpaceImpl.execute_sparql_query()` (production)
- [x] Add `context_uuid` scoping to vector/geo subqueries: `_context_clause()` adds `AND context_uuid = (...)` when `graph_lock_uri` is set, ensuring multi-graph correctness
- [x] Unit tests (`test_vg_functions.py` — 26 tests): detection, arg extraction, SQL generation, type inference, placeholder substitution, EmitContext sharing, emit_expressions integration, context scoping
- [x] Implement query planner heuristics (`vg_optimize.py`): pre-emit pass detects SLICE→ORDER→EXTEND(vg:vector*) top-K and FILTER threshold patterns, annotates plan tree with hints; `emit_extend` uses hints to generate vector-driving JOIN SQL (HNSW index drives) or threshold pushdown in WHERE clause
- [x] Live end-to-end tests (`test_scripts/test_vector_geo_e2e.py` — 4/4 pass): vectorNearby ranking, geoDistance ordering, withinRadius filtering, combined vector+geo query all verified against real PostgreSQL with pgvector+PostGIS

### Phase 4: KG Integration ✅ COMPLETE
- [x] Implement vector mapping manager (`vectorization/mapping_manager.py` — Python API for CRUD)
- [x] Implement REST API endpoints for vector mapping management (`vector_mappings_endpoint.py`, wired in `vitalgraphapp_impl.py`)
- [x] Implement REST API endpoints for geo config management (`geo_config_endpoint.py`, wired in `vitalgraphapp_impl.py`)
- [x] Implement Entity Registry CLI commands for vector/geo (`vitalgraph_entity_registry_cmd.py` §8.5)
- [x] Implement REST API endpoints for vector index management (`vector_indexes_endpoint.py`: list/create/get/delete/reindex)
- [x] Extend `KGQueryCriteriaBuilder` with vector/geo criteria: added `VectorCriteria` and `GeoCriteria` dataclasses, `_build_vector_geo_clauses()` method generates BIND/FILTER/ORDER BY/LIMIT overrides, wired into `build_entity_query_sparql()` with `vg:` prefix; supports `vectorSimilarity`, `vectorNearby`, `geoDistance`, `withinRadius`, threshold filter, top-K limit, custom score/distance variables
- [x] Extend KGEntity/KGFrame endpoints with vector/geo query parameters: added `VectorSearchCriteria` and `GeoSearchCriteria` Pydantic models with validation (kgentities_model.py), added to `KGQueryCriteria` (kgqueries_model.py), wired conversion in `_execute_entity_query` (kgquery_endpoint.py); 28 end-to-end tests pass
- [x] Add geo slot type handling (auto-populate geo table from KGGeoSlot): created `geo_slot_handler.py` — detects KGGeoLocationSlot on write, parses `hasGeoLocationSlotValue` (comma/space/JSON formats), resolves owning entity via frame_entity table or edge traversal, upserts entity geo point; wired into `auto_sync._sync_geo_for_subjects`; added `vital-aimp#hasLatitude/hasLongitude` to default predicate sets; 22 unit tests pass
- [x] Implement `GET /api/geo?space_id=...` endpoint for listing/querying geo points (`geo_points_endpoint.py`, wired in `vitalgraphapp_impl.py`; supports pagination, spatial radius filter via ST_DWithin, graph_uri scoping, distance-ordered results; 4/4 tests pass)
- [x] Client-based geo integration test (`vitalgraph_client_test/test_geo_points_endpoint.py` — 9/9 pass): creates space via client, enables geo config, inserts KGEntities with `KGGeoLocationSlot` triggering auto-sync geo population, validates spatial queries/pagination/graph filtering/error cases, cleans up
- [x] Comprehensive SPARQL geo tests (`test_scripts/test_geo_sparql_all.py` — 7/7 pass): `vg:withinRadius`, `vg:geoDistance`, `vg:withinBounds`, combined radius+distance ordering, known-distance verification (Empire State ~1066m, Central Park ~3244m, Brooklyn Bridge ~5843m from Times Square)

### Phase 5: Weaviate Removal (partially complete)
- [x] Remove Weaviate from Entity Registry CLI (§8.5 — all weaviate-* commands, init, attributes removed)
- [ ] Switch all search queries to PostgreSQL
- [ ] Delete all Weaviate code files (see §8.4: `entity_weaviate.py`, `entity_weaviate_schema.py`, etc.)
- [ ] Remove Weaviate from Docker Compose / ECS deployment
- [ ] Remove Weaviate Keycloak client and credentials

### Phase 6: API Consistency — No Dynamic Path Parameters ✅ COMPLETE

**Rule**: No dynamic items in the URL path. All identifiers (`space_id`, `index_name`, `mapping_id`, `property_id`, etc.) must be passed as **query parameters**. URL paths are static route segments only.

**Before** (path params — WRONG):
```
GET /api/spaces/{space_id}/vector-indexes/{index_name}
GET /api/spaces/{space_id}/vector-mappings/{mapping_id}/properties/{property_id}
```

**After** (query params only — CORRECT):
```
GET /api/vector-indexes?space_id=...&index_name=...
GET /api/vector-mappings?space_id=...&mapping_id=...
DELETE /api/vector-mappings/properties?space_id=...&mapping_id=...&property_id=...
GET /api/geo?space_id=...
GET /api/geo-config?space_id=...
```

**Affected endpoints** (backend):
- [x] `vector_indexes_endpoint.py` — all path params removed; `space_id`, `index_name` are query params
- [x] `vector_mappings_endpoint.py` — all path params removed; `space_id`, `mapping_id`, `property_id` are query params
- [x] `geo_points_endpoint.py` — `space_id` is a query param
- [x] `geo_config_endpoint.py` — `space_id` is a query param

**Affected client code**:
- [x] TypeScript client (`vitalgraph-client-ts/src/endpoint/VectorIndexesEndpoint.ts`, `VectorMappingsEndpoint.ts`, `GeoConfigEndpoint.ts`, `GeoPointsEndpoint.ts`) — all routes use query params
- [x] Frontend `VectorGeoService.ts` — delegates to TS client (`vgClient.vectorIndexes`, `vgClient.vectorMappings`, `vgClient.geoConfig`, `vgClient.geoPoints`); no raw `fetch`/`apiService` calls remain
- [x] Python client (`vitalgraph/client/endpoint/`) — all vector/geo endpoint methods use query params

### Phase 7: Multi-Vector Query ✅ COMPLETE

`vg:multiVectorSimilarity` / `vg:multiVectorNearby` SPARQL functions for weighted fusion across multiple vector indexes.

- [x] SPARQL builder: `MultiVectorCriteria` + `MultiVectorCriteriaInput` dataclasses in `kg_query_builder.py`
- [x] Pydantic models: `MultiVectorSearchCriteria` + `WeightedVectorInput` in `kgentities_model.py`, `multi_vector_criteria` field on `KGQueryCriteria`
- [x] REST endpoint wiring: `kgquery_endpoint.py` converts Pydantic → builder, passes `multi_vector_config` to SQL generator
- [x] SQL generation: CTE-per-vector + weighted sum in `vg_functions.py`; three fusion strategies:
  - `weighted_sum` (default) — simple weighted combination of raw cosine scores
  - `relative_score` — window-function normalization (MIN/MAX scaling per index)
  - `ranked` — Reciprocal Rank Fusion via `ROW_NUMBER()` CTEs
- [x] Mixed-model auto-detect: when indexes use different `model_name`/`dimensions`, auto-upgrades from `weighted_sum` to `relative_score`
  - `generator.py` Stage 2e pre-loads `{space}_vector_index` metadata
  - `vg_functions.py` checks `ctx.vector_index_meta` for model mismatches
- [x] Configurable oversample factor: `MultiVectorSearchCriteria.oversample_factor` (default 5, max 50)
- [x] INTERSECT semantics: `FILTER(BOUND(?score))` always emitted to exclude entities missing from any index
- [x] `EmitContext` extensions: `multi_vector_config` dict + `vector_index_meta` dict; propagated to child contexts
- [x] `SparqlSQLSpaceImpl.execute_sparql_query()` passes `multi_vector_config` kwargs to `generate_sql()`
- [x] Unit tests: 54/54 pass in `test_kg_query_builder_vector_geo.py` (multi-vector criteria, fusion config, Pydantic integration)
- [x] End-to-end tests: 7/7 pass in `test_sparql_sql_multi_vector.py` (equal weights, weighted fusion ranking, INTERSECT semantics, min_score threshold)
- [x] Benchmarks: correlated pattern (SPARQL multi-vector function) confirmed optimal — 0.12–0.27ms per entity via btree lookup

Full details: `planning_multi_vector/multi_vector_query_plan.md`

### Phase 8: Direct Vector Upsert / Get API ✅ COMPLETE

Client-provided pre-computed embeddings — no server-side vectorization.

- [x] Pydantic models: `VectorEntry`, `VectorUpsertRequest`, `VectorUpsertResponse`, `VectorGetOut`, `VectorGetResponse` in `model/vector_indexes_model.py`
- [x] Server handlers: `upsert_vectors()` and `get_vectors()` in `vector_indexes_endpoint.py`
- [x] Routes: `POST /api/vector-indexes/vectors?space_id=&index_name=` (upsert), `GET /api/vector-indexes/vectors?space_id=&index_name=&subject_uri=&graph_uri=` (get)
- [x] Python client: `upsert_vectors()` and `get_vectors()` on `VectorIndexesClientEndpoint`
- [x] TypeScript client: `upsertVectors()` and `getVectors()` on `VectorIndexesEndpoint`
- [x] UUID generation: uses `uuid5(ns, "{uri}\x00U")` — consistent with quad table term UUIDs
- [x] Dimension validation, idempotent `ON CONFLICT DO UPDATE`, resolves UUIDs back to URIs via term table

See §5.4.1 for full API documentation.

### Bugs Found & Fixed (June 2026)

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| **UUID mismatch in vector upsert/get endpoints** | `vector_indexes_endpoint.py` used `f"U:{uri}"` for UUID generation; quad table uses `f"{uri}\x00U"` | Fixed to `f"{uri}\x00U"` in both `upsert_vectors` and `get_vectors` |
| **UUID mismatch in auto_sync** | `auto_sync.py` used `f"{term_type}:{term_text}"` | Fixed to `f"{term_text}\x00{term_type}"` |
| **INTERSECT semantics not enforced in multi-vector** | `BIND()` assigns NULL for missing entities but doesn't filter them out | Added `FILTER(BOUND(?score))` in `kg_query_builder.py` |
| **KGDocument re-segmentation hook** | SPARQL UPDATE on document content predicates didn't trigger re-segmentation | Added `collect_segmentation_targets_from_update_ops` hook in `sparql_sql_space_impl.py` |

---

## 11. Open Questions / Research Items

1. **Jena sidecar property function pass-through**: **Resolved** — tested via `VectorGeoSparqlTest.java` (9/9 tests pass). FILTER/BIND custom functions parse cleanly as `ExprFunctionN` with `functionIRI` in the JSON AST. Property functions (list-arg syntax) decompose into rdf:first/rdf:rest BGP triples without registration. **Decision: Use FILTER/BIND as primary syntax. No sidecar Java changes needed.**

2. **Vectorization at query time**: **Resolved** — three sources supported (see §5.5):
   - Pre-computed vector passed in by the caller
   - External provider API (OpenAI, Cohere, etc.) called Python-side before SQL execution
   - VitalSigns built-in ONNX model (default/fallback) — `vital-model-paraphrase-MiniLM-onnx`, 384 dims, CPU-only, no network access
   - All vectorization happens Python-side; the database never calls external APIs

3. **Multiple distance metrics per index**: Should we support creating the same data with different metrics (cosine + L2)? This would require multiple HNSW indexes on the same table or separate tables.
   - **Recommendation**: One metric per named index. Users create separate indexes if they need different metrics.

4. **Vector dimension limits**: pgvector supports up to 2,000 indexed dimensions (HNSW/IVFFlat). For larger models (e.g., OpenAI ada-002 at 1,536), this is fine. For very large models, we'd need dimensionality reduction.

5. **Geo data model**: **Resolved** — separate side-table is required (not optional). PostGIS `geography` type needs its own column with a GiST index; this cannot live in the term table. The geo table is linked to RDF data via `subject_uuid` + `context_uuid` JOINs, and is auto-populated from lat/long literal triples. See §3.2 for full details.

6. **Index maintenance under updates**: **Resolved** — implemented in `maintenance_job.py`. Each cycle scans `pg_stat_user_tables` for `{space}_vec_*` tables, evaluates dead tuple ratio (>20% threshold, >1000 min dead, 24h cooldown), picks worst candidate, runs `REINDEX INDEX CONCURRENTLY` on the HNSW index. Exposed via `POST /api/processes/trigger {"process_type": "vector_reindex", "space_id": "..."}`. Uses thread-offloaded psycopg or asyncpg fallback, consistent with ANALYZE/VACUUM.

7. **Weaviate removal**: Weaviate will be fully removed once pgvector/PostGIS is implemented. No dual-write or parity verification needed — straight cutover.

---

## 12. Dependencies

- **PostgreSQL 15+** with `pgvector` 0.8.0+ and `PostGIS` 3.4+
- **asyncpg**: Already used by sparql_sql backend (pgvector types may need registration)
- **pgvector Python**: `pip install pgvector` for asyncpg type registration
- **Embedding models**:
  - Built-in (✅ migrated to ONNX): `vital-model-paraphrase-MiniLM-onnx` (384 dims) — bundled ONNX weights, CPU-only via ONNXRuntime, no HuggingFace downloads. Provider: `VitalSignsProvider` in `vitalsigns_provider.py`.
  - External: OpenAI `text-embedding-3-small` (1536 dims), Cohere, etc. via API
- **API keys**: Stored in environment variables, referenced by name in `provider_config` JSONB
- **No new infrastructure services**: Everything runs in PostgreSQL + Python (unlike Weaviate which required a separate cluster + text2vec-transformers container)
- **No HuggingFace network access**: The `vitalsigns` provider uses locally-bundled ONNX model weights (`vital-model-paraphrase-MiniLM-onnx` package). Server starts without internet access.

### 12.1 Related: Entity Dedup Fuzzy Search → PostgreSQL (✅ Complete)

The entity near-duplicate detection index has been migrated from Redis/MemoryDB to PostgreSQL as part of the broader consolidation strategy. This represents a **fourth form of text search** in the system:

| Search Type | Technique | Scope | Use Case |
|-------------|-----------|-------|----------|
| **SPARQL pattern matching** | GIN trigram on `{space}_term` | All literals | LIKE, REGEX, CONTAINS |
| **Full-text search** | tsvector + GIN on `{space}_vec_{idx}` | Indexed content fields | Keyword/phrase matching with stemming and ranking |
| **Vector search** | pgvector HNSW on `{space}_vec_{idx}` | Limited properties (entity type, entity content) | Semantic similarity (meaning-based) |
| **Fuzzy name search (dedup)** | MinHash LSH bands + RapidFuzz | Limited properties (person/business names, aliases) | Near-duplicate detection, typo tolerance, phonetic matching |

Both vector search and fuzzy name search are **scoped to specific properties and slot types**, not applied to all strings. Vector search targets entity type classification and entity content descriptions. Fuzzy name search targets person names, business names, and aliases — a small, well-defined set of properties where typo tolerance and phonetic matching are critical.

The fuzzy search layer uses character n-gram shingling and phonetic codes to find entities with similar names despite typos, abbreviations, and transliterations — cases where both keyword search and embedding similarity may miss matches.

- **Implementation**: `entity_dedup_storage.py` + `entity_dedup_pg.py` (MinHash LSH bands stored in PG tables)
- **Activation**: `ENTITY_DEDUP_BACKEND=postgresql`
- **Details**: See `planning_vector_geo/dedup_redis_to_postgresql_plan.md`

#### Future: SPARQL Integration for Fuzzy Name Search

Currently the fuzzy name search is accessed via the Entity Registry REST API (`find_similar`). A future enhancement would expose it as a SPARQL custom function, consistent with how vector and geo search are integrated:

```sparql
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
# Find entities with names fuzzy-matching a query (MinHash LSH + phonetic)
SELECT ?entity ?name ?score WHERE {
    ?entity a <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
    ?entity <http://vital.ai/ontology/vital-core#hasName> ?name .
    BIND(vg:fuzzyNameMatch(?entity, "Jon Smyth") AS ?score)
    FILTER(?score > 50.0)
}
ORDER BY DESC(?score)
LIMIT 10
```

This would map to the same MinHash LSH band lookup + RapidFuzz scoring pipeline but invoked from within a SPARQL query, analogous to `vg:vectorSimilarity` and `vg:withinRadius`. The implementation would register a custom SPARQL function that queries the `entity_dedup_band` / `entity_dedup_phonetic_band` tables and returns a score.

#### Property-to-Index Mapping (PostgreSQL-stored, replacing Weaviate config)

Currently, the Weaviate collection schema (`entity_weaviate_schema.py`) defines which entity properties participate in vectorization (`skip_vectorization=True/False`) and which properties are used for fuzzy name matching (hardcoded in `entity_dedup.py`). For the PostgreSQL-native approach, this mapping should be stored in the database itself — similar to how `{space_id}_vector_mapping` maps KG concepts to vector indexes:

```sql
-- Property-to-search-index mapping (replaces Weaviate collection config)
CREATE TABLE IF NOT EXISTS {space_id}_search_mapping (
    mapping_id      SERIAL PRIMARY KEY,
    search_type     VARCHAR(50) NOT NULL,   -- 'vector', 'fuzzy_name', 'fulltext', 'geo'
    index_name      VARCHAR(255),           -- references {space_id}_vector_index(index_name)
    source_type     VARCHAR(50) NOT NULL,   -- 'entity_registry', 'kgentity', 'kgframe_slot'
    property_uri    VARCHAR(500),           -- RDF property URI or entity registry field name
    role            VARCHAR(50) NOT NULL,   -- 'primary_name', 'alias', 'content', 'type_description'
    -- Vector-specific metadata (which kind of vector for this property)
    provider        VARCHAR(50),            -- 'openai', 'vitalsigns', 'cohere', null for non-vector
    model_name      VARCHAR(255),           -- 'text-embedding-3-small', 'paraphrase-multilingual-MiniLM-L12-v2'
    dimensions      SMALLINT,              -- 384, 1536, etc.
    modality        VARCHAR(50),           -- 'text', 'image', 'multimodal', null for non-vector
    config          JSONB,                  -- additional config (api_key_env, phonetic, shingle_k, etc.)
    created_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

The `provider`, `model_name`, `dimensions`, and `modality` columns capture which **kind** of vector is associated with each property — analogous to how Weaviate's collection config binds `text2vec-transformers` to specific properties. This enables:
- Multiple vector types per entity (e.g., text embedding for name, image embedding for photo)
- Model versioning (swap `text-embedding-3-small` → `text-embedding-3-large` per property)
- Mixed providers (OpenAI for content, local MiniLM for type classification)

Example rows:

| search_type | source_type | property_uri | role | provider | model_name | dims | modality | config |
|-------------|-------------|--------------|------|----------|------------|------|----------|--------|
| `vector` | `entity_registry` | `primary_name` | `content` | `vitalsigns` | `paraphrase-multilingual-MiniLM-L12-v2` | 384 | `text` | `{"vectorize": true}` |
| `vector` | `entity_registry` | `description` | `content` | `vitalsigns` | `paraphrase-multilingual-MiniLM-L12-v2` | 384 | `text` | `{"vectorize": true}` |
| `vector` | `entity_registry` | `type_description` | `content` | `openai` | `text-embedding-3-small` | 1536 | `text` | `{"api_key_env": "OPENAI_API_KEY"}` |
| `vector` | `entity_registry` | `country` | — | — | — | — | — | `{"vectorize": false, "filter": true}` |
| `vector` | `kgentity` | `vital-core:hasName` | `content` | `openai` | `text-embedding-3-small` | 1536 | `text` | `{"api_key_env": "OPENAI_API_KEY"}` |
| `vector` | `kgentity` | `haley-ai-kg:hasImage` | `image` | `openai` | `clip-vit-large-patch14` | 768 | `image` | `{"api_key_env": "OPENAI_API_KEY"}` |
| `fuzzy_name` | `entity_registry` | `primary_name` | `primary_name` | — | — | — | — | `{"phonetic": true, "shingle_k": 3}` |
| `fuzzy_name` | `entity_registry` | `alias_name` | `alias` | — | — | — | — | `{"phonetic": true}` |
| `fuzzy_name` | `kgentity` | `vital-core:hasName` | `primary_name` | — | — | — | — | `{"phonetic": true}` |
| `geo` | `entity_registry` | `latitude/longitude` | `coordinates` | — | — | — | — | `{}` |

This replaces the Weaviate collection schema's property-by-property `skip_vectorization` flags and vectorizer binding with a unified, queryable mapping stored in PostgreSQL. All search types (vector, fuzzy name, full-text, geo) use the same mapping table, making it easy to see at a glance which properties feed which search indexes, and with which vector kind (provider, model, dimensions, modality).

## 13. References

- [pgvector GitHub](https://github.com/pgvector/pgvector)
- [AWS RDS pgvector 0.8.0 announcement](https://aws.amazon.com/about-aws/whats-new/2024/11/amazon-rds-for-postgresql-pgvector-080/)
- [PostGIS ST_DWithin docs](https://postgis.net/docs/ST_DWithin.html)
- [AWS RDS PostGIS docs](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Appendix.PostgreSQL.CommonDBATasks.PostGIS.html)
- [Jena ARQ Extensions](https://jena.apache.org/documentation/query/extension.html)
- [Jena GeoSPARQL](https://jena.apache.org/documentation/geosparql/)
- [GeoSPARQL OGC Standard](https://docs.ogc.org/is/22-047r1/22-047r1.html)
- [pgvector HNSW vs IVFFlat](https://aws.amazon.com/blogs/database/optimize-generative-ai-applications-with-pgvector-indexing-a-deep-dive-into-ivfflat-and-hnsw-techniques/)
