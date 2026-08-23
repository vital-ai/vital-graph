"""Arithmetic reports the datatype XSD promotion says it does.

DAWG `sparql10/type-promotion`, 22 cases, all of the shape

    ASK { t:short1 rdf:value ?l . t:short1 rdf:value ?r .
          FILTER ( datatype(?l + ?r) = xsd:integer ) }

Two separate defects sit behind that one query.

**The rule.** `infer_expr_type` types `add`/`subtract`/`multiply` by
propagating the FIRST argument's datatype. XSD promotes both operands to their
least common type up `integer -> decimal -> float -> double`, with every
bounded integer subtype (`short`, `byte`, `int`, `long`, `unsignedX`, ...)
collapsing to `xsd:integer`. "First arg wins" is right only when both operands
are the same unbounded type.

**The reach.** `datatype()` never consulted that inference at all — it handled
variables, constants and `STRDT`, then returned NULL. So `datatype(?l + ?r)`
was unbound no matter what the rule said.

The computed VALUE is not at stake here; arithmetic is evaluated in PostgreSQL
NUMERIC either way. Only the reported datatype moves — which is also why this
can change results for a caller relying on the old typing, and why the
`BIND` cases below are pinned alongside the FILTER ones.
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
X = str(XSD)


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
async def tp_space(make_space):
    return await make_space(f"{TEST_SPACE_PREFIX}tp_{uuid.uuid4().hex[:8]}")


def _lit(v, dt):
    return f'"{v}"^^<{X}{dt}>'


async def _dt_of_sum(space_impl, space, dt_a, dt_b, a="1", b="1"):
    return await _val(space_impl, space,
                      f'datatype({_lit(a, dt_a)} + {_lit(b, dt_b)})')


# --- the bounded integer subtypes all collapse to xsd:integer --------------

@pytest.mark.parametrize("sub", ["short", "byte", "int", "long",
                                 "unsignedShort", "unsignedByte",
                                 "unsignedInt", "nonNegativeInteger"])
async def test_two_integer_subtypes_promote_to_integer(space_impl, tp_space, sub):
    """THE case. `short + short` is `xsd:integer`, not `xsd:short`."""
    got = await _dt_of_sum(space_impl, tp_space, sub, sub)
    assert got == f"{X}integer", f"{sub} + {sub} -> {got}"


async def test_mixed_integer_subtypes_promote_to_integer(space_impl, tp_space):
    assert await _dt_of_sum(space_impl, tp_space, "int", "long") == f"{X}integer"
    assert await _dt_of_sum(space_impl, tp_space, "short", "byte") == f"{X}integer"


# --- the lattice: integer < decimal < float < double ----------------------

async def test_integer_and_decimal_promote_to_decimal(space_impl, tp_space):
    assert await _dt_of_sum(space_impl, tp_space, "integer", "decimal") == f"{X}decimal"
    assert await _dt_of_sum(space_impl, tp_space, "decimal", "integer") == f"{X}decimal"


async def test_decimal_and_float_promote_to_float(space_impl, tp_space):
    assert await _dt_of_sum(space_impl, tp_space, "decimal", "float") == f"{X}float"
    assert await _dt_of_sum(space_impl, tp_space, "float", "decimal") == f"{X}float"


async def test_float_and_double_promote_to_double(space_impl, tp_space):
    assert await _dt_of_sum(space_impl, tp_space, "float", "double") == f"{X}double"
    assert await _dt_of_sum(space_impl, tp_space, "double", "float") == f"{X}double"


async def test_integer_and_double_promote_to_double(space_impl, tp_space):
    """Skipping ranks must not lose the promotion — this is the case
    'first arg wins' gets most visibly wrong."""
    assert await _dt_of_sum(space_impl, tp_space, "integer", "double") == f"{X}double"
    assert await _dt_of_sum(space_impl, tp_space, "double", "integer") == f"{X}double"


async def test_same_unbounded_type_is_unchanged(space_impl, tp_space):
    """The cases 'first arg wins' happened to get right, which must stay right."""
    for dt in ("integer", "decimal", "float", "double"):
        assert await _dt_of_sum(space_impl, tp_space, dt, dt) == f"{X}{dt}", dt


# --- subtract and multiply share the rule ---------------------------------

async def test_subtract_and_multiply_promote_the_same_way(space_impl, tp_space):
    for op in ("-", "*"):
        got = await _val(space_impl, tp_space,
                         f'datatype({_lit("2", "short")} {op} {_lit("1", "short")})')
        assert got == f"{X}integer", f"{op} -> {got}"


# --- divide is NOT the same rule ------------------------------------------

async def test_integer_division_is_decimal(space_impl, tp_space):
    """XSD: integer / integer is decimal, not integer."""
    got = await _val(space_impl, tp_space,
                     f'datatype({_lit("1", "integer")} / {_lit("2", "integer")})')
    assert got == f"{X}decimal", got


async def test_double_division_stays_double(space_impl, tp_space):
    """The floor is decimal, not the answer. Hardcoding decimal makes this
    wrong for the float and double cases."""
    got = await _val(space_impl, tp_space,
                     f'datatype({_lit("1", "double")} / {_lit("2", "double")})')
    assert got == f"{X}double", got


async def test_float_division_stays_float(space_impl, tp_space):
    got = await _val(space_impl, tp_space,
                     f'datatype({_lit("1", "float")} / {_lit("2", "float")})')
    assert got == f"{X}float", got


# --- the value is not what changes ----------------------------------------

async def test_the_computed_value_is_unaffected(space_impl, tp_space):
    got = await _val(space_impl, tp_space, f'{_lit("2", "short")} + {_lit("3", "short")}')
    assert got is not None and float(got) == 5.0, got
