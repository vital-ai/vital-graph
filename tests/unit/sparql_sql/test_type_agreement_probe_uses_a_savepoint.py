"""A probe that is allowed to fail must not take the caller's transaction down.

`_stored_verdict` reads `type_agreement` and treats a missing table as "this
deployment has not run the migration" -- a deliberate, supported outcome. What
it could not do was fail WITHOUT consequence: a failed statement aborts the
whole transaction block server-side, and catching the exception in Python does
not undo that. PostgreSQL only forgets it if the statement ran inside a
SAVEPOINT.

That was harmless while every query ran on its own autocommit connection, where
each statement is its own transaction. `execute_sparql_query` then learned to
accept a CALLER'S connection (`issues/175` class 2), and on that path the
swallowed `UndefinedTableError` poisoned everything the caller ran afterwards
with "current transaction is aborted, commands ignored until end of transaction
block" -- including the caller's own read, which came back empty and looked
like an answer.

Same shape as `issues/177`: a fallback that logged reassurance and then died,
because the abort is server-side state rather than an exception you can decline.

The integration test `test_write_conn_composition.py::
test_a_read_on_the_same_connection_sees_the_uncommitted_write` covers this end
to end, but only while `type_agreement` happens to be absent from the test
database. Create that table and it would pass with the bug restored. This pins
the mechanism instead of the circumstance.
"""

import asyncpg
import pytest

from vitalgraph.db.sparql_sql.edge_type_agreement import (
    NOT_MIGRATED, _NO_VERDICT, _stored_verdict)

SPACE, KIND, PRED = "sp", "edge", "urn:p:1"


class _Savepoint:
    def __init__(self, conn): self._conn = conn
    async def __aenter__(self): self._conn.savepoints += 1; return self
    async def __aexit__(self, *exc): return False


class _Conn:
    """Records whether the probe was wrapped, and what it returned."""

    def __init__(self, result=None, raises=None):
        self.result, self.raises = result, raises
        self.savepoints = 0
        self.fetchval_calls = 0

    def transaction(self):
        return _Savepoint(self)

    async def fetchval(self, *args, **kwargs):
        self.fetchval_calls += 1
        if self.raises:
            raise self.raises
        return self.result


@pytest.fixture(autouse=True)
def _clear_caches():
    """The module memoises "no verdict" per key; a stale entry short-circuits
    the round trip and would make these assert nothing."""
    _NO_VERDICT.clear()
    yield
    _NO_VERDICT.clear()


@pytest.mark.asyncio
async def test_a_missing_table_is_still_not_migrated():
    conn = _Conn(raises=asyncpg.UndefinedTableError("relation does not exist"))
    assert await _stored_verdict(conn, SPACE, KIND, PRED) is NOT_MIGRATED


@pytest.mark.asyncio
async def test_the_probe_runs_inside_a_savepoint():
    """The point of the fix: the statement is wrapped, so its failure rolls
    back only itself and the caller's transaction survives."""
    conn = _Conn(raises=asyncpg.UndefinedTableError("relation does not exist"))
    await _stored_verdict(conn, SPACE, KIND, PRED)
    assert conn.fetchval_calls == 1
    assert conn.savepoints == 1, (
        "the probe must open a savepoint — without one its failure aborts the "
        "caller's transaction and every later statement fails too")


@pytest.mark.asyncio
async def test_the_savepoint_is_used_on_the_success_path_too():
    """Wrapping only the failure would require knowing the outcome first."""
    conn = _Conn(result=True)
    assert await _stored_verdict(conn, SPACE, KIND, PRED) is True
    assert conn.savepoints == 1


@pytest.mark.asyncio
async def test_an_unreadable_row_is_unknown_not_a_verdict():
    conn = _Conn(raises=asyncpg.PostgresError("permission denied"))
    assert await _stored_verdict(conn, SPACE, KIND, PRED) is None


@pytest.mark.asyncio
async def test_no_stored_row_is_unknown():
    conn = _Conn(result=None)
    assert await _stored_verdict(conn, SPACE, KIND, PRED) is None
