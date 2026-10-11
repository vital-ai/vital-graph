"""A burst of nudges costs one forced backfill cycle per window, for the space written.

`issues/266`. Every SPARQL insert/update nudges the backfill task, and a nudge
bypassed both of `237`'s gates — the discovery cache and the completion markers
— for EVERY space until a full cycle completed. Under a burst that meant one
full, unmarked cycle per write: on production 2026-10-03, 1,639 forced cycles
and 2,516 s in four hours, during a SPARQL-update repair.

The force itself is necessary (`pg_stat_user_tables` lags commits, so a marker
read straight after a write can say "unchanged"), so these tests pin that it is
still honoured — once per window, never dropped — as firmly as they pin the
saving.
"""

from __future__ import annotations

import pytest

from vitalgraph.tasks import backfill_server_properties_task as B
from vitalgraph.tasks.backfill_server_properties_task import (
    BackfillServerPropertiesTask)

pytestmark = [pytest.mark.unit]


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(B.time, "monotonic", lambda: now[0])
    return now


@pytest.fixture
def task(clock):
    t = BackfillServerPropertiesTask(pool=object(), space_manager=None)
    t._begin_cycle()            # consume the startup force-all
    clock[0] += t.nudge_min_interval_s
    t._begin_cycle()            # a plain steady-state cycle
    assert not t._force_pending()
    return t


def test_a_nudge_forces_only_the_space_written(task):
    task.nudge("sp_a")
    task._begin_cycle()
    assert task._forced("sp_a")
    assert not task._forced("sp_b"), (
        "a write to one space must not bypass every other space's gates")


def test_a_nudge_without_a_space_forces_every_space(task):
    task.nudge()
    task._begin_cycle()
    assert task._forced("sp_a") and task._forced("sp_b")


def test_a_burst_is_one_forced_cycle_per_window_not_one_per_write(task, clock):
    """Production's burst: a nudge every 3.4 s. Replayed over ten minutes with a
    cycle starting after every nudge, as the idle loop did."""
    forced = 0
    for _ in range(int(600 / 3.4)):
        task.nudge("sp")
        task._begin_cycle()
        forced += task._forced("sp")
        clock[0] += 3.4
    windows = 600 / task.nudge_min_interval_s
    assert forced <= windows + 1, (
        f"{forced} forced cycles for {int(600 / 3.4)} nudges; coalescing should "
        f"give about one per {task.nudge_min_interval_s:.0f} s window")
    assert forced >= windows - 1, "the force must still be honoured each window"


def test_a_nudge_inside_the_window_is_held_not_dropped(task, clock):
    task.nudge("sp")
    task._begin_cycle()                       # forced
    clock[0] += 5
    task.nudge("sp")                          # inside the window
    task._begin_cycle()
    assert not task._forced("sp")
    assert task._force_pending(), "the held nudge must still be pending"
    assert 0 < task._force_delay() <= task.nudge_min_interval_s

    clock[0] += task._force_delay()
    task._begin_cycle()
    assert task._forced("sp"), "the held nudge must be honoured when the window ends"


def test_a_nudge_during_a_cycle_survives_that_cycle(task, clock):
    """The single flag was cleared at the END of every cycle, so a write that
    landed mid-cycle lost its force — contrary to the comment beside it."""
    task.nudge("sp")
    task._begin_cycle()                       # cycle 1 forced, now running
    task.nudge("sp_late")                     # arrives mid-cycle
    clock[0] += task.nudge_min_interval_s
    task._begin_cycle()                       # cycle 2
    assert task._forced("sp_late")


def test_a_notify_payload_scopes_the_nudge(task):
    task._on_notify(None, 0, B.BACKFILL_NUDGE_CHANNEL, "sp_cli")
    task._begin_cycle()
    assert task._forced("sp_cli") and not task._forced("sp_other")


def test_an_empty_notify_still_forces_everything(task):
    """Out-of-process callers that predate scoping send no payload."""
    task._on_notify(None, 0, B.BACKFILL_NUDGE_CHANNEL, "")
    task._begin_cycle()
    assert task._forced("anything")


def test_startup_forces_every_space(clock):
    t = BackfillServerPropertiesTask(pool=object(), space_manager=None)
    t._begin_cycle()
    assert t._forced("any_space"), (
        "the first cycle after a restart must not trust markers from before it")


def test_the_endpoints_pass_the_space():
    import inspect
    from vitalgraph.endpoint import sparql_insert_endpoint, sparql_update_endpoint
    for mod in (sparql_insert_endpoint, sparql_update_endpoint):
        src = inspect.getsource(mod)
        assert "nudge_backfill(space_id)" in src, (
            f"{mod.__name__} nudges without naming the space, so every write "
            f"forces every space (issues/266)")
