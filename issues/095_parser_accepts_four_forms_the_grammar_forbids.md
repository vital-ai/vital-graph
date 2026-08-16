# The Parser Accepts Four Forms the SPARQL Grammar Forbids

## Status: OPEN — upstream (Jena); found 2026-08-16 by wiring in the DAWG syntax categories

Four `NegativeSyntaxTest11` cases are accepted by our parse path when the
grammar says they must be rejected:

    syntax-query/syn-bad-01   SELECT * { ?s ?p ?o } GROUP BY ?s
    syntax-query/syn-bad-04   SELECT (?x +?y) {}
    syntax-query/syn-bad-05   SELECT COUNT(*) {}
    construct/constructwhere06   CONSTRUCT WHERE { GRAPH <data.ttl> { ?s ?p ?o } }

`syn-bad-04` and `syn-bad-05` are projected expressions without the `AS ?var`
the grammar requires. `constructwhere06` uses the short `CONSTRUCT WHERE` form,
which takes a bare TriplesTemplate and does not admit `GRAPH`.

## Severity: low, with one qualifier

This is **over-acceptance** — we answer queries that should have been refused,
rather than refusing valid ones. That is the mild direction: no valid query is
harmed, and no result is wrong for any query the spec defines.

The qualifier is `syn-bad-01`. `SELECT *` with `GROUP BY` has **no defined
answer** — the spec forbids it precisely because `*` cannot be resolved against
a grouped solution. So whatever we return for it is undefined behaviour rather
than a documented extension, and two engines that both accept it may still
disagree about the answer.

## Attribution

Ours only in the sense that we ship it. All four are decisions made inside
Apache Jena, reached through `/v1/sparql/compile`
(`vitalgraph-jena-sidecar`). Nothing in `vitalgraph/db/sparql_sql/` participates
in the accept/reject decision.

Fixing them would mean post-parse validation in the sidecar — checking the
parsed `Query` for these four shapes and rejecting. That is a real option, since
we already own `SparqlCompiler`, but it means maintaining a slice of grammar
enforcement that Jena declines to.

## Why they were not found earlier

The `syntax-query` category was never in any suite's category list. The
`construct` case is worse: that category WAS wired, but `_collect_p0_tests`
filters `test_type == "QueryEvaluation"`, so its two negative-syntax cases were
read out of the manifest and dropped. Nine cases across four wired categories
were being parsed and discarded that way.

## Tests

`tests/conformance/test_dawg_syntax.py` runs all 152 syntax cases plus the nine
recovered ones. These four are `xfail` with this issue named; the other 166
pass. An entry that starts passing should be deleted rather than left as a
permanent xfail.

## Related

- `issues/093` — subquery inside `GRAPH` returns zero rows
- `planning/planning_sparql_features/dawg_conformance_coverage.md`
