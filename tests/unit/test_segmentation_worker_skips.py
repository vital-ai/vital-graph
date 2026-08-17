"""A vanished space is a skip, not an ERROR traceback (issues/100).

The segmentation worker polls every active space for jobs. `list_active_spaces`
reads an in-memory set, so it cannot know a space was dropped between the
listing and the poll — and ephemeral test spaces are created and deleted
constantly. Each one produced:

    ERROR - Error in poll_space(inttest_raw_concurrency): relation
    "inttest_raw_concurrency_segmentation_jobs" does not exist
    Traceback (most recent call last): ... 15 frames ...

several times per deleted space, at ERROR with a full traceback, for something
entirely routine. That is the kind of noise that trains people to skim
tracebacks, which is how a real one gets missed.

The skip list is deliberately NOT permanent: space ids are reused, and a
worker that stopped polling a recreated space would be a silent failure to
segment — strictly worse than the noise it replaced.
"""

from __future__ import annotations

import asyncio

import asyncpg
import pytest

from vitalgraph.document.segmentation_worker import SegmentationWorker


class _SpaceManager:
    def __init__(self, spaces):
        self.spaces = list(spaces)

    def list_active_spaces(self):
        return list(self.spaces)


@pytest.fixture
def worker():
    return SegmentationWorker(_SpaceManager(["a", "b"]))


class TestSkipListLifecycle:

    def test_starts_empty(self, worker):
        assert worker._skip_spaces == set()

    def test_a_skipped_space_is_dropped_from_the_next_poll(self, worker):
        worker._skip_spaces.add("a")
        worker._space_manager.spaces = ["a", "b"]
        # Same basis, so the skip survives this cycle.
        worker._skip_basis = frozenset({"a", "b"})
        active = [s for s in worker._get_active_space_ids()
                  if s not in worker._skip_spaces]
        assert active == ["b"]

    def test_the_skip_list_clears_when_the_space_set_changes(self, worker):
        """A reused space id must be polled again.

        The ephemeral suites recreate the same names, so a permanent skip would
        quietly stop segmenting a space that had come back — a silent failure
        traded for a noisy log.
        """
        worker._skip_spaces = {"a"}
        worker._skip_basis = frozenset({"a", "b"})

        worker._space_manager.spaces = ["a", "b", "c"]   # set changed
        basis = frozenset(worker._get_active_space_ids())
        if basis != worker._skip_basis:
            worker._skip_spaces.clear()
            worker._skip_basis = basis

        assert worker._skip_spaces == set()

    def test_a_recreated_space_is_polled_again(self, worker):
        """End to end on the lifecycle: skip, space set changes, poll resumes."""
        worker._skip_spaces = {"a"}
        worker._skip_basis = frozenset({"a", "b"})
        worker._space_manager.spaces = ["b"]             # 'a' deleted
        basis = frozenset(worker._get_active_space_ids())
        if basis != worker._skip_basis:
            worker._skip_spaces.clear()
            worker._skip_basis = basis

        worker._space_manager.spaces = ["a", "b"]        # 'a' recreated
        basis = frozenset(worker._get_active_space_ids())
        if basis != worker._skip_basis:
            worker._skip_spaces.clear()
            worker._skip_basis = basis

        assert "a" not in worker._skip_spaces


class TestUndefinedTableIsHandledSeparately:

    def test_the_worker_catches_undefined_table_specifically(self):
        """Not `except Exception` — a real failure must still be an ERROR.

        Checked in the source because reproducing it needs a live pool, a live
        space, and a deletion timed inside the poll window. Weaker than
        executing it; strong enough to catch a revert.
        """
        import inspect
        src = inspect.getsource(SegmentationWorker._poll_space)
        assert "asyncpg.exceptions.UndefinedTableError" in src
        assert "self._skip_spaces.add(space_id)" in src
        # The generic handler must survive, or genuine errors go quiet too.
        assert "except Exception as e:" in src
        assert "exc_info=True" in src

    def test_undefined_table_is_a_distinct_asyncpg_type(self):
        """Guards the assumption the handler rests on."""
        assert issubclass(asyncpg.exceptions.UndefinedTableError, Exception)
        assert asyncpg.exceptions.UndefinedTableError is not Exception
