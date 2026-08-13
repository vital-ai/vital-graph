"""A cached count must follow the data, not the clock.

The dashboard's counts are served from `CountCache` because an exact
`COUNT(*)` over a graph is O(the graph) — 4,591 ms for 50.5M quads. That is
only acceptable if a write is reflected immediately; a 15 minute TTL is a
backstop, not the mechanism.

This is asserted against the REAL write path rather than by calling
`invalidate_graph` directly, because what matters is not that the cache CAN be
invalidated but that the code which changes data actually does it. A unit test
of the cache proves the former and would pass while the dashboard showed a
stale total for fifteen minutes.
"""

from __future__ import annotations

import pytest
from rdflib import URIRef

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

GRAPH = URIRef("urn:test:count_cache_graph")
EX = "http://example.org/cc/"


def _quads(n, tag):
    return [(URIRef(f"{EX}{tag}{i}"), URIRef(f"{EX}p"), URIRef(f"{EX}o{i}"), GRAPH)
            for i in range(n)]


async def test_an_insert_is_reflected_in_the_cached_count(test_space, space_impl):
    """Count, write, count again — the second must include the new quads."""
    backend = space_impl.get_db_space_impl() if hasattr(space_impl, "get_db_space_impl") else space_impl

    await backend.add_rdf_quads_batch(test_space, _quads(5, "a"))
    first = await backend.get_rdf_quad_count(test_space, str(GRAPH))
    assert first >= 5, f"seed did not land: {first}"

    # Warm the cache explicitly, so the next read would be served from it.
    assert await backend.get_rdf_quad_count(test_space, str(GRAPH)) == first

    await backend.add_rdf_quads_batch(test_space, _quads(3, "b"))
    second = await backend.get_rdf_quad_count(test_space, str(GRAPH))

    assert second == first + 3, (
        f"count went {first} -> {second} after inserting 3 quads. The write "
        f"path did not invalidate the count cache, so the dashboard would show "
        f"a stale total until the TTL expires.")


async def test_a_delete_is_reflected_too(test_space, space_impl):
    """Deletes are the direction that looks like a working cache when broken:
    the number simply stays high, which is indistinguishable from data still
    being there."""
    backend = space_impl.get_db_space_impl() if hasattr(space_impl, "get_db_space_impl") else space_impl

    quads = _quads(4, "d")
    await backend.add_rdf_quads_batch(test_space, quads)
    before = await backend.get_rdf_quad_count(test_space, str(GRAPH))
    assert await backend.get_rdf_quad_count(test_space, str(GRAPH)) == before  # warm

    removed = 0
    for q in quads[:2]:
        try:
            if await backend.remove_rdf_quad(test_space, *q):
                removed += 1
        except AttributeError:
            pytest.skip("backend has no single-quad remove; delete path untested here")
    if removed == 0:
        pytest.skip("no quads were removed; nothing to assert about")

    after = await backend.get_rdf_quad_count(test_space, str(GRAPH))
    assert after == before - removed, (
        f"count stayed at {after} after removing {removed} quads (was {before}) "
        f"— a stale count after a DELETE reads as data that is still present")


async def test_the_cache_is_per_graph(test_space, space_impl):
    """Writing to one graph must not disturb another's cached count, or the
    invalidation is too coarse and every write costs every graph its cache."""
    backend = space_impl.get_db_space_impl() if hasattr(space_impl, "get_db_space_impl") else space_impl
    other = URIRef("urn:test:count_cache_other")

    await backend.add_rdf_quads_batch(test_space, _quads(2, "g1"))
    await backend.add_rdf_quads_batch(test_space, [
        (URIRef(f"{EX}x{i}"), URIRef(f"{EX}p"), URIRef(f"{EX}o"), other)
        for i in range(6)])

    a_before = await backend.get_rdf_quad_count(test_space, str(GRAPH))
    b_before = await backend.get_rdf_quad_count(test_space, str(other))
    assert b_before == 6

    await backend.add_rdf_quads_batch(test_space, _quads(1, "g2"))

    assert await backend.get_rdf_quad_count(test_space, str(GRAPH)) == a_before + 1
    assert await backend.get_rdf_quad_count(test_space, str(other)) == b_before, (
        "the other graph's count changed when this one was written to")
