"""One request for the dashboard, instead of one per space.

`Home.tsx` rendered four numbers by calling `list_graphs` once per space. With
67 spaces that is 67 concurrent multi-second counts — the ~20 s dashboard load
reported from the UI. Caching each call fixed the WARM path (4,831 ms -> 5 ms)
and left the shape wrong: the work still grew with the number of spaces, and a
cold cache after a deploy meant 67 concurrent counts again.

`_spaces_summary` answers the whole thing in a handful of queries — measured at
40 ms for 67 spaces in-process, 86 ms over HTTP — using two grouped lookups and
no quad scan at all.

These tests cover what would be silently wrong rather than merely slow:

* a space the caller cannot read must not appear, or the dashboard leaks the
  existence and size of other tenants' data;
* `reltuples = -1` (never analysed) must not surface as a negative triple count;
* the totals must equal the rows, or the header and the table disagree.
"""

from __future__ import annotations

import logging

import pytest

from vitalgraph.model.result_status import OperationStatus


def _endpoint(space_rows, graph_rows, est_rows, allow=None):
    """An endpoint wired to canned query results.

    `allow` is the set of spaces the caller may read; None means all.
    """
    from vitalgraph.endpoint.sparql_graph_endpoint import SPARQLGraphEndpoint
    import vitalgraph.endpoint.sparql_graph_endpoint as mod

    class _DB:
        async def execute_query(self, sql, args):
            if "FROM space" in sql:
                return space_rows
            if "FROM graph" in sql:
                return graph_rows
            if "pg_class" in sql:
                return est_rows
            return []

    ep = SPARQLGraphEndpoint.__new__(SPARQLGraphEndpoint)
    ep.logger = logging.getLogger(__name__)

    class _SM:
        db_impl = _DB()
    ep.space_manager = _SM()
    ep.db_impl = _DB()

    if allow is not None:
        def _require(user, space_id):
            if space_id not in allow:
                raise PermissionError("no")
        mod.require_space_read = _require
    else:
        mod.require_space_read = lambda user, space_id: None
    return ep


SPACES = [{"space_id": "a", "space_name": "Alpha"},
          {"space_id": "b", "space_name": "Beta"}]
GRAPHS = [{"space_id": "a", "n": 2}, {"space_id": "b", "n": 1}]
EST = [{"relname": "a_rdf_quad", "est": 1_000},
       {"relname": "b_rdf_quad", "est": 2_000}]


async def test_it_returns_every_space_with_totals():
    ep = _endpoint(SPACES, GRAPHS, EST)
    r = await ep._spaces_summary({"username": "u"})

    assert r.status is OperationStatus.FOUND
    assert r.total_spaces == 2
    assert r.total_graphs == 3
    assert r.total_triples == 3_000
    assert {s.space for s in r.spaces} == {"a", "b"}
    assert all(s.estimated for s in r.spaces), (
        "triple_count comes from reltuples, so `estimated` must say so — a "
        "caller comparing an estimate for equality needs to know")


async def test_the_totals_equal_the_rows():
    """The header and the table are rendered from the same response; if they
    disagree the page contradicts itself."""
    ep = _endpoint(SPACES, GRAPHS, EST)
    r = await ep._spaces_summary({"username": "u"})
    assert r.total_graphs == sum(s.graph_count for s in r.spaces)
    assert r.total_triples == sum(s.triple_count for s in r.spaces)
    assert r.total_spaces == len(r.spaces)


async def test_a_space_the_user_cannot_read_is_omitted():
    """Not merely a permissions nicety: the dashboard would otherwise disclose
    the existence and SIZE of another tenant's data."""
    ep = _endpoint(SPACES, GRAPHS, EST, allow={"a"})
    r = await ep._spaces_summary({"username": "u"})

    assert [s.space for s in r.spaces] == ["a"]
    assert r.total_spaces == 1
    assert r.total_triples == 1_000, (
        "totals must cover only the visible spaces, or the number leaks what "
        "the list withholds")


async def test_a_never_analyzed_table_reports_zero_not_minus_one():
    """PostgreSQL 14+ stores -1 for "never analysed". Rendering that would show
    a space with minus one triple."""
    ep = _endpoint(SPACES, GRAPHS,
                   [{"relname": "a_rdf_quad", "est": -1},
                    {"relname": "b_rdf_quad", "est": 2_000}])
    r = await ep._spaces_summary({"username": "u"})
    a = next(s for s in r.spaces if s.space == "a")
    assert a.triple_count == 0
    assert r.total_triples == 2_000


async def test_a_space_with_no_graphs_and_no_estimate_is_still_listed():
    """A newly created space has no graph rows and no statistics. It must still
    appear — showing zero is right, omitting it looks like the space is gone."""
    ep = _endpoint(SPACES + [{"space_id": "c", "space_name": "Gamma"}],
                   GRAPHS, EST)
    r = await ep._spaces_summary({"username": "u"})
    c = next(s for s in r.spaces if s.space == "c")
    assert c.graph_count == 0 and c.triple_count == 0
    assert r.total_spaces == 3


async def test_no_visible_spaces_is_empty_not_found():
    """`FOUND` is defined as "returned >= 1"; nothing visible is `EMPTY`."""
    ep = _endpoint(SPACES, GRAPHS, EST, allow=set())
    r = await ep._spaces_summary({"username": "u"})
    assert r.status is OperationStatus.EMPTY
    assert r.spaces == []
    assert r.total_spaces == 0


# ---------------------------------------------------------------------------
# _get_graph_counts. This had no unit test, and shipped a 500: its count-cache
# import used `...` (correct under vitalgraph/db/sparql_sql/) inside
# vitalgraph/endpoint/, where `..` is right. Being function-local, it failed
# only when a user loaded the page — "attempted relative import beyond
# top-level package".
# ---------------------------------------------------------------------------

async def test_graph_counts_runs_and_caches():
    """Exercises the real method, so a bad import cannot pass unnoticed."""
    from vitalgraph.endpoint.sparql_graph_endpoint import SPARQLGraphEndpoint
    from vitalgraph.cache.count_cache import _count_cache

    ENTITY = next(iter(SPARQLGraphEndpoint._ENTITY_TYPES))

    class _Conn:
        def __init__(self):
            self.count_queries = 0

        async def fetchval(self, sql, *args):
            return "uuid-value"

        async def fetch(self, sql, *args):
            self.count_queries += 1
            return [{"type_uri": ENTITY, "cnt": 7}]

    conn = _Conn()

    class _Pool:
        def acquire(self):
            class _Ctx:
                async def __aenter__(self_i):
                    return conn

                async def __aexit__(self_i, *a):
                    return False
            return _Ctx()

    class _DbHolder:
        _pool = _Pool()

    class _Impl:
        # the method reaches through `db_space_impl._db._pool`
        _db = _DbHolder()

    class _SpaceImpl:
        def get_db_space_impl(self):
            return _Impl()

    class _Record:
        space_impl = _SpaceImpl()

    class _SM:
        async def get_space_or_load(self, space_id):
            return _Record()

    ep = SPARQLGraphEndpoint.__new__(SPARQLGraphEndpoint)
    ep.logger = logging.getLogger(__name__)
    ep.space_manager = _SM()

    _count_cache.invalidate_space("cgspace")
    first = await ep._get_graph_counts("cgspace", "urn:g")
    assert first.status is OperationStatus.FOUND, (
        f"graph counts failed: {first.message}")
    assert first.entity_count == 7

    ran = conn.count_queries
    second = await ep._get_graph_counts("cgspace", "urn:g")
    assert second.entity_count == 7
    assert conn.count_queries == ran, (
        "the second call re-ran the aggregate — the cache is not being used, "
        "which is the 3,343 ms this exists to avoid")
