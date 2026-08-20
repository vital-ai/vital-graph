# The More Selective a Range Criterion, the More It Costs

## Status: OPEN — measured and reproducible; the two obvious explanations are both wrong

On `sp_lead_synth_100k`, a 25-row page under `MQLRating >= t`:

        t   matches    buffers   buf/match
       99     1,017  3,768,476     3705.5
       90     9,907     70,471        7.1
       65    34,790     24,798        0.7
       50    49,814     14,110        0.3
        0   100,000      5,477        0.1

**The tightest threshold is the most expensive query in the suite.** 1,017 rows
cost 3.77M buffers — 688x the buffers of the query returning 100x MORE rows, and
roughly 29 GB of buffer traffic for a thousand results. The 10k fixture has the
same shape (2,972 buf/match at t=99 against 0.3 at t=0), so it is not a
large-fixture artifact.

`test_range_comparator_pays_for_every_candidate[100k]` takes 72 seconds, four
times the next slowest bench in the repo.

## It matches the worst thing in the slow log

`graphs_kgqueries` is the worst endpoint recorded: 21,309 ms max, 2,373 ms
average over 97 samples, every one of them on `sp_lead_synth_100k`. A selective
range filter is exactly the shape a UI control produces.

## Both obvious explanations are wrong

**Not the probe/set-join gate.** The test's own comment says the gate "sends
low-selectivity criteria to the set-based join and high ones to the probe", which
predicts this curve. The plans say otherwise:

    t=99   Sort over a Nested Loop producing 100,000 rows -> Unique -> Limit 25
    t=90   Index Only Scan -> Unique -> Limit, nested loops at 231 loops

t=90 is an ordered scan that stops at the page. t=99 materialises every candidate
and sorts it.

**Not a missing `enable_sort` fence, either — though the flag IS wrong.**
`execute_sparql_query` runs under `SET LOCAL enable_sort = off` when the
generator sets `needs_ordered_scan`. Measured directly:

    t=99   needs_ordered_scan=False   unfenced 3,766,045   fenced 2,110,740
    t=90   needs_ordered_scan=True    unfenced    70,474   fenced    70,471

So two separate facts. The flag is FALSE for the shape that most needs it, which
means the number above is what production actually pays — the benchmark is not
measuring a plan that never runs. And fencing by hand recovers only 44%, leaving
2.11M buffers, still 30x the looser threshold. The cost is structural to this
shape, not a GUC away.

## Why nothing failed

The test measures the extreme and then deliberately does not gate it:

> Judge the range at a threshold whose selectivity is comparable to an available
> equality case, rather than at the extreme.

At that comparison point the range is 1.2x equality, which passes. The
3.77M-buffer case is recorded in `perf_record` and tolerated. That is defensible
— comparing across the plan boundary would compare two different plans — but it
means the largest number in the suite is one nothing watches.

## The docstring describes the opposite of what happens

> Range comparators cost the same whatever the threshold. Sweeping the threshold
> changes the match count by 625x and the buffer count by nothing, because the
> filter is applied above the join and every candidate crosses it regardless.

Flat would be bad. This is INVERTED, which is worse, and the test's own summary
line already says so — `10x fewer matches -> 12.87x the cost`. Corrected in the
same commit as this issue.

## What to do

1. Establish why `needs_ordered_scan` is False at t=99 and True at t=90.
   `emit_slice` sets it in two places; something about the tighter shape misses
   both. That is worth knowing even though the fence is not the fix, because a
   flag that tracks selectivity rather than plan shape will keep being wrong.
2. Explain the 2.11M floor. Fenced, t=99 still reads 30x t=90 while returning a
   tenth as many rows. Either the ordered scan walks most of the entity set to
   fill 25 rows — in which case the cost is inherent to paging a selective
   post-filter and the answer is a different access path — or something else
   dominates. `EXPLAIN (ANALYZE, BUFFERS)` on the fenced t=99 plan answers this.
3. Only then decide on a fix. Nothing here yet justifies changing the gate.

## Related

- `issues/047` — the `enable_sort` fence and why it is a GUC rather than a hint
- `issues/081` — a benchmark measured against a configuration nobody recorded;
  the fenced-vs-unfenced split above is the same trap, avoided by measuring both
- the test cites `issues/040`, which does not exist — the issues directory starts
  at 041, so whatever documented this originally is gone
