# The Slot-Sort Backfill Calls An Unbuilt Edge Table A "Data Shape"

## Status: FIXED 2026-09-18. `edge_table_unbuilt` discriminates before the
## message asserts anything, and `maintenance_job` logs the precondition case at
## INFO instead of claiming permanence at WARNING.

## Symptom

`maintenance_job._run_entity_slot_sort_integrity` logs, at WARNING:

    entity_slot_sort: <space> type <T> — 500 entities selected, 0 rows derived.
    They have no frame/slot/value chain to walk, so they will be re-selected
    every cycle and coverage can never reach 100% for this type. This is a
    DATA shape, not a backfill failure (issues/151)

Two of those three claims can be false, and the message states all three as
settled fact.

## Measured counterexample

Space `lead_nurture_100k` (53.3M quads) during its bulk import, 2026-09-04:

    14:38:44  500 entities selected, 0 rows derived   (coverage 0 of 22,762)
    14:47:41  500 entities selected, 0 rows derived   (coverage 0 of 50,416)
    14:57:12  500 entities selected, 0 rows derived   (coverage 0 of 73,743)
    15:09:30  500 entities selected, 0 rows derived   (coverage 0 of 93,872)
    15:18:08  500 entities selected, 0 rows derived   (coverage 0 of 100,000)
    15:26:26  500 entities selected, 0 rows derived   (coverage 0 of 100,000)
    15:33:13  batch failed: canceling statement due to lock timeout
    15:41:28  batch failed: canceling statement due to lock timeout

Coverage then reached **100,000 of 100,000 entities, 4,064,500 rows**, when the
import's own resync phase finished at ~15:45. "Coverage can never reach 100%"
was wrong six times, and "DATA shape, not a backfill failure" was wrong six
times.

## Cause

`backfill_entity_slot_sort_batch` selects seeds from `{space}_rdf_quad` (which
the import populates early, via COPY) but walks `{space}_edge` (a DERIVED table
the import does not populate until its resync phase). Between those two points a
space has every entity visible to the coverage probe and no edges to walk, so
the seeded walk correctly derives nothing.

The code cannot distinguish

  - no frame/slot/value chain exists  (a real data shape), from
  - the chain is not built yet        (a bulk load in flight),

and reports the first unconditionally. The window is not small: 83 minutes for
this import, the entire time at WARNING.

The two lock timeouts have the same root — the import's `entity_slot_sort`
rebuild held the lock the maintenance batch wanted. Expected contention,
reported as failure.

## Why it matters

It is only a log line, but it is a confident, alarming, and wrong diagnosis
emitted during the single most common trigger (bulk load). It sent this
investigation after a phantom planner bug for some time: the honest reading of
"0 rows derived, coverage can never reach 100%" is that the seeded walk is not
equivalent to the full walk, which would be a correctness bug in `issues/151`'s
central claim. It is not — the seeding is fine.

## Fix — SHIPPED 2026-09-18

`edge_table_unbuilt(conn, space_id)` in `sync_edge_table.py`: empty edge table
AND non-empty quads. Both halves are required and both are tested — an empty
edge table on an EMPTY space is not a diagnosis, it is an empty space, and a
populated one means the original DATA-shape message was right and must not be
downgraded. Two EXISTS probes that short-circuit, reached only on the rare path
where a batch derived nothing.

The warning now states which case it is rather than leaving it implied: the
precondition case at INFO naming the unbuilt edge table, the genuine case at
WARNING saying the edge table IS built.

**The in-flight-import test was NOT adopted.** This section proposed the process
tracker as "a sharper test than the table heuristic". It would be sharper and it
is narrower: it only sees imports that register there, and the edge table can be
empty after a resync, a restore, or a migration that never touches the tracker.
The table is the condition the walk actually depends on, so it is the thing to
ask about.

**Two bugs this codebase had already been burned by, re-attempted in one change
and caught:**

  * the probe first used `conn` from the enclosing scope, whose
    `async with pool.acquire()` block had already closed — the released
    connection bug pinned by `test_maintenance_edge_integrity_conn.py`, where
    one `except` took out every remaining step of the cycle. It acquires its
    own now.
  * its failure path was `logger.debug`, which
    `test_no_REPAIR_step_swallows_a_failure_silently` rejected: production runs
    at INFO, so DEBUG is invisible, which is how `issues/144` hid a dead repair
    path. It reports through `log_probe_failure` now.

Original proposal follows.

Cheap discriminator before asserting a data shape: if `{space}_edge` is empty
while `{space}_rdf_quad` is not, the derived tables are not built yet. Log that
instead, at INFO, and skip the type this cycle rather than claiming permanence.

An in-flight import is also directly observable via the process tracker, which
would be a sharper test than the table heuristic if the import registers there
for the whole of its run.

Also worth reconsidering: whether the maintenance loop should attempt the
slot-sort backfill for a space with an import in progress at all, given both
lock timeouts came from exactly that overlap.

## Not in scope

The seeded walk is correct and `issues/151`'s design holds. Nothing here argues
for putting the O(graph) `backfill_entity_slot_sort` back on the loop.
