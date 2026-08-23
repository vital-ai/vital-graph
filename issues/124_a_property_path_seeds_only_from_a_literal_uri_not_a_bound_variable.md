# A Property Path Seeds Only From a Literal URI, Not From a Bound Variable

## Status: OPEN — found 2026-08-22. Not a collections problem; collections are
## just where it was noticed.

The same query, the same data, the same 100 results. The only difference is
whether the path's start arrives as a constant or through a join:

    <urn:sd:c0> rdf:rest* ?n . ?n rdf:first ?item
        100 items    22.8 ms     27,896 buffers

    <urn:sd:s> :items ?l . ?l rdf:rest* ?n . ?n rdf:first ?item
        100 items   244.9 ms    389,002 buffers

**14x the buffers, 11x the time**, for an identical answer.

## Mechanism

`emit_path.py:143`

    seed_start_sql = seed_end_sql = None
    if isinstance(subject, URINode):
        seed_start_sql = (
            f"(SELECT term_uuid FROM {term_table} "
            f"WHERE term_text = '{_esc(subject.value)}' AND term_type = 'U' LIMIT 1)")

The seed is built only when the path's subject is a **URINode** — a URI written
literally in the query. A variable bound by a preceding triple pattern is a
`VarNode`, so no seed is produced and the recursion runs unseeded.

The file already explains what that costs, at `:134`:

> A pinned SUBJECT is handed down so a recursive path can seed its base term
> from it rather than **closing over the whole graph and filtering afterwards**.

Closing over the whole graph is exactly what the join-bound case does. Measured
on a 101-cell chain, the unseeded recursion materialises **5,252 rows** — the
full transitive closure, every cell to every later cell — where the seeded form
needs 101.

## Why this is bigger than the case that found it

Collections made it visible because a list is a long thin chain, so the closure
is quadratic in an obvious way. But the condition is just "the path's start is
a variable", and that is the ordinary shape of our own traversal queries:

    ?entity :hasFrame ?f . ?f :hasSubFrame* ?sub

Any query that reaches a node and then walks from it pays this. Entity-to-frame
traversal, frame nesting — the workload the derived tables and the collapse
rewrite exist to serve — is written this way.

**Not measured on those shapes yet.** The 14x above is one list. Whether the
same gap appears on the lead and graph fixtures is the first thing to check,
and it is cheap: the fixtures and benches already exist.

## What a fix has to deal with

Not a one-liner. `seed_start_sql` is a **scalar** SQL expression substituted
into the CTE's base term. A bound variable's value is per-row, so seeding from
it means either:

* a **LATERAL** join, so the path CTE is evaluated once per outer binding with
  that binding as the seed; or
* passing the outer binding's column reference into the CTE as a correlated
  value, which PostgreSQL does not allow for a `WITH RECURSIVE` term directly.

The first is the real option and it changes the shape of the emitted SQL, not
just a predicate. It is the same family as `_try_selective_driven` — use a
known binding to drive the work rather than computing everything and filtering
— and it carries the same risk that repository has already been burned by: a
plan-selection change that helps one shape and hurts another.

## Before implementing

1. **Measure it on the real traversal shapes**, not on a synthetic list. If the
   gap is small there, this is a collections curiosity; if it is 14x, it is a
   core-workload defect.
2. **Check the interaction with `issues/123`.** That proposes removing the
   `depth` column so the recursion terminates by dedup. An unseeded closure is
   where dedup matters most, so the two changes touch the same code and should
   be reasoned about together.
3. **Baseline first.** `query.json` and `ingest.json` were re-promoted
   2026-08-22 and are current, so a before/after is meaningful today.

## Relationship to other issues

* `issues/122` — collections truncate past 100 elements. Different defect, same
  file.
* `issues/123` — the depth cap. Same CTEs.
* `rdf_collections.md` §4.1 attributes the position query's cost to the
  double-closure idiom. That is true, but this issue is the larger multiplier
  underneath it, and §4.1 should be read with that in mind.
