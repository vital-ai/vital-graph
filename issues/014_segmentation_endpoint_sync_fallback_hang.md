# Issue #014: Segmentation endpoints leak DB connections → pool exhaustion → hang

## Summary

The segmentation config CRUD and job status endpoints in `kgdocuments_endpoint.py`
acquire database connections via `pool.acquire()` but never release them. After
several requests, the connection pool is exhausted and subsequent calls to
`pool.acquire()` hang indefinitely, blocking the entire event loop.

Additionally, the `POST /segment` endpoint had a sync fallback that could block
the event loop when the job queue was unavailable.

## Root Cause

1. **Connection pool leak** (primary): `_get_connection()` returned a raw connection
   with no mechanism to release it. `_get_config_manager()` and `_get_job_manager()`
   passed this connection to managers but never released it after the handler finished.
   Each request leaked one connection.

2. **Sync fallback** (secondary): `_handle_segment()` fell through to
   `_handle_segment_sync()` which performs blocking segmentation inline when the
   job queue is unavailable.

## Impact

- After ~5-10 requests, all pool connections exhausted
- Subsequent requests hang on `pool.acquire()` with no timeout
- Event loop stalls propagate to auth endpoint, blocking new client connections
- Server becomes completely unresponsive until restart

## Fix Applied

### Connection leak fix

`_get_connection()` now returns `(conn, pool)` tuple. All callers (`_get_config_manager`,
`_get_job_manager`) return `(manager, pool, conn)`. All handlers use `try/finally`
to release connections:

```python
manager, pool, conn = await self._get_config_manager(space_id)
try:
    # ... use manager ...
finally:
    if pool and conn:
        await pool.release(conn)
```

### Sync fallback fix

Replaced with immediate error response:

```python
return SegmentDocumentResponse(
    success=False,
    message="Segmentation job queue unavailable; cannot process request",
    document_uri=body.document_uri,
)
```

## Files Changed

- `vitalgraph/endpoint/kgdocuments_endpoint.py`
  - `_get_connection()` — returns `(conn, pool)` tuple
  - `_get_config_manager()` — returns `(manager, pool, conn)`
  - `_get_job_manager()` — returns `(manager, pool, conn)`
  - `_handle_list_configs()` — release in finally
  - `_handle_create_config()` — release in finally
  - `_handle_update_config()` — release in finally
  - `_handle_delete_config()` — release in finally
  - `_handle_segmentation_status()` — release in finally
  - `_enqueue_segmentation_job()` — release in finally
  - `_handle_segment()` — removed sync fallback

## Testing

- `tests/api/test_kgdocuments_api.py::TestSegmentationConfigCrud` (5 tests)
- `tests/api/test_kgdocuments_api.py::TestSegmentationTriggerAndStatus` (3 tests)

## Status

**Fixed** — connections properly released; endpoint returns promptly when queue unavailable.
