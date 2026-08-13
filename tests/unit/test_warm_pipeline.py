"""The pipeline warm-up must be safe to run at startup, and actually run.

`warm_query_pipeline` exists because the first query in a process costs 2,065 ms
against 76 ms warm, dominated by SQL generation (1,190 vs 5 ms) — empty
module-global caches in `generator.py`, function-local imports, and a cold
per-space `rdf_stats`. See the module docstring for the measurements.

What these tests protect is not the speed — that is measured in
`tests/performance` — but the two properties that make it safe to put on the
startup path at all:

* it NEVER raises, whatever a space does. A warm-up that can fail startup is
  worse than no warm-up.
* it actually issues a query per space. A warm-up that silently does nothing
  looks identical to a working one from the outside, and would leave the 27x in
  place while the log claims otherwise.
"""

from __future__ import annotations

import asyncio

import pytest

from vitalgraph.db.sparql_sql.warm_pipeline import (
    warm_query_pipeline, warm_space)


class _Backend:
    def __init__(self, fail=None, hang=False):
        self.queries = []
        self._fail = fail
        self._hang = hang

    async def execute_sparql_query(self, space_id, sparql, **kw):
        self.queries.append((space_id, sparql))
        if self._hang:
            await asyncio.sleep(60)
        if self._fail:
            raise self._fail
        return {"results": {"bindings": []}}


class _Record:
    def __init__(self, backend, graph_uri=None):
        self.graph_uri = graph_uri
        self.space_impl = self          # stand in for both
        self._backend = backend

    def get_db_space_impl(self):
        return self._backend


class _Manager:
    def __init__(self, records):
        self._records = records

    def get_active_space_ids(self):
        return list(self._records)

    async def get_space_or_load(self, space_id):
        return self._records.get(space_id)


async def test_it_queries_every_space():
    backends = {s: _Backend() for s in ("a", "b", "c")}
    mgr = _Manager({s: _Record(b) for s, b in backends.items()})

    summary = await warm_query_pipeline(mgr)

    assert summary["warmed"] == 3, summary
    for space_id, b in backends.items():
        assert len(b.queries) == 1, (
            f"space {space_id} was not warmed — a warm-up that issues no query "
            f"leaves the 27x first-query cost in place while appearing to work")
        assert "SELECT" in b.queries[0][1]


async def test_a_failing_space_does_not_stop_the_others():
    """One bad space must not abort the sweep, or a single broken space
    silently costs every OTHER space its warm-up."""
    good1, good2 = _Backend(), _Backend()
    mgr = _Manager({"bad": _Record(_Backend(fail=RuntimeError("boom"))),
                    "good1": _Record(good1), "good2": _Record(good2)})

    summary = await warm_query_pipeline(mgr)

    assert summary["skipped"] == 1
    assert summary["warmed"] == 2
    assert good1.queries and good2.queries


async def test_a_hanging_space_is_bounded():
    """A space that never answers must time out, not hang startup forever.

    Backgrounded or not, an unbounded await here would keep the task alive for
    the life of the process and hold a connection.
    """
    from vitalgraph.db.sparql_sql import warm_pipeline as wp
    original = wp._PER_SPACE_TIMEOUT_S
    wp._PER_SPACE_TIMEOUT_S = 0.05
    try:
        ms = await warm_space(_Backend(hang=True), "slow", "urn:g")
        assert ms is None, "a hanging space should report no timing, not block"
    finally:
        wp._PER_SPACE_TIMEOUT_S = original


async def test_it_survives_a_manager_that_cannot_enumerate():
    class Broken:
        def get_active_space_ids(self):
            raise RuntimeError("no database")

    summary = await warm_query_pipeline(Broken())
    assert summary["warmed"] == 0        # returned a summary rather than raising


async def test_max_spaces_caps_the_sweep():
    """The first space carries the process-global cost; later ones only their
    own statistics. Capping is the trade on an instance with many spaces."""
    backends = {s: _Backend() for s in ("a", "b", "c", "d")}
    mgr = _Manager({s: _Record(b) for s, b in backends.items()})

    summary = await warm_query_pipeline(mgr, max_spaces=2)

    assert summary["warmed"] == 2
    assert sum(1 for b in backends.values() if b.queries) == 2


async def test_the_space_graph_uri_is_used_when_known():
    b = _Backend()
    mgr = _Manager({"s1": _Record(b, graph_uri="urn:custom:graph")})
    await warm_query_pipeline(mgr)
    assert "urn:custom:graph" in b.queries[0][1]


async def test_the_toggle_actually_disables_it(monkeypatch):
    """`VITALGRAPH_WARM_QUERY_PIPELINE=0` must issue no queries at all.

    This runs on the startup path against every space, so an operator
    diagnosing a slow start has to be able to remove it from the picture
    without a code change — and a toggle that is read but not honoured is
    worse than none.
    """
    monkeypatch.setenv("VITALGRAPH_WARM_QUERY_PIPELINE", "0")
    b = _Backend()
    summary = await warm_query_pipeline(_Manager({"s": _Record(b)}))

    assert summary["warmed"] == 0
    assert b.queries == [], "the toggle was ignored and a query was still sent"


async def test_max_spaces_from_the_environment(monkeypatch):
    monkeypatch.setenv("VITALGRAPH_WARM_MAX_SPACES", "1")
    backends = {s: _Backend() for s in ("a", "b", "c")}
    summary = await warm_query_pipeline(
        _Manager({s: _Record(x) for s, x in backends.items()}))
    assert summary["warmed"] == 1


async def test_a_bad_max_spaces_value_does_not_crash_startup(monkeypatch):
    monkeypatch.setenv("VITALGRAPH_WARM_MAX_SPACES", "not-a-number")
    b = _Backend()
    summary = await warm_query_pipeline(_Manager({"s": _Record(b)}))
    assert summary["warmed"] == 1        # falls back to "all", does not raise
