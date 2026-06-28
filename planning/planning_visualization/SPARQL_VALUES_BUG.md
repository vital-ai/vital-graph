# SPARQL VALUES Clause Bug in KGType Search

## Summary

The `VALUES` clause used in KGType unfiltered search queries returns **0 results**
when translated through the SPARQL-to-SQL pipeline, despite the same data being
queryable with other patterns.

## Affected Code

`vitalgraph/kg_impl/kgtypes_read_impl.py` — methods `_search_types_keyword` and
`_search_types_vg`.

## Symptom

- `search_types(query="Commerce", search_mode="keyword")` → **0 results**
- `search_types(query="Commerce", type="frame", search_mode="keyword")` → **9 results**

The only difference is that the unfiltered path uses an inline `VALUES` clause
while the filtered path uses a direct `?s vc:vitaltype <URI>` triple.

## Reproducer

```sparql
# This returns 0 results (bug):
PREFIX vc: <http://vital.ai/ontology/vital-core#>
SELECT ?s ?name ?vitaltype WHERE {
  ?s vc:vitaltype ?vt .
  VALUES ?vt {
    <http://vital.ai/ontology/haley-ai-kg#KGType>
    <http://vital.ai/ontology/haley-ai-kg#KGEntityType>
    <http://vital.ai/ontology/haley-ai-kg#KGFrameType>
    <http://vital.ai/ontology/haley-ai-kg#KGRelationType>
    <http://vital.ai/ontology/haley-ai-kg#KGSlotType>
    <http://vital.ai/ontology/haley-ai-kg#KGSlotRoleType>
  }
  ?s vc:vitaltype ?vitaltype .
  ?s vc:hasName ?name .
  FILTER(CONTAINS(LCASE(?name), "commerce"))
} LIMIT 5
```

```sparql
# This returns 5 results (correct):
PREFIX vc: <http://vital.ai/ontology/vital-core#>
SELECT ?s ?name ?vitaltype WHERE {
  ?s vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#KGFrameType> .
  ?s vc:vitaltype ?vitaltype .
  ?s vc:hasName ?name .
  FILTER(CONTAINS(LCASE(?name), "commerce"))
} LIMIT 5
```

```sparql
# This also returns results (no type constraint at all):
PREFIX vc: <http://vital.ai/ontology/vital-core#>
SELECT ?s ?name WHERE {
  ?s vc:hasName ?name .
  FILTER(CONTAINS(LCASE(?name), "commerce"))
} LIMIT 5
```

## Root Cause (Confirmed)

The bug is in `vitalgraph/db/sparql_sql/var_scope.py` —
`_collect_referenced_vars()` did not include `KIND_TABLE` (VALUES) variables
in the "referenced" set used by `compute_text_needed_vars()`.

**Failure chain:**

1. Jena parses the query into `OpJoin(OpBGP(...), OpTable(vars=[vt], ...))`.
2. The collect pass builds `PlanV2(kind=JOIN, children=[bgp, table])`.
3. `compute_text_needed_vars()` determines which BGP variables need term-table
   JOINs for text resolution. It considers a variable "referenced" if it
   appears in a PROJECT, FILTER, EXTEND, ORDER, or GROUP node.
4. **Bug:** `?vt` is not projected (`project_vars = [s, name, vitaltype]`),
   not filtered, and not ordered — so it was classified as "internal only"
   and excluded from `text_needed_vars`.
5. `emit_bgp` skips the term-table JOIN for `?vt`, producing `NULL` for its
   text column while keeping its UUID column populated.
6. `emit_join` builds the ON clause as a text equality:
   `CAST(j0.v2 AS TEXT) = CAST(j1.v5 AS TEXT)` — comparing `NULL` (BGP side)
   with the VALUES literal URI string → always NULL → **0 results**.
7. The null-tolerance wrapper `(j0.v2__uuid IS NULL OR j1.v5 IS NULL OR ...)`
   doesn't save it because `v2__uuid` IS populated (non-NULL UUID from the
   quad table), so the equality is still evaluated and fails.

## Workaround Applied

Replaced `VALUES ?vt { ... }` with `FILTER(?vitaltype IN (...))` which
the SQL emitter handles correctly:

```python
# Before (broken):
type_values = " ".join(f"<{t}>" for t in self.ALL_KGTYPE_URIS)
type_filter_clause = f'?s vc:vitaltype ?vt . VALUES ?vt {{ {type_values} }}'

# After (working):
type_in_list = ", ".join(f"<{t}>" for t in self.ALL_KGTYPE_URIS)
type_filter_clause = f'FILTER(?vitaltype IN ({type_in_list}))'
```

## Impact

- KGType search with **no type filter** was silently returning empty results
- All other query paths (filtered by type, raw SPARQL, list operations) worked

## Test Space

Validated against `framenet_kgtypes_test` space with 2,506 KGType objects.

## Fix Applied

**Production pipeline** (`vitalgraph/db/sparql_sql/var_scope.py`):

Added `KIND_TABLE` handling in `_collect_referenced_vars()` so VALUES variables
are marked as "referenced" — ensuring BGP siblings resolve their text column:

```python
if kind == KIND_TABLE and plan.values_vars:
    refs.update(plan.values_vars)
```

**Legacy pipeline** (`vitalgraph_sparql_sql/jena_sql_resolve.py`):

Fixed `_plan_vars()` to include `values_vars` so joins detect shared variables:

```python
if plan.values_vars:
    for v in plan.values_vars:
        if v not in vars:
            vars.append(v)
```

## Status

- [x] Workaround applied in `kgtypes_read_impl.py`
- [x] Root cause confirmed — `_collect_referenced_vars` missing KIND_TABLE
- [x] Fix applied in `vitalgraph/db/sparql_sql/var_scope.py`
- [x] Fix applied in `vitalgraph_sparql_sql/jena_sql_resolve.py` (legacy)
- [x] Regression tests: `test_scripts/sparql/test_values_text_needed.py` (7 tests)
- [ ] Service restart required to pick up the fix
- [ ] Workaround in `kgtypes_read_impl.py` can be reverted back to VALUES syntax

## Related Files

- `vitalgraph/db/sparql_sql/var_scope.py` — production fix location
- `vitalgraph/db/sparql_sql/emit_join.py` — JOIN ON clause logic (correct, not changed)
- `vitalgraph/db/sparql_sql/emit_bgp.py` — text_needed_vars consumer (correct, not changed)
- `vitalgraph_sparql_sql/jena_sql_resolve.py` — legacy pipeline fix
- `test_scripts/sparql/test_values_text_needed.py` — regression tests
- `test_scripts/sparql/debug_kgtype_search.py` — debug script that isolated the bug
