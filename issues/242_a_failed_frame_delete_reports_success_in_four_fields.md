# 242 — A failed frame delete reported success, in four fields at once

## Status: FIXED 2026-09-26, both halves, verified by falsification. Found by
## asking what the CONTRACT was — `success` was computed from the DISCOVERY phase,
## and the endpoint never read it anyway.

**Related:** `issues/215` (the same mistake on the READ side: a killed query
reported as `EMPTY`, a success status — and the reason `QUERY_FAILED` exists),
`issues/229` (a saturated pool returning fewer entities with HTTP 200 and no
error), `issues/241` (removing the retired second-store flag is what exposed this)

## The defect

`DeleteFrameResult.success` was:

    kgentity_frame_delete_impl.py    success = len(deleted_frame_uris) > 0

and `deleted_frame_uris` is appended in **Phase 2 — DISCOVERY**, before Phase 3
runs the batch delete:

    Phase 2, line ~96    deleted_frame_uris.append(frame_uri)     <- discovery
    Phase 3, line ~121   deleted_ok = await self._batch_delete_triples(...)
    line ~134            success = len(deleted_frame_uris) > 0    <- ignores line 121

So `success` answered *"did we find anything to delete"*, not *"was anything
deleted"*. On a failed batch delete the caller got:

| field | value | |
|---|---|---|
| `success` | `True` | the delete failed |
| `message` | `"Successfully deleted 2 frame graphs (7 components)"` | nothing was deleted |
| `status` | `deleted` | **hardcoded at the endpoint** |
| `deleted_count` | `2` | the DISCOVERED count |

Four fields, all wrong, HTTP 200. The frames are still there.

## Fixing `success` alone changed NOTHING, which is the more important half

Both endpoint call sites — `kgentities_endpoint.py` `_delete_entity_frames` and
`delete_entity_frames` — did this:

```python
return FrameDeleteResponse(
    status=OperationStatus.DELETED,          # hardcoded
    message=result.message,
    deleted_count=len(result.deleted_frame_uris),
    deleted_uris=result.deleted_frame_uris,
)
```

`result.success` is never mentioned. So a correct `success` would have been
computed, returned, and discarded — the processor telling the truth to nobody.
That is `issues/229`'s exact shape (`execute_sparql_query` reports failure IN THE
RETURN VALUE; the reader read `bindings` and ignored `success`) and
`issues/215`'s (`_extract_bindings` again). Third instance.

## The vocabulary already existed, and the file already used it correctly

`OperationStatus.STORE_FAILED` — *"write failed for a describable data reason"*,
`success=False`, still HTTP 200 — is exactly this case. Its sibling
`QUERY_FAILED` carries the comment that names the read-side version:

> a killed or errored query was reported as EMPTY, which is a SUCCESS status, so a
> 56s statement timeout and a genuinely empty space were the same response
> (`issues/215`)

And `kgentities_endpoint.py:1356` already writes
`status=DELETED if success else STORE_FAILED` for a different delete. **This path
was the outlier, in two places**, so the fix is not a new convention — it is
applying the one already in the file.

## What was fixed

**1. `success` requires the delete to have happened.**

    deleted_ok = not batch_delete_failed
    success = len(deleted_frame_uris) > 0 and deleted_ok

`deleted_frame_uris` keeps its meaning as the ATTEMPTED set — renaming it is a
wider change — and the comment says so at the point of use, because the name reads
as a result.

**2. The message stops claiming a deletion.** On failure it says the delete failed
and names what it was asked to remove. It does NOT say "0 deleted": a single batch
statement that reported failure most likely applied nothing, but "nothing" is a
claim too, and the honest statement is that the delete failed and the frames may
still be present.

**3. `error` is populated**, so the failure is on the result rather than only in
prose.

**4. Both endpoint sites map `success` to status**, `STORE_FAILED` with
`deleted_count=0` and `deleted_uris=[]` — reporting the attempted set as deleted is
what made the old response wrong in four fields rather than one.

## Pinned, and falsified BOTH WAYS

`tests/unit/test_frame_delete_reports_failure.py`, 6 cells. Reverting the processor
half fails the message test; reverting the endpoint half fails the mapping test.
Checked separately, because a test that only covers one half would pass against a
tree where the other is broken — which is precisely the state this issue found
(the processor could have been right and the endpoint would still have lied).

The endpoint cell asserts on source structure rather than behaviour: every site
reporting `deleted_count=len(result.deleted_frame_uris)` must have a `STORE_FAILED`
response within the preceding 25 lines. Structural because the failure path needs a
real batch-delete failure to exercise, and the regression to guard against is
someone collapsing the two returns back into one.

tests/unit: 4886 passed, 0 failures.

## How it stayed hidden

The only trace was `fuseki_success=False` on the response — a flag about a SECOND
STORE that was retired and archived in `issues/241`. So while that flag existed,
there was something in the payload that hinted at the failure, and removing it is
what made the silence total. **The flag did not cause this and was not protecting
against it**: `success=True` and `status=deleted` were wrong the whole time, for
any caller not reading a Fuseki-specific field.

## Not established

  * **Whether a failed batch delete can partially apply.** It is one
    `DELETE DATA`, so all-or-nothing is the expectation, but that is not verified
    against the SQL backend's update path, and the message is worded to avoid
    claiming either way.
  * **Whether any caller treated `status=deleted` as authoritative and skipped a
    re-check.** The client and portal were not audited; `deleted_count` was wrong
    too, so a caller reconciling counts would have seen a discrepancy.
  * **The same question on the sibling delete paths.** `:1439` and `:1752` still
    return a hardcoded `DELETED` (the two fixed here are now at `:2234` and
    `:2975`, each behind a `STORE_FAILED` guard). Those two were NOT traced to
    their processors, so whether their `success` is derived before or after the
    write is unknown. **This issue does not clear them**, and they are the obvious
    place the same defect would still be — `:1439` is an entity delete and `:1752`
    a single-frame delete, so neither is covered by the guard test, which only
    looks at sites reporting `deleted_count=len(result.deleted_frame_uris)`.
