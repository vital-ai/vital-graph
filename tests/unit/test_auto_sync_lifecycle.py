"""auto_sync task lifecycle vs. space deletion (L0 — no DB, no model load).

auto_sync runs fire-and-forget background tasks. Callers discard the returned
Task, so before the in-flight registry there was no way to stop work already
queued against a space that was being deleted. The observed symptom:

    .811  Dropped space tables for: apitest_f95db9fb
    .814  DELETE /api/spaces -> 200 OK
    .858  POST api.openai.com/v1/embeddings 200      <-- billed, space is gone
    .878  ERROR: relation "..._geo_config" does not exist

The individual queries were already guarded, so nothing crashed — but the
embedding calls cost money and PostgreSQL logs every failed statement
server-side, which reads like a schema bug.

Two defences, both covered here:
  * cancel_space_syncs()  — stops tasks in THIS process, awaited before drop
  * _space_still_exists() — backstop for a deletion in ANOTHER worker process
"""

import asyncio

import pytest

from vitalgraph.vectorization import auto_sync

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def _clean_registry():
    auto_sync._IN_FLIGHT.clear()
    yield
    auto_sync._IN_FLIGHT.clear()


class _Conn:
    """Minimal asyncpg-ish connection returning a canned to_regclass result."""

    def __init__(self, exists: bool):
        self._exists = exists
        self.queries = []

    async def fetchval(self, sql, *args):
        self.queries.append((sql, args))
        return self._exists


class TestSpaceStillExists:
    async def test_true_when_table_present(self):
        assert await auto_sync._space_still_exists(_Conn(True), "sp") is True

    async def test_false_when_table_absent(self):
        assert await auto_sync._space_still_exists(_Conn(False), "sp") is False

    async def test_checks_the_core_space_table(self):
        conn = _Conn(True)
        await auto_sync._space_still_exists(conn, "myspace")
        _, args = conn.queries[0]
        assert args == ("myspace_rdf_quad",)


class TestScheduleSyncRegistry:
    async def test_task_is_registered_then_cleaned_up(self, monkeypatch):
        started = asyncio.Event()

        async def _fake_run(*a, **kw):
            started.set()
            await asyncio.sleep(0)

        monkeypatch.setattr(auto_sync, "_run_sync", _fake_run)
        task = auto_sync.schedule_sync(
            db_impl=object(), space_id="sp1", subject_uris=["urn:a"], graph_uri="g",
        )
        assert task in auto_sync._IN_FLIGHT["sp1"]
        await started.wait()
        await task
        # done-callback runs on the next loop pass
        await asyncio.sleep(0)
        assert "sp1" not in auto_sync._IN_FLIGHT

    async def test_no_subjects_schedules_nothing(self):
        assert auto_sync.schedule_sync(
            db_impl=object(), space_id="sp1", subject_uris=[], graph_uri="g",
        ) is None
        assert auto_sync._IN_FLIGHT == {}


class TestCancelSpaceSyncs:
    async def test_cancels_in_flight_work(self, monkeypatch):
        """The task must not survive the call — it would outlive the tables."""
        ran_to_completion = False

        async def _slow(*a, **kw):
            nonlocal ran_to_completion
            await asyncio.sleep(10)
            ran_to_completion = True

        monkeypatch.setattr(auto_sync, "_run_sync", _slow)
        task = auto_sync.schedule_sync(
            db_impl=object(), space_id="sp1", subject_uris=["urn:a"], graph_uri="g",
        )
        await asyncio.sleep(0)

        assert await auto_sync.cancel_space_syncs("sp1") == 1
        assert task.cancelled()
        assert ran_to_completion is False
        assert "sp1" not in auto_sync._IN_FLIGHT

    async def test_awaits_before_returning(self, monkeypatch):
        """Tables get dropped right after; a task still unwinding would race."""
        async def _slow(*a, **kw):
            await asyncio.sleep(10)

        monkeypatch.setattr(auto_sync, "_run_sync", _slow)
        task = auto_sync.schedule_sync(
            db_impl=object(), space_id="sp1", subject_uris=["urn:a"], graph_uri="g",
        )
        await asyncio.sleep(0)
        await auto_sync.cancel_space_syncs("sp1")
        assert task.done()

    async def test_only_targets_the_named_space(self, monkeypatch):
        async def _slow(*a, **kw):
            await asyncio.sleep(10)

        monkeypatch.setattr(auto_sync, "_run_sync", _slow)
        keep = auto_sync.schedule_sync(
            db_impl=object(), space_id="keep", subject_uris=["urn:a"], graph_uri="g",
        )
        drop = auto_sync.schedule_sync(
            db_impl=object(), space_id="drop", subject_uris=["urn:b"], graph_uri="g",
        )
        await asyncio.sleep(0)

        assert await auto_sync.cancel_space_syncs("drop") == 1
        assert drop.cancelled()
        assert not keep.done()

        keep.cancel()
        await asyncio.gather(keep, return_exceptions=True)

    async def test_unknown_space_is_a_no_op(self):
        assert await auto_sync.cancel_space_syncs("never_seen") == 0

    async def test_cancellation_is_not_logged_as_failure(self, monkeypatch):
        """A cancelled task is expected teardown, not an error."""
        errors = []
        monkeypatch.setattr(auto_sync.logger, "error",
                            lambda *a, **kw: errors.append(a))

        async def _slow(*a, **kw):
            await asyncio.sleep(10)

        monkeypatch.setattr(auto_sync, "_run_sync", _slow)
        auto_sync.schedule_sync(
            db_impl=object(), space_id="sp1", subject_uris=["urn:a"], graph_uri="g",
        )
        await asyncio.sleep(0)
        await auto_sync.cancel_space_syncs("sp1")
        await asyncio.sleep(0)
        assert errors == []

    async def test_slow_task_times_out_rather_than_hanging_deletion(self, monkeypatch):
        """Deletion must not block indefinitely on a task that resists cancelling.

        The stub swallows the FIRST cancellation only, so the timeout path is
        exercised and the test can still clean up afterwards.
        """
        swallowed = asyncio.Event()

        async def _stubborn(*a, **kw):
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                swallowed.set()
                await asyncio.sleep(10)   # a second cancel WILL end this

        monkeypatch.setattr(auto_sync, "_run_sync", _stubborn)
        task = auto_sync.schedule_sync(
            db_impl=object(), space_id="sp1", subject_uris=["urn:a"], graph_uri="g",
        )
        await asyncio.sleep(0)

        loop = asyncio.get_running_loop()
        t0 = loop.time()
        count = await auto_sync.cancel_space_syncs("sp1", timeout=0.05)
        elapsed = loop.time() - t0

        assert count == 1          # reported even though it did not stop in time
        assert swallowed.is_set()  # it really did resist the first cancel
        # The point of the timeout: deletion returns promptly instead of
        # blocking on the task's 10s sleep.
        assert elapsed < 1.0, f"cancel_space_syncs blocked for {elapsed:.2f}s"

        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
