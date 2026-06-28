# Bug: Falsey Property Values Dropped During Storage

## Problem

When inserting KG entity graphs, properties with **falsey Python values** (`false`, `0.0`, `0`, `""`) are silently dropped and never stored in Fuseki (and potentially PostgreSQL via SPARQL UPDATE path).

**Affected value types:**
- `boolean false` → `Literal(False)` with `xsd:boolean`
- `float 0.0` → `Literal(0.0)` with `xsd:float`
- `integer 0` → `Literal(0)` with `xsd:integer`
- `empty string ""` → `Literal("")` with `xsd:string`

**Confirmed missing in production:** `hasBooleanSlotValue: false` on KGBooleanSlot and `hasCurrencySlotValue: 0.0` on KGCurrencySlot in the `lead_test` space.

## Root Cause

**Three `_format_term()` functions** use Python truthiness checks (`if not term:`) instead of `None` checks (`if term is None:`). RDFLib `Literal(False)` and `Literal(0.0)` are **falsey in Python**, so they are treated as missing/null and the triple is silently skipped.

### Bug Location 1 (PRIMARY — Fuseki INSERT path)

**File:** `vitalgraph/db/fuseki_postgresql/fuseki_dataset_manager.py`

**Line 910:**
```python
def _format_term(self, term, convert_float_to_decimal=False):
    if not term:       # ← BUG: Literal(False), Literal(0.0), Literal(0) are falsey
        return None    # ← Returns None, causing triple to be skipped
```

**Line 867 (secondary):**
```python
if subject and predicate and obj:  # ← Skips triple when obj is None from _format_term
```

This is the **primary code path** for entity graph creation. All quads go through `add_quads_to_dataset()` → `_quads_to_sparql_insert_data()` → `_format_term()`.

### Bug Location 2 (SPARQL UPDATE path)

**File:** `vitalgraph/db/fuseki_postgresql/dual_write_coordinator.py`

**Line 1245:**
```python
def _format_sparql_term(self, term):
    if not term:       # ← Same bug
        return None
```

This affects the SPARQL UPDATE execution path (used for entity updates via `execute_sparql_update()`).

### Bug Location 3 (db_ops formatting)

**File:** `vitalgraph/db/fuseki_postgresql/fuseki_postgresql_db_ops.py`

**Line 224:**
```python
def _format_sparql_term(self, term):
    if not term:       # ← Same bug
        return '""'    # ← Returns empty string literal instead of proper formatting
```

### Bug Location 4 (space_impl formatting)

**File:** `vitalgraph/db/fuseki_postgresql/fuseki_postgresql_space_impl.py`

**Line 318:**
```python
def _format_sparql_term(self, term: str) -> str:
    if not term:       # ← Same bug
        return '""'
```

## Data Flow Trace

The test script `test_falsey_values_trace.py` confirmed:

| Step | Layer | Result |
|------|-------|--------|
| 1 | VitalSigns object creation | ✅ `booleanSlotValue = False` |
| 2 | `GraphObject.to_jsonld_list()` | ✅ `"hasBooleanSlotValue": false` |
| 3 | Pydantic `model_dump(by_alias=True)` | ✅ preserved |
| 4 | JSON serialization (wire format) | ✅ preserved |
| 5 | Server-side Pydantic deserialization | ✅ preserved |
| 6 | VitalSigns `from_jsonld_list()` | ✅ `booleanSlotValue = False` |
| 7 | VitalSigns `to_rdf()` | ✅ `hasBooleanSlotValue "false"^^xsd:boolean` |
| 8 | Full end-to-end (client → server → Fuseki) | ❌ **MISSING** |
| 9 | Fuseki SPARQL query | ❌ `hasBooleanSlotValue` triple not stored |

The value survives the entire pipeline until `_format_term()` in `fuseki_dataset_manager.py` drops it.

## Fix

### Fix 1: `fuseki_dataset_manager.py` — `_format_term()` (line 910)

```python
# BEFORE (buggy):
if not term:
    return None

# AFTER (fixed):
if term is None:
    return None
```

### Fix 2: `fuseki_dataset_manager.py` — `_quads_to_sparql_insert_data()` (line 867)

```python
# BEFORE (buggy):
if subject and predicate and obj:

# AFTER (fixed):
if subject is not None and predicate is not None and obj is not None:
```

### Fix 3: `dual_write_coordinator.py` — `_format_sparql_term()` (line 1245)

```python
# BEFORE (buggy):
if not term:
    return None

# AFTER (fixed):
if term is None:
    return None
```

### Fix 4: `fuseki_postgresql_db_ops.py` — `_format_sparql_term()` (line 224)

```python
# BEFORE (buggy):
if not term:
    return '""'

# AFTER (fixed):
if term is None:
    return '""'
```

### Fix 5: `fuseki_postgresql_space_impl.py` — `_format_sparql_term()` (line 318)

```python
# BEFORE (buggy):
if not term:
    return '""'

# AFTER (fixed):
if term is None:
    return '""'
```

## Verification

After applying fixes:
1. Run `test_falsey_values_trace.py` — all 17 tests should pass
2. Re-ingest a lead entity graph and verify boolean/currency slots in Fuseki
3. Check PostgreSQL for the same data (may already be correct if PostgreSQL path handles RDFLib objects directly without `_format_term`)

## Impact Assessment

- **All existing data** with falsey property values is affected — those triples were silently dropped
- **Re-ingestion required** for any entity graphs that contained `false`, `0.0`, `0`, or `""` values
- The fix is minimal (single-line changes) and backward-compatible
- No risk of breaking existing truthy values

## Files to Modify

1. `vitalgraph/db/fuseki_postgresql/fuseki_dataset_manager.py` (lines 867, 910)
2. `vitalgraph/db/fuseki_postgresql/dual_write_coordinator.py` (line 1245)
3. `vitalgraph/db/fuseki_postgresql/fuseki_postgresql_db_ops.py` (line 224)
4. `vitalgraph/db/fuseki_postgresql/fuseki_postgresql_space_impl.py` (line 318)

## Test Script

`vitalgraph_client_test/test_falsey_values_trace.py` — comprehensive trace test that creates entity graph with `KGBooleanSlot(false)`, `KGCurrencySlot(0.0)`, and `KGTextSlot("hello")` control, verifying each pipeline layer.

---

## Codebase Audit: All Similar Truthiness-Check Patterns

Full audit performed to find every location in the codebase with the same class of bug.

### Category A: DEFINITE BUGS — `if not term:` on RDFLib Literal objects

These are called with RDFLib `Literal` objects which are **falsey** for `False`, `0`, `0.0`, `""`.

| # | File | Line | Function | Impact |
|---|------|------|----------|--------|
| A1 | `fuseki_dataset_manager.py` | 910 | `_format_term()` | **PRIMARY** — drops falsey Literals from Fuseki INSERT |
| A2 | `fuseki_dataset_manager.py` | 867 | `_quads_to_sparql_insert_data()` | Secondary guard `if subject and predicate and obj:` skips when A1 returns None |
| A3 | `dual_write_coordinator.py` | 1245 | `_format_sparql_term()` | Drops falsey Literals from Fuseki DELETE DATA and INSERT via SPARQL UPDATE path |
| A4 | `fuseki_postgresql_db_ops.py` | 224 | `_format_sparql_term()` | Returns `""` instead of properly formatting falsey Literals |
| A5 | `fuseki_postgresql_space_impl.py` | 318 | `_format_sparql_term()` | Returns `""` instead of properly formatting falsey term strings |

**Fix for all A-category:** Change `if not term:` → `if term is None:`.
**Fix for A2:** Change `if subject and predicate and obj:` → `if subject is not None and predicate is not None and obj is not None:`.

### Category B: SECONDARY — `if subject_formatted and predicate_formatted and obj_formatted:` guards

These are downstream of A-category bugs. After `_format_sparql_term()` returns `None` for a falsey term, these guards silently skip the triple. If the A-category bugs are fixed, these become safe (formatted strings like `'"false"^^<xsd:boolean>'` are always truthy). However, they should still be hardened.

| # | File | Line | Function | Context |
|---|------|------|----------|---------|
| B1 | `dual_write_coordinator.py` | 942 | `_remove_quads_from_fuseki()` | 4-tuple path: skips triple when `_format_sparql_term` returns None |
| B2 | `dual_write_coordinator.py` | 957 | `_remove_quads_from_fuseki()` | 3-tuple path: same |
| B3 | `dual_write_coordinator.py` | 1208 | `_build_delete_data_body()` | 4-tuple path: same |
| B4 | `dual_write_coordinator.py` | 1218 | `_build_delete_data_body()` | 3-tuple path: same |

**Recommended fix:** Change to `is not None` checks for defense-in-depth.

### Category C: POTENTIAL — `if subject and predicate and obj:` on SPARQL result strings

These operate on **string values** extracted from SPARQL JSON result bindings via `.get("value")`. For boolean `false`, Fuseki returns the string `"false"` which is truthy — **NOT affected**. For numeric `0.0`, Fuseki returns `"0.0"` which is truthy — **NOT affected**. Only empty string `""` would be falsey and dropped.

| # | File | Line | Function | Risk |
|---|------|------|----------|------|
| C1 | `kg_sparql_utils.py` | 285 | `extract_triples_from_results()` | Drops triples where SPARQL obj value is `""` |
| C2 | `kg_sparql_utils.py` | 293 | `extract_triples_from_results()` | Same (flat bindings path) |
| C3 | `kg_sparql_utils.py` | 310 | `extract_triples_from_results()` | Same (list path) |
| C4 | `kg_sparql_query.py` | 674 | SPARQL result processing | Drops triples where obj is `""` |
| C5 | `kgframes_endpoint.py` | 2402 | Frame triple extraction | Drops triples where obj is `""` |
| C6 | `sparql_update_parser.py` | 1417 | `_convert_results_to_triples()` | After `str()` conversion — `str(Literal(""))` = `""` is falsey |
| C7 | `fuseki_postgresql_space_impl.py` | 261 | `get_rdf_quad()` | `if obj:` skips SPARQL filter when obj is empty string |

**Recommended fix:** Change to `is not None` checks. Low priority since empty string property values are rare, but correctness matters.

### Category D: NOT BUGS — already correct or different variable types

| # | File | Line | Pattern | Why safe |
|---|------|------|---------|----------|
| D1 | `kgentity_update_impl.py` | 246 | `if subject and predicate and obj is not None:` | Already uses `is not None` ✅ |
| D2 | `kgtypes_update_impl.py` | 281 | `if subject and predicate and obj is not None:` | Already uses `is not None` ✅ |
| D3 | `kg_backend_utils.py` | 610-657 | `_build_insert_query()` | Uses `isinstance(obj, URIRef/Literal)` — no truthiness check ✅ |
| D4 | `postgresql_db_impl.py` | 884 | `if term_key and ...` | `term_key = str(term)` — `str(Literal(False))` = `"false"` is truthy. Only empty string `""` affected. |
| D5 | `postgresql_space_db_objects.py` | 184 | `if obj is None:` | Correct `is None` check ✅ |
| D6 | Various files | — | `if not triples:` | Checks on **lists**, not individual terms — empty list check is correct ✅ |
| D7 | Various SPARQL files | — | `if obj == variable` / `if obj not in ...` | Equality/membership checks, not truthiness ✅ |
| D8 | `mock_space.py` | 547 | `if object_value:` | Mock client, not production — low priority |

### Summary

| Category | Count | Severity | Action |
|----------|-------|----------|--------|
| **A: Definite bugs** | 5 | **Critical** — silently drops data | Fix immediately |
| **B: Downstream guards** | 4 | Medium — secondary to A | Harden for defense-in-depth |
| **C: String truthiness** | 7 | Low — only affects empty string `""` values | Fix for correctness |
| **D: Not bugs** | 8+ | None | No action needed |

### Positive finding

`kgentity_update_impl.py:246` and `kgtypes_update_impl.py:281` already correctly use `obj is not None`, which shows awareness of the issue — but the fix was not applied consistently to the other locations.

---

## Bug 2: Read-Path — SPARQL Result Datatypes Dropped During Reconstruction

### Problem

After fixing the write-path bug, boolean `false` was correctly stored in Fuseki as `"false"^^xsd:boolean`. However, when reading data back via the API, **all boolean values appeared as `true`**.

### Root Cause

`vitalgraph/kg_impl/kg_graph_retrieval_utils.py` — the `GraphObjectRetriever` class converts SPARQL JSON results to RDFLib triples. **All 6 methods** created `Literal(obj_value)` without the `datatype` or `lang` from the SPARQL result binding:

```python
# BEFORE (buggy):
obj = Literal(obj_value)  # Creates Literal("false") — a plain string literal

# Literal("false").toPython() → "false" (str)
# Property setter does bool("false") → True  ← WRONG
```

The SPARQL result binding contains `{"type": "literal", "value": "false", "datatype": "http://...#boolean"}` but the datatype was ignored.

### Fix

```python
# AFTER (fixed):
datatype = obj_data.get('datatype')
lang = obj_data.get('xml:lang') or obj_data.get('lang')
if lang:
    obj = Literal(obj_value, lang=lang)
elif datatype:
    obj = Literal(obj_value, datatype=URIRef(datatype))
else:
    obj = Literal(obj_value)

# Literal("false", datatype=XSD.boolean).toPython() → False (bool) ← CORRECT
```

### Affected Methods (6 instances)

| # | Method | Line |
|---|--------|------|
| 1 | `get_object_triples()` | ~143 |
| 2 | `get_entity_graph()` | ~224 |
| 3 | `get_objects_by_uris()` | ~302 |
| 4 | `get_entity_by_reference_id()` | ~374 |
| 5 | `get_entity_graph_by_reference_id()` | ~459 |
| 6 | `get_objects_paginated()` | ~595 |

### Impact

- **All typed literal values** were losing their datatype on read-back (booleans, integers, floats, dates, etc.)
- Boolean `false` → string `"false"` → `bool("false")` = `True` (most visible)
- Float `0.0` happened to survive because `float("0.0")` = `0.0` (correct by coincidence)
- This was a **pre-existing bug** masked by the write-path bug (falsey values were never stored, so they were never read back incorrectly)

---

## Complete Fix Summary

| Bug | File(s) | Fix | Tests |
|-----|---------|-----|-------|
| **Write-path**: falsey values dropped | 9 files (see Category A-C above) | `if not term:` → `if term is None:` | Steps 1-9 (17 tests) |
| **Read-path**: datatypes dropped | `kg_graph_retrieval_utils.py` (6 methods) | Preserve `datatype`/`lang` from SPARQL results in `Literal()` | Step 10 (3 tests) |

**All 20/20 tests pass** — boolean `false` and currency `0.0` are correctly stored in Fuseki, correctly returned in the server JSON-LD response, and correctly deserialized by the client.
