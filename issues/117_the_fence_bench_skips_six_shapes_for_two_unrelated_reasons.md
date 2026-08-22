# The Fence Bench Skips Six Shapes, for Two Reasons and Neither Is the Fence

## Status: OPEN — investigated 2026-08-22. Both causes are bench defects, not
## product defects. One further question is genuinely open (see the end).

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

**`contains` + the specific entity type stays over 20 s even with a matching
needle**, where the generic entity type drops to 8.2 s. That is a 2.5x-plus
gap between two entity types on the same criterion, and it is not explained by
either cause above. It may be ordinary — the specific type adds a type
predicate to an already wide walk — or it may be a real planning problem of the
`issues/111` family.

NOT MEASURED WARM, so no claim is made about the size of it. That measurement
is the next step, and it should be taken the way cause 1 shows is necessary:
warm both sides, alternate, take a median.
