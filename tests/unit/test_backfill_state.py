"""Completion markers must never skip a graph that still needs work.

`backfill_state` exists because proving a finished space is finished costs a
full scan — 2,593 ms on the 100k fixture to find 0 missing, every safety-net
cycle forever. The saving is real, and so is the danger: a marker that wrongly
says "complete" leaves entities permanently unstamped, which is the exact
failure the backfill exists to prevent.

So these tests are almost entirely about the SKIP being refused. Every uncertain
input must produce False (scan anyway), because the cost of a needless scan is
seconds and the cost of a needless skip is silent data loss.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from vitalgraph.tasks import backfill_state


class _Conn:
    """Minimal asyncpg-ish connection returning canned rows."""

    def __init__(self, row=None, activity=None, fail=None):
        self._row = row
        self._activity = activity
        self._fail = fail
        self.executed = []

    async def fetchrow(self, sql, *args):
        if self._fail:
            raise self._fail
        if "pg_stat_user_tables" in sql:
            return self._activity
        return self._row

    async def execute(self, sql, *args):
        if self._fail:
            raise self._fail
        self.executed.append((sql, args))
        return "DELETE 1"


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False
        return _Ctx()


RESET = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _marker(inserts=100, reset=RESET, age_s=10.0):
    return {"quad_inserts": inserts, "stats_reset": reset, "age_s": age_s}


def _activity(inserts=100, reset=RESET):
    return {"n_tup_ins": inserts, "stats_reset": reset}


async def test_complete_when_nothing_changed():
    """The one case that may skip: marked done, counter identical."""
    pool = _Pool(_Conn(row=_marker(inserts=100), activity=_activity(inserts=100)))
    assert await backfill_state.is_complete(pool, "sp", "urn:g") is True


async def test_not_complete_when_rows_were_inserted():
    pool = _Pool(_Conn(row=_marker(inserts=100), activity=_activity(inserts=137)))
    assert await backfill_state.is_complete(pool, "sp", "urn:g") is False


async def test_not_complete_when_statistics_were_reset():
    """The case that made the design pair the counter with `stats_reset`.

    A reset can put the counter back to a value it held before, so "unchanged"
    stops meaning "no inserts". Observed for real: `kg_load_test_rdf_quad`
    reports n_tup_ins=0 with 6,550 live rows.
    """
    later = datetime(2026, 8, 12, tzinfo=timezone.utc)
    pool = _Pool(_Conn(row=_marker(inserts=100, reset=RESET),
                       activity=_activity(inserts=100, reset=later)))
    assert await backfill_state.is_complete(pool, "sp", "urn:g") is False, (
        "statistics were reset, so the recorded counter is not comparable — "
        "skipping here can leave a space permanently unstamped")


async def test_not_complete_when_the_marker_is_stale():
    """A marker older than the re-check window is ignored, so a missed
    invalidation self-heals rather than persisting forever."""
    pool = _Pool(_Conn(row=_marker(age_s=backfill_state.DEFAULT_RECHECK_AFTER_S + 1),
                       activity=_activity()))
    assert await backfill_state.is_complete(pool, "sp", "urn:g") is False


async def test_not_complete_when_there_is_no_marker():
    pool = _Pool(_Conn(row=None, activity=_activity()))
    assert await backfill_state.is_complete(pool, "sp", "urn:g") is False


async def test_not_complete_when_the_counter_is_unreadable():
    pool = _Pool(_Conn(row=_marker(), activity=None))
    assert await backfill_state.is_complete(pool, "sp", "urn:g") is False


async def test_not_complete_when_no_counter_was_recorded():
    pool = _Pool(_Conn(row=_marker(inserts=None), activity=_activity()))
    assert await backfill_state.is_complete(pool, "sp", "urn:g") is False


async def test_a_missing_table_degrades_to_scanning():
    """`backfill_state` is created by the explicit schema path, so an older
    install will not have it. That must behave exactly as before markers
    existed — scan — not disable the backfill."""
    pool = _Pool(_Conn(fail=RuntimeError('relation "backfill_state" does not exist')))
    assert await backfill_state.is_complete(pool, "sp", "urn:g") is False


async def test_mark_complete_survives_a_missing_table():
    pool = _Pool(_Conn(fail=RuntimeError("no such table")))
    assert await backfill_state.mark_complete(pool, "sp", "urn:g") is False


async def test_a_decreasing_counter_is_not_treated_as_unchanged():
    """Should not happen without a reset, and is a reason to look, not to skip."""
    pool = _Pool(_Conn(row=_marker(inserts=500), activity=_activity(inserts=12)))
    assert await backfill_state.is_complete(pool, "sp", "urn:g") is False


# ---------------------------------------------------------------------------
# Task integration — the marker is only useful if the task honours it, and only
# SAFE if a nudge overrides it.
# ---------------------------------------------------------------------------

class _FakeTask:
    """The parts of BackfillServerPropertiesTask `_iteration` touches."""

    def __init__(self):
        from vitalgraph.tasks.backfill_server_properties_task import (
            BackfillServerPropertiesTask, BackfillCursor)
        self.task = BackfillServerPropertiesTask.__new__(BackfillServerPropertiesTask)
        self.task.pool = object()
        self.task.batch_size = 200
        self.task._force_full_check = False
        self.task._cursor = BackfillCursor(targets=[("sp", "urn:g")], index=0)

        # `_iteration` re-discovers targets at the start of a cycle, which needs
        # a space manager and a live database. The marker logic under test sits
        # after that, so the discovery is stubbed rather than simulated.
        async def _targets():
            return [("sp", "urn:g")]
        self.task._refresh_targets = _targets


async def test_the_task_skips_a_complete_graph(monkeypatch):
    """The whole point: no scan for a graph already marked done."""
    from vitalgraph.tasks import backfill_server_properties_task as mod

    scanned = []

    async def never(*a, **k):
        scanned.append(a)
        raise AssertionError("scanned a graph that was marked complete")

    monkeypatch.setattr(mod, "backfill_entity_server_properties_sql", never)
    monkeypatch.setattr(mod.backfill_state, "is_complete",
                        lambda *a, **k: _true())

    ft = _FakeTask()
    assert await ft.task._iteration() is False
    assert scanned == []


async def test_a_nudge_forces_the_scan_anyway(monkeypatch):
    """`pg_stat_user_tables` lags commits, so a marker read straight after a
    nudge can still say "unchanged". The nudge must win, or freshly imported
    data stays unstamped until the 24 h re-check."""
    from vitalgraph.tasks import backfill_server_properties_task as mod

    scanned = []

    class _Result:
        entities_patched = 0

    async def scan(*a, **k):
        scanned.append(a)
        return _Result()

    monkeypatch.setattr(mod, "backfill_entity_server_properties_sql", scan)
    monkeypatch.setattr(mod.backfill_state, "is_complete", lambda *a, **k: _true())
    monkeypatch.setattr(mod.backfill_state, "mark_complete", lambda *a, **k: _true())

    ft = _FakeTask()
    ft.task._force_full_check = True          # as nudge() sets it
    await ft.task._iteration()
    assert scanned, "a nudge must override completion markers"


async def test_a_clean_scan_records_the_marker(monkeypatch):
    """Without this the skip never engages and nothing is saved."""
    from vitalgraph.tasks import backfill_server_properties_task as mod

    marked = []

    class _Result:
        entities_patched = 0

    async def scan(*a, **k):
        return _Result()

    async def mark(pool, space_id, graph_uri):
        marked.append((space_id, graph_uri))
        return True

    monkeypatch.setattr(mod, "backfill_entity_server_properties_sql", scan)
    monkeypatch.setattr(mod.backfill_state, "is_complete", lambda *a, **k: _false())
    monkeypatch.setattr(mod.backfill_state, "mark_complete", mark)

    ft = _FakeTask()
    await ft.task._iteration()
    assert marked == [("sp", "urn:g")]


async def test_work_found_does_not_mark_complete(monkeypatch):
    """A batch that patched entities may have more to do — marking here would
    strand the remainder until the re-check window."""
    from vitalgraph.tasks import backfill_server_properties_task as mod

    marked = []

    class _Result:
        entities_patched = 7

    async def scan(*a, **k):
        return _Result()

    async def mark(pool, s, g):
        marked.append((s, g))
        return True

    monkeypatch.setattr(mod, "backfill_entity_server_properties_sql", scan)
    monkeypatch.setattr(mod.backfill_state, "is_complete", lambda *a, **k: _false())
    monkeypatch.setattr(mod.backfill_state, "mark_complete", mark)

    ft = _FakeTask()
    assert await ft.task._iteration() is True
    assert marked == [], "marked complete while it was still patching entities"


async def _true():
    return True


async def _false():
    return False
