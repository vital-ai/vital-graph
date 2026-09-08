"""`GET /kgframes?parent_uri=` returns a parent's CHILD frames, not the graph.

The client had always sent `parent_uri`; the route never declared it, and
FastAPI drops an undeclared query parameter SILENTLY. So filtering frames by
parent returned every frame in the graph — the wrong rows, indistinguishable
from the right ones, with no error anywhere.

Asserted through the query BUILDER rather than a live HTTP round trip, because
the defect was in what the server was willing to receive and what it then built.
A round trip would also have "passed" before the fix, by returning rows.

The relationship is an edge NODE, not a property: `?edge a Edge_hasKGFrame`
with `hasEdgeSource` the parent and `hasEdgeDestination` the child — the same
pattern `kg_validation_utils` uses to verify a parent-child link exists.
"""

from __future__ import annotations

import pytest

HALEY = "http://vital.ai/ontology/haley-ai-kg#"
CORE = "http://vital.ai/ontology/vital-core#"
PARENT = "http://example.org/frames/parent1"


def _processor():
    from vitalgraph.endpoint.kgframes_endpoint import KGFramesEndpoint
    return KGFramesEndpoint.__new__(KGFramesEndpoint)


def _clauses(**kw):
    p = _processor()
    p.haley_prefix = HALEY
    p.vital_prefix = CORE
    return p._build_frame_filter_clauses(**kw)


def test_the_route_declares_parent_uri():
    """Undeclared means silently dropped, which is how this went unnoticed."""
    import inspect, re
    from vitalgraph.endpoint import kgframes_endpoint as m

    src = inspect.getsource(m)
    i = src.index('@self.router.get("/kgframes"')
    j = src.index("async def ", i)
    k = src.index("):", j)
    assert "parent_uri" in src[j:k], (
        "GET /kgframes does not declare parent_uri; FastAPI will drop it and "
        "the caller will receive every frame in the graph")


def test_parent_uri_produces_the_edge_pattern():
    out = _clauses(parent_uri=PARENT)
    assert f"<{HALEY}Edge_hasKGFrame>" in out, f"no child-frame edge pattern: {out}"
    assert f"<{CORE}hasEdgeSource> <{PARENT}>" in out, (
        f"the parent is not bound as the edge SOURCE: {out}")
    assert f"<{CORE}hasEdgeDestination> ?frame" in out, (
        f"the listed frame is not bound as the edge DESTINATION: {out}")


def test_absent_parent_uri_adds_nothing():
    """It must not narrow a listing that did not ask to be narrowed."""
    assert "Edge_hasKGFrame" not in _clauses()
    assert "Edge_hasKGFrame" not in _clauses(status="urn:x")


def test_it_composes_with_the_other_filters():
    out = _clauses(parent_uri=PARENT, status="urn:Active",
                   frame_type_uri=f"{HALEY}SomeType")
    assert "Edge_hasKGFrame" in out
    assert "urn:Active" in out
    assert "SomeType" in out, "parent_uri displaced the other filters"


def test_the_plain_fast_path_treats_parent_uri_as_a_filter():
    """`fast_typed_subject_page` pages every frame by subject_uuid and has no
    notion of a parent, so a parent-scoped request must not reach it."""
    import inspect
    from vitalgraph.endpoint import kgframes_endpoint as m

    src = inspect.getsource(m)
    i = src.index("_no_filters = not any([")
    assert "parent_uri" in src[i:i + 800], (
        "the plain fast path does not treat parent_uri as a filter; it would "
        "page the whole graph for a parent-scoped request")


def test_the_prop_sort_path_SERVES_parent_scoped_listings():
    """It is not declined — it is answered from `{space}_edge`.

    "The children of this frame" is one typed hop, and
    `idx_{space}_edge_type_src` is `(edge_type_uuid, source_node_uuid)`, so it
    is a seek. Declining here would send a shape the schema is built for down
    the SPARQL path.
    """
    from vitalgraph.db.sparql_sql.fast_frame_prop_sort import build_frame_page_sql

    sql, params = build_frame_page_sql(
        "sp", [], f"{CORE}hasName", descending=False, typed=False,
        parent_uri=PARENT)
    assert "sp_edge" in sql, f"the parent hop is not served from the edge table: {sql}"
    assert "edge_type_uuid" in sql and "source_node_uuid" in sql, (
        f"the hop does not use the typed-traversal index columns: {sql}")
    assert "INTERSECT" in sql or "frame_uuid IN (" in sql, (
        f"the parent hop is not composed as a conjunct: {sql}")


def test_parent_composes_with_filter_and_sort_in_one_plan():
    """parent + property filter + sort must be ONE query, not a fallback."""
    from vitalgraph.db.sparql_sql.fast_frame_prop_sort import build_frame_page_sql

    built = build_frame_page_sql(
        "sp", [(f"{HALEY}hasKGFrameType", "eq", f"{HALEY}T")],
        f"{CORE}hasName", descending=False, typed=False, parent_uri=PARENT)
    assert built is not None, "the combination was declined"
    sql, _ = built
    assert "sp_edge" in sql and "value_all" in sql and "ORDER BY" in sql, (
        f"parent, filter and sort are not all in the one plan: {sql}")


# --------------------------------------------------------------------------
# Against real data: the fast path must return the parent's children and
# nothing else. The SQL-shape assertions above cannot show that.
# --------------------------------------------------------------------------

from .conftest import skip_no_infra  # noqa: E402

EX = "http://example.org/pf/"
GRAPH = "http://example.org/pf/graph"


def _hierarchy_quads():
    """Two parents, two children each, plus an unrelated top-level frame."""
    from rdflib import URIRef, Literal
    g = URIRef(GRAPH)
    out = []

    def frame(name, desc):
        f = URIRef(f"{EX}{name}")
        return [
            (f, URIRef(f"{CORE}vitaltype"), URIRef(f"{HALEY}KGFrame"), g),
            (f, URIRef(f"{HALEY}hasKGFrameType"), URIRef(f"{EX}FT"), g),
            (f, URIRef(f"{HALEY}hasKGFrameTypeDescription"), Literal(desc), g),
        ]

    def child_edge(parent, child):
        e = URIRef(f"{EX}edge_{parent}_{child}")
        return [
            (e, URIRef(f"{CORE}vitaltype"), URIRef(f"{HALEY}Edge_hasKGFrame"), g),
            (e, URIRef(f"{CORE}hasEdgeSource"), URIRef(f"{EX}{parent}"), g),
            (e, URIRef(f"{CORE}hasEdgeDestination"), URIRef(f"{EX}{child}"), g),
        ]

    for n, d in (("p1", "parent one"), ("p2", "parent two"), ("lonely", "no parent"),
                 ("c1", "zulu"), ("c2", "alpha"), ("c3", "mike"), ("c4", "bravo")):
        out += frame(n, d)
    out += child_edge("p1", "c1") + child_edge("p1", "c2")
    out += child_edge("p2", "c3") + child_edge("p2", "c4")
    return out


@pytest.mark.integration
@skip_no_infra
@pytest.mark.asyncio(loop_scope="session")
async def test_fast_path_returns_only_that_parents_children(test_space, space_impl):
    from vitalgraph.db.sparql_sql.fast_frame_prop_sort import fast_frame_prop_page

    await space_impl.add_rdf_quads_batch(test_space, _hierarchy_quads())

    uris = await fast_frame_prop_page(
        space_impl, test_space, GRAPH, 50, 0,
        form_type=f"{HALEY}KGFormType_Assertion",
        parent_uri=f"{EX}p1",
        sort_by=f"{HALEY}hasKGFrameTypeDescription")

    assert uris is not None, "the fast path declined a parent-scoped listing"
    names = [u.rsplit("/", 1)[-1] for u in uris]
    # c2 'alpha' before c1 'zulu'; p2's children and the lonely frame excluded.
    assert names == ["c2", "c1"], (
        f"got {names}; expected exactly p1's children in sorted order. "
        f"Anything containing c3/c4/lonely means the parent hop did not "
        f"restrict, which is the whole bug.")


@pytest.mark.integration
@skip_no_infra
@pytest.mark.asyncio(loop_scope="session")
async def test_a_parent_with_no_children_returns_empty_not_everything(
        test_space, space_impl):
    """The dangerous direction: an unrestricted page looks like a full result."""
    from vitalgraph.db.sparql_sql.fast_frame_prop_sort import fast_frame_prop_page

    await space_impl.add_rdf_quads_batch(test_space, _hierarchy_quads())

    uris = await fast_frame_prop_page(
        space_impl, test_space, GRAPH, 50, 0,
        form_type=f"{HALEY}KGFormType_Assertion",
        parent_uri=f"{EX}lonely",
        sort_by=f"{HALEY}hasKGFrameTypeDescription")

    assert uris == [], (
        f"a childless parent returned {uris}; an unfiltered page here is "
        f"exactly the silent wrong answer this parameter was added to end")
