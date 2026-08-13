# Client delete_kgentity: CombinedProperty not coerced to str

## Status: FIXED

## Summary

The `delete_kgentity` and `delete_kgentities_batch` methods in the client's
`KGEntitiesEndpoint` pass the raw `uri` parameter into `build_error_response()`
as `requested_uris=[uri]`. When the caller passes `entity.URI` from a VitalSigns
`GraphObject`, it is a `CombinedProperty` instance rather than a plain `str`.
Pydantic V2's `DeleteResponse(requested_uris: List[str])` rejects this with a
`ValidationError`.

## Root Cause

In `vitalgraph/client/endpoint/kgentities_endpoint.py`, the error-handling path
constructs the response without coercing:

```python
# Line ~785 (delete_kgentity)
return build_error_response(
    DeleteResponse, ..., requested_uris=[uri]  # uri is CombinedProperty
)

# Line ~847 (delete_kgentities_batch)
return build_error_response(
    DeleteResponse, ..., requested_uris=uri_list  # items are CombinedProperty
)
```

The existing `case_kgentities_crud.py` tests never trigger this because they
pass f-string literals (`f"{NS}entity_beta"`) which are already `str`.

## Reproduction

```python
from ai_haley_kg_domain.model.KGEntity import KGEntity

e = KGEntity()
e.URI = "http://example.org/test/entity1"

# e.URI is now a CombinedProperty, not str
await client.kgentities.delete_kgentity(
    space_id="some_space", graph_id="urn:graph", uri=e.URI
)
# → pydantic ValidationError: Input should be a valid string
```

## Proposed Fix

Cast to `str` at the top of both methods:

```python
# delete_kgentity
async def delete_kgentity(self, space_id: str, graph_id: str, uri) -> DeleteResponse:
    uri = str(uri)  # coerce CombinedProperty → str
    ...

# delete_kgentities_batch
async def delete_kgentities_batch(self, space_id: str, graph_id: str, uri_list) -> DeleteResponse:
    uri_list = [str(u) for u in uri_list]
    ...
```

## Severity

**Low** — only manifests when passing VitalSigns property objects directly.
Workaround: callers cast with `str(entity.URI)`.

## Affected Tests

- `tests/api/test_kgentities_api.py::TestKGEntitiesCrud::test_delete_entity`
  (uses `str()` workaround)
- `tests/api/test_kgentities_api.py::TestKGEntitiesCrud::test_batch_delete`
  (uses `str()` workaround)

## Files

- `vitalgraph/client/endpoint/kgentities_endpoint.py` (lines ~785, ~847)
- `vitalgraph/client/response/response_builder.py` (`build_error_response`)
