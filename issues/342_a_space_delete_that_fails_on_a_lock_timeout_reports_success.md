# 342 — A space delete that fails on a lock timeout reports success

## Status: FIXED 2026-11-15, verified on the vg test stack

Four layers, each of which hid the failure on its own:
1. `delete_space_storage` runs the whole drop (every DROP plus the `graph`/`space` row
   deletes) in ONE transaction. A failure rolls back to an intact space instead of leaving
   a half-dropped one. Lock contention (`55P03`, `40P01`) is retried 3 times with 2 s / 4 s
   backoff; anything else fails at once.
2. `SpaceManager.delete_space_with_tables` reads False as the failure it now always is:
   the space stays registered and no "deleted" notification goes out.
3. `VitalGraphAPI.delete_space` tells "not found" apart from "present and the drop failed"
   (`SpaceDeleteFailed`). The endpoint reports the second case as `STORE_FAILED` in an
   HTTP 200 body; it used to become `NOT_FOUND`.
4. The client's `spaces.delete_space` derives `error_code` from the body's `status`
   (`build_response_from_server`). It hardcoded `error_code=0`, so even the server's
   `NOT_FOUND` read as success. Behaviour change: deleting a missing space now gives
   `error_code 1`. `is_success` was already False for it.

**Verified live** (vg test stack, image built from HEAD + this fix; a second session held
`ACCESS SHARE` on the space's quad table):
- lock held 90 s: three attempts at 10 s `lock_timeout`, each rolled back. Client got
  `error_code 1`, `status store_failed`, "failed; the space is unchanged. Retry". The row
  and all 29 tables were present, and the space was still listed.
- lock held 15 s: attempt 1 timed out, attempt 2 succeeded. Client got `deleted`; the row
  and tables were gone, 0 orphans.

Tests: `tests/unit/test_a_failed_space_delete_is_not_reported_as_deleted.py` (13; 6 of
the 7 storage/manager cells and the client cells fail on the old code); `tests/api/test_spaces.py`
17 passed; unit suite 6,377 passed, 0 failed.

Note: the auto-sync and background tasks the manager cancels before the drop stay
cancelled after a failed drop. They restart on the space's next write.

(Opened 2026-11-14.)

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
