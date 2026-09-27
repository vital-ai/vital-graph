"""Graph discovery re-derives only when quads changed — issue 237.

`_refresh_targets` ran `discover_graphs_sql` — a `SELECT DISTINCT` over the
space's quad table joined to `term` — for every space at the top of every cycle.
Only afterwards did `_iteration` consult `backfill_state.is_complete`, the cheap
per-graph marker whose own comment prices what it saves. So a space where every
graph was already complete paid full discovery forever, and it was
self-reinforcing: a cycle in which every target is skipped completes almost
instantly, so the faster the gate worked the sooner the scan ran again.

Measured on production: 45,336 calls, 754M buffers, 35.0 hours — against a space
whose quad write watermark is zero.

WHAT THESE TESTS ARE REALLY FOR
-------------------------------
A cache in front of a discovery step is easy to write and easy to get wrong in
one direction only: too much skipping means entities that are never stamped, and
nothing reports it. So the three escape hatches are pinned harder than the
saving is — a nudge, an expiry, and any failure to read the signal all
re-derive. `backfill_state`'s docstring calls this defence in depth for the same
reason, and this is the same shape one level up.
"""

from __future__ import annotations

import pytest

from vitalgraph.tasks import backfill_server_properties_task as B
from vitalgraph.tasks.backfill_server_properties_task import (
    BackfillServerPropertiesTask)

pytestmark = [pytest.mark.unit]


@pytest.fixture
def task(monkeypatch):
    """A task whose discovery and activity signal are both counted."""
    t = BackfillServerPropertiesTask(pool=object(), space_manager=None)
    t._force_full_check = False          # the steady state, not the first cycle
    t.calls = {"discover": 0, "activity": 0}
    t.graphs = ["urn:g1", "urn:g2"]
    t.activity = (100, "reset-1")

    async def _discover(pool, space_id):
        t.calls["discover"] += 1
        return list(t.graphs)

    async def _activity(pool, space_id):
        t.calls["activity"] += 1
        return t.activity

    monkeypatch.setattr(B, "discover_graphs_sql", _discover)
    monkeypatch.setattr(B.backfill_state, "quad_activity", _activity)
    return t


class TestItStopsRescanningAnUnchangedSpace:

    async def test_the_second_cycle_does_not_rediscover(self, task):
        assert await task._discover_graphs_cached("sp") == ["urn:g1", "urn:g2"]
        assert await task._discover_graphs_cached("sp") == ["urn:g1", "urn:g2"]
        assert task.calls["discover"] == 1

    async def test_many_cycles_still_only_one_scan(self, task):
        for _ in range(20):
            await task._discover_graphs_cached("sp")
        assert task.calls["discover"] == 1

    async def test_spaces_do_not_share_a_cache_entry(self, task):
        await task._discover_graphs_cached("a")
        await task._discover_graphs_cached("b")
        assert task.calls["discover"] == 2
        await task._discover_graphs_cached("a")
        assert task.calls["discover"] == 2


class TestEveryWayItMustReDerive:
    """Skipping too much strands entities unstamped, and nothing reports it."""

    async def test_an_insert_reopens_it(self, task):
        await task._discover_graphs_cached("sp")
        task.activity = (101, "reset-1")
        task.graphs = ["urn:g1", "urn:g2", "urn:g3"]
        assert await task._discover_graphs_cached("sp") == \
            ["urn:g1", "urn:g2", "urn:g3"]
        assert task.calls["discover"] == 2

    async def test_a_stats_reset_reopens_it(self, task):
        """The case `backfill_state` documents: reset to 0 and re-insert back to
        the same value looks untouched. Comparing `stats_reset` too makes that
        exact rather than inferred."""
        await task._discover_graphs_cached("sp")
        task.activity = (100, "reset-2")
        assert await task._discover_graphs_cached("sp")
        assert task.calls["discover"] == 2

    async def test_a_nudge_ignores_the_cache(self, task):
        await task._discover_graphs_cached("sp")
        task.nudge()
        await task._discover_graphs_cached("sp")
        assert task.calls["discover"] == 2

    async def test_the_cache_expires(self, task, monkeypatch):
        await task._discover_graphs_cached("sp")
        clock = [B.time.monotonic() + task.discovery_recheck_s + 1]
        monkeypatch.setattr(B.time, "monotonic", lambda: clock[0])
        await task._discover_graphs_cached("sp")
        assert task.calls["discover"] == 2

    async def test_an_unreadable_signal_re_derives(self, task, monkeypatch):
        await task._discover_graphs_cached("sp")

        async def _boom(pool, space_id):
            raise RuntimeError("no pg_stat_user_tables")
        monkeypatch.setattr(B.backfill_state, "quad_activity", _boom)
        assert await task._discover_graphs_cached("sp") == ["urn:g1", "urn:g2"]
        assert task.calls["discover"] == 2

    async def test_a_null_counter_is_never_cached(self, task):
        """`n_tup_ins` is NULL for a table the stats view has not seen. Caching
        against NULL would make 'unknown' compare equal to 'unknown' forever."""
        task.activity = (None, None)
        await task._discover_graphs_cached("sp")
        await task._discover_graphs_cached("sp")
        assert task.calls["discover"] == 2
        assert "sp" not in task._discovery_cache


class TestTheSignalIsReadBeforeTheScan:

    async def test_an_insert_during_discovery_is_not_swallowed(self, task, monkeypatch):
        """Reading the counter AFTER the scan would record a write that landed
        mid-scan as already covered, and it would never be re-derived."""
        async def _discover(pool, space_id):
            task.calls["discover"] += 1
            task.activity = (200, "reset-1")   # a write lands mid-scan
            return list(task.graphs)
        monkeypatch.setattr(B, "discover_graphs_sql", _discover)

        await task._discover_graphs_cached("sp")
        assert task._discovery_cache["sp"][1] == 100, "cached the post-scan value"

        # so the next cycle sees 200 != 100 and re-derives
        await task._discover_graphs_cached("sp")
        assert task.calls["discover"] == 2


class TestTheOldBehaviourIsGone:

    async def test_refresh_targets_no_longer_calls_discovery_directly(self):
        """The defect was the CALL SITE, so pin the call site.

        `_refresh_targets` must go through the cache; calling
        `discover_graphs_sql` from it again reintroduces the scan-per-cycle
        whatever the cache does.
        """
        import inspect
        src = inspect.getsource(
            BackfillServerPropertiesTask._refresh_targets)
        assert "discover_graphs_sql(" not in src, src
        assert "_discover_graphs_cached(" in src
