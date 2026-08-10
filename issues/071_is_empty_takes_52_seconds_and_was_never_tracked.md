# `is_empty` Takes 52 Seconds and Was Never Counted

## Status: OPEN — 2026-08-10, `sp_lead_synth_100k`

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

## Not yet diagnosed

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
