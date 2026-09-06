# `import_space` Leaves A Stale entity_slot_sort And A Marker Still Saying Complete

## Status: OPEN, live wrong-answer path. Found by the `issues/167` audit, not by
## a test.

## What it does

`bulk_export.import_space` restores a space: it TRUNCATEs the core tables
(`datatype`, `term`, `rdf_quad`), COPYs the exported files in, and — when
`resync=True` — rebuilds the derived tables. It rebuilds THREE of the four:

    resync_edge_table            yes
    resync_frame_entity_table    yes
    recompute_stats_tables       yes
    resync_entity_slot_sort      NO

Zero references to `entity_slot_sort` in the module. It also does not call
`resync_all_auxiliary_tables`, which would have covered all of them; it
hand-rolls a subset, and the subset drifted when a fourth derived table was
added.

It does not clear `slot_sort_coverage` either.

## Why that is a wrong answer and not merely a slow one

`import_space` TRUNCATEs and re-COPYs, so it is designed to restore OVER AN
EXISTING SPACE. If that space already had a complete coverage marker — the
normal state for any space being served — then after the restore:

  * `rdf_quad` holds the NEW contents;
  * `{space}_entity_slot_sort` still holds rows derived from the OLD contents;
  * `slot_sort_coverage` still says COMPLETE, because nothing cleared it;
  * `fast_slot_filter` therefore SERVES from the stale table.

The result is a confident, plausible answer computed from data that is no longer
there — entities that no longer exist, and none of the entities that now do. No
error, and a count that looks reasonable.

This is the exact failure the marker exists to prevent, arriving through the one
path that neither maintains the table nor invalidates the marker.

## Reachability

No production caller. `import_space` is an operator/test tool — the callers are
`tests/integration/test_bulk_export.py` and nothing else in `vitalgraph/` or
`scripts/`. So this is not firing in production today.

It is still a real path: restoring a space from an export is an operational
procedure, and "restore over the existing space" is what TRUNCATE-then-COPY is
for. The severity is wrong answers, silently, on a space that was serving
correctly before the restore.

## The precedent, one layer over

`graph_registry` records this same function copying a whole space in and
registering NO GRAPHS — "the data is queryable by naming the URI, so anything
hardcoding the graph works, while everything that LISTS graphs sees nothing".
That was fixed by making registration derive from the data. This is the same
omission for a different derived artefact, in the same function.

Two omissions of the same shape in one function is the argument for the fix
below being structural rather than another line added to the list.

## Fix

Call `resync_all_auxiliary_tables` instead of hand-picking resyncs. It rebuilds
every derived table, registers graphs, and since `af1c717` clears and re-records
the coverage marker as one operation. A restore then cannot leave any derived
artefact describing the previous contents, and cannot leave a marker vouching
for one.

That also removes the failure mode by construction rather than by remembering:
the next derived table added is covered without editing this function, which is
precisely what did not happen twice here.

If `resync=False` is kept as an option, it must CLEAR the marker unconditionally
— a caller opting out of the rebuild is opting into an incomplete table, and the
marker must not continue to vouch for it.

## Test

Restore a space over one with a complete marker and a populated
`entity_slot_sort`, then assert the marker is not left true over stale rows.
Asserting on the marker rather than on query results, because the wrong answer
here is plausible and a result-shaped assertion could pass on coincidence.

## Relation to `issues/167`

Under today's ALLOW-LIST this is a bug in a path that forgets to invalidate.
Under the proposed BLOCK-LIST it is the canonical case for taking a block: the
operation makes the table disagree with the quads, so it must block for its own
duration and release on verified completion. Fixing it now is a prerequisite for
that inversion, not a substitute — inverting the register while this path exists
would convert it from "wrong only if a marker happened to be set" into "wrong
always".
