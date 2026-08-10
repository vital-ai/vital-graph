# Pushed Term Subqueries Re-Execute Per Row Inside Correlated Probes

## Status: OPEN — the guard in place is a mitigation, not the fix

Every push-down in `filter_pushdown` emits the same shape:

    q.object_uuid IN (SELECT term_uuid FROM {space}_term WHERE <condition>)

That subquery is **uncorrelated** — its result does not depend on the outer row.
PostgreSQL nonetheless does not hoist it out of an enclosing *correlated*
subquery, so wherever the constraint lands inside one, the term scan re-executes
for every outer row.

Two enclosing correlated subqueries exist in this pipeline, and the constraint
reaches both:

1. **EXISTS / NOT EXISTS bodies** — `_exists_to_sql`. Measured cost of pushing
   `?v IN (...)` into a `NOT EXISTS` body:

       not_has_any/Choice    56 ms -> 10,649 ms   (190x)
       not_has_any/Text      47 ms ->  1,804 ms   (38x)

   Guarded as of this change: `EmitContext.in_correlated_subquery` is set for
   these bodies and `push_filters` declines outright. Nothing is lost —
   `prepare_exists_subplans` has already materialised those bodies' constants to
   uuids, which is the better constraint anyway.

2. **The two-phase probe** — `emit_bgp.emit_bgp_exists`. NOT guarded, because
   here the push-down is the only reason the query is not a blocking sort. This
   is why the surviving cells are merely slow rather than fast:

       has_any/Text      timeout -> 12,094 ms
       has_any/Choice    timeout -> 12,271 ms
       contains/Text     timeout ->  1,171 ms

   `contains` fares better only because the trigram index makes each re-execution
   cheap; it is the same O(candidates x term-scan) shape.

## Why this is not simply "guard the probe too"

In case 1 the push-down is redundant with something better. In case 2 it is
load-bearing: without it `?val` stays live, the semi-join does not fire, two-phase
paging declines and the plan reverts to a blocking sort over the whole match set
(`issues/058` documents that chain). Declining would return these cells to
timeout. The constraint needs to stay — it just needs to be evaluated once.

## The fix: evaluate the term set once, in a MATERIALIZED CTE

    WITH _f0 AS MATERIALIZED (
      SELECT term_uuid FROM {space}_term WHERE term_text ILIKE '%ca%'
    )
    ... q.object_uuid IN (SELECT term_uuid FROM _f0)

A CTE is evaluated once per query execution, so the term scan happens once no
matter how many candidates the probe tests. `MATERIALIZED` is required — without
it PostgreSQL may inline the CTE and reproduce exactly the problem being fixed.

The pipeline already has somewhere to put this: `materialize_constants` emits a
`_const` CTE at the top of the query, so CTE registration is a solved problem
here rather than new machinery.

Open question worth measuring before choosing: for the plain-literal cases
(`has_any` on text and choice) the equality set is a handful of exact terms, so
resolving them to uuids at generation time — the way `eq` already does — would
beat even the CTE, because it yields a constant `IN (uuid, uuid)` the index can
probe directly. That is not available for the numeric and datetime equality sets,
where `num_val = 5` may match several terms and cannot be enumerated without a
query. So the CTE is the general answer and constant resolution is a faster
special case, not a replacement.

## How this was found

A comparator sweep after the `contains`/`has_any` push-down landed showed
`not_has_any` slower than the baseline. It was only caught because the sweep was
re-run against stashed code on the same box in the same session — the absolute
numbers alone looked unremarkable (1.8 s and 10.6 s among cells that had recently
been minutes), and without the baseline column the 190x regression would have
shipped as "still a bit slow".

## Related

- `issues/053` — the sweep these cells come from
- `issues/058` — why the push-down must exist at all (the semi-join / two-phase chain)
- `issues/040` — `OFFSET 0` as an optimisation fence, the same planner behaviour
  used deliberately rather than suffered
