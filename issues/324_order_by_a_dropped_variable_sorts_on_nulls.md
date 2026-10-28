# 324 — ORDER BY a variable the projection drops sorts on NULLs

## Status: FIXED 2026-10-27 on the default path. Open until the vg test stack runs the full suite on the rebuilt image. One part left as a product decision (below).

## Defects

On the default path, which production runs. Found by a differential sweep of generated
queries against Oxigraph (`test_scripts_internal/sweep`).

1. **An ordering variable the projection drops had no text.** `SELECT ?s WHERE { ?s :name ?n }
   ORDER BY ?n` sorted on NULLs: the order, and a LIMIT's page, came from the next key alone (or
   none). `ORDER BY ?x` is held as the bare name (`collect._collect_order`), and
   `var_scope._collect_referenced_vars` read it through `vars_in_expr`, which reads expression
   objects only: `?n` counted as internal-only and its term row was never joined. Silent wrong
   answers; with a LIMIT, the wrong page.
2. **Equal numbers were ordered by their text.** `10` and `"1.0E1"^^xsd:double` are equal under
   SPARQL's `<`, so the next ORDER BY key decides between them; the generator's keys (value,
   date, text) put the lexical form first.
3. **Kinds were not ordered.** SPARQL 15.1 orders blank nodes, then IRIs, then literals; a
   variable holding both IRIs and literals sorted them by text.
4. **`ORDER BY` a variable nothing binds failed** with an SQL error (a column of the projection's
   NULLs, referenced below it).

## Fix

- `var_scope._collect_referenced_vars`: a bare ORDER BY variable is a reference.
- `emit_order.variable_order_keys` (both paths; the qtree planner's undecoded keys likewise): a
  kind rank first, then the value, the date, and the text only for a value with neither.
- `emit_order`, `emit_project`, `emit_slice.reorder_over_distinct`: an unbound (never bound)
  ordering variable orders nothing.

## Left as is: where an unbound value sorts

SPARQL 15.1 puts an unbound value LOWEST (first ascending, last descending). Here it sorts last
ascending and first descending, PostgreSQL's NULL placement, and the app relies on it: frame and
slot sequence is optional, and `ORDER BY ?seq ?frame` puts unsequenced items last
(`tests/integration/test_sequence_ordering.py`, `TestCoalesceInOrderBy`). Changing it would
reorder production's frame and slot listings: a product decision, not a defect fix. The kind rank
keeps unbound after every kind for that reason.

## Test

`tests/integration/test_order_by_follows_sparql_ordering.py`: a dropped ordering variable, with
and without a LIMIT; unbound placement both ways (as kept); equal numbers tying to the next key;
an ordering variable nothing binds.
