"""A backend failure must not be reported as a successful empty read.

`issues/082`. `execute_sparql_query` already detects its own failures and
returns `{'results': {'bindings': []}, 'success': False, 'error': ...}`. No
KGQuery path read that flag, so the endpoint saw the empty bindings list, took
the same branch a genuinely empty match set takes, and answered HTTP 200 with
`status=FOUND, total_count=0` — for a backend that was completely unreachable.

The cost was concrete: an investigation spent hours A/B-testing code versions
across two servers and a git worktree, because the API's answer for "the query
engine is down" is character-for-character the answer for "nothing matched".
The cause was in the server log the whole time.

These tests pin both halves, because both were wrong:

* a reported failure must RAISE rather than degrade to an empty page;
* a genuine miss must be `EMPTY`, not `FOUND` — the enum defines `FOUND` as
  "read returned >= 1" and `EMPTY` for exactly this case.
"""

from __future__ import annotations

import pytest

from vitalgraph.endpoint.kgquery_endpoint import (
    BackendQueryError, _checked_query, _read_status)
from vitalgraph.model.result_status import OperationStatus


class _Backend:
    """Minimal stand-in returning whatever execute_sparql_query would."""

    def __init__(self, result):
        self._result = result
        self.calls = []

    async def execute_sparql_query(self, space_id, sparql, **kwargs):
        self.calls.append((space_id, sparql, kwargs))
        return self._result


_FAILED = {"results": {"bindings": []}, "success": False,
           "error": "[Errno 8] nodename nor servname provided, or not known"}
_EMPTY_OK = {"results": {"bindings": []}}
_ONE_ROW = {"results": {"bindings": [{"entity": {"value": "urn:x", "type": "uri"}}]}}


async def test_a_reported_failure_raises():
    """The exact shape a dead sidecar produces must not return quietly."""
    with pytest.raises(BackendQueryError) as exc:
        await _checked_query(_Backend(_FAILED), "sp", "SELECT * WHERE {}")

    # The backend's own message has to survive — it is what points at the cause.
    # Losing it is most of why the original failure took hours to attribute.
    assert "nodename nor servname" in str(exc.value)


async def test_a_genuinely_empty_result_does_not_raise():
    """An empty match set is a normal answer and must pass through untouched.

    The distinction this whole issue is about: `bindings == []` is not by itself
    a failure. Only the flag says so.
    """
    out = await _checked_query(_Backend(_EMPTY_OK), "sp", "SELECT * WHERE {}")
    assert out == _EMPTY_OK


async def test_rows_pass_through_with_kwargs():
    out = await _checked_query(_Backend(_ONE_ROW), "sp", "Q", multi_vector_config={"a": 1})
    assert out == _ONE_ROW


async def test_kwargs_reach_the_backend():
    """`multi_vector_config` travels through the wrapper — vector queries need it."""
    b = _Backend(_ONE_ROW)
    await _checked_query(b, "sp", "Q", multi_vector_config={"fusion_strategy": "rrf"})
    assert b.calls[0][2] == {"multi_vector_config": {"fusion_strategy": "rrf"}}


def test_status_distinguishes_a_hit_from_a_miss():
    """`FOUND` means "returned >= 1", by the enum's own definition."""
    assert _read_status(["urn:a"]) is OperationStatus.FOUND
    assert _read_status([]) is OperationStatus.EMPTY
    assert _read_status(None) is OperationStatus.EMPTY


def test_empty_is_still_a_success():
    """EMPTY must not read as a failure — nothing matching is a normal outcome.

    Worth pinning: `success` is derived from `status`, so moving an empty read
    from FOUND to EMPTY would break every client that checks `success` if EMPTY
    were not in the success set.
    """
    from vitalgraph.model.result_status import _SUCCESS_STATUSES
    assert OperationStatus.EMPTY in _SUCCESS_STATUSES


def test_every_kgquery_call_site_goes_through_the_wrapper():
    """No raw `execute_sparql_query` may remain in the endpoint.

    This is the assertion that actually prevents recurrence. The bug was not a
    wrong check, it was a MISSING one, repeated across 28 call sites — and a
    missed site fails silently and looks exactly like an empty match set. The
    only occurrence permitted is the one inside the wrapper itself.
    """
    import inspect
    from vitalgraph.endpoint import kgquery_endpoint

    src = inspect.getsource(kgquery_endpoint)
    assert src.count("backend.execute_sparql_query(") == 1, (
        "a KGQuery call site bypasses _checked_query — a backend failure there "
        "will be reported as a successful empty page (issues/082)")


def test_typed_responses_carry_the_outcome_not_just_the_payload():
    """`from_raw` must propagate status, or the fix stops at the server.

    Found while verifying `082` end-to-end: the endpoint correctly returned
    EMPTY for a miss and the client still reported FOUND, because every
    `from_raw` copied only the payload and the typed model fell back to its
    default. A status the caller never receives is not a status.
    """
    from vitalgraph.model.kgqueries_model import (
        KGQueryResponse, KGEntityQueryResponse, FrameQueryResponse,
        RelationQueryResponse, DocumentQueryResponse)

    raw = KGQueryResponse(query_type="entity", status=OperationStatus.EMPTY,
                          message="nothing matched", total_count=0,
                          page_size=25, offset=0)
    for cls in (KGEntityQueryResponse, FrameQueryResponse,
                RelationQueryResponse, DocumentQueryResponse):
        typed = cls.from_raw(raw)
        assert typed.status is OperationStatus.EMPTY, (
            f"{cls.__name__}.from_raw dropped status — the caller cannot tell a "
            f"miss from a hit (issues/082)")
        assert typed.message == "nothing matched", (
            f"{cls.__name__}.from_raw dropped message")

    hit = KGQueryResponse(query_type="entity", status=OperationStatus.FOUND,
                          total_count=3, page_size=25, offset=0)
    assert KGEntityQueryResponse.from_raw(hit).status is OperationStatus.FOUND


async def test_a_dead_backend_surfaces_as_500_through_the_real_endpoint():
    """End to end through `_execute_entity_query`, not just the wrapper.

    This is the assertion that matches the original symptom. Given a backend
    returning exactly what an unresolvable sidecar produces, the endpoint used
    to answer HTTP 200 / status FOUND / total_count 0 / entity_uris []. It must
    now fail loudly, and the backend's own message must survive into the detail
    — that message is what points at the cause, and losing it is most of why the
    original incident took hours to attribute.
    """
    import logging
    from fastapi import HTTPException
    from vitalgraph.endpoint.kgquery_endpoint import KGQueriesEndpoint
    from vitalgraph.model.kgqueries_model import KGQueryRequest, KGQueryCriteria
    from vitalgraph.model.kgentities_model import EntityQueryCriteria
    from vitalgraph.sparql.kg_query_builder import KGQueryCriteriaBuilder

    class DeadBackend:
        async def execute_sparql_query(self, space_id, sparql, **kw):
            return {"results": {"bindings": []}, "success": False,
                    "error": "[Errno 8] nodename nor servname provided, or not known"}

    ep = KGQueriesEndpoint.__new__(KGQueriesEndpoint)   # no router wiring needed
    ep.logger = logging.getLogger(__name__)
    ep.query_builder = KGQueryCriteriaBuilder()

    req = KGQueryRequest(
        criteria=KGQueryCriteria(
            query_type="entity", query_mode="edge",
            source_entity_criteria=EntityQueryCriteria(entity_type="urn:T")),
        page_size=25, offset=0)

    with pytest.raises(HTTPException) as exc:
        await ep._execute_entity_query(DeadBackend(), "sp", "urn:g", req)

    assert exc.value.status_code == 500, (
        "a backend outage is a server-level error, not a domain outcome — it "
        "must not be a 200 (issues/082)")
    assert "nodename nor servname" in str(exc.value.detail)
