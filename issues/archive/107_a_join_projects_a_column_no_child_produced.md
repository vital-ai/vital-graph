# A JOIN Projects a Column No Child Produced, and the Query Dies

## Status: FIXED 2026-08-18

    asyncpg.exceptions.UndefinedColumnError: column j2._seg_idx does not exist

`emit_join` resolved a variable's SQL column name with

    def _child_sn(v, child_ctx):
        info = child_ctx.types.get(v)
        return info.sql_name if info else v      # <- fabricates

A missing registry entry means the child DOES NOT EMIT that column. Falling back
to the raw SPARQL name invents one, and the projection then asks a subquery for
a column nothing created. PostgreSQL rejects the whole statement.

Both the plain join projection and the semi-join path did it, and the
registration loop below them repeated the same `else v`, so a fabricated name
propagated upward and the outer join trusted it.

The fix skips variables neither child produces, and logs which. An absent column
cannot be projected; inventing a name turns "this variable is not here" into a
syntax error a long way from the cause.

## Why it looked data-dependent

The same document query is FINE on one space and fails on another. The semi-join
gate fires on selectivity, so whether this path is taken depends on the
statistics of the space being queried — which is why it survived: the shape is
common, and the plan that exposes it is not.

Reproduced with the KGQuery document builder, `search_scope="segments"` plus
`parent_document_uri` (the `?_seg_idx` variable comes from `FILTER(?_seg_idx > 0)`):

    apitest_37a59eb5   column j2._seg_idx does not exist
    e2e_test_space     0 rows, no error

Same query text, same code, different statistics.

## The comment that was already there

Ten lines below the fallback, the semi-join registration says:

    # ... without this an ORDER BY above cannot resolve them and
    # emits the raw SPARQL name as a column.

The same fabrication, named as a hazard, one step later in the same function.

## What it broke

`tests/api/test_wikipedia_document_e2e.py::test_query_by_parent_document`, which
failed identically before any of today's changes — pre-existing, not from the
late-text window.

## Verification

Unit, integration, conformance and performance suites all at 0 failures after
the change, which matters more than usual here: skipping columns in a join is
the kind of edit that could silently narrow output everywhere.

## Related

- `issues/083` — a var_map naming nothing; this is the same class from the other
  side, a projection naming what does not exist
