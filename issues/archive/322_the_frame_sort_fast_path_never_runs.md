# 322 — The frame listing's sort / filter fast path never runs

## Status: RESOLVED 2026-10-27. Verified on the vg test stack rebuilt for the fix: unit, DAWG conformance, integration and API suites, 0 failures; the fast path served every sorted / filtered frame listing of the API suite (no AttributeError, no decline).

## Defect

On the default path, which production runs: every frame listing that sorts or filters
(`sort_by`, `frame_type_uri`, `status`, `parent_uri`, `form_type`, the created / modified
bounds) first calls `fast_frame_prop_sort.fast_frame_prop_page`, which fails at once:

```
File ".../fast_frame_prop_sort.py", line 338, in fast_frame_prop_page
    async with impl.db_impl.connection_pool.acquire() as conn:
AttributeError: 'SpaceImpl' object has no attribute 'db_impl'
```

`kgframes_endpoint` passes `space_record.space_impl`, the space's `SpaceImpl` record, where
the function needs the storage implementation (`SparqlSQLSpaceImpl`, with `.db_impl` and
`.schema`). The entity listing resolves that with `kg_backend_utils._resolve_space_impl`
before calling its own fast path (`fast_entity_prop_page`); the frame listing does not.

The error is caught and the listing falls back to SPARQL, so answers are correct. But the
`frame_prop_sort` table is maintained on every write and never read: each sorted or
filtered frame listing pays the general SPARQL query plus a logged traceback.

## How it was found

The API suite against the planner stack: 28 tracebacks per run (c35-c37 gates), from
`tests/api/test_kgframes_api.py` (frame sorting, sorted paging). It surfaced when a planner
change made the fallback SPARQL fail, and the sorted listings came back empty.

## Fix

`kgframes_endpoint` passes `_resolve_space_impl(backend)`, as the entity path does. Two
latent defects of the path, which had never served a request, fixed with it:

- `exclude_status` was neither passed to the table query nor a reason to decline: served
  there, it would have been ignored. It now declines to SPARQL.
- the total for a parent-scoped listing was counted without `parent_uri`: the graph's
  frame count, not the parent's children. It now passes `parent_uri`, as the SPARQL path does.

`tests/api/test_kgframes_api.py`: a parent-scoped sorted listing (its children, in order,
counted as 3) and a sorted listing excluding a status; the existing sort / paging tests now
run on the fast path.

## Was to do

- Pass the resolved storage impl (`_resolve_space_impl`), as the entity path does.
- Then the fast path serves these listings for the first time: run the frame sort and
  paging API tests against it, and check it pages by partition (the bindings, not SQL
  rows), since it has not served a request before.
- Count the tracebacks in production's logs to see how often listings hit this.
