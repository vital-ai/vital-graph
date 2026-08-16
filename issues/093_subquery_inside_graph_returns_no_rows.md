# A Missing Term Used Only to EXCLUDE Emptied the Whole Query

## Status: FIXED 2026-08-16

Filed as "a subquery inside a GRAPH block returns zero rows". The subquery was a
red herring — Jena folds `{SELECT * WHERE {...}}` away entirely, so the algebra
sq01 reaches us with is just `(project (graph ?g (bgp ...)))`. The same query
WITHOUT the subquery failed identically, which is what identified the real
cause:

    GRAPH ?g { {SELECT * ...} }   default_graph set -> 0 rows,  unset -> 2
    GRAPH ?g { ?x ?p ?y }         default_graph set -> 0 rows,  unset -> 2

## The defect

`query_is_provably_empty` (`prune_union.py`) short-circuits a query to `LIMIT 0`
when it REQUIRES a constant absent from the term table. That is a real and large
win — an equality against a never-stored term matches nothing, and proving it by
scanning cost 40 s+ on one measured shape (issues/073).

"Requires" was decided by looking for the constant's token anywhere in a
constraint string, with no regard for the operator:

    col = <missing>                  can never hold   -> empty. Correct.
    col IS DISTINCT FROM <missing>   ALWAYS holds     -> empty. WRONG.

`collect.py` emits the second for every `GRAPH ?g`, because `GRAPH ?g` ranges
over the named graphs and the default graph must be excluded. It chooses
`IS DISTINCT FROM` over `!=` *precisely so* that a missing default-graph term
reads as "no exclusion" rather than filtering every row — and its comment says
so. The emptiness check then read that same absence as proof of emptiness.

So the two passes disagreed about what an absent term means, and the one that
ran second won.

## Blast radius

Wider than the three DAWG cases. ANY query with a `GRAPH ?g` and a
`default_graph` whose URI has no term in that space returned zero rows. An empty
default graph is enough — the URI only exists in the term table once something
has been written to it.

Silent: `LIMIT 0` raises nothing, and zero rows is a legitimate answer to a
query matching nothing.

## Fix

`_dead_constant_is_required` checks the operator each occurrence sits under. A
dead constant on the right of `IS DISTINCT FROM` is a no-op, not a
contradiction, and does not mark the node dead. Everything else is unchanged, so
the optimisation still fires where it was right.

Verified all three ways round:

    = against a missing term          -> still short-circuits
    missing term only in an OPTIONAL  -> runs (already correct)
    GRAPH ?g with a default graph     -> runs

## Tests

`tests/unit/sparql_sql/test_provably_empty_negative_use.py` — 14 cases over the
predicate, no database needed. Reverting to the textual check fails 6.

The three DAWG entries were REMOVED from `KNOWN_FAILURES` rather than left as
xfails; all 14 subquery cases now pass.

## A note on the false lead

The middle case above cost a detour: I first tested "missing term in an
OPTIONAL" with a default_graph that ALSO had no term, so two constants were
dead — one of them pinned with `=` outside any GRAPH, which genuinely does make
the query empty. It looked like a second bug in the OPTIONAL handling. It was a
badly built test case; `_required_subtree_is_dead` handles LEFT_JOIN correctly
and always did.
