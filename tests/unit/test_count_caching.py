"""The dashboard's counts are cached, and the cache cannot lie about a failure.

The space and graph pages were reported as ~20 s loads. Measured:

    exact COUNT(*) for one graph        4,591.3 ms   (50.5M quads)
    graph entity/frame/relation counts  3,343.0 ms
    reltuples estimate                      1.7 ms   (within 40 rows)

`list_graphs` calls the quad count once per graph, and the dashboard calls
`list_graphs` once per space — 67 of them, concurrently. The counts themselves
are honest work; an exact `COUNT(*)` over a graph is O(the graph) and no index
removes it. So the fix is to stop repeating it, using the `CountCache` that
already existed with its invalidation already wired into the write paths.

What these tests protect is the part that would be silently wrong: a count that
FAILED must not be cached as 0, because 0 is indistinguishable from a genuinely
empty graph — the same class of bug as `issues/082`, where a backend failure was
reported as a successful empty read.
"""

from __future__ import annotations

import pytest

from vitalgraph.cache.count_cache import CountCache


def test_a_hit_returns_the_stored_count():
    c = CountCache()
    h = c.query_hash("rdf_quad_count::sp::urn:g")
    assert c.get("sp", "urn:g", h) is None
    c.put("sp", "urn:g", h, 50_570_000)
    assert c.get("sp", "urn:g", h) == 50_570_000


def test_a_write_to_the_graph_invalidates_it():
    """The property that makes caching a live count acceptable at all."""
    c = CountCache()
    h = c.query_hash("rdf_quad_count::sp::urn:g")
    c.put("sp", "urn:g", h, 10)
    c.invalidate_graph("sp", "urn:g")
    assert c.get("sp", "urn:g", h) is None


def test_invalidating_one_graph_leaves_its_siblings():
    c = CountCache()
    h1 = c.query_hash("rdf_quad_count::sp::urn:g1")
    h2 = c.query_hash("rdf_quad_count::sp::urn:g2")
    c.put("sp", "urn:g1", h1, 1)
    c.put("sp", "urn:g2", h2, 2)
    c.invalidate_graph("sp", "urn:g1")
    assert c.get("sp", "urn:g1", h1) is None
    assert c.get("sp", "urn:g2", h2) == 2


def test_counts_of_different_graphs_do_not_collide():
    """The key includes the graph, so two graphs of one space stay distinct.

    Worth pinning: the cache is keyed by (space, graph, hash) and the hash is
    derived from a string that ALSO contains both. Getting either wrong would
    show one graph's totals on another's page.
    """
    c = CountCache()
    for g, n in (("urn:g1", 11), ("urn:g2", 22)):
        c.put("sp", g, c.query_hash(f"rdf_quad_count::sp::{g}"), n)
    assert c.get("sp", "urn:g1", c.query_hash("rdf_quad_count::sp::urn:g1")) == 11
    assert c.get("sp", "urn:g2", c.query_hash("rdf_quad_count::sp::urn:g2")) == 22


def test_the_whole_space_count_is_separate_from_any_graph():
    """`get_rdf_quad_count(space)` with no graph counts the whole table, and
    must not be served from a per-graph entry or vice versa."""
    c = CountCache()
    whole = c.query_hash("rdf_quad_count::sp::__whole_space__")
    one = c.query_hash("rdf_quad_count::sp::urn:g")
    c.put("sp", "__whole_space__", whole, 999)
    assert c.get("sp", "urn:g", one) is None


def test_the_three_graph_counts_are_stored_independently():
    """Packing entity/frame/relation into one integer would truncate a graph
    with more than ~2M frames. Three keys cannot."""
    c = CountCache()
    vals = {"entity": 3_000_000, "frame": 4_000_000, "relation": 5_000_000}
    keys = {n: c.query_hash(f"graph_counts::sp::urn:g::{n}") for n in vals}
    for n, v in vals.items():
        c.put("sp", "urn:g", keys[n], v)
    for n, v in vals.items():
        assert c.get("sp", "urn:g", keys[n]) == v, (
            f"{n} came back wrong — large counts must survive the cache intact")


async def test_a_failed_count_is_not_cached_as_zero():
    """`get_rdf_quad_count` returns 0 on error. That 0 must NOT be stored.

    A cached 0 is indistinguishable from a genuinely empty graph, so a transient
    database error would show "0 triples" for up to the TTL, on a page whose
    whole purpose is to report size (`issues/082` is the same mistake).
    """
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl
    from vitalgraph.cache.count_cache import _count_cache

    class _Boom:
        def acquire(self):
            raise RuntimeError("pool is down")

    impl = SparqlSQLSpaceImpl.__new__(SparqlSQLSpaceImpl)

    class _Schema:
        @staticmethod
        def get_table_names(space_id):
            return {"rdf_quad": f"{space_id}_rdf_quad"}

    class _DB:
        _pool = _Boom()

    impl.schema = _Schema()
    # `_db` is a read-only property over `db_impl`, so set the backing field.
    impl.db_impl = _DB()

    key = _count_cache.query_hash("rdf_quad_count::failspace::urn:g")
    _count_cache.invalidate_graph("failspace", "urn:g")

    assert await impl.get_rdf_quad_count("failspace", "urn:g") == 0
    assert _count_cache.get("failspace", "urn:g", key) is None, (
        "a failed count was cached as 0 — an outage now looks like an empty "
        "graph for the life of the entry")
