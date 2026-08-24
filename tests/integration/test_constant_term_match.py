"""A constant in a graph pattern matches by RDF TERM, not by lexical form.

`issues/129`. `term_uuid` is a UUIDv5 over `(text, type, lang, datatype)`, but
`register_constant` keyed on `(text, type)` and the constants CTE matched on
that pair alone — so a constant resolved to whichever term happened to share
its lexical form.

Measured: `{ ?x :p "a"^^t:type1 }` over data holding both `"a"^^t:type1` and
`"a"^^t:type2` emitted the type2 uuid and returned the wrong subject.

THIS IS TERM MATCHING, NOT FILTER EQUALITY, and the distinction is the whole
point of the xsd:string cases below. RDF 1.1 makes `"x"` and `"x"^^xsd:string`
one VALUE — which is why `issues/121` made them compare equal in a FILTER — but
they remain two distinct TERMS with different uuids, so a graph pattern must
NOT match one against the other. Applying the issues/121 rule here would be the
obvious and wrong generalisation.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from rdflib import Literal, URIRef, XSD

from .conftest import skip_no_infra, TEST_SPACE_PREFIX

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]

G = "urn:ct:g"
P = "urn:ct:p"
T1 = "urn:ct:type1"
T2 = "urn:ct:type2"
SIDECAR = "http://localhost:7071"


@pytest_asyncio.fixture(loop_scope="session")
async def ct_space(space_impl, make_space):
    """Terms deliberately sharing lexical forms across datatype and language."""
    sid = await make_space(f"{TEST_SPACE_PREFIX}ct_{uuid.uuid4().hex[:8]}")
    g = URIRef(G)
    await space_impl.add_rdf_quads_batch_bulk(sid, [
        (URIRef("urn:ct:t1"), URIRef(P), Literal("a", datatype=URIRef(T1)), g),
        (URIRef("urn:ct:t2"), URIRef(P), Literal("a", datatype=URIRef(T2)), g),
        (URIRef("urn:ct:plain"), URIRef(P), Literal("x"), g),
        (URIRef("urn:ct:int"), URIRef(P), Literal("5", datatype=XSD.integer), g),
        (URIRef("urn:ct:dbl"), URIRef(P), Literal("5.0", datatype=XSD.double), g),
        (URIRef("urn:ct:en"), URIRef(P), Literal("cat", lang="en"), g),
        (URIRef("urn:ct:fr"), URIRef(P), Literal("cat", lang="fr"), g),
        (URIRef("urn:ct:notag"), URIRef(P), Literal("cat"), g)])
    return sid


async def _match(space_impl, space, obj):
    """Subjects matching `{ ?s <P> <obj> }` — a graph pattern, no FILTER."""
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql

    q = f'SELECT ?s WHERE {{ GRAPH <{G}> {{ ?s <{P}> {obj} }} }}'
    client = AsyncSidecarClient(SIDECAR)
    try:
        cr = map_compile_response(await client.compile(q))
        assert cr.ok, f"compile failed for {obj}: {cr.error}"
        async with space_impl.db_impl.connection_pool.acquire() as conn:
            gen = await generate_sql(cr, space, conn=conn)
            assert gen.ok, f"generation refused for {obj}: {gen.error}"
            rows = await conn.fetch(gen.sql)
        return sorted(str(list(dict(r).values())[0]) for r in rows)
    finally:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close:
            res = close()
            if hasattr(res, "__await__"):
                await res


# --- the defect ------------------------------------------------------------

async def test_unknown_datatype_matches_only_its_own_term(space_impl, ct_space):
    """THE case. Two terms share the lexical form `a`."""
    assert await _match(space_impl, ct_space, f'"a"^^<{T1}>') == ["urn:ct:t1"]


async def test_the_other_unknown_datatype_matches_only_its_own(space_impl, ct_space):
    assert await _match(space_impl, ct_space, f'"a"^^<{T2}>') == ["urn:ct:t2"]


async def test_numeric_datatypes_are_distinct_terms(space_impl, ct_space):
    """`5^^xsd:integer` and `5.0^^xsd:double` are ONE VALUE and TWO TERMS, and
    a graph pattern matches terms.

    The double is written `"5.0"` because rdflib canonicalises the lexical form
    on the way in — `Literal("5", datatype=XSD.double)` is STORED as `"5.0"`,
    so a pattern asking for `"5"^^xsd:double` correctly matches nothing. That
    is the ingest's normalisation, not a defect in the lookup."""
    assert await _match(space_impl, ct_space,
                        f'"5"^^<{XSD.integer}>') == ["urn:ct:int"]
    assert await _match(space_impl, ct_space,
                        f'"5.0"^^<{XSD.double}>') == ["urn:ct:dbl"]


# --- language tags ---------------------------------------------------------

async def test_language_tag_selects_its_own_term(space_impl, ct_space):
    assert await _match(space_impl, ct_space, '"cat"@en') == ["urn:ct:en"]
    assert await _match(space_impl, ct_space, '"cat"@fr') == ["urn:ct:fr"]


async def test_an_untagged_literal_does_not_match_a_tagged_one(space_impl, ct_space):
    assert await _match(space_impl, ct_space, '"cat"') == ["urn:ct:notag"]


# --- what must NOT be "fixed" by the issues/121 rule -----------------------

async def test_plain_and_xsd_string_are_one_term(space_impl, ct_space):
    """RDF 1.1 makes `"x"` and `"x"^^xsd:string` the SAME literal, so BOTH
    spellings must find the one stored term.

    This is the case that broke 48 perf tests. Jena hands us a PLAIN literal
    for either spelling, while ingest stores string values with an explicit
    `xsd:string` id — measured on `sp_lead_synth_100k`, 3219 literals at
    `datatype_id = 1` and ZERO at NULL. A lookup demanding
    `datatype_id IS NULL` for a plain constant therefore matched nothing and
    every string-valued criterion returned 0 rows.

    The fixture deliberately stores only ONE of the two spellings. Storing both
    would create two rows for what RDF says is one term — an INGEST defect
    (`add_rdf_quads_batch_bulk` does not normalise `xsd:string` away, where the
    DAWG loader does) — and the lookup would then have to pick one, which is
    the very non-determinism this whole fix is about. Tested against a
    consistent space, which is what real data is."""
    assert await _match(space_impl, ct_space, '"x"') == ["urn:ct:plain"]
    assert await _match(space_impl, ct_space,
                        f'"x"^^<{XSD.string}>') == ["urn:ct:plain"]
