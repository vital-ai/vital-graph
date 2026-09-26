# 243 — The two sibling delete paths: one lied about its status, one had never run

## Status: FIXED 2026-09-26. `issues/242` recorded these two as NOT CLEARED and
## they turned out to be different defects, not two copies of the same one: the
## entity batch delete is LIVE and its status was hardcoded, and the frame path was
## UNREACHABLE and could never have succeeded. Falsified both fixes.
##
## THE SAME DEFECT WAS IN `kgframes_endpoint` TOO — both delete handlers, found by
## being asked about that endpoint specifically. Fixed and verified against a
## running server (a failed batch now returns `store_failed`, not `deleted`).
##
## ALSO CARRIES A REGRESSION I SHIPPED IN `issues/241` AND FOUND HERE: the
## `isinstance` dispatch in `create_backend_adapter` refused an ALREADY-BUILT
## adapter, which several endpoint methods pass in, so frame-graph GET returned
## `objects=[]` and a frame update read back `None`. Two API tests caught it; the
## 4894-cell unit suite did not. Fixed by making the dispatch idempotent. Verified
## against a REBUILT test stack, which is the check that would have caught it
## three commits earlier.

**Related:** `issues/242` (the defect that named these two and declined to clear
them), `issues/184` (the precedent for DELETING a path that has never executed
rather than repairing it), `issues/215`/`issues/229` (the same
failure-in-the-return-value shape)

## Why they were worth tracing separately

`issues/242` fixed two frame-delete responses and listed `:1439` and `:1752` as
also returning a hardcoded `DELETED`, explicitly not cleared. The natural
assumption was "two more of the same". Both halves of that were wrong.

## 1. `DELETE /kgentities?uri_list=a,b,c` — LIVE, and only the status lied

Route `@self.router.delete("/kgentities")` → `_delete_entities_by_uris`.

`deleted_count` was already HONEST here, and that is the difference from `242`:

    deleted_uris_list = [str(u) for u, ok in zip(uris, results) if ok]
    deleted_count = len(deleted_uris_list)

`ok` comes from `_delete_one`, which returns a real per-URI outcome. So the count
told the truth while `status=OperationStatus.DELETED` was a literal, and the
message was built unconditionally:

| batch outcome | `deleted_count` | old `status` | old `message` |
|---|---|---|---|
| all 3 deleted | 3 | `deleted` | "Successfully deleted 3 KG entities" |
| 1 of 3 deleted | 1 | `deleted` | "Successfully deleted 1 KG entities" |
| **0 of 3 deleted** | **0** | **`deleted`** | **"Successfully deleted 0 KG entities"** |

`OperationStatus.PARTIAL` — *"batch: some items succeeded, some failed"* — existed
and was **dead**. That is what makes the old behaviour indefensible rather than
merely imprecise: the vocabulary was there, unused, exactly as `STORE_FAILED` was
in `242`.

Now `DELETED` / `PARTIAL` / `STORE_FAILED` by count against `len(uris)`, with the
message matching.

**One imprecision recorded rather than papered over.** The zero case reports
`STORE_FAILED`, not `NOT_FOUND`, and the two are NOT distinguishable here:
`_delete_one` returns `False` both for an exception and for a legitimately absent
entity (`count > 0` is False when there was nothing to delete). Separating them
means changing what `_delete_one` returns. Until then the stricter report is the
safer one — a caller retrying a `STORE_FAILED` loses nothing, while one trusting a
`NO_OP` stops looking.

## 2. The frame path — UNREACHABLE, and it could never have succeeded

`kgentities_endpoint._delete_frame_by_uri` was called by **nothing**. The live
single-frame delete is `KGFramesEndpoint._delete_frame_by_uri`, reached from
`kgframes_endpoint.py:731` — a DIFFERENT CLASS with no inheritance between them, so
the two same-named methods never met. That is why `242`'s "hardcoded `DELETED` at
`:1752`" looked alarming and was inert.

And it was the only caller of `KGSparqlQueryProcessor.delete_frame`
(`kg_sparql_query.py:327`), which raised on every invocation:

    await self.backend.execute_sparql_update(delete_query)      # ONE argument

against

    async def execute_sparql_update(self, space_id: str, update_query: str)

→ `TypeError: execute_sparql_update() missing 1 required positional argument:
'update_query'`, caught by its own `except` and **re-raised**. Reproduced directly
against the adapter, not inferred.

So the path had never executed — `issues/184`'s situation exactly ("it selects a
column `frame_entity` does not have, so it raises on every call"), and 184's
resolution applies: **delete it, do not repair it.** There is no behaviour to
preserve, and the live path already handles `NOT_FOUND`, `INVALID_REQUEST` and a
real success check, so nothing is lost.

**`delete_frame` also carried `issues/242`'s defect twice over**, which is recorded
in the deletion note because it is the reason not to revive this shape:

  * `deleted_count` came from a COUNT query run BEFORE the delete — the same
    discovery-vs-outcome confusion;
  * the update's return value was DISCARDED, and that adapter returns `False` on
    failure rather than raising;
  * the result dict hardcoded `'success': True`.

Both functions are deleted, each replaced by a comment saying what was there and
why it went, so the next person does not add the missing argument and resurrect it.

## Pinned

Three cells appended to `tests/unit/test_frame_delete_reports_failure.py`, all
falsified: reverting the status mapping fails two of them, and the third asserts
both deleted functions stay deleted AND that the live one still exists — so the
capability cannot be lost by a later cleanup reading this issue as "frame delete
was removed".

tests/unit: 4887 passed, 9 skipped, 0 failures.

## 3. `kgframes_endpoint` had the SAME defect, in both delete handlers

Asked directly: "what about kgframes endpoint including deletes?" — a fair
question, because sections 1 and 2 are both `kgentities`. It did.

`_delete_frame_by_uri` and `_delete_frames_by_uris` each build an HONEST
`deleted_uris` (a frame is appended only when `_delete_frame_from_backend`
returned True) and then returned:

    status=OperationStatus.DELETED
    message=f"Successfully deleted {len(deleted_uris)} frame(s)"

So a request where every delete failed came back `status=deleted` /
"Successfully deleted 0 frame(s)" — the same defect as the entity batch, on the
endpoint whose name is on the operation. `_delete_frames_by_uris` is the worse of
the two: it wraps each frame in `try/except ... continue`, so a frame drops out of
the list on a logged WARNING alone, and that was precisely the case reporting
success.

Both now DELETED / PARTIAL / STORE_FAILED against the requested count.

**VERIFIED AGAINST A RUNNING SERVER**, not just by unit test — deleting two
non-existent frames through `DELETE /api/graphs/kgframes`:

    {"success": false, "status": "store_failed",
     "message": "None of the 2 requested frame(s) were deleted (they may be
                 absent, or the deletes may have failed)",
     "deleted_count": 0, "deleted_uris": []}

`success` is derived from `status` via `_SUCCESS_STATUSES`, so before this the same
request returned `success: true`.

**One bug caught by checking rather than by testing:** the first version of this
fix used `len(uris_to_delete)` in both handlers. That variable exists only in
`_delete_frame_by_uri`; `_delete_frames_by_uris` calls its parameter `uris`, so it
would have raised `NameError` on every batch frame delete. Found by verifying each
handler defines what it references before rebuilding — which is the check the
`issues/241` regression below argues for, applied one step earlier.

## A REGRESSION I SHIPPED IN `241` AND CAUGHT HERE — read this one

Verifying "did I break an endpoint or only delete dead code" found that I HAD
broken one, three commits earlier, and no unit test saw it.

`issues/241` replaced `create_backend_adapter`'s class-NAME substring dispatch
with `isinstance`. The old form matched `SparqlSQLBackendAdapter` as well as
`SparqlSQLSpaceImpl`, so when a caller handed it an ALREADY-BUILT adapter it
wrapped an adapter in an adapter — which worked, because the adapter delegates
through `self.backend`. `isinstance` correctly refused that, and refusing it broke
the callers that rely on it:

    kgentities_endpoint._get_specific_frame_graphs - ERROR -
      No KG backend adapter for SparqlSQLBackendAdapter.
      Supported: SparqlSQLSpaceImpl.

Symptom: `GET` of a frame by URI returned `FrameGraph(objects=[])` and an entity
frame update read back `None` instead of its slot value. **Two API tests failed;
the 4894-cell unit suite was entirely green**, because the double-adaptation only
happens through an endpoint method that takes `backend` as a parameter.

Fixed by making `create_backend_adapter` IDEMPOTENT — an object that is already a
`KGBackendInterface` is returned unchanged. That is better than both predecessors:
the old code re-wrapped (worked, wasteful, and hid the pattern), the interim code
refused (broke it), and this states the invariant. Unknown types still raise.
Pinned by a new cell in `test_backend_adapter_dispatch.py` whose docstring says it
exists because the stricter version shipped without it.

**The lesson is about the verification, not the dispatch.** Every check I ran on
`241` was static or unit-level: imports resolve, 4894 cells green, no dangling
references. None of them exercised a request. The failure needed a running server
and the API suite, and I only ran that when asked to confirm nothing was broken.
A rebuilt stack plus `tests/api` is the cheap check that `issues/108` already
argues for, and skipping it is what let a silent-empty-result regression sit in
three commits.

## What this says about the original `242` note

Listing the two paths as "not cleared" was right, and describing them as probably
the same defect was wrong in both directions — one was less serious (honest count,
lying status) and the other was more so (a function that could never run, wired to
a method nothing called). The cost of tracing them was small; the cost of assuming
would have been a "fix" that added an argument to a function whose whole shape was
wrong.

## Not established

  * **Whether `_delete_one`'s conflation of absence and failure has bitten anyone.**
    It means a delete of an already-absent entity is excluded from
    `deleted_uris_list`, so a caller deleting an idempotent set sees `PARTIAL`
    where `NO_OP` would be right. Not investigated; it is a wrong STATUS, not a
    wrong outcome.
  * Nothing on the delete paths, as it turns out. **Checked rather than left
    open:** `_delete_entity_by_uri` — the single-URI arm of the SAME route — was
    already correct before any of this work, and is the `:1356` this issue's parent
    cited as the model: `DELETED if success else STORE_FAILED`, a branching message,
    `deleted_uris=[]` on failure, and it even uses `NO_OP` for an already-absent
    entity. After this pass only two hardcoded `OperationStatus.DELETED` literals
    remain in the file and both are the `issues/242` sites, each behind a
    `STORE_FAILED` guard.

    Which is the pattern across both issues and worth stating once: in `242` the
    correct form was eleven hundred lines up in the same file, and here it was in
    the sibling arm of the same route. Neither defect needed a new convention —
    both were a path that had not been brought up to one that already existed
    beside it.
