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


# ---------------------------------------------------------------------------
# reltuples estimates. Cheap (1.7ms vs 4,591ms) and near-exact — six of eight
# quad tables measured EXACT, one 0.0001% out, one 0.635% out after deletes.
# Used only where it is SOUND: the whole table, and a space with exactly one
# graph, where the table total IS that graph's count.
# ---------------------------------------------------------------------------

class _EstConn:
    """Answers the catalog lookup and a real COUNT(*) with DIFFERENT values.

    They must differ, or a test cannot tell which path ran — the first version
    of this returned one value for both and "proved" nothing.
    """

    def __init__(self, value, count_value=4_242):
        self._value = value
        self._count_value = count_value

    async def fetchval(self, sql, *args):
        if "pg_class" in sql:
            return self._value
        return self._count_value


class _EstPool:
    def __init__(self, value, count_value=4_242):
        self._value = value
        self._count_value = count_value

    def acquire(self):
        value, cv = self._value, self._count_value

        class _Ctx:
            async def __aenter__(self):
                return _EstConn(value, cv)

            async def __aexit__(self, *a):
                return False
        return _Ctx()


def _impl_with(value):
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl
    impl = SparqlSQLSpaceImpl.__new__(SparqlSQLSpaceImpl)

    class _Schema:
        @staticmethod
        def get_table_names(space_id):
            return {"rdf_quad": f"{space_id}_rdf_quad"}

    class _DB:
        _pool = _EstPool(value)

    impl.schema = _Schema()
    impl.db_impl = _DB()
    return impl


async def test_an_estimate_is_returned_when_available():
    assert await _impl_with(50_570_040).get_rdf_quad_count_estimate("sp") == 50_570_040


async def test_a_never_analyzed_table_returns_none_not_minus_one():
    """PostgreSQL 14+ stores -1 for "never analysed", and one table on this
    database is in that state. Returning it would display MINUS ONE triple;
    None tells the caller to do the real count."""
    assert await _impl_with(-1).get_rdf_quad_count_estimate("sp") is None


async def test_a_missing_table_returns_none():
    assert await _impl_with(None).get_rdf_quad_count_estimate("sp") is None


async def test_a_failure_returns_none_rather_than_zero():
    """Zero would be indistinguishable from an empty space, and would then be
    displayed as the triple count."""
    class _Boom:
        def acquire(self):
            raise RuntimeError("pool down")

    impl = _impl_with(1)
    impl.db_impl._pool = _Boom()
    assert await impl.get_rdf_quad_count_estimate("sp") is None


async def test_the_space_wide_count_uses_the_estimate():
    """`get_rdf_quad_count(space)` with no graph must not run COUNT(*) when an
    estimate exists — that is the 4,591 ms this avoids."""
    impl = _impl_with(12_345)
    assert await impl.get_rdf_quad_count("sp") == 12_345


async def test_a_graph_scoped_count_never_uses_the_estimate():
    """There is no per-context estimate in the catalog. A table total says
    nothing about one graph of a multi-graph space, so this path must fall
    through to the real (cached) count rather than returning the table total.
    """
    from vitalgraph.cache.count_cache import _count_cache

    impl = _impl_with(999_999)          # the table estimate
    _count_cache.invalidate_graph("sp", "urn:g")
    got = await impl.get_rdf_quad_count("sp", "urn:g")
    assert got == 4_242, (
        f"expected the real COUNT(*) (4,242), got {got}")
    assert got != 999_999, (
        "a graph-scoped count returned the whole-TABLE estimate — in a "
        "multi-graph space that reports another graph's rows as this one's")
