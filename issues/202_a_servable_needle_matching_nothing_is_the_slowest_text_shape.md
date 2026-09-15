# A Servable Needle Matching Nothing Is the Slowest Text Shape

## Status: OPEN, found 2026-09-14 while writing the text bench for `issues/192`.
## DIAGNOSED AND CONFIRMED 2026-09-15 (below): the cost is a missing early
## exit, not the text index. `emit_slice` correctly declines the fast plan for
## text filters; the fallback has no way to stop early. Plans captured.

A SIX-character needle — long enough that the trigram index can serve it — that
matches nothing is the most expensive text query measured, and it does not
finish at all on the 100k fixture.

    fixture  needle                 warm exec   rows
    10k      "LLC"      matching       56.8 ms    25
    10k      "ZQ"       UNSERVABLE    611.9 ms     0
    10k      "ZZQQXX"   servable, 0 matches  3,289.8 ms   0
    100k     "LLC"      matching       47.0 ms    25
    100k     "ZQ"       UNSERVABLE    TIMEOUT (>15 s)
    100k     "ZZQQXX"   servable, 0 matches  TIMEOUT (>15 s)

Warm figures, second pass; the first pass is slower but the ordering is
identical. `SELECT count(*) FROM sp_lead_synth_10k_term WHERE term_text ILIKE
'%ZZQQXX%'` returns 0, so there is genuinely nothing to find.

**The servable-empty needle is 5x slower than the one the index cannot serve.**
That is backwards. `MIN_TRIGRAM_NEEDLE = 3` exists precisely because short
needles cannot use the index; a long needle can, and returning nothing should be
the cheapest thing it ever does.

## This is what the failing ordering test has been reporting

`test_paging_fence_covers_every_shape::test_the_three_text_needle_regimes_stay_ordered`
fails with:

    an empty SERVABLE needle (1,475,498) cost as much as an UNSERVABLE one
    (510,486)
    assert 1475498 < 510486

It is the single hole in `coverage.json`. It was easy to read as a stale
expectation — `issues/070` did make the unservable path much cheaper (78,991 ms
exact probe -> 45 ms sampled), so "unservable is no longer worst" sounds like
the fix working. **That reading is wrong.** Unservable did not get cheap enough
to overtake; servable-empty got pathological. The buffer counts and the wall
clock agree.

## Why no bench caught it

There is none. `issues/192` lists fuzzy/text as correctness-tested with zero
bench cells, and the ordering test asserts a RELATION between the regimes
without recording their values — so a regime could degrade by orders of
magnitude while the assertion still passed, right up until it crossed another
regime. The drift was invisible until it inverted.

## What this blocks

The text bench for `issues/192` cannot be written as intended. A query-tier
bench must be fast, and two of its three regimes do not finish in 15 seconds.
Writing it with a generous timeout would be papering over this: a read-only
query taking minutes is not a tier-placement question, it is a defect.

So the bench waits on this. When it lands it should record all three regimes'
values, which is the thing that would have caught this as drift rather than as
an inversion.

## Diagnosed 2026-09-15 — the guard in `emit_slice` is why, and it is CORRECT

The question above was "is it reaching the trigram index at all". The answer is
that the index is not the issue: what is missing is an EARLY EXIT, and the
reason it is missing is a correctness guard that names this exact needle.

`emit_slice._selective_driven` declines whenever the selective side is a text
criterion (`emit_slice.py:630-636`):

    A constant criterion (`WV`) binds object_uuid inside the BGP, so driving
    from it is sound. A text criterion is a pushed FILTER, so driving from its
    BGP drops the ILIKE entirely -- measured: `contains 'ZZQQXX'` returned 25
    rows for a substring matching nothing.

So the fast plan is refused for text, and refused RIGHTLY: taking it returns 25
rows for a needle that matches none. The query falls back to a plan where the
ILIKE is a filter ABOVE the join, and that is what makes the three regimes order
the way they do:

    matching ("LLC")      LIMIT 25 is satisfied after a few candidates   47 ms
    servable-empty        nothing matches, so NOTHING short-circuits --
                          the whole candidate set must be enumerated to
                          prove the answer is zero                   3,290 ms
    unservable ("ZQ")     declined earlier, taking the sampled probe
                          path of `issues/070`                          612 ms

The servable-empty case is not paying for the text search. It is paying for
LIMIT never being reached. That is why it beats the unservable case: being
declined EARLY is cheaper than being served by a plan with no early exit.

This also explains why it scales so badly: cost tracks the candidate set, so
10k -> 100k turns 3.3s into a timeout, while the matching needle stays flat
(56.8 -> 47.0 ms) because it still stops at 25.

### What the fix is, and what it is not

NOT raising `MIN_TRIGRAM_NEEDLE`, and not a tier or timeout change. The comment
names the fix: "teaching the driver to carry pushed filter conditions". With the
ILIKE carried into the driver, the selective-driven plan becomes sound for text,
the trigram index drives the join, and an empty needle becomes the CHEAPEST
case rather than the most expensive -- which is the property `issues/070`
already assumes when it sets `MIN_TRIGRAM_NEEDLE = 3`.

Until then the guard must stay. Removing it trades a slow correct answer for a
fast wrong one, and `issues/046` records what that costs.

### CONFIRMED by the plans, 2026-09-15

Captured on `sp_lead_synth_10k` through the same `_criteria_to_gen` path the
bench uses, `EXPLAIN (ANALYZE, BUFFERS)`:

    matching "LLC"        exec    341.7 ms   buffers     7,516
    servable-empty        exec 19,500.6 ms   buffers 1,681,156 (+1,314 read)

224x the buffers for the same query shape, and the plans say why in one line
each:

    matching        ->  Limit ... (actual ... rows=25.00 loops=1)
                        Index Only Scan ... Rows Removed by Filter: 40
    servable-empty  ->  Limit ... (actual ... rows=0.00 loops=1)
                        Nested Loop (cost=1311.63..7827220.29 rows=164916 ...)

The matching needle stops after examining a handful of candidates because LIMIT
25 is reached. The empty one runs the Nested Loop to exhaustion because it never
is. The text predicate appears as `Filter: EXISTS(SubPlan 1)` ABOVE the join,
exactly as the `emit_slice` guard implies -- it is not driving anything, so
there is no index probe to return empty cheaply.

Nothing here is about the trigram index being unusable. The 6-character needle
is servable; it is simply never given the chance to drive.

## Attempted 2026-09-15, REVERTED — the blocker is a layer above `emit_slice`

The fix `emit_slice` names ("teach the driver to carry pushed filter
conditions") was implemented and backed out, because the driver is never
reached for this shape. What the attempt established:

**1. The driver is already correct, and already carries the ILIKE.**
`filter_pushdown` pushes the text condition INTO the BGP
(`term_type = 'L' AND (term_text ILIKE ...)`), so `emit_bgp_anchor` emits it in
the BGP's own WHERE. A differential run — same query with
`_text_leaf_should_drive` forced False — returns an IDENTICAL row set, driven
and undriven, for both the matching and the empty needle. So the comment's
warning ("driving from its BGP drops the ILIKE entirely") describes a state the
pushdown has since closed for this shape. A carrier added on top is INERT: it
fires on no path, which is why it was reverted rather than kept.

**2. The empty needle never reaches the driver at all.** Instrumented, it
declines with `no 2-child JOIN within 6 hops` — the plan has no join to drive.
The matching needle does get one and is already driven (`DISTINCT ON` in its
SQL).

**3. The plan shape is decided in `mark_semijoins`, and the decision is
CORRECT.** It splits BGPs speculatively, then REVERTS any split the gate did
not mark, because "a split BGP is only equivalent to the original as a
semi-join" — keeping an unmarked split returns wrong rows (`issues/030`:
0 rows instead of 96). The gate computes `sel = matches / candidates` and marks
only when `sel >= MIN_SELECTIVITY`. An empty needle is `sel = 0`, so it refuses
to probe — rightly, since probing an empty needle walks every candidate, which
is `issues/070`'s pathology — and takes the set-based join instead.

So all three plans are individually defensible and none is good:

    probe (semi-join)   walks every candidate to find nothing   refused, rightly
    set-based join      materialises the match set              chosen, and slow
    text-driven         would be right                          plan reverted first

### What the fix actually requires

Not a carrier in `emit_slice`. The split has to SURVIVE for a measured-selective
text leaf, in a form that is equivalent without being a semi-join — or
`emit_slice` has to learn to drive from a text leaf inside a SINGLE unsplit BGP,
where `reorder_bgp` already pins it first for join order.

Either is a change to plan shaping rather than to emission, and the revert
logic it touches is what stops a split from silently returning wrong rows. That
is the reason this was stopped rather than pushed through: the guard being
worked around is load-bearing, and `issues/030` and `issues/046` both record
what shipping past one costs.
