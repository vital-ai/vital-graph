# vg:vectorSimilarity fails when subject variable has no prior triple binding

## Summary

SPARQL queries using `BIND(vg:vectorSimilarity(?var, "text", "index") AS ?score)`
fail with a SQL type error when `?var` is not first bound by a triple pattern in
the same group. The SPARQL→SQL translator cannot resolve the UUID column for the
subject variable, producing invalid SQL.

## Symptoms

1. Server log: `Cannot resolve UUID column for ?segment`
2. SQL error: `operator does not exist: text > numeric` (from `FILTER(?score > 0.0)`)
3. Client receives: `head={'vars': []}`, `results={'bindings': []}` — silent empty result

## Reproduction

```sparql
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

-- BROKEN: BIND comes before the triple pattern
SELECT ?segment ?score ?content WHERE {
    BIND(vg:vectorSimilarity(?segment, "search text", "document_segments") AS ?score)
    FILTER(?score > 0.0)
    ?segment haley:hasKGDocumentContent ?content .
}
ORDER BY DESC(?score) LIMIT 5
```

## Workaround

Place the triple pattern **before** the `BIND(vg:vectorSimilarity(...))` so the
translator resolves `?segment` from the quad table first:

```sparql
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

-- WORKS: triple pattern establishes ?segment binding first
SELECT ?segment ?score ?content WHERE {
    ?segment haley:hasKGDocumentContent ?content .
    BIND(vg:vectorSimilarity(?segment, "search text", "document_segments") AS ?score)
    FILTER(?score > 0.0)
}
ORDER BY DESC(?score) LIMIT 5
```

## Root Cause

In `vitalgraph/db/sparql_sql/vg_functions.py`, the `_resolve_uuid_col` function
attempts to find the SQL column alias for a SPARQL variable by looking at previously
translated triple patterns. When `vg:vectorSimilarity` appears as the first pattern
in the group (before any triple pattern binds the variable), the resolver finds no
mapping and emits a WARNING, returning `None`. The downstream SQL generation then
produces a malformed query that fails with a type cast error.

### Relevant code path

1. SPARQL algebra: `Extend(BGP(...), ?score, vg:vectorSimilarity(?segment, ...))`
2. `emit_extend.py` → calls `extract_vector_args` → calls `_resolve_uuid_col(?segment)`
3. `_resolve_uuid_col` searches the alias map — finds nothing if the triple pattern
   hasn't been translated yet
4. Falls through to a broken SQL path → type error at execution

## Expected Behavior

The `vg:vectorSimilarity` function should work regardless of pattern ordering within
a BGP. Per SPARQL semantics, the order of patterns in a basic graph pattern is
irrelevant — the engine may evaluate them in any order.

## Proposed Fix

In `_resolve_uuid_col` (or the calling code in `emit_extend.py`), when the subject
variable is not yet resolved:

1. **Option A (simple)**: Look ahead in the sibling patterns for a triple pattern
   that binds the variable, and use that pattern's alias. This preserves the current
   architecture with minimal changes.

2. **Option B (robust)**: Generate the vector subquery with a correlated subquery
   that joins on the term table directly:
   ```sql
   SELECT subject_uuid, 1 - (embedding <=> $query_vec) AS score
   FROM {space}_vec_{index}
   WHERE subject_uuid IN (SELECT term_uuid FROM {space}_rdf_term WHERE term_text = ?segment_uri)
   ```
   This removes the dependency on pattern ordering entirely.

## Other Functions Affected by the Same Pattern

Every custom `vg:` function in `vg_functions.py` calls `_resolve_uuid_col` and
silently returns `None` (producing NULL or empty results) if the subject variable
is not yet registered in the TypeRegistry. All are vulnerable when the BIND
appears before the triple pattern that establishes the variable:

| Function | Line | Produces |
|----------|------|----------|
| `vector_similarity_sql` | 614 | Cosine similarity scalar subquery |
| `vector_top_k_driving_sql` | 711 | Top-K driving join subquery |
| `text_search_sql` | 816 | BM25 rank scalar subquery |
| `geo_distance_sql` | 930 | ST_Distance scalar subquery |
| `within_radius_sql` | 958 | EXISTS spatial filter |
| `within_bounds_sql` | 988 | EXISTS bounding box filter |
| `within_polygon_sql` | 1019 | EXISTS polygon filter |
| `fuzzy_match_sql` | 1062 | Fuzzy score placeholder |
| `multi_vector_similarity_sql` | 1119 | Multi-index weighted score |

The `_try_vector_driving_extend` path (line 135 in `emit_extend.py`) has a
separate call that also returns `None` → falls through to the standard path,
which then also calls `_resolve_uuid_col` and fails the same way.

### Why it works for KGQuery-generated SPARQL

The `query_connections` endpoint generates SPARQL with entity triple patterns
**before** the `BIND(vg:vectorSimilarity(...))`. The algebra tree produced by
the query builder always has the BGP (which registers variables in the
TypeRegistry) as a child of the EXTEND node. So `emit_extend` first emits the
child (which populates the TypeRegistry), then resolves the UUID column for
the BIND expression. This ordering is guaranteed by the code path in
`kgqueries_endpoint.py` → `sparql_query_builder.py`.

### Why it fails for user-authored SPARQL

When a user writes raw SPARQL like:
```sparql
SELECT ?s ?score WHERE {
    BIND(vg:vectorSimilarity(?s, "text", "idx") AS ?score)
    ?s <p> ?o .
}
```
The rdflib parser may produce an algebra where the EXTEND wraps the BGP
(correct — the BGP is the child), OR where the EXTEND is evaluated first
if the optimizer reorders. In practice, the VitalGraph optimizer's `emit_extend`
always emits the child first (line 186: `child_sql = emit(plan.child, ctx)`),
so the TypeRegistry **should** have the variable by the time `expr_to_sql` runs.

The actual failure occurs when `vg:vectorSimilarity` is the **only** pattern
(no triple pattern child at all), or when the planner puts it in a separate
EXTEND node with an empty/no child. This happens with:
```sparql
BIND(vg:vectorSimilarity(?s, "text", "idx") AS ?score)
FILTER(?score > 0.0)
?s <p> ?o .
```
...where the algebra becomes `Filter(Extend(BGP(?s <p> ?o), ?score, vg:...), ?score > 0)`.
The child BGP is emitted first, so the variable IS available. The actual bug
is triggered when the **child itself** is also an EXTEND or when pattern
ordering in the algebra differs from textual ordering in the SPARQL string.

**Key insight**: The workaround (triple before BIND) works because it ensures
the algebra's EXTEND child contains the BGP that binds the variable. The real
fix must handle the case where `_resolve_uuid_col` returns None by either:
- Deferring resolution to a later pass (after all children are emitted)
- Generating a term-table lookup subquery as a fallback

## Existing Deferred Resolution Patterns

The codebase already implements three deferred resolution mechanisms. The fix
should follow one of these patterns rather than inventing a new one.

### Pattern 1: VectorRequest — value placeholder (vg_resolve.py:32-107)

**What is deferred**: The embedding vector literal (search text → float[]).
**Mechanism**: At generation time, emit `'__VG_EMBED_12345__'::vector` as a
placeholder in the SQL string. After full SQL generation, the orchestrator
calls `resolve_vector_requests()` which vectorizes the text and does a
`sql.replace(placeholder, actual_vector_literal)`.
**Why it works**: The structural SQL (subquery shape, column references) is
fully resolved at generation time — only the constant value is deferred.

### Pattern 2: FuzzyRequest — score/filter placeholder (vg_resolve.py:114-181)

**What is deferred**: The CASE score expression and UUID IN filter.
**Mechanism**: At generation time, emit `__VG_FUZZY_SCORE_12345__` and
`__VG_FUZZY_FILTER_12345__` placeholder tokens. Post-generation,
`resolve_fuzzy_requests()` performs MinHash + RapidFuzz scoring, then
string-replaces the placeholders with CASE expressions.
**Why it works**: Same as Pattern 1 — structure is known, only values deferred.
**Note**: `fuzzy_match_sql` (line 1062) ALSO calls `_resolve_uuid_col` and
fails with the same bug if the variable isn't bound yet.

### Pattern 3: Term JOIN deferral — structural pushdown (emit_group.py, emit_distinct.py)

**What is deferred**: Term-table JOINs (text resolution) past GROUP BY / DISTINCT.
**Mechanism**: Set `ctx.text_needed_vars = set()` to suppress term JOINs in
the inner scan. After the aggregate/dedup, wrap with an outer SELECT that adds
term JOINs only for the small result set.
**Why it works**: UUID columns are always emitted — text is deferred because
the UUID→text relationship is stable and can be resolved at any layer.

### What's Missing: UUID Column Placeholder (Proposed Pattern 4)

None of the existing patterns defer **structural column references** — they
all require `uuid_col` to be resolved at generation time. The bug is that
`_resolve_uuid_col` needs the variable to already be in the TypeRegistry,
which requires the child pattern to have been emitted first.

**Proposed fix — UUID placeholder token**:

```python
def _resolve_uuid_col(entity_var: str, ctx) -> Optional[str]:
    info = ctx.types.get(entity_var)
    if info and info.uuid_col:
        return info.uuid_col
    # NEW: emit a deferred placeholder instead of returning None
    placeholder = f"__VG_UUID_{entity_var}__"
    ctx.add_deferred_uuid(entity_var, placeholder)
    return placeholder
```

Then in `emit_extend` (line 186), **after** the child is emitted:

```python
child_sql = emit(plan.child, ctx)

# Resolve any deferred UUID placeholders now that child types are populated
for var, placeholder in ctx.pop_deferred_uuids():
    info = ctx.types.get(var)
    if info and info.uuid_col:
        child_sql = child_sql.replace(placeholder, info.uuid_col)
    else:
        # Variable truly doesn't exist — error, not just ordering
        logger.error("Cannot resolve UUID for ?%s after child emit", var)
```

This fits naturally between Patterns 1-2 (placeholder substitution) and
Pattern 3 (structural awareness of emit ordering). It requires:

1. A new `_deferred_uuids: List[Tuple[str, str]]` on `EmitContext`
2. `add_deferred_uuid(var, placeholder)` + `pop_deferred_uuids()` methods
3. Resolution callsite in `emit_extend` after `child_sql = emit(plan.child, ctx)`
4. Resolution callsite in `emit_join` for the same reason (OPTIONAL patterns)

**Complexity**: Low — ~20 lines of code. No architectural changes needed.

## Files

- `vitalgraph/db/sparql_sql/vg_functions.py` — `_resolve_uuid_col`, `vector_top_k_driving_sql`
- `vitalgraph/db/sparql_sql/emit_extend.py` — `extract_vector_args` call site
- `vitalgraph/db/sparql_sql/emit_context.py` — `TypeRegistry` (where variables are registered)
- `vitalgraph/db/sparql_sql/sql_type_generation.py` — `register_from_triple` (how BGPs populate registry)

## Status

**FIXED** — Pattern 4 implemented 2026-07-03. All 420 API tests + 363
conformance tests pass.

### Changes made:
- `emit_context.py` — Added `_deferred_uuids: List[Tuple[str, str]]`,
  `add_deferred_uuid()`, `pop_deferred_uuids()`, shared via `child()`.
- `vg_functions.py` — `_resolve_uuid_col` now emits `__VG_UUID_{var}__`
  placeholder instead of returning `None` when `ctx.add_deferred_uuid` is available.
- `emit_extend.py` — Two resolution callsites:
  1. Standard path (line 209): after `expr_to_sql()`, resolves placeholders in `sql_expr`.
  2. Vector driving path (line 140): resolves placeholder in `child_uuid_col`.

## Discovered

2026-07-03 — During document segmentation e2e test implementation.
