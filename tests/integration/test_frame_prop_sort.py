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


async def test_every_frame_is_indexed_with_its_resolved_form_type(
        test_space, space_impl, pg_pool):
    """Membership is "it is a frame". Form type is a COLUMN, not a filter on
    what the table contains.

    Scoping the table to Assertions made form type a property of the
    population, and that had a consequence beyond the All tab: traversal is
    general, so a table admitting one form type can only answer the traversals
    whose results happen to share it. On `lead_nurture_grouped` every one of
    its 900,000 child frames resolves to Aspect, so no parent-scoped listing
    there could be served.
    """
    await space_impl.add_rdf_quads_batch(test_space, _quads())

    # Compared as UUIDs, not resolved through `term`: these form-type URIs are
    # DERIVED, so they need never appear as a term in the space at all.
    from vitalgraph.db.sparql_sql.sync_frame_prop_sort import (
        _u, ASSERTION_URI, ASPECT_URI)

    async with pg_pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT DISTINCT frame_uri, form_type_uuid "
            f"FROM {test_space}_frame_prop_sort")
    got = {r["frame_uri"].rsplit("/", 1)[-1]: r["form_type_uuid"] for r in rows}

    assert sorted(got) == ["f1", "f2", "f3", "f4", "f5"], (
        f"not every frame is indexed: {sorted(got)}. Aspects missing here is "
        f"what made parent-scoped listings unservable.")
    # f1-f3 carry no hasFrameGraphURI -> Assertion by the unset default;
    # f4/f5 carry one -> Aspect.
    for n in ("f1", "f2", "f3"):
        assert got[n] == _u(ASSERTION_URI), f"{n} resolved to {got[n]}, not Assertion"
    for n in ("f4", "f5"):
        assert got[n] == _u(ASPECT_URI), f"{n} resolved to {got[n]}, not Aspect"


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


async def test_each_tab_returns_exactly_its_own_frames(test_space, space_impl):
    """Assertion, Aspect and All are one predicate apart — none declines.

    The previous revision could only serve Assertion and had to decline the
    rest; serving All from an Assertion-only table would have returned the
    Assertion subset with nothing saying so.
    """
    await space_impl.add_rdf_quads_batch(test_space, _quads())
    prop = f"{KG}hasKGFrameTypeDescription"

    assertions = await _page(space_impl, test_space, sort_by=prop)
    assert sorted(u.rsplit("/", 1)[-1] for u in assertions) == ["f1", "f2", "f3"], (
        f"Assertion tab returned {assertions}")

    aspects = await _page(space_impl, test_space, sort_by=prop,
                          form_type=f"{KG}KGFormType_Aspect")
    assert aspects is not None, "the Aspect tab was declined"
    assert sorted(u.rsplit("/", 1)[-1] for u in aspects) == ["f4", "f5"], (
        f"Aspect tab returned {aspects}")

    every = await _page(space_impl, test_space, sort_by=prop, form_type=None)
    assert every is not None, "the All tab was declined"
    assert sorted(u.rsplit("/", 1)[-1] for u in every) == \
        ["f1", "f2", "f3", "f4", "f5"], f"All tab returned {every}"


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


async def test_a_whole_space_block_stops_a_typed_listing(
        test_space, space_impl, pg_pool):
    """A whole-space block must stop EVERY listing, typed or not.

    The gate's predicate used to match a NULL `entity_type_uuid` only when the
    caller happened to pass no type — so a typed listing was served straight
    out of a half-built table while its own migration was still populating.
    That is the exact window blocking exists to close.
    """
    from vitalgraph.db.sparql_sql.fast_frame_prop_sort import fast_frame_prop_page

    await space_impl.add_rdf_quads_batch(test_space, _quads())
    prop = f"{KG}hasKGFrameTypeDescription"
    assert await _page(space_impl, test_space, sort_by=prop) is not None

    async with pg_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO prop_sort_block (space_id, entity_type_uuid, reason) "
            "VALUES ($1, NULL, 'test whole-space') ON CONFLICT DO NOTHING", test_space)
    try:
        untyped = await _page(space_impl, test_space, sort_by=prop)
        typed = await _page(space_impl, test_space, sort_by=prop,
                            frame_type_uri=FTYPE)
        assert untyped is None, "a whole-space block did not stop an untyped listing"
        assert typed is None, (
            "a whole-space block did not stop a TYPED listing — it would be "
            "served from a table its own migration is still populating")
    finally:
        async with pg_pool.acquire() as conn:
            await conn.execute("DELETE FROM prop_sort_block WHERE space_id = $1",
                               test_space)


async def test_building_frames_does_not_block_slot_sort(test_space, space_impl, pg_pool):
    """A prop-sort rebuild must not disable an unrelated fast path.

    The migrations took their whole-space block in `slot_sort_block`, which
    turned the SLOT-sort fast path off for the entire space for the length of
    the build — eleven minutes on a 74.5M-quad space — for a rebuild that says
    nothing about that table. Reading `slot_sort_block` is still correct; only
    writing it was wrong.
    """
    import pathlib
    for name in ("migrate_entity_prop_sort.py", "migrate_frame_prop_sort.py"):
        src = (pathlib.Path(__file__).resolve().parents[2] / "scripts" / name).read_text()
        writes = [ln for ln in src.splitlines()
                  if "slot_sort_block" in ln and ("INSERT INTO" in ln or "DELETE FROM" in ln)]
        assert not writes, (
            f"{name} writes to slot_sort_block: {writes}. A table must block "
            f"itself, in prop_sort_block.")
