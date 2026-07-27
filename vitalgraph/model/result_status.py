"""Unified result-status contract for VitalGraph endpoint responses.

Every endpoint response (read and write) carries three orthogonal signals:

  - HTTP status code  — transport only. It is **200 for every domain/application
    outcome** (created, already-exists, not-found, empty, invalid-request, …). A
    non-200 (5xx) is returned ONLY for a genuine server-level internal error
    (unhandled exception, backend/DB unavailable). See
    planning/planning_response_status/kg_response_contract_plan.md §5.
  - ``success: bool`` — "did the expected thing happen?" DERIVED from ``status``
    (see below); never set by hand.
  - ``status``        — the machine-readable outcome discriminator. Single source
    of truth; callers set this (plus ``message``).
  - ``message: str``  — human-facing text for a log or UI; never parsed.

The client API (typed wrappers) MAY layer conveniences on top of these — e.g.
raising on ``success=false`` — but that is a client-side choice, independent of
this wire contract (the server still returns HTTP 200).

This contract is the standard for ALL VitalGraph endpoints; the KG endpoints are
the first/reference rollout.
"""

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class OperationStatus(str, Enum):
    """Machine-readable outcome discriminator, shared across all verbs/endpoints."""

    # ── generic / neutral success (mixin default; families override) ──
    OK = "ok"

    # ── success outcomes (success=True) ──
    CREATED = "created"
    UPDATED = "updated"
    UPSERTED = "upserted"
    DELETED = "deleted"
    FOUND = "found"          # read returned >= 1
    EMPTY = "empty"          # read matched nothing (still success=True)
    NO_OP = "no_op"          # nothing to do (e.g. delete of an already-absent URI)

    # ── "expected thing didn't happen" (success=False, but HTTP 200) ──
    ALREADY_EXISTS = "already_exists"   # create on an existing URI
    NOT_FOUND = "not_found"             # get/update/delete a missing specific URI
    PARTIAL = "partial"                 # batch: some items succeeded, some failed

    # ── domain faults (success=False, still HTTP 200) ──
    INVALID_REQUEST = "invalid_request"   # bad/missing params, no valid objects
    STORE_FAILED = "store_failed"         # write failed for a describable data reason
    ERROR = "error"                       # server-level internal error (also → HTTP 500)


#: Statuses that map to ``success = True``. Every other member maps to False.
_SUCCESS_STATUSES = frozenset({
    OperationStatus.OK,
    OperationStatus.CREATED,
    OperationStatus.UPDATED,
    OperationStatus.UPSERTED,
    OperationStatus.DELETED,
    OperationStatus.FOUND,
    OperationStatus.EMPTY,
    OperationStatus.NO_OP,
})


class ResultStatus(BaseModel):
    """Mixin providing the unified status fields for every endpoint response body.

    ``success`` is DERIVED from ``status`` by a validator — ``status`` is the single
    source of truth, so it is impossible to emit an inconsistent pair (e.g.
    ``success=True`` with ``status=STORE_FAILED``). Callers set only ``status`` (and
    ``message``); each response family overrides the ``status`` default with its
    natural success value (created / updated / deleted / found).
    """

    success: bool = Field(True, description="Did the expected operation happen? (derived from status)")
    status: OperationStatus = Field(
        OperationStatus.OK,
        description="Machine-readable outcome discriminator (see OperationStatus)",
    )
    message: str = Field("", description="Human-readable status text (log/UI only)")

    @model_validator(mode="after")
    def _derive_success(self) -> "ResultStatus":
        derived = self.status in _SUCCESS_STATUSES
        if self.success != derived:
            object.__setattr__(self, "success", derived)
        return self
