"""A transaction that fails to START must give its connection back — issue 231.

`_SparqlSQLCoreAdapter.create_transaction` acquired a connection and then started
a transaction on it with no error handling, so a failed `start()` lost the
connection for the life of the process. Each occurrence silently shrank the pool,
and pool exhaustion presents as `issues/229`: fewer results, HTTP 200, no error.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _SparqlSQLCoreAdapter

pytestmark = [pytest.mark.unit]


class _Tx:
    def __init__(self, fail):
        self.fail = fail

    async def start(self):
        if self.fail:
            raise ConnectionError("server closed the connection unexpectedly")


class _Conn:
    def __init__(self, fail):
        self.fail = fail

    def transaction(self):
        return _Tx(self.fail)


class _Pool:
    def __init__(self, fail):
        self.fail = fail
        self.out = 0
        self.released = []

    async def acquire(self):
        self.out += 1
        return _Conn(self.fail)

    async def release(self, conn):
        self.out -= 1
        self.released.append(conn)


def _adapter(pool):
    impl = SimpleNamespace(_db=SimpleNamespace(_pool=pool))
    return _SparqlSQLCoreAdapter(impl)


async def test_a_failed_start_releases_the_connection():
    pool = _Pool(fail=True)
    with pytest.raises(ConnectionError):
        await _adapter(pool).create_transaction()
    assert pool.out == 0, "the connection leaked when the transaction failed to start"


async def test_a_started_transaction_keeps_its_connection():
    pool = _Pool(fail=False)
    tx = await _adapter(pool).create_transaction()
    assert pool.out == 1 and pool.released == []
    assert tx.connection is not None
