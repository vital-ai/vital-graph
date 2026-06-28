# Materialized View → Maintained Table Migration Plan

## Overview

The v2 SPARQL-to-SQL pipeline uses several auxiliary database resources during query generation. These resources must stay fresh as data changes through the REST API, not just after bulk loads.

### Auxiliary Resources Used During Query Generation

| # | Resource | Purpose | Current Implementation | Staleness Risk |
|---|----------|---------|----------------------|----------------|
| 1 | `{space}_term` | Resolve URI/literal constants to UUIDs | Regular table, populated with quads | Low (append-only) |
| 2 | `{space}_rdf_pred_stats` | Predicate cardinality for join reorder | Regular table, only populated by admin `StatsRebuildOp` | **High** |
| 3 | `{space}_rdf_stats` | Predicate+object co-occurrence for join reorder | Regular table, only populated by admin `StatsRebuildOp` | **High** |
| 4 | `{space}_edge` | Edge traversal optimization (2 quad JOINs → 1 lookup) | ✅ Regular table, populated on first access | Low (will be incremental) |
| 5 | `{space}_frame_entity` | Frame-entity lookup (depends on edge table) | ✅ Regular table, populated on first access | Low (will be incremental) |
| 6 | `{space}_datatype` | Map datatype_id → XSD URI for type-aware SQL | Regular table, seeded at space creation | Low (rarely changes) |

Resources #2-5 go stale during normal entity CRUD operations via the REST API. This plan migrates all four to **application-maintained tables** that are updated incrementally as data changes, with utilities to resync from scratch and hooks for bulk operations.

> **Status**: Resources #4 and #5 have been migrated from materialized views to regular tables. Resources #2 and #3 still need incremental sync on write.

### Key Design Principles

1. **Never stale** — All auxiliary resources are updated as part of every entity create/update/delete operation, so queries always see current data.
2. **Resyncable** — Utility functions can rebuild any auxiliary table from scratch by scanning `rdf_quad`, for disaster recovery or after manual DB edits.
3. **Bulk-aware** — After bulk load operations, a single function call resyncs all auxiliary tables and runs ANALYZE to update PostgreSQL planner statistics.
4. **Minimal write overhead** — Incremental sync adds 1-2 SQL statements per entity graph mutation, not per-quad.

### Problems Addressed

1. **~~MV rewrite not matching~~** ✅ FIXED — var_slots co-reference detection enabled in `rewrite_edge_table.py`. KGQuery patterns (R1, R4, R8) now use edge table with 1.8-5.4× speedup.
2. **~~MV staleness~~** ✅ FIXED — Both `edge_mv` and `frame_entity_mv` replaced by regular tables (`{space}_edge`, `{space}_frame_entity`). All old MVs dropped from database.
3. **Stats staleness** — `rdf_pred_stats` and `rdf_stats` are never updated during REST API operations. Fixed by incremental sync (this plan).
4. **~~Stub MV detection~~** ✅ FIXED — No longer needed; MVs replaced by tables with `CREATE TABLE IF NOT EXISTS`.

---

## Current Architecture

### Files Involved

| File | Role |
|------|----- |
| `vitalgraph/db/sparql_sql/ensure_edge_table.py` | DDL: create edge table if missing, populate from rdf_quad |
| `vitalgraph/db/sparql_sql/rewrite_edge_table.py` | IR rewrite: replace quad pairs with edge table lookup |
| `vitalgraph/db/sparql_sql/ensure_frame_entity_table.py` | DDL: create frame_entity table if missing, populate from edge + rdf_quad |
| `vitalgraph/db/sparql_sql/rewrite_frame_entity_table.py` | IR rewrite: replace slot groups with frame_entity table lookup |
| `vitalgraph/db/sparql_sql/generator.py` | Orchestrator: calls ensure + rewrite in Stage 2a |
| `vitalgraph/db/sparql_sql/ir.py` | IR dataclasses: `PlanV2`, `VarSlot`, `TableRef` |
| `vitalgraph/db/sparql_sql/sparql_sql_space_impl.py` | Space impl: entity CRUD, quad operations |
| `vitalgraph/db/sparql_sql/sparql_sql_schema.py` | Schema DDL: edge + frame_entity tables in create/drop |
| `vitalgraph_sparql_sql/dawg_test_impl/dawg_space_manager.py` | Test schema: edge + frame_entity tables in create/drop |

**Deleted files** (replaced by above):
- `ensure_mv.py`, `ensure_frame_entity_mv.py`, `rewrite_edge_mv.py`, `rewrite_frame_entity_mv.py`

### Edge Table Schema ✅ Implemented

```sql
CREATE TABLE IF NOT EXISTS {space}_edge (
    edge_uuid        UUID NOT NULL,
    source_node_uuid UUID NOT NULL,
    dest_node_uuid   UUID NOT NULL,
    context_uuid     UUID NOT NULL,
    PRIMARY KEY (edge_uuid, context_uuid)
);
```

**Indexes:**
- `idx_{space}_edge_src_dst (source_node_uuid, dest_node_uuid)`
- `idx_{space}_edge_dst_src (dest_node_uuid, source_node_uuid)`
- `idx_{space}_edge_edge (edge_uuid)`
- `idx_{space}_edge_ctx (context_uuid)`

**Population query** (used by `ensure_edge_table()` when table is empty):
```sql
INSERT INTO {space}_edge (edge_uuid, source_node_uuid, dest_node_uuid, context_uuid)
SELECT src.subject_uuid, src.object_uuid, dst.object_uuid, src.context_uuid
FROM {space}_rdf_quad src
JOIN {space}_rdf_quad dst
    ON dst.subject_uuid = src.subject_uuid AND dst.context_uuid = src.context_uuid
WHERE src.predicate_uuid = (SELECT term_uuid FROM {space}_term WHERE term_text = 'hasEdgeSource' AND term_type = 'U')
  AND dst.predicate_uuid = (SELECT term_uuid FROM {space}_term WHERE term_text = 'hasEdgeDestination' AND term_type = 'U')
ON CONFLICT DO NOTHING;
```

### Frame-Entity Table Schema ✅ Implemented

```sql
CREATE TABLE IF NOT EXISTS {space}_frame_entity (
    frame_uuid           UUID NOT NULL,
    source_entity_uuid   UUID,
    dest_entity_uuid     UUID,
    context_uuid         UUID NOT NULL,
    PRIMARY KEY (frame_uuid, context_uuid)
);
```

**Indexes:**
- `idx_{space}_fe_src_frame (source_entity_uuid, frame_uuid)`
- `idx_{space}_fe_dst_frame (dest_entity_uuid, frame_uuid)`
- `idx_{space}_fe_frame (frame_uuid)`
- `idx_{space}_fe_ctx (context_uuid)`

**Population query** (used by `ensure_frame_entity_table()` when table is empty):
```sql
INSERT INTO {space}_frame_entity (frame_uuid, source_entity_uuid, dest_entity_uuid, context_uuid)
SELECT
    emv.source_node_uuid AS frame_uuid,
    (array_agg(sv.object_uuid) FILTER (WHERE st.object_uuid = '{src_uuid}'::uuid))[1],
    (array_agg(sv.object_uuid) FILTER (WHERE st.object_uuid = '{dst_uuid}'::uuid))[1],
    emv.context_uuid
FROM {space}_edge emv
JOIN {space}_rdf_quad st ON st.subject_uuid = emv.dest_node_uuid AND st.predicate_uuid = '{st_uuid}'::uuid
JOIN {space}_rdf_quad sv ON sv.subject_uuid = emv.dest_node_uuid AND sv.predicate_uuid = '{sv_uuid}'::uuid
WHERE st.object_uuid IN ('{src_uuid}'::uuid, '{dst_uuid}'::uuid)
GROUP BY emv.source_node_uuid, emv.context_uuid
HAVING (array_agg(sv.object_uuid) FILTER (WHERE st.object_uuid = '{src_uuid}'::uuid))[1] IS NOT NULL
   AND (array_agg(sv.object_uuid) FILTER (WHERE st.object_uuid = '{dst_uuid}'::uuid))[1] IS NOT NULL
ON CONFLICT DO NOTHING;
```

---

## Problem 1: Co-Reference Chain Through `vitaltype` Quad

### Background: How Co-References Are Created

The v2 `collect.py` **does** produce explicit co-reference constraints in `tagged_constraints`.
When a SPARQL variable appears in a second (or third) triple, collect creates a constraint
linking the new quad alias to the **first** alias that introduced the variable:

```python
# collect.py lines 109-116
if node.name in plan.var_slots:
    first = plan.var_slots[node.name]
    first_uuid = f"{first.positions[0][0]}.{first.positions[0][1]}"
    constraint = f"{full_uuid} = {first_uuid}"           # always points to FIRST occurrence
    plan.constraints.append(constraint)
    plan.tagged_constraints.append((q_id, constraint))
    first.positions.append((q_id, uuid_col_name))
```

### Why WordNet Edge Patterns Worked

WordNet SPARQL queries had simple edge patterns:

```sparql
?edge hasEdgeSource ?source .
?edge hasEdgeDestination ?dest .
```

Collect processes in order:
- **q0** (`hasEdgeSource`): `?edge` first occurrence → new VarSlot, no constraint
- **q1** (`hasEdgeDestination`): `?edge` second occurrence → constraint: **`q1.subject_uuid = q0.subject_uuid`**

The rewrite regex `_COREF_RE` finds `q1` (dst) directly referencing `q0` (src) → **match** ✅

### Why KGQuery Edge Patterns Fail

The `KGConnectionQueryBuilder` always emits a `vitaltype` triple **before** the edge pair:

```sparql
?relation_edge vital:vitaltype <Edge_hasKGRelation> .       ← introduces variable first
?relation_edge vital:hasEdgeSource ?source_entity .
?relation_edge vital:hasEdgeDestination ?destination_entity .
```

Collect processes:
- **q1** (`vitaltype`): `?relation_edge` first occurrence → new VarSlot
- **q2** (`hasEdgeSource`): second occurrence → constraint: **`q2.subject_uuid = q1.subject_uuid`**
- **q3** (`hasEdgeDestination`): third occurrence → constraint: **`q3.subject_uuid = q1.subject_uuid`**

The rewrite regex checks each constraint:
- `q2.subject_uuid = q1.subject_uuid` → q2 is src ✓, but **q1 is the vitaltype quad**, not in `dst_quads` ❌
- `q3.subject_uuid = q1.subject_uuid` → q3 is dst ✓, but **q1 is the vitaltype quad**, not in `src_quads` ❌

**No direct src↔dst constraint exists.** Both co-references chain through the vitaltype quad.

### Summary Table

| Scenario | First triple on edge var | Co-ref chain | Rewrite matches? |
|----------|--------------------------|-------------|-------------------|
| **WordNet** | `hasEdgeSource` (src quad) | dst → src (direct) | ✅ Yes |
| **KGQuery** | `vitaltype` (neither src nor dst) | src → vitaltype, dst → vitaltype (indirect) | ❌ No |

### Diagnostic Evidence (from logs)

```
rewrite_edge_mv: found src/dst quads but no co-reference pairs.
    src={'q2': 'c_3'}, dst={'q3': 'c_4'}
rewrite_edge_mv: potential var_slots co-ref via ?relation_edge:
    q2(src) + q3(dst) — NOT YET REWRITING
```

### Required Fix: Use var_slots for Transitive Co-Reference Detection

The `var_slots` data structure already records ALL positions of a shared variable:

```python
plan.var_slots["relation_edge"].positions = [
    ("q1", "subject_uuid"),   # vitaltype quad (first occurrence)
    ("q2", "subject_uuid"),   # hasEdgeSource quad (src)
    ("q3", "subject_uuid"),   # hasEdgeDestination quad (dst)
]
```

Scanning var_slots finds q2+q3 as a src/dst pair **regardless of the constraint chain going through q1**.

Implementation steps:

1. **Detect pairs via var_slots** — for each variable in `plan.var_slots`, check if it has `subject_uuid` positions in both a `src_quad` and a `dst_quad`.

2. **Remove the two quad tables** (`q2`, `q3`) from `plan.tables`.

3. **Add one edge table** (`mv0` or `et0`) to `plan.tables`.

4. **Remap var_slots correctly** (the critical step):
   - Shared subject variable (`?relation_edge`): remove `(q2, subject_uuid)` and `(q3, subject_uuid)`, add `(et0, edge_uuid)`. Keep `(q1, subject_uuid)` for the vitaltype quad.
   - Source variable (`?source_entity`): `[(q2, object_uuid)]` → `[(et0, source_node_uuid)]`
   - Dest variable (`?destination_entity`): `[(q3, object_uuid)]` → `[(et0, dest_node_uuid)]`
   - Context variables: deduplicate to `[(et0, context_uuid)]`

5. **Remap constraints** that reference the removed quads:
   - `q2.subject_uuid = q1.subject_uuid` → `et0.edge_uuid = q1.subject_uuid`
   - `q3.subject_uuid = q1.subject_uuid` → remove (redundant, same edge_uuid)
   - `q2.predicate_uuid = __CONST_c_X__` → remove (predicate is baked into edge table)
   - `q3.predicate_uuid = __CONST_c_Y__` → remove

6. **Preserve the vitaltype constraint** — `q1.predicate_uuid = __CONST_vitaltype__` stays as-is, and the co-reference from q1 to et0 ensures the vitaltype pattern is still enforced.

### Why the Naive Fix Broke Queries

An initial attempt activated the rewrite after detecting pairs via var_slots, but the downstream rewrite logic was designed for the direct-constraint model. It did not handle the vitaltype quad's co-reference constraints or correctly update the var_slots positions for the shared variable, causing the emit phase to generate broken JOINs. All 8 relation queries returned 0 results.

---

## Problem 2: MV Staleness and Missing Statistics

### Staleness

- The MV is created once via `ensure_edge_mv()` and cached in `_edge_mv_exists`
- Entity CRUD operations (create/update/delete) modify the underlying `rdf_quad` table
- `REFRESH MATERIALIZED VIEW` is **never called** after data changes
- The MV may persist from a **previous test run** when space tables are dropped and recreated

### Missing Statistics

- `ANALYZE` is never run on the MV
- `ANALYZE` is never run on per-entity REST API insertions (only the bulk import path runs it)
- Without stats, PostgreSQL uses default row estimates → bad join orders → slow queries

### Statistics Must Be Updated Dynamically As Data Changes

The per-space tables (`{space}_rdf_quad`, `{space}_term`) and maintained tables (`{space}_edge`, `{space}_frame_entity`) are all affected. Relying solely on post-bulk-load `ANALYZE` is insufficient because:

- Entity graphs are created/updated/deleted interactively via the REST API throughout the application lifecycle
- Each entity graph mutation changes hundreds of rows in `rdf_quad` and several rows in the edge/frame-entity tables
- PostgreSQL’s autovacuum may not trigger fast enough in rapid create-then-query test or production flows

**Approach — incremental ANALYZE with row-change counter**:

| Trigger | Action | Scope |
|---------|--------|-------|
| **After bulk load** | `ANALYZE {space}_rdf_quad, {space}_term, {space}_edge, {space}_frame_entity` | All space tables |
| **After entity graph create/update/delete** | `ANALYZE` if Δrows > threshold (e.g. 1000) | Modified table(s) + edge/frame-entity |
| **After maintained table sync** | Include edge/frame-entity in the same `ANALYZE` call | Edge/frame tables |
| **Periodic (production)** | Tune `autovacuum_analyze_threshold` + `autovacuum_analyze_scale_factor` per table | All space tables |
| **On demand** | Admin endpoint / CLI `ANALYZE` command | User-triggered |

Implementation: track a per-space row-change counter (incremented by `add_rdf_quads_batch_bulk`, `remove_rdf_quads_batch_bulk`, `update_quads`). When it crosses the threshold, run `ANALYZE` on all affected tables and reset. This keeps stats fresh without running `ANALYZE` on every single-entity operation.

### Co-Occurrence Stats Tables Must Be Maintained Incrementally

The `{space}_rdf_stats` (predicate+object co-occurrence) and `{space}_rdf_pred_stats` (predicate cardinality) tables drive the join reorder heuristic in `_reorder_joins()`. Currently they are **never populated** during REST API operations — only the bulk import path has a stub.

**Previous approach (flawed)**: Ignore co-occurrences with count < 2 to keep the table small. But if you never count from 1, the count never reaches 2 — so no stats ever appear.

**Correct approach — always write, threshold on read**:

- **Write path**: On every entity graph create/update/delete, increment the co-occurrence count for every `(predicate_uuid, object_uuid)` pair and every `predicate_uuid` encountered in the affected quads. Use `INSERT ... ON CONFLICT DO UPDATE SET row_count = row_count + delta`. This ensures counts grow organically from 1 → 2 → N as data accumulates.

- **Read path**: When loading stats for query planning (`_load_quad_stats` in `generator.py`), apply a **minimum threshold** filter (e.g. `WHERE row_count >= 2`) so that rare/noise entries don't bloat the in-memory stats cache. The existing upper cap (`WHERE row_count <= 200000`) is already in place to exclude extremely common predicates that provide no selectivity signal.

```sql
-- Write: always increment (in add_rdf_quads_batch_bulk / remove_rdf_quads_batch_bulk)
INSERT INTO {space}_rdf_stats (predicate_uuid, object_uuid, row_count)
VALUES ($1, $2, $3)
ON CONFLICT (predicate_uuid, object_uuid)
DO UPDATE SET row_count = {space}_rdf_stats.row_count + EXCLUDED.row_count;

INSERT INTO {space}_rdf_pred_stats (predicate_uuid, row_count)
VALUES ($1, $2)
ON CONFLICT (predicate_uuid)
DO UPDATE SET row_count = {space}_rdf_pred_stats.row_count + EXCLUDED.row_count;

-- Read: only load above threshold (in _load_quad_stats)
SELECT predicate_uuid::text, object_uuid::text, row_count
FROM {space}_rdf_stats
WHERE row_count >= 2 AND row_count <= 200000;
```

**On DELETE**: decrement counts (but floor at 0). Periodic cleanup can remove rows where `row_count = 0`.

**Cache invalidation**: The `_stats_cache` in `generator.py` caches stats per space for the lifetime of the process. After significant data changes (same row-change counter threshold as ANALYZE), clear the cache entry so the next query reloads fresh stats.

**Integration points**: Same as the edge table sync — `add_rdf_quads_batch_bulk`, `remove_rdf_quads_batch_bulk`, `update_quads` in `sparql_sql_space_impl.py`.

### Impact on Query Performance

Relation queries R4 and R8 (returning only 2 results each) took 1.8s and 3.4s respectively — 10–50× slower than they should be. The combination of no MV rewrite (falling through to raw quad JOINs) and no statistics (bad join plans) explains the degradation.

---

## Pros and Cons: Maintained Table vs. Materialized View

| Factor | Materialized View | Maintained Table |
|--------|-------------------|------------------|
| **Data freshness** | Stale between explicit REFRESH calls | Always current (updated on every write) |
| **Write overhead** | Zero on individual writes; REFRESH is bulk | Small per-write overhead (1 INSERT/DELETE per edge mutation) |
| **Read performance** | Identical once refreshed | Identical (same schema, same indexes) |
| **Statistics** | Must run ANALYZE after REFRESH | Auto-maintained by autovacuum (normal table) |
| **Schema complexity** | DDL is one CREATE MATERIALIZED VIEW | DDL is CREATE TABLE + triggers or app-level sync |
| **Space cleanup** | MV may not be dropped with CASCADE properly | Normal table in space schema, drops naturally |
| **Concurrency** | REFRESH blocks concurrent reads (unless CONCURRENTLY, which requires unique index) | No blocking — normal row-level locking |
| **Dependency chain** | frame_entity_mv depends on edge_mv; REFRESH order matters | Independent tables, updated atomically |
| **Bulk load** | Fast if REFRESH is deferred to end | Must batch edge table updates (same as deferred indexes) |
| **Implementation effort** | Rewrite detection fix only | Table DDL + app-level sync + rewrite detection fix |

### Recommendation: Maintained Table

The maintained table approach is preferred because:

1. **Eliminates staleness entirely** — no REFRESH coordination needed
2. **Statistics stay current** — PostgreSQL autovacuum handles ANALYZE automatically
3. **No cascade dependency issues** — table drops cleanly with space
4. **Simpler concurrency** — no REFRESH locking
5. **The rewrite detection fix is needed regardless** — both approaches require the var_slots fix

---

## Reference SPARQL Queries (from Test Suite)

These queries are generated by `KGConnectionQueryBuilder` in the test suite and exercise the edge traversal patterns that the MV/table is designed to optimize.

### R1: All MakesProduct Relations (simple, no frame filter)

```sparql
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX vital: <http://vital.ai/ontology/vital-core#>

SELECT DISTINCT ?source_entity ?destination_entity ?relation_edge ?relation_type
WHERE {
    GRAPH <urn:sql_kgqueries> {
        ?source_entity vital:vitaltype ?source_vitaltype .
        ?relation_edge vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation> .
        ?relation_edge vital:hasEdgeSource ?source_entity .
        ?relation_edge vital:hasEdgeDestination ?destination_entity .
        ?relation_edge haley:hasKGRelationType ?relation_type .
        VALUES ?relation_type { <http://vital.ai/test/kgtype/MakesProductRelation> }
        ?destination_entity vital:vitaltype ?dest_vitaltype .
        FILTER(?source_entity != ?destination_entity)
    }
}
ORDER BY ?source_entity ?destination_entity
```

**Edge pairs**: 1 (relation_edge: hasEdgeSource + hasEdgeDestination)
**Expected MV benefit**: 2 quad JOINs → 1 table lookup

### R4: MakesProduct from Technology Companies (with source frame/slot filter)

```sparql
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX vital: <http://vital.ai/ontology/vital-core#>

SELECT DISTINCT ?source_entity ?destination_entity ?relation_edge ?relation_type
WHERE {
    GRAPH <urn:sql_kgqueries> {
        ?source_entity vital:vitaltype ?source_vitaltype .
        ?relation_edge vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation> .
        ?relation_edge vital:hasEdgeSource ?source_entity .
        ?relation_edge vital:hasEdgeDestination ?destination_entity .
        ?relation_edge haley:hasKGRelationType ?relation_type .
        VALUES ?relation_type { <http://vital.ai/test/kgtype/MakesProductRelation> }
        ?destination_entity vital:vitaltype ?dest_vitaltype .
        ?source_frame_edge_0 vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .
        ?source_frame_edge_0 vital:hasEdgeSource ?source_entity .
        ?source_frame_edge_0 vital:hasEdgeDestination ?source_frame_0 .
        ?source_frame_0 haley:hasKGFrameType <http://vital.ai/ontology/haley-ai-kg#CompanyInfoFrame> .
        ?source_slot_edge_0_0 vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .
        ?source_slot_edge_0_0 vital:hasEdgeSource ?source_frame_0 .
        ?source_slot_edge_0_0 vital:hasEdgeDestination ?source_slot_0_0 .
        ?source_slot_0_0 haley:hasKGSlotType <http://vital.ai/ontology/haley-ai-kg#IndustrySlot> .
        ?source_slot_0_0 haley:hasTextSlotValue ?source_slot_value_0_0 .
        FILTER(?source_slot_value_0_0 = 'Technology')
        FILTER(?source_entity != ?destination_entity)
    }
}
ORDER BY ?source_entity ?destination_entity
```

**Edge pairs**: 3
- `?relation_edge`: hasEdgeSource + hasEdgeDestination
- `?source_frame_edge_0`: hasEdgeSource + hasEdgeDestination
- `?source_slot_edge_0_0`: hasEdgeSource + hasEdgeDestination

**Expected MV benefit**: 6 quad JOINs → 3 table lookups (saves 3 JOINs)

### R8: MakesProduct from Large Tech Companies (combined industry + employee filter)

```sparql
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX vital: <http://vital.ai/ontology/vital-core#>

SELECT DISTINCT ?source_entity ?destination_entity ?relation_edge ?relation_type
WHERE {
    GRAPH <urn:sql_kgqueries> {
        ?source_entity vital:vitaltype ?source_vitaltype .
        ?relation_edge vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation> .
        ?relation_edge vital:hasEdgeSource ?source_entity .
        ?relation_edge vital:hasEdgeDestination ?destination_entity .
        ?relation_edge haley:hasKGRelationType ?relation_type .
        VALUES ?relation_type { <http://vital.ai/test/kgtype/MakesProductRelation> }
        ?destination_entity vital:vitaltype ?dest_vitaltype .
        ?source_frame_edge_0 vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .
        ?source_frame_edge_0 vital:hasEdgeSource ?source_entity .
        ?source_frame_edge_0 vital:hasEdgeDestination ?source_frame_0 .
        ?source_frame_0 haley:hasKGFrameType <http://vital.ai/ontology/haley-ai-kg#CompanyInfoFrame> .
        ?source_slot_edge_0_0 vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .
        ?source_slot_edge_0_0 vital:hasEdgeSource ?source_frame_0 .
        ?source_slot_edge_0_0 vital:hasEdgeDestination ?source_slot_0_0 .
        ?source_slot_0_0 haley:hasKGSlotType <http://vital.ai/ontology/haley-ai-kg#IndustrySlot> .
        ?source_slot_0_0 haley:hasTextSlotValue ?source_slot_value_0_0 .
        FILTER(?source_slot_value_0_0 = 'Technology')
        ?source_slot_edge_0_1 vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .
        ?source_slot_edge_0_1 vital:hasEdgeSource ?source_frame_0 .
        ?source_slot_edge_0_1 vital:hasEdgeDestination ?source_slot_0_1 .
        ?source_slot_0_1 haley:hasKGSlotType <http://vital.ai/ontology/haley-ai-kg#EmployeeCountSlot> .
        ?source_slot_0_1 haley:hasIntegerSlotValue ?source_slot_value_0_1 .
        FILTER(?source_slot_value_0_1 >= 500)
        FILTER(?source_entity != ?destination_entity)
    }
}
ORDER BY ?source_entity ?destination_entity
```

**Edge pairs**: 4
- `?relation_edge`: hasEdgeSource + hasEdgeDestination
- `?source_frame_edge_0`: hasEdgeSource + hasEdgeDestination
- `?source_slot_edge_0_0`: hasEdgeSource + hasEdgeDestination (industry slot)
- `?source_slot_edge_0_1`: hasEdgeSource + hasEdgeDestination (employee slot)

**Expected MV benefit**: 8 quad JOINs → 4 table lookups (saves 4 JOINs)

### Frame Query: Entities with CompanyInfoFrame (frame-based, not relation-based)

```sparql
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX vital: <http://vital.ai/ontology/vital-core#>

SELECT DISTINCT ?source_entity ?destination_entity ?shared_frame ?frame_type
WHERE {
    GRAPH <urn:sql_kgqueries> {
        ?source_entity vital:vitaltype ?source_vitaltype .
        ?source_frame_edge vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .
        ?source_frame_edge vital:hasEdgeSource ?source_entity .
        ?source_frame_edge vital:hasEdgeDestination ?shared_frame .
        ?dest_frame_edge vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .
        ?dest_frame_edge vital:hasEdgeSource ?destination_entity .
        ?dest_frame_edge vital:hasEdgeDestination ?shared_frame .
        ?shared_frame vital:vitaltype ?frame_type .
        ?destination_entity vital:vitaltype ?dest_vitaltype .
        FILTER(?source_entity != ?destination_entity)
    }
}
ORDER BY ?source_entity ?destination_entity
```

**Edge pairs**: 2
- `?source_frame_edge`: hasEdgeSource + hasEdgeDestination
- `?dest_frame_edge`: hasEdgeSource + hasEdgeDestination

---

## Implementation Plan

### Requirements

All auxiliary resources used during query generation must satisfy these requirements:

1. **Incrementally maintained** — Updated as part of every entity graph create, update, and delete operation so they are never stale.
2. **Full resync from scratch** — Utility functions can rebuild each auxiliary table by scanning `rdf_quad`, for disaster recovery, after manual DB edits, or initial population of a new space with existing data.
3. **Bulk-operation hooks** — A single function call after bulk load/import operations resyncs all auxiliary tables and runs `ANALYZE` to update PostgreSQL planner statistics.
4. **Stats cache invalidation** — The in-memory `_stats_cache` in `generator.py` is invalidated when data changes, so the next query reloads fresh stats from the database.

---

### Phase 1: Edge Table ✅ COMPLETE

#### Step 1.1: Create `{space}_edge` table DDL

Replace `CREATE MATERIALIZED VIEW` in `ensure_mv.py` with `CREATE TABLE`:

```sql
CREATE TABLE IF NOT EXISTS {space}_edge (
    edge_uuid        UUID NOT NULL,
    source_node_uuid UUID NOT NULL,
    dest_node_uuid   UUID NOT NULL,
    context_uuid     UUID NOT NULL,
    PRIMARY KEY (edge_uuid, context_uuid)
);

CREATE INDEX IF NOT EXISTS idx_{space}_edge_src_dst ON {space}_edge (source_node_uuid, dest_node_uuid);
CREATE INDEX IF NOT EXISTS idx_{space}_edge_dst_src ON {space}_edge (dest_node_uuid, source_node_uuid);
CREATE INDEX IF NOT EXISTS idx_{space}_edge_edge    ON {space}_edge (edge_uuid);
CREATE INDEX IF NOT EXISTS idx_{space}_edge_ctx     ON {space}_edge (context_uuid);
```

File: `ensure_mv.py` → rename to `ensure_edge_table.py` (or keep same file, change DDL).
Add to `sparql_sql_schema.py` → `create_space_tables_sql()` so new spaces get the table automatically.

#### Step 1.2: Incremental sync on entity graph write

On every entity graph create/update/delete, update the edge table as part of the same transaction.

**On INSERT** (after quads are inserted):
```sql
INSERT INTO {space}_edge (edge_uuid, source_node_uuid, dest_node_uuid, context_uuid)
SELECT
    src.subject_uuid,
    src.object_uuid,
    dst.object_uuid,
    src.context_uuid
FROM {space}_rdf_quad src
JOIN {space}_rdf_quad dst
    ON dst.subject_uuid = src.subject_uuid
    AND dst.context_uuid = src.context_uuid
WHERE src.predicate_uuid = $1   -- hasEdgeSource UUID
  AND dst.predicate_uuid = $2   -- hasEdgeDestination UUID
  AND src.subject_uuid = ANY($3) -- edge UUIDs from inserted quads
ON CONFLICT DO NOTHING
```

**On DELETE** (before quads are removed):
```sql
DELETE FROM {space}_edge
WHERE edge_uuid = ANY($1)  -- edge UUIDs being deleted
```

**On UPDATE** (entity graph update = delete old + insert new):
The existing update path already does delete-then-insert on quads, so edge sync piggybacks on both.

Integration points in `sparql_sql_space_impl.py`:
- `add_rdf_quads_batch_bulk()` — after quad insert, sync new edges
- `remove_rdf_quads_batch_bulk()` — before quad delete, remove edge rows
- `delete_entity_graph_bulk()` — include edge table in cleanup
- `update_quads()` — delete old edges, insert new edges

#### Step 1.3: Full resync utility

A function that rebuilds the edge table from scratch by scanning `rdf_quad`. Used for:
- Initial population of a space with existing data but no edge table
- Disaster recovery after manual DB edits
- Called by the bulk-operation hook (Step 3.3)

```python
async def resync_edge_table(space_id: str, conn) -> int:
    """Rebuild {space}_edge from rdf_quad. Returns rows inserted."""
```

```sql
TRUNCATE {space}_edge;

INSERT INTO {space}_edge (edge_uuid, source_node_uuid, dest_node_uuid, context_uuid)
SELECT src.subject_uuid, src.object_uuid, dst.object_uuid, src.context_uuid
FROM {space}_rdf_quad src
JOIN {space}_rdf_quad dst
    ON dst.subject_uuid = src.subject_uuid
    AND dst.context_uuid = src.context_uuid
WHERE src.predicate_uuid = (SELECT term_uuid FROM {space}_term WHERE term_text = 'http://vital.ai/ontology/vital-core#hasEdgeSource' AND term_type = 'U')
  AND dst.predicate_uuid = (SELECT term_uuid FROM {space}_term WHERE term_text = 'http://vital.ai/ontology/vital-core#hasEdgeDestination' AND term_type = 'U');

ANALYZE {space}_edge;
```

---

### Phase 2: Stats Tables ✅ COMPLETE

#### Step 2.1: Incremental stats sync on entity graph write

On every entity graph create/update/delete, update stats counters incrementally.

**On INSERT** (after quads are inserted, using the inserted quads' predicate/object UUIDs):
```sql
-- Predicate cardinality: increment for each predicate in the inserted quads
INSERT INTO {space}_rdf_pred_stats (predicate_uuid, row_count)
VALUES ($1, $2)
ON CONFLICT (predicate_uuid)
DO UPDATE SET row_count = {space}_rdf_pred_stats.row_count + EXCLUDED.row_count;

-- Predicate-object co-occurrence: increment for each (predicate, object) pair
INSERT INTO {space}_rdf_stats (predicate_uuid, object_uuid, row_count)
VALUES ($1, $2, $3)
ON CONFLICT (predicate_uuid, object_uuid)
DO UPDATE SET row_count = {space}_rdf_stats.row_count + EXCLUDED.row_count;
```

**On DELETE** (decrement, floor at 0):
```sql
UPDATE {space}_rdf_pred_stats
SET row_count = GREATEST(0, row_count - $2)
WHERE predicate_uuid = $1;

UPDATE {space}_rdf_stats
SET row_count = GREATEST(0, row_count - $3)
WHERE predicate_uuid = $1 AND object_uuid = $2;
```

Integration points: same as edge table (Step 1.2) — `add_rdf_quads_batch_bulk`, `remove_rdf_quads_batch_bulk`, `delete_entity_graph_bulk`, `update_quads`.

#### Step 2.2: Read-path threshold filter

Update `_load_quad_stats()` in `generator.py` to filter low-count noise:

```sql
-- Current (upper cap only):
SELECT predicate_uuid::text, object_uuid::text, row_count
FROM {space}_rdf_stats WHERE row_count <= 200000

-- Updated (lower threshold + upper cap):
SELECT predicate_uuid::text, object_uuid::text, row_count
FROM {space}_rdf_stats WHERE row_count >= 2 AND row_count <= 200000
```

This keeps the in-memory cache small by excluding rare/noise entries with count=1.

#### Step 2.3: Full resync utility

A function that rebuilds both stats tables from scratch. Replaces `StatsRebuildOp`:

```python
async def resync_stats_tables(space_id: str, conn) -> dict:
    """Rebuild rdf_pred_stats and rdf_stats from rdf_quad. Returns row counts."""
```

```sql
TRUNCATE {space}_rdf_pred_stats;
INSERT INTO {space}_rdf_pred_stats (predicate_uuid, row_count)
SELECT predicate_uuid, COUNT(*) FROM {space}_rdf_quad GROUP BY predicate_uuid;

TRUNCATE {space}_rdf_stats;
INSERT INTO {space}_rdf_stats (predicate_uuid, object_uuid, row_count)
SELECT predicate_uuid, object_uuid, COUNT(*) FROM {space}_rdf_quad
GROUP BY predicate_uuid, object_uuid HAVING COUNT(*) <= 200000;

ANALYZE {space}_rdf_pred_stats;
ANALYZE {space}_rdf_stats;
```

#### Step 2.4: Stats cache invalidation

Clear the in-memory `_stats_cache[space_id]` in `generator.py` after data changes so the next query reloads fresh stats. Two triggers:

1. **Per-space row-change counter**: Increment on every entity graph mutation. When it crosses a threshold (e.g. 1000 rows changed), clear the cache entry and reset.
2. **Explicit invalidation**: The resync utility and bulk-operation hook always clear the cache.

```python
# In generator.py
def invalidate_stats_cache(space_id: str) -> None:
    """Clear cached stats for a space so the next query reloads from DB."""
    _stats_cache.pop(space_id, None)
```

---

### Phase 3: Bulk-Operation Hooks and ANALYZE ✅ COMPLETE

#### Step 3.1: Per-space row-change counter

Track cumulative row changes per space. When the counter exceeds a threshold, run `ANALYZE` on all space tables and clear the stats cache.

```python
# Module-level counter
_row_change_counter: Dict[str, int] = {}
_ANALYZE_THRESHOLD = 1000  # configurable

async def _maybe_analyze(space_id: str, delta: int, conn) -> None:
    """Increment counter and run ANALYZE if threshold exceeded."""
    _row_change_counter[space_id] = _row_change_counter.get(space_id, 0) + delta
    if _row_change_counter[space_id] >= _ANALYZE_THRESHOLD:
        await _analyze_all_space_tables(space_id, conn)
        _row_change_counter[space_id] = 0
        invalidate_stats_cache(space_id)
```

Tables included in ANALYZE: `rdf_quad`, `term`, `edge`, `frame_entity`, `rdf_pred_stats`, `rdf_stats`.

#### Step 3.2: Post-bulk-load resync function

A single function that resyncs ALL auxiliary resources after a bulk load:

```python
async def resync_all_auxiliary_tables(space_id: str, conn) -> dict:
    """Full resync of all auxiliary tables + ANALYZE. Call after bulk loads."""
    edge_count = await resync_edge_table(space_id, conn)
    frame_count = await resync_frame_entity_table(space_id, conn)  # Phase 5
    stats = await resync_stats_tables(space_id, conn)
    await _analyze_all_space_tables(space_id, conn)
    invalidate_stats_cache(space_id)
    return {
        'edge_rows': edge_count,
        'frame_entity_rows': frame_count,
        'pred_stats_rows': stats['pred_stats'],
        'quad_stats_rows': stats['quad_stats'],
    }
```

Integration points:
- Called at the end of `SparqlSQLBackendAdapter.store_objects()` (bulk entity import)
- Called by the `StatsRebuildOp` admin operation (replaces current TRUNCATE+INSERT)
- Exposed as an admin CLI command (`vitalgraphadmin resync-auxiliary <space_id>`)
- Exposed as a REST API endpoint for programmatic use

#### Step 3.3: Space creation hook

When a new space is created via `sparql_sql_schema.py`, the edge and frame-entity tables are created as part of the DDL (empty). Stats tables are already created. No resync needed for empty spaces.

When a space is populated via bulk import, `resync_all_auxiliary_tables()` is called at the end.

---

### Phase 4: Rewrite Module Updates ✅ COMPLETE

#### Step 4.1: ~~var_slots co-reference detection~~ ✅ DONE

Enabled Method 2 in `rewrite_edge_table.py` and relaxed the `if not pairs` guard to `if remaining_src and remaining_dst` so mixed direct/indirect patterns work.

**Results (kgquery_perf_bench.py warm run):**

| Query | Quad Refs | MV Refs | Execute (before) | Execute (after) | Speedup |
|-------|-----------|---------|------------------|-----------------|---------|
| R1 (1 edge pair) | 8→4 | 0→1 | 31ms | 17ms | 1.8× |
| R4 (3 edge pairs) | 15→9 | 0→3 | 144ms | 123ms | 1.2× |
| R8 (4 edge pairs) | 20→12 | 0→4 | 396ms | 74ms | 5.4× |

#### Step 4.2: ~~Update `TableRef.kind` references~~ ✅ DONE

Changed `kind="edge_mv"` to `kind="edge"` in `rewrite_edge_table.py`, `emit_bgp.py`, `filter_pushdown.py`. Changed `kind="frame_entity_mv"` to `kind="frame_entity"` in `rewrite_frame_entity_table.py`, `emit_bgp.py`, `filter_pushdown.py`.

#### Step 4.3: ~~File renames and cleanup~~ ✅ DONE

- `ensure_mv.py` → split into `ensure_edge_table.py` + `ensure_frame_entity_table.py` (then deleted)
- `rewrite_edge_mv.py` → `rewrite_edge_table.py` (then deleted)
- `rewrite_frame_entity_mv.py` → `rewrite_frame_entity_table.py` (then deleted)
- `ensure_frame_entity_mv.py` → `ensure_frame_entity_table.py` (then deleted)
- All MV-specific code removed: REFRESH logic, `pg_matviews` checks, `WHERE FALSE` stub detection
- All `__pycache__` artifacts for deleted files cleaned up
- All old materialized views dropped from database (zero remaining)

---

### Phase 5: Frame-Entity Table ✅ COMPLETE

Replaced `{space}_frame_entity_mv` materialized view with `{space}_frame_entity` regular table:

1. ✅ Created `ensure_frame_entity_table.py` with `CREATE TABLE` DDL + populate-if-empty logic
2. ✅ Created `rewrite_frame_entity_table.py` with `kind="frame_entity"` TableRef
3. ✅ Added `frame_entity` table to `sparql_sql_schema.py` (create + indexes + drop)
4. ✅ Added `frame_entity` table to `dawg_space_manager.py` (create + drop)
5. ✅ Updated `generator.py` imports
6. ✅ Updated `emit_bgp.py` and `filter_pushdown.py` kind checks
7. ✅ Verified: kgquery_perf_bench passes (R1=6, R4=2, R8=2)

---

### Phase 6: Cleanup + Integration (partially complete)

1. ✅ Remove MV-specific code paths (REFRESH, `pg_matviews` checks, `_edge_mv_exists` / `_frame_entity_mv_exists` caches)
2. ✅ Add edge + frame-entity table creation to `sparql_sql_schema.py` → `create_space_tables_sql()`
3. ✅ Add edge + frame-entity table drop to `drop_space_tables_sql()`
4. Pending: Replace `StatsRebuildOp` with call to `resync_all_auxiliary_tables()`
5. Pending: Run KGQueries full regression test suite
6. ✅ Update planning documents

---

## Execution Order

| # | Step | Priority | Status | Depends On |
|---|------|----------|--------|------------|
| 1 | EXPLAIN ANALYZE baseline (R1, R4, R8) | P0 | ✅ Done | — |
| 2 | var_slots co-reference detection in `rewrite_edge_table.py` | P0 | ✅ Done | — |
| 3 | Stub MV detection (no longer needed — tables replace MVs) | P0 | ✅ Done | — |
| 4 | EXPLAIN ANALYZE after fix (verify speedup) | P0 | ✅ Done | Steps 2-3 |
| 5 | Edge table DDL (`CREATE TABLE` replaces MV) + file renames | P1 | ✅ Done | — |
| 5b | Frame-entity table DDL (`CREATE TABLE` replaces MV) + file renames | P1 | ✅ Done | Step 5 |
| 14 | Rewrite module updates (`TableRef.kind`, file cleanup, schema DDL) | P1 | ✅ Done | Step 5 |
| 6 | Edge table incremental sync (`sync_edge_table.py`) | P1 | ✅ Done | Step 5 |
| 6b | Frame-entity incremental sync (`sync_frame_entity_table.py`) | P1 | ✅ Done | Step 6 |
| 7 | Edge + frame-entity full resync utilities | P1 | ✅ Done | Step 5 |
| 8 | Stats incremental sync (`sync_stats_tables.py`) | P1 | ✅ Done | — |
| 9 | Stats read-path threshold filter (`row_count >= 2`) | P1 | ✅ Done | — |
| 10 | Stats full resync utility (`resync_stats_tables()`) | P1 | ✅ Done | — |
| 11 | Stats cache invalidation (`invalidate_stats_cache()`) | P1 | ✅ Done | Steps 8-10 |
| 12 | Per-space row-change counter + auto-ANALYZE (`auto_analyze.py`) | P1 | ✅ Done | Steps 6, 8 |
| 13 | `resync_all_auxiliary_tables()` bulk hook (`resync_all.py`) | P1 | ✅ Done | Steps 7, 10 |
| 15 | KGQueries full regression test | P1 | ✅ Done | Steps 5-13 |
| 16 | ~~Frame-entity table migration~~ | P2 | ✅ Done (Step 5b) | — |
| 17 | ~~Cleanup + integrate into space schema DDL~~ | P2 | ✅ Done (Step 14) | — |
| 18 | Admin CLI / REST endpoint + client for resync | P2 | ✅ Done | Step 13 |

---

## Verified Test Results

### ✅ Lead Dataset Test (100 entities, 192,810 triples) — 21/21 passed

All KGQuery frame-based queries return correct non-zero results:

| Query | Results | Time (before) | Time (after) |
|---|---|---|---|
| Find MQL leads | 99 | 242ms | 180ms |
| Hierarchical frame query | 100 | 692ms | 930ms |
| Find leads in California | 13 | 170ms | 91ms |
| Find leads in Los Angeles | 3 | 100ms | 70ms |
| Find high-rated leads | 73 | 102ms | 108ms |
| Find leads with business accounts | 53 | 2,347ms | 95ms |
| Find converted leads | 9 | 107ms | 93ms |
| Find abandoned leads | 100 | 145ms | 146ms |
| Multi-criteria (MQL+CA+rating) | 10 | 1,503ms | 3,403ms |
| Range query (50≤MQL≤80) | 88 | 147ms | 220ms |
| Pagination (5+5) | 10 | 211ms | 430ms |
| Empty results (expected 0) | 0 | 51ms | 55ms |

**"Before"** = with synchronous INFO-level SQL pretty-print logging (event loop blocking).
**"After"** = with fire-and-forget DEBUG-level logging (non-blocking).

The business accounts query dropped from **2,347ms → 95ms** — the previous time was dominated
by synchronous pretty-printing of ~40k SQL on the event loop. The multi-criteria query rose
to 3.4s wall time; server-side EXPLAIN ANALYZE shows **655ms planning vs 38ms execution**,
confirming the PostgreSQL planning bottleneck documented in the UNION Branch Pruning section below.

**Note**: The `frame_entity` table is empty (0 rows) for this dataset because the lead data
does not use `urn:hasSourceEntity`/`urn:hasDestinationEntity` URIs. Queries work correctly
through the edge table rewrite + standard quad JOINs. The frame_entity optimization only
applies to datasets that use the WordNet-style slot pattern.

---

## Future Optimizations

### UNION Branch Pruning via Early Probing

**Problem**: KGQuery SPARQL generation produces UNION branches for multiple entity subtypes
(e.g. `KGEntity`, `KGNewsEntity`, `KGProductEntity`, `KGWebEntity`). In most spaces only
`KGEntity` exists, so 3 of 4 branches match 0 rows. However, PostgreSQL still plans all
branches, and for complex queries (71.8k SQL, 16 variables, 6 edge rewrites) the **planning
time dominates execution** — e.g. 655ms planning vs. 38ms execution on the lead dataset
multi-criteria query.

**Proposed fix**: Before generating the full SQL, probe the space's `rdf_quad` or `term` table
to check which entity type URIs actually exist. Prune UNION branches for types with 0 matching
rows. For the lead dataset this would eliminate 3 of 4 branches, reducing SQL size by ~40% and
significantly reducing PG planning time.

**Scope**: This optimization applies at the SPARQL generation layer (in `kg_query_builder.py`
or as a post-processing step in the v2 generator) and does not require schema changes. The
probe query is a cheap index lookup on the term table.

**Priority**: P2 — the current performance (~3.4s wall time for the most complex multi-criteria
query, of which ~655ms is PG planning) could be improved to sub-500ms with branch pruning.

---

## Step 18: Admin CLI / REST Endpoint + Client for Resync

Delivered four components:

1. **CLI REPL**: `rebuild resync [space_id]` subcommand in `vitalgraphdb_admin_cmd.py`
2. **CLI non-interactive**: `vitalgraphadmin -c rebuild-resync -s <space_id>`
3. **REST endpoint**: `POST /api/admin/resync?space_id=...` in `vitalgraph/endpoint/admin_endpoint.py`
4. **Client method**: `client.admin.resync(space_id)` via `vitalgraph/client/endpoint/admin_endpoint.py`

Test (`vitalgraph_client_test/test_admin_resync.py`) on `sp_sql_lead_dataset`:
- edge: 19,225 rows
- frame_entity: 0 rows
- pred_stats: 21 rows
- quad_stats: 72,498 rows
- Server elapsed: 514ms

---

## Open Questions

1. **Edge table for non-KG edges**: The current MV captures ALL edges (any quad with hasEdgeSource + hasEdgeDestination), not just KG relation edges. Should the maintained table be scoped to specific edge types, or remain general-purpose? **Recommendation**: remain general-purpose — the rewrite logic already filters by query shape.

2. **Index strategy**: The edge table is small relative to rdf_quad (one row per edge vs. 2+ quads per edge). Should we add a covering index `(source_node_uuid, dest_node_uuid, edge_uuid, context_uuid)` to enable index-only scans?

3. **Stats cleanup on DELETE**: When `row_count` drops to 0 after deletions, should rows be removed from `rdf_stats` immediately or cleaned up periodically? Immediate removal keeps the table smaller but adds complexity.

4. **ANALYZE threshold tuning**: Default 1000 rows is a starting point. May need tuning based on production workloads — too low adds overhead, too high allows planner drift.
