# SPARQL-to-SQL Datatype Loss in Quad-Level Operations

## Status: FULLY FIXED — all write paths + SPARQL UPDATE pipeline fixed

**Date**: 2026-04-29  |  **Updated**: 2026-04-30  |  **Verified**: 110/110 multi-org + 12/12 kgframes + 60/60 kgentities + 35/35 kgqueries

---

## Problem Statement

The SPARQL-to-SQL pipeline can **lose datatype information** on literal values
at some point between SQL execution and RDFLib object reconstruction.  This
causes any downstream operation that reconstructs RDFLib objects from SPARQL
bindings and then generates UUID-based quad identifiers to **silently fail** —
the generated UUID does not match the stored quad's UUID, so the DELETE misses.

> **Note**: An earlier version of this document attributed the loss to UNION
> queries specifically.  Code review of `emit_union.py` shows that the UNION
> handler correctly propagates `__datatype` via `remap_columns` /
> `null_companions` over `COMPANION_SUFFIXES`.  The actual point of loss is
> still under investigation (see "Candidate Root Causes" below).

### Observed symptom

`hasObjectModificationDateTime` accumulated **duplicate values** on the
`TechCorp Industries` entity after multiple updates.  Each update was supposed
to DELETE the old datetime triple and INSERT a new one, but the DELETE never
matched, so old values persisted.  When `list_kgentities` tried to deserialize
the entity, it found a list of 3 datetime values for a single-valued property
and threw:

```
TypeError: Unsupported type in value
  ['2026-04-29T22:58:37.886191+00:00',
   datetime.datetime(2026, 4, 29, 22, 58, 36, 823353, tzinfo=...),
   '2026-04-29T22:58:37.699852+00:00']
  for datetime property: list
```

This broke the "Delete Organization Entities" test because `list_kgentities`
returned `total_count=0` (the error was caught and an empty response returned).

---

## Root Cause Chain

### 1. `_rows_to_sparql_bindings()` converts SQL rows → SPARQL JSON bindings

`sparql_sql_space_impl.py` line ~1344:

```python
entry = {
    'type': type_map.get(term_type, 'literal'),
    'value': str(val),
}
datatype = row.get(f'{sql_name}__datatype')
if datatype and term_type == 'L':
    entry['datatype'] = str(datatype)
```

If the SQL pipeline fails to propagate `__datatype` columns through UNION or
subquery boundaries, the `datatype` key is **absent** from the binding dict.

### 2. `_sparql_binding_to_rdflib()` reconstructs Literal without datatype

`kgentity_frame_create_impl.py` line ~52:

```python
datatype = binding.get('datatype')
if datatype:
    return Literal(value, datatype=URIRef(datatype))
else:
    return Literal(value)          # ← plain string, no xsd:dateTime
```

When `datatype` is missing, the reconstructed Literal is a plain `xsd:string`
instead of `xsd:dateTime`.

### 3. `remove_rdf_quads_batch_bulk()` generates a different UUID

`sparql_sql_space_impl.py` line ~1100:

```python
o_dt = dt_map.get(str(o.datatype)) if isinstance(o, Literal) and o.datatype else None
o_uuid = _generate_term_uuid(o_text, o_type, o_lang, o_dt)
```

The UUID is computed from `(text, type, lang, datatype_id)`.  The original
quad was stored with `datatype_id=<xsd:dateTime id>`, but the reconstructed
Literal has `o.datatype=None` → `o_dt=None` → **different UUID** → DELETE
does not match any row.

### 4. Old triple persists; new INSERT adds a second value

The update_entity flow does `DELETE old quads` then `INSERT new quads`.  Since
the DELETE misses, the old triple remains.  After N updates there are N+1
datetime values for a single-valued property.

---

## Scope of the Problem

This is **not limited to `hasObjectModificationDateTime`**.  Any operation
that:

1. Queries existing quads via SPARQL (through the SQL pipeline)
2. Reconstructs RDFLib objects from the bindings
3. Feeds those objects into `remove_rdf_quads_batch_bulk()` for deletion

will silently fail to delete quads whose object is a typed literal, **if** the
SPARQL query's SQL compilation drops the `__datatype` column.

### Known affected code paths

| Code path | Method | Risk |
|-----------|--------|------|
| Entity update | `KGEntityUpdateProcessor._build_delete_quads_for_entity()` | **High** — triggered on every entity update via the old `update_quads` path |
| Frame update | `KGEntityFrameUpdateProcessor._build_delete_quads_for_frame()` | **High** — same pattern for frame-level updates |
| Any future quad-level delete that round-trips through SPARQL | | **Medium** — any new code using the same pattern will inherit the bug |

### Root Cause Investigation — ALL CANDIDATES ELIMINATED (2026-04-30)

Thorough code review and **live database testing** against the V2 pipeline
confirmed that all three original candidates are **not the cause**.  The
pipeline correctly propagates `__datatype` end-to-end.

#### Candidate 1: BGP `dt_case_sql` defaults to `"NULL"` — ❌ ELIMINATED

`emit_bgp.py:166` **always** passes `dt_case_sql=ctx.dt_case_expr(t_alias)`.
`dt_case_expr()` builds `CASE t.datatype_id WHEN {id} THEN '{uri}' ... END`
from the `datatype_cache`, which is loaded from `{space}_datatype` at
generation time.  Live test on `acme_kg` (20 datatype entries) confirms
the CASE expression resolves correctly.

#### Candidate 2: `str(val)` datetime format mismatch — ❌ ELIMINATED

The value column comes from `t.term_text` (VARCHAR in the term table).
PostgreSQL returns this as a Python `str`, so `str(str)` is a no-op.  The
`__dt` typed lane (`CAST(term_text AS TIMESTAMP)`) is a **separate column**
that `_rows_to_sparql_bindings` never reads — it only reads `var`, not
`var__dt`.

#### Candidate 3: `datatype_id` vs URI string — ❌ ELIMINATED

`dt_case_expr()` resolves `datatype_id → URI string` at the SQL level.
Live test confirms the `__datatype` column contains the full URI string:
```
row[0]: value='0'  __type='L'  __datatype='http://www.w3.org/2001/XMLSchema#integer'
binding[0]: has_datatype=True  dt=http://www.w3.org/2001/XMLSchema#integer
```

#### UNION handler — ❌ ELIMINATED (earlier)

`emit_union.py` uses `remap_columns`/`null_companions`, both iterating
`COMPANION_SUFFIXES` which includes `__datatype`.

### Actual Root Cause: `emit_update.py` UUID / datatype_id mismatch (2026-04-30)

The V2 SELECT pipeline correctly propagates `__datatype` (confirmed by live
testing).  The bug is in the **UPDATE** pipeline — specifically in
`emit_update.py`, which is used by `touch_entity_modification_time()`.

#### Two problems (BOTH FIXED — see below)

1. **`_term_upsert()` (line 181)** ~~uses `gen_random_uuid()` and does not
   set `datatype_id`~~  **FIXED** — Now uses `_generate_term_uuid()` with
   deterministic UUID v5 and passes `datatype_id`.

2. **`_term_uuid_subquery()` (line 201)** ~~looks up terms by `term_text +
   term_type` only~~  **FIXED** — Now computes deterministic UUID directly
   when `datatype_id` is known or `ttype != 'L'`.  Falls back to text+type
   lookup only for plain untyped literals.

#### Chain of causation

```
1. Entity CREATE via add_rdf_quads_batch_bulk
   → dateTime term stored with deterministic UUID v5(text, L, datatype:9)
   → quad.object_uuid = that deterministic UUID

2. touch_entity_modification_time fires (on frame write)
   → SPARQL DELETE/INSERT WHERE via emit_update.py
   → DELETE: finds ?old_mod by text lookup → gets deterministic UUID → works
   → INSERT: _term_upsert creates NEW term with gen_random_uuid(), datatype_id=NULL
   → quad.object_uuid = random UUID

3. Entity UPDATE via old update_quads path
   → Queries quads via SPARQL SELECT → gets term text
   → remove_rdf_quads_batch_bulk → _generate_term_uuid(text, L, datatype:9)
   → deterministic UUID ≠ random UUID → DELETE fails silently
   → New quads inserted → old quads remain → ACCUMULATION
```

#### Verified by live test

- All 20 existing dateTime terms match deterministic UUID v5 with `datatype_id=9`
- `_term_upsert` would create a new term with `gen_random_uuid()` and `datatype_id=NULL`
- `_generate_term_uuid` with `datatype_id=None` produces a *different* UUID than
  with `datatype_id=9` for the same text

#### Additional finding: Backfill task — RESOLVED

~~`BackfillServerPropertiesTask` is never imported or started from
`vitalgraphapp_impl.py`.~~  **RESOLVED** — The backfill task is now wired up
in `vitalgraphapp_impl.py` (lines 466-477): imported, instantiated with
pool + space_manager, started at startup, and stopped at shutdown.

#### Fix status

1. ✅ **`_term_upsert`** — Now uses deterministic UUID v5 and sets `datatype_id`.
2. ✅ **`_term_uuid_subquery`** — Now uses deterministic UUID when `datatype_id`
   is known.
3. ✅ **`BackfillServerPropertiesTask`** — Wired up in service startup.
4. ✅ The subject-level delete fix remains correct as a structural improvement.
5. ✅ **Step 3b variable upsert** — Now uses `vitalgraph_term_uuid()` SQL
   function with `lang` and `datatype_id` from companion binding columns
   instead of `gen_random_uuid()`.
6. ✅ **`vitalgraph_term_uuid()` SQL function** — Deterministic UUID v5
   function created in PostgreSQL using `pgcrypto` extension.  Matches
   Python `_generate_term_uuid()` exactly (verified via test script).
   Auto-created via `vitalgraphdb init` (`sparql_sql_admin.py`).
7. ✅ **`pgcrypto`** — Installed on prod RDS (`acme-postgres-prod`)
   and local (`sparql_sql_graph`).
8. ✅ **All write paths migrated** — Every `update_quads()` caller that
   performed quad-level delete has been migrated to `update_subjects_graph()`
   (subject-level delete via direct SQL).  See "Write Path Migration" below.
9. ✅ **`vitalgraph_term_uuid()` signature** — Changed `p_datatype_id`
   from `integer` to `bigint` to match the `datatype_id` column type in
   `{space}_datatype` tables.  Applied to local + prod RDS.
10. ✅ **OPTIONAL-only DELETE no-op bug** — `_delete_from_bindings()` in
    `emit_update.py` was skipping the entire DELETE when a template
    variable (e.g. `?old_mod`) wasn't in `var_map`.  This happened because
    the V2 generator doesn't project OPTIONAL-only variables.  Fixed by
    omitting the unbound variable's condition instead of skipping the
    DELETE — correctly deletes all quads matching the constant parts
    (subject, predicate, graph).
11. ✅ **`FusekiPostgreSQLBackendAdapter` removed from kgframes** —
    `kgframes_endpoint.py` was hardcoding `FusekiPostgreSQLBackendAdapter`
    instead of using `create_backend_adapter()`.  This routed to a stale
    adapter whose `update_quads()` relied on a non-existent
    `dual_write_coordinator`.  Replaced all usages with
    `create_backend_adapter()` which routes to `SparqlSQLBackendAdapter`.
    Also wrapped raw `get_db_space_impl()` calls in `_create_frame_slots`,
    `_update_frame_slots`, and `_delete_frame_slots` with the adapter.

---

## Fix Applied (2026-04-29)

### Immediate fix: Subject-level delete bypasses SPARQL entirely

Added `SparqlSQLBackendAdapter.update_entity_graph()` in
`kg_backend_utils.py` which:

1. Finds all subjects belonging to an entity graph via a direct SQL query on
   `hasKGGraphURI`.
2. Deletes **all quads** for those subjects (by `subject_uuid` + `context_uuid`)
   — no object UUID matching needed.
3. Inserts the new quads.
4. All within a single transaction.

Modified `KGEntityUpdateProcessor.update_entity()` to use this method instead
of the old `_build_delete_quads_for_entity()` + `update_quads()` path.

### Listing: multi-value accumulation (first-value guard removed)

`kgentity_list_impl.py` `_bindings_to_graph_objects()` now accumulates
multiple values per predicate, including for annotation predicates that
legitimately have multiple values (e.g. `rdfs:label` with different
language tags):

```python
if p in props:
    existing = props[p]
    if isinstance(existing, list):
        existing.append(value)
    else:
        props[p] = [existing, value]
else:
    props[p] = value
```

The original first-value-only guard (`if p not in props`) was removed
because properties and annotations can legitimately have multiple values.
VitalSigns' `from_property_maps()` handles multi-value properties
correctly — single-valued domain properties take the last value,
list-valued properties accumulate, and annotation predicates always
support multi-value.  The underlying data duplication bug is addressed
by the subject-level delete fix, not by suppressing values at read time.

> See also: `annotation_integration_plan.md` — annotation read-path
> changes (2026-04-30) added language tag preservation in the same method.

---

## Write Path Migration (2026-04-30)

All write paths that previously used the vulnerable `update_quads()` →
`remove_rdf_quads_batch_bulk()` pattern have been migrated to use
`update_subjects_graph()`, which performs subject-level delete via direct
SQL (`DELETE FROM rdf_quad WHERE subject_uuid = ANY($1) AND context_uuid = $2`)
followed by insert — all in a single transaction.  No SPARQL pipeline, no
UUID matching fragility.

| File | Methods migrated |
|------|------------------|
| `kg_backend_utils.py` | New: `update_subjects_graph()` |
| `kgentity_frame_create_impl.py` | `execute_frame_creation()`, `execute_atomic_frame_update()` |
| `kgslot_update_impl.py` | `update_slot()` |
| `kgtypes_update_impl.py` | `update_kgtype()` |
| `kgtypes_delete_impl.py` | `delete_kgtype()`, `delete_kgtypes_batch()` |
| `kgrelations_endpoint.py` | `_update_relations_in_space()`, `_upsert_relations_in_space()` |
| `kgframes_endpoint.py` | `_store_frames_in_backend()`, `_update_frame_slots_in_backend()`, `_store_frame_slots_in_backend()` |

All methods fall back to the old `update_quads()` path for backends that
don't have `update_subjects_graph` (e.g. legacy Fuseki+PostgreSQL).

Remaining `update_quads()` callers are safe:
- **CREATE-only** (`kgtypes_create_impl.py`) — empty `delete_quads`
- **Already has safe path** (`kgentity_update_impl.py`) — primary path uses `update_entity_graph()`

---

## Remaining Risks & Recommended Actions

### ~~1. Frame update path still uses the vulnerable pattern~~ — FIXED

All frame, slot, type, and relation write paths now use `update_subjects_graph()`.

### 2. Existing data may have duplicate triples

Any entity that was updated before the fix was applied may have accumulated
duplicate typed-literal triples.  These won't cause errors now (due to the
defensive listing fix), but they waste storage and could confuse downstream
consumers.

**Action**: Write a diagnostic query to find entities with duplicate values
for single-valued properties, and a repair script to deduplicate them.

### 3. ~~Root cause in the SQL pipeline is unfixed~~ — FULLY RESOLVED

All parts of the `emit_update.py` pipeline are now fixed:
- `_term_upsert()` — deterministic UUID v5 with `datatype_id`
- `_term_uuid_subquery()` — deterministic UUID when datatype known
- **Step 3b variable upsert** — uses `vitalgraph_term_uuid()` SQL function
  with `lang` and `datatype_id` from binding companion columns
- **`_delete_from_bindings()`** — OPTIONAL-only variables no longer cause
  the entire DELETE to be skipped; unbound variable conditions are omitted
  instead, allowing constant-part matching

### 4. `remove_rdf_quads_batch_bulk` is fragile by design

The method requires exact 4-tuple UUID matching `(subject, predicate, object,
graph)`.  Any discrepancy in the reconstructed object (datatype, timezone
format, microsecond precision, etc.) causes a silent miss.

**Action**: Consider adding a fallback mode that matches on
`(subject_uuid, predicate_uuid, context_uuid)` only — i.e., "delete all
values for this subject+predicate in this graph" — for use cases where the
caller knows the property is single-valued.

### 5. `str(val)` for datetime may vary

In `_rows_to_sparql_bindings()`, `str(val)` is used to convert the Python
value to a string.  For `datetime` objects, `str()` produces
`2026-04-29 22:58:37.886191+00:00` (note the space, not a `T`), while the
original stored value was ISO 8601 `2026-04-29T22:58:37.886191+00:00`.
This is a **second** source of UUID mismatch, independent of the datatype
loss.

**Action**: Normalize datetime serialization in `_rows_to_sparql_bindings()`
to always use `.isoformat()` for datetime objects.

---

## Diagnostic Queries

### Find entities with duplicate single-valued properties

```sparql
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
SELECT ?s ?p (COUNT(?o) AS ?cnt) WHERE {
    GRAPH <{graph_id}> {
        { ?s vital-core:vitaltype haley:KGEntity . }
        UNION { ?s vital-core:vitaltype haley:KGProductEntity . }
        ?s ?p ?o .
    }
}
GROUP BY ?s ?p
HAVING (COUNT(?o) > 1)
ORDER BY DESC(?cnt)
```

### Check if a specific property returns datatype in SPARQL results

```sparql
SELECT ?s ?o WHERE {
    GRAPH <{graph_id}> {
        ?s <http://vital.ai/ontology/vital-core#hasObjectModificationDateTime> ?o .
    }
} LIMIT 5
```

Inspect the binding dict — if `datatype` key is missing on the `?o` binding,
the pipeline is dropping it.

---

## Files Involved

| File | Role | Status |
|------|------|--------|
| `vitalgraph/db/sparql_sql/emit_update.py` | `_term_upsert()`, `_term_uuid_subquery()`, Step 3b, `_delete_from_bindings()` | **Fixed** — deterministic UUID v5 + OPTIONAL DELETE fix |
| `vitalgraph/db/sparql_sql/sparql_sql_admin.py` | `pgcrypto` extension + `vitalgraph_term_uuid()` DDL | **Added** — created via `vitalgraphdb init` |
| `sql_scripts/create_vitalgraph_term_uuid_function.sql` | SQL function for deterministic UUID v5 (`bigint` signature) | **Updated** |
| `vitalgraph/db/sparql_sql/sparql_sql_space_impl.py` | `_rows_to_sparql_bindings()`, `remove_rdf_quads_batch_bulk()`, `_generate_term_uuid()` | OK (V2 SELECT pipeline correct) |
| `vitalgraph/kg_impl/kgentity_frame_create_impl.py` | `execute_frame_creation()`, `execute_atomic_frame_update()` | **Fixed** — uses `update_subjects_graph()` |
| `vitalgraph/kg_impl/kgentity_update_impl.py` | `update_entity()` | **Fixed** — uses `update_entity_graph()` |
| `vitalgraph/kg_impl/kg_backend_utils.py` | `update_entity_graph()`, `update_subjects_graph()` (subject-level delete) | **Fixed** |
| `vitalgraph/kg_impl/kgslot_update_impl.py` | `update_slot()` | **Fixed** — uses `update_subjects_graph()` |
| `vitalgraph/kg_impl/kgtypes_update_impl.py` | `update_kgtype()` | **Fixed** — uses `update_subjects_graph()` |
| `vitalgraph/kg_impl/kgtypes_delete_impl.py` | `delete_kgtype()`, `delete_kgtypes_batch()` | **Fixed** — uses `update_subjects_graph()` |
| `vitalgraph/endpoint/kgrelations_endpoint.py` | `_update_relations_in_space()`, `_upsert_relations_in_space()` | **Fixed** — uses `update_subjects_graph()` |
| `vitalgraph/endpoint/kgframes_endpoint.py` | 3 store/update methods + slot CRUD + frame delete | **Fixed** — uses `create_backend_adapter()` → `SparqlSQLBackendAdapter` |
| `vitalgraph/kg_impl/kgentity_list_impl.py` | `_bindings_to_graph_objects()` — multi-value accumulation | **Updated** — supports annotations + multi-value |
| `vitalgraph/impl/vitalgraphapp_impl.py` | Backfill task wiring | **Fixed** |
| `vitalgraph/db/sparql_sql/generator.py` | SQL generation — metadata column propagation | OK |

---

## Relationship to Other Plans

- **`relation_query_pagination_plan.md`** — Not directly related, but the same
  SPARQL-to-SQL pipeline serves all query types.
- **`kg_query_sorting_plan.md`** Phase 7 — `count_only` was implemented
  2026-04-29; count queries are not affected since they don't reconstruct
  objects.
- **`entity_timestamp_management_plan.md`** — Server-managed timestamps like
  `objectModificationDateTime` are the most visible victims of this bug.
- **`annotation_integration_plan.md`** — The annotation read-path changes
  (2026-04-30) modified `_bindings_to_graph_objects()` to support multi-value
  accumulation and language tag preservation, replacing the first-value-only
  defensive guard.
