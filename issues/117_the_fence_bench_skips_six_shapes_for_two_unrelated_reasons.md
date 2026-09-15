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

## 2026-09-14 — it now FAILS rather than SKIPS in a serial run, and costs four
## other cells with it

The note above says "a run reporting anything other than `SKIPPED [1]` here has
changed something real". It reported FAILED, so that criterion fired — but what
changed is not the shape. Checked rather than assumed: re-run ALONE immediately
afterwards, it passes. That is exactly the boundary the bench's own comment
describes ("failed here at ~70% of a long serial run and passed alone minutes
later"), and the one retry at the warm budget was not enough to cross it on a
fixture that `issues/204` had just made ~48% larger.

The cost is not the single red cell. When it fails, the sweep stops, and every
cell after it goes UNRECORDED — so `coverage.json` was promoted with FIVE holes
where the previous baseline had two:

    p100-range-tight-specific-100k   failed      (the shape itself)
    p100-contains-specific-100k      unrecorded  } collateral: the sweep
    p100-eq-common-specific-100k     unrecorded  } never reached them
    p100-range-loose-specific-100k   unrecorded  }
    p25-range-tight-generic-100k     unrecorded  }

So a known, load-dependent flake in ONE shape silently removes gating from four
others. Those four have no recorded values to compare against, and nothing in
the promotion says why — it reads as though they were never benched. That is
the part worth fixing: the cells are independent measurements and one of them
timing out should not take the rest of the sweep down with it.

Updating the criterion this issue offered: anything other than `SKIPPED [1]`
means something changed, but "something" includes the fixture getting bigger
and the suite running longer, not only the shape regressing.

## 2026-09-15 — the retry budget is NOT the lever, and neither is the warm-up

This issue offered the criterion "a run reporting anything other than
`SKIPPED [1]` here has changed something real", and suggested the retry budget
as the lever. Both were tested and neither holds.

**The budget is not it.** It is already `WARM_TIMEOUT_MS = 120_000`, and the
cell PASSES ALONE at that budget. So 120 s is not the difference between
passing alone and failing in a serial run.

**The warm-up pairing is not it either.** Hypothesis: `_warm` warmed both plans
up front, unfenced then fenced, so on a 22 GB fixture in a 16 GB pool warming
the second evicts the first one's set and the first probe runs cold anyway —
which would explain an outcome that depends on pool pressure. Implemented as
pairing each warm-up with its own probe, with the retry re-warming too, then
measured across a full coverage tier:

    before   37 min   1 failed / 48 passed   hole: p100-range-tight-specific-100k
    after    51 min   1 failed / 48 passed   hole: p100-range-tight-specific-100k

Same cell, same hole, and 14 minutes slower — the retry re-warm costs most of
that on the slow shapes. REVERTED (`90544013`): it fixes nothing observable and
makes the tier 38% longer.

**What the next attempt needs first.** Not another hypothesis. The assertion
text has never actually been read: the tier is launched with `| tail -N`, which
truncates the traceback, and the cell cannot be reproduced alone. Capture the
full pytest output for the failing cell — specifically WHICH assertion fires
(`fenced is None` with the flag set, `unfenced is None` with it unset, or the
buffer comparison) — before changing anything. Two attempts have now been spent
guessing at a message that was never in hand.

## 2026-09-15, investigated properly — the cell OSCILLATES, and both outcomes are holes

The assertion text still has not been read, and that is now a finding rather
than an omission: across five coverage runs the cell reached an assertion three
times and skipped twice, and it skipped on the run that was captured in full.

    run 1  pre-fix          FAILED    37 min
    run 2  record() fix     (202 failed instead)
    run 3  202 fixed        FAILED    37 min
    run 4  warm pairing     FAILED    51 min
    run 5  reverted         SKIPPED   37 min   <- captured, tier PASSED

Run standalone as a file it also SKIPS: "neither plan finished within the probe
timeout", 48 passed 1 skipped.

### What actually distinguishes the two outcomes

Not load in the direction assumed. The test bails with a SKIP only when
BOTH sides time out, and reaches an assertion when exactly ONE does:

    both time out    -> skip, no verdict, tier passes, cell is an UNRECORDED hole
    one finishes     -> a verdict is reached, the flag disagrees, tier FAILS

So a warmer fixture makes failure MORE likely, not less, because it pushes one
side over the 20 s line while the other stays under. That is why the warm-up
pairing attempt above made things worse rather than better: it warmed each plan
more effectively, which is movement toward the one-side-finishes state.

### The consequence that matters

EITHER OUTCOME IS A HOLE. A skip records nothing and a failure records nothing,
so `coverage.json` carries this cell empty whichever way the run lands. The
difference is only whether the tier reports red, which makes the red/green
signal noise rather than information.

### What would actually close it

Make BOTH sides finish, reliably, so the buffer comparison can be made and a
value recorded. `issues/117` measured this shape at ~5 s warm against >20 s
cold, so the budget is not absurd — the difficulty is getting both plans warm
at once on a fixture larger than the pool, which the paired warm-up moved
toward and did not reach.

That is a real piece of work with a measurable end state (the cell records a
value instead of a hole), and it should be judged against its cost: the paired
warm-up alone added 14 minutes to a 37-minute tier. Accepting the skip, as this
issue originally proposed, remains defensible — but it should be an explicit
choice, with the knowledge that the cell gates nothing either way.
