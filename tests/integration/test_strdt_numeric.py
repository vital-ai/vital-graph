"""`STRDT` must produce a value the numeric lane will use.

`datatypes_and_language_tags.md` §4.4:

    STRDT("1", xsd:integer) + 1     spec: 2     actual: NULL

`STRDT` is the standard way to type a value computed in the query, so a
constructed literal that arithmetic cannot see makes the function close to
useless. The emitter returned the LEXICAL form and dropped the datatype, so
nothing downstream could tell `STRDT("1", xsd:integer)` from the string "1".

Two halves, and the second is the one that generalises: the result has to
BE numeric in the emitted SQL, and it has to be RECOGNISED as numeric by
`_is_numeric_expr`, which is what decides whether arithmetic takes the numeric
lane at all. Fixing either alone leaves the other wrong.

An ill-typed lexical form (`STRDT("abc", xsd:integer)`) is a type error, i.e.
unbound — NOT a cast failure. Casting without a guard would raise and take the
whole query with it, which is worse than the bug.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from rdflib import XSD

from .conftest import skip_no_infra, TEST_SPACE_PREFIX

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]

SIDECAR = "http://localhost:7071"
INT = str(XSD.integer)
DBL = str(XSD.double)
STR = str(XSD.string)


async def _val(space_impl, space, expr):
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
async def sd_space(make_space):
    return await make_space(f"{TEST_SPACE_PREFIX}strdt_{uuid.uuid4().hex[:8]}")


# --- the defect ------------------------------------------------------------

async def test_arithmetic_on_a_constructed_integer(space_impl, sd_space):
    """THE case from the planning document."""
    got = await _val(space_impl, sd_space, f'STRDT("1", <{INT}>) + 1')
    assert got is not None, "STRDT result never reached the numeric lane"
    assert float(got) == 2.0, got


async def test_arithmetic_on_a_constructed_double(space_impl, sd_space):
    got = await _val(space_impl, sd_space, f'STRDT("1.5", <{DBL}>) * 2')
    assert got is not None and float(got) == 3.0, got


async def test_a_constructed_number_compares_as_a_number(space_impl, sd_space):
    assert await _val(space_impl, sd_space, f'STRDT("1", <{INT}>) = 1') is True


async def test_datatype_of_a_constructed_literal(space_impl, sd_space):
    """The datatype is the whole point of STRDT; reporting it unbound means
    the constructed literal is indistinguishable from a plain string."""
    assert await _val(space_impl, sd_space,
                      f'datatype(STRDT("1", <{INT}>))') == INT


# --- what must NOT happen --------------------------------------------------

async def test_an_ill_typed_lexical_form_is_unbound_not_an_error(space_impl, sd_space):
    """A bare CAST would raise and fail the whole query."""
    assert await _val(space_impl, sd_space, f'STRDT("abc", <{INT}>) + 1') is None


async def test_a_constructed_string_is_still_a_string(space_impl, sd_space):
    assert await _val(space_impl, sd_space,
                      f'datatype(STRDT("abc", <{STR}>))') == STR


async def test_a_constructed_string_does_not_become_numeric(space_impl, sd_space):
    """`STRDT("1", xsd:string)` is the STRING "1", so arithmetic on it is a
    type error — the numeric lane must key on the target datatype, not on
    whether the lexical form happens to parse."""
    assert await _val(space_impl, sd_space, f'STRDT("1", <{STR}>) + 1') is None
