# 342 — A space delete that fails on a lock timeout reports success

## Status: OPEN, 2026-11-14

## Found

Trimming a restored copy of the vg test cluster (planning_test_data), `DELETE /api/spaces?space_id=nurture_typed`
ran about 1 s after the app started, while startup work was still touching that space (`ensure_edge_table`,
a SPARQL query on `nurture_typed` at 03:12:40). The log:

    03:12:52.927  delete_space called for space_id: nurture_typed
    03:13:06.397  delete_space_storage(nurture_typed) failed: canceling statement due to lock timeout
    03:13:06.398  Failed to delete space storage for 'nurture_typed' (may not exist)
    03:13:06.399  Successfully deleted space 'nurture_typed' with complete cleanup
    03:13:06.399  Delete successful: {'message': 'space deleted successfully with tables', ...}
    "DELETE /api/spaces?space_id=nurture_typed HTTP/1.1" 200 OK

The client got `error_code 0`. What was left:
- the `space` row, its `graph` rows, and all 14 `vgs_3bfyhkoe_*` tables (**21 GB**);
- no registry entry, so `list_spaces` no longer showed the space. A caller that checks the
  listing reads the delete as done, and the orphan is invisible until the next restart re-reads
  the `space` table.

Re-issuing the delete once startup had finished removed everything (0 orphan tables).

## Cause

- `SparqlSQLSpaceImpl.delete_space_storage` (`vitalgraph/db/sparql_sql/sparql_sql_space_impl.py`)
  catches every exception and returns `False`.
- `SpaceManager.delete_space_with_tables` (`vitalgraph/space/space_manager.py`, "may not exist")
  treats `False` as "nothing to delete". It then removes the registry entry, sends the deleted
  notifications, and reports success.
- A lock timeout (or any other DROP failure) on a space that DOES exist therefore reads as a
  successful delete.

## Expected

If the storage drop fails while the space's tables or `space` row still exist:
- the delete reports failure (HTTP 200 with `success: false` and the reason, per the domain-outcome
  convention);
- the registry entry stays;
- no deleted notification is sent.

"Not found" should be decided by checking that the space is absent, not inferred from an
exception. Retrying the drop on a lock timeout is optional.

## Reproduce

Start the vg test stack on a volume with a large space, and delete that space within the first
seconds of startup, while `ensure_edge_table` / the startup queries hold locks on it. Then check
`SELECT * FROM space WHERE space_id = ...` and the orphan-table query from
`planning/planning_test_data/01_test_data_footprint_plan.md`.
