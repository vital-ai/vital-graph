# Direct SQL for Entity Graph & Frame Retrieval

## Overview

This document proposes bypassing the SPARQL→SQL pipeline for a set of well-defined, high-frequency read operations and instead issuing **hand-crafted SQL (with prepared statements)** directly against the PostgreSQL quad/term tables. The operations in scope are:

1. **Get entity graph** — retrieve all objects belonging to an entity (entity + frames + slots + edges grouped by `hasKGGraphURI`)
2. **Get entity frames** — list/paginate frames for an entity, optionally with their complete frame graphs
3. **Query entities by frame/slot criteria** — the "frame" query type in `/kgqueries`, where entities are filtered by frame type and slot value constraints
4. **Relation queries** — the "relation" query type in `/kgqueries`, where entities are connected via `Edge_hasKGRelation`

These are the dominant read patterns in the KG API surface and currently account for the majority of SPARQL pipeline invocations.

---

## Current Architecture (SPARQL→SQL)

Every read operation follows this path:

```
Endpoint → Build SPARQL string → Jena sidecar (parse + algebra) → jena_ast_mapper
    → collect (IR) → rewrite (MV) → emit (SQL) → execute → rows → SPARQL bindings
    → triples → VitalSigns objects → response
```

### Key files in the current flow

| Layer | File | Role |
|-------|------|------|
| **Endpoint** | `vitalgraph/endpoint/kgentities_endpoint.py` | REST routes, orchestration |
| **Endpoint** | `vitalgraph/endpoint/kgquery_endpoint.py` | KGQueries REST routes |
| **SPARQL builders** | `vitalgraph/sparql/kg_connection_query_builder.py` | Builds SPARQL for relation/frame queries |
| **SPARQL builders** | `vitalgraph/sparql/kg_query_builder.py` | Builds SPARQL for entity criteria queries |
| **SPARQL builders** | `vitalgraph/sparql/grouping_uri_queries.py` | Builds SPARQL for entity/frame graph retrieval |
| **kg_impl** | `vitalgraph/kg_impl/kgentity_get_impl.py` | Entity retrieval orchestration |
| **kg_impl** | `vitalgraph/kg_impl/kg_graph_retrieval_utils.py` | Entity/frame graph SPARQL + triple conversion |
| **kg_impl** | `vitalgraph/kg_impl/kg_sparql_query.py` | Frame listing/retrieval via SPARQL |
| **kg_impl** | `vitalgraph/kg_impl/kgframe_graph_impl.py` | Frame graph retrieval |
| **kg_impl** | `vitalgraph/kg_impl/kg_backend_utils.py` | Backend adapter (routes to execute_sparql_query) |
| **DB objects** | `vitalgraph/db/sparql_sql/sparql_sql_db_objects.py` | Two-phase SPARQL query pattern |
| **Pipeline** | `vitalgraph/db/sparql_sql/sparql_sql_space_impl.py` | `execute_sparql_query()` — sidecar + generate_sql + execute |
| **Pipeline** | `vitalgraph/db/sparql_sql/generator.py` | `generate_sql()` — collect/emit/rewrite |
| **Schema** | `vitalgraph/db/sparql_sql/sparql_sql_schema.py` | Table DDL: `{space}_rdf_quad`, `{space}_term` |

### Overhead in the current flow

For a single "get entity graph" call:
1. **SPARQL string construction** — Python string formatting
2. **Jena sidecar HTTP call** — ~5–15ms network + JVM parse time
3. **AST mapping** — Python dict traversal
4. **collect/emit/rewrite** — IR construction, MV detection, SQL generation
5. **Constant materialization** — term lookups for every URI in the SPARQL query
6. **SQL execution** — the actual database query
7. **Result conversion** — rows → SPARQL bindings → rdflib triples → VitalSigns objects

Steps 1–5 and 7 are pure overhead when the target SQL is predictable and static.

---

## Proposed Architecture (Direct SQL)

```
Endpoint → Direct SQL module → execute prepared statement → rows → VitalSigns objects → response
```

### Core Idea

For each well-defined operation, write a **single parameterized SQL query** (or a small set of them) that can be executed as a PostgreSQL prepared statement. The SQL is known at development time — it only varies by parameter values (entity URI, graph UUID, slot type, value, etc.).

### Data Model Recap

```sql
-- {space}_term: URI/literal dictionary
term_uuid    UUID PRIMARY KEY
term_text    TEXT        -- the actual URI or literal value
term_type    CHAR(1)     -- 'U' (URI), 'L' (Literal), 'B' (BNode)
lang         VARCHAR(20)
datatype_id  BIGINT

-- {space}_rdf_quad: the quad store
subject_uuid   UUID
predicate_uuid UUID
object_uuid    UUID
context_uuid   UUID
```

All UUIDs are **deterministic** (UUID v5 of the term text + type), computed by `_generate_term_uuid()`. This means we can compute the UUID of any known URI in Python without a database lookup.

### Well-Known URIs (Pre-Computable UUIDs)

These are ontology constants used in every query. Their UUIDs can be computed once at startup:

```python
# Predicates
VITALTYPE        = uuid5("http://vital.ai/ontology/vital-core#vitaltype", "U")
HAS_EDGE_SOURCE  = uuid5("http://vital.ai/ontology/vital-core#hasEdgeSource", "U")
HAS_EDGE_DEST    = uuid5("http://vital.ai/ontology/vital-core#hasEdgeDestination", "U")
HAS_KG_GRAPH_URI = uuid5("http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI", "U")
HAS_FRAME_GRAPH_URI = uuid5("http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI", "U")
HAS_KG_FRAME_TYPE = uuid5("http://vital.ai/ontology/haley-ai-kg#hasKGFrameType", "U")
HAS_KG_SLOT_TYPE  = uuid5("http://vital.ai/ontology/haley-ai-kg#hasKGSlotType", "U")
HAS_NAME         = uuid5("http://vital.ai/ontology/vital-core#hasName", "U")

# Edge types (object UUIDs)
EDGE_HAS_KG_RELATION = uuid5("http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation", "U")
EDGE_HAS_ENTITY_KG_FRAME = uuid5("http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame", "U")
EDGE_HAS_KG_SLOT = uuid5("http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot", "U")

# Slot value predicates (per slot class)
HAS_TEXT_SLOT_VALUE    = uuid5("http://vital.ai/ontology/haley-ai-kg#hasTextSlotValue", "U")
HAS_INTEGER_SLOT_VALUE = uuid5("http://vital.ai/ontology/haley-ai-kg#hasIntegerSlotValue", "U")
HAS_DOUBLE_SLOT_VALUE  = uuid5("http://vital.ai/ontology/haley-ai-kg#hasDoubleSlotValue", "U")
# ... etc
```

---

## Operation-by-Operation SQL Design

### 1. Get Entity Graph

**Current**: SPARQL UNION query finding `<entity> ?p ?o` + `?s hasKGGraphURI <entity>. ?s ?p ?o`
**See**: `kg_graph_retrieval_utils.py:160-206`

**Direct SQL**:
```sql
-- Step 1: Find all subject UUIDs belonging to this entity graph
WITH entity_subjects AS (
    SELECT DISTINCT subject_uuid
    FROM {space}_rdf_quad
    WHERE predicate_uuid = $1        -- hasKGGraphURI
      AND object_uuid = $2           -- uuid5(entity_uri)
      AND context_uuid = $3          -- uuid5(graph_id)
    UNION
    SELECT $2 AS subject_uuid        -- the entity itself
)
-- Step 2: Get all triples for those subjects
SELECT q.subject_uuid, q.predicate_uuid, q.object_uuid,
       st.term_text AS s_text, st.term_type AS s_type,
       pt.term_text AS p_text,
       ot.term_text AS o_text, ot.term_type AS o_type,
       ot.lang AS o_lang, dt.datatype_uri AS o_datatype
FROM {space}_rdf_quad q
JOIN entity_subjects es ON q.subject_uuid = es.subject_uuid
JOIN {space}_term st ON q.subject_uuid = st.term_uuid
JOIN {space}_term pt ON q.predicate_uuid = pt.term_uuid
JOIN {space}_term ot ON q.object_uuid = ot.term_uuid
LEFT JOIN {space}_datatype dt ON ot.datatype_id = dt.datatype_id
WHERE q.context_uuid = $3
  AND pt.term_text NOT IN (
      'http://vital.ai/vitalgraph/direct#hasEntityFrame',
      'http://vital.ai/vitalgraph/direct#hasFrame',
      'http://vital.ai/vitalgraph/direct#hasSlot'
  )
```

**Parameters**: `($1=hasKGGraphURI_uuid, $2=entity_uuid, $3=graph_uuid)`

**Advantage**: One round-trip, no sidecar, no IR. The CTE `entity_subjects` replaces the SPARQL UNION. The materialized predicate filter is a static list.

### 2. List Entity Frames (Paginated)

**Current**: Two SPARQL queries — frame discovery + count
**See**: `kg_sparql_query.py:214-243`

**Direct SQL**:
```sql
-- Find frames connected to entity via Edge_hasEntityKGFrame
SELECT DISTINCT
    dest_q.object_uuid AS frame_uuid,
    ft.term_text AS frame_uri
FROM {space}_rdf_quad type_q
JOIN {space}_rdf_quad src_q  ON type_q.subject_uuid = src_q.subject_uuid
JOIN {space}_rdf_quad dest_q ON type_q.subject_uuid = dest_q.subject_uuid
JOIN {space}_term ft ON dest_q.object_uuid = ft.term_uuid
WHERE type_q.predicate_uuid = $1   -- vitaltype
  AND type_q.object_uuid = $2      -- Edge_hasEntityKGFrame
  AND src_q.predicate_uuid = $3    -- hasEdgeSource
  AND src_q.object_uuid = $4       -- uuid5(entity_uri)
  AND dest_q.predicate_uuid = $5   -- hasEdgeDestination
  AND type_q.context_uuid = $6     -- uuid5(graph_id)
ORDER BY frame_uri
LIMIT $7 OFFSET $8
```

**Count variant**: Same query with `SELECT COUNT(DISTINCT dest_q.object_uuid)` and no LIMIT/OFFSET.

### 3. Get Frame Graph

**Current**: SPARQL query to find subjects with `hasFrameGraphURI = frame_uri`, then fetch all triples
**See**: `kgframe_graph_impl.py`

**Direct SQL**: Same CTE pattern as entity graph, but using `hasFrameGraphURI` instead of `hasKGGraphURI`.

### 4. Query Entities by Frame/Slot Criteria (KGQueries "frame" type)

**Current flow**: `kgquery_endpoint.py:181-298` → `kg_query_builder.py:281-479` → SPARQL → pipeline → SQL
**See**: `kg_query_builder.py:360-419` for frame/slot pattern generation

This is the most complex case. The current SPARQL builds a chain:
```
entity → Edge_hasEntityKGFrame → frame → Edge_hasKGSlot → slot → slotValue
```

**Direct SQL** (example: one frame criterion with one slot criterion):
```sql
SELECT DISTINCT entity_t.term_text AS entity_uri
FROM {space}_rdf_quad entity_type_q
-- Entity type check
JOIN {space}_term entity_t ON entity_type_q.subject_uuid = entity_t.term_uuid
-- Entity → Frame edge
JOIN {space}_rdf_quad fe_type_q ON fe_type_q.context_uuid = entity_type_q.context_uuid
JOIN {space}_rdf_quad fe_src_q  ON fe_type_q.subject_uuid = fe_src_q.subject_uuid
JOIN {space}_rdf_quad fe_dst_q  ON fe_type_q.subject_uuid = fe_dst_q.subject_uuid
-- Frame type filter
JOIN {space}_rdf_quad frame_type_q ON fe_dst_q.object_uuid = frame_type_q.subject_uuid
-- Frame → Slot edge
JOIN {space}_rdf_quad se_type_q ON se_type_q.context_uuid = entity_type_q.context_uuid
JOIN {space}_rdf_quad se_src_q  ON se_type_q.subject_uuid = se_src_q.subject_uuid
JOIN {space}_rdf_quad se_dst_q  ON se_type_q.subject_uuid = se_dst_q.subject_uuid
-- Slot type + value
JOIN {space}_rdf_quad slot_type_q ON se_dst_q.object_uuid = slot_type_q.subject_uuid
JOIN {space}_rdf_quad slot_val_q  ON se_dst_q.object_uuid = slot_val_q.subject_uuid
JOIN {space}_term val_t ON slot_val_q.object_uuid = val_t.term_uuid
WHERE entity_type_q.predicate_uuid = $1    -- vitaltype
  AND entity_type_q.object_uuid = ANY($2)  -- KGEntity types
  AND entity_type_q.context_uuid = $3      -- graph_uuid
  -- Frame edge constraints
  AND fe_type_q.predicate_uuid = $1        -- vitaltype
  AND fe_type_q.object_uuid = $4           -- Edge_hasEntityKGFrame
  AND fe_src_q.predicate_uuid = $5         -- hasEdgeSource
  AND fe_src_q.object_uuid = entity_type_q.subject_uuid
  AND fe_dst_q.predicate_uuid = $6         -- hasEdgeDestination
  -- Frame type filter
  AND frame_type_q.predicate_uuid = $7     -- hasKGFrameType
  AND frame_type_q.object_uuid = $8        -- uuid5(frame_type_uri)
  -- Slot edge constraints
  AND se_type_q.predicate_uuid = $1        -- vitaltype
  AND se_type_q.object_uuid = $9           -- Edge_hasKGSlot
  AND se_src_q.predicate_uuid = $5         -- hasEdgeSource
  AND se_src_q.object_uuid = fe_dst_q.object_uuid  -- frame
  AND se_dst_q.predicate_uuid = $6         -- hasEdgeDestination
  -- Slot type + value
  AND slot_type_q.predicate_uuid = $10     -- hasKGSlotType
  AND slot_type_q.object_uuid = $11        -- uuid5(slot_type_uri)
  AND slot_val_q.predicate_uuid = $12      -- hasTextSlotValue (varies by slot class)
  AND val_t.term_text = $13                -- the actual value to match
ORDER BY entity_uri
LIMIT $14 OFFSET $15
```

**Note**: For variable numbers of frame/slot criteria, the SQL must be **dynamically composed** at the Python level (building the JOIN chain based on criteria count), but each composed query uses only parameterized values — no string interpolation of user data.

### 5. Relation Queries (KGQueries "relation" type)

**Current flow**: `kgquery_endpoint.py:126-179` → `kg_connection_query_builder.py:31-67`

**Direct SQL** (outgoing direction):
```sql
SELECT DISTINCT
    src_t.term_text AS source_entity,
    dst_t.term_text AS destination_entity,
    edge_t.term_text AS relation_edge,
    rtype_t.term_text AS relation_type
FROM {space}_rdf_quad type_q
JOIN {space}_rdf_quad src_q   ON type_q.subject_uuid = src_q.subject_uuid
JOIN {space}_rdf_quad dst_q   ON type_q.subject_uuid = dst_q.subject_uuid
JOIN {space}_rdf_quad rtype_q ON type_q.subject_uuid = rtype_q.subject_uuid
JOIN {space}_term edge_t  ON type_q.subject_uuid = edge_t.term_uuid
JOIN {space}_term src_t   ON src_q.object_uuid = src_t.term_uuid
JOIN {space}_term dst_t   ON dst_q.object_uuid = dst_t.term_uuid
JOIN {space}_term rtype_t ON rtype_q.object_uuid = rtype_t.term_uuid
WHERE type_q.predicate_uuid = $1   -- vitaltype
  AND type_q.object_uuid = $2      -- Edge_hasKGRelation
  AND src_q.predicate_uuid = $3    -- hasEdgeSource
  AND dst_q.predicate_uuid = $4    -- hasEdgeDestination
  AND rtype_q.predicate_uuid = $5  -- hasKGRelationType
  AND type_q.context_uuid = $6     -- graph_uuid
  -- Optional source entity filter
  AND ($7::uuid IS NULL OR src_q.object_uuid = $7)
  -- Optional relation type filter
  AND ($8::uuid IS NULL OR rtype_q.object_uuid = ANY($8))
ORDER BY source_entity, destination_entity
```

With the **edge maintained table** (from `mv_to_maintained_table_plan.md`), this simplifies dramatically:
```sql
SELECT DISTINCT
    src_t.term_text AS source_entity,
    dst_t.term_text AS destination_entity,
    edge_t.term_text AS relation_edge,
    rtype_t.term_text AS relation_type
FROM {space}_edge e
JOIN {space}_rdf_quad rtype_q ON e.edge_uuid = rtype_q.subject_uuid
JOIN {space}_term edge_t  ON e.edge_uuid = edge_t.term_uuid
JOIN {space}_term src_t   ON e.source_node_uuid = src_t.term_uuid
JOIN {space}_term dst_t   ON e.dest_node_uuid = dst_t.term_uuid
JOIN {space}_term rtype_t ON rtype_q.object_uuid = rtype_t.term_uuid
WHERE rtype_q.predicate_uuid = $1  -- hasKGRelationType
  AND e.context_uuid = $2          -- graph_uuid
  AND ($3::uuid IS NULL OR e.source_node_uuid = $3)
  AND ($4::uuid IS NULL OR rtype_q.object_uuid = ANY($4))
ORDER BY source_entity, destination_entity
```

---

## Result-to-VitalSigns Conversion

The direct SQL queries return term text, type, lang, and datatype directly. This allows building rdflib triples without the intermediate SPARQL JSON binding format:

```python
from rdflib import URIRef, Literal

def rows_to_triples(rows):
    triples = []
    for row in rows:
        s = URIRef(row['s_text'])
        p = URIRef(row['p_text'])
        if row['o_type'] == 'U':
            o = URIRef(row['o_text'])
        else:
            o = Literal(row['o_text'], lang=row.get('o_lang'),
                       datatype=URIRef(row['o_datatype']) if row.get('o_datatype') else None)
        triples.append((s, p, o))
    return triples

# Then: VitalSigns().from_triples_list(triples)
```

This eliminates the `_rows_to_sparql_bindings` → `_extract_bindings` → `_triples_to_vitalsigns` chain.

---

## Pros and Cons

### Pros

| Benefit | Detail |
|---------|--------|
| **Eliminates sidecar latency** | ~5–15ms per query saved (network + JVM SPARQL parse) |
| **No IR overhead** | Skips collect/emit/rewrite/constant-materialization (~2–10ms) |
| **Prepared statements** | PostgreSQL caches the query plan after first execution; subsequent calls skip planning entirely |
| **Predictable SQL** | No risk of suboptimal SQL from the general-purpose SPARQL translator |
| **Simpler debugging** | SQL is visible in the codebase, not generated at runtime |
| **Fewer conversions** | rows → triples → VitalSigns (skips SPARQL JSON bindings intermediate) |
| **No MV/rewrite dependency** | Entity graph and frame queries don't need edge_mv or frame_entity_mv — they use grouping URIs |
| **Easier to optimize** | Can add targeted indexes, use CTEs, tune individual queries without affecting the general pipeline |

### Cons

| Cost | Detail |
|------|--------|
| **Two code paths** | SPARQL pipeline remains for general/ad-hoc queries; direct SQL adds a parallel path for specific operations |
| **Schema coupling** | Direct SQL is tightly coupled to the `rdf_quad`/`term` table schema; schema changes require updating both paths |
| **Dynamic query composition** | Frame/slot criteria queries require building SQL dynamically (variable number of JOINs); this is simpler than SPARQL generation but still involves string building |
| **Maintenance burden** | Two implementations of the same logic (SPARQL-based and SQL-based) must stay in sync |
| **No SPARQL fallback** | If direct SQL has a bug, there's no automatic fallback to the SPARQL path (must be explicitly configured) |
| **Less portable** | Direct SQL is PostgreSQL-specific; the SPARQL pipeline is theoretically backend-agnostic |
| **VitalSigns conversion unchanged** | The `from_triples_list()` cost remains — this is the dominant remaining overhead |

### Risk Mitigation

- **Dual-path toggle**: Add a configuration flag (`use_direct_sql: true/false`) per operation so the SPARQL path remains available as fallback
- **Shared test suite**: Run the same functional tests against both paths to ensure correctness parity
- **Schema migration hook**: If `rdf_quad`/`term` schema changes, a single module (`direct_sql_queries.py`) needs updating

---

## Codebase Changes Required

### New Files

| File | Purpose |
|------|---------|
| `vitalgraph/db/sparql_sql/direct_sql_constants.py` | Pre-computed UUIDs for well-known URIs, shared across all direct SQL queries |
| `vitalgraph/db/sparql_sql/direct_sql_entity.py` | Direct SQL for get entity, get entity graph, list entities |
| `vitalgraph/db/sparql_sql/direct_sql_frames.py` | Direct SQL for list frames, get frame graph |
| `vitalgraph/db/sparql_sql/direct_sql_kgqueries.py` | Direct SQL for frame-criteria and relation queries |
| `vitalgraph/db/sparql_sql/direct_sql_utils.py` | `rows_to_triples()`, `rows_to_vitalsigns()`, prepared statement management |

### Modified Files

| File | Change |
|------|--------|
| `vitalgraph/kg_impl/kg_backend_utils.py` | Add direct SQL dispatch in `get_entity()`, `get_entity_graph()`, `execute_sparql_query()` — check config flag, route to direct SQL or SPARQL path |
| `vitalgraph/kg_impl/kg_graph_retrieval_utils.py` | Add `get_entity_graph_direct()` method that calls `direct_sql_entity.py` |
| `vitalgraph/kg_impl/kg_sparql_query.py` | Add `_list_entity_frames_direct()` alongside `_list_entity_frames()` |
| `vitalgraph/endpoint/kgquery_endpoint.py` | Add direct SQL path in `_execute_relation_query()` and `_execute_frame_query()` |
| `vitalgraph/db/sparql_sql/sparql_sql_space_impl.py` | Add `execute_direct_sql()` method that acquires a connection and runs parameterized SQL |
| `vitalgraph/db/sparql_sql/sparql_sql_db_objects.py` | Add direct SQL variants of `get_objects_by_uris()`, `list_objects()` |

### Unchanged Files

- The entire SPARQL→SQL pipeline (`generator.py`, `collect.py`, `emit_bgp.py`, `rewrite_edge_mv.py`, etc.) remains untouched
- The Jena sidecar remains available for ad-hoc SPARQL queries
- All write operations continue using the existing paths

---

## Implementation Plan

### Phase 1: Constants & Utilities (P0)

1. Create `direct_sql_constants.py` with pre-computed UUIDs for all well-known predicates and edge types
2. Create `direct_sql_utils.py` with:
   - `rows_to_triples()` — convert query rows to rdflib triples
   - `rows_to_vitalsigns()` — convert rows → triples → VitalSigns objects
   - Prepared statement helper (wraps `conn.prepare()` with caching)

### Phase 2: Entity Graph Retrieval (P1)

1. Implement `direct_sql_entity.get_entity_graph()` with the CTE-based query
2. Wire into `kg_graph_retrieval_utils.py` behind a config flag
3. Test: verify identical results vs SPARQL path for all entity graph test cases

### Phase 3: Frame Listing & Graph (P1)

1. Implement `direct_sql_frames.list_entity_frames()` and `direct_sql_frames.get_frame_graph()`
2. Wire into `kg_sparql_query.py` behind config flag
3. Test: verify identical results vs SPARQL path

### Phase 4: KGQueries — Relation Queries (P1)

1. Implement `direct_sql_kgqueries.execute_relation_query()`
2. Wire into `kgquery_endpoint.py`
3. Test: run `test_sparql_sql_kgqueries` relation tests (R1–R8) against both paths

### Phase 5: KGQueries — Frame/Slot Criteria Queries (P2)

1. Implement dynamic SQL composition for variable frame/slot criteria chains
2. Handle all slot value types (text, integer, double, datetime, boolean)
3. Handle hierarchical frame criteria (parent → child frames)
4. Wire into `kgquery_endpoint.py`
5. Test: run `test_sparql_sql_kgqueries` frame tests against both paths

### Phase 6: Performance Validation (P2)

1. EXPLAIN ANALYZE each direct SQL query and compare with SPARQL-generated SQL
2. Verify prepared statement plan caching is active
3. Benchmark: latency comparison (direct SQL vs SPARQL pipeline) for each operation
4. Document results

---

## Discussion Points

### 1. Prepared Statement Lifecycle

PostgreSQL prepared statements are **per-connection**. With a connection pool, each connection will prepare the statement on first use, then reuse the cached plan. asyncpg's `conn.prepare()` supports this natively. The question is whether to:
- **Prepare on first call** (lazy) — simpler, no startup cost
- **Prepare on connection checkout** — guaranteed fast first query, but adds pool overhead

Recommendation: **Lazy preparation** — the first call per connection pays ~1ms for plan preparation; subsequent calls are free.

### 2. Dynamic SQL for Variable Criteria

Frame/slot criteria queries have a variable number of JOIN chains. Two approaches:
- **Dynamic SQL composition** — build the SQL string in Python based on criteria count, use parameterized values for all user data
- **Fixed SQL with LATERAL joins** — use a single query with LATERAL subqueries for each criterion

Recommendation: **Dynamic composition** — it's what the SPARQL builder already does (building SPARQL strings dynamically), but now we build SQL directly, which is simpler and eliminates the SPARQL→SQL translation layer.

### 3. When to Keep SPARQL

The SPARQL pipeline should remain the **default** for:
- Ad-hoc SPARQL queries from external clients
- Complex queries not covered by the direct SQL operations (e.g., CONSTRUCT, ASK, DESCRIBE)
- New operations during prototyping (SPARQL is faster to iterate on)
- Operations where the generated SQL is already optimal

### 4. Interaction with Maintained Tables

The maintained edge table (`{space}_edge`) from `mv_to_maintained_table_plan.md` directly benefits relation queries. If implemented, the direct SQL relation query should use the edge table instead of the 3-join pattern on `rdf_quad`. The direct SQL module should detect whether the edge table exists and use the optimized query path.

### 5. Term Table Join Cost

Every direct SQL query JOINs `{space}_term` to resolve UUIDs back to text. This is unavoidable given the current schema (UUID-based quad store). If this becomes a bottleneck:
- Consider a **denormalized quad table** with text columns (at the cost of storage)
- Or a **materialized column** on rdf_quad for frequently-accessed predicates

For now, the term table has a primary key index on `term_uuid`, so lookups are O(1).

### 6. Backward Compatibility with fuseki_postgresql Backend

The direct SQL module is specific to the `sparql_sql` backend. The `fuseki_postgresql` backend continues to use Fuseki for queries. The `kg_backend_utils.py` adapter should only dispatch to direct SQL when the backend is `SparqlSQLSpaceImpl`.

---

## Testing Approach

### Unit Tests

1. **`test_direct_sql_constants.py`** — verify UUID computation matches `_generate_term_uuid()` for all well-known URIs
2. **`test_direct_sql_utils.py`** — verify `rows_to_triples()` produces identical output to the SPARQL binding conversion chain

### Integration Tests (A/B Comparison)

For each operation, run the **same test case** through both paths and compare results:

```python
async def test_get_entity_graph_parity():
    """Verify direct SQL returns identical results to SPARQL path."""
    # SPARQL path
    sparql_result = await retriever.get_entity_graph(space_id, graph_id, entity_uri)
    # Direct SQL path
    direct_result = await direct_sql_entity.get_entity_graph(conn, space_id, graph_id, entity_uri)
    # Compare
    assert set(sparql_result) == set(direct_result)
```

### Regression Tests

Run existing test suites with direct SQL enabled:
- `test_sparql_sql_kgqueries` — 35/35 tests
- `test_sparql_sql_kgrelations` — 32/32 tests (if applicable)
- `test_sparql_sql_lead_dataset` — entity graph retrieval tests

### Performance Tests

For each operation, measure and compare:
- **Total latency** (endpoint to response)
- **SQL execution time** (PostgreSQL only)
- **Pipeline overhead** (total - SQL execution)

---

## Execution Priority

| # | Step | Priority | Depends On |
|---|------|----------|------------|
| 1 | Constants + utilities | P0 | — |
| 2 | Entity graph direct SQL | P1 | Step 1 |
| 3 | Frame listing direct SQL | P1 | Step 1 |
| 4 | Relation queries direct SQL | P1 | Steps 1, maintained edge table |
| 5 | Frame/slot criteria direct SQL | P2 | Step 1 |
| 6 | A/B parity tests | P1 | Steps 2–5 |
| 7 | Performance benchmarks | P2 | Step 6 |
| 8 | Config flag + production rollout | P2 | Steps 6–7 |

---

## Open Questions

1. **Batch entity graph retrieval**: When `_get_entities_by_uris` fetches N entity graphs concurrently, should we combine them into a single SQL query with `object_uuid = ANY(array_of_entity_uuids)` for the `hasKGGraphURI` lookup? This would reduce N queries to 1.

2. **Text search in direct SQL**: The SPARQL path uses `CONTAINS(LCASE(...))` which maps to `ILIKE` or `LOWER() LIKE` in SQL. Should the direct SQL use the existing trigram GIN index (`idx_{space}_term_trgm`) directly via `term_text ILIKE '%search%'`?

3. **OFFSET/LIMIT for relation queries**: Currently the SPARQL pipeline returns all results and the endpoint does in-memory pagination (`connections[start_idx:end_idx]`). Direct SQL can push LIMIT/OFFSET into the query. Should we always do this?

4. **Cache invalidation for prepared statements**: If the schema changes (e.g., new indexes), do prepared statements automatically pick up the new plans? (Answer: Yes, PostgreSQL invalidates prepared statement plans when the underlying schema changes.)

5. **Slot value comparators beyond equality**: The current SPARQL builder supports `gt`, `lt`, `gte`, `lte`, `contains`, `ne`. The direct SQL needs to handle all of these, potentially with different SQL for text vs numeric comparisons. Should we use `term_text::numeric` casting for numeric comparisons, or rely on a separate numeric column?
