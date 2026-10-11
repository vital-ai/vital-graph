# A UNION-Bound Variable Forces A Null-Tolerant Join, And LIMIT Stops Working

## ARCHIVED 2026-10-11 — correctness fixed (COALESCE in emit_join, and distribution); the performance half re-measured on current code: distribution + merge wins every shape, including the ORDER BY + LIMIT one that cost 2x before the merge. Nothing remaining. Evidence: the last section.
## Status: CORRECTNESS FIXED 2026-09-09 — the join is distributed over the union, so
## every projected variable is bound (`tests/integration/test_join_distributes_over_union.py`).
## PERFORMANCE OPEN: that rewrite exactly doubles the work on an ORDER BY + LIMIT
## shape (31.2M vs 15.6M buffers) and has no gate. Header corrected 2026-10-11.
##
## Was: SPLIT after measurement. The CORRECTNESS half is CONFIRMED and open:
## the join merges compatible solutions in its condition but not in its
## projection, so bound values are lost (`COALESCE` is absent from the generated
## SQL entirely). The PERFORMANCE half is **REFUTED** — removing the
## null-tolerant join makes this query 6x SLOWER, not faster. What actually
## governs cost is whether ORDER BY + LIMIT can be satisfied incrementally.

**Raised:** 2026-09-09, profiling the reference happy-frame CONSTRUCT while
working `issues/178`. Split out from it as a separate mechanism.

**Related:** `issues/178` (where it surfaced, and which records the 212/213 NULL
split this explains), `issues/179` (the other half of the same profile),
`vitalgraph/db/sparql_sql/var_scope.py`, `emit_union.py`

## The defect

When a variable is bound in only some branches of a UNION, the generator emits a
null-tolerant join predicate:

    Join Filter: ((v8__uuid IS NULL)  OR (v8__uuid  = q15.object_uuid))
             AND ((v10__uuid IS NULL) OR (v10__uuid = q9.object_uuid))

`(a IS NULL OR a = b)` is neither an index condition nor a hash key. So the join
degrades to a nested loop over a **fully materialised** inner side, with the
predicate applied afterwards — and because the filter sits ABOVE the join,
`LIMIT` cannot push down through it.

## Measured

`EXPLAIN (ANALYZE, BUFFERS)` on the generated SQL, a `LIMIT 10` query:

    Limit  rows=10   Buffers: shared hit=1,738,342   Execution Time: 1,464 ms
      Nested Loop
        Join Filter: (as above)
        Rows Removed by Join Filter: 16,162
          outer: Gather Merge -> 1 row
          inner: Materialize  -> 16,172 rows   (855,245 buffers)

**16,172 rows built, 16,162 discarded, to return 10.** The inner side is a tower
of ~13 nested loops accumulating ~65,000 buffers per level, several of them
joined by a post-hoc `Join Filter: (q16.subject_uuid = q14.subject_uuid)` rather
than an index condition.

The traversal side is 855,245 of the 1,738,342 buffers. The other 883,066 are
`issues/179` and are independent of this.

## The part that makes it a defect and not a cost

**The variables should not be unbound.** The shared BGP that runs AFTER the
union binds both:

    ?sourceSlot      <hasEntitySlotValue> ?sourceSlotEntity .
    ?destinationSlot <hasEntitySlotValue> ?destinationSlotEntity .

`Join(Union(A,B), C)` where `C` binds both means neither is unbound in any
solution. Yet across the full 425-row result **no row has both bound** — 212
NULL on one, 213 on the other, 212 + 213 = 425, exactly one per row. Measured
identically with the frame-entity and edge rewrites disabled, so it is not a
rewrite artefact.

So the null-tolerance is compensating for bindings the plan is losing somewhere,
and the unindexable join is the downstream cost of that loss.

## What to establish, in order

1. **Why the post-UNION BGP's bindings are lost.** This decides everything else:
   whether the fix is "bind them properly, then emit plain equality" or "detect
   when null-tolerance is unnecessary and drop it". Start at `compute_scope`'s
   `merge_union` / `merge_join` and at how `emit_union` projects branch
   variables.
2. **Confirm plain equality actually helps**, by hand-editing the generated SQL
   to `v8__uuid = q15.object_uuid` and re-running `EXPLAIN ANALYZE`. If the plan
   does not improve, the diagnosis is wrong and nothing should be built on it.
   `issues/178` records a day lost to skipping exactly this step.
3. Only then decide what to change, and price it on a shape that is not this one
   query.

## What is NOT established

- Whether this generalises beyond UNION-with-shared-BGP.
- Whether the ~13-level nested-loop tower is itself reasonable, or a second
  problem sitting underneath this one. Its per-level buffer growth was measured;
  its necessity was not examined.
- Whether `LIMIT` push-down is achievable at all for this shape even with a
  plain equality join.




## CONFIRMED — the correctness half

The generated SQL contains **no `COALESCE` at all**. The union branches are:

    left  (ul0):   ul0.v0 AS v10   +  NULL AS v8      binds sourceSlotEntity only
    right (ur0):   ur0.v3 AS v8    +  NULL AS v10     binds destinationSlotEntity only

    join:  ON (j0.v8__uuid  IS NULL OR j0.v8__uuid  = j1.v17__uuid)
          AND (j0.v10__uuid IS NULL OR j0.v10__uuid = j1.v14__uuid)
    projects: j0.v8, j0.v10        <- the UNION side, i.e. the NULL

SPARQL merges compatible solutions so the BOUND value wins: for
`mu1(v unbound)` joined with `mu2(v = x)`, the result has `v = x`. This SQL
implements compatibility in the join CONDITION — correctly — and not in the
PROJECTION. The chain is `u0.v8 -> j0.v8 -> p0.v8`, taking the union side at
every level.

The fix is `COALESCE(j0.v8, j1.v17)` and the same for every companion column
(`__uuid`, `__type`, `__lang`, `__datatype`, `__num`, `__bool`, `__dt`).

This is the 212/213 NULL split, and it is **also the third missing CONSTRUCT
triple in `issues/178`** — `urn:hasSourceSlotEntity`, the one the projection
guard did not explain. Same root cause, now identified.

## The performance half — RE-ESTABLISHED 2026-09-09, after being wrongly refuted

The refutation below deleted a UNION branch, which changes the QUERY. Deleting
the predicate instead — by distributing the join over the union so each arm
carries a plain equality — shows the predicate is exactly the blocker, for a
reason the refutation never tested:

**A null-tolerant join cannot be an index condition, so a small driving set
cannot cross it.** `issues/183` traced the reference CONSTRUCT end to end: the
text-filter anchor in `reorder_bgp` already works, each UNION branch is reduced
to 61 entities cheaply, and then the entity set DIES at this join. The
traversal is computed over all frames and filtered afterwards.

    driving from the matched entities (hand-written SQL)      307 buffers
    the same answer through the null-tolerant join      5,151,495 buffers

### Distribution: implemented, correctness half CONFIRMED, row count WRONG

`rewrite_distribute_union.distribute_join_over_union` rewrites
`Join(Union(A,B), C)` to `Union(Join(A,C), Join(B,C))`, cloning `C` with fresh
aliases. Wired in and measured:

  * **the null-tolerant predicates disappeared** — 2 to 0 in the emitted SQL;
  * **the NULLs disappeared** — `sourceSlotEntity` and `destinationSlotEntity`
    went from 212 and 213 NULL to **zero**, which is the correctness defect this
    issue documents, fixed;
  * **and the row count fell from 425 to 213**, so it is REVERTED.

212 + 213 = 425 and the result is 213, which points at one arm being lost or the
two arms collapsing into one — the emitted UNION deduplicating, the clone
sharing state with the original, or the emitter mishandling a UNION whose
children are JOINs. Not diagnosed.

### FIXED and wired 2026-09-09

The row loss was the alias RENAMING in the clone, and the renaming was both
wrong and unnecessary. Aliases appear in `var_slots`, in the constraint strings,
in `leaf_terms`, in `range_leaves` AND in the parent join node; missing any one
leaves part of an arm pointing at the other arm's tables, and that arm then
matches nothing. A SQL alias only has to be unique within one SELECT scope, and
the arms are separate SELECTs under `UNION ALL`, so both may use `q5`. The deep
copy remains solely so later in-place rewrites cannot mutate one arm through the
other.

Result on the reference CONSTRUCT: **425 rows, every projected variable bound,
zero NULLs** where `sourceSlotEntity` and `destinationSlotEntity` were NULL on
212 and 213 rows. Same rows, now carrying the bindings the query gives them.
That also recovers the third missing triple of `issues/178` —
`urn:hasSourceSlotEntity` — which the projection guard never explained.

`tests/integration/test_join_distributes_over_union.py` pins it: row count
preserved, no projected variable unbound, both arms contributing, no
`IS NULL OR` surviving. Verified to FAIL with the renaming reintroduced.

### The cost: it doubles work on ORDER BY + LIMIT

Three paired runs in one process, so both conditions share a tautology branch:

    distribution ON    31,152,935 buffers (+/-2)   13.2-15.1 s
    distribution OFF   15,578,409 buffers (exact)   4.6-5.0 s

**Exactly 2.0000x.** That is `C` evaluated once per arm, which is what
distribution does, with none of the benefit realised — `full_sort=True` in both,
so `ORDER BY` + `LIMIT` computes everything regardless and an indexable per-arm
join saves nothing.

On the full result set the same rewrite is worth 6.1x (15,736,127 -> 2,593,983).
So the rewrite is right for some shapes and wrong for others, and it currently
has no gate. The obvious candidate — do not distribute when the plan will sort
everything anyway — is a guess; it has not been measured, and the sort decision
is not available where the rewrite runs.

**Kept enabled** on the strength of the correctness fix, which is not
shape-dependent. The 2x on one shape is a known, measured cost, not a surprise
waiting to be found.

The claim was that the null-tolerant predicate is unindexable, forces the inner
side to be materialised, and is therefore the cost. Tested by deleting the
second UNION branch from the reference query, which removes the disjunction
entirely:

    reference, with UNION      758 ms    1,738,177 buffers   disjunctive preds = 2
    single branch, no UNION  4,655 ms   19,418,229 buffers   disjunctive preds = 0

**6x slower and 11x the buffers with the disjunction GONE.** The null-tolerant
join co-occurs with the FAST plan, not the slow one. Nothing should be built on
the theory that removing it helps.

## What the three measurements actually agree on

    baseline (Limit -> Gather Merge over a Sort)        758-1,464 ms    1.7M buffers
    text filter pushed (Result -> Sort -> Nested Loop)     24,586 ms   36.4M buffers
    UNION branch removed                                   4,655 ms   19.4M buffers

The query is cheap in exactly one case: when the plan can satisfy
`ORDER BY ?entity` incrementally and stop after ten rows. Both perturbations
destroyed that path and both cost 10-20x, by different routes and with no
predicate in common.

So the thing that governs cost here is **whether LIMIT can stop early**, not any
individual predicate. That is the shape a fix has to protect, and it is also
what makes this query fragile: it is one planner decision away from twenty
seconds.

## What is NOT established

- Whether the incremental path can be made ROBUST rather than lucky. It
  currently depends on the planner choosing a sorted union feed, which nothing
  in the generator asks for or guarantees.
- Whether `COALESCE` in the projection changes performance at all. It should be
  neutral — it does not touch the join condition — but that is an expectation,
  not a measurement, and this issue has now been wrong twice about which
  mechanism dominates.
- What the cost looks like WITHOUT `ORDER BY` + `LIMIT`, which is the shape most
  real queries take. Every measurement here is of a top-10 query.

## The 2x cost is gone: re-measured 2026-10-11

The 2.0000x above was measured before `merge_bgp_joins` joined the rewrite
(`35cf5616`, which measured 362x on this query). Re-measured on current code on the
test stack's `wordnet_frames` (10.3M quads), distribution ON vs patched to the
identity (OFF), 5 alternating runs per cell, fenced exactly as the executor fences
(`test_scripts/perf/_issue180_distribution_gate.py`):

| shape | ON buffers | OFF buffers | ON ms min/med | OFF ms min/med |
|---|---|---|---|---|
| full result | 38,047 | 15,579,252 | 32.0 / 66.6 | 7,061.7 / 7,126.1 |
| `ORDER BY ?entity LIMIT 10` (the shape this issue measured) | 38,047 | 15,579,253 | 32.1 / 42.4 | 6,485.3 / 7,101.3 |
| `ORDER BY ?frame LIMIT 10` | 38,047 | 15,579,268 | 33.6 / 42.8 | 9,954.5 / 10,272.3 |
| `LIMIT 10 OFFSET 20` | 2,635 | 910,890 | 2.5 / 2.9 | 627.6 / 674.4 |

**ON wins every shape, ~170x on the ORDER BY + LIMIT shape that cost 2x before.**
The full result is identical (425 rows, same multiset digest). Both top-10s are
valid answers: their `?entity` values are exactly the 10 smallest, and every row is
in the full result; the digests differ only by which tied rows were picked. The
null-tolerant predicates are 0 ON, 2 OFF. So the gate this issue asked for is not
needed: there is no shape here where distributing loses.

A paging check across all 43 pages: ON partitions the 425 rows exactly, while OFF
repeats 24 and drops 24. That is not a defect in either. This query projects six
variables, so `_anchor_var_for_paging` imposes no order (`collect.py:629`), and
LIMIT/OFFSET with no ORDER BY is unordered by definition. ON partitions because its
plan happens to be deterministic, not because anything guarantees it.

Side note: generation took 5.5 s here, all of it `slot_type_tautology` giving up
at its 5 s budget. The fixture space has never had a maintenance cycle to
precompute that, as the warning says (`issues/178`).
