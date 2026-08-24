# The Fence Bench Skips Six Shapes, for Two Reasons and Neither Is the Fence

## Status: FIXED 2026-08-22 (`4c61499`). Both bench defects corrected; six
## skips are now one, and that one is honest. The product question this
## uncovered went to `issues/118` and was downgraded there.

`test_paging_fence_covers_every_shape` reports:

    SKIPPED [6] ... neither plan finished within the probe timeout

Which reads as "six shapes are pathological". They are not. All six are on the
100k fixture, and they split into two unrelated causes:

    100k  range-tight  specific  p25, p100      cold cache
    100k  contains     generic   p25, p100      a needle that cannot match
    100k  contains     specific  p25, p100      a needle that cannot match

## Cause 1 — the probe is unwarmed, so the timeout measures the buffer pool

`range-tight / specific` looks catastrophic on the bench's single cold probe
and ordinary once warm. Measured cold-first, then warm with both sides
pre-loaded and the two alternating, median of three:

    | cold (bench's probe) | warm, median of 3
    unfenced   |  64.5s               |  5.32s   3,529,541 buffers
    fenced     |   9.1s               |  4.15s   2,511,504 buffers
    ratio      |  7.1x                |  1.3x    1.41x buffers

The 7.1x is the buffer pool, not the plan — the first probe pays to pull a
22 GB fixture's working set into a 16 GB pool. This is the same distortion that
turned `issues/060`'s 31x into 6.5x, and `issues/081` exists because of it.

Warm, the fence is 1.41x cheaper in buffers, **below the bench's own
`DECISIVE = 2.0` gate**, so `needs_ordered_scan=False` is a defensible
judgement here. There is no defect in the shape — only in probing it cold.

**Fix:** run one throwaway probe per shape before timing, so the timeout
measures the plan rather than the cache.

## Cause 2 — the `contains` needle cannot match the slot it queries

`_contains_criteria("CAL")` filters `urn:acme:kg:slot:CompanyStateCode`. That
slot holds **two-letter codes**:

    CA x9,220   TX x7,337   FL x6,528   NY x5,531   IL x3,713   PA x3,610

`"CAL"` matches none of them. ("California" exists in the fixture, 13,000
times, but on a different slot — which is what makes the needle look
plausible.) `contains` is case-insensitive on both paths
(`CONTAINS(LCASE(?v), LCASE(...))`), so case is not the problem; length is.

The consequence is that the bench is not measuring a fence decision at all.
With no match the `LIMIT` never fills, so both plans do the complete walk:

    loops=100,000   rows=0   31,138,227 buffers   ~105s

Both sides are equally slow because both are exhaustive. The comparison is
degenerate, and the 10k fixture passes only because the same futile walk is
ten times smaller and finishes inside 20 s.

A needle that matches behaves completely differently:

    needle 'CAL'  generic    TIMED OUT at 20s
    needle 'CAL'  specific   TIMED OUT at 20s
    needle 'CA'   generic     8.21s    4,044,630 buffers      <- 8x fewer
    needle 'CA'   specific   TIMED OUT at 20s

**Fix:** probe with a needle the slot can hold. If an empty result is worth
covering — and it probably is, since it is the worst case for paging — it
should be its own named shape (`contains-nomatch`) that ASSERTS the exhaustive
walk, rather than arriving disguised as a timeout.

## What is still open

~~**`contains` + the specific entity type stays over 20 s even with a matching
needle**~~ MEASURED 2026-08-22, and it is real: **`issues/118`**.

Warm, alternating, median of three: 6.37s / 4,043,455 buffers for the generic
entity type against 62.56s / 23,861,490 for the specific one — 9.81x time,
5.90x buffers, for a predicate that selects the identical 100,000 entities and
therefore filters nothing. Intermediate rows expand to 800,000 in the specific
arm where the generic arm holds flat at 100,000.

So of the three things behind these six skips, two are defects in this bench
and one is a product problem that the bench's timeout was hiding.

## Fixed

**Cause 1 — the cold probe.** Both plans now run once, untimed, before either
is measured. `_warm` has its own 120 s budget: the warm-up is the run that pays
for the cache misses, and bounding it separately keeps a genuinely pathological
shape from hanging the suite.

**Cause 2 — the needle.** The shape moved off `CompanyStateCode` entirely.
Matching was necessary but not sufficient: on a two-letter slot every matching
needle is at most two characters, and `MIN_TRIGRAM_NEEDLE = 3`, so a "fixed"
needle of `"CA"` would have measured the unservable path instead — 1,276,968
buffers against 138,369 for a servable needle. It now probes `CompanyName`
(average 21 characters, hanging off the same `CompanyFrame` parent) with
`"LLC"`: three characters, servable, 41 distinct matches.

**Result: 6 skips became 1.** The survivor is
`p100-range-tight-specific-100k`, which does not finish either way even warm —
so the skip now means what it says.

## And the empty-result case got a test that is actually true

It was going to be a shape asserting that an empty result costs the whole walk.
That was assumed, and measuring it showed it false: a SERVABLE needle matching
nothing is answered from the index and is cheap. The ordering that does hold,
now pinned on the 10k fixture:

    servable + matches      6,528 buffers   the LIMIT short-circuits
    servable + no match   138,357 buffers   nothing to short-circuit on
    UNSERVABLE (2-gram) 1,276,968 buffers   the index cannot help

Emptiness costs something. Unservability costs far more. The two-character
needle is kept deliberately, so the cost of the `MIN_TRIGRAM_NEEDLE` decision
stays visible rather than becoming folklore.

## Re-verified 2026-08-24 — still exactly one skip, and it is stable

Checked while chasing an unrelated perf regression, so the observation is
incidental but worth keeping: `test_paging_fence_covers_every_shape` reports

    SKIPPED [1] ... neither plan finished within the probe timeout

on EVERY clean run — on `main`, on a feature branch, and before and after a
change that moved 48 other perf cases. The count did not vary once across a
dozen runs.

That stability is the useful part. A skip that comes and goes is a flaky probe
and should be chased; one that is identical in every run is a fixed property of
the shape, which is what this issue concluded. It can be used as a baseline: a
run reporting anything other than `SKIPPED [1]` here has changed something
real.

**The survivor is `p100-range-tight-specific-100k`**, as recorded above — the
shape that does not finish either way even warm. Worth stating plainly because
it is easy to misremember as the `contains` case: `contains` LOOKS like the
obvious candidate, having been half the original six and carrying the
`MIN_TRIGRAM_NEEDLE` problem, but it was FIXED here by probing `CompanyName`
with `"LLC"`. I made exactly that error reading this issue back, which is the
argument for the sentence rather than against it.

Not re-measured. This note records the count and which case, not a fresh
timing — the 20s probe against a 22 GB fixture is the reason this is a skip in
the first place.
