"""Maintenance connections SET their fences after connecting.

ANALYZE / VACUUM connections used to carry `statement_timeout` and
`lock_timeout` in libpq's `options` startup parameter. PgBouncer does not
forward `options`, and CloudNativePG's Pooler always lists it in
`ignore_startup_parameters`, so through the pooler the connection succeeded
and the fences were silently dropped: maintenance ran on the role's read-path
fences (60 s / 10 s), and large VACUUMs were cancelled again (`issues/136`).
"""

from __future__ import annotations

import psycopg
import pytest

from vitalgraph.process import maintenance_job as M

_CFG = {"host": "h", "port": 5432, "database": "d", "username": "u", "password": "p"}


class _Conn:
    def __init__(self, fail_on=None):
        self.sql, self.closed, self.fail_on = [], False, fail_on

    def execute(self, sql):
        if self.fail_on and self.fail_on in sql:
            raise psycopg.OperationalError("boom")
        self.sql.append(sql)

    def close(self):
        self.closed = True


def test_fences_are_set_by_SET_not_startup_options(monkeypatch):
    seen = {}
    conn = _Conn()

    def _connect(**kw):
        seen.update(kw)
        return conn

    monkeypatch.setattr(psycopg, "connect", _connect)
    assert M.connect_maintenance_sync(_CFG) is conn
    assert "options" not in seen, "a startup option is dropped by the pooler"
    assert seen["autocommit"] is True, "a session-level SET needs no open transaction"
    assert conn.sql == [f"SET statement_timeout = {M.MAINTENANCE_STATEMENT_TIMEOUT_MS}",
                        f"SET lock_timeout = {M.MAINTENANCE_LOCK_TIMEOUT_MS}"]


def test_a_failed_SET_closes_the_connection(monkeypatch):
    conn = _Conn(fail_on="lock_timeout")
    monkeypatch.setattr(psycopg, "connect", lambda **kw: conn)
    with pytest.raises(psycopg.OperationalError):
        M.connect_maintenance_sync(_CFG)
    assert conn.closed


def test_both_sync_paths_use_it():
    import inspect
    from vitalgraph.db.sparql_sql import auto_analyze
    assert "connect_maintenance_sync(" in inspect.getsource(auto_analyze._sync_analyze)
    assert "connect_maintenance_sync(" in inspect.getsource(M.MaintenanceJob._make_sync_connection)
    src = inspect.getsource(M) + inspect.getsource(auto_analyze)
    assert "options=" not in src.replace("options={", "")


def test_no_pool_sends_server_settings():
    """asyncpg's `server_settings` are startup parameters: PgBouncer refuses
    the connection outright ("unsupported startup parameter")."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2] / "vitalgraph"
    hits = [str(p) for p in root.rglob("*.py") if "server_settings=" in p.read_text()]
    assert not hits, hits
