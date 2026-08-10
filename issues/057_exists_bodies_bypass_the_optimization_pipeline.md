# EXISTS / NOT EXISTS Bodies Receive None of the Optimization Pipeline

## Status: FIXED — 4 of 6 cells closed; the other 2 match nothing — 2026-08-10

Two changes, in the order that mattered:

1. **EXISTS bodies get the pipeline** (`exists_subplan.prepare_exists_subplans`).
   Probe cost 435 ms -> 0.11 ms. Closed nothing on its own.
2. **The negation folds into the probe** (`emit_slice._foldable_exists_join` +
   `emit_bgp_exists(extra_conds=...)` + `_exists_to_sql(outer_uuid_overrides=)`).

| cell | before | after |
|---|---|---|
| `not_has`/Text | TIMED OUT | **163 ms** |
| `not_has`/Choice | TIMED OUT | **108 ms** |
| `not_has_any`/Text | TIMED OUT | **52 ms** |
| `not_has_any`/Choice | TIMED OUT | **47 ms** |
| `not_exists`/Text, `not_exists`/Double | TIMED OUT | TIMED OUT |

Tests: 2,195 conformance + unit, 30 comparator coverage, 0 failures.

### The two that remain are not a paging problem

`not_exists` matches **0 of 100,000 entities** in this fixture — every entity has
the slot, and `test_comparator_coverage` pins the expected answer at 0. Proving
that nothing matches requires visiting everything, so no early-terminating plan
can help; O(page) is impossible when the page is empty. This is the same shape as
`eq`/DateTime, and it belongs to D3 (match density) in
`two_phase_kgquery_paging_plan.md`: a density-aware gate would choose a set-based
plan here instead of probing 100,000 times to return nothing.

### A bug this introduced, and what caught it

The first version computed the set of correlated variables from
`ctx.types.all_vars()`. At that point two-phase has emitted only the anchor, so
that set is empty — the soundness check passed **vacuously**, no correlation
overrides were built, and the fold emitted an *uncorrelated*
`NOT EXISTS (SELECT 1 FROM ...)`. That asks "does any slot anywhere have this
value", which is always true, so every entity was excluded and `not_has` returned
**0 rows instead of 1,508**.

`test_comparator_coverage` failed on 4 cells immediately. It exists because a
comparator returning 0 rows looks fast and plausible; here it was the difference
between a working rewrite and a silently empty one. The fix derives the variable
sets from the plan (`left_bgp` / `right_bgp` var_slots) rather than the emit
context, and refuses when any correlated variable has no probe column.

## Original status: FIXED (the probe), but CLOSES NO CELLS

The pipeline now runs on EXISTS bodies (`exists_subplan.prepare_exists_subplans`,
called from `generate_sql` stage 2a.3, consumed by `_exists_to_sql`). Measured on
`sp_lead_synth_100k`:

| | before | after |
|---|---|---|
| single correlated probe, warm | 435 ms | **0.11 ms** |
| lookup subqueries in the body | 7 | **0** |
| edge-table refs in the body | 0 | 1 |
| raw quad joins in the body | 4 | 2 |

Correctness: 30/30 comparator cases, 670/670 DAWG conformance, 0 failures.

**And all six affected cells still time out at 60s.** The probe was never the
whole cost. With the anchor at 100,000 entities and a blocking `Sort` on
`term_text` above the anti-join, the query pays `100,000 x probe` no matter how
cheap the probe is — about 11 s of probing plus term joins and the sort itself:

    Limit -> Unique -> Incremental Sort -> Sort (Key: t_v0.term_text)
          -> Nested Loop Anti Join

So this fix is necessary and not sufficient. What it changes is which work is
worth doing next: **25 probes now cost 2.75 ms**, so an early-terminating plan
would make these cells trivial, where before it would have needed 11 seconds.

### Correction: the blast radius is 6 cells, not 11

An earlier revision claimed `ne` compiles to `FILTER NOT EXISTS`. It does not —
checked by counting constructs in the generated SPARQL:

| comparator | construct | in this issue? |
|---|---|---|
| `not_exists`, `not_has`, `not_has_any` | `FILTER NOT EXISTS` | yes — 6 cells |
| `ne` (x5) | plain `FILTER(?v != x)` | **no — separate cause, unidentified** |
| `is_empty` | `OPTIONAL` + `!BOUND` | no |
| `has_any`, `contains` | neither | no |

`ne` timing out on all five slot classes is therefore still unexplained and
needs its own investigation.

## Original analysis (2026-08-10, fully-indexed `sp_lead_synth_100k`)

A single correlated `NOT EXISTS` probe costs **435 ms** and 40,403 buffer reads.
Twenty-five of them — one page — is about 11 seconds.

## Cause

`emit_expressions._exists_to_sql` builds the inner plan by calling `collect()`
**at emit time**:

    inner_plan = collect(gp, ctx.space_id, inner_aliases,
                         graph_uri=ctx.graph_lock_uri)

By then `generate_sql` has already run every optimization stage on the *outer*
plan and moved on. The inner plan is created afterwards and emitted directly, so
it receives none of them:

| stage | outer plan | EXISTS body |
|---|---|---|
| `materialize_constants` | uuid literals inline | 7 InitPlans, each resolving a URI at runtime |
| `rewrite_edge_table` | 2 edge-table refs | 0 — four raw quad joins |
| `rewrite_frame_entity_table` | applied | never |
| `mark_semijoins` | marked | never |
| text-needed pruning (`compute_text_needed_vars`) | applied | 3 term JOINs resolving text an EXISTS cannot use |

Confirmed by counting table references either side of the `WHERE NOT EXISTS` in
generated SQL for `not_exists`/Double:

    OUTER (before NOT EXISTS)    edge_table=2  rdf_quad=5
    INNER (NOT EXISTS body)      edge_table=0  rdf_quad=4

The edge table exists specifically to collapse `entity -> frame -> slot`
traversals. Inside an EXISTS it is never used, so every negated criterion walks
raw quads.

## Blast radius

Everything the KGQuery builder compiles to `FILTER NOT EXISTS`:

- `ne` — all five slot classes
- `not_exists`, `not_has`, `not_has_any`

That is ten of the twenty-one slow cells in `issues/053`, with one cause.

## An earlier, larger number was environmental

The first measurement of this probe was 2,300 ms, dominated by
`Parallel Seq Scan on ..._term` filtering 3,489,174 rows to resolve one
predicate URI — 245 ms per lookup, seven lookups. That was because the fixture
was missing `idx_*_term_tt` entirely (`issues/055`). With indexes restored the
probe is 435 ms and the remaining cost is the unoptimized traversal itself.

Both numbers point at the same defect; only the 435 ms one is the defect's
actual size.

## Why two-phase paging was the wrong FIRST fix, and is now the right SECOND one

The reasoning below concluded that generalizing the `_emit_two_phase` gate to
accept negative probes was not the fix. That was correct **at the time and for
the stated reason** — 25 x 435 ms is 11 seconds, so early termination could not
have rescued it.

With the probe at 0.11 ms that arithmetic reverses: 25 x 0.11 ms is 2.75 ms. The
gate is now the binding constraint, and the ordering was the whole point — doing
the gate first would have produced a correct plan that was still far too slow,
and the probe fix would have looked unnecessary.

### But NOT the way first proposed — that would return wrong answers

The obvious version — recognize a filter whose expression is a correlated
`ExprExists` and mark the join beneath it as a semi-join — is **unsound here**.

The plan is:

    order
      filter [ExprExists(NOT EXISTS)]
        join
          bgp  tables=2   vars=[entity]                             <- anchor
          bgp  tables=11  vars=[entity, frame_0, frame_0_0, ...]    <- frame path

and the variables tell the story:

    outside the NOT EXISTS:  entity, frame_0, frame_0_0, frame_edge_0, frame_edge_0_0
    inside  the NOT EXISTS:  entity, frame_0_0, slot_0_0_0, slot_edge_0_0_0

`?frame_0_0` is bound by the right BGP and referenced inside the body. Per SPARQL
1.1 §8.1.1 the body is evaluated with the current solution mapping substituted,
so the criterion means "**this** frame has no slot of type X", not "no frame
does". Marking the join would drop the side that binds `frame_0_0` and change the
question being asked.

`mark_semijoins` is therefore declining **correctly**, via
`not (right_private & (needed - pushable_vars))` — the `ExprExists` is not
pushable, so `_expr_list_vars` puts `frame_0_0` into `needed`, and it is in
`right_private`. Nothing is broken; the gate is right.

### The design that would work

Fold the negation **into** the probe rather than leaving it above the join.
`emit_bgp_exists` already emits `EXISTS (...)` over the right BGP; the
`NOT EXISTS` condition belongs *inside* that subquery, where `frame_0_0` is in
scope and correlation to the anchor is only on `entity`. That is what
`_filters_between` + `push_filters` is for — the machinery exists, it just cannot
consume an `ExprExists`.

Two ends have to agree, as always:

1. `semijoin._pushable_range_var` (or a sibling) must report the `ExprExists` as
   pushable **only** when every variable it references is bound within the probe
   BGP or is the anchor key — otherwise the correlation escapes the subquery.
2. `filter_pushdown` / `_emit_two_phase` must actually emit it inside the probe,
   and `_emit_two_phase`'s existing consumption check must still bail out when it
   does not.

If those two disagree the gate marks a join whose filter then fails to push, and
the result is a page containing entities outside the result set — which has
happened before (item 5 in `two_phase_kgquery_paging_plan.md`) and is why that
check is not optional.

## Original reasoning: why this was the right fix, and two-phase paging was not

The hypothesis before measuring was that negated criteria are slow because
`_emit_two_phase` gates on `_has_semijoin` (emit_slice.py:69) and a negation
never produces a semi-join, so it falls back to a blocking sort. Generalizing
that gate to accept negative probes looked like a one-line unlock.

It is not, and the probe cost is why: 25 x 435 ms is 11 seconds, so an
early-terminating plan over this probe would still miss a page budget by two
orders of magnitude. **The gate was never the binding constraint.** Running the
passes on the body is the fix, and it is the better one — it helps every negated
query whether or not it is paged.

The plan tree also shows there is no negated join node to mark. `not_exists`
produces `filter -> join -> (bgp, bgp)`, with the negation living inside a
filter *expression*; `exists` produces `join [SEMIJOIN] -> (bgp, bgp)`. So the
proposed gate change had nothing to attach to.

## Direction

Run the pass pipeline on EXISTS sub-plans. The obstacle is ordering: the passes
live in `generate_sql` and the sub-plan does not exist until emit. Options:

1. **Collect EXISTS bodies during `collect()`** so they are ordinary sub-plans
   present before the passes run, and let the passes recurse into them. Largest
   change, best result, and it also brings union pruning and semi-join marking.
2. **Run a subset of passes inside `_exists_to_sql`** — at minimum
   `materialize_constants` and `rewrite_edge_table`. Cheaper, and the two that
   matter most, but leaves the pipeline with two entry points that must be kept
   in step.
3. **Prune the pointless term JOINs** independently. Small, safe, and worth
   doing regardless: an EXISTS needs existence, not text.

Whichever is chosen, correctness rests on the correlation semantics already
documented at `_exists_to_sql` (SPARQL 1.1 §8.1.1, and the issue-027 note about
outer variables resolving to the enclosing row). Any pass that rewrites the body
must preserve which variables are inner and which are correlated.

## Related

- `issues/053` — the comparator sweep; ten of its cells are this issue
- `issues/055` — the missing indexes that inflated the first measurement
- `two_phase_kgquery_paging_plan.md` — the gate this was expected to be about
