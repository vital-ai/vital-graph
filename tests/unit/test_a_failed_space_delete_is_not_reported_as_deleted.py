"""A space delete that failed must not be reported as deleted (`issues/342`).

Found deleting `nurture_typed` seconds after the app started, while startup work
held locks on the space: `delete_space_storage` hit `lock_timeout` partway
through its DROPs. The statements ran outside a transaction, so some tables had
already been dropped and the rest stayed. It returned False, and
`SpaceManager.delete_space_with_tables` read False as "may not exist". It then
unregistered the space, sent the "deleted" notifications and returned success.
The client got `error_code 0`. The `space` row and 14 tables (21 GB) stayed, and
`list_spaces` no longer showed them.

Pinned here:
- the drop is ONE transaction, so a failure leaves the space whole;
- lock contention (55P03, 40P01) is retried and anything else is not;
- the manager reports a failed drop as a failure, keeps the space registered,
  and sends no "deleted" notification.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

import asyncpg
import pytest

from vitalgraph.db.sparql_sql import sparql_sql_space_impl as impl_mod
from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl
from vitalgraph.space.space_impl import SpaceImpl
from vitalgraph.space.space_manager import SpaceManager, SpaceRecord


# ---------------------------------------------------------------- backend drop

class _Conn:
    def __init__(self, log):
        self.log = log
        self.in_tx = False

    @asynccontextmanager
    async def transaction(self):
        self.in_tx = True
        self.log.append("BEGIN")
        try:
            yield
        except BaseException:
            self.log.append("ROLLBACK")
            raise
        else:
            self.log.append("COMMIT")
        finally:
            self.in_tx = False

    async def execute(self, sql, *args):
        self.log.append(("exec", sql.split()[0], self.in_tx))


class _Pool:
    def __init__(self, log):
        self.log = log
        self.acquired = 0

    @asynccontextmanager
    async def acquire(self):
        self.acquired += 1
        yield _Conn(self.log)


def _backend(pool):
    b = object.__new__(SparqlSQLSpaceImpl)
    b.db_impl = type("Db", (), {"_pool": pool})()
    return b


@pytest.fixture
def no_sleep(monkeypatch):
    slept = []

    async def _sleep(s):
        slept.append(s)
    monkeypatch.setattr(impl_mod.asyncio, "sleep", _sleep)
    return slept


def _drop_that_fails(monkeypatch, failures):
    """drop_space raising the given exceptions in order, then succeeding."""
    seq = list(failures)

    async def drop_space(conn, space_id):
        conn.log.append(("drop_space", conn.in_tx))
        if seq:
            raise seq.pop(0)
    monkeypatch.setattr(impl_mod.SparqlSQLSchema, "drop_space", staticmethod(drop_space))


def _lock_timeout():
    return asyncpg.LockNotAvailableError("canceling statement due to lock timeout")


async def test_the_whole_drop_runs_in_one_transaction(monkeypatch, no_sleep):
    log = []
    _drop_that_fails(monkeypatch, [])
    assert await _backend(_Pool(log)).delete_space_storage("sp") is True
    assert log[0] == "BEGIN" and log[-1] == "COMMIT"
    # drop_space and both row deletes all ran inside it.
    assert ("drop_space", True) in log
    assert [e for e in log if isinstance(e, tuple) and e[0] == "exec"] == [
        ("exec", "DELETE", True), ("exec", "DELETE", True)]


async def test_a_lock_timeout_rolls_back_and_is_retried(monkeypatch, no_sleep):
    log = []
    pool = _Pool(log)
    _drop_that_fails(monkeypatch, [_lock_timeout()])
    assert await _backend(pool).delete_space_storage("sp") is True
    assert pool.acquired == 2
    assert log.count("ROLLBACK") == 1 and log.count("COMMIT") == 1
    assert no_sleep == [impl_mod.SparqlSQLSpaceImpl.DROP_RETRY_BASE_SECONDS]


async def test_a_deadlock_is_retried_too(monkeypatch, no_sleep):
    log = []
    _drop_that_fails(monkeypatch, [asyncpg.DeadlockDetectedError("deadlock detected")])
    assert await _backend(_Pool(log)).delete_space_storage("sp") is True


async def test_contention_that_outlasts_the_retries_is_a_failure(monkeypatch, no_sleep):
    log = []
    pool = _Pool(log)
    n = SparqlSQLSpaceImpl.DROP_ATTEMPTS
    _drop_that_fails(monkeypatch, [_lock_timeout() for _ in range(n)])
    assert await _backend(pool).delete_space_storage("sp") is False
    assert pool.acquired == n
    assert log.count("ROLLBACK") == n and "COMMIT" not in log


async def test_any_other_error_fails_at_once(monkeypatch, no_sleep):
    log = []
    pool = _Pool(log)
    _drop_that_fails(monkeypatch, [RuntimeError("disk full")])
    assert await _backend(pool).delete_space_storage("sp") is False
    assert pool.acquired == 1 and no_sleep == []
    assert "ROLLBACK" in log and "COMMIT" not in log


# ---------------------------------------------------------------- the manager

class _Backend:
    def __init__(self, destroy_ok):
        self.destroy_ok = destroy_ok

    async def space_exists(self, space_id):
        return True

    async def delete_space_storage(self, space_id):
        return self.destroy_ok


class _Signals:
    def __init__(self):
        self.sent = []

    async def notify_spaces_changed(self, kind):
        self.sent.append(("spaces", kind))

    async def notify_space_changed(self, space_id, kind):
        self.sent.append((space_id, kind))


def _manager(destroy_ok):
    backend = _Backend(destroy_ok)
    signals = _Signals()
    db_impl = type("DbImpl", (), {"get_signal_manager": lambda self: signals})()
    m = SpaceManager(db_impl=db_impl, space_backend=backend)
    impl = SpaceImpl(space_id="sp", backend=backend)
    m._spaces["sp"] = SpaceRecord(space_id="sp", space_impl=impl)
    return m, signals


async def test_a_failed_drop_is_reported_and_the_space_stays_registered():
    m, signals = _manager(destroy_ok=False)
    assert await m.delete_space_with_tables("sp") is False
    assert "sp" in m._spaces, "a space whose drop failed was unregistered"
    assert signals.sent == [], "a 'deleted' notification went out for a space that is still there"


async def test_a_successful_drop_unregisters_and_notifies():
    m, signals = _manager(destroy_ok=True)
    assert await m.delete_space_with_tables("sp") is True
    assert "sp" not in m._spaces
    assert ("sp", signals.sent[-1][1]) == signals.sent[-1]


# ------------------------------------------------- what the caller is told

from fastapi import HTTPException

from vitalgraph.api.vitalgraph_api import SpaceDeleteFailed, VitalGraphAPI
from vitalgraph.client.endpoint.spaces_endpoint import SpacesEndpoint


class _Mgr:
    def __init__(self, deleted, still_there):
        self.deleted = deleted
        self.space_backend = type("B", (), {"space_exists": self._exists})()
        self._still = still_there

    async def _exists(self, space_id):
        return self._still

    async def delete_space_with_tables(self, space_id):
        return self.deleted


def _api(mgr):
    api = object.__new__(VitalGraphAPI)
    api.space_manager = mgr
    return api


async def test_a_failed_drop_on_a_present_space_is_a_failure_not_not_found():
    with pytest.raises(SpaceDeleteFailed):
        await _api(_Mgr(deleted=False, still_there=True)).delete_space("sp", {"username": "t"})


async def test_a_missing_space_is_still_not_found():
    with pytest.raises(HTTPException) as e:
        await _api(_Mgr(deleted=False, still_there=False)).delete_space("sp", {"username": "t"})
    assert e.value.status_code == 404


class _Resp:
    status_code = 200

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def _client(body):
    ep = object.__new__(SpacesEndpoint)
    ep._check_connection = lambda: None
    ep._get_server_url = lambda: "http://x"

    async def _req(method, url, **kw):
        return _Resp(body)
    ep._make_authenticated_request = _req
    return ep


@pytest.mark.parametrize("status,ok", [
    ("deleted", True), ("store_failed", False), ("not_found", False), ("invalid_request", False)])
async def test_the_client_reports_the_servers_verdict_not_the_http_code(status, ok):
    body = {"status": status, "success": ok, "message": "m",
            "deleted_count": 1 if ok else 0, "deleted_uris": []}
    r = await _client(body).delete_space("sp")
    assert (r.error_code == 0) is ok, f"{status}: error_code={r.error_code}"
    assert r.is_success is ok
