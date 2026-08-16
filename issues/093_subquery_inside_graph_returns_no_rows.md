# A Subquery Inside a GRAPH Block Returns Zero Rows

## Status: OPEN — found 2026-08-16 by running DAWG categories that were never wired in

    SELECT ?x ?p WHERE {
      GRAPH ?g {
        { SELECT * WHERE { ?x ?p ?y } }
      }
    }

Expected 2 rows. Returns 0. pyoxigraph matches the manifest, so this is ours.

Three DAWG cases, all the same shape:

- `subquery/sq01 - Subquery within graph pattern`
- `subquery/sq02 - Subquery within graph pattern, graph variable is bound`
- `subquery/sq03 - Subquery within graph pattern, graph variable is not bound`

The other 11 subquery cases pass, so it is specifically a subquery nested inside
`GRAPH`, not subqueries generally.

## Why it was not found earlier

The `subquery` category was never in `P0_CATEGORIES`
(`tests/conformance/test_dawg_sql_v2.py`), the hardcoded list of DAWG categories
the suite runs. The manifests and the 14 `.rq` files have been in the tree the
whole time; nothing executed them.

At the point this was found, 19 of 34 DAWG categories were wired in. A green
conformance run meant "green on the categories someone remembered to add".

## Severity

Silent. Zero rows is a legitimate answer to a query that matches nothing, so
there is nothing to distinguish this from an empty result — no error, no warning.
Any caller nesting a subquery inside `GRAPH` gets an empty answer and no reason
to doubt it.

Mitigating: the shape is unusual in our own query paths, which build `GRAPH`
blocks without nested `SELECT`. It is reachable from any hand-written or
third-party SPARQL.

## Where to look

The interaction between graph-context binding and subquery scope. `GRAPH ?g`
introduces a context that the inner `SELECT` must inherit; a nested `SELECT`
projects only its own variables, so the likely cause is the graph context being
dropped or re-bound when the subquery's projection is emitted. sq03 ("graph
variable is not bound") failing alongside sq02 ("bound") suggests it is not
about the variable's binding state.

## Related

- `issues/094` — the `cast/xsd:float` mismatch, found in the same pass
- `planning/planning_sparql_features/README.md` — §5 property paths were also
  never exercised, and turned out to PASS (33 of 33), which is the other half of
  what this measurement was worth
