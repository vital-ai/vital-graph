# `BNODE()` Returns One Constant For Every Solution

## Status: OPEN — identified 2026-08-10

SPARQL 1.1 §17.4.2.2: `BNODE()` with no argument **must** return a distinct
blank node for each solution in which it is invoked. The one-argument form
`BNODE(expr)` must return the same blank node for the same simple-literal
argument within one query execution, and a different one otherwise.

We emit a constant:

```python
if fname == "bnode" and len(args) <= 1:
    if args:
        a = expr_to_sql(args[0], ctx)
        return f"CONCAT('_:', {a})" if a else "'_:b0'"
    return "'_:b0'"
```
`vitalgraph/db/sparql_sql/emit_expressions.py:848-852`

So

    SELECT (BNODE() AS ?b) WHERE { ?s ?p ?o }

returns the *same* node `b0` on every row. Every solution collapses onto one
blank node. Under `DISTINCT` the effect is worse — rows that the spec says are
distinct dedup down to one.

The one-argument form is right in spirit (equal arguments → equal node) but
inherits two problems: a non-literal or unbound argument falls through to the
same `'_:b0'` constant, and it is not scoped to the query execution, so two
separate queries using `BNODE("x")` produce the same label and therefore, if
either is written back, the same stored node.

## Second defect: the value carries the `_:` prefix

The emitted string already contains `_:`, and `sql_type_binding.py:220` renders
a `'B'` term by passing `value` through unchanged. The JSON result is
`{"type": "bnode", "value": "_:b0"}` where the spec wants `"b0"`. This is the
result-path half of `issues/065` and should be fixed in the same change.

## Third defect: the two code paths disagree

The typed-expression model types `BNODE` with an **empty** SQL string:

```python
if fname == "bnode":
    return TypedExpr(sql="", sparql_type="bnode")
```
`vitalgraph/db/sparql_sql/sql_type_generation.py:847-849`

while `emit_expressions` emits `'_:b0'`. Whichever path a given query takes
determines the answer. Reconcile these as part of the fix rather than leaving
two implementations of one function.

## Fix

The zero-argument form needs a per-solution identity. The natural SQL is a row
identity from the enclosing SELECT — a window `row_number()`, or a hash over
the solution's bound columns — combined with a per-execution salt so labels do
not collide across queries:

    'b' || {exec_salt} || '_' || row_number() OVER ()

and for the one-argument form, the same salt over the argument's text:

    'b' || {exec_salt} || '_' || md5({arg})

The salt must be stable within one execution and distinct across executions;
the compile/emit context already carries per-query state that can hold it.
Emit the **bare** label (no `_:`) so `sql_type_binding` renders it correctly.

Constraints worth checking before implementing: `row_number() OVER ()` inside
a projected expression is legal but interacts with how `emit_project` /
`emit_distinct` wrap the SELECT, and the value must survive `ORDER BY` and
`DISTINCT` without being recomputed with a different row number.

## Tests currently assert the wrong behavior

`tests/unit/sparql_sql/test_emit_expressions.py:637` (`test_bnode_no_args`) and
`:642` (`test_bnode_with_arg`) pin the current constant-emitting behavior. They
must be rewritten as part of this fix, not merely updated — the correct test is
a behavioral one:

- `SELECT (BNODE() AS ?b) WHERE { ?s ?p ?o }` over ≥2 rows returns ≥2 distinct
  labels;
- `SELECT (BNODE("x") AS ?b) (BNODE("x") AS ?c) WHERE { ... }` returns `?b = ?c`;
- no returned binding value starts with `_:`.

See `planning/planning_sparql_features/blank_nodes.md` §6 gaps 3 and 4.

## Related

- `planning/planning_sparql_features/blank_nodes.md` §4.2
- `issues/065` — the `_:` prefix convention
- `issues/076` — `INSERT DATA` freshness, the same "blank nodes must be fresh"
  requirement on the update side
- `issues/069` — test coverage
