# The Frame CONSTRUCT Enumerates Every Frame In The Space

## Status: RESOLVED 2026-09-11. The enumeration is gone: **285,348 frames
## enumerated before, 341 loops now** for the same 425 rows, 23,854 buffers.
##
## NOT by the mechanism this issue proposed. The fix is
## `rewrite_distribute_union` + `rewrite_merge_bgp` (`issues/178`), which put the
## anchor and the traversal into ONE join-ordering decision so `reorder_joins`
## could open on the trigram leaf it already preferred. Absorbing the edge type
## constraint — the 6.8x measured here — was implemented and REVERTED: it
## returned zero rows on the criteria and sort shapes (see the revert note in
## this file).
##
## The "ONE open question" below — why the CONSTRUCT regressed under
## `issues/179` — is answered there: the push-down was producing a cheap anchor
## that the plan discarded, because nothing let it drive.


## (SUPERSEDED — see the RESOLVED status at the top. Kept because the reasoning was
## half right in a useful way: it correctly concluded that no single mechanism
## would do it, and correctly predicted that each alone is "worth little or is a
## regression". It named the wrong three.)
##
## Status: ROOT CAUSE FOUND AND FULLY DECOMPOSED — **1,218x available**, from
## three fixes that must land TOGETHER (`issues/179`, the `frame_entity` slot
## columns from `issues/178`, and dropping redundant type constraints). Each
## alone is worth little or is a regression, which is why five separate
## single-mechanism measurements all failed. Nothing built yet.
##
## (superseded status below)
## ROOT CAUSE FOUND. The plan enumerates every frame because the text
## predicate cannot use the trigram index, so there is no cheap way to start
## from the selective end. With `issues/179` applied the simplified query goes
## **1,153,015 -> 3,561 buffers (324x)** and reaches the pinned-set floor. The
**Raised:** 2026-09-09, after `issues/178`, `179`, `180` and `181` each
identified a real mechanism and none of them explained the query's cost.

**Related:** `issues/178` (where this started), `issues/179`, `issues/180`,
`issues/181`, `issues/048` (traversal work), `issues/051` (records 285,348 as
this space's frame count)

## Where the buffers go

Per-node attribution on the reference CONSTRUCT, full result set (425 rows).
Buffers are self, not cumulative — children subtracted:

     self_buf     loops    rows  node
    2,282,796   570,696       0  Index Only Scan rdf_quad_pkey  (q16)
    1,426,700   285,348       2  Index Scan idx_edge_src_dst    (mv1)
    1,141,472   285,348       1  Index Only Scan rdf_quad_pkey  (q9)
    1,141,406   285,348       1  Index Only Scan rdf_quad_pkey  (q5)
    1,141,404   285,348       1  Index Only Scan rdf_quad_pkey  (q8, q15, q14, q11)
    1,141,394   285,348       1  Index Scan term_pkey           (t_v11, t_v16, t_v13)
      856,047   285,348       1  Index Only Scan term_pkey      (t_v14)
      438,981   109,745       0  Index Scan term_pkey           (t_v4, t_v1)

**285,348 is the number of frames in this space** — `issues/051` records it as
exactly the `frame_entity` row count. So the plan visits EVERY frame and runs
about eleven index probes on each: roughly 3.1 million probes, ~15M buffers, to
return 425 rows.

Every probe is individually efficient — index scans, one row each, a few buffers
apiece. Nothing here is a bad access path. The cost is entirely that there are
285,348 of them when the query is looking for 61 entities' frames.

The text filter (`t_v1`, `t_v4`) is the two SMALLEST entries on the list.

## What has been ruled out

Each of these was measured against this query and none of them changes the ~15M:

| candidate | result |
|---|---|
| slot-type tautology precompute (`178`) | one-off 58s generation cost; execution unchanged |
| `frame_entity` collapse (`178`) | 16.17M buffers WITH it enabled — no better |
| null-tolerant join removal (`180`) | removing it made the query 6x SLOWER |
| text push-down (`179`) | 28.4M buffers on the full set — worse |
| pinned 61-entity driving set (`181`) | 14.86M buffers — 6% better |

The last one is the most informative. **Handing the query the exact 61 entities
it is looking for still enumerates all 285,348 frames.** So the plan is not
failing to find a selective entry point; it is not USING one when it is handed
one.

## What that points at, without claiming it

The same traversal in a simplified form — single branch, no UNION, no type
patterns, slots not projected — costs 1.15M buffers with the filter and 3,699
with the pinned set. So driving from the small end IS achievable in PostgreSQL
for this data; something about the CONSTRUCT's shape prevents it.

The differences between the two forms, none of them yet tested in isolation:

  * the UNION of two branches,
  * the `a KGEntity` / `a KGFrame` / `a Edge_hasKGSlot` / `a KGEntitySlot` type
    patterns,
  * projecting the slot variables (which disables the `frame_entity` collapse,
    `issues/178`),
  * the inner `SELECT` subquery wrapper.

`traversal_decision` logged `as-is` for BOTH the filtered and the pinned form,
so the traversal machinery is not choosing the shape in either case. Note that
this means the gate can see neither a text filter (`issues/181`) NOR an explicit
`VALUES` set as a pinned end — which is a wider blindness than `issues/181`
records, and is the first thing to check.

## What NOT to do

Do not propose a fix from this document alone. Five have been proposed and
priced against this query already; all five were real mechanisms and none moved
this number. The rule that came out of `issues/181` applies here too: **a
mechanism measured on a simplified query predicts nothing about the real one.**

The next step is not a fix. It is to find which of the four differences above
turns a 1.15M-buffer plan into a 15.7M-buffer one, by removing them from the
CONSTRUCT one at a time and measuring. That is a bisection, and it is cheap.


## ROOT CAUSE — confirmed 2026-09-09

Attribution of the SIMPLIFIED query (same traversal, single branch, 213 rows):

     self_buf     loops    rows  node
    1,141,394   285,348       0  Index Scan term_pkey (t_v1)   <- 99% of the total
        7,048         3  95,116  Parallel Seq Scan on frame_entity
       ~11,620 everything else combined

The plan seq-scans the WHOLE `frame_entity` table and then probes the term table
once per frame to evaluate the text filter, which matches nothing almost every
time:

    Index Scan using term_pkey on term t_v1 (cost=0.43..0.81 rows=1)
      (actual rows=0.00 loops=285348)
      Filter: (lower(term_text) ~~ '%happy%')
      Rows Removed by Filter: 1

**The selective filter is applied LAST, once per frame.** That is the whole
defect, and it is the same shape at both scales — the CONSTRUCT does ~11 probes
per frame instead of ~1, which is the difference between 1.15M and 15.7M.

### Why the planner chooses frame-first

Because `lower(term_text) ~~ '%happy%'` cannot use the trigram index
(`issues/179`), the only way to START from the text would be a sequential scan
of all 617,455 terms. Frame-first is genuinely the cheaper of the two options
the planner is offered. It is choosing correctly between bad alternatives.

### Proof: give it the third option

With `issues/179`'s fix applied, so the predicate becomes `term_text ILIKE`:

    simplified, WITHOUT 179   1,153,015 buffers
    simplified, WITH 179          3,561 buffers    114 ms      324x
    pinned-set floor (181)        3,699 buffers

    ->  Bitmap Index Scan on idx_wordnet_frames_term_trgm

The frame enumeration disappears entirely, and the result is slightly BETTER
than handing the query its 61 entities by hand — because the trigram lookup is
cheaper than materialising a 61-element VALUES list.

## What this changes

`issues/179` is not a marginal optimisation whose sign depends on `ORDER BY`. It
is the fix for this issue, worth 324x on the shape where it can be measured
cleanly, and it reaches the floor.

The five "failed" candidates in the table above were not wrong about their
mechanisms; they were all aimed at the entity SET, and the entity set was never
the problem. The problem is the ORDER the planner joins in, and only 179 changes
that.

## THE BISECTION — 2026-09-09

With `issues/179` applied, and the slot-type verdict PINNED first so every
variant is generated against the same plan basis (the 2 s bound otherwise makes
the plan depend on buffer warmth — see `issues/178`):

    A  baseline                 23,894 ms   34,747,812 buf   trigram=YES   full-frame probes=21
    B  minus UNION                 TIMEOUT (>900 s)
    C  minus type patterns      10,738 ms   11,847,567 buf   trigram=YES   probes=14
    D  minus slot projection     3,494 ms    5,018,007 buf   trigram=YES   probes=5
    E  minus UNION + types       8,449 ms   13,097,845 buf   trigram=YES   probes=13
    F  minus types + slots       3,014 ms       12,924 buf   trigram=YES   probes=1

**F is 2,700x cheaper than A**, and it needs BOTH removals. Either alone leaves
millions of buffers: slot projection alone (D) is 5.0M, type patterns alone (C)
is 11.8M.

### What each one is

  * **The slot projection** disables the `frame_entity` collapse, because that
    table has no slot columns — this is the projection guard from `issues/178`
    doing exactly what it was written to do. `issues/178` already proposes the
    fix (two `array_agg` columns the sync already has in hand) and priced it at
    1.9x IN ISOLATION. In combination it is worth far more.
  * **The type patterns** are `?e a KGEntity`, `?frame a KGFrame`,
    `?sourceEdge a Edge_hasKGSlot`, `?sourceSlot a KGEntitySlot`. The
    slot-type tautology machinery (`slot_type_tautology`) exists to drop exactly
    this kind of redundant constraint, and covers only the SLOT type. The other
    three are not covered by anything.

### The finding that explains the whole investigation

**The trigram index is used in EVERY variant** — `trigram=YES` throughout. So
`issues/179` works; the entry point exists in all of them. The difference
between 34.7M and 12,924 buffers is not the entry point, it is what the plan has
to do after it.

And that is why every single-mechanism measurement in this family failed. Each
of the three — the text push, the slot columns, the redundant type constraints —
is worth little or is NEGATIVE on its own, and together they are ~2,700x. Five
"failed" candidates were not wrong; they were measured one at a time against a
cost that only moves when they are combined.

This also retires the `?e a KGEntity` measurement recorded as DECLINED in
`issues/178` (1.6%, "noise"). That was measured WITHOUT 179 and WITHOUT the
collapse, in a plan where the type join genuinely did not matter. In the fast
plan the type patterns are worth 388x (D -> F).

### Not yet controlled

`B` timing out at over 900 s says removing the UNION is catastrophic here, which
matches `issues/180`'s separate finding that the single-branch form is 6x worse.
Not investigated.

### CONTROLLED — the same variants without issues/179

                          WITHOUT 179         WITH 179        effect of 179
    A  baseline           15,736,126 buf   34,747,812 buf     2.2x WORSE
    D  minus slots         5,898,944 buf    5,018,007 buf     ~neutral (15%)
    F  minus types+slots     906,202 buf       12,924 buf     **70x BETTER**

`issues/179` is load-bearing — but only once the other two are fixed. On the
shipped query it is a 2.2x regression; on the fixed plan shape it is worth 70x.

**The full composition, baseline to best:**

    shipped today                                    15,736,126 buffers
    + slot columns in frame_entity, + type dropping     906,202     17x
    + issues/179 text push                               12,924     70x
                                                                 ------
                                                                 1,218x

That is the answer to this issue, and to the whole family. Three fixes, none of
which is worth having alone — one is a 2.2x REGRESSION alone — and 1,218x
together.

## The one remaining question

`issues/179` regresses the reference CONSTRUCT (15.7M -> 28.4M on the full set)
while delivering 324x on the simplified form of the same traversal. Both use the
same predicate and the same data. Something in the CONSTRUCT's shape — the
UNION, the four type patterns, the projected slot variables, or the subquery
wrapper — prevents the planner from using the trigram entry point.

That is now a narrow, well-posed question, and the bisection described below is
how to answer it. It is the only thing standing between this issue and a 324x.


## Implementation — 2026-09-09

### Which type constraint actually costs (bisected per class)

The earlier bisection removed all seven type patterns as a block. Splitting them,
with the slot-type verdicts pinned so the plan basis is constant:

    all type patterns      6,185,137 buffers
    minus ENTITY types     6,182,837      (-2,300)        ~0
    minus FRAME  type      4,051,066      (-2,134,071)    1.5x
    minus EDGE   types       914,457      (-5,270,680)    6.8x   <- essentially all of it
    minus SLOT   types     6,185,133      (-4)            0, already dropped
    minus ALL    types       903,218                      6.8x

Two corrections to this issue's earlier text fall out of that:

  * **The `?e a KGEntity` measurement recorded as DECLINED in `issues/178` was
    RIGHT** — 2,300 buffers, noise. This issue later claimed it was "worth 388x
    in the fast plan"; that 388x came from removing all seven patterns and was
    attributed to the wrong class. Retracted.
  * The SLOT type constraints already cost nothing, because
    `slot_type_tautology` drops them. That mechanism works; it is the other
    classes that have no equivalent.

### What was built

**`frame_entity` slot columns** (`issues/178`) — done, migrated, verified.

**Edge type absorption** — `?edge a <T>` now becomes a predicate on
`edge.edge_type_uuid`, a column `issues/060` added and `rewrite_edge_table`
never used. Gated by `edge_type_agreement.edge_type_absorbable`, because the
column is populated from VITALTYPE and an `rdf:type` constraint is equivalent
only where the two agree in this space — measured here as 570,696 edges, 0
missing `rdf:type`, 0 disagreeing, but `sync_edge_table` documents a space where
it fails. Absent or unanswerable verdict keeps the join.

No new constraint is emitted: `_remap_constraint_sql` turns the existing
`qN.object_uuid = <const>` into `mvN.edge_type_uuid = <const>` from the
alias_map entry, and the predicate constraint is dropped with the alias.

### Measured, end to end, correctness verified

    reference CONSTRUCT, before   10,796 ms   15,736,125 buffers   rdf_quad=13
    reference CONSTRUCT, after     4,133 ms    5,623,363 buffers   rdf_quad=9

(Both unpinned, so both are subject to the verdict swing; the pinned comparison
below is the trustworthy one — 6,185,137 -> 914,457.)

The output is identical to the
rewrites-disabled ground truth: 425 rows, zero diff on all six columns, slot
NULL counts 0.

### RESOLVED — the absorption delivers the full 6.8x

An earlier revision of this section recorded an unexplained gap: removing the
edge type patterns measured 914,457 buffers while absorbing them measured
5,623,363. **The gap was a measurement error, not a defect.** The absorption run
was taken with the slot-type verdict EXPIRED (the 2 s bound) and compared
against a baseline where it was PINNED — two different plans, because an expired
verdict keeps the slot-type constraint and emits it as a semi-join worth ~12.4M
buffers (`issues/178`).

Re-measured with the verdict pinned in both:

                            BEFORE absorption    WITH absorption
    0 all type patterns       6,185,137 buf         914,457 buf     6.8x
    3 minus EDGE types          914,457 buf         914,456 buf

With absorption the query carrying all seven type patterns costs **exactly what
deleting the edge patterns costs**, and removing them makes no further
difference. The absorption is equivalent to deleting them, which is what it was
built to be.

**The lesson is the verdict, not the absorption.** A 2.9x plan swing driven by
whether a 2 s budget happened to be enough invalidated a measurement in this
issue and would invalidate any that follows. Every measurement in this family
must pin the verdict first, and `issues/178` now records that as the blocker it
is.

## REVERTED — absorption returns empty results on the criteria/sort shapes

Absorbing `?edge a <T>` into `{space}_edge.edge_type_uuid` broke **8 integration
tests**, every one by returning NO rows:

    tests/integration/test_kgquery_sort_projection.py     5 failed
    tests/integration/test_kgquery_bindings_are_named.py  3 failed

    AssertionError: the sorted criteria query returned no bindings
    AssertionError: asc: expected ['e1', 'e3', 'e2', 'e0'], got []

Bisected file-by-file against a clean HEAD worktree: they pass at HEAD, and
copying this ONE file in takes the failure count from 0 to 8. Reverting it
restores all 9 to passing.

The gate reports `ABSORBABLE` on those spaces and the rewrite then fires:

    edge-type agreement: inttest_... rdf:type vs edge_type_uuid -> ABSORBABLE
    Edge table rewrite: absorbed ?sort_slot_edge_0 type constraint q3 into mv0.edge_type_uuid

So the verdict and the rewrite disagree about what the column means. Two
candidates, not yet separated — the test spaces are torn down after the run, so
neither could be confirmed post-hoc:

  * **The agreement check is vacuously true.** `edge_rows` is fetched and then
    never used except as a cache key; on an EMPTY edge table the counterexample
    query returns nothing and the verdict is "agrees". Same class as the empty-
    table problem that made `frame_entity` look healthy on 38 of 41 spaces.
  * **The absorption maps a variable it should not.** It walks `var_slots` for
    any variable positioned on `edge_uuid` and rewrites every constant-object
    quad on that subject, keyed only by predicate.

**Correctness beats the 6.8x.** The measurement in this issue stands; the
mechanism does not. Anything that revives it needs the zero-row guard AND a test
on these two files, which is where it would have been caught immediately.

Note the reverted optimisation is NOT load-bearing for `issues/178`: with it
removed the reference CONSTRUCT is unchanged, because its edge patterns are
collapsed into `frame_slot` before the edge rewrite is reached.
