# SQL generator: BIND in UNION branches produces empty bindings

## Summary

A SPARQL query using `{ BIND(?x AS ?y) } UNION { BIND(?z AS ?y) }`
where `?x` and `?z` are bound in a sibling GRAPH pattern compiles and
executes through the pipeline — but the projected variable (`?y`) is always
empty `{}` in bindings.

Jena sidecar correctly accepts the query (it is syntactically valid), but
the algebra evaluation semantics mean the variables are **out of scope**
within the UNION branches.

## Root Cause (Investigated)

**This is NOT a bug in the SQL generator.** The behavior is correct per
W3C SPARQL 1.1 formal algebra evaluation rules (§18.5).

### Why the variables are out of scope

The SPARQL algebra for this query is:

```
Join(
  Graph(<g>, BGP(?frame, ?slot, ...)),
  Union(
    Extend(TableUnit(), ?subject, ExprVar(?frame)),
    Extend(TableUnit(), ?subject, ExprVar(?slot))
  )
)
```

Each UNION branch's EXTEND has `TableUnit()` (one empty solution) as its
child — NOT the GRAPH pattern. Per SPARQL §18.5, `Extend(Ω, var, expr)`
evaluates `expr` over each μ in Ω. Since Ω = {μ₀} where μ₀ = {} (empty
mapping), `eval({}, ?frame)` → error → binding not added.

`Join(A, B)` evaluates A and B **independently** then merges compatible
solutions. B cannot reference variables from A during its own evaluation.

### Pipeline trace

1. `emit_join` creates independent child contexts for left/right
2. Left (GRAPH/BGP) emits and registers `?frame`, `?slot` in left context
3. Right (UNION) emits in its own context where `?frame`/`?slot` are absent
4. `emit_extend` → `expr_to_sql(ExprVar("frame"))` → `_var_to_sql` →
   `ctx.types.get("frame")` → None → returns `"NULL"`
5. `?subject` is bound to NULL in both branches → empty bindings after JOIN

## Resolution

Added a **diagnostic warning** (not a behavioral fix) so this pattern is no
longer silent. When `_var_to_sql` resolves a variable to NULL that IS defined
elsewhere in the query plan, it now logs:

```
WARNING: Variable ?frame exists in query but is out of scope in current
context (depth=N). This typically means a BIND inside a UNION branch
references a variable from a sibling pattern. Per SPARQL 1.1 semantics,
each UNION branch is evaluated independently — move the source pattern
into the UNION branch or use a different query structure.
```

## Reproduction

```sparql
SELECT DISTINCT ?subject WHERE {
    GRAPH <g> {
        ?frame a haley:KGFrame .
        ?slot_edge vital-core:vitaltype <...Edge_hasKGSlot> .
        ?slot_edge vital-core:hasEdgeSource ?frame .
        ?slot_edge vital-core:hasEdgeDestination ?slot .
    }
    { BIND(?frame AS ?subject) } UNION { BIND(?slot AS ?subject) }
}
```

- Jena sidecar returns compiled AST without error (syntactically valid)
- SQL is generated (~9000 chars)
- Query executes and returns 1 row
- Binding is `{}` — `?subject` is unbound (correct per SPARQL semantics)
- **Now emits a WARNING log** explaining the out-of-scope reference

## Correct Pattern

Use the standard UNION pattern with the full graph pattern repeated in each
branch:

```sparql
SELECT DISTINCT ?subject WHERE {
    {
        GRAPH <g> {
            ?subject a haley:KGFrame .
            ?slot_edge vital-core:hasEdgeSource ?subject .
            ...
        }
    } UNION {
        GRAPH <g> {
            ?frame a haley:KGFrame .
            ?slot_edge vital-core:hasEdgeSource ?frame .
            ?slot_edge vital-core:hasEdgeDestination ?subject .
            ...
        }
    }
}
```

## Impact

This caused a silent data-loss bug during development: the query appeared to
work (no errors, rows returned) but produced empty results that took
significant debugging effort to trace. The diagnostic warning now makes this
immediately visible in logs.

## Severity

**Low** (reclassified from Medium) — the behavior is correct per spec. The
issue was lack of diagnostic feedback, which is now addressed.

## Files Modified

- `vitalgraph/db/sparql_sql/emit_expressions.py` — warning in `_var_to_sql`
- `vitalgraph/db/sparql_sql/emit_context.py` — `query_all_vars` field
- `vitalgraph/db/sparql_sql/generator.py` — computes `query_all_vars` before emit
