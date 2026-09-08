"""The fast page and the SPARQL page must be the SAME page.

A derived-table fast path is only ever worth having if it cannot disagree with
the query it replaces. The failure that matters is not "slower than hoped" —
it is a page that looks right, is ordered right, and is missing rows, because
nothing in the response says which path produced it.

So these compare the two directly rather than asserting the fast path against a
hand-written expectation. A hand-written expectation can be wrong in the same
direction as the code.

`verify_paging_by_partition` is the other half of this and lives elsewhere:
pages must partition the full result set. Here the concern is agreement.
"""

from __future__ import annotations

import pytest

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

KG = "http://vital.ai/ontology/haley-ai-kg#"
CORE = "http://vital.ai/ontology/vital-core#"
AIMP = "http://vital.ai/ontology/vital-aimp#"
EX = "http://example.org/epp/"
GRAPH = "http://example.org/epp/graph"
ETYPE = f"{EX}Lead"

# Deliberately not in name order, so a page that ignores the sort is visible.
ROWS = [("e1", "zulu", "Active"), ("e2", "alpha", "Closed"),
        ("e3", "mike", "Active"), ("e4", "bravo", "Active"),
        ("e5", "yankee", "Closed")]


def _quads():
    from rdflib import URIRef, Literal
    g = URIRef(GRAPH)
    out = []
    for name, value, status in ROWS:
        e = URIRef(f"{EX}{name}")
        out += [
            (e, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}KGEntity"), g),
            (e, URIRef(f"{KG}hasKGEntityType"), URIRef(ETYPE), g),
            (e, URIRef(f"{CORE}hasName"), Literal(value), g),
            (e, URIRef(f"{AIMP}hasObjectStatusType"), URIRef(f"{EX}{status}"), g),
        ]
    return out


async def _fast(impl, space, **kw):
    from vitalgraph.db.sparql_sql.fast_prop_sort import fast_entity_prop_page
    return await fast_entity_prop_page(impl, space, GRAPH, 50, 0, **kw)


async def test_sort_by_name_is_actually_sorted(test_space, space_impl):
    await space_impl.add_rdf_quads_batch(test_space, _quads())

    uris = await _fast(space_impl, test_space,
                       entity_type_uri=ETYPE, sort_by=f"{CORE}hasName")

    assert uris is not None, "the fast path declined a plain sort it should serve"
    names = [u.rsplit("/", 1)[-1] for u in uris]
    expected = [n for n, _, _ in sorted(ROWS, key=lambda r: r[1])]
    assert names == expected, (
        f"page order {names} is not the sorted order {expected} — the ORDER BY "
        f"is not being served from the index")


async def test_descending_reverses_it(test_space, space_impl):
    await space_impl.add_rdf_quads_batch(test_space, _quads())

    uris = await _fast(space_impl, test_space, entity_type_uri=ETYPE,
                       sort_by=f"{CORE}hasName", sort_order="desc")

    names = [u.rsplit("/", 1)[-1] for u in uris]
    expected = [n for n, _, _ in sorted(ROWS, key=lambda r: r[1], reverse=True)]
    assert names == expected, f"descending page {names} != {expected}"


async def test_filter_and_sort_may_name_different_properties(
        test_space, space_impl):
    """Two rows of the same table for one entity, INTERSECTed on entity_uuid.

    The shape most likely to be got wrong, because it is the one where a single
    row cannot answer the question.
    """
    await space_impl.add_rdf_quads_batch(test_space, _quads())

    uris = await _fast(space_impl, test_space, entity_type_uri=ETYPE,
                       filters={"status": f"{EX}Active"},
                       sort_by=f"{CORE}hasName")

    names = [u.rsplit("/", 1)[-1] for u in uris]
    expected = [n for n, v, s in sorted(ROWS, key=lambda r: r[1]) if s == "Active"]
    assert names == expected, (
        f"filter+sort produced {names}, expected {expected} — status filter and "
        f"name sort are different properties and must intersect, not collide")


async def test_paging_partitions_the_result_set(test_space, space_impl):
    """Each page disjoint, the union complete, no row seen twice or lost."""
    from vitalgraph.db.sparql_sql.fast_prop_sort import fast_entity_prop_page

    await space_impl.add_rdf_quads_batch(test_space, _quads())

    seen = []
    for off in range(0, len(ROWS), 2):
        page = await fast_entity_prop_page(
            space_impl, test_space, GRAPH, 2, off,
            entity_type_uri=ETYPE, sort_by=f"{CORE}hasName")
        assert page is not None, f"declined at offset {off}"
        seen += page

    assert len(seen) == len(set(seen)), f"a row appears on two pages: {seen}"
    assert len(seen) == len(ROWS), (
        f"paging returned {len(seen)} of {len(ROWS)} rows — pages do not "
        f"partition the result set")
    expected = [n for n, _, _ in sorted(ROWS, key=lambda r: r[1])]
    assert [u.rsplit("/", 1)[-1] for u in seen] == expected


async def test_a_blocked_space_declines(test_space, space_impl, pg_pool):
    """Absence means serve; a block must actually stop it.

    The gate is a block-list, so this is the only thing standing between a
    resync in flight and a page served from a half-built table.
    """
    from vitalgraph.db.sparql_sql.fast_prop_sort import fast_entity_prop_page

    await space_impl.add_rdf_quads_batch(test_space, _quads())
    assert await fast_entity_prop_page(
        space_impl, test_space, GRAPH, 50, 0,
        entity_type_uri=ETYPE, sort_by=f"{CORE}hasName") is not None

    async with pg_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO slot_sort_block (space_id, entity_type_uuid, reason) "
            "VALUES ($1, NULL, 'test') ON CONFLICT DO NOTHING", test_space)
    try:
        blocked = await fast_entity_prop_page(
            space_impl, test_space, GRAPH, 50, 0,
            entity_type_uri=ETYPE, sort_by=f"{CORE}hasName")
        assert blocked is None, (
            "a whole-space block did not stop the prop-sort page — the shared "
            "block is what makes a restore safe for BOTH derived tables")
    finally:
        async with pg_pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM slot_sort_block WHERE space_id = $1", test_space)


async def test_an_unexpressible_filter_declines_rather_than_ignoring_it(
        test_space, space_impl):
    """Serving a SUBSET of the filters is a confident wrong answer."""
    await space_impl.add_rdf_quads_batch(test_space, _quads())

    got = await _fast(space_impl, test_space, entity_type_uri=ETYPE,
                      filters={"something_new": "x"},
                      sort_by=f"{CORE}hasName")

    assert got is None, (
        "an unrecognised filter was ignored and the page served anyway; the "
        "caller cannot tell that its filter was dropped")


async def _list(adapter, space, **kw):
    """One page through the real listing, returning entity URIs in page order."""
    from vitalgraph.kg_impl.kgentity_list_impl import KGEntityListProcessor

    res = await KGEntityListProcessor().list_entities(
        space, GRAPH, adapter, page_size=50, offset=0, **kw)
    return [str(o.URI) for o in res.entities], res.total_count


@pytest.mark.parametrize("kw", [
    {"sort_by": f"{CORE}hasName"},
    {"sort_by": f"{CORE}hasName", "sort_order": "desc"},
    {"entity_type_uri": ETYPE, "sort_by": f"{CORE}hasName"},
    {"entity_type_uri": ETYPE, "sort_by": f"{CORE}hasName", "status": f"{EX}Active"},
    {"entity_type_uri": ETYPE, "status": f"{EX}Active"},
    # The most common browse, and the one shape that used to decline: filter by
    # type, no sort. It must return the SAME page as the SPARQL walk it now
    # replaces — same rows AND same order.
    {"entity_type_uri": ETYPE},
])
async def test_fast_path_and_sparql_return_the_same_page(
        test_space, space_impl, backend_adapter, monkeypatch, kw):
    """THE ONE THAT MATTERS: same rows, same order, both paths.

    Compared against the SPARQL query the fast path replaces, not against a
    hand-written expectation — an expectation can be wrong in the same direction
    as the code, and this is exactly the class of bug (a plausible subset) that
    a derived table introduces.

    The fallback is forced by making the fast page decline, which is the same
    lever production has: declining is always safe.
    """
    await space_impl.add_rdf_quads_batch(test_space, _quads())

    fast_uris, fast_total = await _list(backend_adapter, test_space, **kw)

    async def _decline(*a, **k):
        return None
    monkeypatch.setattr(type(backend_adapter), "fast_entity_page",
                        _decline, raising=True)
    slow_uris, slow_total = await _list(backend_adapter, test_space, **kw)

    assert fast_uris == slow_uris, (
        f"the two paths disagree for {kw}\n"
        f"  fast: {[u.rsplit('/',1)[-1] for u in fast_uris]}\n"
        f"  slow: {[u.rsplit('/',1)[-1] for u in slow_uris]}\n"
        "A derived-table page that is ordered right and missing rows is the "
        "failure this table can introduce; nothing in the response says which "
        "path produced it.")
    assert fast_total == slow_total, (
        f"total_count disagrees for {kw}: fast={fast_total} slow={slow_total}")


async def test_tied_sort_values_break_the_tie_the_same_way(
        test_space, space_impl, backend_adapter, monkeypatch):
    """When the sort value ties, the TIE-BREAK is the page order.

    Not an edge case. Two of the seven sortable properties are `uri` typed with a
    handful of distinct values — sort by `hasObjectStatusType` and essentially
    every row ties, so whatever breaks the tie decides the whole page.

    The fast path used to break ties on `entity_uuid`, a hash of the URI, while
    the SPARQL query breaks them on `?s`. Five entities sharing a name came back
    b,e,a,c,d against a,b,c,d,e. Found by comparing the paths, not by reasoning
    about them.
    """
    from rdflib import URIRef, Literal
    g = URIRef(GRAPH)
    quads = []
    for n in ("a", "b", "c", "d", "e"):
        e = URIRef(f"{EX}tie_{n}")
        quads += [
            (e, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}KGEntity"), g),
            (e, URIRef(f"{KG}hasKGEntityType"), URIRef(ETYPE), g),
            (e, URIRef(f"{CORE}hasName"), Literal("identical"), g),
        ]
    await space_impl.add_rdf_quads_batch(test_space, quads)

    fast, _ = await _list(backend_adapter, test_space,
                          entity_type_uri=ETYPE, sort_by=f"{CORE}hasName")

    async def _decline(*a, **k):
        return None
    monkeypatch.setattr(type(backend_adapter), "fast_entity_page",
                        _decline, raising=True)
    slow, _ = await _list(backend_adapter, test_space,
                          entity_type_uri=ETYPE, sort_by=f"{CORE}hasName")

    assert fast == slow, (
        f"tie-break diverges\n"
        f"  fast: {[u.rsplit('/',1)[-1] for u in fast]}\n"
        f"  slow: {[u.rsplit('/',1)[-1] for u in slow]}")


async def test_a_typed_listing_with_no_sort_is_served_in_uri_order(
        test_space, space_impl):
    """It used to decline, sending the commonest browse to the SPARQL walk.

    Ordered by entity URI, matching `ORDER BY ?s`. Deliberately NOT by
    `entity_uuid`: that is a hash of the URI, so the two orders are unrelated,
    and the sibling `fast_typed_subject_page` already disagrees with SPARQL for
    exactly that reason.
    """
    from vitalgraph.db.sparql_sql.fast_prop_sort import fast_entity_prop_page

    await space_impl.add_rdf_quads_batch(test_space, _quads())

    uris = await fast_entity_prop_page(
        space_impl, test_space, GRAPH, 50, 0, entity_type_uri=ETYPE)

    assert uris is not None, (
        "a typed listing with no sort was declined; that is the most common "
        "browse and it falls to a 3.7s SPARQL walk")
    assert uris == sorted(uris), f"not in URI order: {uris}"
    # A superset check, not equality: this module's space is shared and other
    # tests add entities of the same type to it.
    names = {u.rsplit("/", 1)[-1] for u in uris}
    assert names >= {n for n, _, _ in ROWS}, (
        f"rows missing from the typed listing: "
        f"{ {n for n, _, _ in ROWS} - names}")


async def test_an_untyped_unsorted_listing_still_defers(test_space, space_impl):
    """The plain default belongs to `fast_typed_subject_page`; this path must
    not take it over, or the two would order pages differently."""
    from vitalgraph.db.sparql_sql.fast_prop_sort import fast_entity_prop_page

    await space_impl.add_rdf_quads_batch(test_space, _quads())
    assert await fast_entity_prop_page(
        space_impl, test_space, GRAPH, 50, 0) is None
