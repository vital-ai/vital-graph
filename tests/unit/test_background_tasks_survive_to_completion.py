"""Fire-and-forget needs three things, and each has been got wrong somewhere.

`issues/253`. Deferrable work must not be awaited by a request — five production
writes were lost because one `await` on an ANALYZE held a write transaction open
past `idle_in_transaction_session_timeout`. Scheduling it instead is only safe if
the task cannot be collected mid-flight, its failure is visible, and the absence
of an event loop is not an error.
"""
import asyncio
import gc

import pytest

from vitalgraph.utils.background import BackgroundTasks


class TestTheStrongReference:
    @pytest.mark.asyncio
    async def test_a_running_task_is_held_and_then_released(self):
        tasks = BackgroundTasks("probe")
        release = asyncio.Event()

        async def _work():
            await release.wait()

        task = tasks.schedule(_work(), key="k")
        assert tasks.in_flight("k") == 1
        release.set()
        await asyncio.wait_for(task, timeout=1)
        assert tasks.in_flight("k") == 0

    @pytest.mark.asyncio
    async def test_it_survives_the_caller_dropping_the_task_and_a_gc_pass(self):
        # THE REASON THIS CLASS EXISTS. asyncio keeps only a weak reference to a
        # running task, and every caller of a fire-and-forget helper drops the
        # return value by definition — so without the registry the work can
        # vanish half done, silently.
        tasks = BackgroundTasks("probe")
        done = asyncio.Event()

        async def _work():
            await asyncio.sleep(0.05)
            done.set()

        tasks.schedule(_work(), key="k")     # return value deliberately dropped
        gc.collect()
        await asyncio.wait_for(done.wait(), timeout=1)

    @pytest.mark.asyncio
    async def test_several_tasks_under_one_key_are_all_tracked(self):
        tasks = BackgroundTasks("probe")
        release = asyncio.Event()

        async def _work():
            await release.wait()

        created = [tasks.schedule(_work(), key="k") for _ in range(3)]
        assert tasks.in_flight("k") == 3
        release.set()
        await asyncio.wait_for(asyncio.gather(*created), timeout=1)
        assert tasks.in_flight("k") == 0


class TestFailures:
    @pytest.mark.asyncio
    async def test_a_failure_is_logged_with_the_label_and_key(self, caplog):
        tasks = BackgroundTasks("probe-label")

        async def _boom():
            raise RuntimeError("it broke")

        with caplog.at_level("ERROR"):
            task = tasks.schedule(_boom(), key="space-7")
            with pytest.raises(RuntimeError):
                await task
            await asyncio.sleep(0)
        line = next(r.getMessage() for r in caplog.records if "it broke" in r.getMessage())
        assert "probe-label" in line and "space-7" in line
        assert tasks.in_flight("space-7") == 0

    @pytest.mark.asyncio
    async def test_a_cancelled_task_is_not_logged_as_a_failure(self, caplog):
        tasks = BackgroundTasks("probe")

        async def _work():
            await asyncio.sleep(10)

        with caplog.at_level("ERROR"):
            task = tasks.schedule(_work(), key="k")
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await asyncio.sleep(0)
        assert not [r for r in caplog.records if "task failed" in r.getMessage()]
        assert tasks.in_flight("k") == 0


class TestNoEventLoop:
    def test_scheduling_without_a_loop_skips_rather_than_raising(self):
        # Reached from scripts and tests that call the write methods
        # synchronously; it must not turn into an error there.
        tasks = BackgroundTasks("probe")

        async def _work():
            return None

        assert tasks.schedule(_work(), key="k") is None
        assert tasks.in_flight("k") == 0

    def test_the_skipped_coroutine_is_closed(self):
        # Otherwise Python warns "coroutine was never awaited" at GC time, in an
        # unrelated place, which is its own small debugging tax.
        tasks = BackgroundTasks("probe")

        async def _work():
            return None

        coro = _work()
        assert tasks.schedule(coro, key="k") is None
        with pytest.raises(RuntimeError, match="cannot reuse"):
            asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


class TestCancellationBeforeASpaceIsDropped:
    """Found by running the API suite, not by reasoning about it.

    A scheduled ANALYZE OUTLIVES the space it was scheduled for: the suite deletes
    its ephemeral space while the task is still in flight, and the task then logs a
    wall of `relation "…" does not exist`. `vectorization.auto_sync` hit this first
    and `space_manager.delete_space_with_tables` already cancels its tasks before
    dropping; this is the same requirement for the ANALYZE schedulers.
    """

    @pytest.mark.asyncio
    async def test_cancel_stops_the_tasks_and_waits_for_them(self):
        tasks = BackgroundTasks("probe")
        stopped = []

        running = asyncio.Event()

        async def _work():
            try:
                running.set()
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                stopped.append(True)
                raise

        for _ in range(3):
            tasks.schedule(_work(), key="sp")
        # LET THEM START. `create_task` does not enter the coroutine until the
        # next loop step, and a task cancelled before its first step never runs
        # its body — so cancelling immediately would pass this test while proving
        # nothing about a RUNNING task, which is the only case that matters here.
        await asyncio.wait_for(running.wait(), timeout=1)
        n = await tasks.cancel("sp")

        assert n == 3
        # WAITED, not just signalled — the caller is about to drop the tables
        # these tasks read.
        assert len(stopped) == 3
        assert tasks.in_flight("sp") == 0

    @pytest.mark.asyncio
    async def test_cancelling_an_unknown_key_is_free(self):
        tasks = BackgroundTasks("probe")
        assert await tasks.cancel("never-scheduled") == 0

    @pytest.mark.asyncio
    async def test_a_cancelled_task_is_not_reported_as_a_failure(self, caplog):
        tasks = BackgroundTasks("probe")

        async def _work():
            await asyncio.sleep(10)

        with caplog.at_level("ERROR"):
            tasks.schedule(_work(), key="sp")
            await tasks.cancel("sp")
            await asyncio.sleep(0)
        assert not [r for r in caplog.records if "task failed" in r.getMessage()]

    @pytest.mark.asyncio
    async def test_cancel_all_sweeps_every_registry(self):
        # The property that matters for the next scheduler someone adds: the drop
        # path makes ONE call and does not have to know about it.
        from vitalgraph.utils.background import cancel_all

        a, b = BackgroundTasks("probe-a"), BackgroundTasks("probe-b")

        async def _work():
            await asyncio.sleep(10)

        a.schedule(_work(), key="sp")
        b.schedule(_work(), key="sp")
        b.schedule(_work(), key="other")

        assert await cancel_all("sp") >= 2
        assert a.in_flight("sp") == 0 and b.in_flight("sp") == 0
        assert b.in_flight("other") == 1          # a different key is untouched
        await b.cancel("other")

    @pytest.mark.asyncio
    async def test_the_space_drop_path_calls_it(self):
        # A guard: the registry sweep is worthless if nothing invokes it.
        import inspect

        from vitalgraph.space.space_manager import SpaceManager

        src = inspect.getsource(SpaceManager.delete_space_with_tables)
        assert "cancel_all(space_id)" in src
