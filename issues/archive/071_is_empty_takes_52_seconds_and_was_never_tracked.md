# `is_empty` Takes 52 Seconds and Was Never Counted

## Status: CLOSED 2026-08-11 — both halves

> **Buffer-pool review — see `issues/081`. NOT AFFECTED, by arithmetic and by measurement.** A 1 GB pool holds 131,072 pages; every comparator cell reads between 4,350 and 82,724 buffers, so all of them fit with room to spare. The re-run on a 16 GB pool confirms it: warm total 1,444 ms -> 1,745 ms, buffers 1,597,396 -> 1,597,348 (identical), no regressions across 39 cells. The queries that WERE destroyed read 453,180 buffers — 3.5x the whole pool — and none of them are here. Original note follows.
>
> _(superseded)_ At risk: the 52s. `shared_buffers` was 1 GB on a 64 GB machine against queries touching 400,000+ buffers; raising it to 16 GB moved a comparable query 16,411 ms -> 616 ms with no code change. Plan shapes, row counts and buffer counts are unaffected.

**The query:** fixed via `issues/072` and the candidate-driven negation path in
`issues/059`. The closing sweep in `issues/053` records
`is_empty/Text 51,753 ms -> 355 ms`, with buffers 3.3M -> 25k.

**The process point, which was the more valuable half of this issue:**
`scripts/perf_comparator_timing.py` now derives its verdict from the measurement
instead of from a hand-maintained table. It groups every swept cell into
slow-warm, over-buffer-threshold and cold-only, and the closing figure for `053`
is stated that way — "0 cells slow warm, 0 over the buffer threshold" — rather
than as a count of remaining known-bad cells.

That is what this issue asked for: a cell that is slow but not timing out can no
longer be invisible, because nothing is maintained by subtraction any more.

    is_empty/KGTextSlot     0 rows    52,374 ms

Measured identically at HEAD (50,905 ms) and after the `contains`/`has_any`
push-down (53,573 ms / 52,374 ms), so it is **not a regression** — it has always
been this slow.

## Why this is worth its own issue

`issues/053` tracks "twenty-one comparator shapes" and has been revised through
several rounds of fixes, each time re-counting what remains. `is_empty` was never
in the count, in any revision, despite the sweep that produced those counts
measuring it every single run at 50+ seconds — worse than most of the cells that
*were* tracked.

The list was built from one sweep's set of timeouts and then maintained by
subtraction: cells got crossed off as they were fixed, and nothing ever re-derived
the list from a fresh measurement. A cell that was slow but not *timing out* at
the moment the list was drawn never entered it and could never be noticed
afterwards, because attention followed the list rather than the data.

Worth fixing in the process as well as in the code: the sweep prints
`N of the swept cells exceed 1s`, and that number — not a hand-maintained
table — should be what the issue tracks.

## DIAGNOSED — see `issues/072`

Nested-loop misplanning from a 100,000x cardinality underestimate.
`enable_nestloop = off` takes it from 56,993 ms to 5,831 ms, reproducibly. The
guess below — that it pays for proving absence — is half right: it IS O(entities)
because the answer is empty, but the 56 s was the planner running a nested loop
100,000 times on a `rows=1` estimate, not the cost of the scan.

`eq`/Integer, noted at the bottom of this file as also uninvestigated, does NOT
have the same cause — an earlier revision said it did, from a contaminated
measurement. It runs in 37 ms warm with or without nested loops; its ~2 s in the
sweep is first-touch I/O. See the retraction in `issues/072`.

## Original guess, kept because it was only half right

`is_empty` returns 0 rows, so like `eq`/DateTime it pays the cost of *proving
absence*: an ordered scan that early-terminates on a broad match set has to walk
everything when the match set is empty. That is a guess from the shape and the
row count, not a measured plan — no `EXPLAIN` has been run.

Adjacent cells returning 0 rows are fast (`not_exists`/Text 950 ms,
`not_exists`/Double 249 ms), so "returns nothing" is not sufficient on its own.

## Also uninvestigated, same sweep

    eq/KGIntegerSlot    1,939 / 1,669 / 2,015 ms across three runs

Consistent, so not noise, and never tracked either. `eq` on every other slot
class is 107-435 ms.

## Related

- `issues/053` — the sweep and the count this was missing from
- `issues/070` — the cells that are slow for a now-understood reason
