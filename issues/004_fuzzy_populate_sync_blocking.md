# Issue 004: Fuzzy Populate Was Synchronous / Blocking

## Problem

The `POST /api/fuzzy-mappings/populate` endpoint was executing the full
fuzzy population synchronously inside the HTTP request handler.  For
large datasets this caused:

- **HTTP timeout risk** — reverse proxies (nginx, ALB) typically kill
  requests after 30–60 seconds.
- **DB connection held** — a single connection from the pool was locked
  for the entire population duration, starving other requests.
- **Client blocked** — the caller had no way to continue until
  population finished.
- **No progress visibility** — unlike FTS populate, there was no way to
  poll for status while population was in progress.

The FTS populate endpoint (`POST /api/fts-indexes/populate`) already
used the correct pattern: fire an `asyncio.ensure_future()` background
task and return immediately with a status message.

## Root Cause

`FuzzyMappingsEndpoint.populate_mapping()` directly awaited
`populate_fuzzy_index()` inside the request handler:

```python
# BEFORE (blocking)
count = await populate_fuzzy_index(conn, space_id, index_name=dto.index_name)
return {"message": "Fuzzy index populated", "mapping_id": mapping_id, "entities_indexed": count}
```

## Fix Applied

Refactored to match the FTS pattern:

1. The handler validates the mapping exists, then releases the request
   connection immediately.
2. A background task (`_run_populate`) is spawned via
   `asyncio.ensure_future()`.
3. The background task acquires its own DB connection from the pool.
4. The endpoint returns immediately with `entities_indexed: 0` and a
   status message.
5. Clients poll `GET /api/fuzzy-mappings/stats` to check progress.

```python
# AFTER (non-blocking)
asyncio.ensure_future(self._run_populate(space_id, mapping_id, index_name))
return {"message": f"Fuzzy population started for mapping {mapping_id}", ...}
```

## Files Changed

- `vitalgraph/endpoint/fuzzy_mappings_endpoint.py` — refactored
  `populate_mapping()`, added `_run_populate()` background worker.
- `tests/api/test_text_search_api.py` — updated fuzzy populate tests to
  poll stats (same pattern as FTS populate tests).

## Testing

API tests pass with the async pattern.  The test polls
`fuzzy_mappings.get_stats()` in a loop until `entity_count >= 1` or
timeout (15 s).

## Related

- FTS populate endpoint (already correct):
  `vitalgraph/endpoint/fts_indexes_endpoint.py`
- Future consideration: add a `status` field to the fuzzy mapping row
  (e.g. `populating`, `ready`, `error`) so clients can distinguish
  "not started" from "in progress" from "complete".
