"""Background jobs acquire from INTERNAL, never from the request pool.

`issues/231`, step 1. Separate pools are worth nothing if the background work
still acquires from the request pool — the separation would be cosmetic, and
the failure mode of a cosmetic separation is WORSE than none, because the
architecture diagram says the readers are protected and they are not.

This is the routing half. `tests/load/test_query_is_not_starved_by_internal.py`
is the behavioural half: it saturates INTERNAL for real and measures that QUERY
keeps serving. Neither is sufficient alone — routing can be correct while the
pools share a limit, and the pools can be isolated while nothing is routed at
them.

WHAT THIS PINS, and why each one is a live risk rather than a hypothetical:

  * the three `maybe_analyze` sites in the bulk write/delete paths. These are
    the EXACT statements that stacked six deep on 2026-09-24 and stopped
    production answering.
  * the fallback. A test double or a half-initialised impl has no
    `internal_pool`; that must degrade to today's behaviour, not raise, because
    raising here would take down the write path to protect a read path.
"""

import pytest

from vitalgraph.db.sparql_sql.sparql_sql_db_impl import SparqlSQLDbImpl


class _Pool:
    def __init__(self, name):
        self.name = name


def _impl(request_pool, internal_pool):
    """A bare impl with the two pools set directly — `connect()` is what
    normally creates them and it needs a live server."""
    obj = object.__new__(SparqlSQLDbImpl)
    obj.connection_pool = request_pool
    obj.internal_pool = internal_pool
    return obj


def test_background_work_gets_the_internal_pool():
    req, internal = _Pool("request"), _Pool("internal")
    assert _impl(req, internal)._internal_pool is internal


def test_disabled_on_purpose_returns_the_request_pool_QUIETLY(caplog):
    """`internal_pool_size=0` means the operator chose the pre-split behaviour.

    That choice is already logged at WARNING when the pool is not created, so
    this path must not log again on every background job.
    """
    import logging
    req = _Pool("request")
    obj = _impl(req, None)
    obj.internal_pool_disabled = True
    with caplog.at_level(logging.ERROR):
        assert obj._internal_pool is req
    assert "NOT disabled" not in caplog.text


def test_missing_by_accident_is_reported_at_ERROR(caplog):
    """THE DISTINCTION THAT MAKES THE FALLBACK SAFE.

    `getattr(x, 'internal_pool', None) or pool` treated "disabled by the
    operator" and "missing because something went wrong" identically, and
    silently. The second case puts ANALYZE, VACUUM and auto-sync back on the
    connections readers need — the 2026-09-24 outage configuration — and nothing
    distinguished it from a working bulkhead.

    It still returns the request pool rather than raising: a connect() path that
    raised here would take down the write path to protect the read path.
    """
    import logging
    from vitalgraph.db import pool as poolmod
    poolmod._internal_fallback_reported = False      # one report per process

    req = _Pool("request")
    obj = _impl(req, None)                            # not disabled, just absent
    with caplog.at_level(logging.ERROR):
        assert obj._internal_pool is req
    assert "NOT disabled" in caplog.text
    assert "2026-09-24" in caplog.text, "the record must name what this causes"


def test_the_accident_is_reported_once_not_per_acquire(caplog):
    """A misconfiguration repeated on every background job buries the log."""
    import logging
    from vitalgraph.db import pool as poolmod
    poolmod._internal_fallback_reported = False

    obj = _impl(_Pool("request"), None)
    with caplog.at_level(logging.ERROR):
        for _ in range(5):
            obj._internal_pool
    assert caplog.text.count("NOT disabled") == 1


def test_an_unconnected_impl_still_raises():
    """The fallback must not paper over "not connected at all" — that is a
    programming error and has to stay loud."""
    obj = object.__new__(SparqlSQLDbImpl)
    obj.connection_pool = None
    obj.internal_pool = None
    with pytest.raises(RuntimeError, match="not connected"):
        obj._internal_pool


def test_the_analyze_sites_in_the_write_path_are_routed():
    """THE OUTAGE PATH. The property is unchanged; WHERE it lives moved.

    `add_rdf_quads_batch_bulk`, `remove_rdf_quads_batch_bulk` and
    `delete_entity_graph_bulk` each end by triggering an ANALYZE. All three once
    acquired from `_db._pool` — the request pool — which is how a bulk copy's
    maintenance came to hold the connections readers needed (`issues/231`).

    They no longer acquire anything inline: `issues/253` found that AWAITING the
    ANALYZE there held the caller's write transaction open across a 60-98 s
    statement, and PostgreSQL terminated the connection as idle-in-transaction —
    five confirmed lost writes in a day. The three sites now call
    `schedule_maybe_analyze`, which chooses the pool itself.

    So the pool choice is asserted where it now happens, and the earlier
    two-line textual shape is gone because the code it described is gone. The
    requirement it protected is not: ANALYZE must not be taken on the request
    pool by default.
    """
    import ast
    import inspect

    from vitalgraph.db.sparql_sql import auto_analyze, sparql_sql_space_impl

    src = inspect.getsource(sparql_sql_space_impl)
    scheduled = src.count("schedule_maybe_analyze(self._db")
    assert scheduled == 3, f"expected 3 scheduled ANALYZE sites, found {scheduled}"

    # The scheduler picks the pool through the sanctioned accessor, which returns
    # the INTERNAL pool and falls back to the request pool only when an operator
    # has deliberately disabled the split (`internal_pool_for`'s own contract).
    sched = inspect.getsource(auto_analyze.schedule_maybe_analyze)
    assert "internal_pool_for(" in sched
    # Not reaching past it to the request pool.
    tree = ast.parse(inspect.getsource(auto_analyze))
    direct = [n.lineno for n in ast.walk(tree)
              if isinstance(n, ast.Attribute) and n.attr == "connection_pool"]
    assert not direct, f"auto_analyze reaches for the request pool at {direct}"


# --------------------------------------------------------------------------
# The scheduled jobs (`issues/231` step 1, completed 2026-09-26)
# --------------------------------------------------------------------------

def test_the_scheduled_background_jobs_are_routed():
    """SIX consumers were constructed with the REQUEST pool.

    `MaintenanceJob` is the ANALYZE/VACUUM path that exhausted the request pool
    on 2026-09-24, and it was handed `connection_pool` directly — so the pool
    split existed while the single largest INTERNAL workload still ran on the
    connections readers needed. That is the "cosmetic separation" this issue
    warns about, in the one place it mattered most.

    Pinned against source because constructing these requires a live pool, a
    scheduler and a process table; the property under test is which pool each
    receives, which is textual.
    """
    # READ the module, do not IMPORT it. Importing `vitalgraphapp_impl` pulls in
    # `starlette.middleware.sessions`, which needs `itsdangerous` — a `server`
    # extra that the unit-test environment installs deliberately WITHOUT (see the
    # note on the `dev` extra in `pyproject.toml`, which names this exact package
    # as incidental). The property under test is textual, so the text is all this
    # needs; importing for `inspect.getsource` made a source assertion depend on
    # the whole server's dependency tree and failed CI.
    from pathlib import Path as _Path
    src = (_Path(__file__).resolve().parents[2]
           / "vitalgraph" / "impl" / "vitalgraphapp_impl.py").read_text()

    # The INTERNAL handle must come from the shared helper, which is what makes
    # "disabled on purpose" distinguishable from "missing by accident". A bare
    # `getattr(..., 'internal_pool', None) or pool` here would silently put the
    # scheduled jobs back on request connections.
    assert "internal_pool_for(self.db_impl)" in src, (
        "the scheduled jobs do not resolve their pool through internal_pool_for")
    assert "getattr(self.db_impl, 'internal_pool', None) or pool" not in src, (
        "a bare `or` fallback is back; that hides a missing bulkhead")

    for ctor in ("ProcessTracker(bg_pool)",
                 "MaintenanceJob(bg_pool",
                 "ProcessScheduler(bg_pool",
                 "AnalyticsJob(bg_pool)",
                 "PostgresMetricsCollector(bg_pool)",
                 "MetricsRollupJob(bg_pool)"):
        assert ctor in src, f"{ctor} is not routed at the internal pool"

    # And none left on the request pool. Checked per-constructor rather than by
    # counting, because two routed and one missed still leaks the heaviest
    # background job onto readers while looking fixed.
    for stale in ("ProcessTracker(pool)",
                  "MaintenanceJob(pool,",
                  "ProcessScheduler(pool,",
                  "AnalyticsJob(pool)",
                  "PostgresMetricsCollector(pool)",
                  "MetricsRollupJob(pool)"):
        assert stale not in src, f"{stale} still takes a request connection"


def test_segmentation_polling_prefers_the_internal_pool():
    """`issues/231` names segmentation explicitly. Its `_get_pool` walks four
    fallback tiers to find a pool, and every tier returned the request one."""
    import inspect
    from vitalgraph.document import segmentation_worker

    src = inspect.getsource(segmentation_worker.SegmentationWorker._get_pool)
    assert "internal_pool_for" in src, (
        "segmentation polling still takes whatever pool it finds first")
    # It must NOT reach past the helper to grab a request pool itself — that is
    # the four-tier walk this replaced, and it returned the request pool at
    # every tier.
    assert "connection_pool" not in src, (
        "segmentation is still able to select a request pool directly")
