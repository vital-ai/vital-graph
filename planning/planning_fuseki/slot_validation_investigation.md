# Slot Type/Property Mismatch Validation Investigation

## Problem Statement

`include_entity_graph=True` returned 0 objects for a valid entity. Root cause: two `KGTextSlot` objects
in Fuseki had `hasIntegerSlotValue` properties, and those same slots also had `hasTextSlotValue`.
VitalSigns `from_triples_list` throws `AttributeError` when a property doesn't belong to the declared
type, causing the entire entity graph conversion to fail.

The data was created via the standard REST API path (kgentities endpoint → create entity → add/update
frames and slots). **Validation should already be in place** — incoming JSON-LD should be instantiated
as typed VitalSigns GraphObjects, and `__setattr__` enforces that only valid properties can be set.

## Hypothesis

The incoming JSON-LD was converted to GraphObjects using a **raw property path** that bypasses
VitalSigns type validation. Instead of instantiating a properly typed object (e.g., `KGTextSlot()`)
and setting properties via validated `__setattr__`, the code may be:

1. Creating objects from raw JSON-LD dicts with arbitrary key/value pairs
2. Converting those raw dicts directly to RDF triples (bypassing VitalSigns type checking)
3. Storing those unvalidated triples in PostgreSQL and Fuseki

The mismatch only surfaces on **read** when `from_triples_list` tries to reconstitute typed objects
and hits the `__setattr__` validation.

## Data That Was Corrupted

| Slot URI | Stored vitaltype | Invalid Property |
|---|---|---|
| `..._financial_info_monthly_sales` | `KGTextSlot` | `hasIntegerSlotValue=120000` |
| `..._financial_info_amount_requested` | `KGTextSlot` | `hasIntegerSlotValue=50000` |

Both slots had BOTH `hasTextSlotValue` AND `hasIntegerSlotValue`, meaning the write path
stored all incoming properties regardless of whether they belong to the declared type.

## Investigation Plan

### Phase 1: Trace the REST API Write Path (Server-Side)

The data was written via the kgentities endpoint. Trace the full path:

1. **Endpoint entry**: `kgentities_endpoint.py` → `_create_or_update_frames` / `_update_entity_frames`
2. **Processor**: `KGFrameCreateProcessor` / `KGFrameUpdateProcessor` — how do they convert JSON-LD to objects?
3. **JSON-LD → GraphObject conversion**: Which method is used?
   - `VitalSigns.from_jsonld()` / `from_jsonld_list()` → **validated path** (creates typed objects)
   - `KGJsonLdUtils.convert_jsonld_to_graph_objects()` → uses VitalSigns, should be validated
   - Raw dict processing with manual property assignment → **potential bypass**
4. **Object → RDF conversion**: `obj.to_rdf()` vs raw triple construction
5. **Storage**: `add_rdf_quads_batch` / `add_quads` in `dual_write_coordinator.py`

### Phase 2: Check for Raw Property Bypass Paths

Look for code patterns that could bypass VitalSigns validation:

- [ ] Direct `setattr(obj, property_uri, value)` without type checking
- [ ] Raw dict-to-triple conversion (JSON-LD properties → RDF triples without GraphObject instantiation)
- [ ] `to_rdf()` on objects created from raw dicts
- [ ] N-Triples bulk load path that feeds raw triples to Fuseki

### Phase 3: Identify the Specific Slot Write Path

Slots are created/updated via:
- `POST /api/graphs/kgentities/kgframes` with `operation_mode=create` or `operation_mode=update`
- This calls `_create_or_update_frames` or `_update_entity_frames`
- Frames contain slots — slots are nested objects in the JSON-LD

Key question: When a slot is created with a declared type `KGTextSlot` but the JSON-LD payload
includes `hasIntegerSlotValue`, does the conversion path reject it or pass it through?

### Phase 4: Fix

Once the bypass is identified:
- Add validation at the write path to reject objects with invalid properties
- Ensure all JSON-LD → RDF conversion goes through VitalSigns typed instantiation
- Consider a round-trip validation: after converting to triples, verify they can be read back

## Files to Investigate

### Server-side endpoint handlers
- `vitalgraph/endpoint/kgentities_endpoint.py` — `_create_or_update_frames`, `_update_entity_frames`
- `vitalgraph/endpoint/kgframes_endpoint.py` — frame CRUD handlers

### Processors (JSON-LD → GraphObject conversion)
- `vitalgraph/kg_impl/kgentity_create_impl.py`
- `vitalgraph/kg_impl/kgframe_create_impl.py`
- `vitalgraph/kg_impl/kgframe_update_impl.py`
- `vitalgraph/kg_impl/kg_jsonld_utils.py` — `convert_jsonld_to_graph_objects`
- `vitalgraph/kg_impl/kg_sparql_utils.py` — triple conversion utilities

### Backend storage
- `vitalgraph/kg_impl/kg_backend_utils.py` — `store_objects` (line 99)
- `vitalgraph/db/fuseki_postgresql/dual_write_coordinator.py` — `add_quads`, `update_quads`
- `vitalgraph/db/fuseki_postgresql/fuseki_dataset_manager.py` — `add_quads_to_dataset`

## Empirical Findings

### VitalSigns Validation Tests

All three VitalSigns conversion paths **correctly validate** and reject mismatched properties:

| Method | Input | Result |
|---|---|---|
| `vs.from_jsonld_list()` | KGTextSlot + hasIntegerSlotValue | **AttributeError** (rejects) |
| `vs.from_jsonld()` | KGTextSlot + hasIntegerSlotValue | **ValueError** (rejects) |
| `vs.from_triples_list()` | KGTextSlot triples + hasIntegerSlotValue | **AttributeError** (rejects) |
| `vs.from_jsonld_list()` | Batch: 2 valid + 1 invalid | **ValueError** (entire batch fails) |
| `vs.from_jsonld_list()` | @type=KGIntegerSlot, vitaltype=KGTextSlot | Creates KGIntegerSlot (uses @type) |

Key: `from_jsonld_list` fails the ENTIRE batch if any single object has invalid properties.

### REST Endpoint Server-Side Validation

All server-side write paths use `vs.from_jsonld_list()` or `vs.from_jsonld()`:

| Endpoint | Method | Line | Validates? |
|---|---|---|---|
| `kgentities_endpoint.py` | `_create_or_update_frames` | 1181 | ✅ `from_jsonld_list` |
| `kgentities_endpoint.py` | `_update_entity_frames` | 1675 | ✅ `from_jsonld_list` |
| `kgentities_endpoint.py` | direct create/update | 1391, 2304 | ✅ `from_jsonld_list` |
| `kgframes_endpoint.py` | `_convert_request_to_objects` | 138, 141 | ✅ `from_jsonld_list` |
| `kgframes_endpoint.py` | slot handling | 1110 | ✅ `from_jsonld` |
| `kgframes_endpoint.py` | slot handling | 1961, 1963 | ✅ `from_jsonld_list`/`from_jsonld` |

### Unvalidated Bypass Paths (exist but user confirms NOT used)

- `sparql_insert_endpoint.py` — raw SPARQL INSERT, no VitalSigns validation
- `postgresql_space_db_import.py` — bulk N-Triples import, no VitalSigns validation
- Direct Fuseki HTTP API access

### Potential Corruption Mechanisms Found

While all VitalSigns conversion paths validate correctly, three **structural issues** in the
write paths could cause property accumulation in Fuseki:

#### Issue 1: `_create_frame_slots` UPSERT does INSERT without DELETE

**File**: `kgframes_endpoint.py` line 1474-1487

```python
# Only CREATE mode checks existence — UPSERT skips straight to INSERT
if operation_mode == OperationMode.CREATE:
    for slot in slots:
        if await self._slot_exists_in_backend(...):
            return ... # fail

# This INSERT runs for ALL modes (create, upsert) — no DELETE of existing triples
created_uris = await self._store_frame_slots_in_backend(backend, ...)
```

If a slot is upserted with a different type (e.g., KGIntegerSlot → KGTextSlot), the new
triples are ADDED alongside the old ones. Old `rdf:type`, `vitaltype`, and value properties
are never removed. **This is the most likely corruption mechanism.**

#### Issue 2: `_update_frame_slots_in_backend` uses non-atomic DELETE + INSERT

**File**: `kgframes_endpoint.py` lines 2807-2863

```python
# Step 1: DELETE (separate SPARQL UPDATE call)
await backend.execute_sparql_update(space_id, delete_query)

# Step 2: INSERT (separate SPARQL UPDATE call)  
await backend.execute_sparql_update(space_id, insert_query)
```

Each call goes through `dual_write_coordinator.execute_sparql_update()` independently.
If the DELETE call's Fuseki operation fails (but PostgreSQL succeeds), old triples
remain in Fuseki while new triples are added, causing property accumulation.

**Contrast with**: `update_quads()` in `dual_write_coordinator.py` which properly combines
DELETE DATA + INSERT DATA into a single atomic Fuseki request (line 555).

#### Issue 3: `_store_frame_slots_in_backend` only does INSERT DATA

**File**: `kgframes_endpoint.py` lines 2914-2973

This is the storage method used by `_create_frame_slots`. It builds a single
`INSERT DATA` query with no preceding cleanup. Fine for first-time creation,
but dangerous when called from UPSERT mode where data may already exist.

### Root Cause Assessment

The most likely scenario for the observed corruption:

1. Slot was created as one type (e.g., `KGIntegerSlot` with `hasIntegerSlotValue`)
2. A subsequent operation (upsert or update) changed the slot to `KGTextSlot` with `hasTextSlotValue`
3. Due to Issue 1 or Issue 2, the old triples were not cleaned from Fuseki
4. Result: Fuseki has BOTH `hasIntegerSlotValue` (old) AND `hasTextSlotValue` (new)
5. On read, `from_triples_list` creates the object from the latest `rdf:type` but fails
   when it encounters the property belonging to the old type

## Recommended Fixes

### Fix 1: `_create_frame_slots` — add DELETE before INSERT for UPSERT mode

Before calling `_store_frame_slots_in_backend`, delete existing triples for the slot URIs:

```python
if operation_mode != OperationMode.CREATE:
    # Clean up existing data before upsert
    for slot in slots:
        delete_query = f"DELETE {{ GRAPH <{graph_id}> {{ <{slot.URI}> ?p ?o . }} }} ..."
        await backend.execute_sparql_update(space_id, delete_query)
```

Or better: use the existing `_update_frame_slots_in_backend` for UPSERT mode.

### Fix 2: `_update_frame_slots_in_backend` — use atomic `update_quads`

Replace the two separate `execute_sparql_update` calls with a single `update_quads` call
that uses the dual_write_coordinator's atomic combined DELETE DATA + INSERT DATA:

```python
# Build delete quads from existing triples
# Build insert quads from new VitalSigns objects
result = await coordinator.update_quads(space_id, delete_quads, insert_quads)
```

### Fix 3: Add round-trip validation before storage

After converting objects to triples, verify they can be read back:

```python
triples = GraphObject.to_triples_list(objects)
validated = vs.from_triples_list(triples)  # Will fail on invalid combinations
```

This catches any corruption introduced by code that modifies objects after initial validation.

## Status

- [x] Data fixed in Fuseki (changed types, removed orphaned properties)
- [x] Phase 1: Trace write path — all REST paths use from_jsonld_list
- [x] Phase 2: Check for raw property bypass — VitalSigns validates correctly
- [x] Phase 3: Identify corruption mechanisms — 3 structural issues found
- [x] Phase 4: Apply fixes to prevent future corruption — **DONE** (see Resolution below)

## Resolution — Changes Applied

### Root Cause (refined)

Two independent bugs combined to cause triple accumulation:

1. **`str(o)` on RDFLib Literal objects** — All quad construction code paths converted
   RDFLib `Literal` objects to plain strings via `str(o)`, stripping datatype and language
   metadata. This meant:
   - **INSERT**: Typed literals stored as plain strings (e.g., `"100"` instead of
     `"100"^^<xsd:integer>`)
   - **DELETE**: `DELETE DATA` couldn't match the stored typed literals in Fuseki because
     the delete quads contained untyped strings while Fuseki stored typed values. Old
     triples persisted.

2. **Non-atomic DELETE + INSERT** — Some write paths used separate SPARQL UPDATE calls
   for delete and insert. If the delete failed to match (due to issue 1), old triples
   remained and new triples were added alongside them.

### Fix 1: Preserve RDFLib objects in all quad builders (datatype preservation)

All insert quad builders now pass the RDFLib `Literal` object directly instead of
`str(o)`, so downstream formatters (`_format_term` in `fuseki_dataset_manager.py`,
`_extract_term_info` in `postgresql_db_impl.py`) can preserve datatype and language info.

All delete quad builders now reconstruct proper RDFLib objects from SPARQL JSON result
bindings using the `_sparql_binding_to_rdflib` helper, so `DELETE DATA` statements
match the exact typed literals stored in Fuseki.

**Helper added**: `_sparql_binding_to_rdflib(binding)` in `kgentity_frame_create_impl.py`
— converts a SPARQL JSON binding `{type, value, datatype?, xml:lang?}` back to the
correct RDFLib object (`URIRef`, `Literal` with datatype/language, or `BNode`).

### Fix 2: String-keyed diff for quad deduplication

RDFLib objects don't hash consistently across different construction paths (e.g., a
`Literal` from `to_triples_list` vs one reconstructed from SPARQL bindings). The diff
logic that removes common quads between delete and insert sets now uses string
representations as comparison keys while mapping back to the original RDFLib quads.

### Files Changed

| File | Methods Fixed |
|---|---|
| `vitalgraph/kg_impl/kgentity_frame_create_impl.py` | `build_insert_quads_for_objects`, `build_delete_quads_for_frames`, `_build_delete_quads_for_subjects`, `execute_atomic_frame_update`, `execute_frame_creation` + added `_sparql_binding_to_rdflib` helper |
| `vitalgraph/kg_impl/kgentity_update_impl.py` | `_build_insert_quads_for_objects`, `_build_delete_quads_for_entity` (+ SPARQL result format handling) |
| `vitalgraph/endpoint/kgframes_endpoint.py` | `_store_frames_in_backend`, `_store_frame_slots_in_backend`, `_update_frame_slots_in_backend` |

### Test Verification

`test_duplicate_uri_writes.py` — **8/8 passed**:

| Test | What it verifies |
|---|---|
| 1. Initial create | Entity graph created successfully |
| 2. Retrieve initial data | Correct object count and values |
| 3. Update same URIs, different values | `update_kgentities` with full entity graph succeeds |
| 4. No triple accumulation | Object count unchanged after update |
| 5. Values replaced correctly | Alpha Corp → Beta Industries, 100 → 500 |
| 6. Slot type change | KGTextSlot → KGIntegerSlot on same URI |
| 7. Type change clean | 0 leftover TextSlots, no orphaned properties |
| 8. Entity graph retrieval | Regression check — retrieval works after multiple writes |

`test_multiple_organizations_crud.py` — **100/100 passed** (regression check).

### Note on `update_kgentities` vs `update_entity_frames`

Initial investigation incorrectly assumed `update_kgentities` only updates the entity
object itself. In fact, the server-side `_handle_update_mode` passes **all** objects
(entity + frames + slots + edges) to `KGEntityUpdateProcessor.update_entity()`, which:
- **DELETE**: Queries all triples for the entity AND objects linked via `hasKGGraphURI`
- **INSERT**: Converts all passed objects to quads

So `update_kgentities` with a full entity graph is the correct approach for updating
an entire entity graph atomically. The `update_entity_frames` endpoint is for updating
only the frame/slot portion without touching the entity itself.
