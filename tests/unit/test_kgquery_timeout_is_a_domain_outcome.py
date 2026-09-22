"""A KGQuery that TIMES OUT is HTTP 200 `query_failed`; an OUTAGE stays HTTP 500.

Every KGQuery path turned any exception into HTTP 500, while the entity and type
endpoints report the same failed read as HTTP 200 with `status=query_failed`.
Observed 2026-09-22: eleven broad-shape FTS KGQueries hit `statement_timeout`
and each came back a 500.

The split, and why it is the right one:

* a query that ran and exceeded its budget is a DOMAIN outcome — the request was
  answerable, it was too expensive, and the caller can narrow it or drop the
  count — so it is reported in the body;
* an unreachable sidecar or a lost connection is a SERVER fault, which
  `issues/082` deliberately pinned as HTTP 500 and
  `test_kgquery_reports_backend_failure.py` still asserts.

The classifier reads PostgreSQL's own message to separate a statement timeout
from an administrator's cancel, which share SQLSTATE 57014.
"""
from __future__ import annotations

import asyncio
import logging

import asyncpg
import pytest
from fastapi import HTTPException

from vitalgraph.endpoint.kgquery_endpoint import KGQueriesEndpoint
from vitalgraph.model.kgentities_model import EntityQueryCriteria
from vitalgraph.model.kgqueries_model import KGQueryCriteria, KGQueryRequest
from vitalgraph.model.result_status import OperationStatus
from vitalgraph.sparql.kg_query_builder import KGQueryCriteriaBuilder
from vitalgraph.utils.db_retry import is_query_timeout


class TestTheClassifier:
    def test_a_statement_timeout_is_a_timeout(self):
        assert is_query_timeout(asyncpg.QueryCanceledError(
            "canceling statement due to statement timeout"))

    def test_the_drivers_command_timeout_is_a_timeout(self):
        assert is_query_timeout(asyncio.TimeoutError())

    def test_an_administrators_cancel_is_not(self):
        """Same SQLSTATE 57014 as a statement timeout; the message separates them."""
        assert not is_query_timeout(asyncpg.QueryCanceledError(
            "canceling statement due to user request"))

    def test_an_outage_is_not(self):
        assert not is_query_timeout(OSError("[Errno 8] nodename nor servname provided"))
        assert not is_query_timeout(RuntimeError("connection was closed"))


def _endpoint():
    ep = KGQueriesEndpoint.__new__(KGQueriesEndpoint)   # no router wiring needed
    ep.logger = logging.getLogger(__name__)
    ep.query_builder = KGQueryCriteriaBuilder()
    return ep


def _request():
    return KGQueryRequest(
        criteria=KGQueryCriteria(
            query_type="entity", query_mode="edge",
            source_entity_criteria=EntityQueryCriteria(entity_type="urn:T")),
        page_size=25, offset=7)


class _Backend:
    """Returns exactly the failure dict `execute_sparql_query` produces."""

    def __init__(self, error, timed_out):
        self.error, self.timed_out = error, timed_out

    async def execute_sparql_query(self, space_id, sparql, **kw):
        return {"results": {"bindings": []}, "success": False,
                "error": self.error, "timed_out": self.timed_out}


@pytest.mark.asyncio
async def test_a_timed_out_kgquery_is_a_200_query_failed():
    backend = _Backend("canceling statement due to statement timeout", True)
    resp = await _endpoint()._execute_entity_query(backend, "sp", "urn:g", _request())
    assert resp.status is OperationStatus.QUERY_FAILED
    assert resp.success is False, "a timeout must never read as an empty success"
    assert "statement timeout" in resp.message, "the cause must survive to the caller"
    assert (resp.page_size, resp.offset) == (25, 7)


@pytest.mark.asyncio
async def test_an_outage_is_still_a_500():
    """The `issues/082` half, restated beside the new one so the split is visible."""
    backend = _Backend("[Errno 8] nodename nor servname provided, or not known", False)
    with pytest.raises(HTTPException) as exc:
        await _endpoint()._execute_entity_query(backend, "sp", "urn:g", _request())
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_a_backend_without_the_flag_is_classified_from_the_message_type():
    """An older backend dict carries no `timed_out`; an outage must not be
    promoted to a 200 by its absence."""
    class Legacy:
        async def execute_sparql_query(self, space_id, sparql, **kw):
            return {"results": {"bindings": []}, "success": False,
                    "error": "canceling statement due to statement timeout"}
    with pytest.raises(HTTPException) as exc:
        await _endpoint()._execute_entity_query(Legacy(), "sp", "urn:g", _request())
    assert exc.value.status_code == 500, (
        "without the structured flag the failure is a bare string, and a string "
        "is not classified — the conservative answer is the old 500")
