"""`datatype()` must answer for every literal, including plain ones.

`datatypes_and_language_tags.md` §4.3. RDF 1.1 abolished the untyped literal:
a plain literal HAS datatype `xsd:string`, and a language-tagged one has
`rdf:langString`. We returned unbound for both, so

    FILTER(datatype(?x) = xsd:string)

dropped exactly the rows it should keep — a silently wrong answer, the same
signature as `issues/120` and `issues/121`.

Measured before writing: the stored-data path returned `xsd:integer` and an
explicit `xsd:string` correctly and only missed the plain literal, while the
INLINE path missed every case. Two different causes in one emitter arm, and
the second is not in the planning document — Jena canonicalises
`"abc"^^xsd:string` to a plain literal, so a constant never had a datatype to
report.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from rdflib import Literal, URIRef, XSD

from .conftest import skip_no_infra, TEST_SPACE_PREFIX

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]

G = "urn:da:g"
SIDECAR = "http://localhost:7071"
XSD_STRING = str(XSD.string)
RDF_LANGSTRING = "http://www.w3.org/1999/02/22-rdf-syntax-ns#langString"


async def _val(space_impl, space, expr):
    """Evaluate a scalar expression, returning its value or None."""
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
        return list(dict(rows[0]).values())[0] if rows else None
    finally:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close:
            res = close()
            if hasattr(res, "__await__"):
                await res


@pytest_asyncio.fixture(loop_scope="session")
async def da_space(space_impl, make_space):
    sid = await make_space(f"{TEST_SPACE_PREFIX}dtacc_{uuid.uuid4().hex[:8]}")
    g = URIRef(G)
    await space_impl.add_rdf_quads_batch_bulk(sid, [
        (URIRef("urn:da:plain"), URIRef("urn:da:v"), Literal("abc"), g),
        (URIRef("urn:da:str"), URIRef("urn:da:v"),
         Literal("abc", datatype=XSD.string), g),
        (URIRef("urn:da:int"), URIRef("urn:da:v"), Literal(7), g),
        (URIRef("urn:da:lang"), URIRef("urn:da:v"),
         Literal("abc", lang="en"), g),
        (URIRef("urn:da:uri"), URIRef("urn:da:v"), URIRef("urn:da:thing"), g)])
    return sid


async def _datatypes(space_impl, space):
    """subject -> datatype(?v), over stored data."""
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql

    q = (f'SELECT ?s (datatype(?v) AS ?d) WHERE '
         f'{{ GRAPH <{G}> {{ ?s <urn:da:v> ?v }} }}')
    client = AsyncSidecarClient(SIDECAR)
    try:
        cr = map_compile_response(await client.compile(q))
        assert cr.ok, cr.error
        async with space_impl.db_impl.connection_pool.acquire() as conn:
            gen = await generate_sql(cr, space, conn=conn)
            assert gen.ok, gen.error
            rows = await conn.fetch(gen.sql)
        out = {}
        for r in rows:
            vals = [v for v in dict(r).values() if v is not None]
            subj = next(v for v in vals if str(v).startswith("urn:da:"))
            dt = next((v for v in vals
                       if str(v).startswith("http") and v != subj), None)
            out[str(subj)] = str(dt) if dt else None
        return out
    finally:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close:
            res = close()
            if hasattr(res, "__await__"):
                await res


# --- stored data -----------------------------------------------------------

async def test_stored_plain_literal_is_an_xsd_string(space_impl, da_space):
    """THE case. RDF 1.1 has no untyped literal."""
    got = await _datatypes(space_impl, da_space)
    assert got["urn:da:plain"] == XSD_STRING, got


async def test_stored_language_tagged_literal_is_rdf_langstring(space_impl, da_space):
    """A lang tag stores datatype NULL, but its datatype is rdf:langString."""
    got = await _datatypes(space_impl, da_space)
    assert got["urn:da:lang"] == RDF_LANGSTRING, got


async def test_stored_typed_literals_are_unchanged(space_impl, da_space):
    """These were already right and must stay right."""
    got = await _datatypes(space_impl, da_space)
    assert got["urn:da:int"] == str(XSD.integer), got
    assert got["urn:da:str"] == XSD_STRING, got


async def test_a_uri_has_no_datatype(space_impl, da_space):
    """`datatype()` of a non-literal is a type error, i.e. unbound — NOT
    xsd:string. Coalescing without checking the term type would claim every
    URI is a string."""
    got = await _datatypes(space_impl, da_space)
    assert got.get("urn:da:uri") is None, got


async def test_filter_on_xsd_string_keeps_the_plain_literal(space_impl, da_space):
    """The consequence the planning document names."""
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql

    q = (f'SELECT ?s WHERE {{ GRAPH <{G}> {{ ?s <urn:da:v> ?v }} '
         f'FILTER(datatype(?v) = <{XSD_STRING}>) }}')
    client = AsyncSidecarClient(SIDECAR)
    try:
        cr = map_compile_response(await client.compile(q))
        assert cr.ok, cr.error
        async with space_impl.db_impl.connection_pool.acquire() as conn:
            gen = await generate_sql(cr, da_space, conn=conn)
            assert gen.ok, gen.error
            rows = await conn.fetch(gen.sql)
        got = sorted(str(list(dict(r).values())[0]) for r in rows)
    finally:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close:
            res = close()
            if hasattr(res, "__await__"):
                await res
    assert got == ["urn:da:plain", "urn:da:str"], (
        f"got {got} — a plain literal IS an xsd:string in RDF 1.1")


# --- inline literals, the half the planning document missed ----------------

async def test_inline_plain_literal_is_an_xsd_string(space_impl, da_space):
    assert await _val(space_impl, da_space, 'datatype("abc")') == XSD_STRING


async def test_inline_explicitly_typed_string(space_impl, da_space):
    """Jena canonicalises this to a plain literal, so it reaches the emitter
    with no datatype at all — same arm, same answer."""
    assert await _val(space_impl, da_space,
                      f'datatype("abc"^^<{XSD_STRING}>)') == XSD_STRING


async def test_inline_typed_literal_keeps_its_datatype(space_impl, da_space):
    assert await _val(space_impl, da_space,
                      f'datatype("7"^^<{XSD.integer}>)') == str(XSD.integer)


async def test_inline_datatype_equals_xsd_string(space_impl, da_space):
    assert await _val(space_impl, da_space,
                      f'(datatype("abc") = <{XSD_STRING}>)') is True
