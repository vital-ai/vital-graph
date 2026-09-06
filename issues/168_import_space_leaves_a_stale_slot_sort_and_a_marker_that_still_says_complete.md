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


---

## FOUND ON THE WAY: `resync_all` was not fail-safe inside a transaction

Delegating to `resync_all_auxiliary_tables` failed the round-trip test with
`current transaction is aborted, commands ignored until end of transaction
block` — and the fault was not in the delegation.

Every optional step in `resync_all` is written `try: ... except: warn and
continue`, because a derived table that only affects plan choice must not fail a
whole resync. The reasoning is right; the implementation was not. Inside a
transaction a statement that raises ABORTS THE TRANSACTION, so catching the
exception does not let the next step run: every later statement fails, including
the caller's own work after the function returns.

It stayed hidden because the callers that mattered ran `resync_all` OUTSIDE a
transaction. `import_space` runs inside the caller's, so one genuine failure
cascaded into three steps that were not broken:

    edge fan-out      null value in column "edge_type_uuid"   <- the real one
    entity fan-out    current transaction is aborted          <- collateral
    geo               current transaction is aborted          <- collateral
    final ANALYZE     current transaction is aborted          <- collateral

Each optional step now runs in its own SAVEPOINT (`conn.transaction()` opens one
when already inside a transaction), so a failure rolls back only itself. After
the change the same run produces ONE warning — the real one — and nothing else.

This is a latent fix for every caller, not just this one. Any code path running
`resync_all` in a transaction had the same exposure.

## STILL BROKEN, and now visible: edge fan-out on an imported space

    resync_all(inttest_exp_dst_*): edge fan-out skipped
      (null value in column "edge_type_uuid" of relation ...)

`compute_edge_fanout` fails with a NOT NULL violation on every import round
trip. It is pre-existing, unrelated to the marker, and was previously buried as
the first line of a four-warning cascade that read like one failure.

Consequence: a restored space has no edge fan-out statistics, so any plan choice
that consults them is made without them. Degraded plans, not wrong answers.
Worth its own investigation — the likely cause is that the fan-out derivation
reads an edge type the restore has not populated at that point, which would make
it an ORDERING problem rather than a data one.


---

## REVISED FIX: defer the long derivation instead of holding a lock across it

The first fix delegated to `resync_all_auxiliary_tables`, which rebuilds
everything. It is correct and it is the WRONG PLACE to do it.

`import_space` runs inside the caller's transaction and the TRUNCATE takes
ACCESS EXCLUSIVE on the core tables, so every statement before COMMIT extends
the window in which the space answers nothing. `resync_entity_slot_sort` is the
longest derivation by far — minutes on a 53M-quad space — and holding an
exclusive lock across it is precisely the failure this work exists to remove:
rebuild work blocking the application queries it is meant to make fast
(`issues/161`). Trading a wrong answer for an outage is not a fix.

So the restore now:

  * rebuilds INLINE only what a correct query cannot do without — edge,
    frame_entity, stats;
  * EMPTIES `entity_slot_sort` rather than leaving it stale, and clears the
    marker;
  * hands the long rebuild to `backfill_entity_slot_sort_batch`, which is
    bounded per batch, fenced, and already runs on a duty cycle (`issues/150`).

Queries are served throughout by the general SPARQL pipeline: slower, correct,
and not blocked.

## PREREQUISITE, and it was a live hole of its own: the SORT path was ungated

Deferring is only safe because both read paths now decline on a cleared marker.
The sort path did not check it. The stated reasoning was that a short table
merely MIS-ORDERS a page where a short filter returns a subset — true for a
table that is short, false for one that is EMPTY. `fast_slot_sort_page` ends in

    return [r[0] for r in rows]

so a table with no rows for the type returns an EMPTY PAGE, served as "no
results": every result missing, not mis-ordered. Emptying the table without
gating that path would have converted this issue's bug into a worse one.

Both paths are now gated on the same marker, each warning once per
(space, type).

## STILL NOT REBUILT ON RESTORE, pre-existing and unchanged by this

`import_space` has never rebuilt the geo table, the value histograms, or the
edge/entity fan-out statistics — the original hand-picked list was three
resyncs and remains three. Of these:

    geo               DERIVED FROM QUADS -> can be wrong after a restore
    value histograms  plan-only -> degraded plans, correct answers
    fan-out           plan-only -> degraded plans, correct answers

Geo is the same class of defect this issue is about, one table over, and is not
fixed here. It wants the same treatment: emptied at restore and rebuilt by a
job, or rebuilt inline if it is cheap enough to hold the lock for. Not measured.
