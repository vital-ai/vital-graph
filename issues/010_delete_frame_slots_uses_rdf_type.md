# DELETE /kgframes/kgslots: validation uses rdf:type instead of vital-core:vitaltype

**Status: RESOLVED**

## Summary

The `DELETE /api/graphs/kgframes/kgslots` endpoint always silently fails to
delete slots because its validation queries use `rdf:type` (the SPARQL `a`
keyword) to check type information. The SQL backend stores types as
`vital-core:vitaltype`, not `rdf:type`, so the validation always fails and
the delete is never attempted.

Additionally, the client's `delete_frame_slots` method always returns
`is_success=True` regardless of the server's `success` field, masking the
failure.

## Root Cause

In `vitalgraph/endpoint/kgframes_endpoint.py`:

1. **`_slot_exists_in_backend`** (line ~2805) uses:
   ```sparql
   <slot_uri> a ?type .
   FILTER(STRSTARTS(STR(?type), "...KG") && STRENDS(STR(?type), "Slot"))
   ```
   The `a` keyword is `rdf:type`, but the DB stores type as
   `vital-core:vitaltype`. This query never matches.

2. **`_slot_connected_to_frame`** (line ~2835) uses:
   ```sparql
   ?edge a <...Edge_hasKGSlot> ;
   ```
   Same issue — `a` (rdf:type) vs `vital-core:vitaltype`.

3. **Client `delete_frame_slots`** (kgframes_endpoint.py client, line ~854)
   always calls `build_success_response` without checking
   `response_data.get('success')`.

## Reproduction

```python
# Create frame + slot
await client.kgframes.create_kgframes(space_id, graph_id, [frame])
await client.kgframes.create_frame_slots(space_id, graph_id, frame.URI, [slot, edge])

# Delete reports "success" but slot is still there
dr = await client.kgframes.delete_frame_slots(space_id, graph_id, frame.URI, [slot.URI])
assert dr.is_success  # True (client bug masks server failure)

# Slot still exists
lr = await client.kgframes.get_frame_slots(space_id, graph_id, frame.URI)
# slot is still in lr.objects
```

## Proposed Fix

1. **Server**: Replace `a` with `vital-core:vitaltype` in both
   `_slot_exists_in_backend` and `_slot_connected_to_frame`.

2. **Client**: Add `success` field check in `delete_frame_slots` before
   calling `build_success_response`.

## Affected Tests

- `tests/api/test_kgframes_api.py::TestSlotCrud::test_delete_slot`

## Severity

**High** — slot deletion via the standalone kgframes endpoint is completely
broken. Deletes are silently swallowed.

## Files

- `vitalgraph/endpoint/kgframes_endpoint.py` (lines ~2805-2852)
- `vitalgraph/client/endpoint/kgframes_endpoint.py` (lines ~849-858)
