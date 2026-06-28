# DB Write Path Audit — Consistency & Atomicity

## Purpose

Audit all database modification paths (INSERT, UPDATE, DELETE) in VitalGraph to identify:
1. Paths that bypass the central `update_quads` / dual-write coordinator
2. `str(o)` on RDFLib objects (strips datatype/language metadata)
3. Non-atomic DELETE + INSERT patterns (separate calls, not transactional)
4. Manual SPARQL construction that drops type information from SPARQL bindings

## Architecture Overview

### Central Write Functions (Correct Path)

All DB modifications should flow through the `DualWriteCoordinator` which writes to both PostgreSQL and Fuseki:

| Method | Pattern | Atomicity |
|---|---|---|
| `update_quads(delete_quads, insert_quads)` | Combined DELETE + INSERT in single PG transaction, single Fuseki request | **Atomic** ✅ |
| `add_quads(quads)` | INSERT only, via `add_quads_to_dataset` + `store_quads_to_postgresql` | Single op ✅ |
| `remove_quads(quads)` | DELETE only, via `_remove_quads_from_fuseki` + `remove_quads_from_postgresql` | Single op ✅ |
| `execute_sparql_update(sparql)` | Parses SPARQL → PG first, then Fuseki | Dual-write ✅ |

### Adapter Layers

- `FusekiPostgreSQLBackendAdapter` (`kg_backend_utils.py`) — wraps `DualWriteCoordinator`
- `FusekiPostgreSQLDbOps` (`fuseki_postgresql_db_ops.py`) — wraps `DualWriteCoordinator` methods as `add_rdf_quads_batch` / `remove_rdf_quads_batch`
- `db_space_impl.db_ops` — the `DbOps` layer used by `objects_impl.py`, `files_impl.py`
- `db_space_impl` directly — used by `triples_endpoint.py`, `kgrelations_endpoint.py`

All adapter layers correctly delegate to the dual-write coordinator. The issues are in **how quads are constructed** before reaching these layers.

---

## Issue Category 1: `str(o)` Stripping Datatype/Language

These paths convert RDFLib `Literal` objects to plain strings before storage, losing `datatype` and `xml:lang` metadata.

### ✅ FIXED

| File | Method | Status |
|---|---|---|
| `kgentity_frame_create_impl.py` | `build_insert_quads_for_objects` | Fixed — preserves `o` |
| `kgentity_frame_create_impl.py` | `build_delete_quads_for_frames` | Fixed — uses `_sparql_binding_to_rdflib` |
| `kgentity_frame_create_impl.py` | `_build_delete_quads_for_subjects` | Fixed — uses `_sparql_binding_to_rdflib` |
| `kgentity_update_impl.py` | `_build_insert_quads_for_objects` | Fixed — preserves `o` |
| `kgentity_update_impl.py` | `_build_delete_quads_for_entity` | Fixed — uses `_sparql_binding_to_rdflib` |
| `kgtypes_update_impl.py` | `_build_insert_quads_for_objects` | Fixed — preserves `o` |
| `kgtypes_update_impl.py` | `_build_delete_quads_for_kgtype` | Fixed — uses `_sparql_binding_to_rdflib` |
| `kgframes_endpoint.py` | `_store_frames_in_backend` | Fixed — preserves `o` |
| `kgframes_endpoint.py` | `_update_frame_slots_in_backend` | Fixed — preserves `o` |
| `kgframes_endpoint.py` | `_store_frame_slots_in_backend` | Fixed — preserves `o` |

### ⚠️ REMAINING

| File | Line | Method | Impact |
|---|---|---|---|
| `triples_endpoint.py` | 397 | `_handle_delete_jsonld` | `str(o)` on quads from `_jsonld_to_quads` (which returns RDFLib objects). DELETE path loses types. INSERT path (line 319) is clean. |

**Note**: `triples_endpoint.py` is a low-level raw triples API, not the primary entity/frame CRUD path. Risk is limited to direct triple deletion via this endpoint.

### ✅ CLEAN (no `str(o)`)

| File | Method | How |
|---|---|---|
| `objects_impl.py` | create/update/delete | Uses `graphobjects_to_quads` (preserves RDFLib) + CONSTRUCT queries (RDFLib) |
| `files_impl.py` | create/update/delete | Same pattern as `objects_impl.py` |
| `kgrelations_endpoint.py` | create/upsert | Uses `relation.to_rdf()` → RDFLib objects preserved in quads |
| `data_format_utils.py` | `graphobjects_to_quads` | `(s, p, o, graph_uri)` — no `str()` on `o` |

---

## Issue Category 2: Non-Atomic DELETE + INSERT

These paths perform DELETE and INSERT as **separate** calls. If the DELETE succeeds but the INSERT fails (or vice versa), data is left in an inconsistent state.

| File | Method | Pattern | Risk |
|---|---|---|---|
| `kgrelations_endpoint.py` | `_update_relations_in_space` (line 646+655) | `execute_sparql_update` (DELETE WHERE) then `add_rdf_quads_batch` (INSERT) | Data loss if INSERT fails after DELETE |
| `kgrelations_endpoint.py` | `_upsert_relations_in_space` (line 698+707) | Same pattern | Same risk |

**Recommended fix**: Refactor to use `update_quads(delete_quads, insert_quads)` which does both in a single PG transaction and a single Fuseki request.

---

## Issue Category 3: Manual SPARQL DELETE DATA — Drops Datatype

These paths build `DELETE DATA` SPARQL by hand, extracting values from SPARQL SELECT bindings. They format literals manually and may lose datatype/language information.

### `kgentity_delete_impl.py` — `delete_entity` (line 60-103)

Extracts `o_value` and `o_type` (`literal` vs `uri`) but **drops** `datatype` and `xml:lang`:
```python
o_value = binding['o'].get('value', '')
o_type = binding['o'].get('type', 'uri')
# datatype and xml:lang NOT extracted
```

Then formats as:
```python
if o_type == 'literal':
    o_formatted = f'"{o_escaped}"'  # No datatype, no language
```

This means `DELETE DATA` won't match typed literals like `"100"^^<xsd:integer>` in Fuseki. The triples survive the delete attempt.

**Goes through**: `execute_sparql_update` → SPARQL parser → dual-write.

### `kgentity_delete_impl.py` — `delete_entity_graph` (line 200-234)

Same issue — extracts `o_value` and `o_type` but drops `datatype` and `xml:lang`. Passes 5-tuples `(s, p, o, graph, o_type)` to `remove_rdf_quads_batch`.

The Fuseki side in `_remove_quads_from_fuseki` handles 5-tuples (lines 894-917) but only formats literals as plain `"value"` — no datatype, no language tag.

**Goes through**: `remove_rdf_quads_batch` → `remove_quads` → `_remove_quads_from_fuseki` + `remove_quads_from_postgresql`.

### `kgentity_frame_delete_impl.py` — `_extract_triples_from_results` (line 422-450)

**Correctly** extracts `o_datatype` and `o_lang` from SPARQL bindings and includes them as 6-tuple elements. The `_batch_delete_triples` method (lines 374-404) properly formats with datatype/language:
```python
if o_lang:
    o_formatted = f'"{o_escaped}"@{o_lang}'
elif o_datatype:
    o_formatted = f'"{o_escaped}"^^<{o_datatype}>'
```

This path is **correct** for Fuseki. However, it goes through `execute_sparql_update`, so the SPARQL parser must correctly parse the typed literals for PostgreSQL.

---

## Issue Category 4: DELETE WHERE via execute_sparql_update

These use `DELETE { ... } WHERE { ... }` pattern SPARQL. Fuseki handles this natively (resolves the pattern and deletes matching triples). For PostgreSQL, the SPARQL parser resolves the pattern via Fuseki SELECT queries.

The parser's `_resolve_delete_patterns_from_fuseki` (line 157-260) queries Fuseki for concrete triples and uses `_format_sparql_term` to format them. This method **does** preserve datatype and language:
```python
if datatype:
    return f'"{value}"^^<{datatype}>'
if lang:
    return f'"{value}"@{lang}'
```

The resulting string-formatted triples go to `_store_delete_triples` → `remove_quads_from_postgresql`. PostgreSQL's `_extract_term_info` parses the formatted string back (e.g., `"100"^^<xsd:integer>` → `value="100"`) for UUID lookup by `term_text`. Since term_text is the unwrapped value, the lookup **should** work.

**Verdict**: DELETE WHERE paths are **likely correct** because:
1. Fuseki handles DELETE WHERE natively
2. SPARQL parser preserves types in formatted strings
3. PostgreSQL lookup uses unwrapped value

| File | Method | Line |
|---|---|---|
| `kgframes_endpoint.py` | `_delete_frame_from_backend` | 2343, 2357 |
| `kgframes_endpoint.py` | `_delete_frame_slots_from_backend` | 2848, 2861 |
| `kgframe_graph_impl.py` | `delete_frame_graph` | 193 |
| `kgrelations_create_impl.py` | `_delete_relation` | 221 |
| `kgrelations_delete_impl.py` | (batch delete) | 72 |
| `kg_backend_utils.py` | `delete_object` | 508 |

---

## Priority Summary

### High Priority (Fuseki data corruption / orphaned triples)

1. **`kgentity_delete_impl.py` `delete_entity`** — Drops datatype/lang from DELETE DATA. Won't match typed literals in Fuseki. Entity triples may survive deletion.

2. **`kgentity_delete_impl.py` `delete_entity_graph`** — Same issue for entity graph deletion. 5-tuple path through `_remove_quads_from_fuseki` also drops datatype.

### Medium Priority (non-atomic, potential data loss)

3. **`kgrelations_endpoint.py` `_update_relations_in_space`** — Separate DELETE + INSERT, not atomic.

4. **`kgrelations_endpoint.py` `_upsert_relations_in_space`** — Same pattern.

### Low Priority (limited scope)

5. **`triples_endpoint.py` `_handle_delete_jsonld`** — `str(o)` on DELETE path. Low-level API, not primary CRUD path.

### No Action Needed

6. **DELETE WHERE paths** — Fuseki handles natively; parser preserves types for PostgreSQL.
7. **`objects_impl.py` / `files_impl.py`** — Clean, uses RDFLib objects throughout.
8. **`kgentity_frame_delete_impl.py`** — Correctly extracts and formats datatype/language.

---

## Fixes Applied

### Fix 1: `kgentity_delete_impl.py` — `delete_entity` (High Priority)

**Problem**: Built DELETE DATA SPARQL manually, extracting only `o_value` and `o_type` from SPARQL bindings. Dropped `datatype` and `xml:lang`, so typed literals like `"100"^^<xsd:integer>` were formatted as plain `"100"` — won't match in Fuseki.

**Fix**: Replaced manual SPARQL construction with `_sparql_binding_to_rdflib` to reconstruct proper RDFLib objects from SPARQL bindings. Changed from `execute_sparql_update` (handcrafted DELETE DATA) to `remove_rdf_quads_batch` (proper 4-tuple quads with RDFLib objects). Added `_sparql_binding_to_rdflib` import.

### Fix 2: `kgentity_delete_impl.py` — `delete_entity_graph` (High Priority)

**Problem**: Same as Fix 1 but for entity graph deletion. Extracted `(s, p, o_value, o_type)` 4-tuples, then converted to 5-tuples `(s, p, o, graph, o_type)` for `remove_rdf_quads_batch`. The 5-tuple path through `_remove_quads_from_fuseki` also formatted literals without datatype/language.

**Fix**: Replaced triple extraction with `_sparql_binding_to_rdflib` reconstruction, producing standard 4-tuples `(s, p, o_rdflib, graph_uri)` that the dual-write coordinator handles correctly for both Fuseki and PostgreSQL.

### Fix 3: `kgrelations_endpoint.py` — `_update/_upsert_relations_in_space` (Medium Priority)

**Problem**: Used separate `execute_sparql_update` (DELETE WHERE) then `add_rdf_quads_batch` (INSERT) — not atomic. If DELETE succeeds but INSERT fails, data is lost.

**Fix**:
- Added `_get_backend_adapter()` helper to wrap raw `db_space_impl` with `FusekiPostgreSQLBackendAdapter`, consistent with kgframes/kgentities endpoints.
- Refactored `_update_relations_in_space` to: (1) query existing triples with `_sparql_binding_to_rdflib` for delete quads, (2) build insert quads from `to_rdf()` preserving RDFLib objects, (3) use atomic `update_quads`.
- Refactored `_upsert_relations_in_space` with same pattern — atomic `update_quads` handles both create (empty delete_quads) and update cases.
- Refactored `_store_relations_in_space` to use the adapter for consistency.

### Fix 4: `triples_endpoint.py` — `_handle_delete_jsonld` (Low Priority)

**Problem**: `str(o)` on quads from `_jsonld_to_quads` (which correctly returns RDFLib objects). Stripped datatype/language before passing to `remove_rdf_quads_batch`.

**Fix**: Changed `str(o)` to `o` in quad tuple construction, preserving RDFLib Literal objects for downstream formatters.

### Files Changed

| File | Methods Fixed |
|---|---|
| `kgentity_delete_impl.py` | `delete_entity`, `delete_entity_graph` + added `_sparql_binding_to_rdflib` import |
| `kgrelations_endpoint.py` | `_store_relations_in_space`, `_update_relations_in_space`, `_upsert_relations_in_space` + added `_get_backend_adapter` helper |
| `triples_endpoint.py` | `_handle_delete_jsonld` |

---

## Test Verification

**Runner**: `vitalgraph_client_test/test_datatype_preservation.py`
**Case**: `vitalgraph_client_test/datatypes/case_datatype_preservation.py`
**Space**: `dt_test` / **Graph**: `urn:dt_test`

**Result: 21/21 passed**

### Entity Graph Tests (Tests 1–9) — Fixes 1 & 2

| # | Test | Verifies |
|---|---|---|
| 1 | Create entity graph with typed values (text, int, datetime) | Frame/slot create path preserves RDFLib objects |
| 2 | Verify typed values survive round-trip | Datatype preservation on retrieval |
| 3 | Update entity graph with different typed values | `kgentity_update_impl` atomic `update_quads` |
| 4 | Verify updated values — no stale data | Old typed literals fully replaced |
| 5 | No triple accumulation after update | Exactly 1 of each slot type |
| 6 | Create second entity for delete tests | Setup |
| 7 | Delete single entity (typed literals must match) | Fix 1: `delete_entity` with `_sparql_binding_to_rdflib` |
| 8 | Delete entity graph (all related objects) | Fix 2: `delete_entity_graph` with RDFLib 4-tuples |
| 9 | Verify entity graph fully deleted — no orphans | Confirms typed literal DELETE matched in Fuseki |

### KGRelations Tests (Tests 10–14) — Fix 3

| # | Test | Verifies |
|---|---|---|
| 10 | Create entities + relation | Relation create via wrapped backend adapter |
| 11 | Update relation | Atomic `update_quads` (was separate DELETE + INSERT) |
| 12 | Upsert relation | Atomic `update_quads` for existing relation |
| 13 | Verify relation values after upsert | Latest values present, no stale data |
| 14 | Delete relation + entities cleanup | Relation delete works correctly |

### KGTypes Tests (Tests 15–17) — kgtypes_update_impl

| # | Test | Verifies |
|---|---|---|
| 15 | Create KGType | Type creation path |
| 16 | Update KGType | `kgtypes_update_impl` datatype preservation in update quads |
| 17 | Delete KGType | Type deletion cleanup |

### Triples Tests (Tests 18–21) — Fix 4

| # | Test | Verifies |
|---|---|---|
| 18 | Add triples via JSON-LD (JsonLdObject) | Triples insert path |
| 19 | Verify triples exist for subject | Round-trip confirmation |
| 20 | Delete triples via JSON-LD body | Fix 4: `_handle_delete_jsonld` preserves RDFLib `o` (was `str(o)`) |
| 21 | Verify triples deleted — no orphans | Typed literal DELETE matched correctly |
