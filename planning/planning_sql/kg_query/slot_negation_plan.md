# KGQuery: Frame & Slot Negation Support

## Problem Statement

The KGQuery SPARQL generation currently treats all frame and slot criteria as **mandatory BGP patterns** (inner-join semantics). If an entity does not have a frame of the requested type, or a frame does not have a slot of the requested type, the entity is silently excluded from results.

There is no way to express:
1. "Find entities that do **not** have a frame of type X"
2. "Find entities where a slot of type X does **not** exist on a frame"
3. "Find entities where a slot of type X exists but has **no value** asserted"

## New Capabilities

### Frame-Level Negation

Add a `negate` boolean field to `FrameCriteria`:

| Field | Type | Default | Semantics |
|---|---|---|---|
| `negate` | `bool` | `False` | When `True`, the entire frame pattern (connection + type filter + any nested slot criteria) is wrapped in `FILTER NOT EXISTS { ... }` |

This enables queries like: "find entities that do NOT have a frame of type AddressFrame" or "find entities that do NOT have a frame of type X with a slot of type Y equal to Z."

Frame negation also applies to frame-level queries (`build_frame_query_sparql`), where it means "find frames that do NOT match these criteria."

### Slot-Level Comparators

Add two new comparator values to `SlotCriteria`:

| Comparator | Priority | Semantics | SPARQL Pattern |
|---|---|---|---|
| `not_exists` | **Primary** | Slot of this type must NOT exist on the frame | `FILTER NOT EXISTS { ...slot pattern... }` |
| `is_empty` | Secondary | Slot exists but has no value property asserted | Mandatory slot pattern + `OPTIONAL { ?slot prop ?val } FILTER(!BOUND(?val))` |

The existing comparators (`eq`, `ne`, `gt`, `lt`, `gte`, `lte`, `contains`, `exists`) remain unchanged.

### Priority

**Primary:** Frame `negate` and slot `not_exists` — these handle the common query cases of filtering for entities that lack a particular frame type or slot type.

**Secondary (deferrable):** Slot `is_empty` — a diagnostic/data-quality tool. In normal operation, slots are either created with a value or not created at all, so `is_empty` would not match anything. Useful for error checking (finding orphaned or incompletely populated slots) but not used in typical application queries.

**Why not `optional`?** KGQuery returns a set of matching entity/frame URIs. A criterion either narrows that set or it doesn't — wrapping a pattern in OPTIONAL is equivalent to not including the criterion at all. If sorting-by-nullable-slot is needed in the future, that would be handled in the sort-criteria layer.

## Affected Files

### 1. Model Layer

**`vitalgraph/model/kgentities_model.py`** — Pydantic models
- `FrameCriteria`: Add `negate: bool = Field(False, description="When True, negate this frame criterion — match entities that do NOT have this frame pattern")`
- `SlotCriteria`: Update `comparator` field description to include `not_exists`, `is_empty`

**`vitalgraph/sparql/kg_query_builder.py`** — Dataclass models
- `FrameCriteria`: Add `negate: bool = False`
- `SlotCriteria`: Update comment on `comparator` field to include new values

### 2. SPARQL Builder — Entity Queries

**`vitalgraph/sparql/kg_query_builder.py`** — `KGQueryCriteriaBuilder`

Six slot-criteria code paths need the new comparator branches. They all share the same pattern today:

```python
if slot_criterion.value is not None and slot_criterion.comparator:
    value_clause = self._build_value_filter(...)
    frame_clauses.append(value_clause)
elif slot_criterion.comparator == "exists":
    frame_clauses.append(f"?{slot_var} ?slot_pred ?slot_val .")
```

Each needs to be extended with:

```python
elif slot_criterion.comparator == "not_exists":
    # Wrap the entire slot connection + type filter in FILTER NOT EXISTS
elif slot_criterion.comparator == "is_empty":
    # Keep slot connection mandatory, OPTIONAL the value, FILTER(!BOUND)
```

**Specific locations (line numbers approximate):**

| Method | Context | Lines |
|---|---|---|
| `build_entity_query_sparql` | `frame_criteria → slot_criteria` loop | ~383–407 |
| `build_entity_query_sparql` | standalone `slot_criteria` loop | ~422–448 |
| `build_frame_query_sparql` | `slot_criteria` loop | ~579–594 |
| `_build_hierarchical_frame_patterns` | recursive child frame slots | ~734–758 |
| `_build_grouped_slot_criteria` | grouped slot criteria | ~887–908 |
| `build_frame_query_sparql_with_sorting` | frame query slot criteria | ~1101–1117 |

### 3. SPARQL Builder — Connection Queries

**`vitalgraph/sparql/kg_connection_query_builder.py`** — `KGConnectionQueryBuilder`

Two code paths for source/destination frame patterns:

| Method | Lines |
|---|---|
| `_build_source_frame_patterns` | ~247–270 |
| `_build_destination_frame_patterns` | ~306–330 |

### 4. Endpoint Conversion Layer

**`vitalgraph/endpoint/kgquery_endpoint.py`** — `_execute_frame_query`
- The `convert_frame_criteria` helper (line ~206) already passes `comparator` through; no change needed unless we add validation.

**`vitalgraph/kg/kgframe_query_endpoint_impl.py`** — `_convert_to_sparql_criteria`
- Already passes `comparator` through; no change needed.

### 5. `_build_value_filter` method

**`vitalgraph/sparql/kg_query_builder.py`** — `_build_value_filter` (~line 775)
- No changes needed. This method is only called when `value is not None and comparator` is a value-bearing comparator. The new comparators (`not_exists`, `is_empty`) are handled before this method is reached.

## Implementation Details

### Frame `negate` — Negate the entire frame pattern

When `FrameCriteria.negate = True`, the entire entity→frame connection block (edge triples + frame type filter + all nested slot criteria) is wrapped in `FILTER NOT EXISTS { ... }`.

**Generated SPARQL (edge mode, frame_type only):**
```sparql
FILTER NOT EXISTS {
    ?frame_edge_0 vital-core:vitaltype <Edge_hasEntityKGFrame> .
    ?frame_edge_0 vital-core:hasEdgeSource ?entity .
    ?frame_edge_0 vital-core:hasEdgeDestination ?frame_0 .
    ?frame_0 haley:hasKGFrameType <urn:AddressFrame> .
}
```

**Generated SPARQL (edge mode, frame_type + slot criteria):**
```sparql
FILTER NOT EXISTS {
    ?frame_edge_0 vital-core:vitaltype <Edge_hasEntityKGFrame> .
    ?frame_edge_0 vital-core:hasEdgeSource ?entity .
    ?frame_edge_0 vital-core:hasEdgeDestination ?frame_0 .
    ?frame_0 haley:hasKGFrameType <urn:AddressFrame> .
    ?slot_edge_0_0 vital-core:vitaltype <Edge_hasKGSlot> .
    ?slot_edge_0_0 vital-core:hasEdgeSource ?frame_0 .
    ?slot_edge_0_0 vital-core:hasEdgeDestination ?slot_0_0 .
    ?slot_0_0 haley:hasKGSlotType <urn:ZipCodeSlot> .
    ?slot_0_0 haley:hasTextSlotValue "10001" .
}
```

This second example means: "find entities that do NOT have an AddressFrame with a ZipCodeSlot equal to 10001" — a powerful combined negation.

**Generated SPARQL (direct mode):**
```sparql
FILTER NOT EXISTS {
    ?entity vg-direct:hasEntityFrame ?frame_0 .
    ?frame_0 haley:hasKGFrameType <urn:AddressFrame> .
}
```

**Implementation:** In the frame_criteria loop, after building `frame_clauses`, check `frame_criterion.negate`. If true, wrap the joined clauses in `FILTER NOT EXISTS { ... }` instead of appending them directly to `where_clauses`.

### Slot `not_exists` — Negate the entire slot pattern

For the edge-based pattern, the slot connection involves 3–4 triples (edge vitaltype, edge source, edge destination, optional slot type filter). All of these must be wrapped in `FILTER NOT EXISTS { ... }`.

**Generated SPARQL (edge mode):**
```sparql
FILTER NOT EXISTS {
    ?slot_edge_0_0 vital-core:vitaltype <Edge_hasKGSlot> .
    ?slot_edge_0_0 vital-core:hasEdgeSource ?frame_0 .
    ?slot_edge_0_0 vital-core:hasEdgeDestination ?slot_0_0 .
    ?slot_0_0 haley:hasKGSlotType <urn:SomeSlotType> .
}
```

**Generated SPARQL (direct mode):**
```sparql
FILTER NOT EXISTS {
    ?frame_0 vg-direct:hasSlot ?slot_0_0 .
    ?slot_0_0 haley:hasKGSlotType <urn:SomeSlotType> .
}
```

**Key detail:** Variables inside `FILTER NOT EXISTS` are scoped — they do not need unique names since they cannot clash with outer variables. However, for clarity and consistency, keep the existing naming scheme.

### `is_empty` — Slot exists, value not asserted

The slot connection triples remain mandatory (the slot must exist). The value property is wrapped in `OPTIONAL` and filtered with `!BOUND`.

**Generated SPARQL:**
```sparql
?slot_edge_0_0 vital-core:vitaltype <Edge_hasKGSlot> .
?slot_edge_0_0 vital-core:hasEdgeSource ?frame_0 .
?slot_edge_0_0 vital-core:hasEdgeDestination ?slot_0_0 .
?slot_0_0 haley:hasKGSlotType <urn:SomeSlotType> .
OPTIONAL { ?slot_0_0 haley:hasTextSlotValue ?val_0_0 . }
FILTER(!BOUND(?val_0_0))
```

**Requires:** `_get_slot_value_property()` to determine the correct property. If `slot_class_uri` is not provided, defaults to `haley:hasTextSlotValue`. For robustness, could check all value properties:

```sparql
OPTIONAL { ?slot_0_0 haley:hasTextSlotValue ?val_text_0_0 . }
OPTIONAL { ?slot_0_0 haley:hasDoubleSlotValue ?val_num_0_0 . }
OPTIONAL { ?slot_0_0 haley:hasIntegerSlotValue ?val_int_0_0 . }
OPTIONAL { ?slot_0_0 haley:hasBooleanSlotValue ?val_bool_0_0 . }
FILTER(!BOUND(?val_text_0_0) && !BOUND(?val_num_0_0) && !BOUND(?val_int_0_0) && !BOUND(?val_bool_0_0))
```

**Decision:** If `slot_class_uri` is provided, use the specific value property. If not, use the multi-property check above to be thorough.

## Implementation Plan

### Step 1: Update Models
- Add `negate: bool` field to both Pydantic and dataclass `FrameCriteria`
- Add `not_exists`, `is_empty` to comparator descriptions in both Pydantic and dataclass `SlotCriteria`
- Add validation: if `FrameCriteria.negate=True`, reject any nested `SlotCriteria` with `comparator="not_exists"` (no double negation)

### Step 2: Add Frame Negation to Frame Criteria Loop
In `build_entity_query_sparql` (line ~360), after building `frame_clauses` and before appending to `where_clauses`, add:

```python
if frame_criterion.negate:
    where_clauses.append(f"FILTER NOT EXISTS {{ {' '.join(frame_clauses)} }}")
else:
    where_clauses.append(" ".join(frame_clauses))
```

Apply the same pattern in:
- `_build_hierarchical_frame_patterns` (child frame loop)
- `_build_source_frame_patterns` / `_build_destination_frame_patterns` in connection builder

### Step 3: Add Helper Method `_build_negated_slot_pattern`
Add a helper that generates the `FILTER NOT EXISTS` block for a given slot.

```python
def _build_negated_slot_pattern(self, slot_var, slot_edge_var, frame_var, 
                                 slot_criterion, use_edge_pattern) -> str:
```

### Step 4: Add Helper Method `_build_empty_value_pattern`
Add a helper that generates the `OPTIONAL + !BOUND` pattern for `is_empty`.

```python
def _build_empty_value_pattern(self, slot_var, slot_criterion, value_var) -> str:
```

### Step 5: Update All Six Entity/Frame Slot Criteria Code Paths
At each of the six locations in `kg_query_builder.py`, extend the comparator branching:

```python
elif slot_criterion.comparator == "not_exists":
    negation = self._build_negated_slot_pattern(...)
    frame_clauses.append(negation)
elif slot_criterion.comparator == "is_empty":
    # Keep slot connection mandatory, add empty value check
    frame_clauses.append(self._build_empty_value_pattern(...))
elif slot_criterion.value is not None and slot_criterion.comparator:
    value_clause = self._build_value_filter(...)
    frame_clauses.append(value_clause)
elif slot_criterion.comparator == "exists":
    frame_clauses.append(...)
```

### Step 6: Update Connection Query Builder
Apply frame negation and slot comparator branches in `_build_source_frame_patterns` and `_build_destination_frame_patterns` in `kg_connection_query_builder.py`.

### Step 7: Update Endpoint Conversion Layer
Ensure `negate` is passed through in:
- `kgquery_endpoint.py` → `convert_frame_criteria` helper
- `kgframe_query_endpoint_impl.py` → `_convert_to_sparql_criteria`

### Step 8: Add Unit Tests
Create a test file that validates the generated SPARQL for each new comparator:

**`test_scripts_misc/test_kgquery_negation.py`**

Test cases — frame negation:
1. `negate=True` on frame with `frame_type` only — Verify `FILTER NOT EXISTS` wraps frame pattern
2. `negate=True` on frame with `frame_type` + slot criteria — Verify combined negation
3. `negate=True` on child frame in hierarchical structure
4. Mix of `negate=True` and `negate=False` frames in same query
5. Edge mode vs direct mode — Both generate correct frame negation

Test cases — slot negation:
6. `not_exists` — Verify `FILTER NOT EXISTS` wraps slot pattern
7. `is_empty` with `slot_class_uri` — Verify specific value property in OPTIONAL
8. `is_empty` without `slot_class_uri` — Verify multi-property OPTIONAL check
9. Mixed — `eq` on one slot with `not_exists` on another in same frame
10. Connection queries — `not_exists` on source entity's frame slot

### Step 9: Integration Test
Create an integration test that runs actual queries against the sparql_sql backend:

**`test_scripts_misc/test_kgquery_slot_negation_integration.py`**

Setup:
- Create entities with different frame types (some have AddressFrame, some don't)
- Create entities with frames and slots where some slots have values, some don't
- Create entities with frames that are missing certain slot types entirely

Verify:
- Frame `negate=True` returns only entities without the specified frame type
- Frame `negate=True` with slot criteria returns only entities without that specific frame+slot combination
- Slot `not_exists` returns only entities without the specified slot type
- Slot `is_empty` returns only entities with the slot type but no value

## Edge Cases

1. **Frame `negate=True` without `frame_type`** — Negates "entity has any frame," which is unusual but valid. Log a warning.
2. **Frame `negate=True` with nested `negate=True` child frame** — Double negation. The outer FILTER NOT EXISTS contains inner patterns. Semantically: "entity does NOT have a parent frame that has a child frame of type X." Valid but complex.
3. **Slot `not_exists` with `value` provided** — Ignore the value; `not_exists` only checks slot presence. Log a warning.
4. **Slot `is_empty` with `value` provided** — Ignore the value; `is_empty` checks absence of value. Log a warning.
5. **Slot `not_exists` without `slot_type`** — This would negate "any slot exists," which is likely a mistake. Log a warning and generate the pattern anyway.
6. **Multiple `not_exists` on same frame** — Each generates its own `FILTER NOT EXISTS` block. They compose correctly (AND semantics).
7. **Frame `negate=True` combined with slot `not_exists` inside** — **Reject at validation.** The slot `not_exists` pattern inside a negated frame creates double negation (universal quantification), which is confusing and unlikely to be intentional. Raise a 400 error: "Cannot use slot comparator 'not_exists' inside a negated frame criterion."

## Estimated Scope

- ~2 new helper methods in `kg_query_builder.py` (~40 lines)
- ~6 slot-criteria call sites updated in `kg_query_builder.py` (~6 lines each = ~36 lines)
- ~4 frame-criteria call sites updated with negate check (~3 lines each = ~12 lines)
- ~2 call sites updated in `kg_connection_query_builder.py` (~8 lines each = ~16 lines)
- ~4 lines updated in model layer (new field + updated descriptions)
- ~2 lines in endpoint conversion to pass `negate` through
- ~1 unit test file (~250 lines)
- ~1 integration test file (~180 lines)

**Total: ~540 lines of new/changed code**
