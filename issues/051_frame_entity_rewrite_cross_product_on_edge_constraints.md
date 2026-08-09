# The frame_entity Rewrite Cross-Products When the Query Constrains the Edge Node

## Status: FIXED 2026-08-09 — narrower than first recorded

An earlier revision of this issue said the rewrite "returns wrong results", full
stop. That was too broad, and it was based on a query I wrote specifically to
force the rewrite to fire. On the real queries it returns exactly right answers.

## What is actually true

The defect needs one specific ingredient: a constraint on the **edge node**.

| query shape | rewrite | rows ON | rows OFF | |
|---|---|---|---|---|
| `?sourceEdge a Edge_hasKGSlot` present | fired | over a million | 285,348 | **WRONG** |
| frame type constraint only | fires | 285,348 | 285,348 | correct |
| no type constraints | fires | 285,348 | 285,348 | correct |

285,348 is right — one row per frame, exactly the `frame_entity` row count.

The real queries do not have edge constraints and were never affected:

| query | rewrite ON | rewrite OFF | |
|---|---|---|---|
| `FRAME_UNION_SPARQL` ("happy") | 425 rows, 16 ms | 425 rows, 396 ms | MATCH |
| `RELATIONSHIPS_SPARQL` | 45 rows, 6 ms | 45 rows, 23 ms | MATCH |

So the rewrite delivers **25x** on the happy frame union and **4x** on
relationships, correctly, and always did.

## Mechanism

`rewrite_frame_entity_table` remaps each variable position onto a
`frame_entity` column. A position with no counterpart column was dropped
*silently*:

```python
new_col = col_map.get(col_name)
if new_col is None:
    continue          # <- position discarded
```

`?sourceEdge` is bound twice: at `mv0.edge_uuid` (collapsed away, no
frame_entity column) and at the type quad's `subject_uuid` (survives). Dropping
the first leaves the type quad with nothing tying it to the frame, so it scans
every `Edge_hasKGSlot` in the space — 1.14M on wordnet — and the result
multiplies.

## Fix

Decline when a variable loses a position to the collapse *and* is still bound by
a surviving table. That is exactly the "lost its tie to the frame" condition,
and it is checkable at the point the position is dropped.

Verified: the edge-constrained shape now declines and returns 285,348; the two
safe shapes still fire and still return 285,348; the happy queries are
unchanged. Full suite clean.

This is the third guard of the same kind on this rewrite — the other two are in
`issues/048` — and they share a cause: the rewrite removes tables and then
assumes everything referring to them can be remapped. When it cannot, the
correct answer is to decline, not to emit something plausible.

## Related

- `issues/048` — the alias-reference guard, and the boundary bug in my first
  version of it
- `vitalgraph/db/sparql_sql/rewrite_frame_entity_table.py`
