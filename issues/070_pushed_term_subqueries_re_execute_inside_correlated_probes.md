# Pushed Term Subqueries Re-Execute Per Row Inside Correlated Probes

## Status: `has_any` FIXED; `contains` LARGELY FIXED — 2026-08-11

    sp_lead_synth_100k, 25-row page, warm:

                       before        after
      contains 'CA'      45 ms       48 ms    common — unchanged, as required
      contains 'XQ'    TIMEOUT   11,151 ms    rare
      contains 'ZZQQXX' TIMEOUT        1 ms   absent

Gated on `scripts/perf_sweep_diff.py`: 39 cells both arms, NO REGRESSIONS,
0 cells slow warm, 0 over the buffer threshold. `contains` also left the
cold-only list (1,156 ms cold -> under the 1s threshold).

**What made the difference was measuring the leaf, not re-planning it.**
`semijoin.needed_texts` extracts the LIKE-family condition, the generator counts
it BOUNDED, and `_leaf_rows` reports it — after which the existing semi-join gate
declines to probe a leaf it can now see is tiny, and the set-based join it falls
back to answers the empty case immediately. No new plan shape was introduced.

The probe is two-step because the naive one charges most for the answer that
matters least: counting matching QUADS to a 50,000 cap cost 943 ms of generation
for `'CA'`. Counting matching TERMS to a 200 cap first is ~1.5 ms — trigram-served
when selective, and short-circuiting when not, since reaching the cap IS the
answer. Net generation cost is now ~1.5 ms; the 500-600 ms seen on a first call
is process warm-up and appears whichever pattern runs first.

**`'XQ'` at 11 s is the remaining half.** It matches few enough to be selective
but not zero, so the set-based join materialises the match set. Driving the page
from the text leaf is what would fix it — and that is blocked on a real defect,
below.

### BLOCKED: the selective-driven path silently drops FILTERs

`_try_selective_driven` drives the page from `emit_bgp_anchor(right_bgp)`, which
carries the BGP's own constant leaves but NOT a FILTER sitting above the join.
That is sound for a constant criterion (`WV` binds `object_uuid` inside the BGP)
and WRONG for a text criterion, which is a pushed filter.

Measured, by letting a zero count through the guard: **`contains 'ZZQQXX'`
returned 25 rows** for a substring matching nothing. Reverted immediately.

The guard that prevents this is `if not anchor_n or not driver_n` — falsiness,
so a measured ZERO is treated as unmeasured. That reads like a bug (zero is a
measurement, and the most selective one there is), and fixing it in isolation
produces wrong answers. The comment at that line now says so, because the next
person to notice it will reach for the same one-line change.

Fixing it properly means teaching the driver to carry pushed filter conditions.
That is the prerequisite for `issues/061` step 3 driving from text at all.

    has_any/Text     timeout -> 80 ms     fixed, uuid constants
    has_any/Choice   timeout -> 73 ms     fixed, uuid constants
    contains/Text    45 ms COMMON substring / TIMES OUT when selective

**I closed this earlier today and was wrong.** The closure measured only the
sweep's fixed value, `contains 'CA'`, saw 45 ms, and concluded there was no
problem. `CA` matches 2.6M of the term rows in `sp_lead_synth_100k`. Every
selective substring — the normal case for a user searching — behaves completely
differently:

    sp_lead_synth_100k, 25-row page, warm:
      contains 'CA'        45 ms       common
      contains 'XQ'        TIMEOUT     >120 s
      contains 'ZZQQXX'    TIMEOUT     >120 s   absent by construction

The mechanism, from `sp_lead_synth_10k` where the absent case still completes:

                      rows removed by filter   max buffers    time
      'CA'      common        243                  35,793     2,054 ms
      'ZZQQXX'  absent     10,000 = EVERY entity  1,360,001   16,090 ms

So it is O(entities) whenever matches are rare: the page is driven in candidate
order and the ILIKE is applied per candidate, so the Limit can only stop early
if matches are dense. When they are not, it walks the whole space to fill 25
rows — or to prove there are none. That is the `issues/073` shape exactly:
absent is the worst case when it should be the best.

## The trigram index exists, is never used, and is the answer

`idx_{space}_term_trgm` (GIN, `gin_trgm_ops`) is present and appears in NO plan
for these queries. Measured directly against the term table, PostgreSQL already
chooses correctly when it is given the choice:

    SELECT term_uuid FROM ..._term WHERE term_text ILIKE '%ZZQQXX%'
      -> Bitmap Index Scan on ..._term_trgm, 1.255 ms, 9 buffers, 0 rows

    SELECT count(*) FROM ..._term WHERE term_text ILIKE '%CA%'
      -> Parallel Seq Scan, 1,668 ms, 2.6M rows  (trigram correctly REJECTED)

The planner picks the index for the selective case and rejects it for the common
one, unprompted. It never gets the opportunity in the generated SQL, because the
ILIKE is not a term-set constraint there — it is a filter on a row already
fetched by `term_pkey`.

### The text anchor already fires. It is pinned in the wrong PLACE.

`reorder_bgp` does exactly what it is supposed to — confirmed by instrumenting
the generation for `contains 'ZZQQXX'`:

    reorder_bgp: Chain root: q16 (text-filter anchor)

and its comment states the reason outright: a LIKE/ILIKE/regex leaf is served by
the GIN trigram index and must root the chain ahead of any row count.

But that pins the text leaf FIRST WITHIN THE PROBE, and the probe runs once per
candidate. `_emit_two_phase` unconditionally anchors the PAGE on the entity-type
BGP, because that is what supplies `subject_uuid` order so `LIMIT` can stop
early; every criterion is then a probe by construction.
`_try_selective_driven` — the one path that would drive the page from a
criterion instead — only runs when two-phase DECLINES, and for `contains` it
does not decline.

That is also the whole reason the trigram index is unreachable: inside a
correlated probe the term row is already identified by `term_uuid`, so the ILIKE
can only ever be a filter on a fetched row. An index lookup requires the text
leaf to DRIVE.

**So the fix is driver selection, not a push-down.** An earlier revision of this
line proposed giving `contains` the standard
`object_uuid IN (SELECT term_uuid FROM {space}_term WHERE ...)` shape. That does
not work here and the reason is this issue's own premise: PostgreSQL does not
hoist an uncorrelated subquery out of an enclosing CORRELATED one, so it would
re-execute per candidate — 1.2 ms x 100,000 candidates for the absent case, still
a timeout. Not the MATERIALIZED CTE either (41x worse; the LIMIT is what makes
the common case cheap and a CTE barrier discards it).

What is needed is for an INDEX-BACKED TEXT LEAF to be allowed to drive the page,
gated on selectivity — the same precedence `reorder_bgp` already applies to join
order, extended to driver choice. Gated, because the common case must not
regress: `'CA'` matches 2.6M terms, and driving from that side would be far worse
than the 45 ms it costs today. The planner makes exactly this call correctly when
given the choice at the term level.

Any attempt must measure BOTH ends: the selective case it is meant to fix and
the common `CA` case at 45 ms that it must not regress.

## The measurement gap this exposes, which is the more general lesson

`scripts/perf_shape_matrix.py` uses ONE fixed value per cell. For `contains`
that value is `CA`, which is the least selective substring in the fixture. The
sweep therefore reports this cell green and cannot see the pathology, at any
scale, however many times it is run — and `issues/053` closed partly on that
sweep. A comparator whose cost depends on SELECTIVITY needs at least a common
and a rare value, or the sweep is measuring one point on a curve and calling it
the curve. Compare `issues/071`: a cell that is slow but not tracked cannot be
noticed by looking harder at the list.

## Superseded status: the guard in place is a mitigation, not the fix

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

## The proposed fix was implemented, measured, and REVERTED — 2026-08-10

The MATERIALIZED CTE below was built and swept. It is **much worse**:

    contains/Text    1,284 ms -> 53,098 ms   (41x, nearly back to timeout)
    ne/Text            228 ms ->  1,692 ms   (7.4x)
    has_any/Text    12,684 ms -> 20,603 ms
    has_any/Choice  13,269 ms -> 12,114 ms   (the only cell not hurt)

No cell improved. Reverted; `filter_pushdown._term_set` now emits the inline
subquery and carries this result so it is not re-attempted.

### Why the reasoning was wrong

"Evaluated once" only beats "evaluated per row" when the per-row evaluation
cannot early-terminate. Under two-phase paging it can, and that is the whole
design: the probe tests candidates until the page is full — about 25 of them —
and each test is an index lookup that never materialises the term set.

The CTE throws that away. `term_text ILIKE '%ca%'` under the trigram index costs
almost nothing per probe, but as a CTE it must produce EVERY matching term
before the first page row exists. The `LIMIT` is what makes the inline form
cheap, and a CTE is precisely the optimisation barrier that discards it. That
`contains` — the cell with the cheapest per-probe cost and the broadest term set
— regressed hardest is the signature of exactly this.

So the diagnosis in this issue is right and the prescription was backwards: the
subquery does re-execute per candidate, and that is FINE, because per-candidate
work bounded by LIMIT beats unbounded work done once.

### What would actually help

Not "compute once" but "compute less". `has_any` on text and choice resolves to
a handful of exact literals, so resolving them to uuids at generation time — the
way `eq` already does through `materialize_constants` — yields a constant
`IN (uuid, uuid)` that the index probes directly, with no term scan per
candidate at all. That is narrower than the CTE and does not fight the LIMIT.

Blocked on the same thing noted below: `_ne_equality_cond` produces a lexical
condition, and the uuid depends on the per-space `datatype_id`, so the mapping
from literal to uuid needs the resolution machinery rather than a local
computation.

## The original proposal (superseded — kept for the record)

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
