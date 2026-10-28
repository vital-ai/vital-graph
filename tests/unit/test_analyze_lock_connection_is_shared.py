"""The aux-table ANALYZE lock uses ONE connection per process, not one per adapter.

`SparqlSQLBackendAdapter` is built per request, and each one lazily opened its
own `ProcessLockManager` — a dedicated database connection — the first time it
ran an ANALYZE, and never closed it. The connection went only when the adapter
was freed, as `ResourceWarning: unclosed connection` (~25 per API suite run).

Sharing the connection makes the advisory lock re-entrant for this process's
own tasks (a session-level lock is), so an in-process guard keeps two ANALYZEs
of one space apart.
"""

import asyncio

import pytest

from vitalgraph.db.sparql_sql import auto_analyze
from vitalgraph.kg_impl import kg_backend_utils as kbu

SPACE = "sp_lock_share"
CFG = {"host": "h", "port": 5432, "database": "d", "username": "u", "password": "p"}


class _Mgr:
    made = 0
    instances: list = []

    def __init__(self, cfg):
        type(self).made += 1
        type(self).instances.append(self)
        self.closed = False
        self.held = 0

    async def connect(self):
        await asyncio.sleep(0)

    async def disconnect(self):
        self.closed = True

    async def try_acquire(self, kind, sub):
        self.held += 1          # re-entrant, as a session-level advisory lock is
        return True

    async def release(self, kind, sub):
        self.held -= 1


def _adapter():
    class _Backend:
        schema = None
        db_impl = None
        postgresql_config = CFG
    return kbu.SparqlSQLBackendAdapter(_Backend())


@pytest.fixture(autouse=True)
def _fake_manager(monkeypatch):
    from vitalgraph.process import process_lock_manager as plm
    _Mgr.made = 0
    _Mgr.instances = []
    monkeypatch.setattr(plm, "ProcessLockManager", _Mgr)
    kbu._ANALYZE_LOCK_MANAGERS.clear()
    kbu._ANALYZE_IN_FLIGHT.clear()
    yield
    kbu._ANALYZE_LOCK_MANAGERS.clear()
    kbu._ANALYZE_IN_FLIGHT.clear()


@pytest.mark.asyncio
async def test_adapters_share_one_lock_connection():
    a, b = _adapter(), _adapter()
    m1 = await a._get_analyze_lock_manager()
    m2 = await b._get_analyze_lock_manager()
    assert m1 is m2 and _Mgr.made == 1


@pytest.mark.asyncio
async def test_two_first_callers_leave_one_connection_open():
    m1, m2 = await asyncio.gather(_adapter()._get_analyze_lock_manager(),
                                  _adapter()._get_analyze_lock_manager())
    assert m1 is m2
    assert _Mgr.made == 2           # both connected; the loser closed its own
    assert [m for m in _Mgr.instances if not m.closed] == [m1]


@pytest.mark.asyncio
async def test_a_second_analyze_of_the_space_in_this_process_skips(monkeypatch):
    monkeypatch.setattr(auto_analyze, "was_analyzed_recently",
                        lambda space_id, max_age_seconds=None: False)
    release = asyncio.Event()
    ran = []

    def _slow(self, tables):        # stands in for the thread-offloaded ANALYZE
        ran.append(tables)
        return len(tables)

    async def _to_thread(fn, *args):
        await release.wait()
        return fn(*args)

    monkeypatch.setattr(kbu.SparqlSQLBackendAdapter, "_sync_analyze_tables", _slow)
    monkeypatch.setattr(kbu.asyncio, "to_thread", _to_thread)
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
    monkeypatch.setattr(SparqlSQLSchema, "get_table_names",
                        staticmethod(lambda sid: {k: f"{sid}_{k}" for k in (
                            "rdf_pred_stats", "rdf_stats", "datatype", "edge",
                            "frame_slot", "entity_slot_sort")}))

    first = asyncio.create_task(_adapter()._maybe_analyze_aux_tables(SPACE))
    for _ in range(5):
        await asyncio.sleep(0)
    assert SPACE in kbu._ANALYZE_IN_FLIGHT
    assert await _adapter()._maybe_analyze_aux_tables(SPACE) is False
    release.set()
    assert await first is True
    assert len(ran) == 1
    assert SPACE not in kbu._ANALYZE_IN_FLIGHT
    mgr = next(iter(kbu._ANALYZE_LOCK_MANAGERS.values()))
    assert mgr.held == 0
