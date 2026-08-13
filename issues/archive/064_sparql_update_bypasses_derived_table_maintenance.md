# SPARQL UPDATE Mutates Quads Without Maintaining Any Derived Table

## Status: FIXED — 2026-08-10, in `execute_sparql_update`


## REGRESSION AND RE-FIX 2026-08-12 — the frame_entity half had no caller

Bounding the sweeps for `issues/079` (`d3920b4`) moved the referential cleanup
out of `execute_sparql_update`, where it was O(edge table), cancelled by the 60 s
command timeout, and therefore cleaning nothing. The edge half went to
`MaintenanceJob`. **The frame_entity half went nowhere.**
`cleanup_stale_frame_entity` was left with no call site anywhere in the
codebase, so after a WHERE-bound delete its rows were never cleaned — not
deferred, simply abandoned. Exactly the defect this issue was filed on,
reintroduced by its own performance fix.

Both integration tests caught it immediately and had been red since that commit;
they were not run, because the change looked write-path-local and only the unit
suite was.

Now:

* `cleanup_stale_frame_entity` runs in the `MaintenanceJob` sweep, BEFORE
  `cleanup_orphan_edges`. The order is load-bearing and was documented in the
  inline code that got deleted: a frame_entity row is validated against the edge
  table, so cleaning it after those edges are gone makes it look stale for the
  wrong reason.
* It is scan-bounded like the edge sweep, with its own cursor. It had the same
  flaw the edge sweep did — `LIMIT` on rows DELETED bounds nothing when there is
  nothing to delete — and its check is strictly more expensive: two correlated
  `NOT EXISTS`, each joining the edge table to two quads.
* The contract the tests assert is now the real one: the update MARKS the space,
  and sweeping CLEARS it. Asserting both is what makes an uncalled sweep
  visible; a test that only checks the end state after a maintenance tick cannot
  distinguish "swept" from "never needed sweeping".


All four holes are closed, and option (1) below was taken rather than the
dirty-flag interim:

| case | handling |
|---|---|
| concrete subjects (INSERT/DELETE DATA) | `sync_edge_table_after_insert` + `cleanup_orphan_edges_for_subjects`, then `sync_frame_entity_before_delete` + `sync_frame_entity_after_edge_insert` |
| `CLEAR` / `DROP GRAPH` | names no subjects, so the per-subject hooks never fire — handled by CONTEXT instead, `delete_frame_entity_for_context` then `delete_edges_for_context` |
| WHERE-bound subjects | could not be enumerated, and the background self-heal is a backfill that only ADDS — now a bounded referential sweep, `cleanup_stale_frame_entity` then `cleanup_orphan_edges`, and only for updates that actually deferred something |
| `rdf_stats` | `resync_stats_for_predicates` over the predicates the update touched |

Ordering matters in two places and both are deliberate: `frame_entity` is derived
FROM the edge table, so it is cleaned BEFORE the edges it reads — otherwise a row
whose edge is about to go looks stale for the wrong reason and the two passes
disagree about why.

The sync runs in its own transaction inside a try/except, so a sync failure
rolls back cleanly and leaves the committed quads intact rather than poisoning
the pooled connection.

## Original status: OPEN — identified 2026-08-10 as the source of the orphans in `issues/060`

The derived traversal tables are supposed to be maintained on write, and mostly
are. The hooks exist and work:

    sync_edge_table_after_insert          populate on insert
    sync_edge_table_before_delete         remove on delete
    cleanup_orphan_edges_for_subjects     remove rows whose quads are gone

They are wired into `sparql_sql_space_impl`'s own insert/delete methods (the
REST paths), and `data_import_impl` calls `resync_all_auxiliary_tables` after a
bulk load.

**The SPARQL UPDATE path calls none of them.** `emit_update.py` generates 7
`DELETE FROM {quad_table}` and 4 `INSERT INTO {quad_table}` statements and
contains **zero** references to `_edge`; there is no resync anywhere in the
update path either.

So every `INSERT DATA`, `DELETE DATA`, `DELETE WHERE`, `DROP GRAPH` and `CLEAR`
executed through SPARQL UPDATE changes the quads and leaves the edge and
frame_entity tables describing something else.

## Both directions, both silent

| mutation | derived-table result | query symptom |
|---|---|---|
| INSERT via SPARQL UPDATE | edge row never created | traversals miss the new edge |
| DELETE via SPARQL UPDATE | edge row survives its quads | traversals return an edge to nowhere |

Neither errors. This is the mechanism behind both halves of the pattern that
keeps recurring:

* `issues/041` — the production edge table ~25% **incomplete** (the insert half)
* `issues/060` — **20,461 orphaned rows** across four spaces, 20,306 of them
  (5.3%) in a production-shaped space (the delete half)

Those orphans were confirmed independently: the rows have no quads at all, not
even the `hasEdgeSource` that defines them as edges, and rebuilding from the
quads removed exactly that many.

## Why the existing safety nets did not cover it

* `edge_table_drift` compares COUNTS, and an equal number of wrong rows passes.
* `edge_table_orphan_rate` samples 200 rows, so a few percent of orphans in a
  large table is likely to be missed entirely.
* The maintenance job backfills, and **backfill only ADDS** — it repairs the
  insert half and cannot remove an orphan.

So the delete half had no detection and no repair.

## Fix

The mutation is generated as SQL by `emit_update`, and the derived-table hooks
need the affected subject uuids, which that SQL does not currently surface. Two
shapes:

1. **Return affected subjects from the update statements** (`DELETE ...
   RETURNING subject_uuid`, likewise for insert) and feed them to the existing
   hooks. Precise and incremental, and reuses machinery that already works. The
   cost is threading the result through the update executor.
2. **Mark the space dirty and let maintenance repair it.** Much simpler, but it
   leaves a window where traversals are wrong, and repairing the delete half
   needs a full rebuild (ACCESS EXCLUSIVE) rather than a backfill.

(1) is the right target; (2) is a reasonable interim if the plumbing is
substantial, provided the dirty flag actually triggers a *rebuild* and not just
a backfill.

Whichever is chosen, `cleanup_orphan_edges_for_subjects` already exists and is
exactly the delete-side operation needed — it just is never called from here.

## Derived stats have the same shape but a harder version

`rdf_stats` is maintained incrementally by `sync_stats_after_insert` /
`sync_stats_after_delete`, and those presumably share this gap. Stats are worse
than the edge table in one respect: they are also *pruned*, and a pruned row
that a later write resurrects comes back holding only the post-prune delta
(`issues/062`). So stats need both the write hook and a policy for what absence
means — see `issues/061`'s per-predicate MCV proposal, where absence becomes
"smaller than the smallest listed" rather than ambiguous.

## Related

- `issues/041` — the insert half, in production
- `issues/060` — the delete half, and the orphan clear
- `issues/062` — the same class of problem in the stats tables
