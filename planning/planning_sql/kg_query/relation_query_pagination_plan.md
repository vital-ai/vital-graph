# Relation Query Pagination Fix

## Status: Complete

**Date**: 2026-04-28 (pagination), 2026-04-29 (count_only)

---

## Problem Statement

The `relation` query type (`query_type="relation"`) in the KG query endpoint
fetches **all** matching connections from the triplestore, then paginates the
results in Python using list slicing.  This is incorrect for two reasons:

1. **Performance** — For a graph with thousands of relation edges, every
   paginated request transfers and deserialises the entire result set.  Only
   `page_size` rows are actually returned to the client.
2. **count_only support** — The Phase 7 `count_only` flag requires a
   separate count query that avoids executing the data query.  With
   in-memory pagination there is no separate count query to call.

All other query types already paginate at the SPARQL level:

| Query type | SPARQL builder | LIMIT/OFFSET | Separate COUNT query |
|------------|---------------|-------------|---------------------|
| `entity` | `KGQueryCriteriaBuilder.build_entity_query_sparql()` | ✅ | ✅ `build_entity_count_query_sparql()` |
| `frame_query` | `KGQueryCriteriaBuilder.build_frame_query_sparql()` | ✅ | ✅ `_build_frame_count_query()` |
| `frame` (legacy) | delegates to `build_entity_query_sparql()` | ✅ | ✅ `build_entity_count_query_sparql()` |
| **`relation`** | `KGConnectionQueryBuilder.build_relation_query()` | ❌ | ❌ |

---

## Current Implementation

### Builder: `kg_connection_query_builder.py`

`build_relation_query()` (line 32) generates a query shaped like:

```sparql
SELECT DISTINCT ?source_entity ?destination_entity ?relation_edge ?relation_type
WHERE {
    GRAPH <graph_id> {
        <source patterns>
        <relation patterns>
        <destination patterns>
        <filter clause>
        <sort patterns>
    }
}
ORDER BY ?source_entity ?destination_entity
```

**No LIMIT/OFFSET** — the query returns every matching row.

The builder also has `build_frame_query()` (line 89) for frame-based
connections, which has the same problem — no LIMIT/OFFSET.  However the
legacy `frame` query type in the endpoint does not use this method
directly (it delegates to `build_entity_query_sparql` instead), so the
frame connection builder is effectively unused for paginated results
today.

### Endpoint: `kgquery_endpoint.py`

`_execute_relation_query()` (line 165):

```python
# Execute SPARQL query — fetches ALL rows
results = await backend.execute_sparql_query(space_id, sparql_query)

# Convert ALL results to RelationConnection objects
connections = []
for result in results["results"]["bindings"]:
    connections.append(RelationConnection(...))

# Apply pagination in Python
total_count = len(connections)
start_idx = query_request.offset
end_idx = start_idx + query_request.page_size
paginated_connections = connections[start_idx:end_idx]
```

---

## Root Cause

`build_relation_query()` does not accept `page_size`/`offset` parameters
and does not emit LIMIT/OFFSET clauses.  There is no companion count
query method.  The endpoint compensates by doing pagination in Python.

---

## Fix

### 1. Add LIMIT/OFFSET to `build_relation_query()`

Add `page_size: int` and `offset: int` parameters and append
`LIMIT {page_size} OFFSET {offset}` after the ORDER BY clause.

```python
def build_relation_query(self, criteria: KGQueryCriteria, graph_id: str,
                         page_size: int = 100, offset: int = 0,
                         sort_patterns=None, sort_select_vars=None,
                         order_by_clause=None) -> str:
    ...
    query = f"""
    {self.prefixes}
    {select_clause}
    WHERE {{
        GRAPH <{graph_id}> {{
            {where_clause}
        }}
    }}
    {effective_order_by}
    LIMIT {page_size}
    OFFSET {offset}
    """
    return query.strip()
```

### 2. Add `build_relation_count_query()`

New method that wraps the same WHERE clause in a
`SELECT (COUNT(*) AS ?count)` query (no LIMIT/OFFSET):

```python
def build_relation_count_query(self, criteria: KGQueryCriteria, graph_id: str,
                               sort_patterns: Optional[List[str]] = None) -> str:
    """Build COUNT query for relation connections.

    Uses the same WHERE clause as build_relation_query() — including
    sort join patterns — so the count is consistent with the paginated
    data query.  (Sort join patterns act as inner joins; entities/slots
    lacking the sort property are excluded from data results, so the
    count must exclude them too.  Same rationale as
    build_entity_count_query_sparql.)
    """
    where_clause = self._build_relation_where_clause(criteria)

    # Include sort patterns so count matches data query
    sort_extra = ""
    if sort_patterns:
        sort_extra = " " + " ".join(sort_patterns)

    # Subquery approach: wrap SELECT DISTINCT inside COUNT(*)
    # to avoid non-standard COUNT(DISTINCT *).
    query = f"""
    {self.prefixes}
    SELECT (COUNT(*) AS ?count) WHERE {{
        SELECT DISTINCT ?source_entity ?destination_entity ?relation_edge ?relation_type
        WHERE {{
            GRAPH <{graph_id}> {{
                {where_clause}{sort_extra}
            }}
        }}
    }}
    """
    return query.strip()
```

**Count query includes sort patterns** — matching the pattern in
`build_entity_count_query_sparql()`.  Sort join patterns act as inner
joins; without them, the count would overcount relative to the data
query when sorting is active.

**Subquery COUNT pattern** — wraps `SELECT DISTINCT ...` inside
`SELECT (COUNT(*) AS ?count) WHERE { ... }` rather than using
non-standard `COUNT(DISTINCT *)`.  This is valid SPARQL 1.1 and the
Jena sidecar / SPARQL-to-SQL backend handles it correctly.

### 3. Refactor `_build_relation_where_clause()`

Extract the shared WHERE clause construction from `build_relation_query()`
into a private `_build_relation_where_clause()` method, so both the data
query and the count query share the same logic (same pattern as
`_build_entity_where_clause()` in `kg_query_builder.py`).

### 4. Update `_execute_relation_query()` in `kgquery_endpoint.py`

Replace in-memory pagination with the data+count query pattern used by
entity and frame queries:

```python
async def _execute_relation_query(self, backend, space_id, graph_id, query_request):
    # Build queries WITH LIMIT/OFFSET
    sparql_query = self.connection_query_builder.build_relation_query(
        query_request.criteria, graph_id,
        page_size=query_request.page_size,
        offset=query_request.offset,
        sort_patterns=sort_patterns,
        sort_select_vars=sort_select_vars,
        order_by_clause=order_by_clause,
    )
    count_query = self.connection_query_builder.build_relation_count_query(
        query_request.criteria, graph_id,
        sort_patterns=sort_patterns,
    )

    # Count-first short-circuit (same pattern as entity query)
    if query_request.offset > 0:
        count_results = await backend.execute_sparql_query(space_id, count_query)
        total_count = self._extract_total_count(count_results)
        if query_request.offset >= total_count:
            return KGQueryResponse(
                query_type="relation",
                relation_connections=[],
                total_count=total_count, ...
            )
        results = await backend.execute_sparql_query(space_id, sparql_query)
    else:
        results, count_results = await asyncio.gather(
            backend.execute_sparql_query(space_id, sparql_query),
            backend.execute_sparql_query(space_id, count_query),
        )
        total_count = self._extract_total_count(count_results)

    # Convert results — these are already the correct page
    connections = []
    for result in results["results"]["bindings"]:
        connections.append(RelationConnection(...))

    return KGQueryResponse(
        query_type="relation",
        relation_connections=connections,
        total_count=total_count, ...
    )
```

---

## Implementation Steps

| Step | File | Change | Status |
|------|------|--------|--------|
| R1 | `kg_connection_query_builder.py` | Extract `_build_relation_where_clause()` from `build_relation_query()` | ✅ Done |
| R2 | `kg_connection_query_builder.py` | Add `page_size`/`offset` params to `build_relation_query()`, emit LIMIT/OFFSET | ✅ Done |
| R3 | `kg_connection_query_builder.py` | Add `build_relation_count_query()` using subquery pattern (includes sort patterns) | ✅ Done |
| R4 | `kgquery_endpoint.py` | Refactor `_execute_relation_query()`: use data+count queries, remove in-memory pagination | ✅ Done |
| R5 | `kgquery_endpoint.py` | Add count-first short-circuit and `asyncio.gather` concurrency | ✅ Done |

---

## Testing

| Test | Description | Status |
|------|-------------|--------|
| Relation page_size=5 offset=0 | Returns ≤ 5 connections, total_count is full set | ✅ Verified |
| Relation offset beyond total | Returns empty connections, correct total_count | ✅ Verified |
| Relation count matches full | total_count with page_size=5 == total_count with page_size=100 | ✅ Verified |
| Relation sort + pagination | Sorted results are consistent across pages | ✅ Verified |
| Relation count_only | (Phase 7) count_only=true returns total_count, empty connections | ✅ Verified |
| Large relation set | Verify SPARQL-level pagination avoids full result transfer | Not yet implemented (perf benchmark) |
| Existing relation tests | All current relation query tests continue to pass | ✅ Verified |

**Verified 2026-04-29**:
- `test_multiple_organizations_crud.py`: 102/102 passed (KGQuery Relation-Based Queries 10/10)
- `test_kgentities_endpoint.py`: 54/54 passed
- `count_only` implemented in Phase 7 (model + all 4 query types + client methods)

---

## Design Notes

### DISTINCT and deduplication

The data query uses `SELECT DISTINCT` over the 4-tuple
`(?source_entity, ?destination_entity, ?relation_edge, ?relation_type)`.
With the current AND-only criteria model, duplicates cannot arise:

- **Outgoing / Incoming**: Each physical edge binds to exactly one tuple.
- **Bidirectional (UNION)**: Each edge appears in at most one UNION arm
  with a given `(source, destination)` orientation.  The only case where
  both UNION arms produce the same 4-tuple is a self-loop (A→A), which
  is eliminated by `exclude_self_connections=True` (the default).
- **Sort variables**: Sort vars are *not* in the DISTINCT projection
  (the SELECT projects only the 4 core vars plus sort vars for ORDER BY,
  but DISTINCT applies to the 4 core vars).  A given connection resolves
  to at most one sort slot value via the join path, so sort vars do not
  fan out duplicates.  (Multi-valued sort slots are a general sort
  correctness concern, not specific to pagination.)

DISTINCT is therefore a safety net for the current criteria model rather
than a deduplication requirement.  If OR-based criteria are added in the
future, this analysis should be revisited.

### Subquery COUNT and the SPARQL-to-SQL backend

The count query uses a nested `SELECT DISTINCT ... ` inside
`SELECT (COUNT(*) AS ?count) WHERE { ... }`.  This is valid SPARQL 1.1.
The Jena sidecar supports all valid SPARQL, so correctness is not a
concern.  Performance of the compiled SQL should be profiled on a real
dataset with a meaningful number of relations to verify LIMIT/OFFSET
push-down and COUNT subquery efficiency.

---

## Risks

- **SQL push-down performance** — LIMIT/OFFSET and subquery COUNT are
  standard, but the compiled SQL may not push LIMIT into the join plan
  on complex UNION (bidirectional) queries.  Profile on real data to
  confirm the performance benefit.
- **Sort stability** — The default `ORDER BY ?source_entity ?destination_entity`
  should provide stable pagination, but verify that DISTINCT + ORDER BY +
  LIMIT/OFFSET produces consistent pages.
- **Multi-valued sort slots** — If a sort slot has multiple values, the
  join fans out, producing more rows than expected.  This is a general
  sort correctness issue (not specific to pagination) and is acceptable
  for now given the current data model.

---

## Relationship to Other Plans

- **Phase 7 (count_only)** in `kg_query_sorting_plan.md` — Decision 22
  notes that `count_only` on relation queries requires this fix to
  provide a genuine performance benefit.
- **Relation query sorting** — Sorting is already wired through
  (`sort_patterns`, `sort_select_vars`, `order_by_clause` passed to
  `build_relation_query`).  LIMIT/OFFSET must come after ORDER BY so
  sort + pagination work correctly together.
