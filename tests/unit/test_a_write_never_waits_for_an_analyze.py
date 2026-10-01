"""A write must not wait for an ANALYZE, least of all inside its transaction.

`issues/253`, and this is the root cause of five confirmed lost writes on
2026-09-30. Three call sites did

    async with self._db._internal_pool.acquire() as conn:
        await maybe_analyze(conn, space_id, pg_config=...)

under a comment reading "outside transaction" — which held only when the
enclosing function opened the transaction itself. Every caller that passes
`connection=` (the frame-write path always does) still had its write transaction
OPEN around it, so the write's session sat IDLE IN TRANSACTION for the duration.

Measured on production: those ANALYZEs take **60-98 s each** on `rdf_quad` and
`term`, back to back, against an `idle_in_transaction_session_timeout` of 60 s.
PostgreSQL terminated the write's connection, the ANALYZE finished, the write
resumed one to two seconds later and died in its rollback. The database log
matched it 4 for 4: every idle-in-transaction FATAL fell inside an ANALYZE window.

Two properties are asserted here, and the second is the one that regresses:
scheduling instead of awaiting, and NOT PAYING FOR IT on the writes that have
nothing to analyze.
"""
import asyncio

import pytest

from vitalgraph.db.sparql_sql import auto_analyze
from vitalgraph.db.sparql_sql.auto_analyze import (
    DEFAULT_ANALYZE_THRESHOLD, changes_pending, record_changes,
    schedule_maybe_analyze)

SPACE = "sp_analyze_test"


@pytest.fixture(autouse=True)
def _clean():
    auto_analyze._change_counts.pop(SPACE, None)
    auto_analyze._IN_FLIGHT.pop(SPACE, None)
    yield
    auto_analyze._change_counts.pop(SPACE, None)
    auto_analyze._IN_FLIGHT.pop(SPACE, None)


class FakePool:
    """Counts acquisitions, because the point is that most writes make none."""

    def __init__(self):
        self.acquisitions = 0

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                pool.acquisitions += 1
                return object()

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


class FakeDbImpl:
    def __init__(self):
        self.internal_pool = FakePool()
        self.connection_pool = FakePool()


class TestTheCheapPath:
    def test_below_the_threshold_nothing_is_pending(self):
        record_changes(SPACE, 10)
        assert changes_pending(SPACE) is False

    def test_at_the_threshold_it_is_pending(self):
        record_changes(SPACE, DEFAULT_ANALYZE_THRESHOLD)
        assert changes_pending(SPACE) is True

    @pytest.mark.asyncio
    async def test_an_ordinary_write_acquires_no_connection_at_all(self):
        # THE REGRESSION THAT MATTERS BESIDES THE AWAIT. maybe_analyze tests the
        # threshold only after it has been handed a connection, so the old shape
        # paid an internal-pool acquisition on EVERY write to discover there was
        # nothing to do. At a 50,000-row threshold that is nearly every write.
        db = FakeDbImpl()
        record_changes(SPACE, 1)
        assert schedule_maybe_analyze(db, SPACE) is None
        assert db.internal_pool.acquisitions == 0
        assert db.connection_pool.acquisitions == 0


class TestTheScheduledPath:
    @pytest.mark.asyncio
    async def test_it_returns_before_the_analyze_runs(self, monkeypatch):
        # The property the lost writes needed: the caller is not blocked, so its
        # transaction is not held open across the ANALYZE.
        started = asyncio.Event()
        release = asyncio.Event()

        async def _slow_analyze(conn, space_id, threshold=None, *, pg_config=None):
            started.set()
            await release.wait()
            return True

        monkeypatch.setattr(auto_analyze, "maybe_analyze", _slow_analyze)
        db = FakeDbImpl()
        record_changes(SPACE, DEFAULT_ANALYZE_THRESHOLD)

        task = schedule_maybe_analyze(db, SPACE)
        assert task is not None
        # Scheduling returned while the "ANALYZE" has not even begun.
        assert not started.is_set()

        await asyncio.wait_for(started.wait(), timeout=1)
        assert not task.done()          # still running, and nobody is waiting
        release.set()
        await asyncio.wait_for(task, timeout=1)
        assert db.internal_pool.acquisitions == 1

    @pytest.mark.asyncio
    async def test_the_task_is_strongly_referenced_until_it_finishes(
            self, monkeypatch):
        # A task referenced by nothing can be garbage-collected mid-ANALYZE;
        # callers fire-and-forget the return value, so the registry is the only
        # reference.
        release = asyncio.Event()

        async def _wait(conn, space_id, threshold=None, *, pg_config=None):
            await release.wait()
            return True

        monkeypatch.setattr(auto_analyze, "maybe_analyze", _wait)
        record_changes(SPACE, DEFAULT_ANALYZE_THRESHOLD)
        task = schedule_maybe_analyze(FakeDbImpl(), SPACE)

        assert task in auto_analyze._IN_FLIGHT[SPACE]
        release.set()
        await asyncio.wait_for(task, timeout=1)
        assert SPACE not in auto_analyze._IN_FLIGHT

    @pytest.mark.asyncio
    async def test_a_failing_analyze_is_logged_and_never_raised_at_the_caller(
            self, monkeypatch, caplog):
        async def _boom(conn, space_id, threshold=None, *, pg_config=None):
            raise RuntimeError("ANALYZE exploded")

        monkeypatch.setattr(auto_analyze, "maybe_analyze", _boom)
        record_changes(SPACE, DEFAULT_ANALYZE_THRESHOLD)

        with caplog.at_level("ERROR"):
            task = schedule_maybe_analyze(FakeDbImpl(), SPACE)
            with pytest.raises(RuntimeError):
                await task                      # the task itself still failed
            await asyncio.sleep(0)              # let the done-callback run
        assert any("auto_analyze" in r.getMessage() and "exploded" in r.getMessage()
                   for r in caplog.records), caplog.text
        assert SPACE not in auto_analyze._IN_FLIGHT

    def test_no_event_loop_is_not_an_error(self):
        # Called from sync context (a script, a test): skip, do not explode.
        record_changes(SPACE, DEFAULT_ANALYZE_THRESHOLD)
        assert schedule_maybe_analyze(FakeDbImpl(), SPACE) is None


class TestNoCallSiteAwaitsItAnyMore:
    def test_the_write_paths_schedule_rather_than_await(self):
        # The guard. Any of these three regaining an awaited `maybe_analyze`
        # restores the lost-write defect, and the two that take a `connection=`
        # argument restore it inside a caller's transaction.
        #
        # Over the AST, not the text — the comments explaining the fix quote the
        # old code, so a substring check trips on the explanation. The same trap
        # caught the `uuid4` guard in this issue; it is the second time, hence the
        # note.
        import ast
        import inspect

        from vitalgraph.db.sparql_sql import sparql_sql_space_impl as mod

        tree = ast.parse(inspect.getsource(mod))

        awaited, scheduled, internal_acquires = [], [], []
        for node in ast.walk(tree):
            if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
                fn = node.value.func
                if getattr(fn, "id", None) == "maybe_analyze" or \
                        getattr(fn, "attr", None) == "maybe_analyze":
                    awaited.append(node.lineno)
            if isinstance(node, ast.Call):
                fn = node.func
                if getattr(fn, "id", None) == "schedule_maybe_analyze":
                    scheduled.append(node.lineno)
                # `<something>._internal_pool.acquire()`
                if getattr(fn, "attr", None) == "acquire" and \
                        getattr(getattr(fn, "value", None), "attr", None) == "_internal_pool":
                    internal_acquires.append(node.lineno)

        assert not awaited, f"maybe_analyze is awaited at {awaited}"
        assert not internal_acquires, \
            f"an internal-pool connection is acquired inline at {internal_acquires}"
        assert len(scheduled) == 3, f"expected 3 scheduled sites, found {scheduled}"
