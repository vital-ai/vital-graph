# Client reports a server-rejected delete as a success, and overwrites the server's explanation

## Status: FIXED (2026-08-04)

## Severity

**A protection guard that works server-side is invisible to every client.**
`kgdocuments_endpoint._check_delete_protection` correctly refuses to delete a
managed segment and returns `status=invalid_request` with an explanation. The
client turned that into `is_success=True`, `deleted=True`,
`deleted_uris=[uri]`, and the message `"Deleted KGDocument: <uri>"`.

The server did the right thing. The caller was told the opposite.

## Summary

Endpoints return HTTP 200 for domain outcomes, with the real result in the body
(`status` / `message`). Two compounding defects meant the client ignored that.

**1. The client fabricated the success payload.**
`vitalgraph/client/endpoint/kgdocuments_endpoint.py:378-386` read the response
body, passed `status` through, and then hardcoded everything else regardless of
what that status said:

```python
return build_success_response(
    KGDocumentDeleteResponse,
    status_code=200,
    status=response_data.get('status'),
    message=f"Deleted KGDocument: {uri}",   # overwrites the server's message
    deleted=True,                            # unconditional
    deleted_count=response_data.get('total_count', 1),
    deleted_uris=[uri],                      # unconditional
)
```

**2. `is_success` overrode the status-aware base class.**
`vitalgraph/client/response/client_response.py:761-764` — `KGDocumentDeleteResponse`
replaced the base implementation with:

```python
return self.deleted and not self.error_code
```

The base `VitalGraphResponse.is_success` (`:55-64`) is explicitly written to
treat a server-supplied domain `status` as authoritative — its own docstring
says *"an HTTP 200 with status=already_exists is NOT a success"*. The override
discarded that and keyed on the `deleted` flag, which defect 1 had already
hardcoded to `True`. Either defect alone would have been caught by the other.

## Reproduction

Verified against the test stack on :8002. Create a KGDocument, attach
`hasKGDocumentSegmentTypeURI = urn:segtype:text_chunk`, then delete it:

| | before | after |
|---|---|---|
| document actually deleted | no | no |
| `status` | `invalid_request` | `invalid_request` |
| `deleted_count` | `0` | `0` |
| `is_success` | **`True`** | `False` |
| `deleted` | **`True`** | `False` |
| `deleted_uris` | **`[uri]`** | `[]` |
| `message` | **`"Deleted KGDocument: …"`** | `"Cannot directly delete managed segment …"` |

The server's behaviour never changed — only what the client reported about it.

## How it was found

Writing endpoint-level tests for the guards touched by
`issues/024_query_form_detected_by_string_prefix_not_parser.md`. That issue's
fix reverted `_check_delete_protection` from a hand-rolled `SELECT … LIMIT 1`
back to `ASK`, and neither guard had any test coverage. The first real test of
the rejection path failed — not because the revert was wrong, but because the
client had been misreporting rejections all along.

Worth noting: the whole `tests/api` suite passed both before and after the
revert. Nothing exercised a *rejected* delete, only successful ones, where
`deleted=True` happens to be correct.

## Fix

- `client/response/client_response.py:761` — `is_success` now defers to the
  status-aware base when the server supplied a `status`, falling back to the
  `deleted` flag only when it did not.
- `client/endpoint/kgdocuments_endpoint.py:378` — derives `deleted` from the
  server's status, and prefers the server's `message` over the canned string.

## Regression tests added

`tests/api/test_kgdocuments_api.py::TestManagedSegmentDeleteProtection`

- A managed segment type is rejected: `is_success` false, `deleted` false,
  `deleted_count == 0`, `deleted_uris == []`, and the server's own message
  survives in `message`.
- A *user-defined* segment type is still deletable — guards against
  over-broad matching on the predicate rather than the managed type set.
- A document with no segment type deletes normally.

## Not investigated

The same hardcoded-success shape appears in other client delete methods —
`grep "deleted=True" vitalgraph/client/endpoint/` also hits
`graphs_endpoint.py`, `objects_endpoint.py` and `kgtypes_endpoint.py` (17 sites
in total). Whether each of those has a server-side domain outcome it can
misreport was not checked. Several other response classes also override
`is_success` without consulting `status`; that pattern deserves a sweep.

## Related

- `issues/024_query_form_detected_by_string_prefix_not_parser.md` — the work
  that surfaced this. Same underlying shape: a layer deciding an outcome from
  something other than the authoritative value it was handed.
- `issues/023_values_clause_ignored_in_sparql_update.md` — same fail-open
  family: an outcome that should be a refusal quietly reads as permission.
