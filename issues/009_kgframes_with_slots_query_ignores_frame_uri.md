# GET /kgframes/kgslots ignores frame_uri and never returns slots

**Status: RESOLVED**

## Summary

The `GET /api/graphs/kgframes/kgslots` endpoint accepts a `frame_uri` query
parameter to retrieve a specific frame's slots, but the underlying SPARQL query
ignores this parameter entirely and never joins to slot objects — it only
returns KGFrame subjects.

## Root Cause

In `vitalgraph/endpoint/kgframes_endpoint.py`, three stub methods delegate to
the plain frames-only code path:

1. **`_build_frames_with_slots_query`** — ignores `frame_uri`,
   `entity_uri`, `parent_uri`, and `kGSlotType`; delegates to
   `_build_list_frames_query` which only selects `?frame` subjects of type
   `haley:KGFrame`. No `Edge_hasKGSlot` join is performed, so slots are never
   discovered.

2. **`_build_count_frames_with_slots_query`** — same issue;
   delegates to `_build_count_frames_query` with no frame_uri filter.

3. **`_sparql_results_to_frames_with_slots`** — delegates to
   `_sparql_results_to_frames` which filters converted objects for
   `isinstance(obj, KGFrame)`, discarding any slot objects even if they were
   somehow included.

## Fix Applied

All three methods replaced with proper implementations:

1. **`_build_frames_with_slots_query`** — uses a proper UNION with repeated
   GRAPH patterns. Branch 1 selects the frame as `?subject`, branch 2 selects
   the slot destination as `?subject`. Both branches filter by `frame_uri`
   when provided.

   ```sparql
   SELECT DISTINCT ?subject WHERE {
       {
           GRAPH <g> {
               ?subject a haley:KGFrame .
               FILTER(?subject = <frame_uri>)
               ?slot_edge vital-core:vitaltype <...Edge_hasKGSlot> .
               ?slot_edge vital-core:hasEdgeSource ?subject .
               ?slot_edge vital-core:hasEdgeDestination ?slot .
           }
       } UNION {
           GRAPH <g> {
               ?frame a haley:KGFrame .
               FILTER(?frame = <frame_uri>)
               ?slot_edge vital-core:vitaltype <...Edge_hasKGSlot> .
               ?slot_edge vital-core:hasEdgeSource ?frame .
               ?slot_edge vital-core:hasEdgeDestination ?subject .
           }
       }
   }
   ```

2. **`_build_count_frames_with_slots_query`** — counts slots for the given
   frame when `frame_uri` is set; falls back to the general frame count
   otherwise.

3. **`_sparql_results_to_frames_with_slots`** — fetches triples for all
   subject URIs and converts via `VitalSigns.from_triples_list` without
   filtering by type, so both KGFrame and KGSlot objects are returned.

**Note:** An initial attempt using `{ BIND(?frame AS ?subject) } UNION
{ BIND(?slot AS ?subject) }` failed due to a separate SQL generator bug
(see issue 011).

## Tests

All 12 tests in `tests/api/test_kgframes_api.py` pass, including:
- `TestSlotCrud::test_get_frame_slots`
- `TestSlotCrud::test_delete_slot`
- `TestFramesWithSlots::test_get_kgframes_with_slots`

## Files Changed

- `vitalgraph/endpoint/kgframes_endpoint.py` (lines ~923-1044)
