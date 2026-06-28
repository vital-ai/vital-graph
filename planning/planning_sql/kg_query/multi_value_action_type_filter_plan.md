# Multi-Value Filter & Sort: Entity Properties + Slot Criteria

## Status: ✅ Complete

**Date**: 2026-05-08

---

## Problem Statement

Two related areas of the query system currently assume **single-valued**
properties and need multi-value support:

### 1. Top-level entity property: `hasKGActionTypeList`

The entity property filter/sort system (`_FILTERABLE_ENTITY_PROPERTIES` in
`kgentities_model.py`) currently supports only single-valued properties.
All five existing properties (`hasName`, `hasObjectModificationDateTime`,
`hasObjectCreationTime`, `hasKGEntityType`, `hasObjectStatusType`) produce
exactly one triple per entity for a given predicate.

We need to add:

```
http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList
```

This property is fundamentally different: it is a **multi-valued URI
property**.  A single entity can have zero, one, or many values for this
predicate — each stored as a separate RDF triple:

```turtle
<urn:entity:123> haley:hasKGActionTypeList <urn:action:TypeA> .
<urn:entity:123> haley:hasKGActionTypeList <urn:action:TypeB> .
<urn:entity:123> haley:hasKGActionTypeList <urn:action:TypeC> .
```

### 2. Multi-valued slot criteria in KG queries

The `SlotCriteria` system (`SlotCriteria.comparator` in both the Pydantic
model and the builder dataclass) supports: `eq`, `ne`, `gt`, `lt`, `gte`,
`lte`, `contains`, `exists`, `not_exists`, `is_empty`.  All of these
assume a slot has a single value.  Multi-valued slots (e.g. a `KGTextSlot`
with multiple `hasTextSlotValue` triples) need the same multi-value
operators across all four KG query types: **entity**, **relation**,
**frame**, and **frame_query**.

### What already exists

| Component | Current state |
|-----------|--------------|
| **Ontology** | `hasKGActionTypeList` is a `URIProperty` defined on KGEntity (and many subclasses). Present in `haley-ai-kg-0.1.0-schema.json`. VitalSigns short name: `kGActionTypeList` |
| **RDF storage** | Multi-valued — VitalSigns stores one triple per value. The subject has N triples for the same predicate |
| **Property registry** | `_FILTERABLE_ENTITY_PROPERTIES` has 5 entries, all single-valued. No `uri_list` datatype exists |
| **Filter operators** | URI type supports `eq`, `ne`, `in`, `not_in`. These assume a single value per entity |
| **Sort system** | `_ENTITY_SORT_PROPERTIES` derived from the registry. Sort binds `?entity <prop> ?sort_val .` — produces row duplication for multi-valued properties |
| **SPARQL generation** | `_build_property_filter_clauses()` and `_build_entity_property_filters()` emit simple triple patterns that assume one binding per entity |
| **Slot criteria** | `SlotCriteria` comparators assume single-valued slots. `_build_value_filter()` (kg_query_builder.py) and `_build_slot_value_filter()` (kg_connection_query_builder.py) generate single-value SPARQL patterns |
| **KG query cases** | All four query types (entity, relation, frame, frame_query) delegate slot filtering to these builder methods |

---

## RDF Multi-Value Semantics

In RDF/SPARQL, a multi-valued property means the triple pattern:

```sparql
?entity haley:hasKGActionTypeList ?val .
```

binds **once per value**.  An entity with 3 action types produces 3 rows.
This has two consequences:

1. **Filtering**: A simple triple pattern + FILTER acts as "entity has
   at least one value matching the filter" — which is usually what we
   want.  But `ne` and `not_in` require care (see below).

2. **Sorting**: The sort variable binds multiple times per entity,
   producing duplicate rows.  `SELECT DISTINCT ?entity` collapses them
   but the sort order becomes non-deterministic when an entity has
   multiple values.

---

## Filtering Design

### New datatype: `uri_list`

Add a new datatype `"uri_list"` to the property registry to distinguish
multi-valued URI properties from single-valued ones:

```python
_FILTERABLE_ENTITY_PROPERTIES = {
    # ... existing entries ...
    "http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList": "uri_list",
}
```

### Operators for `uri_list`

| Operator | Meaning | SPARQL pattern |
|----------|---------|---------------|
| `has` | Entity has this value in the list | Simple triple match |
| `has_any` | Entity has at least one of these values | Triple + `FILTER(?val IN (...))` |
| `has_all` | Entity has all of these values | Multiple triple patterns, one per value |
| `not_has` | Entity does NOT have this value | `FILTER NOT EXISTS { ... }` |
| `not_has_any` | Entity has NONE of these values | `FILTER NOT EXISTS` with `IN` |
| `exists` | Entity has at least one value (non-empty list) | Simple triple pattern (no filter) |
| `not_exists` | Entity has no values (empty list) | `FILTER NOT EXISTS { ... }` |

**Why not reuse `eq`/`ne`/`in`/`not_in`?**  The semantics are different
for multi-valued properties.  With a single-valued URI property,
`eq` means "the value equals X".  With a multi-valued property, the
natural question is "does the list contain X?" — which is `has`.
Using distinct operator names avoids ambiguity and makes the API
self-documenting.

### SPARQL Patterns

**`has` (entity has value X in list):**
```sparql
?entity <http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList> <urn:action:TypeA> .
```

**`has_any` (entity has at least one of [X, Y]):**
```sparql
?entity <http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList> ?_action_val .
FILTER(?_action_val IN (<urn:action:TypeA>, <urn:action:TypeB>))
```

**`has_all` (entity has both X and Y):**
```sparql
?entity <http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList> <urn:action:TypeA> .
?entity <http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList> <urn:action:TypeB> .
```

**`not_has` (entity does NOT have X):**
```sparql
FILTER NOT EXISTS {
    ?entity <http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList> <urn:action:TypeA> .
}
```

**`not_has_any` (entity has NONE of [X, Y]):**
```sparql
FILTER NOT EXISTS {
    ?entity <http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList> ?_action_excl .
    FILTER(?_action_excl IN (<urn:action:TypeA>, <urn:action:TypeB>))
}
```

**`exists` (entity has at least one value):**
```sparql
?entity <http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList> ?_action_any .
```

**`not_exists` (entity has no values):**
```sparql
FILTER NOT EXISTS {
    ?entity <http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList> ?_action_any .
}
```

### Validation

```python
_OPERATORS_BY_DATATYPE = {
    # ... existing ...
    "uri_list": {"has", "has_any", "has_all", "not_has", "not_has_any", "exists", "not_exists"},
}
```

- `has`, `not_has`: `value` must be a single string (URI)
- `has_any`, `has_all`, `not_has_any`: `value` must be a list of strings (URIs)
- `exists`, `not_exists`: `value` is ignored / not required

---

## Sorting Design

### The multi-value sort problem

When sorting by a single-valued property, each entity produces exactly one
`?sort_val` binding, and `ORDER BY` works as expected.

With a multi-valued property, an entity can produce N bindings for the sort
variable.  `SELECT DISTINCT ?entity` collapses duplicate entity URIs, but
which value does the triplestore pick for ordering?  The answer is
**non-deterministic** in SPARQL — different engines may pick different values.

### Typical cardinality

In practice, `hasKGActionTypeList` will usually have **0 or 1** values.
Multiple values are possible but less common.  This informs the sort strategy:

- **0 values**: Entity is excluded from results (required-join semantic,
  consistent with existing sort behavior).  If we want to include entities
  with empty lists, we need OPTIONAL + NULLS LAST — a decision point.
- **1 value**: Sorts like any single-valued property — no ambiguity.
- **N values**: Need a deterministic sort order.

### Sort strategy options

| Strategy | SPARQL | Pros | Cons |
|----------|--------|------|------|
| **A. MIN/MAX aggregate** | `SELECT ?entity (MIN(?val) AS ?sort_val) ... GROUP BY ?entity` | Deterministic, well-defined, works in standard SPARQL 1.1 | Requires GROUP BY which complicates the existing query structure; performance impact on large datasets |
| **B. First value (non-deterministic)** | `?entity <prop> ?sort_val .` (plain) | Simple, no query changes needed | Non-deterministic for multi-value; acceptable if N>1 is rare |
| **C. Concatenated sort key** | `GROUP_CONCAT(?val; separator=",")` | All values contribute to sort | String comparison of concatenated URIs is not semantically meaningful |
| **D. Exclude from sort when multi-valued** | Same as B but documented | Honest about limitation | Does not solve the problem |

### Recommended approach: Strategy A (MIN/MAX) with opt-in

For the **list entities endpoint** (`GET /kgentities`), use Strategy A:

```sparql
SELECT DISTINCT ?s (MIN(?_action_sort) AS ?sort_val) WHERE {
    GRAPH <graph_id> {
        # ... type clause, filters ...
        ?s <http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList> ?_action_sort .
    }
}
GROUP BY ?s
ORDER BY ASC(?sort_val) ?s
LIMIT 25 OFFSET 0
```

- `MIN` for `asc` order (sort by the "first" URI alphabetically)
- `MAX` for `desc` order (sort by the "last" URI alphabetically)
- This is deterministic and well-defined for any cardinality

For the **KG query endpoint** (`POST /kgqueries`), the `entity_property`
sort type already uses a subquery pattern that can accommodate GROUP BY.

### Impact on existing sort infrastructure

The current sort implementation in `kgentity_list_impl.py` injects:

```sparql
?s <sort_property> ?sort_val .
```

For `uri_list` properties, this must change to the GROUP BY pattern above.
This means the query builder needs to know the datatype of the sort property
to decide whether to use a simple triple or an aggregate.

### Empty lists and sort — required join (Decision D4)

Consistent with existing sort behavior: entities missing the sort property
are **excluded** from results.  Entities with an empty `hasKGActionTypeList`
will not appear when sorting by this property.  This matches Decision #3
in the sorting plan and avoids OPTIONAL + NULLS LAST complexity.

---

## Implementation Plan

### Phase 1: Model and validation changes — ✅ Complete

| Step | File | Change | Status |
|------|------|--------|--------|
| 1a | `kgentities_model.py` | Add `hasKGActionTypeList` to `_FILTERABLE_ENTITY_PROPERTIES` with datatype `"uri_list"` | ✅ |
| 1b | `kgentities_model.py` | Add `"uri_list"` entry to `_OPERATORS_BY_DATATYPE` with operators `has`, `has_any`, `has_all`, `not_has`, `not_has_any`, `exists`, `not_exists` | ✅ |
| 1c | `kgentities_model.py` | Update `EntityPropertyFilter.validate_entity_property_filter` to handle `uri_list` value validation (single string for `has`/`not_has`, list for `has_any`/`has_all`/`not_has_any`, none for `exists`/`not_exists`) | ✅ |

### Phase 2: Filter SPARQL generation — ✅ Complete

| Step | File | Change | Status |
|------|------|--------|--------|
| 2a | `kgentity_list_impl.py` | `_build_property_filter_clauses()` — deferred to Phase 4 (`action_type` convenience param uses simple triple pattern) | ✅ |
| 2b | `kg_query_builder.py` | Update `_build_entity_where_clause()` to handle `uri_list` operators in the KG query path (has, has_any, has_all, not_has, not_has_any, exists, not_exists) | ✅ |
| 2c | `kgentity_list_impl.py` | Count query includes `uri_list` filter patterns via shared `prop_filters` string | ✅ |

### Phase 3: Sort SPARQL generation — ✅ Complete

| Step | File | Change | Status |
|------|------|--------|--------|
| 3a | `kgentity_list_impl.py` | Detect `uri_list` datatype via `_FILTERABLE_ENTITY_PROPERTIES`; emit GROUP BY + MIN/MAX aggregate pattern instead of simple triple | ✅ |
| 3b | `kgentity_list_impl.py` | Updated `_build_optimized_properties_query` — uses `SELECT ?s (MIN/MAX(?_sort_raw) AS ?sort_val)` with `GROUP BY ?s` for uri_list, drops DISTINCT | ✅ |
| 3c | `kgentity_list_impl.py` | Updated `_build_entity_uris_query` — same GROUP BY change for graph-mode listing | ✅ |
| 3d | `kgentity_list_impl.py` | `_build_count_query` unchanged — `COUNT(DISTINCT ?entity)` correctly deduplicates multi-value bindings | ✅ |
| 3e | `kg_query_builder.py` | Updated `_build_sort_bindings` — returns 4-tuple `(patterns, select_vars, order_by, requires_group_by)`, callers use GROUP BY instead of DISTINCT when needed | ✅ |

### Phase 4: List endpoint convenience parameters — ✅ Complete (server)

| Step | File | Change | Status |
|------|------|--------|--------|
| 4a | `kgentities_endpoint.py` | Added `action_type` query parameter to GET `/kgentities`, threaded through `_list_entities` → `list_entities` → `_build_property_filter_clauses`. Generates `?entity <hasKGActionTypeList> <uri> .` triple pattern | ✅ |
| 4b | `client/endpoint/kgentities_endpoint.py` | Added `action_type` parameter to client `list_kgentities()` with doc and query param pass-through | ✅ |

### Phase 5: Tests — ✅ Complete

| Test | Description |
|------|-------------|
| Filter `has` | Entities with action type A in list |
| Filter `has_any` | Entities with action type A or B |
| Filter `has_all` | Entities with both action type A and B |
| Filter `not_has` | Entities without action type A |
| Filter `not_has_any` | Entities with neither A nor B |
| Filter `exists` | Entities with at least one action type |
| Filter `not_exists` | Entities with no action types |
| Sort ASC | Sort by action type list ascending (MIN) |
| Sort DESC | Sort by action type list descending (MAX) |
| Sort + filter combined | Filter by action type A, sort by name |
| Sort with single value | Entities with exactly one action type sort correctly |
| Count with filter | Count-only with `has` filter matches full query count |
| List endpoint `action_type` param | Convenience parameter works |
| Multi-value entity excluded from sort | Entity with 0 action types excluded when sorting by this property |
| Pagination consistency | Page 1 + page 2 ordering is consistent with GROUP BY sort |

---

## Multi-Valued Slot Criteria in KG Queries

### Problem

The `SlotCriteria` comparator set currently supports: `eq`, `ne`, `gt`,
`lt`, `gte`, `lte`, `contains`, `exists`, `not_exists`, `is_empty`.
These all assume a slot has a **single value**.

Certain slot classes are defined as **multi-value slots** — a single
slot instance stores multiple values on the same property via multiple
RDF triples.  These are distinct from the case of multiple slot instances
of the same single-value type within a frame (e.g. two `KGTextSlot`
objects on the same frame).

#### Multi-value slot classes

| Slot class | Value property | Property type |
|------------|---------------|---------------|
| `KGMultiChoiceSlot` | `haley:hasMultiChoiceSlotValues` | `StringProperty` |
| `KGMultiChoiceOptionSlot` | `haley:hasMultiChoiceSlotValues` | `StringProperty` |
| `KGMultiTaxonomySlot` | `haley:hasMultiTaxonomySlotValues` | `URIProperty` |
| `KGMultiTaxonomyOptionSlot` | `haley:hasMultiTaxonomySlotValues` | `URIProperty` |

A `KGMultiChoiceSlot` with values `["Boston", "NYC"]` is stored as:

```turtle
<urn:slot:1> haley:hasMultiChoiceSlotValues "Boston" .
<urn:slot:1> haley:hasMultiChoiceSlotValues "NYC" .
```

This is **not** the same as having two separate `KGTextSlot` instances
on the same frame — that is multiple single-value slot instances, and
the existing `eq`/`ne` comparators already handle them correctly.

The multi-value comparators (`has`, `has_any`, `has_all`, `not_has`,
`not_has_any`) are designed for these multi-value slot classes where a
single slot node has N triples for the same value property:

- `eq` matches if **any** value equals X (correct for `has` semantic)
- `ne` matches if **any** value ≠ X (wrong — matches when slot has
  value X plus something else)
- No way to say "slot has ALL of these values"
- No way to say "slot has NONE of these values"

### New slot comparators

Extend `SlotCriteria.comparator` with the same multi-value operators:

| Comparator | Meaning | Value field |
|------------|---------|-------------|
| `has` | Slot has this value | Single value |
| `has_any` | Slot has at least one of these values | List of values |
| `has_all` | Slot has all of these values | List of values |
| `not_has` | Slot does NOT have this value | Single value |
| `not_has_any` | Slot has NONE of these values | List of values |

**Note**: `exists` and `not_exists` already handle the "slot
present/absent" case.  `is_empty` handles "slot exists but has no value".
These remain unchanged.

### SPARQL patterns for slot multi-value operators

The patterns are analogous to the entity property patterns but operate on
the slot's value property (determined by `slot_class_uri`).  The value
property is resolved by `_get_slot_value_property()` which maps slot
class URIs to their SPARQL property names.  For the multi-value slot
classes this resolves to:

- `KGMultiChoiceSlot` / `KGMultiChoiceOptionSlot` → `haley:hasMultiChoiceSlotValues`
- `KGMultiTaxonomySlot` / `KGMultiTaxonomyOptionSlot` → `haley:hasMultiTaxonomySlotValues`

Let `{value_prop}` be the resolved property.

**`has` (slot has value X):**
```sparql
?slot_0_0 {value_prop} <urn:value:X> .
```
Same as current `eq` — works correctly because the triple pattern matches
any of the multiple values.

**`has_any` (slot has at least one of [X, Y]):**
```sparql
?slot_0_0 {value_prop} ?mv_val_0_0 .
FILTER(?mv_val_0_0 IN (<urn:value:X>, <urn:value:Y>))
```

**`has_all` (slot has both X and Y):**
```sparql
?slot_0_0 {value_prop} <urn:value:X> .
?slot_0_0 {value_prop} <urn:value:Y> .
```

**`not_has` (slot does NOT have value X):**
```sparql
FILTER NOT EXISTS {
    ?slot_0_0 {value_prop} <urn:value:X> .
}
```

**`not_has_any` (slot has NONE of [X, Y]):**
```sparql
FILTER NOT EXISTS {
    ?slot_0_0 {value_prop} ?mv_excl_0_0 .
    FILTER(?mv_excl_0_0 IN (<urn:value:X>, <urn:value:Y>))
}
```

### Affected query types

All four KG query types support frame→slot filtering and must handle the
new comparators:

| Query type | Builder file | Method(s) affected |
|------------|-------------|-------------------|
| **entity** (Case 2) | `kg_query_builder.py` | `_build_value_filter()`, `_build_entity_where_clause()` (frame_criteria + standalone slot_criteria paths) |
| **relation** (Case 3) | `kg_connection_query_builder.py` | `_build_slot_value_filter()`, `_build_source_frame_patterns()`, `_build_destination_frame_patterns()` |
| **frame** (legacy) | `kgquery_endpoint.py` | Inline slot filtering in `_execute_frame_query()` (calls `_build_value_filter`) |
| **frame_query** (Case 1) | `kgquery_endpoint.py` | `_execute_frame_query_case()` (converts to builder `SlotCriteria`, then delegates to `build_frame_query_sparql()`) |

### Value formatting for multi-value operators

The `value` field on `SlotCriteria` is typed `Optional[Any]`.  For the
new list operators (`has_any`, `has_all`, `not_has_any`), `value` must be
a list.  Value formatting (string quoting, URI angle brackets, XSD typing)
must be applied per-element using the same logic as the existing
`_build_value_filter` / `_build_slot_value_filter` methods.

---

## Implementation Plan (continued)

### Phase 6: Multi-valued slot model changes — ✅ Complete

| Step | File | Change | Status |
|------|------|--------|--------|
| 6a | `kgentities_model.py` | Documented new comparators in `SlotCriteria.comparator` field description | ✅ |
| 6b | `kg_query_builder.py` | Updated builder `SlotCriteria` dataclass comparator comment | ✅ |

### Phase 7: Multi-valued slot SPARQL generation — ✅ Complete

| Step | File | Change | Status |
|------|------|--------|--------|
| 7a | `kg_query_builder.py` | Added `_format_slot_value()` helper + handlers for `has`, `has_any`, `has_all`, `not_has`, `not_has_any` in `_build_value_filter()` | ✅ |
| 7b | `kg_query_builder.py` | `_build_entity_where_clause()` frame_criteria path — no change needed (delegates to `_build_value_filter`) | ✅ Verified |
| 7c | `kg_query_builder.py` | `_build_entity_where_clause()` standalone slot_criteria path — no change needed (delegates to `_build_value_filter`) | ✅ Verified |
| 7d | `kg_query_builder.py` | `_build_grouped_slot_criteria()` — no change needed (delegates to `_build_value_filter`) | ✅ Verified |
| 7e | `kg_query_builder.py` | `build_frame_query_sparql()` — delegates to `_build_value_filter`, works with new comparators | ✅ Verified |
| 7f | `kg_connection_query_builder.py` | Added `_format_conn_value()` helper + handlers for `has`, `has_any`, `has_all`, `not_has`, `not_has_any` in `_build_slot_value_filter()` | ✅ |
| 7g | `kg_connection_query_builder.py` | `_build_source_frame_patterns()` — no change needed (delegates to `_build_slot_value_filter`) | ✅ Verified |
| 7h | `kg_connection_query_builder.py` | `_build_destination_frame_patterns()` — same as 7g | ✅ Verified |
| 7i | `kgquery_endpoint.py` | `_execute_frame_query()` legacy path — already delegates to `_build_value_filter()`, no inline changes needed | ✅ Verified |
| 7j | `kgquery_endpoint.py` | `convert_frame_criteria()` passes comparator as raw string — new comparators flow through correctly | ✅ Verified |
| 7k | `kg_query_builder.py` | `_get_slot_value_property()` — added mappings for `KGMultiChoiceSlot`, `KGMultiChoiceOptionSlot`, `KGMultiTaxonomySlot`, `KGMultiTaxonomyOptionSlot` (see D11) | ✅ |
| 7l | `kg_connection_query_builder.py` | `_build_slot_value_filter()` property resolution — added `MultiChoiceSlot`/`MultiTaxonomySlot` branches | ✅ |

### Phase 8: Multi-valued slot tests — ✅ Complete

| Test | Query type | Description |
|------|-----------|-------------|
| Slot `has` (entity) | entity | Entity query — filter for entity whose text slot has value "X" |
| Slot `has_any` (entity) | entity | Entity query — slot has at least one of ["X", "Y"] |
| Slot `has_all` (entity) | entity | Entity query — slot has both "X" and "Y" |
| Slot `not_has` (entity) | entity | Entity query — slot does NOT have value "X" |
| Slot `not_has_any` (entity) | entity | Entity query — slot has none of ["X", "Y"] |
| Slot `has` (relation source) | relation | Relation query — source entity's slot has value |
| Slot `has_any` (relation dest) | relation | Relation query — destination entity's slot has any of values |
| Slot `not_has` (relation) | relation | Relation query — source entity's slot does not have value |
| Slot `has` (frame_query) | frame_query | Frame query — frame's slot has value |
| Slot `has_any` (frame_query) | frame_query | Frame query — frame's slot has any of values |
| Slot `has` (frame legacy) | frame | Legacy frame query — slot has value |
| Count consistency | entity | count_only with `has` filter matches full query count |
| Multi-value + single-value combined | entity | `has` on one slot + `eq` on another in same frame |
| Hierarchical frame + multi-value | entity | Multi-value slot filter on a child frame in hierarchical structure |

---

## Decisions

### D1: New operators for multi-value properties — ✅ Confirmed

Use dedicated operators: `has`, `has_any`, `has_all`, `not_has`,
`not_has_any`, `exists`, `not_exists`.  Do NOT reuse `eq`/`ne`/`in`/`not_in`
which have single-value semantics.

### D2: `not_has` includes entities with empty lists — ✅ Confirmed

`FILTER NOT EXISTS` naturally includes entities with zero values — an
entity with no action types trivially satisfies "does not have TypeA".
This is the correct semantic.

### D3: Sort aggregate — MIN for ASC, MAX for DESC — ✅ Confirmed

Deterministic sort via `MIN`/`MAX` aggregate.  Alphabetical URI order is
arbitrary but deterministic, which is sufficient.

### D4: Sort with empty lists — exclude (required join) — ✅ Confirmed

Consistent with existing sort behavior (Decision #3 in sorting plan).
Entities with no action type values are excluded when sorting by this
property.  OPTIONAL + NULLS LAST can be added later if needed.

### D5: List endpoint convenience parameter — ✅ Include

Add an `action_type` query parameter to `GET /kgentities` for the `has`
filter shorthand (single URI — "entities that have this action type").
This parallels `status` for `hasObjectStatusType`.  For multi-value
operations (`has_any`, `has_all`, etc.), use the POST
`EntityPropertyFilter` path.

### D6: Scope — top-level property + multi-valued slot criteria in KG queries

This plan covers **two** related pieces:

1. **Top-level entity property** — `hasKGActionTypeList` added to
   `_FILTERABLE_ENTITY_PROPERTIES` as `uri_list` datatype.  The `uri_list`
   infrastructure is generic so additional multi-valued properties can be
   added by simply adding a registry entry.

2. **Multi-valued slot criteria in KG queries** — The `SlotCriteria`
   comparator set is extended with the same multi-value operators (`has`,
   `has_any`, `has_all`, `not_has`, `not_has_any`) for the dedicated
   multi-value slot classes (`KGMultiChoiceSlot`, `KGMultiChoiceOptionSlot`,
   `KGMultiTaxonomySlot`, `KGMultiTaxonomyOptionSlot`) across all four
   KG query cases: `entity`, `relation`, `frame`, and `frame_query`.

### D7: Multi-valued slot operators mirror entity property operators

The new slot comparators use the same names as the entity property
`uri_list` operators for consistency.  The SPARQL patterns are analogous
but operate on the slot value property instead of a direct entity property.

### D8: `eq` coexists with `has` — no breaking change — ✅ Confirmed

The existing `eq` comparator on slots is unchanged.  It accidentally gives
correct "has" semantics on multi-valued slots (matches any value).  The new
`has` operator is an explicit alias.  No existing callers break.

### D9: Validate value type for list slot operators — ✅ Confirmed

Add validation to `SlotCriteria` (or at SPARQL generation time) that
rejects non-list values for `has_any`, `has_all`, `not_has_any`.  Fail
fast with a clear error rather than producing broken SPARQL.

### D10: Legacy frame query — keep isolated, do not integrate — ✅ Confirmed

_(see below)_

### D11: Multi-value slot classes — specific class requirement — ✅ Confirmed

The multi-value comparators (`has`, `has_any`, `has_all`, `not_has`,
`not_has_any`) apply **only** to the four dedicated multi-value slot
classes:

- `KGMultiChoiceSlot` → `hasMultiChoiceSlotValues` (StringProperty)
- `KGMultiChoiceOptionSlot` → `hasMultiChoiceSlotValues` (StringProperty)
- `KGMultiTaxonomySlot` → `hasMultiTaxonomySlotValues` (URIProperty)
- `KGMultiTaxonomyOptionSlot` → `hasMultiTaxonomySlotValues` (URIProperty)

These classes store multiple values on a single slot node via multiple
RDF triples on the same property.  This is **not** the same as having
multiple instances of a single-value slot type (e.g. two `KGTextSlot`
nodes on the same frame).  The latter case is handled by the existing
`eq`/`ne` comparators and does not need multi-value operators.

Both `_get_slot_value_property()` in `kg_query_builder.py` and the
`_build_slot_value_filter()` property resolution in
`kg_connection_query_builder.py` have been updated to map these slot
classes to their correct value properties.

### D10 (continued): Legacy frame query — keep isolated, do not integrate — ✅ Confirmed

The `_execute_frame_query()` inline slot handling in `kgquery_endpoint.py`
is intentionally isolated from the newer builder.  This legacy path will
be removed in the future.  Add the new multi-value comparator cases
without integrating with the other KG query cases.

**Note**: The current legacy frame query implementation may be split into
separate implementation files as needed to keep the code clean (e.g. moving
inline SPARQL generation into a dedicated legacy builder file).  However,
it must **not** be integrated with the newer query builder infrastructure
(`kg_query_builder.py`, `kg_connection_query_builder.py`).  The goal is to
keep the legacy implementation fully partitioned from the new query
implementations so it can be removed cleanly in the future.

---

## SQL Pipeline Bugs Fixed (Phase 9)

During testing, the multi-value sort (Phase 3) exposed two bugs in the
v2 SPARQL→SQL pipeline (`vitalgraph/db/sparql_sql/`).  Both were root-cause
fixes in the SQL emitter — no workarounds needed at the SPARQL or endpoint
level.

### Bug 1: MIN/MAX used numeric column for URI values

**File**: `emit_group.py` — `_qualify_agg_inner()`

**Root cause**: `_qualify_agg_inner` for MIN/MAX preferred the `__num`
(numeric companion) column when available.  For triple-sourced variables,
`__num` is always allocated but is NULL for non-numeric RDF types (URIs,
strings).  This caused `MIN(g0.v2__num)` to be NULL for all groups, and
the SPARQL error guard (`CASE WHEN COUNT(*) != COUNT(col) THEN NULL`)
evaluated to NULL — destroying sort order entirely.

**Fix**: MIN/MAX now always uses the text column (`g0.v2`).  Text
comparison is correct for SPARQL MIN/MAX across all RDF term types.
SUM/AVG continue to use `__num` since they require arithmetic.

### Bug 2: PROJECT buried ORDER BY in subquery

**File**: `emit_project.py` — `emit_project()`

**Root cause**: `emit_project` wraps its child SQL in
`SELECT cols FROM (child_sql) AS pN`.  When the child is an ORDER node,
the ORDER BY ends up inside the subquery.  PostgreSQL ignores ORDER BY
inside subqueries, so the final result was unsorted.

**Fix**: `emit_project` now detects when its child plan is an ORDER node
and re-emits the ORDER BY on the outer SELECT, rewriting column
references from the child alias to `pN`.

### Workaround removed

An interim two-query strategy was implemented in `kgentity_list_impl.py`
(Query 1: flat GROUP BY for sorted URIs, Query 2: VALUES-based property
fetch).  After fixing both pipeline bugs, this workaround was removed.
All sort paths now use the single-query approach via
`_build_optimized_properties_query()`.

---

## Dependencies

- Sorting plan Phases 1–7 (all complete) — this builds on that foundation
- `_FILTERABLE_ENTITY_PROPERTIES` registry pattern (Phase 6, complete)
- `EntityPropertyFilter` model and validation (Phase 6a, complete)
- Count cache invalidation (Phase 7, complete) — new filter patterns
  will automatically benefit from existing cache infrastructure

---

## References

- `kgentities_model.py` — property registry, operator validation, filter model
- `kgentity_list_impl.py` — list endpoint SPARQL generation
- `kg_query_builder.py` — KG query endpoint SPARQL generation
- `kg_query_sorting_plan.md` — sorting and filtering design decisions
- `haley-ai-kg-0.1.0-schema.json` — property definition
- `planning/kg_classes_properties.md` — full property catalog
