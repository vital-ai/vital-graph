"""An FTS criterion the space cannot answer is INVALID_REQUEST, not an empty page.

Two failures were observed on 2026-09-22 against a 49.7M-quad space, and they
were the same defect from opposite sides:

* a target slot type with no enabled search mapping is never populated, so the
  query ran and returned a confident, successful EMPTY page — indistinguishable
  from "no messages match";
* a nonexistent index crashed with HTTP 500 carrying the raw SQL error
  `relation "<space>_fts_<name>" does not exist`.

Both are requests the caller can fix, so both are domain outcomes: HTTP 200 with
`status=invalid_request` and a message naming what is missing.

The check resolves the index name the SAME way the pushdown does
(`vg_functions._resolve_index_name`): an alias in `{space}_search_mapping`
resolves through `{space}_search_mapping_index` to the real FTS index. A check
stricter than the pushdown would reject queries that work.

It must never be the thing that fails a query: no pool, or any unexpected error,
returns None and the query runs as before.
"""
from __future__ import annotations

import logging

import asyncpg
import pytest

from vitalgraph.endpoint.kgquery_endpoint import KGQueriesEndpoint
from vitalgraph.model.kgqueries_model import FTSCriteria, FTSTarget

SENT = "urn:acme:kg:slot:MsgContent"
DRAFT = "urn:acme:kg:slot:GenMsgContent"


class _Conn:
    """Answers the four questions the check asks, from a configured state."""

    def __init__(self, *, registry=True, registered=("message_content",),
                 tables=("sp_fts_message_content",), mapped=(SENT,), alias=None,
                 explode=None):
        self.registry, self.registered, self.tables = registry, set(registered), set(tables)
        self.mapped, self.alias, self.explode = set(mapped), alias, explode
        self.seen = []

    async def fetchval(self, sql, *args):
        self.seen.append(sql)
        if self.explode:
            raise self.explode
        if "search_mapping_index" in sql and "LIMIT 1" in sql:
            return self.alias
        if "_fts_index WHERE" in sql:
            if not self.registry:
                raise asyncpg.UndefinedTableError('relation "sp_fts_index" does not exist')
            return 1 if args[0] in self.registered else None
        if "to_regclass" in sql:
            return args[0] in self.tables
        raise AssertionError(f"unexpected fetchval: {sql}")

    async def fetch(self, sql, *args):
        self.seen.append(sql)
        targets = args[0]
        return [{"type_uri": t} for t in targets if t in self.mapped]


class _Acquire:
    def __init__(self, conn): self.conn = conn
    async def __aenter__(self): return self.conn
    async def __aexit__(self, *a): return False


class _Pool:
    def __init__(self, conn): self.conn = conn
    def acquire(self): return _Acquire(self.conn)


class _Backend:
    def __init__(self, conn):
        self.db_impl = type("DbImpl", (), {"connection_pool": _Pool(conn)})()


def _endpoint():
    ep = KGQueriesEndpoint.__new__(KGQueriesEndpoint)   # no router wiring needed
    ep.logger = logging.getLogger(__name__)
    return ep


def _fts(*slot_types, index="message_content"):
    # `kind` is required once there is more than one target (model rule).
    return FTSCriteria(text="saved", index_name=index,
                       targets=[FTSTarget(slot_type=t, kind=f"k{i}")
                                for i, t in enumerate(slot_types)])


async def _problem(conn, fts):
    return await _endpoint()._fts_configuration_problem(_Backend(conn), "sp", fts)


@pytest.mark.asyncio
async def test_a_fully_configured_target_passes():
    assert await _problem(_Conn(), _fts(SENT)) is None


@pytest.mark.asyncio
async def test_an_unmapped_target_is_named_not_answered_with_an_empty_page():
    """The live case: drafts existed, the mapping covered sent only."""
    problem = await _problem(_Conn(mapped=(SENT,)), _fts(SENT, DRAFT))
    assert problem is not None
    assert DRAFT in problem
    assert SENT not in problem, "only the UNCOVERED type is the caller's problem"


@pytest.mark.asyncio
async def test_a_missing_index_is_a_message_not_a_raw_sql_error():
    problem = await _problem(_Conn(registered=()), _fts(SENT, index="no_such_index"))
    assert problem is not None and "no_such_index" in problem
    assert "relation" not in problem, "the raw SQL error is what this replaces"


@pytest.mark.asyncio
async def test_a_registered_index_whose_table_is_gone_is_missing_too():
    problem = await _problem(_Conn(tables=()), _fts(SENT))
    assert problem is not None and "does not exist" in problem


@pytest.mark.asyncio
async def test_a_space_without_fts_at_all_says_so():
    problem = await _problem(_Conn(registry=False), _fts(SENT))
    assert problem is not None and "not configured" in problem


@pytest.mark.asyncio
async def test_an_alias_resolves_the_way_the_pushdown_resolves_it():
    """`msg_search` is a mapping alias for the real index `message_content`.

    A check that looked the alias up directly in the index registry would
    reject a query the pushdown answers correctly.
    """
    conn = _Conn(alias="message_content", registered=("message_content",),
                 tables=("sp_fts_message_content",))
    assert await _problem(conn, _fts(SENT, index="msg_search")) is None


@pytest.mark.asyncio
async def test_the_check_never_fails_a_query():
    """No pool, or any unexpected error: say nothing, let the query run."""
    ep = _endpoint()
    assert await ep._fts_configuration_problem(object(), "sp", _fts(SENT)) is None
    assert await _problem(_Conn(explode=RuntimeError("connection reset")), _fts(SENT)) is None
