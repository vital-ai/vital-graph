"""Two literals with different datatypes are not equal.

`issues/121`. Comparison falls back to `term_text`, so every datatype we do not
model collapses into the string lane and `"x"^^<urn:myType> = "x"` answers TRUE
where SPARQL says FALSE — a silently wrong answer, not an error.

The design is written up in
`planning/planning_sparql_features/datatypes_and_language_tags.md` §4b. The
part that decides these tests: `=` and `!=` are NOT mirror images once a type
guard exists. Appending `AND datatypes agree` is right for `=` and wrong for
`!=`, because two literals with the same lexical form and different datatypes
are different terms and must compare UNEQUAL.

Everything in §3 of that document is correct today and must stay correct, so
much of what follows is a guard against the fix rather than a test of it.

TWO PATHS, AND THE FIRST VERSION OF THIS FILE ONLY TESTED ONE. Comparing two
literals written in the QUERY exercises `emit_expressions`. A `FILTER` against
stored DATA can be pushed down instead, where `filter_pushdown` emits its own
matching SQL — and it matched on `term_text` and `term_type` while ignoring
`datatype_id`, so it returned a custom-typed term for `FILTER(?v = "x")`. The
expression-path fix passed all eight of the original tests while the case that
actually matters stayed broken. The stored-data tests at the end are the ones
that would have caught it.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from rdflib import Literal, URIRef, XSD

from .conftest import skip_no_infra, TEST_SPACE_PREFIX

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]

G = "urn:dt:g"
CUSTOM = "urn:dt:myType"
OTHER = "urn:dt:otherType"
SIDECAR = "http://localhost:7071"


async def _ask(space_impl, space, expr):
    """Evaluate a boolean expression, returning True/False/None(unbound)."""
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql

    q = f'SELECT ?r WHERE {{ BIND(({expr}) AS ?r) }}'
    client = AsyncSidecarClient(SIDECAR)
    try:
        cr = map_compile_response(await client.compile(q))
        assert cr.ok, f"compile failed for {expr}: {cr.error}"
        async with space_impl.db_impl.connection_pool.acquire() as conn:
            gen = await generate_sql(cr, space, conn=conn)
            assert gen.ok, f"generation refused for {expr}: {gen.error}"
            rows = await conn.fetch(gen.sql)
        if not rows:
            return None
        return list(dict(rows[0]).values())[0]
    finally:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close:
            res = close()
            if hasattr(res, "__await__"):
                await res


@pytest_asyncio.fixture(loop_scope="session")
async def dt_space(make_space):
    """A space holding literals with NON-STANDARD datatypes.

    Nothing else in the repository has one: measured 2026-08-23, zero of the 54
    spaces on the test stack and 99 on the host carry a datatype outside the
    standard 40. This fixture exists because the defect cannot be exercised
    without it.
    """
    sid = await make_space(f"{TEST_SPACE_PREFIX}dteq_{uuid.uuid4().hex[:8]}")
    return sid


# --- the defect ------------------------------------------------------------

async def test_different_datatypes_are_not_equal(space_impl, dt_space):
    assert await _ask(space_impl, dt_space,
                      f'"x"^^<{CUSTOM}> = "x"') is False


async def test_different_datatypes_are_unequal_under_ne(space_impl, dt_space):
    """The case a naive `AND datatypes agree` gets backwards."""
    assert await _ask(space_impl, dt_space,
                      f'"x"^^<{CUSTOM}> != "x"') is True


async def test_two_unknown_datatypes_that_differ_are_not_equal(space_impl, dt_space):
    assert await _ask(space_impl, dt_space,
                      f'"x"^^<{CUSTOM}> = "x"^^<{OTHER}>') is False


# --- what must NOT change --------------------------------------------------

async def test_the_same_unknown_datatype_still_compares_by_value(space_impl, dt_space):
    assert await _ask(space_impl, dt_space,
                      f'"x"^^<{CUSTOM}> = "x"^^<{CUSTOM}>') is True
    assert await _ask(space_impl, dt_space,
                      f'"x"^^<{CUSTOM}> = "y"^^<{CUSTOM}>') is False


async def test_cross_type_numeric_equality_survives(space_impl, dt_space):
    """`issues/049` in the other direction: do not break a working lane."""
    assert await _ask(space_impl, dt_space,
                      '"1"^^<http://www.w3.org/2001/XMLSchema#integer> = 1.0') is True


async def test_plain_and_xsd_string_stay_equal(space_impl, dt_space):
    """RDF 1.1 makes a plain literal an xsd:string; they are the same term."""
    assert await _ask(space_impl, dt_space,
                      '"x" = "x"^^<http://www.w3.org/2001/XMLSchema#string>') is True


async def test_booleans_still_compare(space_impl, dt_space):
    assert await _ask(space_impl, dt_space, 'true = true') is True
    assert await _ask(space_impl, dt_space, 'true != false') is True


async def test_datetime_still_compares(space_impl, dt_space):
    XS = "http://www.w3.org/2001/XMLSchema#dateTime"
    assert await _ask(space_impl, dt_space,
                      f'"2020-01-01T00:00:00Z"^^<{XS}> = "2020-01-01T00:00:00Z"^^<{XS}>') is True


# --- the same question against STORED data, which takes the pushdown path ----

@pytest_asyncio.fixture(loop_scope="session")
async def stored(space_impl, dt_space):
    """Three terms sharing one lexical form, differing only by datatype.

    Stored they are distinct — plain has `datatype_id` NULL, `xsd:string` has
    the standard id, a custom datatype gets a NEW ROW in the space's `datatype`
    table (id 41+, which is what makes `datatype_id > 40` an exposure query).
    """
    g = URIRef(G)
    await space_impl.add_rdf_quads_batch_bulk(dt_space, [
        (URIRef("urn:dt:plain"), URIRef("urn:dt:v"), Literal("x"), g),
        (URIRef("urn:dt:xsd"), URIRef("urn:dt:v"), Literal("x", datatype=XSD.string), g),
        (URIRef("urn:dt:custom"), URIRef("urn:dt:v"), Literal("x", datatype=URIRef(CUSTOM)), g)])
    return dt_space


async def _subjects(space_impl, space, flt):
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql

    q = f'SELECT ?s WHERE {{ GRAPH <{G}> {{ ?s <urn:dt:v> ?v }} FILTER({flt}) }}'
    client = AsyncSidecarClient(SIDECAR)
    try:
        cr = map_compile_response(await client.compile(q))
        assert cr.ok, f"compile failed: {cr.error}"
        async with space_impl.db_impl.connection_pool.acquire() as conn:
            gen = await generate_sql(cr, space, conn=conn)
            assert gen.ok, f"generation refused: {gen.error}"
            rows = await conn.fetch(gen.sql)
        return sorted(str(list(dict(r).values())[0]) for r in rows)
    finally:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close:
            res = close()
            if hasattr(res, "__await__"):
                await res


async def test_stored_custom_datatype_does_not_match_a_plain_literal(space_impl, stored):
    """THE case. A plain-literal filter must not return a custom-typed term."""
    got = await _subjects(space_impl, stored, '?v = "x"')
    assert got == ["urn:dt:plain", "urn:dt:xsd"], (
        f"FILTER(?v = \"x\") returned {got}. A term whose datatype is "
        f"<{CUSTOM}> is not the plain literal \"x\" — RDF 1.1 makes plain and "
        f"xsd:string one value, and nothing else (issues/121).")


async def test_stored_custom_datatype_matches_its_own_datatype(space_impl, stored):
    got = await _subjects(space_impl, stored, f'?v = "x"^^<{CUSTOM}>')
    assert got == ["urn:dt:custom"], got


async def test_stored_ne_excludes_only_the_matching_terms(space_impl, stored):
    """`!=` is where a naive guard inverts: the custom term IS unequal to "x"."""
    got = await _subjects(space_impl, stored, '?v != "x"')
    assert got == ["urn:dt:custom"], got
