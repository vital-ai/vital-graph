"""A write that dies says which phase it got to (`issues/253`).

Five production writes were lost to `idle_in_transaction_session_timeout`: the
transaction was open, NO statement was running, and nothing arrived for 60 s, so
PostgreSQL terminated the connection and the write never committed. Neither log
could say where the request was parked:

  * the DATABASE log cannot — three of the four killed sessions in that hour
    appear in it only as a FATAL, with no slow statement at all, and
    `log_lock_waits` and `log_disconnections` are off;
  * the APPLICATION log could not either — the four pre-delete scans are timed,
    but acquiring the connection, BEGIN, the lock, the prop-sort syncs, the
    insert and the COMMIT were not.

So the phases are timed, and — the part that makes it work — **the breakdown is
logged on the FAILURE path too**. Every one of these losses ends in an exception,
so a line emitted only on success would have missed all five. A phase that never
completed prints `-`, and the missing tail is the answer.
"""
import pytest

from vitalgraph.kg_impl.kg_backend_utils import (
    _WRITE_PHASES, SparqlSQLBackendAdapter, _phase_breakdown)


class TestTheBreakdown:
    def test_a_complete_write_reports_every_phase(self):
        marks = {name: 100.0 + i for i, name in enumerate(_WRITE_PHASES, start=1)}
        out = _phase_breakdown(100.0, marks)
        for name in _WRITE_PHASES:
            assert f"{name}=1.000s" in out

    def test_the_numbers_are_per_phase_not_cumulative(self):
        # They must sum to the elapsed total; printing running totals would make
        # every phase look as slow as the whole write.
        marks = {"acquire": 100.5, "begin": 100.5, "lock": 101.0,
                 "presync": 103.0, "insert": 103.5, "commit": 104.0}
        out = _phase_breakdown(100.0, marks)
        assert "acquire=0.500s" in out
        assert "lock=0.500s" in out
        assert "presync=2.000s" in out
        assert "commit=0.500s" in out

    def test_a_phase_that_never_completed_prints_a_dash(self):
        # THE PRODUCTION CASE: parked with the transaction open, so everything
        # from `presync` onward is missing and that is what names the stall.
        out = _phase_breakdown(100.0, {"acquire": 100.01, "begin": 100.01,
                                       "lock": 100.02})
        assert "lock=0.010s" in out
        assert "presync=-" in out and "insert=-" in out and "commit=-" in out

    def test_a_write_that_never_started_is_all_dashes(self):
        out = _phase_breakdown(100.0, {})
        assert out == "phases " + " ".join(f"{n}=-" for n in _WRITE_PHASES)

    def test_the_order_is_fixed(self):
        # Fixed order, so two lines can be compared by eye and a missing tail is
        # visibly a tail rather than a gap in the middle.
        out = _phase_breakdown(100.0, {n: 100.0 for n in _WRITE_PHASES})
        positions = [out.index(f"{n}=") for n in _WRITE_PHASES]
        assert positions == sorted(positions)


class FakeTransaction:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        self.conn.statements.append("BEGIN")
        return self

    async def __aexit__(self, *exc):
        self.conn.statements.append("ROLLBACK" if exc[0] else "COMMIT")
        return False


class FakeConn:
    def __init__(self):
        self.statements = []

    def transaction(self):
        return FakeTransaction(self)

    def is_in_transaction(self):
        return True

    async def execute(self, sql, *args):
        self.statements.append(sql)
        return "DELETE 0"


class FakeSchema:
    @staticmethod
    def get_table_names(space_id):
        return {"rdf_quad": f"{space_id}_rdf_quad"}


class FakeBackend:
    schema = FakeSchema()

    class db_impl:
        connection_pool = None


@pytest.fixture
def adapter():
    return SparqlSQLBackendAdapter(FakeBackend())


class TestTheFailurePath:
    """The load-bearing half: these losses all end in an exception."""

    @pytest.mark.asyncio
    async def test_a_failure_logs_the_breakdown_with_its_tail_missing(
            self, adapter, monkeypatch, caplog):
        from vitalgraph.db.sparql_sql import entity_lock

        async def _boom(conn, uris, budget_s=None):
            raise RuntimeError("the connection is closed")

        monkeypatch.setattr(entity_lock, "lock_entities", _boom)

        with caplog.at_level("ERROR"):
            ok = await adapter.update_subjects_graph(
                "sp", "urn:g", ["urn:s:1"], [], lock_uris=["urn:e:1"],
                conn=FakeConn())

        assert ok is False
        failures = [r.getMessage() for r in caplog.records
                    if "update_subjects_graph failed" in r.getMessage()]
        assert len(failures) == 1, caplog.text
        line = failures[0]
        # The cause, unmasked...
        assert "the connection is closed" in line
        # ...and WHERE it stopped: past BEGIN, never past the lock.
        assert "phases " in line
        assert "acquire=" in line and "begin=" in line
        assert "lock=-" in line and "presync=-" in line and "commit=-" in line

    @pytest.mark.asyncio
    async def test_a_lock_timeout_also_carries_the_breakdown(
            self, adapter, monkeypatch, caplog):
        from vitalgraph.db.sparql_sql import entity_lock
        from vitalgraph.db.sparql_sql.entity_lock import EntityLockTimeout

        async def _timeout(conn, uris, budget_s=None):
            raise EntityLockTimeout("urn:lead:42", 123, 10.0)

        monkeypatch.setattr(entity_lock, "lock_entities", _timeout)

        with caplog.at_level("ERROR"):
            ok = await adapter.update_subjects_graph(
                "sp", "urn:g", ["urn:s:1"], [], lock_uris=["urn:lead:42"],
                conn=FakeConn())

        assert ok is False
        line = next(r.getMessage() for r in caplog.records
                    if "LOCK TIMEOUT" in r.getMessage())
        assert "urn:lead:42" in line
        assert "phases " in line and "lock=-" in line
