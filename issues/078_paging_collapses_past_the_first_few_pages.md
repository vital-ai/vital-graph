# Paging Collapses Past the First Few Pages — Page 11 Takes 39 Seconds

## CONCURRENCY CHECKED — materialise wins under load (sorted shape)

    8 concurrent clients, 12 s per arm, sorted page 1
      ordered scan (current)    9.6 q/s   median 810 ms   p95 1,283 ms
      materialise              14.1 q/s   median 564 ms   p95   784 ms

1.47x throughput, lower median and p95. The worry that building the whole match
set per query would cost throughput is not borne out — plausibly because the
ordered scan's per-candidate probes serialise on the same pages while the
materialise pass is a bulk scan that shares them.

STILL UNTESTED, and it is the case the caveat was really about: the UNSORTED
page 1, where the ordered scan is 54 ms against materialise's 312 ms. That arm
needs the two-phase SQL's uuid layer, which the extraction used here cannot
reach. Until it is measured, the hybrid argument survives for unsorted page 1
only.

## Direction: ALWAYS materialise, not a hybrid (concurrency now checked for sorted)

Flat ~312 ms at every depth is easier to reason about and support than
54 ms .. 16 s depending on how far the user paged — a p99 that depends on user
behaviour is not a p99. 312 ms is inside what a UI absorbs.

The maintainability argument is the stronger one: a hybrid needs a THRESHOLD,
and a threshold is a gate that must agree with the emitter it selects. This repo
has been bitten by gate/emitter drift four times in one effort and wrote itself
a rule about it. One plan shape has no gate to drift.

It also enables the cursor cache later (planning §8c): the materialised match set
is identical for every page of a query, which is exactly what such a cache would
hold. A hybrid's early pages could not participate.

**Caveat to measure first:** materialise builds the whole match set every query,
where the ordered scan at page 1 does ~1/25th of it and stops. Single-query that
is 6x latency; under CONCURRENCY it is throughput and memory, and every number
here is single-query. Concurrency is this repo's largest blind spot. Measure
under load before making materialise the only path.

## Status: OPEN — and MATERIALISE fixes it. Measured 2026-08-11.

Warm, arms alternated, median of 3, on the corrected 16 GB pool:

                     materialise      current path
    offset     0        312 ms            54 ms      current wins 6x
    offset   250        321 ms         1,437 ms      materialise 4.5x
    offset  1000        309 ms         2,958 ms      materialise 9.6x
    offset  5000        313 ms        16,271 ms      materialise 52x

Materialise is FLAT — 296-438 ms across every offset — because its cost is
building the match set once. The current path is unbeatable at page 1 and
O(offset) after it.

**Neither dominates, so the answer is a HYBRID**: ordered scan for early pages,
materialise past a threshold, crossover somewhere between offset 0 and 250. Both
plans already exist; the work is choosing between them.

This is where the materialise work from `issues/080` belongs. `080` itself turned
out to be a configuration artifact (616 ms after the pool fix, materialise only
1.4x), but THIS issue is a real plan problem that the config improved without
solving.

`shared_buffers` 1 GB -> 16 GB on a 64 GB machine (see `issues/080`), no code
change:

    offset      before        after
         0       49 ms        54 ms
       250   39,247 ms     1,437 ms     27x
     1,000    TIMEOUT       2,958 ms
     5,000    TIMEOUT      16,271 ms

Nothing times out any more. But cost still scales with offset — the O(offset)
shape is real and independent of the pool, which only set the constant. Page 201
at 16 s is still a bad page, so this issue stands; it is just no longer a
cliff.

`eq/KGTextSlot`, 25-row page, warm, generated through the real pipeline
(`build_entity_query_sparql(..., page_size=25, offset=N)`):

    offset      page      time
         0         1        49 ms
        25         2       175 ms
       250        11    39,247 ms
     1,000        41    TIMEOUT (>120 s)
     5,000       201    TIMEOUT (>120 s)

Page 11 is 800x page 1. Page 41 does not complete.

## Why this was never seen

**Every performance test pages at `offset=0`.** Verified across
`tests/performance/`: the only offset literal present anywhere is `offset=0`.
The comparator sweep, the growth curves, the paging benches and the plan
assertions all measure the first page and nothing else.

So the entire two-phase paging effort — `issues/040`, `047`, `053`, `059`-`061`
— was validated on page 1. Everything it concluded is true of page 1. Nothing
was ever asserted about page 2 onward, and it turns out not to hold there.

That is the same shape as `issues/071` (a slow cell that was never counted) and
the `contains` single-value gap (`issues/070`): the measurement had one fixed
parameter, and the cost lived in the dimension nobody varied.

## Suspected mechanism, NOT yet confirmed

Two-phase paging exists so `LIMIT` can stop an ordered scan early. `OFFSET N`
does not let it stop early — the scan must produce and discard N rows first, so
cost is O(offset + limit) with the discarded rows paying full probe cost. The
25-row page is cheap because it stops after 25 matches; page 11 pays for 275.

That would make the curve roughly linear in offset, and 49 ms -> 175 ms -> 39 s
is much worse than linear, so something else is likely involved as well — a plan
flip past some threshold, most plausibly. **This needs an EXPLAIN at several
offsets before anyone acts on the guess above.** `issues/047` is a precedent for
exactly that: the paging plan flipped to a blocking sort above 51 rows.

## Why it matters

Deep paging is a normal thing for a UI to do, and the failure is silent — no
error, just a request that takes 39 seconds and then a timeout two pages later.
The per-request deadline from `issues/044` will now cut it off at 120 s, which
turns it into a visible failure rather than a hang, but does not make it work.

## MATERIALISE is flat with depth — a candidate fix, measured 2026-08-11

A hand-written materialise shape (`issues/080`): build the uuid match set once
in a `MATERIALIZED` CTE, then order/offset/limit over that narrow set.

                          materialise    current
        offset=0             265 ms         45 ms
        offset=250           278 ms     39,247 ms
        offset=1000          267 ms      TIMEOUT
        offset=2475          273 ms      TIMEOUT

Flat. The cost is materialising the match set once; the offset then walks an
already-built set.

The trade is explicit: ~265 ms flat against 45 ms at page 1, so it is ~6x SLOWER
for the first page and unboundedly faster after it. A HYBRID — ordered scan
early, materialise beyond a threshold — is the obvious shape, and the crossover
is measurable since both plans already exist.

This also revises the note below: that reasoning ("sorted and unsorted behave
oppositely, so they need separate fixes") was about the CURRENT plans.
Materialise is a third plan, flat for both, so one change may serve both.

CAVEAT: the uuid layer used omits the entity-type UNION, so the match set is not
the real one. Indicative only — rebuild it faithfully and re-run before relying
on any of this.

## Tested 2026-08-11: it is NOT the ordered-scan fence, and NOT the same bug as 080

The hope was that fixing sorted-page driver selection (`issues/080`) would fix
this too. Two measurements say otherwise.

The mechanism that made it plausible: two-phase sets `ctx.needs_ordered_scan`
and the executor fences the statement (`issues/047`) so page 1 keeps its
early-terminating scan. At depth that fence might forbid the better plan.
Measured, with and without it:

     page  offset   fence ON (today)   fence OFF
        1       0          3,168 ms        54 ms
       11     250         36,433 ms    35,720 ms
       41    1000           TIMEOUT      TIMEOUT
      100    2475           TIMEOUT      TIMEOUT

Within 2% at page 11, both timing out beyond. (Caveat: fence-ON ran first at
each offset so fence-OFF had the warmer cache — the page-1 pair is not
comparable. The page-11 near-equality holds despite that advantage.)

And the two paths behave in OPPOSITE directions with depth:

    sorted (080)     13,491 ms -> 5,605 ms -> 2,727 ms   FASTER
    unsorted (078)      49 ms -> 39,247 ms -> timeout    SLOWER

Opposite signs is not what one shared mechanism looks like. This issue should
keep its own fix — a cursor cache converting sequential OFFSET paging into an
internal seek (planning §8d, E4) — rather than waiting on `080`.

## What to do

1. `EXPLAIN (ANALYZE, BUFFERS)` at offsets 0 / 25 / 250 / 1000 and find where
   the plan changes, rather than assuming it is the discarded-rows cost.
2. Add offset to the perf matrix as a dimension — it is currently a constant.
   A curve over offsets belongs next to the growth curves.
3. Consider keyset pagination (page from the last uuid seen) for the ordered
   case. It is the standard answer to O(offset), and this schema pages on a
   uuid that is already ordered — `decision D1` may make that natural here.

## Related

- `issues/047` — paging plan flips to a blocking sort above 51 rows. Same class.
- `issues/040` — paging is O(matches) not O(page). The first-page half was fixed.
- `issues/071` — the measurement-shaped blind spot this shares.
