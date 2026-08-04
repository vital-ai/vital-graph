# Spaces Endpoint Raises HTTP Errors for Domain Outcomes

## Status: FIXED (2026-08-04)

All three fix-sketch items done. Measured against the rebuilt test stack:

| call | situation | before | now |
|---|---|---|---|
| `POST /api/spaces` | space exists | 500 `{"detail": "Error adding space: 400: …"}` | **200** `{"status": "already_exists", "success": false}` |
| `DELETE /api/spaces` | space missing | 404 `{"detail": "Space not found or deletion failed"}` | **200** `{"status": "not_found", "success": false}` |
| `POST /api/spaces` | new space | 200 created | **200** created *(unchanged)* |
| `DELETE /api/spaces` | space exists | 200 deleted | **200** deleted *(unchanged)* |

### What changed

1. **`create_space_with_tables` now distinguishes the case** (fix item 3). Its
   two already-exists branches raise `SpaceAlreadyExistsError` instead of
   returning the same `False` used for genuine failures, so the endpoint no
   longer has to infer intent from a boolean. Existing callers are unaffected —
   all of them create fresh spaces.
2. **`vitalgraph_api.add_space` stops swallowing its own status codes** (fix
   item 1). Added `except SpaceAlreadyExistsError: raise` and
   `except HTTPException: raise` ahead of the bare handler, mirroring
   `delete_space`. This was a bug on its own terms: the deliberate 400 was
   caught by its own error handler and re-reported as a 500 with the reason
   buried in a string.
3. **The endpoint returns both outcomes at HTTP 200** (fix item 2), using the
   `ALREADY_EXISTS` and `NOT_FOUND` members that already existed and are
   documented as "success=False, still HTTP 200". No model changes were needed.
   A delete failure that is *not* 404 still raises.

### Callers

- **Python client** — verified through `vg_client.spaces`: `is_success` is
  `True/False` correctly for all four cases. It does not surface the `status`
  enum, which is a pre-existing client gap and not a regression.
- **`e2e/tests/spaces-crud.spec.ts`** — tolerated 404 and only failed loudly on
  405, so a 200 passes through unchanged. Comment updated; it described a
  status code that no longer occurs.
- **`e2e/tests/space-fixtures.ts`** — `dropSpace` ignores the result. Docstring
  updated for the same reason.

### Verification

`tests/api/test_spaces.py::TestSpaceDomainOutcomes` — four tests covering both
new outcomes plus their neighbours (a real delete still succeeds; create is
repeatable after delete, so the already-exists path leaves nothing broken).
2216 local tests and 511 `tests/api` pass against a rebuilt stack.

## Problem

`POST /api/spaces` and `DELETE /api/spaces` signal ordinary domain outcomes
with non-200 HTTP status codes, contrary to the convention the rest of the API
follows: HTTP 200 for all domain outcomes (success / status / message in the
body), non-200 reserved for server-level internal errors.

Measured against the test stack:

| call | situation | actual | expected |
|---|---|---|---|
| `POST /api/spaces` | space already exists | **500** `{"detail": "Error adding space: 400: Failed to add space with tables"}` | 200 with a conflict/invalid-request status in the body |
| `DELETE /api/spaces?space_id=…` | space does not exist | **404** `{"detail": "Space not found or deletion failed"}` | 200 with a not-found status in the body |

The same endpoint file already implements the convention elsewhere, so this is
an inconsistency rather than a deliberate design:

- `SpacesEndpoint.get_space` (`vitalgraph/endpoint/spaces_endpoint.py:80-93`)
  catches the failure and returns `SpaceResponse(status=NOT_FOUND)` at HTTP 200,
  with the comment *"Return domain not-found response (HTTP 200) instead of
  raising"*.
- `SpacesEndpoint.delete_space` (`:247-257`) already returns HTTP 200 with
  `OperationStatus.INVALID_REQUEST` when the caller tries to delete a protected
  system space — but a *missing* space raises 404 from the layer below.

## Root cause

Both non-200s originate in `vitalgraph/api/vitalgraph_api.py`, not in the
endpoint layer:

- `add_space` raises `HTTPException(400, "Failed to add space with tables")`
  at `:249-251` when `create_space_with_tables` returns falsy (which includes
  the already-exists case).
- `delete_space` raises `HTTPException(404, "Space not found or deletion
  failed")` at `:341-343`.

`SpacesEndpoint.add_space` (`:63-78`) does not catch either, so both propagate.

### Secondary defect: the 400 is swallowed and re-wrapped as a 500

`add_space` ends with a bare `except Exception` at `:260-263` that re-raises as
500 with the original message nested in the detail string. `HTTPException` is
an `Exception`, and unlike `delete_space` (`:346-347`) this handler has no
`except HTTPException: raise` clause ahead of it. So the deliberate 400 is
caught by its own error handler and reported as a server fault:

```
"Error adding space: 400: Failed to add space with tables"
```

That is why the already-exists case surfaces as a 500 rather than the 400 the
code intends. Even if the convention change below were declined, this
swallow-and-rewrap is a bug on its own terms — it reports a client-side
condition as a server error and makes the status code untrustworthy.

## Impact

- Callers cannot distinguish "space already exists" from a genuine server
  failure without string-matching the `detail` field.
- Clients written to the documented convention (check `success` / `status` in
  the body) see an exception instead, and clients that retry on 5xx will retry
  a request that can never succeed.
- Found via `e2e/tests/spaces-crud.spec.ts`, where a leftover space turned the
  create test into an opaque 500. See `issues/022`.

## Fix sketch

1. In `vitalgraph_api.add_space`, add `except HTTPException: raise` before the
   bare `except Exception` (mirroring `delete_space:346`) so intended status
   codes are not rewritten. This alone is worth doing independently.
2. Return domain outcomes from the endpoint layer at HTTP 200:
   - `SpacesEndpoint.add_space` → `SpaceCreateResponse(status=INVALID_REQUEST
     or CONFLICT, message=…, created_count=0)` when creation fails because the
     space exists.
   - `SpacesEndpoint.delete_space` → `SpaceDeleteResponse(status=NOT_FOUND,
     deleted_count=0, deleted_uris=[])` when the space is absent, matching the
     protected-space branch directly above it.

   Both response models already carry `status` / `message` / count fields, so
   no model changes are needed.
3. Distinguish "already exists" from other creation failures in
   `create_space_with_tables` so the endpoint can report the right status
   rather than inferring it from a boolean.

## Callers to update alongside

Anything that currently treats non-200 as the signal:

- `e2e/tests/space-fixtures.ts:45` — `dropSpace` relies on the 404 being
  harmless (it ignores the result), so it keeps working either way.
- `e2e/tests/spaces-crud.spec.ts` — `cleanupCrudSpace` tolerates 404 explicitly
  and would need that branch revisited once the status moves into the body.
- `vitalgraph/client/` space methods and `vitalgraph-client-ts` — check whether
  either maps HTTP status to an error before the body is read.
