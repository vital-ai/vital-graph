"""`langMatches` must do RFC 4647 basic filtering, not string equality.

`issues/120`. `FILTER(langMatches(lang(?x), "en"))` is the standard way to ask
for "English, any region", and it returned NOTHING for `en-US`, `en-GB`,
`en-AU` — an empty result set rather than an error, which is the category of
defect this repository keeps finding late.

SPARQL 1.1 defines the function in terms of RFC 4647 basic filtering: a range
matches a tag when it equals the tag, or is a prefix of it ENDING AT A SUBTAG
BOUNDARY. The emitter implemented only the first half.

The boundary is the whole difficulty, and it is why a bare `LIKE b || '%'`
would be a different bug rather than a fix: `enm` is Middle English, a distinct
language from `en`, and `en-U` is not a subtag of `en-US`. Both directions are
pinned below.

Two arms were already correct — the `*` wildcard and case-insensitivity — so
several of these tests guard the fix rather than test it.

Unlike `issues/121`, the pushdown is NOT a second path here: `filter_pushdown`
has no `langMatches` arm, so every case below reaches `emit_expressions`. That
was checked before writing rather than assumed, because assuming it is exactly
what made the first attempt at `issues/121` miss the bug it was fixing.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from rdflib import Literal, URIRef

from .conftest import skip_no_infra, TEST_SPACE_PREFIX

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]

G = "urn:lm:g"
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
async def lm_space(make_space):
    return await make_space(f"{TEST_SPACE_PREFIX}lm_{uuid.uuid4().hex[:8]}")


# --- the defect ------------------------------------------------------------

async def test_region_subtag_matches_the_bare_language(space_impl, lm_space):
    """THE case. `en-US` is English."""
    assert await _ask(space_impl, lm_space,
                      'langMatches("en-US", "en")') is True


async def test_every_region_of_english_matches(space_impl, lm_space):
    for tag in ("en-GB", "en-AU", "en-CA"):
        assert await _ask(space_impl, lm_space,
                          f'langMatches("{tag}", "en")') is True, tag


async def test_extended_subtags_match(space_impl, lm_space):
    """Basic filtering is a prefix test, so depth beyond one subtag matches."""
    assert await _ask(space_impl, lm_space,
                      'langMatches("en-US-x-private", "en")') is True
    assert await _ask(space_impl, lm_space,
                      'langMatches("en-US-x-private", "en-US")') is True


# --- the boundary, which a naive LIKE would get wrong -----------------------

async def test_a_longer_language_is_not_a_region_of_a_shorter_one(space_impl, lm_space):
    """`enm` is Middle English. A bare `LIKE 'en%'` would match it."""
    assert await _ask(space_impl, lm_space,
                      'langMatches("enm", "en")') is False


async def test_a_partial_subtag_does_not_match(space_impl, lm_space):
    """`en-U` is not a prefix of `en-US` at a subtag boundary."""
    assert await _ask(space_impl, lm_space,
                      'langMatches("en-US", "en-U")') is False


async def test_prefix_direction_is_not_reversed(space_impl, lm_space):
    """The RANGE is the prefix, not the tag. `en` does not match range `en-US`."""
    assert await _ask(space_impl, lm_space,
                      'langMatches("en", "en-US")') is False


# --- arms that were already correct, guarded against the fix ---------------

async def test_exact_match_still_matches(space_impl, lm_space):
    assert await _ask(space_impl, lm_space, 'langMatches("en", "en")') is True


async def test_case_insensitive_both_sides(space_impl, lm_space):
    assert await _ask(space_impl, lm_space, 'langMatches("EN", "en")') is True
    assert await _ask(space_impl, lm_space, 'langMatches("EN-us", "en-US")') is True
    assert await _ask(space_impl, lm_space, 'langMatches("en-US", "EN")') is True


async def test_a_different_language_does_not_match(space_impl, lm_space):
    assert await _ask(space_impl, lm_space, 'langMatches("de", "en")') is False
    assert await _ask(space_impl, lm_space, 'langMatches("de-DE", "en")') is False


async def test_wildcard_matches_any_tag(space_impl, lm_space):
    assert await _ask(space_impl, lm_space, 'langMatches("en-GB", "*")') is True
    assert await _ask(space_impl, lm_space, 'langMatches("de", "*")') is True


async def test_wildcard_does_not_match_an_absent_tag(space_impl, lm_space):
    """`*` means "has some tag", so an untagged literal fails it."""
    assert await _ask(space_impl, lm_space, 'langMatches("", "*")') is False


async def test_an_absent_tag_matches_nothing(space_impl, lm_space):
    assert await _ask(space_impl, lm_space, 'langMatches("", "en")') is False


async def test_range_supplied_by_a_variable(space_impl, lm_space):
    """`b` is an expression, not always a literal — the concatenation must
    still work when the range arrives through a variable."""
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql

    q = ('SELECT ?r WHERE { BIND("en" AS ?range) '
         'BIND((langMatches("en-US", ?range)) AS ?r) }')
    client = AsyncSidecarClient(SIDECAR)
    try:
        cr = map_compile_response(await client.compile(q))
        assert cr.ok, cr.error
        async with space_impl.db_impl.connection_pool.acquire() as conn:
            gen = await generate_sql(cr, lm_space, conn=conn)
            assert gen.ok, gen.error
            rows = await conn.fetch(gen.sql)
        assert rows and list(dict(rows[0]).values())[0] is True
    finally:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close:
            res = close()
            if hasattr(res, "__await__"):
                await res


async def test_wildcard_supplied_by_a_variable(space_impl, lm_space):
    """A range of `*` is only recognisable at runtime when it arrives through a
    variable. Found while fixing the prefix bug, not part of `issues/120` as
    filed: the wildcard arm tested the emitted SQL for the literal `'*'`, so
    `langMatches(?t, ?r)` with ?r = "*" answered FALSE for every tag."""
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql

    async def ask(tag):
        q = (f'SELECT ?r WHERE {{ BIND("*" AS ?range) '
             f'BIND((langMatches("{tag}", ?range)) AS ?r) }}')
        client = AsyncSidecarClient(SIDECAR)
        try:
            cr = map_compile_response(await client.compile(q))
            assert cr.ok, cr.error
            async with space_impl.db_impl.connection_pool.acquire() as conn:
                gen = await generate_sql(cr, lm_space, conn=conn)
                assert gen.ok, gen.error
                rows = await conn.fetch(gen.sql)
            return list(dict(rows[0]).values())[0] if rows else None
        finally:
            close = getattr(client, "aclose", None) or getattr(client, "close", None)
            if close:
                res = close()
                if hasattr(res, "__await__"):
                    await res

    assert await ask("en-US") is True
    assert await ask("de") is True
    assert await ask("") is False, "`*` means \"has some tag\""


# --- the same question against STORED data ---------------------------------

@pytest_asyncio.fixture(loop_scope="session")
async def tagged(space_impl, lm_space):
    g = URIRef(G)
    await space_impl.add_rdf_quads_batch_bulk(lm_space, [
        (URIRef("urn:lm:en"), URIRef("urn:lm:v"), Literal("c", lang="en"), g),
        (URIRef("urn:lm:enus"), URIRef("urn:lm:v"), Literal("c", lang="en-US"), g),
        (URIRef("urn:lm:engb"), URIRef("urn:lm:v"), Literal("c", lang="en-GB"), g),
        (URIRef("urn:lm:enm"), URIRef("urn:lm:v"), Literal("c", lang="enm"), g),
        (URIRef("urn:lm:de"), URIRef("urn:lm:v"), Literal("c", lang="de"), g),
        (URIRef("urn:lm:none"), URIRef("urn:lm:v"), Literal("c"), g)])
    return lm_space


async def _subjects(space_impl, space, flt):
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql

    q = f'SELECT ?s WHERE {{ GRAPH <{G}> {{ ?s <urn:lm:v> ?v }} FILTER({flt}) }}'
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


async def test_stored_english_any_region(space_impl, tagged):
    """THE query from the issue, against data. `enm`, `de` and the untagged
    literal must all stay out."""
    got = await _subjects(space_impl, tagged, 'langMatches(lang(?v), "en")')
    assert got == ["urn:lm:en", "urn:lm:engb", "urn:lm:enus"], (
        f'FILTER(langMatches(lang(?v), "en")) returned {got} — "English, any '
        f'region" must include en-US and en-GB and exclude enm (issues/120).')


async def test_stored_wildcard_returns_every_tagged_literal(space_impl, tagged):
    got = await _subjects(space_impl, tagged, 'langMatches(lang(?v), "*")')
    assert got == ["urn:lm:de", "urn:lm:en", "urn:lm:engb", "urn:lm:enm",
                   "urn:lm:enus"], got


async def test_stored_exact_region(space_impl, tagged):
    got = await _subjects(space_impl, tagged, 'langMatches(lang(?v), "en-US")')
    assert got == ["urn:lm:enus"], got
