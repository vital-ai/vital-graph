"""A text filter is declared empty only when it really matches nothing (`issues/292`).

`issues/202` made a REQUIRED text filter measured at zero matches make the
whole query provably empty (`_empty LIMIT 0`). Two defects turned that into
wrong answers:

1. The measurement counts quads whose OBJECT is in the needle's term set, but
   it took the variable's first position whatever its column, so a filter on a
   SUBJECT (`FILTER(STRSTARTS(STR(?s), ...))`) was measured against objects:
   zero, and the query returned nothing.
2. The count was cached process-wide with no invalidation on write, so a
   needle searched for before its value existed kept the query empty after the
   value was written.

Both were found 2026-10-20 while testing the index sync trigger (`issues/291`),
when a SPARQL DELETE whose WHERE used STRSTARTS on the subject deleted nothing.
"""

from __future__ import annotations

import uuid

import pytest

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

CORE = "http://vital.ai/ontology/vital-core#"


def _graph():
    return f"http://example.org/txtempty/{uuid.uuid4().hex[:8]}"


async def _rows(space_impl, space, q):
    r = await space_impl.execute_sparql_query(space, q)
    return r["results"]["bindings"], r.get("sql") or ""


@pytest.mark.parametrize("fn", ["STRSTARTS", "CONTAINS"])
async def test_a_filter_on_the_subject_finds_its_subjects(test_space, space_impl, fn):
    from rdflib import Literal, URIRef
    g = _graph()
    subs = [f"urn:txtempty:{fn.lower()}:{i}" for i in range(3)]
    await space_impl.add_rdf_quads_batch_bulk(test_space, [
        (URIRef(s), URIRef(f"{CORE}hasName"), Literal("n"), URIRef(g)) for s in subs])
    needle = f"urn:txtempty:{fn.lower()}:"
    rows, sql = await _rows(space_impl, test_space,
        f'SELECT ?s WHERE {{ GRAPH <{g}> {{ ?s <{CORE}hasName> ?n . '
        f'FILTER({fn}(STR(?s), "{needle}")) }} }}')
    assert "_empty LIMIT 0" not in sql, "declared empty from a count over OBJECTS"
    assert sorted(r["s"]["value"] for r in rows) == subs


async def test_a_value_written_after_a_search_is_found_by_the_next(test_space, space_impl):
    from rdflib import Literal, URIRef
    g = _graph()
    needle = f"zq{uuid.uuid4().hex[:10]}"
    q = (f'SELECT ?s WHERE {{ GRAPH <{g}> {{ ?s <{CORE}hasName> ?n . '
         f'FILTER(CONTAINS(?n, "{needle}")) }} }}')
    await space_impl.add_rdf_quads_batch_bulk(test_space, [
        (URIRef("urn:txtempty:other"), URIRef(f"{CORE}hasName"), Literal("other"), URIRef(g))])
    rows, sql = await _rows(space_impl, test_space, q)
    assert rows == [] and "_empty LIMIT 0" in sql, "precondition: genuinely empty"
    await space_impl.add_rdf_quads_batch_bulk(test_space, [
        (URIRef("urn:txtempty:hit"), URIRef(f"{CORE}hasName"), Literal(f"a {needle} b"),
         URIRef(g))])
    rows, _ = await _rows(space_impl, test_space, q)
    assert [r["s"]["value"] for r in rows] == ["urn:txtempty:hit"], (
        "a cached zero kept the query empty after the value was written")


async def test_a_genuinely_absent_needle_is_still_declared_empty(test_space, space_impl):
    """The issues/202 short-circuit itself still fires for an object needle."""
    from rdflib import Literal, URIRef
    g = _graph()
    await space_impl.add_rdf_quads_batch_bulk(test_space, [
        (URIRef("urn:txtempty:x"), URIRef(f"{CORE}hasName"), Literal("present"), URIRef(g))])
    rows, sql = await _rows(space_impl, test_space,
        f'SELECT ?s WHERE {{ GRAPH <{g}> {{ ?s <{CORE}hasName> ?n . '
        f'FILTER(CONTAINS(?n, "absent{uuid.uuid4().hex[:8]}")) }} }}')
    assert rows == [] and "_empty LIMIT 0" in sql
