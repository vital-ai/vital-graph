# The frame_entity Rewrite Returns Wrong Results — Far Too Many Rows

## Status: OPEN — correctness defect, 2026-08-08

When `rewrite_frame_entity_table` fires, it does not return the same rows as the
query it replaced. It returns many more.

## Measured

wordnet_frames, the pattern the rewrite exists for — a frame with a
`hasSourceEntity` slot group and a `hasDestinationEntity` slot group sharing
`?frame`, projecting both entities:

| | rows | time |
|---|---|---|
| rewrite **OFF** | **285,348** | 7,771 ms |
| rewrite **ON** | **≥ 1,000,000** (hit the LIMIT) | 5,371 ms |

285,348 is correct: each frame carries exactly one source and one destination
slot, so the answer is one row per frame, and `{space}_frame_entity` holds
exactly 285,348 rows. The rewritten form over-produces by at least 3.5x. An
unbounded `count(*)` over it did not finish in ten minutes, while the correct
form counts in about eight seconds.

At a 25-row page the defect is invisible and the rewrite looks like a clear win —
**808 ms against 4,549 ms, a 5.6x speed-up** — because a page of wrong rows
comes back faster than a page of right ones. That is the shape of the problem:
every cheap check passes.

## Why this matters more than the speed-up

The 5.6x is real and shows the traversal table works: collapsing six tables into
one `frame_entity` row is exactly the join reduction the edge table already
delivers 8x on elsewhere. The mechanism is sound and the table is populated
(285,348 rows on wordnet, maintained by insert/delete hooks, resync, backfill and
drift detection).

It is the rewrite's row semantics that are wrong, not the idea. Until that is
fixed the table cannot be used, which is the direct answer to "why aren't the
traversal tables being used".

## Not the same as issues/048

`048` is a *different* failure of the same rewrite: on the canonical reference
query (`vitalgraph_sparql_sql_dev/sql_reference/happy_frame_query.sparql`) it
emitted SQL referencing a collapsed alias — `missing FROM-clause entry for table
"mv0"` — and now declines instead. That decline is triggered by a type
constraint on the **slot** node (`?sourceSlot a KGEntitySlot`), which has no
column in `frame_entity` to remap onto.

So the rewrite has two independent problems:

1. it cannot carry constraints on the slot node through the collapse, and now
   declines when it meets one (`048`, fixed by declining);
2. when it *does* fire, it returns too many rows (this issue, open).

Removing the slot type constraints is what makes it fire — and firing is when
the over-production appears.

## Likely cause, not yet confirmed

A cross product between the source and destination slot groups. The rewrite
replaces six tables with one `frame_entity` row precisely to avoid pairing every
source slot with every destination slot; if the join condition tying the two
groups to the same frame is dropped rather than absorbed, the result multiplies.
The row counts are consistent with that, but this has not been traced.

## Reproduce

Query: frame → source slot → entity and frame → dest slot → entity, sharing
`?frame`, **without** `?slot a KGEntitySlot` type quads (those make it decline
per `048`). Run with `rewrite_frame_entity_table` monkeypatched to identity and
compare row counts. 285,348 is the right answer.

## Related

- `issues/048` — the decline path, and the search error that first mis-scoped this
- `issues/041` — the same table's staleness detection
- `vitalgraph/db/sparql_sql/rewrite_frame_entity_table.py`
