# 324 — ORDER BY a variable the projection drops sorts on NULLs

## Status: RESOLVED 2026-10-28. Verified on the vg test stack rebuilt at 3d99208c: unit, DAWG conformance, integration and API suites, 0 failures. The unbound placement left open here was decided and fixed in issues/326 (SPARQL's lowest; the app states missing-last explicitly).

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

- `var_scope._collect_referenced_vars`: a bare ORDER BY variable is a reference (1).
- `emit_order`, `emit_project`, `emit_slice.reorder_over_distinct`: an ordering variable nothing
  binds orders nothing (4).

## Left as they are

- **(2), (3)** were fixed first with expression keys in `variable_order_keys` (a kind rank; a
  text key confined to values with no numeric or date reading). Measured on the default path
  before / after, 7 runs each: every ordered query 10-59% slower (u08 1.36-1.59x, d09 1.19-1.28x):
  an expression key no longer matches the inner ORDER BY's sorted output, so the outer ORDER BY
  sorts again. Both deviations are rare (a variable mixing kinds; equal numbers written
  differently) and still give a valid order; reverted to plain columns. With the revert, the
  lead10k portal queries and the ordered corpus shapes generate exactly the SQL they did before.
- **Where an unbound value sorts.** SPARQL 15.1 puts it LOWEST (first ascending, last
  descending). Here it sorts last ascending and first descending, PostgreSQL's NULL placement,
  and the app relies on it: frame and slot sequence is optional, and `ORDER BY ?seq ?frame` puts
  unsequenced items last (`tests/integration/test_sequence_ordering.py`, `TestCoalesceInOrderBy`).
  Changing it would reorder production's frame and slot listings: a product decision.

## Test

`tests/integration/test_order_by_follows_sparql_ordering.py`: a dropped ordering variable, with
and without a LIMIT; unbound placement both ways (as kept);
an ordering variable nothing binds. (Equal numbers keep their text order, as above.)
