# Geo Query Architecture — Dual Subject Support

> **Status: ✅ IMPLEMENTED** (Jul 2026)
>
> All items in this plan have been implemented and verified.
> Integration tests: 13/13 passing in `tests/api/test_geo_search_integration.py`.

## 1. Problem Statement

The `vg:geoDistance(?subject, lat, lon)` and `vg:withinRadius(?subject, lat, lon, meters)` SPARQL functions operate on any `subject_uuid` in the `{space}_geo` table. However, the original implementation had an inconsistency:

- **`geo_populator.py` (datatype-driven path)**: Stored the **slot UUID** — whatever subject owns the geo-typed literal (correct for slot-level queries).
- **`geo_slot_handler.py`**: Resolved slot→frame→entity and stored the **entity UUID** (correct for entity-level queries).

These two paths produced different `subject_uuid` values for the same geo point, making it impossible to reliably query either way.

Additionally, `_build_vector_geo_clauses()` in `kg_query_builder.py` hardcoded `anchor_var="entity"`, meaning geo functions always bound to `?entity` — they could not bind to a slot variable from frame/slot criteria.

---

## 2. Two Valid Use Cases

### 2.1 Slot-Level Geo (specific slot → distance)

The geo point is associated with a specific `KGGeoLocationSlot`. A KGQuery specifies frame/slot criteria to identify the slot, and `vg:geoDistance` binds to the **slot** subject.

**Use case**: "Find entities whose GeoLocationSlot is within 10km of Bristol."

**SPARQL** (generated from KGQuery):
```sparql
?frame_edge_0 vital-core:vitaltype haley:Edge_hasEntityKGFrame .
?frame_edge_0 vital-core:hasEdgeSource ?entity .
?frame_edge_0 vital-core:hasEdgeDestination ?frame_0 .
?slot_edge_0_0 vital-core:vitaltype haley:Edge_hasKGSlot .
?slot_edge_0_0 vital-core:hasEdgeSource ?frame_0 .
?slot_edge_0_0 vital-core:hasEdgeDestination ?slot_0_0 .
?slot_0_0 haley:hasKGSlotType <http://vital.ai/ontology/haley-ai-kg#KGGeoLocationSlot> .
BIND(vg:geoDistance(?slot_0_0, 51.45, -2.59) AS ?vg_distance)
FILTER(vg:withinRadius(?slot_0_0, 51.45, -2.59, 10000))
```

**Geo table row**: `subject_uuid = slot_uuid`

### 2.2 Entity-Level Geo (N distances per entity, any slot)

An entity may have multiple geo slots (e.g. "headquarters", "branch office") — each produces a separate row in the geo table keyed on its slot UUID. The query still traverses entity→frame→slot, but doesn't constrain frame type.

**Use case**: "Find entities that have ANY geo slot within 50km."

**SPARQL** (generated from KGQuery):
```sparql
?entity vital-core:vitaltype haley:KGEntity .
?frame_edge_0 vital-core:vitaltype haley:Edge_hasEntityKGFrame .
?frame_edge_0 vital-core:hasEdgeSource ?entity .
?frame_edge_0 vital-core:hasEdgeDestination ?frame_0 .
?slot_edge_0_0 vital-core:vitaltype haley:Edge_hasKGSlot .
?slot_edge_0_0 vital-core:hasEdgeSource ?frame_0 .
?slot_edge_0_0 vital-core:hasEdgeDestination ?slot_0_0 .
?slot_0_0 haley:hasKGSlotType <http://vital.ai/ontology/haley-ai-kg#KGGeoLocationSlot> .
BIND(vg:geoDistance(?slot_0_0, 51.45, -2.59) AS ?vg_distance)
FILTER(vg:withinRadius(?slot_0_0, 51.45, -2.59, 50000))
```

**Geo table row**: `subject_uuid = slot_uuid` (same as slot-level)

The difference from §2.1 is only in what additional frame/slot constraints are applied — the geo function always binds to the slot.

---

## 3. Geo Table Schema (Implemented)

The geo table is a generic `subject_uuid → location` lookup. `vg:geoDistance(?x, lat, lon)` resolves `?x` to its UUID and looks it up — it doesn't care whether it's an entity, slot, or anything else.

### 3.1 Dual-Entry Population

When an entity has N geo slots, the geo table gets **2N entries**:

| Row | `subject_uuid` | `source_slot_uuid` | Purpose |
|-----|---------------|-------------------|--------|
| Slot row (×N) | slot UUID | slot UUID | `vg:geoDistance(?slot, ...)` in slot-level queries |
| Entity row (×N) | entity UUID | slot UUID | `vg:geoDistance(?entity, ...)` in entity-level queries |

Each slot produces one slot-keyed row and one entity-keyed row (with that slot's location).

### 3.2 Schema (Implemented — Option A)

We chose **Option A** with `source_slot_uuid` discriminator and `geo_id SERIAL PRIMARY KEY`:

```sql
CREATE TABLE IF NOT EXISTS {space_id}_geo (
    geo_id            SERIAL PRIMARY KEY,
    subject_uuid      UUID NOT NULL,
    source_slot_uuid  UUID,
    predicate_uuid    UUID,
    location          geography(Point, 4326) NOT NULL,
    latitude          DOUBLE PRECISION NOT NULL,
    longitude         DOUBLE PRECISION NOT NULL,
    context_uuid      UUID NOT NULL,
    updated_time      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (subject_uuid, source_slot_uuid, context_uuid)
);
CREATE INDEX idx_{space_id}_geo_gist ON {space_id}_geo USING gist (location);
CREATE INDEX idx_{space_id}_geo_subj ON {space_id}_geo (subject_uuid);
CREATE INDEX idx_{space_id}_geo_slot ON {space_id}_geo (source_slot_uuid);
CREATE INDEX idx_{space_id}_geo_ctx ON {space_id}_geo (context_uuid);
```

File: `vitalgraph/db/sparql_sql/sparql_sql_schema.py`

### 3.3 Entity-Level Multi-Slot Behavior

When `vg:geoDistance(?entity, lat, lon)` matches an entity with N geo slots, it returns N rows (one per slot location). The SQL uses `MIN` to pick the closest:

```sql
SELECT subject_uuid, MIN(ST_Distance(location, ST_MakePoint(lon, lat)::geography)) AS distance_m
FROM {space_id}_geo
WHERE subject_uuid = {entity_uuid_col}
  AND ST_DWithin(location, ST_MakePoint(lon, lat)::geography, radius_m)
GROUP BY subject_uuid
```

This gives a single distance per entity — the nearest of its N geo slots.

---

## 4. Implementation Changes (All Complete)

### 4.1 `geo_slot_handler.py` ✅

Now stores **both** the slot UUID row and the entity UUID row. Uses `GEO_UPSERT_SQL` with `source_slot_uuid` parameter. Delete uses `GEO_DELETE_BY_SLOT_SQL` to remove both rows by `source_slot_uuid`.

### 4.2 `geo_populator.py` ✅

Datatype-driven path also stores dual entries. Added `_resolve_entity_for_slot()` helper (lazy import to avoid circular dependency with `geo_slot_handler`). SQL templates updated:
- `GEO_UPSERT_SQL`: Now includes `source_slot_uuid` ($2) with `ON CONFLICT (subject_uuid, source_slot_uuid, context_uuid)`
- `GEO_DELETE_BY_SLOT_SQL`: Deletes by `source_slot_uuid` (removes both slot-keyed and entity-keyed rows)

### 4.3 `vg_functions.py` — `geo_distance_sql()` ✅

Changed from `LIMIT 1` (arbitrary row) to `MIN` (closest distance) for multi-slot scenarios:
```python
f"(SELECT MIN(ST_Distance(location, ST_MakePoint({lon}, {lat})::geography)) "
f"FROM {geo_table} WHERE subject_uuid = {uuid_col}{ctx_clause})"
```

`within_radius_sql()` uses `EXISTS` which naturally handles multi-slot (passes if ANY row is within radius). No change needed.

### 4.4 `kg_query_builder.py` — `_build_vector_geo_clauses()` ✅

Now respects `geo_criteria.geo_target`:
- `geo_target="slot"` → `anchor_var = "slot_0_0"` (first frame, first slot variable)
- `geo_target="entity"` or `None` → `anchor_var = "entity"` (backward-compatible)

### 4.5 `GeoSearchCriteria` Model ✅

Added `geo_target` field to `vitalgraph/model/kgentities_model.py`:
```python
geo_target: Optional[str] = Field(
    None,
    description="Which SPARQL variable the geo function binds to. "
               "'slot' = bind to the geo slot variable from frame_criteria; "
               "'entity' = bind to ?entity (default, backward-compatible)."
)
```

### 4.6 `kgquery_endpoint.py` ✅

Passes `geo_target` from the Pydantic model to the builder's `GeoCriteria` dataclass.

---

## 5. KGQuery JSON Examples

### 5.1 Slot-Level Geo Query

```json
{
  "query_type": "entity",
  "frame_criteria": [{
    "slot_criteria": [{
      "slot_type": "http://vital.ai/ontology/haley-ai-kg#KGGeoLocationSlot",
      "comparator": "exists"
    }]
  }],
  "geo_criteria": {
    "latitude": 51.45,
    "longitude": -2.59,
    "radius_m": 200000,
    "sort_by_distance": true,
    "top_k": 20,
    "geo_target": "slot"
  }
}
```

### 5.2 Entity-Level Geo Query

```json
{
  "query_type": "entity",
  "geo_criteria": {
    "latitude": 51.45,
    "longitude": -2.59,
    "radius_m": 200000,
    "sort_by_distance": true,
    "top_k": 20,
    "geo_target": "entity"
  }
}
```

### 5.3 Auto-Detect (default)

```json
{
  "query_type": "entity",
  "frame_criteria": [{
    "slot_criteria": [{
      "slot_type": "http://vital.ai/ontology/haley-ai-kg#KGGeoLocationSlot",
      "comparator": "exists"
    }]
  }],
  "geo_criteria": {
    "latitude": 51.45,
    "longitude": -2.59,
    "radius_m": 200000,
    "sort_by_distance": true,
    "top_k": 20
  }
}
```

Auto-detect sees `KGGeoLocationSlot` in frame_criteria → binds geo to slot variable.

---

## 6. Migration

### 6.1 Schema Migration Required

New spaces automatically get the new schema (via `sparql_sql_schema.py`). Existing spaces with geo data need:

1. `ALTER TABLE` to add `geo_id SERIAL PRIMARY KEY`, `source_slot_uuid UUID`
2. Drop old PK constraint `(subject_uuid, context_uuid)`
3. Add `UNIQUE (subject_uuid, source_slot_uuid, context_uuid)`
4. Add index on `source_slot_uuid`

### 6.2 Re-population (Recommended)

Simpler than migrating data: truncate the geo table and let auto_sync re-populate with dual entries on next entity write. The geo table is a derived side-table so this is safe.

```sql
TRUNCATE {space_id}_geo;
-- Then trigger auto_sync by touching any entity with a geo slot
```

---

## 7. Test Updates

### 7.1 `test_geo_search_integration.py`

Update to:
1. Create KGEntities with proper frame/slot structure (already done)
2. Use KGQuery with `frame_criteria` + `slot_criteria` for `KGGeoLocationSlot`
3. Apply `geo_criteria` with `geo_target="slot"` (or let auto-detect work)
4. Verify entities returned by distance ordering
5. Add separate test case for entity-level geo (no frame_criteria)

### 7.2 New Test: Multi-Slot Geo

Test entity with multiple geo slots (e.g. "headquarters" + "warehouse"):
- Verify each slot produces a separate geo point
- Verify entity-level query finds entity if ANY slot is within radius
- Verify slot-level query can distinguish between slots

---

## 8. Implementation Order (Completed)

1. ✅ **Schema**: `sparql_sql_schema.py` — new geo table with `geo_id SERIAL PK`, `source_slot_uuid`, unique constraint
2. ✅ **geo_slot_handler.py**: Dual-entry writes (slot-keyed + entity-keyed rows)
3. ✅ **geo_populator.py**: Dual-entry with `_resolve_entity_for_slot()`, updated SQL templates
4. ✅ **vg_functions.py**: `geo_distance_sql` uses `MIN` instead of `LIMIT 1`
5. ✅ **GeoSearchCriteria model**: Added `geo_target` field
6. ✅ **kg_query_builder.py**: `geo_target="slot"` → binds to `?slot_0_0`
7. ✅ **kgquery_endpoint.py**: Passes `geo_target` through
8. ✅ **Tests**: 13 tests covering population, entity-level geo, slot-level geo, dual-entry, and backward compat

---

## 9. Resolved Questions

1. **Multiple geo slots per entity**: Resolved via `MIN(ST_Distance(...))` in `geo_distance_sql`. The scalar subquery returns the closest slot's distance. `DISTINCT ?entity` is already in the SELECT.

2. **`geo_target` field**: Kept as `Optional[str]` defaulting to `None` (= entity behavior). Explicit `"slot"` required to bind to slot variable. Auto-detect was NOT implemented (too implicit).

3. **`geo_points.list_points()` API**: Currently returns all geo rows (both slot-keyed and entity-keyed). This is acceptable for a diagnostic endpoint. The `source_slot_uuid` column could be exposed in a future enhancement.

---

## 10. Resolved Issues

### 10.1 DELETE Handling ✅

Resolved using `GEO_DELETE_BY_SLOT_SQL`: `DELETE FROM geo WHERE source_slot_uuid = $1 AND context_uuid = $2`. This removes BOTH rows (slot-keyed and entity-keyed) for a given slot in a single statement.

### 10.2 `vg:geoDistance` Multi-Slot Consistency ✅

Fixed: `LIMIT 1` → `MIN(ST_Distance(...))` in `geo_distance_sql()`. Returns closest distance when entity has multiple geo slots.

### 10.3 Test Coverage ✅

Tests now exercise both paths:
- **Entity-level**: `geo_target="entity"` (or None) — binds to `?entity`, looks up entity-keyed rows
- **Slot-level**: `geo_target="slot"` + `frame_criteria` with `slot_type=KGGeoLocationSlot` — binds to `?slot_0_0`, looks up slot-keyed rows
- **Dual-entry verification**: Confirms `list_points()` returns 2× the number of entities (both row types)

### 10.4 Test Fixture: `hasKGSlotType` Property

Discovered during testing: the `KGGeoLocationSlot` domain object doesn't automatically set `hasKGSlotType` as an RDF property. The test fixture must explicitly set it:
```python
slot['http://vital.ai/ontology/haley-ai-kg#hasKGSlotType'] = \
    'http://vital.ai/ontology/haley-ai-kg#KGGeoLocationSlot'
```
Without this, the SPARQL pattern `?slot_0_0 haley:hasKGSlotType <KGGeoLocationSlot>` finds no matches.

---

## 11. Enhancements

### 11.1 Geo + Vector Combined Queries

KGQuery already supports both `geo_criteria` and `vector_criteria` in the same request. These should compose correctly: "find semantically similar entities within 50km." Needs a test covering this combination.

### 11.2 Slot-Type Discrimination

Beyond generic `KGGeoLocationSlot`, subtype slot types (e.g. `HeadquartersGeoSlot`, `WarehouseGeoSlot`) can be used in `frame_criteria.slot_criteria.slot_type` to answer specific queries like "find entities whose *headquarters* is within 10km" vs any geo slot.

### 11.3 Geo-Enriched Entity Listing

The `list_kgentities` endpoint could accept an optional reference point (lat, lon) and return a distance annotation per entity, sorted by proximity — without requiring a full KGQuery. Useful for map-based UIs.

### 11.4 Bounding Box in GeoSearchCriteria

`vg:withinBounds` already exists in `vg_functions.py`. Expose `bounds` (minLat, minLon, maxLat, maxLon) as an alternative to `radius_m` in `GeoSearchCriteria` for map-viewport queries.

### 11.5 Vector/Geo Anchor Parity

Vector search also hardcodes `anchor_var="entity"` in `_build_vector_geo_clauses`. If a use case needs slot-level vector similarity (e.g. embedding on a text slot's value), the same anchor pattern applies. Worth generalizing both geo and vector anchor resolution together.

### 11.6 `geo_slot_handler` Entity Resolution

After the dual-entry fix, `resolve_entity_uuid_for_slot()` is still needed (to produce the entity-keyed row). It uses the `frame_entity` table for fast lookup, falling back to edge traversal. No removal — it just now produces two inserts instead of one.
