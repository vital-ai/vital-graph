"""A dateTime equality compares the INSTANT, not the lexical form.

`datatypes_and_language_tags.md` §4.6, which turned out to describe the
smaller half of the problem. It recorded that a timezoned and an untimezoned
dateTime compare FALSE where XSD says incomparable, and called that a
defensible practical choice. Measured, the real defect was larger:

    "2020-01-01T00:00:00Z"  =  "2020-01-01T00:00:00+00:00"     -> False
    "2020-01-01T00:00:00Z"  =  "2019-12-31T23:00:00-01:00"     -> False

Those are the SAME INSTANT, both timezoned, unambiguously equal. Equality was
lexical, so any two spellings of one moment compared unequal.

Worse against stored data, because rdflib normalises `...Z` to `...+00:00` on
the way in: `FILTER(?v = "2020-01-01T00:00:00Z"^^xsd:dateTime)` returned
NOTHING AT ALL — not even the term holding exactly that instant.

The fix routes `=` through `_ne_equality_cond`, the one place that already
compared dateTimes by `dt_val`. The timezone-agreement guard is what keeps
§4.6 honest: `vitalgraph_iso_to_utc` reads an untimezoned value as if UTC, so
without it, normalising would declare an incomparable pair EQUAL — trading a
missing row for a wrong one.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from rdflib import Literal, URIRef, XSD

from .conftest import skip_no_infra, TEST_SPACE_PREFIX

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]

G = "urn:dtq:g"
DT = str(XSD.dateTime)
SIDECAR = "http://localhost:7071"


@pytest_asyncio.fixture(loop_scope="session")
async def dt_space(space_impl, make_space):
    """Three spellings: two of one instant WITH a timezone, one without."""
    sid = await make_space(f"{TEST_SPACE_PREFIX}dtq_{uuid.uuid4().hex[:8]}")
    g = URIRef(G)
    await space_impl.add_rdf_quads_batch_bulk(sid, [
        (URIRef("urn:dtq:z"), URIRef("urn:dtq:v"),
         Literal("2020-01-01T00:00:00Z", datatype=XSD.dateTime), g),
        (URIRef("urn:dtq:off"), URIRef("urn:dtq:v"),
         Literal("2019-12-31T23:00:00-01:00", datatype=XSD.dateTime), g),
        (URIRef("urn:dtq:no"), URIRef("urn:dtq:v"),
         Literal("2020-01-01T00:00:00", datatype=XSD.dateTime), g)])
    return sid


async def _subjects(space_impl, space, flt):
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql

    q = f'SELECT ?s WHERE {{ GRAPH <{G}> {{ ?s <urn:dtq:v> ?v }} FILTER({flt}) }}'
    client = AsyncSidecarClient(SIDECAR)
    try:
        cr = map_compile_response(await client.compile(q))
        assert cr.ok, cr.error
        async with space_impl.db_impl.connection_pool.acquire() as conn:
            gen = await generate_sql(cr, space, conn=conn)
            assert gen.ok, gen.error
            rows = await conn.fetch(gen.sql)
        return sorted(str(list(dict(r).values())[0]) for r in rows)
    finally:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close:
            res = close()
            if hasattr(res, "__await__"):
                await res


async def test_a_timezoned_literal_finds_its_own_instant(space_impl, dt_space):
    """THE regression: this returned nothing, because rdflib stored `Z` as
    `+00:00` and the comparison was on text."""
    got = await _subjects(space_impl, dt_space, f'?v = "2020-01-01T00:00:00Z"^^<{DT}>')
    assert "urn:dtq:z" in got, f"got {got} — the term IS that instant"


async def test_one_instant_matches_every_timezoned_spelling(space_impl, dt_space):
    got = await _subjects(space_impl, dt_space, f'?v = "2020-01-01T00:00:00Z"^^<{DT}>')
    assert got == ["urn:dtq:off", "urn:dtq:z"], got


async def test_a_different_offset_denotes_the_same_moment(space_impl, dt_space):
    """`23:00-01:00` IS `00:00Z`. Lexically nothing alike."""
    got = await _subjects(space_impl, dt_space,
                          f'?v = "2019-12-31T23:00:00-01:00"^^<{DT}>')
    assert got == ["urn:dtq:off", "urn:dtq:z"], got


async def test_an_untimezoned_literal_matches_only_untimezoned_terms(space_impl, dt_space):
    """§4.6. Incomparable, so it must not match the timezoned ones — even
    though normalising them to UTC would make the numbers line up."""
    got = await _subjects(space_impl, dt_space, f'?v = "2020-01-01T00:00:00"^^<{DT}>')
    assert got == ["urn:dtq:no"], got


async def test_a_timezoned_literal_does_not_match_an_untimezoned_term(space_impl, dt_space):
    got = await _subjects(space_impl, dt_space, f'?v = "2020-01-01T00:00:00Z"^^<{DT}>')
    assert "urn:dtq:no" not in got, (
        f"got {got} — a timezoned and an untimezoned dateTime are "
        f"incomparable, and treating the missing offset as UTC invents one")


async def test_a_different_instant_matches_nothing(space_impl, dt_space):
    got = await _subjects(space_impl, dt_space, f'?v = "2021-06-01T12:00:00Z"^^<{DT}>')
    assert got == [], got
