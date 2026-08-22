# Two Fixtures Disagree About Whether a Page Costs O(page)

## Status: OPEN — observed 2026-08-22 while re-promoting the query baseline.
## Not caused by a code change. Confirmed reproducing, and now encoded in the
## baseline, which is why it needs a home outside a commit message.

`query.kgquery.growth_curve.eq` runs the same equality page against the 10k and
100k lead fixtures. After the fixtures were ANALYZEd on 2026-08-22, the two
swapped plans — Hash Join and Nested Loop traded ends — on **unmodified code**:

    bench       execution        rows examined       plan
    IL-100k   7,503 -> 2,934 ms  100,000 -> 3,713    Hash Join -> Nested Loop
    IL-10k      184 ->   512 ms      365 -> 10,000   Nested Loop -> Hash Join

Re-measured after promotion and still there: IL-10k examines **10,000** rows,
IL-100k examines **3,713**.

## Why this is worth recording rather than shrugging at

The trade is net positive in wall-clock — the large fixture gained 2.5x, the
small one lost 2.8x, and 512 ms is not alarming on its own. That is the reading
that would file this under "the planner made a reasonable choice".

The problem is what the numbers say about the PROPERTY the bench exists to
measure. A page of 25 rows should cost about a page, not about the fixture.

* **IL-10k now examines every entity it has** — 10,000 rows for a 25-row page.
  That is O(fixture), and it is cheap only because the fixture is small.
* **IL-100k examines 3,713** for the same page, which is not O(fixture) at all.

So the two scales now DISAGREE about whether paging is O(page), and the one
that looks healthy is the big one. A property that holds at 100k and fails at
10k is the awkward direction: it means the small fixture — the one used in
edit-loop runs, because it is fast — is the one no longer measuring the thing.

## What it is NOT

Not a code change: the swap happened across an ANALYZE with nothing else
touched. Not noise either, and the distinction matters after
`issues/112`-adjacent confusion the same day: **plan shape changed and rows
examined moved 27x**. Both are structural. A timing ratio moving on its own is
noise; a plan changing which rows it visits is not.

Not caught by the bench's own assertions, which passed throughout.

## Where it now lives

`baselines/query.json`, promoted 2026-08-22, encodes the post-swap state. So a
future run comparing clean does NOT mean the property holds — it means nothing
has changed since the swap. That is the specific hazard of promoting a baseline
over a real difference, and it is why this is filed rather than left in the
promotion commit.

## What would settle it

Establish which side is right, rather than which is faster:

1. Does IL-10k's Hash Join examine 10,000 rows because the planner costs it
   correctly for a 10k table, or because a selectivity estimate is wrong at
   that scale? The fixture has ground truth — `actual_matches` in the manifest.
2. If the estimate is right, then O(page) simply does not hold below some
   size and the bench should say so at 10k rather than implying it does.
3. If the estimate is wrong, it is the same family as `issues/111` — a
   criterion the planner misprices — and the fix belongs there.

Cheap first step: `EXPLAIN` both fixtures' plans side by side and compare
estimated against actual rows at the driving scan. A large gap answers (1)
immediately.
