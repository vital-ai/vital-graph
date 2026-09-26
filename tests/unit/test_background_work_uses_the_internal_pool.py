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


def test_it_falls_back_to_the_request_pool_when_there_is_no_internal_one():
    """Degrade to the status quo, never raise.

    An impl that predates the split, or one caught mid-initialisation, still
    has to be able to ANALYZE. Running maintenance on the wrong pool is what
    every version before this did; refusing to run it is a new failure.
    """
    req = _Pool("request")
    assert _impl(req, None)._internal_pool is req


def test_an_unconnected_impl_still_raises():
    """The fallback must not paper over "not connected at all" — that is a
    programming error and has to stay loud."""
    obj = object.__new__(SparqlSQLDbImpl)
    obj.connection_pool = None
    obj.internal_pool = None
    with pytest.raises(RuntimeError, match="not connected"):
        obj._internal_pool


def test_the_analyze_sites_in_the_write_path_are_routed():
    """THE OUTAGE PATH, pinned as source.

    `add_rdf_quads_batch_bulk`, `remove_rdf_quads_batch_bulk` and
    `delete_entity_graph_bulk` each end by acquiring a connection to ANALYZE.
    All three acquired from `_db._pool` — the request pool — which is how a
    bulk copy's maintenance came to hold the connections readers needed.

    Asserted against the SOURCE rather than by executing the bulk paths: those
    require a live space, a populated schema and a real transaction, and a test
    that heavy would be run rarely enough to regress unnoticed. The property
    here is narrow and textual, so pin it narrowly and textually.
    """
    import inspect
    from vitalgraph.db.sparql_sql import sparql_sql_space_impl

    src = inspect.getsource(sparql_sql_space_impl)
    routed = src.count("self._db._internal_pool.acquire() as conn:\n"
                       "                await maybe_analyze(")
    assert routed == 3, f"expected 3 routed ANALYZE sites, found {routed}"

    # And none left behind on the request pool. Checked as the same two-line
    # shape, because a single stale site is the whole defect — two routed and
    # one missed leaks maintenance onto readers exactly as before, while
    # looking fixed.
    stale = src.count("self._db._pool.acquire() as conn:\n"
                      "                await maybe_analyze(")
    assert stale == 0, f"{stale} ANALYZE site(s) still on the request pool"
