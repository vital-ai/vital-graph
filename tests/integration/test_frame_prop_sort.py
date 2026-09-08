"""`{space}_frame_prop_sort` — top-level (Assertion) frames, sorted and filtered.

The frame twin of `test_entity_prop_sort_maintenance.py` plus the agreement
check that caught two real ordering bugs on the entity side.

THE POPULATION IS THE POINT HERE, in a way it was not for entities. This table
holds ASSERTIONS, defined exactly as `kgframes_endpoint` defines them: an
explicit `hasKGFormType` of Assertion, OR no form type and no
`hasFrameGraphURI`. The tempting approximation — "a frame with no parent" —
disagrees on real data (`sp_lead_dup`: 5,500 Assertions against 1,000
parentless frames), and a population that differs from what the tab lists is a
page that looks complete and is not.
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
EX = "http://example.org/fps/"
GRAPH = "http://example.org/fps/graph"
FTYPE = f"{EX}WordType"
ASSERTION = f"{KG}KGFormType_Assertion"

# name -> (type description, is_aspect)
ROWS = [("f1", "zebra", False), ("f2", "apple", False), ("f3", "mango", False),
        ("f4", "banana", True), ("f5", "cherry", True)]


def _quads():
    """Assertions carry no hasFrameGraphURI; Aspects carry one."""
    from rdflib import URIRef, Literal
    g = URIRef(GRAPH)
    out = []
    for name, desc, is_aspect in ROWS:
        f = URIRef(f"{EX}{name}")
        out += [
            (f, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}KGFrame"), g),
            (f, URIRef(f"{KG}hasKGFrameType"), URIRef(FTYPE), g),
            (f, URIRef(f"{KG}hasKGFrameTypeDescription"), Literal(desc), g),
        ]
        if is_aspect:
            # An Aspect by the unset-default rule: no form type, but it has a
            # frame graph uri.
            out.append((f, URIRef(f"{KG}hasFrameGraphURI"), URIRef(f"{EX}owner"), g))
    return out


async def _page(impl, space, **kw):
    from vitalgraph.db.sparql_sql.fast_frame_prop_sort import fast_frame_prop_page
    kw.setdefault("form_type", ASSERTION)
    return await fast_frame_prop_page(impl, space, GRAPH, 50, 0, **kw)


async def test_only_assertions_are_indexed(test_space, space_impl, pg_pool):
    """The two Aspects must not be in the table at all."""
    await space_impl.add_rdf_quads_batch(test_space, _quads())

    async with pg_pool.acquire() as conn:
        names = [r[0].rsplit("/", 1)[-1] for r in await conn.fetch(
            f"SELECT DISTINCT frame_uri FROM {test_space}_frame_prop_sort")]

    assert sorted(names) == ["f1", "f2", "f3"], (
        f"table holds {sorted(names)}; it must hold only the Assertions — an "
        f"Aspect here would appear on the Assertion tab")


async def test_sorted_by_type_description(test_space, space_impl):
    """The wordnet shape: frames whose only distinguishing property is the
    type description."""
    await space_impl.add_rdf_quads_batch(test_space, _quads())

    uris = await _page(space_impl, test_space,
                       sort_by=f"{KG}hasKGFrameTypeDescription")

    assert uris is not None, "the fast path declined a plain Assertion sort"
    names = [u.rsplit("/", 1)[-1] for u in uris]
    expected = [n for n, d, a in sorted(ROWS, key=lambda r: r[1]) if not a]
    assert names == expected, f"page order {names} != {expected}"


async def test_other_tabs_decline(test_space, space_impl):
    """Serving All or Aspect from an Assertion table is a silent subset."""
    await space_impl.add_rdf_quads_batch(test_space, _quads())

    for form in (None, f"{KG}KGFormType_Aspect"):
        got = await _page(space_impl, test_space, form_type=form,
                          sort_by=f"{KG}hasKGFrameTypeDescription")
        assert got is None, (
            f"form_type={form} was served from the Assertion table; it would "
            f"return only the Assertion subset with nothing saying so")


async def test_becoming_an_aspect_removes_the_row(test_space, space_impl, pg_pool):
    """Membership is DERIVED, so a write that changes nothing about the sorted
    property can still change whether the frame belongs here.

    Adding `hasFrameGraphURI` turns an Assertion into an Aspect. The property
    quads it was indexed on never move, so anything keyed on "which property
    changed" would leave the row behind and keep serving a frame the Assertion
    tab no longer lists.
    """
    from rdflib import URIRef
    await space_impl.add_rdf_quads_batch(test_space, _quads())
    names = [u.rsplit("/", 1)[-1] for u in await _page(
        space_impl, test_space, sort_by=f"{KG}hasKGFrameTypeDescription")]
    assert "f1" in names

    await space_impl.add_rdf_quads_batch(test_space, [
        (URIRef(f"{EX}f1"), URIRef(f"{KG}hasFrameGraphURI"),
         URIRef(f"{EX}owner"), URIRef(GRAPH))])

    names = [u.rsplit("/", 1)[-1] for u in await _page(
        space_impl, test_space, sort_by=f"{KG}hasKGFrameTypeDescription")]
    assert "f1" not in names, (
        "f1 became an Aspect but is still served on the Assertion tab — the "
        "re-derive did not re-evaluate membership")


async def test_drift_and_coverage_are_clean(test_space, space_impl, pg_pool):
    from vitalgraph.db.sparql_sql.sync_frame_prop_sort import (
        frame_prop_sort_drift, frame_prop_sort_coverage)
    await space_impl.add_rdf_quads_batch(test_space, _quads())
    async with pg_pool.acquire() as conn:
        expected, actual = await frame_prop_sort_drift(conn, test_space)
        gaps = await frame_prop_sort_coverage(conn, test_space)
    assert expected == actual, f"drift: expected {expected}, actual {actual}"
    assert gaps == [], f"coverage shortfall on a freshly written space: {gaps}"


async def test_deleting_a_frame_removes_its_rows(test_space, space_impl, pg_pool):
    await space_impl.add_rdf_quads_batch(test_space, _quads())
    await space_impl.remove_rdf_quads_batch(test_space, [
        q for q in _quads() if str(q[0]).endswith("/f2")])

    async with pg_pool.acquire() as conn:
        names = [r[0].rsplit("/", 1)[-1] for r in await conn.fetch(
            f"SELECT DISTINCT frame_uri FROM {test_space}_frame_prop_sort")]
    assert "f2" not in names, f"rows survive the frame they describe: {names}"
