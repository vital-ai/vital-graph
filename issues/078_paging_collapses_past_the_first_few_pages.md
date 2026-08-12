# Paging Collapses Past the First Few Pages — Page 11 Takes 39 Seconds

## Status: OPEN — measured 2026-08-11 on `sp_lead_synth_100k`

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
