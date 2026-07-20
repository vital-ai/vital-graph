# KG Query Sorting Plan

## Status: Implementation Complete — Testing

**Date**: 2026-04-25

---

## Problem Statement

The KG query endpoint (`POST /api/graphs/kgqueries`) currently hardcodes `ORDER BY ?entity` (or `ORDER BY ?frame`) for all paginated queries. There is no way for a caller to sort results by a slot value — for example, sorting leads by MQLRating descending or by CompanyName alphabetically.

### What already exists

The SPARQL builder layer has **partial sorting infrastructure** that is not wired through to the endpoint:

| Layer | What exists | What's missing |
|-------|------------|----------------|
| **Builder dataclass** | `SortCriteria` on `EntityQueryCriteria` and `FrameQueryCriteria` (`kg_query_builder.py:42-49, 68, 80`) | — |
| **Builder methods** | `build_entity_query_sparql_with_sorting()` (line 1111), `build_frame_query_sparql_with_sorting()` (line 1257) | Only handles `entity_frame_slot` sort_type; hardcodes `hasDoubleSlotValue` (line 1221) — does not support text/boolean/integer/datetime slot sorting |
| **Pydantic model** | `SortCriteria` in `kgentities_model.py:72-79`, `sort_criteria` on `EntityQueryCriteria:88` | `KGQueryCriteria` in `kgqueries_model.py` has **no** `sort_criteria` field |
| **Server endpoint** | — | `kgquery_endpoint.py` does not read or pass `sort_criteria`; always calls `build_entity_query_sparql` (non-sorting version) |
| **Client endpoint** | — | `kgqueries_endpoint.py` does not accept or send `sort_criteria` |
| **Tests** | — | No test cases exercise sorting |

### Builder limitations

The existing `build_entity_query_sparql_with_sorting()` has several issues:

1. **Hardcodes `hasDoubleSlotValue`** — only works for `KGDoubleSlot`. Must dispatch to the correct value property based on `slot_class_uri` (text → `hasTextSlotValue`, boolean → `hasBooleanSlotValue`, etc.)
2. **Does not use `_build_entity_where_clause()`** — duplicates the WHERE clause construction logic instead of reusing the standard builder, so frame criteria and hierarchical frames are not supported
3. **Variable naming is fragile** — tries to reuse slot filter variables for sorting, but the naming scheme (`val_slot_{frame_type_key}_{i}`) diverges from the standard builder's `slot_{i}_{j}` pattern
4. **No OPTIONAL** — if sorting by a slot that not every entity has, entities without that slot are excluded from results (this is actually the desired behavior — see Decisions)

---

## Design

### Sorting applies to all three query cases

| Query type | Sort target | ORDER BY |
|------------|------------|----------|
| `entity` (Case 2) | Slot value on entity's frame | `ORDER BY ASC/DESC(?sort_val_0)` |
| `entity` (Case 2) | **Direct property on entity node** | `ORDER BY ASC/DESC(?sort_val_0)` |
| `frame_query` (Case 1) | Slot value on the frame | `ORDER BY ASC/DESC(?sort_val_0)` |
| `relation` (Case 3) | Slot value on **source or destination** entity's frame | `ORDER BY ASC/DESC(?sort_val_0)` |

### Sort criteria model

Reuse the existing `SortCriteria` from `kgentities_model.py`:

```python
class SortCriteria(BaseModel):
    sort_type: str          # "entity_frame_slot" for Case 2, "frame_slot" for Case 1,
                            # "source_frame_slot" or "destination_frame_slot" for Case 3,
                            # "entity_property" for direct property on entity node
    frame_path: List[str]   # Ordered list of frame type URIs from entity to the slot's parent frame
                            # (unused for entity_property)
    slot_type: str          # Slot type URI (e.g. "urn:acme:kg:slot:ZipCode")
                            # (unused for entity_property)
    slot_class_uri: str     # Slot class (KGTextSlot, KGDoubleSlot, etc.) — determines value property
                            # (unused for entity_property)
    property_uri: Optional[str] = None  # Direct property URI — only used when sort_type="entity_property"
    sort_order: str = "asc"            # "asc" | "desc"
    priority: int = 1                  # Multi-level: 1=primary, 2=secondary
```

**Key additions**:
- `slot_class_uri` — needed so the builder can pick the correct value property
- `property_uri` — needed for `entity_property` sort type; the full property URI to sort by
- `frame_path` — ordered frame type chain that disambiguates the slot's position in the hierarchy. The same slot type can appear under different frame paths:

```python
# Person's zip code
SortCriteria(
    sort_type="entity_frame_slot",
    frame_path=["urn:frame:PersonFrame", "urn:frame:AddressFrame"],
    slot_type="urn:slot:ZipCode",
    slot_class_uri="KGTextSlot",
    sort_order="asc"
)

# Business zip code (different path, same slot type)
SortCriteria(
    sort_type="entity_frame_slot",
    frame_path=["urn:frame:BusinessAddressFrame"],
    slot_type="urn:slot:ZipCode",
    slot_class_uri="KGTextSlot",
    sort_order="asc"
)
```

The builder walks `frame_path` to generate the chain of edge patterns:
```
Entity → frame_path[0] → frame_path[1] → ... → Slot
```

### SPARQL pattern for sort binding

For an entity query sorted by a slot value:

```sparql
SELECT DISTINCT ?entity ?sort_val_0 WHERE {
    GRAPH <urn:graph> {
        # ... standard entity + frame + slot WHERE clause ...

        # Sort binding (required — acts as implicit existence filter)
        ?sort_frame_edge_0 vital-core:vitaltype <Edge_hasEntityKGFrame> .
        ?sort_frame_edge_0 vital-core:hasEdgeSource ?entity .
        ?sort_frame_edge_0 vital-core:hasEdgeDestination ?sort_frame_0 .
        ?sort_frame_0 haley:hasKGFrameType <urn:acme:kg:frame:LeadStatusFrame> .
        ?sort_slot_edge_0 vital-core:vitaltype <Edge_hasKGSlot> .
        ?sort_slot_edge_0 vital-core:hasEdgeSource ?sort_frame_0 .
        ?sort_slot_edge_0 vital-core:hasEdgeDestination ?sort_slot_0 .
        ?sort_slot_0 haley:hasKGSlotType <urn:acme:kg:slot:MQLRating> .
        ?sort_slot_0 haley:hasDoubleSlotValue ?sort_val_0 .
    }
}
ORDER BY DESC(?sort_val_0)
LIMIT 100 OFFSET 0
```

When the sort slot is **already used in a filter**, the sort variable references the existing slot binding — no extra join needed.

### Slot class → value property mapping

| `slot_class_uri` | SPARQL property |
|------------------|-----------------|
| `KGTextSlot` | `haley:hasTextSlotValue` |
| `KGBooleanSlot` | `haley:hasBooleanSlotValue` |
| `KGDoubleSlot` | `haley:hasDoubleSlotValue` |
| `KGIntegerSlot` | `haley:hasIntegerSlotValue` |
| `KGDateTimeSlot` | `haley:hasDateTimeSlotValue` |
| `KGEntitySlot` | `haley:hasEntitySlotValue` |
| `KGURISlot` | `haley:hasUriSlotValue` |

This mapping already exists in `_get_slot_value_property()` in `kg_query_builder.py`.

### SPARQL pattern for `entity_property` sort

No frame/slot traversal — a single triple on the entity node:

```sparql
SELECT DISTINCT ?entity ?sort_val_0 WHERE {
    GRAPH <urn:graph> {
        # ... standard entity WHERE clause ...

        # Direct property sort (no frame/slot joins)
        ?entity <http://vital.ai/ontology/vital-core#hasName> ?sort_val_0 .
    }
}
ORDER BY ASC(?sort_val_0)
LIMIT 25 OFFSET 0
```

Example usage from the client:

```python
from vitalgraph.model.kgentities_model import SortCriteria

# Sort entities by name
result = client.kgqueries.query_entities(
    space_id=space_id, graph_id=graph_id,
    criteria=EntityQueryCriteria(...),
    sort_criteria=[SortCriteria(
        sort_type="entity_property",
        property_uri="http://vital.ai/ontology/vital-core#hasName",
        slot_type="unused",        # ignored for entity_property
        slot_class_uri="unused",   # ignored for entity_property
        sort_order="asc"
    )]
)

# Sort entities by last modified (newest first)
result = client.kgqueries.query_entities(
    space_id=space_id, graph_id=graph_id,
    criteria=EntityQueryCriteria(...),
    sort_criteria=[SortCriteria(
        sort_type="entity_property",
        property_uri="http://vital.ai/ontology/vital#hasObjectModificationDateTime",
        slot_type="unused",
        slot_class_uri="unused",
        sort_order="desc"
    )]
)
```

### Sortable direct properties (entity_property)

| Property URI | Type | Short name | Description |
|-------------|------|------------|-------------|
| `vital-core:hasName` | `xsd:string` | `name` | Entity display name |
| `vital:hasObjectModificationDateTime` | `xsd:dateTime` | `modified` | Last modification time |
| `vital-aimp:hasObjectCreationTime` | `xsd:dateTime` | `created` | Object creation time |
| `haley-ai-kg:hasKGEntityType` | `xsd:anyURI` | `entity_type` | Entity type URI |
| `vital-aimp:hasObjectStatusType` | `xsd:anyURI` | `status` | Object status URI (e.g. active, inactive) |

#### Defined status URI values

The `hasObjectStatusType` property uses full namespace URIs under `http://vital.ai/ontology/vital-aimp#`:

| Short name | Full URI |
|-----------|----------|
| `ObjectStatusType_ACTIVE` | `http://vital.ai/ontology/vital-aimp#ObjectStatusType_ACTIVE` |
| `ObjectStatusType_DELETED` | `http://vital.ai/ontology/vital-aimp#ObjectStatusType_DELETED` |
| `ObjectStatusType_INACTIVE` | `http://vital.ai/ontology/vital-aimp#ObjectStatusType_INACTIVE` |
| `ObjectStatusType_INVALID` | `http://vital.ai/ontology/vital-aimp#ObjectStatusType_INVALID` |
| `ObjectStatusType_PENDING` | `http://vital.ai/ontology/vital-aimp#ObjectStatusType_PENDING` |

Additional status values can be added using the same namespace pattern. The filter
accepts any URI value — validation is not restricted to this set.

---

## Implementation Plan

### Phase 1: Wire sort_criteria through the stack

| Step | File | Change |
|------|------|--------|
| 1a | `kgqueries_model.py` | Add `sort_criteria: Optional[List[SortCriteria]]` to `KGQueryCriteria` |
| 1b | `kgentities_model.py` | Add `slot_class_uri: Optional[str]` and `property_uri: Optional[str]` to `SortCriteria` if not already present |
| 1c | `kgquery_endpoint.py` | In `_execute_entity_query`: read `criteria.sort_criteria`, convert to builder `SortCriteria`, pass to builder |
| 1d | `kgquery_endpoint.py` | In `_execute_frame_query_case`: same for frame queries |
| 1e | `kgquery_endpoint.py` | In `_execute_relation_query`: pass `sort_criteria` to connection query builder |
| 1f | `kgqueries_endpoint.py` (client) | Add `sort_criteria` parameter to `query_entities()`, `query_frames()`, and `query_relation_connections()` |

### Phase 2: Fix the SPARQL builder

| Step | File | Change |
|------|------|--------|
| 2a | `kg_query_builder.py` | Refactor `build_entity_query_sparql_with_sorting()` to reuse `_build_entity_where_clause()` instead of duplicating logic |
| 2b | `kg_query_builder.py` | Use `_get_slot_value_property()` to pick the correct value predicate based on `slot_class_uri` instead of hardcoding `hasDoubleSlotValue` |
| 2c | `kg_query_builder.py` | Add sort bindings as required triples (not OPTIONAL) — acts as implicit existence filter |
| 2d | `kg_query_builder.py` | Support hierarchical frame paths for sort (e.g. sort by a slot on a child frame: `Entity → ParentFrame → ChildFrame → Slot`) |
| 2e | `kg_query_builder.py` | Merge sorting directly into `build_entity_query_sparql()` and `build_frame_query_sparql()` rather than maintaining separate methods |
| 2f | `kg_connection_query_builder.py` | Add sort binding support for relation queries — `source_frame_slot` anchors sort to `?source`, `destination_frame_slot` anchors to `?destination` |
| 2g | `kg_query_builder.py` | Handle `sort_type="entity_property"` in `_build_sort_bindings`: emit a single `?entity <property_uri> ?sort_val_N .` triple instead of the frame→slot chain. Skip frame_path/slot_type/slot_class_uri. |

### Phase 3: Tests

| Test | Dataset | Description |
|------|---------|-------------|
| Sort entities by double slot (ASC) | Lead | Sort leads by MQLRating ascending |
| Sort entities by double slot (DESC) | Lead | Sort leads by MQLRating descending — verify highest-rated first |
| Sort entities by text slot | Lead | Sort leads by CompanyStateCode alphabetically |
| Sort entities by boolean slot | Lead | Sort leads by IsConverted (false first, true last, or vice versa) |
| Multi-level sort | Lead | Primary: CompanyStateCode ASC, secondary: MQLRating DESC |
| Sort + filter combined | Lead | Filter to CA leads, then sort by MQLRating DESC |
| Sort on hierarchical frame slot | Lead | Sort by slot on a child frame (e.g. Entity → LeadStatusFrame → LeadStatusQualificationFrame → MQLRating) |
| Pagination with sort | Lead | Verify page 1 and page 2 are correctly ordered with consistent total_count |
| Frame query sort | WordNet | Sort frame_query results by a slot value |
| Relation sort by source slot | Multi-org | Sort MakesProduct relations by source org's EmployeeCount DESC |
| Relation sort by dest slot | Multi-org | Sort MakesProduct relations by destination product's Category alphabetically |
| **Sort by entity name** | **Lead** | **`sort_type="entity_property"`, `property_uri=hasName` — verify alphabetical order** |
| **Sort by modification date** | **Lead** | **`sort_type="entity_property"`, `property_uri=hasObjectModificationDateTime`, desc — newest first** |
| **Sort by creation time** | **Lead** | **`sort_type="entity_property"`, `property_uri=hasObjectCreationTime`, asc — oldest first** |
| **entity_property + frame filter** | **Lead** | **Sort by hasName while filtering by a frame criterion — both coexist** |

**Test file**: `vitalgraph_client_test/entity_graph_lead_dataset/case_kgquery_sort_queries.py`

### Phase 4: Cleanup

- Delete `build_entity_query_sparql_with_sorting()` and `build_frame_query_sparql_with_sorting()` — sorting will be merged into the main builder methods
- Update `kg_query_unification_plan.md` test coverage matrix with sorting rows

---

## Decisions

1. **Merge into main builder** — Sorting is added directly to `build_entity_query_sparql()` and `build_frame_query_sparql()`. No separate `_with_sorting` methods. The old `_with_sorting` methods are deleted in Phase 4.

2. **Reuse filter slot variable for sorting** — When the sort slot matches a slot already bound by a filter criterion, reuse that variable instead of adding a redundant join.

3. **Sort binding is required, not OPTIONAL** — If you sort by a slot (e.g. last name), the intent is that results have that slot. The sort binding acts as an implicit existence filter — entities missing the sort slot are excluded. No NULLS LAST handling needed.

4. **Nested child frame sorting included** — Sorting by a slot on a child frame (Entity → ParentFrame → ChildFrame → Slot) is supported in Phase 2d. The lead dataset exercises this pattern.

5. **`entity_property` sort type** — A new `sort_type="entity_property"` sorts by a direct property on the entity node (e.g. `hasName`, `hasObjectModificationDateTime`).  No frame/slot traversal.  ✅ Implemented in `_build_sort_bindings` — emits `?entity <property_uri> ?sort_val_N .`

6. **`slot_type` / `slot_class_uri` are optional, validated by sort_type** — Made optional on both the Pydantic model and builder dataclass.  A `model_validator` enforces: slot-based sort types require `slot_type` + `slot_class_uri`; `entity_property` requires `property_uri`.  ✅ Implemented.

7. **`property_uri` validated against allowed set** — The server validates `property_uri` against `_ENTITY_SORT_PROPERTIES` (5 properties: `hasName`, `hasObjectModificationDateTime`, `hasObjectCreationTime`, `hasKGEntityType`, `hasObjectStatusType`).  Rejects unknown property URIs with a clear error.  ✅ Implemented (needs update to swap `hasTimestamp` → `hasObjectStatusType`).

8. **Mixed sort types in same criteria list** — A caller can combine `entity_property` and slot-based sort types in the same `sort_criteria` list (e.g. primary: sort by `hasName`, secondary: sort by MQLRating slot).  `_build_sort_bindings` handles each `sort_type` independently per iteration.  ✅ Implemented.

---

## Bug Fix: Count query missing sort joins

**Discovered**: 2026-04-26

The count query (`build_entity_count_query_sparql`) did not include the sort
join patterns that the paginated query includes.  When sorting by a slot that
not every entity has, the paginated query excludes entities without the slot
(correct), but the count query still counted them — producing a `total_count`
larger than the actual result set.

**Fix**: `build_entity_count_query_sparql` now calls `_build_sort_bindings`
and appends the sort patterns to the WHERE clause, matching the paginated
query.  ✅ Implemented.

---

## Phase 5: List Entities Endpoint — Direct Property Sorting

### Motivation

The `GET /api/graphs/kgentities` (list entities) endpoint currently orders
results by URI (`ORDER BY ?s`).  For a table view in the frontend, users need
to sort by display-relevant properties on the entity node itself — no
frame/slot traversal required.

### Sortable entity properties

These properties are inherited by every KGEntity through the class hierarchy
`KGEntity → KGNode → VITAL_Node` and are the natural choices for a table
view:

| Property URI | Type | Short name | Description |
|-------------|------|------------|-------------|
| `vital-core:hasName` | `xsd:string` | `name` | Entity display name (alphabetical) |
| `vital:hasObjectModificationDateTime` | `xsd:dateTime` | `modified` | Last modification time |
| `vital-aimp:hasObjectCreationTime` | `xsd:dateTime` | `created` | Object creation time |
| `haley-ai-kg:hasKGEntityType` | `xsd:anyURI` | `entity_type` | Entity type URI (group by type) |
| `vital-aimp:hasObjectStatusType` | `xsd:anyURI` | `status` | Object status URI (e.g. active, inactive) |

### API change

Add `sort_by` and `sort_order` query parameters to the list endpoint:

```
GET /api/graphs/kgentities?space_id=...&graph_id=...
    &sort_by=name          # one of: name, modified, created, entity_type, status
    &sort_order=asc        # asc | desc (default asc)
    &page_size=25&offset=0
```

Default when `sort_by` is omitted: current behavior (`ORDER BY ?s` — URI
order).

### SPARQL pattern

No frame/slot joins.  A single triple pattern on the entity:

```sparql
SELECT DISTINCT ?entity ?sort_val WHERE {
  GRAPH <urn:graph> {
    ?entity vital-core:vitaltype haley:KGEntity .
    ?entity <property_uri> ?sort_val .
  }
}
ORDER BY ASC(?sort_val) ?entity
LIMIT 25 OFFSET 0
```

The property URI is resolved from the `sort_by` short name via a fixed
mapping in the endpoint.

### Implementation steps

| Step | File | Change |
|------|------|--------|
| 5a | `kgentities_endpoint.py` | Add `sort_by: Optional[str]` and `sort_order: Optional[str]` query params to the list route |
| 5b | `kgentity_list_impl.py` | Accept `sort_by` / `sort_order`, resolve to property URI, inject `ORDER BY` into SPARQL queries (`_build_optimized_properties_query`, `_build_entity_uris_query`, `_build_count_query`) |
| 5c | `kgentity_list_impl.py` | Count query must include the sort property join (same fix as the KG query count bug above) |
| 5d | `kgentities_endpoint.py` (client) | Add `sort_by` / `sort_order` to client `list_kgentities()` |
| 5e | Tests | Add sort test cases to `case_kgquery_sort_queries.py` or a new test file |

### Property URI mapping (server-side constant)

```python
_LIST_SORT_PROPERTIES = {
    "name":        "http://vital.ai/ontology/vital-core#hasName",
    "modified":    "http://vital.ai/ontology/vital#hasObjectModificationDateTime",
    "created":     "http://vital.ai/ontology/vital-aimp#hasObjectCreationTime",
    "entity_type": "http://vital.ai/ontology/haley-ai-kg#hasKGEntityType",
    "status":      "http://vital.ai/ontology/vital-aimp#hasObjectStatusType",
}
```

### Implementation status — ✅ Complete (2026-04-26)

| Step | Status | Notes |
|------|--------|-------|
| 5a | ✅ | `sort_by` / `sort_order` query params added to route + validation against `_ENTITY_SORT_PROPERTIES` |
| 5b | ✅ | `_build_optimized_properties_query`, `_build_entity_uris_query` inject sort triple + `ORDER BY ASC/DESC(?sort_val)` |
| 5c | ✅ | `_build_count_query` includes sort join so `total_count` matches paginated results |
| 5d | ✅ | Client `list_kgentities()` + mock endpoint accept `sort_by` / `sort_order` |
| 5e | ✅ | `case_list_entities_sort.py` — 5 tests: ASC, DESC, pagination consistency, baseline, invalid property rejection |

**API**: `sort_by` accepts the full property URI (not a short name).  Validated against the
same `_ENTITY_SORT_PROPERTIES` set used by `SortCriteria.entity_property`.  Invalid URIs
return HTTP 400.

### Bug fixes discovered during integration testing (2026-04-26)

1. **Subquery projection missing `?sort_val`** — `_build_optimized_properties_query`
   inner subquery was `SELECT DISTINCT ?s WHERE { ... }` but `ORDER BY ASC(?sort_val)`
   referenced a variable not in the projection.  Fuseki silently returned 0 rows.
   **Fix**: inner SELECT becomes `SELECT DISTINCT ?s ?sort_val WHERE { ... }` when
   `sort_by` is set.  Same fix applied to `_build_entity_uris_query`.

2. **Outer ORDER BY overriding inner sort** — The outer query had a hardcoded
   `ORDER BY ?s ?p` which re-sorted results by URI, destroying the sort order
   from the inner subquery.  **Fix**: outer ORDER BY becomes
   `ORDER BY {direction}(?sort_val) ?s ?p` when sorting is active.

3. **Test data: IsConverted boolean sort** — `frame_path` was missing the child
   frame `LeadStatusConversionFrame`.  The slot lives at
   `LeadStatusFrame → LeadStatusConversionFrame → IsConverted`, not directly
   under `LeadStatusFrame`.

### Final test results — ✅ 41/41 passed

```
✅ PASS: List and Query Entities — 4/4
✅ PASS: Retrieve Entity Graphs and Frames — 3/3
✅ PASS: KGQuery Lead Frame Queries — 12/12
✅ PASS: KGQuery Sort Queries — 17/17
✅ PASS: List Entities Sorting — 5/5
OVERALL: 41/41 tests passed
```

### Notes

- Sort is **required join** (not OPTIONAL) — entities missing the sort
  property are excluded.  For `name` this is fine since every entity has
  `hasName`.  For `modified` / `created`, entities created before those
  properties were populated may be excluded — consider OPTIONAL + NULLS LAST
  if this becomes an issue.
- This is orthogonal to the KG query `sort_criteria` (frame→slot sorting).
  Both can coexist.

---

## Dependencies

- Runaway pagination guard (`_MAX_QUERY_OFFSET` + count-first short-circuit) — ✅ already implemented
- `exists` comparator fix (removed cross-product `?slot ?pred ?val` pattern) — ✅ already implemented
- Count query sort join fix — ✅ implemented 2026-04-26

---

## Phase 6: Direct Entity Property Filtering

### Motivation

Sorting (Phases 1–5) controls the **order** of results but does not restrict **which**
entities are returned.  Users also need to **filter** by the same direct properties:

- "Show only entities created after 2026-01-01"
- "Show only active entities" (status URI = `urn:status:active`)
- "Exclude archived entities" (status URI ≠ `urn:status:archived`)
- "Show active entities created after 2026-01-01, sorted by name"

Frame/slot filtering already exists for the KG graph structure.  This phase adds
filtering on **direct properties of the entity node** — the same properties that
Phases 1–5 made sortable.

### Scope

Property filtering applies to **both** endpoints:

1. **KG query endpoint** (`POST /api/graphs/kgqueries`) — uses the full
   `EntityPropertyFilter` model alongside existing frame/slot criteria and
   sort criteria (Phase 6a–6j)
2. **List entities endpoint** (`GET /api/graphs/kgentities`) — uses convenience
   query parameters for the most common filters (Phase 6b)

### Current `search` / `search_string` implementation

Text search already exists but is implemented differently across endpoints.
This section documents the current state so we can decide on alignment.

#### List entities endpoint (`GET /api/graphs/kgentities`)

**Parameter**: `search` (query string)
**File**: `kgentity_list_impl.py`
**Properties searched**: `vital-core:hasName` only
**Method**: Case-insensitive substring (`CONTAINS(LCASE(...))`)
**Used in**: `_build_optimized_properties_query`, `_build_entity_uris_query`,
`_build_count_query` (all three include the search clause consistently)

```sparql
# _build_optimized_properties_query / _build_entity_uris_query / _build_count_query
?s <http://vital.ai/ontology/vital-core#hasName> ?name .
FILTER(CONTAINS(LCASE(?name), LCASE("search_term")))
```

#### KG query endpoint — entity queries (`POST /api/graphs/kgqueries`)

**Parameter**: `search_string` on `EntityQueryCriteria`
**File**: `kg_query_builder.py` → `_build_entity_where_clause()`
**Properties searched**: `rdfs:label` + `vital-core:hasName` (UNION)
**Method**: Case-insensitive substring (`CONTAINS(LCASE(...))`)

```sparql
{ ?entity rdfs:label ?label .
  FILTER(CONTAINS(LCASE(?label), LCASE("search_term")))
} UNION {
  ?entity vital-core:hasName ?name .
  FILTER(CONTAINS(LCASE(?name), LCASE("search_term")))
}
```

#### KG query endpoint — frame queries

**Parameter**: `search_string` on `FrameQueryCriteria`
**File**: `kg_query_builder.py` → `build_frame_query_sparql()`
**Properties searched**: `rdfs:label` + `vital-core:name` (UNION)
**Method**: Case-insensitive substring

```sparql
{ ?frame rdfs:label ?label .
  FILTER(CONTAINS(LCASE(?label), LCASE("search_term")))
} UNION {
  ?frame vital-core:name ?name .
  FILTER(CONTAINS(LCASE(?name), LCASE("search_term")))
}
```

**⚠️ Bug**: Uses `vital-core:name` — this property does not exist. Should be
`vital-core:hasName`. This means the second branch of the UNION never matches
anything; frame search effectively only works on `rdfs:label`.

#### Divergences to resolve

| Aspect | List endpoint | KG query (entity) | KG query (frame) |
|--------|--------------|-------------------|-------------------|
| Properties | `hasName` | `rdfs:label` + `hasName` | `rdfs:label` + `name` (bug) |
| `rdfs:label` | ❌ not searched | ✅ searched | ✅ searched |
| `hasName` | ✅ searched | ✅ searched | ❌ bug (`name` instead of `hasName`) |
| Required join | yes (entities without `hasName` excluded) | yes (via UNION — at least one must match) | yes |

**Alignment decisions**:

1. ~~Should the list endpoint also search `rdfs:label`?~~ **No** — keep as-is
   (`hasName` only).
2. ~~Should KG entity queries drop `rdfs:label`?~~ **Yes** — remove the
   `rdfs:label` UNION branch from both entity and frame search.  `rdfs:label`
   is not populated by the GraphObject write path today.  It will be re-added
   in the future multi-language enhancement phase when `rdfs:label` storage is
   implemented.
3. ~~Should the frame query bug (`vital-core:name`) be fixed?~~ **Yes** — moot
   once the `rdfs:label` branch is removed; the remaining branch should use
   `vital-core:hasName` (fixing the bug in the process).
4. ~~Is the required-join semantic correct?~~ **Yes** — entities without
   `hasName` are excluded from search results.  This is acceptable.

**Search alignment implementation** (part of Phase 6):

| Step | File | Change |
|------|------|--------|
| 6n | `kg_query_builder.py` | `_build_entity_where_clause()` — remove `rdfs:label` UNION, search only `vital-core:hasName` |
| 6o | `kg_query_builder.py` | `build_frame_query_sparql()` — remove `rdfs:label` UNION, fix `vital-core:name` → `vital-core:hasName` |

### Future enhancement: multi-language search via `rdfs:label`

RDF supports language-tagged literals on `rdfs:label` (e.g. `"Chat"@fr`,
`"Cat"@en`).  SPARQL provides `LANG()` and `LANGMATCHES()` to filter by
language tag.  This would enable searching for entities by name in a specific
language.

**Current gap**: The GraphObject mapping does not currently store `rdfs:label`
values.  To support multi-language search we would need to:

1. Define a place to store `rdfs:label` values (with language tags) on
   GraphObjects — either as a dedicated multilingual field or a map of
   language → label.
2. Ensure the triplestore write path emits `rdfs:label` triples with
   appropriate language tags.
3. Add an optional `lang` parameter to search that adds
   `FILTER(LANG(?label) = "en")` to the `rdfs:label` search branch.
4. Decide whether `hasName` remains the canonical untagged name while
   `rdfs:label` carries the multilingual variants.

This is **out of scope for Phase 6** but informs the alignment decision:
keeping the `rdfs:label` search branch in the KG query builder is forward-
compatible with future multi-language support, even though `rdfs:label` is
not yet populated by the GraphObject write path.

### Relationship with new `EntityPropertyFilter`

The new `EntityPropertyFilter` on `hasName` provides **exact match** (`eq`)
and **substring** (`contains`) as explicit filter operations — useful when
callers need precise control rather than the built-in fuzzy search.  The
existing `search`/`search_string` and the new property filters are independent
and can coexist in the same query.

### Filterable properties and datatype handling

Each property's datatype determines the SPARQL value syntax and which operators
are valid:

| Property URI | Datatype | SPARQL value syntax | Valid operators |
|-------------|----------|--------------------|-----------------|
| `vital-core:hasName` | `string` | `"value"` | `eq`, `ne`, `contains` |
| `vital:hasObjectModificationDateTime` | `dateTime` | `"value"^^xsd:dateTime` | `eq`, `ne`, `gt`, `lt`, `gte`, `lte` |
| `vital-aimp:hasObjectCreationTime` | `dateTime` | `"value"^^xsd:dateTime` | `eq`, `ne`, `gt`, `lt`, `gte`, `lte` |
| `haley-ai-kg:hasKGEntityType` | `uri` | `<value>` | `eq`, `ne`, `in`, `not_in` |
| `vital-aimp:hasObjectStatusType` | `uri` | `<value>` | `eq`, `ne`, `in`, `not_in` |

### Model: `EntityPropertyFilter`

New Pydantic model — separate from the existing `QueryFilter` which uses short
`property_name` strings.  This model uses full property URIs and is
datatype-aware.

```python
class EntityPropertyFilter(BaseModel):
    """Filter on a direct property of the entity node."""
    property_uri: str = Field(..., description="Full property URI")
    operator: str = Field(..., description="Filter operator: eq, ne, gt, lt, gte, lte, contains, in, not_in")
    value: Optional[Union[str, List[str]]] = Field(
        None,
        description="Single value for eq/ne/gt/lt/gte/lte/contains, or list of values for in/not_in"
    )
```

Validation:
- `property_uri` must be in `_FILTERABLE_ENTITY_PROPERTIES`
- `operator` must be valid for the property's datatype
- `value` must be a list when operator is `in` / `not_in`

### Property registry

```python
_FILTERABLE_ENTITY_PROPERTIES = {
    "http://vital.ai/ontology/vital-core#hasName":                        "string",
    "http://vital.ai/ontology/vital#hasObjectModificationDateTime":       "dateTime",
    "http://vital.ai/ontology/vital-aimp#hasObjectCreationTime":          "dateTime",
    "http://vital.ai/ontology/haley-ai-kg#hasKGEntityType":               "uri",
    "http://vital.ai/ontology/vital-aimp#hasObjectStatusType":            "uri",
}
```

This registry is also used by sorting validation — `_ENTITY_SORT_PROPERTIES`
becomes `set(_FILTERABLE_ENTITY_PROPERTIES.keys())`, keeping one source of truth.

### SPARQL patterns by datatype

**String `eq`:**
```sparql
?entity <http://vital.ai/ontology/vital-core#hasName> "John Smith" .
```

**String `contains`:**
```sparql
?entity <http://vital.ai/ontology/vital-core#hasName> ?epf_val_0 .
FILTER(CONTAINS(LCASE(STR(?epf_val_0)), LCASE("smith")))
```

**DateTime `gt` (created after):**
```sparql
?entity <http://vital.ai/ontology/vital-aimp#hasObjectCreationTime> ?epf_val_0 .
FILTER(?epf_val_0 > "2026-01-01T00:00:00"^^xsd:dateTime)
```

**URI `eq` (status = active):**
```sparql
?entity <http://vital.ai/ontology/vital-aimp#hasObjectStatusType> <http://vital.ai/ontology/vital-aimp#ObjectStatusType_ACTIVE> .
```

**URI `ne` (status ≠ inactive):**
```sparql
?entity <http://vital.ai/ontology/vital-aimp#hasObjectStatusType> ?epf_val_0 .
FILTER(?epf_val_0 != <http://vital.ai/ontology/vital-aimp#ObjectStatusType_INACTIVE>)
```

**URI `in` (status in [active, pending]):**
```sparql
?entity <http://vital.ai/ontology/vital-aimp#hasObjectStatusType> ?epf_val_0 .
FILTER(?epf_val_0 IN (<http://vital.ai/ontology/vital-aimp#ObjectStatusType_ACTIVE>, <http://vital.ai/ontology/vital-aimp#ObjectStatusType_PENDING>))
```

**URI `not_in` (exclude deleted and invalid):**
```sparql
?entity <http://vital.ai/ontology/vital-aimp#hasObjectStatusType> ?epf_val_0 .
FILTER(?epf_val_0 NOT IN (<http://vital.ai/ontology/vital-aimp#ObjectStatusType_DELETED>, <http://vital.ai/ontology/vital-aimp#ObjectStatusType_INVALID>))
```

### Example client usage

```python
from vitalgraph.model.kgentities_model import EntityPropertyFilter

# Active entities created after 2026-01-01, sorted by name
result = client.kgqueries.query_entities(
    space_id=space_id, graph_id=graph_id,
    criteria=EntityQueryCriteria(
        entity_property_filters=[
            EntityPropertyFilter(
                property_uri="http://vital.ai/ontology/vital-aimp#hasObjectStatusType",
                operator="eq",
                value="http://vital.ai/ontology/vital-aimp#ObjectStatusType_ACTIVE"
            ),
            EntityPropertyFilter(
                property_uri="http://vital.ai/ontology/vital-aimp#hasObjectCreationTime",
                operator="gt",
                value="2026-01-01T00:00:00"
            ),
        ],
        sort_criteria=[SortCriteria(
            sort_type="entity_property",
            property_uri="http://vital.ai/ontology/vital-core#hasName",
            sort_order="asc"
        )]
    )
)
```

### Implementation steps

| Step | File | Change | Status |
|------|------|--------|--------|
| 6a | `kgentities_model.py` | Add `EntityPropertyFilter` model with `model_validator` for datatype-aware validation | ✅ Done |
| 6b | `kgentities_model.py` | Add `_FILTERABLE_ENTITY_PROPERTIES` registry; derive `_ENTITY_SORT_PROPERTIES` from it | ✅ Done |
| 6c | `kgentities_model.py` | Add `entity_property_filters: Optional[List[EntityPropertyFilter]]` to `EntityQueryCriteria` | ✅ Done |
| 6d | `kgqueries_model.py` | Add `entity_property_filters` to `KGQueryCriteria` (or inherit via `source_entity_criteria`) | ✅ Done |
| 6e | `kg_query_builder.py` | Add `EntityPropertyFilter` dataclass mirror; add `entity_property_filters` to builder `EntityQueryCriteria` | ✅ Done |
| 6f | `kg_query_builder.py` | Add `_build_entity_property_filters()` to `_build_entity_where_clause()` — emits SPARQL per datatype | ✅ Done |
| 6g | `kg_query_builder.py` | Count query (`build_entity_count_query_sparql`) must include property filter patterns | ✅ Done |
| 6h | `kgquery_endpoint.py` | Convert Pydantic `EntityPropertyFilter` → builder dataclass in `_execute_entity_query` | ✅ Done |
| 6i | `kgentities_endpoint.py` (server) | Wire `entity_property_filters` through `_convert_to_sparql_criteria()` | ✅ Done |
| 6j | `kgentities_endpoint.py` (client) | Add `entity_property_filters` parameter to `query_entities()` | ✅ Done |

### Phase 6b: List endpoint property filtering

Phase 6a–6j above wire `EntityPropertyFilter` into the **KG query** POST
endpoint.  This section adds the same filtering to the **list entities** GET
endpoint via convenience query parameters:

| Parameter | Type | Description |
|-----------|------|-------------|
| `status` | `str` | Exact-match status URI — only entities with this status |
| `exclude_status` | `str` | Exclude entities with this status URI |
| `created_after` | `str` (ISO 8601) | Entities created after this datetime |
| `created_before` | `str` (ISO 8601) | Entities created before this datetime |
| `modified_after` | `str` (ISO 8601) | Entities modified after this datetime |
| `modified_before` | `str` (ISO 8601) | Entities modified before this datetime |

```
GET /api/graphs/kgentities?space_id=...&graph_id=...
    &status=http://vital.ai/ontology/vital-aimp#ObjectStatusType_ACTIVE
    &created_after=2026-01-01T00:00:00
    &sort_by=http://vital.ai/ontology/vital-core#hasName
    &sort_order=asc
```

| Step | File | Change | Status |
|------|------|--------|--------|
| 6k | `kgentities_endpoint.py` | Add `status`, `exclude_status`, `created_after`, `created_before`, `modified_after`, `modified_before` query params | ✅ Done |
| 6l | `kgentity_list_impl.py` | Inject filter triples + FILTERs into `_build_optimized_properties_query`, `_build_entity_uris_query`, `_build_count_query` | ✅ Done |
| 6m | `kgentities_endpoint.py` (client) | Add filter parameters to client `list_kgentities()` | ✅ Done |

**Implementation notes (Phase 6b):**
- `_build_property_filter_clauses()` static method added to `KGEntityListProcessor` — converts convenience params to SPARQL triple patterns + FILTER clauses
- `prop_filters` string passed through `_list_entities_fast`, `_list_entities_with_graph`, and all three query builders
- `PREFIX xsd:` added to all query builders for dateTime comparisons
- Status filters use exact URI match (`?entity <statusURI> <value>`) or negation (`FILTER(?var != <value>)`)
- Date filters use `xsd:dateTime` typed comparisons

### Phase 6 tests

| Test | Description |
|------|-------------|
| Filter by status (eq) | Only entities with `ObjectStatusType_ACTIVE` |
| Filter by status (ne) | Exclude entities with `ObjectStatusType_INACTIVE` |
| Filter by status (in) | Entities with status in `[ACTIVE, PENDING]` |
| Filter by status (not_in) | Exclude `[DELETED, INVALID]` |
| Filter by created_after | Entities created after a date |
| Filter by created_before | Entities created before a date |
| Filter by date range | `created_after` + `created_before` combined |
| Filter + sort combined | Filter active + sort by name |
| Filter + frame criteria combined | Property filter + frame/slot filter coexist |
| List endpoint status filter | `?status=...ObjectStatusType_ACTIVE` query param |
| List endpoint exclude_status | `?exclude_status=...ObjectStatusType_INACTIVE` |
| List endpoint created_after | `?created_after=2026-01-01T00:00:00` |
| List endpoint combined | `?status=...&created_after=...&sort_by=name` |
| Invalid property URI rejected | Unknown property_uri returns 400 |
| Invalid operator for datatype | `gt` on a URI property returns 400 |

**Test file**: `vitalgraph_client_test/entity_graph_lead_dataset/case_kgquery_property_filters.py`

**Test status (2026-04-30):** 9/9 passing. Tests cover:
- Property filter: name contains, status eq, status ne, combined property+frame
- count_only with property filter
- List endpoint: status filter, exclude_status
- Count endpoint (single), batch count endpoint

### Decisions (Phase 6)

9. **Separate model from `QueryFilter`** — `EntityPropertyFilter` uses full
   property URIs and is datatype-aware.  The legacy `QueryFilter` (short names,
   string-only values) remains for backward compatibility but is not extended.

10. **Property filter is required join** — Like sort bindings, property filter
    patterns are required (not OPTIONAL).  An entity missing the filtered
    property is excluded.  This is the correct semantic — if you filter for
    `status = active`, entities without a status property should not appear.

11. **`in` / `not_in` operators** — Needed for URI properties where a user wants
    to match multiple values (e.g. "active or pending").  Value field accepts a
    list for these operators.

12. **Unified property registry** — `_FILTERABLE_ENTITY_PROPERTIES` is the
    single source of truth.  `_ENTITY_SORT_PROPERTIES` is derived from it.
    Adding a new property to the registry makes it available for both sorting
    and filtering.

13. **List endpoint uses convenience parameters** — Rather than exposing the
    full `EntityPropertyFilter` JSON on a GET endpoint, specific query params
    (`status`, `created_after`, etc.) provide a clean REST API.  The KG query
    POST endpoint uses the full model.

---

## Phase 7: Count-only queries

### Motivation

A UI often needs to display counts for several filter combinations before the
user clicks one to load the actual data.  Examples:

- Dashboard tiles: "Active Persons: 142", "Pending Persons: 7", "Modified
  last 48h: 23" — each clickable to drill into the matching list.
- Tab badges or sidebar counts.

Today the only way to get a count is to execute a full paginated query (which
also fetches the first page of results).  A **count-only** mode avoids the
overhead of serialising and transferring entity data.

### Design

Two surfaces — one for each existing endpoint family:

#### 7a. List endpoint: `GET /api/graphs/kgentities/count`

A lightweight sub-endpoint that mirrors the list endpoint's filter parameters
but returns **only** the count.  Shares the same filter parameters as the
list endpoint (Phase 6b) plus the existing `entity_type_uri` and `search`
parameters.

```
GET /api/graphs/kgentities/count?space_id=...&graph_id=...
    &entity_type_uri=http://vital.ai/ontology/haley-ai-kg#KGEntityType_Person
    &status=http://vital.ai/ontology/vital-aimp#ObjectStatusType_ACTIVE
    &modified_after=2026-04-26T05:00:00Z
```

Response:

```json
{
  "count": 142
}
```

This endpoint reuses the existing `_build_count_query` infrastructure in
`kgentity_list_impl.py` (which already builds a `SELECT (COUNT(DISTINCT
?entity) AS ?count)` SPARQL query with the same filter patterns as the
data query).  The count endpoint simply executes that query without
building the data query.

**Multiple counts in one call** (batch variant):

For the dashboard use-case where the UI needs several counts at once, a
batch endpoint avoids N sequential round-trips:

```
POST /api/graphs/kgentities/counts
{
  "space_id": "...",
  "graph_id": "...",
  "count_requests": [
    {
      "label": "active_persons",
      "entity_type_uri": "http://vital.ai/ontology/haley-ai-kg#KGEntityType_Person",
      "status": "http://vital.ai/ontology/vital-aimp#ObjectStatusType_ACTIVE"
    },
    {
      "label": "recently_modified",
      "modified_after": "2026-04-26T05:00:00Z"
    },
    {
      "label": "pending",
      "status": "http://vital.ai/ontology/vital-aimp#ObjectStatusType_PENDING"
    }
  ]
}
```

Response:

```json
{
  "counts": [
    { "label": "active_persons", "count": 142 },
    { "label": "recently_modified", "count": 23 },
    { "label": "pending", "count": 7 }
  ]
}
```

Counts are executed concurrently via `asyncio.gather` for efficiency.

#### 7b. KG query endpoint: `count_only` flag

The existing `POST /api/graphs/kgqueries` endpoint already builds and
executes a count query alongside the data query.  Adding a `count_only`
flag to `KGQueryRequest` lets callers request just the count:

```json
{
  "criteria": {
    "query_type": "entity",
    "query_mode": "edge",
    "source_entity_criteria": {
      "entity_type": "http://vital.ai/ontology/haley-ai-kg#KGEntityType_Person"
    },
    "entity_property_filters": [
      {
        "property_uri": "http://vital.ai/ontology/vital-aimp#hasObjectStatusType",
        "operator": "eq",
        "value": "http://vital.ai/ontology/vital-aimp#ObjectStatusType_ACTIVE"
      },
      {
        "property_uri": "http://vital.ai/ontology/vital#hasObjectModificationDateTime",
        "operator": "gte",
        "value": "2026-04-26T05:00:00Z"
      }
    ]
  },
  "count_only": true
}
```

Response (when `count_only=true`):

```json
{
  "query_type": "entity",
  "total_count": 142,
  "page_size": 0,
  "offset": 0,
  "entity_uris": []
}
```

When `count_only` is set, the endpoint:
1. Builds and executes **only** the count query (skips the data query).
2. Returns `total_count` with empty result lists and `page_size=0`.
3. Should be significantly faster since it avoids the paginated SPARQL
   query, entity URI extraction, and optional entity graph hydration.

This works for all query types (`entity`, `frame_query`, `relation`,
`frame`).

### Example: Active Person entities modified in last 48 hours

**Via list count endpoint:**
```
GET /api/graphs/kgentities/count?space_id=sp1&graph_id=g1
    &entity_type_uri=http://vital.ai/ontology/haley-ai-kg#KGEntityType_Person
    &status=http://vital.ai/ontology/vital-aimp#ObjectStatusType_ACTIVE
    &modified_after=2026-04-26T05:15:00Z
```

**Via KG query endpoint:**
```json
{
  "criteria": {
    "query_type": "entity",
    "source_entity_criteria": {
      "entity_type": "http://vital.ai/ontology/haley-ai-kg#KGEntityType_Person"
    },
    "entity_property_filters": [
      {
        "property_uri": "http://vital.ai/ontology/vital-aimp#hasObjectStatusType",
        "operator": "eq",
        "value": "http://vital.ai/ontology/vital-aimp#ObjectStatusType_ACTIVE"
      },
      {
        "property_uri": "http://vital.ai/ontology/vital#hasObjectModificationDateTime",
        "operator": "gte",
        "value": "2026-04-26T05:15:00Z"
      }
    ]
  },
  "count_only": true
}
```

**Via client (Python):**
```python
from vitalgraph.model.kgentities_model import EntityPropertyFilter
from datetime import datetime, timedelta, timezone

now = datetime.now(timezone.utc)
cutoff = (now - timedelta(hours=48)).isoformat()

# Single count via list endpoint
count = await client.kgentities.count_kgentities(
    space_id=space_id, graph_id=graph_id,
    entity_type_uri="http://vital.ai/ontology/haley-ai-kg#KGEntityType_Person",
    status="http://vital.ai/ontology/vital-aimp#ObjectStatusType_ACTIVE",
    modified_after=cutoff,
)
print(f"Active persons modified recently: {count}")

# Count via KG query
result = await client.kgqueries.query_entities(
    space_id=space_id, graph_id=graph_id,
    entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntityType_Person",
    entity_property_filters=[
        EntityPropertyFilter(
            property_uri="http://vital.ai/ontology/vital-aimp#hasObjectStatusType",
            operator="eq",
            value="http://vital.ai/ontology/vital-aimp#ObjectStatusType_ACTIVE"
        ),
        EntityPropertyFilter(
            property_uri="http://vital.ai/ontology/vital#hasObjectModificationDateTime",
            operator="gte",
            value=cutoff,
        ),
    ],
    count_only=True,
)
print(f"Count: {result.total_count}")

# Batch counts via list endpoint
counts = await client.kgentities.batch_count_kgentities(
    space_id=space_id, graph_id=graph_id,
    count_requests=[
        {"label": "active_persons", "entity_type_uri": "...", "status": "...#ObjectStatusType_ACTIVE"},
        {"label": "pending_persons", "entity_type_uri": "...", "status": "...#ObjectStatusType_PENDING"},
        {"label": "recently_modified", "modified_after": cutoff},
    ]
)
for c in counts:
    print(f"{c['label']}: {c['count']}")
```

### Implementation steps

| Step | File | Change | Status |
|------|------|--------|--------|
| 7a | `kgentities_model.py` | Add `CountResponse` and `BatchCountRequest`/`BatchCountResponse` models | ⏭ Skipped — inline Pydantic models used in route instead |
| 7b | `kgqueries_model.py` | Add `count_only: bool = False` to `KGQueryRequest` | ✅ Done |
| 7c | `kgentities_endpoint.py` (server) | Add `GET /kgentities/count` route — build count query only, return `CountResponse` | ✅ Done |
| 7d | `kgentities_endpoint.py` (server) | Add `POST /kgentities/counts` batch route — execute multiple count queries concurrently | ✅ Done |
| 7e | `kgquery_endpoint.py` (server) | In each `_execute_*_query`, check `count_only`; if true, run only count query and return early | ✅ Done |
| 7f | `kgentities_endpoint.py` (client) | Add `count_kgentities()` and `batch_count_kgentities()` methods | ✅ Done |
| 7g | `kgqueries_endpoint.py` (client) | Pass `count_only` through to `KGQueryRequest` | ✅ Done |

**Implementation notes (Phase 7a/7b):**
- `GET /kgentities/count` reuses `KGEntityListProcessor._build_count_query()` + `_build_property_filter_clauses()`
- `POST /kgentities/counts` uses `_CountRequest` / `_BatchCountRequest` Pydantic models defined inline in `_setup_routes`
- Batch counts execute concurrently via `asyncio.gather`
- Client returns `int` from `count_kgentities()` and `List[Dict]` from `batch_count_kgentities()`
- `count_only` on KG query endpoint short-circuits for entity, relation, frame, and frame_query types

### Phase 7 tests

| Test | Description |
|------|-------------|
| Count unfiltered | `/kgentities/count` with no filters matches list `total_count` |
| Count by entity type | `/kgentities/count?entity_type_uri=...` |
| Count by status | `/kgentities/count?status=...` |
| Count by date range | `/kgentities/count?modified_after=...&modified_before=...` |
| Count combined filters | entity_type + status + date — should be ≤ individual counts |
| Batch counts | POST `/kgentities/counts` with 3 requests returns 3 counts |
| Batch concurrency | Batch with slow filters still returns faster than sequential |
| KG query count_only (entity) | `count_only=true` returns `total_count`, empty `entity_uris` |
| KG query count_only (frame_query) | `count_only=true` returns `total_count`, empty `frame_results` |
| KG query count_only matches full | count_only total_count == full query total_count |
| Count zero result | Filter that matches nothing returns `{"count": 0}` |

### Count cache invalidation integration tests (2026-04-30)

Six self-contained tests added to the multi-org CRUD suite
(`case_count_cache_invalidation.py`, wired as Step 12.5 in
`test_multiple_organizations_crud.py`).  Each test warms the cache, mutates
data, then asserts the count reflects the mutation — proving the cache was
invalidated.  All tests create/delete their own temp entities so downstream
expected counts are unaffected.

| # | Test | Endpoint | Mutation | Status |
|---|------|----------|----------|--------|
| 1 | Unfiltered count create+delete | `GET /kgentities/count` | Create entity → count +1 → delete → count back to baseline | ✅ |
| 2 | Batch count create+delete | `POST /kgentities/counts` | Same as #1, via batch endpoint | ✅ |
| 3 | KGQuery count_only create+delete | `POST /kgqueries` count_only=true | Same as #1, via KG query entity count_only | ✅ |
| 4 | Filtered count (search) after update | `GET /kgentities/count?search=X` | Create entity with name X → search count=1 → update name → search count=0 | ✅ |
| 5 | Filtered count (entity_type_uri) create+delete | `GET /kgentities/count?entity_type_uri=OrgEntity` | Create OrganizationEntity → filtered count +1 → delete → back | ✅ |
| 6 | Relation count_only create+delete | `POST /kgqueries` relation count_only | Create src+dst entities + MakesProduct relation → relation count +1 → delete all → back | ✅ |

### Decisions (Phase 7)

14. **Separate count endpoint vs query param** — The list endpoint gets a
    dedicated `/count` sub-path (clean REST semantics for a GET).  The KG
    query endpoint gets a `count_only` flag on the existing POST body
    (avoids duplicating the complex criteria model into a new endpoint).

15. **Route ordering** — `/kgentities/count` must be registered **before**
    `/kgentities/{entity_uri}` in FastAPI so that `"count"` is not captured
    as an entity URI.  The entity URI is **not** included in the count
    endpoint URL.

16. **Single space/graph per batch** — `space_id` and `graph_id` are at the
    top level of the batch request and shared across all count requests.
    A single batch cannot span multiple graphs.

17. **Batch size limit** — `count_requests` is capped at **20** items per
    batch call.  Validation rejects requests exceeding this limit.

18. **Batch counts** — The POST `/counts` batch endpoint allows the UI to
    request multiple counts in a single round-trip.  Counts execute
    concurrently server-side via `asyncio.gather`.

19. **Response shape for count_only KG queries** — Returns the standard
    `KGQueryResponse` with `total_count` populated and result lists empty.
    This avoids introducing a new response type and lets the client use
    the same deserialization path.

20. **Client `count_entities()` return type** — Returns a `CountResponse`
    object (not a bare int) for extensibility.  The response includes at
    minimum `count: int` and can later carry metadata like query time.

21. **Count query reuse** — Both the list and KG query count endpoints
    reuse the existing count query builders (`_build_count_query` and
    `build_entity_count_query_sparql` respectively).  No new SPARQL
    generation needed.

22. **Relation query pagination** — ✅ Done.  Relation queries now paginate
    within the SPARQL query itself (LIMIT/OFFSET on the triplestore),
    matching the entity and frame query types.  `count_only` on relation
    queries is now a genuine short-circuit that avoids full result
    serialization.

### Count cache

Count queries for dashboards can be called frequently with the same
filters.  To avoid redundant triplestore hits, count results are cached
using the same invalidation-on-write pattern as the existing
`EntityGraphCache` (`vitalgraph/cache/entity_graph_cache.py`).

**Design:**

- **Cache key**: `(space_id, graph_id, query_hash)` where `query_hash` is
  a deterministic hash of the generated SPARQL count query string.
- **Cache value**: the integer count.
- **TTL safety net**: Same as `EntityGraphCache` — default 15-minute TTL
  bounds staleness if a NOTIFY signal is lost.
- **Invalidation**: Any write operation that mutates entities in a
  `(space_id, graph_id)` — create, update, delete — invalidates **all**
  cached counts for that `(space_id, graph_id)`.  This uses the same
  `_signal_entity_change()` hook that already invalidates the entity
  graph cache.  Count cache invalidation is coarse-grained (graph-level,
  not per-entity) because a single entity change can affect any filtered
  count.
- **Implementation**: A lightweight `CountCache` class in
  `vitalgraph/cache/count_cache.py`, modelled after `EntityGraphCache`
  but simpler (values are ints, no compression needed).
- **Cross-instance**: Like entity graph cache, count cache listens to
  PostgreSQL NOTIFY signals for cross-instance invalidation.

| Step | File | Change | Status |
|------|------|--------|--------|
| 7h | `cache/count_cache.py` | New `CountCache` class with `get`, `put`, `invalidate_graph` methods | ✅ Done |
| 7i | `kgentities_endpoint.py` (server) | Import count cache; check cache before SPARQL; store result; invalidate on writes | ✅ Done |
| 7j | `kgquery_endpoint.py` (server) | Same cache integration for `count_only` queries | ✅ Done |

**Implementation notes (Count cache):**
- `CountCache` in `vitalgraph/cache/count_cache.py` — LRU OrderedDict, keyed by `(space_id, graph_id, sha256(sparql))`, values are ints
- Max 5,000 entries, 15-minute TTL safety net (matching EntityGraphCache)
- Graph-level invalidation: any entity write invalidates all counts for that `(space_id, graph_id)`
- Invalidation wired into `_invalidate_entity_cache()` alongside existing EntityGraphCache invalidation
- Cache integrated into `_count_entities`, `_batch_count_entities` (list endpoint), and all 4 `count_only` blocks in kgquery_endpoint (entity, relation, frame, frame_query)
- Module-level singleton `_count_cache` shared across endpoint instances

**Additional fix (2026-04-30): Cross-instance invalidation + backfill safety**

Two issues identified and fixed alongside the count cache work:

1. **Cross-instance NOTIFY handlers** (`vitalgraphapp_impl.py`): The existing
   `CHANNEL_ENTITY_GRAPH`, `CHANNEL_GRAPH`, and `CHANNEL_SPACE` signal handlers
   only invalidated `_entity_graph_cache`. Added `_count_cache` invalidation to
   all three handlers so count cache is also cleared on remote writes.

2. **SPARQL UPDATE direct invalidation** (`sparql_sql_space_impl.py`): The
   post-UPDATE and graph clear/delete paths now also call
   `_count_cache.invalidate_graph()`.

3. **Backfill task cache invalidation + advisory lock** (`kg_server_properties.py`):
   The background backfill task writes directly to `rdf_quad` tables via raw SQL,
   bypassing the SPARQL UPDATE pipeline. Two problems fixed:
   - **Stale caches**: After backfilling properties onto entities, the entity
     graph cache and count cache could serve stale data. Now
     `backfill_entity_server_properties_sql()` invalidates
     `_entity_graph_cache` per patched entity URI and `_count_cache` per graph.
   - **Duplicate triples**: The `rdf_quad` PK includes `quad_uuid DEFAULT
     gen_random_uuid()`, so `ON CONFLICT DO NOTHING` never fires — concurrent
     instances would insert duplicate property triples. Fixed by acquiring a
     PostgreSQL advisory lock (`pg_try_advisory_lock`) keyed by
     `sha256("backfill:{space_id}:{graph_id}")` before processing. If another
     instance holds the lock, the backfill skips that graph and moves on.

---

## VitalSigns Annotation API — Integration Plan

Moved to dedicated planning file: `planning_sql/kg_query/annotation_integration_plan.md`
