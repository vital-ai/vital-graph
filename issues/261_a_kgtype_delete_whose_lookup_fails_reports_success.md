# 261 — A KGType delete whose lookup query fails reports success

## Status: FIXED 2026-10-11 (uncommitted, not yet released).
##
## Found, filed 2026-10-04. Found on dev, not fixed.

## What was seen

On dev, with the SPARQL compiler sidecar stopped, `delete_kgtypes_batch` for a
type that existed answered `status=deleted`-shaped success ("No KGTypes found
for deletion", `is_success` true) and deleted NOTHING: the type's 5 quads and its
FTS and vector rows were all still there. The server log had, in the same
request:

    failed_query {"error": "ConnectError: [Errno -2] Name or service not known",
                  "space": "sp_kg_types", ...}
    KGType not found for deletion: http://vital.ai/test/indexing-probe/...
    No KGTypes found for deletion

(The `failed_query` line is `issues/259`'s; before it, the failure left no
trace of what the query was.)

## Cause

`kgtypes_delete_impl.KGTypesDeleteProcessor.kgtype_exists` runs a SPARQL lookup
and reads only the bindings:

    result = await backend.execute_sparql_query(space_id, check_query)
    if isinstance(result, dict):
        result = result.get('results', {}).get('bindings', [])
    exists = result and len(result) > 0

`execute_sparql_query` does not RAISE on failure; it returns
`{'success': False, 'error': ..., 'results': {'bindings': []}}`. So a failed
query and an absent type are the same `False`, and the batch delete reports
"nothing to delete" — a success — for a delete that never ran. The `except` that
also returns False only catches the cases that do raise.

The same `kgtype_exists` is copied into `kgtypes_create_impl` and
`kgtypes_update_impl`. On create, a failed lookup reads as "does not exist" and
the create proceeds; on update, as "not found".

This is the `issues/215` / `issues/100` shape again (a failed read reported as an
empty one). `kgquery_endpoint._checked_query` already exists for exactly this —
it raises when the result says `success: False`.

## Fix

Make the three `kgtype_exists` raise when the query result is `success: False`
(or route them through one checked helper), so a failed lookup surfaces as a
failed request — `store_failed` on delete — instead of "not found". Then a test
with a query that fails: the delete must not report success.

## How it was found

Verifying `issues/260` on dev with a probe type: create, check it is indexed,
delete, check the rows go. The rows did not go. The dev stack's sidecar had been
stopped along with the app; restarting it, the same delete removed the quads and
both index rows.

## Fix, 2026-10-11

One checked lookup, `vitalgraph/kg_impl/kgtype_lookup.kgtype_exists`, raises
`KGTypeLookupFailed` when the query result says `success: False`; the create and
delete processors delegate to it. The delete paths already re-raise, so a failed
lookup now reaches the endpoint as `STORE_FAILED` instead of "No KGTypes found
for deletion". The error text avoids "not found", which the endpoint would map
to `NOT_FOUND`. The update processor's copy had NO callers and the opposite bug
(its dict branch read a failure dict as truthy, so "exists"); it is deleted.

Tests: `tests/unit/test_kgtype_lookup_failure_is_not_absence.py` (9). A failed
lookup raises on batch delete, single delete and create; an absent type is still
absent; a present type is still deleted; the message cannot be read as not-found.
Against the old delete processor, the batch-delete test fails with
`DID NOT RAISE`, which is the dev observation exactly.
