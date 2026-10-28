"""A type-anchored slot query does work proportional to its answer (`issues/293`).

The shape, the most common KG query there is:

    ?d   hasKGEntityType <T> .
    ?s   hasKGGraphURI   ?d ;
         hasKGSlotType   <S> ;
         hasTextSlotValue ?v .

PostgreSQL estimates `hasKGGraphURI`'s fan-out per entity at ~10 (a per-column
statistic cannot see that one predicate's objects are each referenced ~1,000
times), so it drives from the entities of type T and expands every member of
every entity's graph before the slot type filters them. On production's
underwriting space: 1,159 entities, ~1,088 members each, 1,261,467 rows for
9,318 kept, 5-16 s per dashboard query.

The generator now owns that decision (the slot group as a materialised CTE,
the cardinality model's join order). This file asserts the RATIO of the
busiest plan node's loops to the rows returned, not a time, under the
executor's own session settings — and asserts the fixture is hard enough to
mean something: with both rewrites switched off, the same query on the same
data must be disproportionate. Without that control a ratio test passes on
any fixture small enough for PostgreSQL to get right by itself.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from rdflib import Literal, URIRef

from .conftest import skip_no_infra, SIDECAR_URL

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

KG = "http://vital.ai/ontology/haley-ai-kg#"
EX = "http://example.org/typeanchored/"

HAS_ENTITY_TYPE = URIRef(f"{KG}hasKGEntityType")
HAS_GRAPH_URI = URIRef(f"{KG}hasKGGraphURI")
HAS_SLOT_TYPE = URIRef(f"{KG}hasKGSlotType")
HAS_TEXT_VALUE = URIRef(f"{KG}hasTextSlotValue")
HAS_NAME = URIRef("http://vital.ai/ontology/vital-core#hasName")

ENTITY_TYPE = URIRef(f"{EX}type/Decision")
SLOT_TYPE = URIRef(f"{EX}slot/Reason")
OTHER_SLOT_TYPES = [URIRef(f"{EX}slot/Other{k}") for k in range(10)]

# Wide graphs, the production shape in miniature: each entity's graph has
# MEMBERS members and ONE of them is the queried slot type. Driven from the
# type, the plan probes N_ENTITIES x MEMBERS rows to keep N_ENTITIES.
N_ENTITIES = 60
MEMBERS = 300

# The loose bound for the fixed plan, and the bound the unfixed one must
# exceed. Measured on this fixture 2026-10-28 (vg test stack): as shipped,
# 60 loops for 60 rows (ratio 1.0; slot_group_cte and model_join_order fired);
# both rewrites off, 18,000 loops = 60 entities x 300 members (ratio 300).
MAX_RATIO = 20.0
MIN_RATIO_UNFIXED = 100.0


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def wide_space(make_space, space_impl):
    space_id = await make_space()
    graph = URIRef(f"urn:{space_id}")
    backend = (space_impl.get_db_space_impl()
               if hasattr(space_impl, "get_db_space_impl") else space_impl)
    quads = []
    for i in range(N_ENTITIES):
        d = URIRef(f"{EX}decision/{i}")
        quads.append((d, HAS_ENTITY_TYPE, ENTITY_TYPE, graph))
        for m in range(MEMBERS):
            s = URIRef(f"{EX}decision/{i}/member/{m}")
            quads.append((s, HAS_GRAPH_URI, d, graph))
            if m == 0:
                quads += [(s, HAS_SLOT_TYPE, SLOT_TYPE, graph),
                          (s, HAS_TEXT_VALUE, Literal(f"reason {i}"), graph)]
            else:
                # Each member carries its own value, as real slots do. This is
                # what makes PostgreSQL wrong: with most object values
                # referenced once or twice, its per-object fan-out estimate
                # for `hasKGGraphURI` falls to a few rows where MEMBERS arrive.
                # Without it the decisions dominate the object column, the
                # estimate is right, and the fixture is easy (measured: 60
                # loops for 60 rows with every rewrite off).
                quads += [(s, HAS_SLOT_TYPE, OTHER_SLOT_TYPES[m % 10], graph),
                          (s, HAS_TEXT_VALUE, Literal(f"value {i}-{m}"), graph),
                          (s, HAS_NAME, Literal(f"name {i}-{m}"), graph)]
    await backend.add_rdf_quads_batch(space_id, quads)

    # Statistics, as maintenance builds them: the model prices from them, and
    # without them every decision keeps today's behaviour.
    from vitalgraph.db.sparql_sql.generator import invalidate_stats_cache
    from vitalgraph.db.sparql_sql.resync_all import resync_all_auxiliary_tables
    pool = backend._db._pool if hasattr(backend, "_db") else space_impl._db._pool
    async with pool.acquire() as conn:
        await resync_all_auxiliary_tables(conn, space_id)
    invalidate_stats_cache(space_id)
    return space_id


def _query(space_id: str) -> str:
    return f"""
SELECT ?d ?v WHERE {{ GRAPH <urn:{space_id}> {{
  ?d <{HAS_ENTITY_TYPE}> <{ENTITY_TYPE}> .
  ?s <{HAS_GRAPH_URI}> ?d ;
     <{HAS_SLOT_TYPE}> <{SLOT_TYPE}> ;
     <{HAS_TEXT_VALUE}> ?v .
}} }}"""


async def _generate(conn, space_id: str):
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql

    client = AsyncSidecarClient(SIDECAR_URL)
    try:
        raw = await client.compile(_query(space_id))
    finally:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close:
            res = close()
            if hasattr(res, "__await__"):
                await res
    cr = map_compile_response(raw)
    assert cr.ok, f"SPARQL failed to compile: {cr.error}"
    gen = await generate_sql(cr, space_id, conn=conn)
    assert gen.ok and gen.sql, f"generation failed: {gen.error}"
    return gen


async def _shape(conn, gen):
    """Rows and plan shape under the executor's own session settings."""
    from vitalgraph.db.sparql_sql.plan_shape import analyse
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _apply_join_order

    async with conn.transaction():
        await _apply_join_order(conn, gen)
        rows = await conn.fetch(gen.sql)
        plan = await conn.fetch("EXPLAIN (ANALYZE, BUFFERS) " + gen.sql)
    return sorted(tuple(r) for r in rows), analyse([r[0] for r in plan],
                                                   rows_returned=len(rows))


class TestTypeAnchoredSlotQuery:

    async def test_work_is_proportional_to_the_answer(self, wide_space, pg_conn):
        gen = await _generate(pg_conn, wide_space)
        rows, shape = await _shape(pg_conn, gen)
        assert len(rows) == N_ENTITIES, (
            f"expected one row per entity, got {len(rows)}; the ratio below "
            f"would be meaningless")
        assert shape.ratio < MAX_RATIO, (
            f"{shape.max_loops:,} loops for {shape.rows} rows (ratio "
            f"{shape.ratio:.1f}, limit {MAX_RATIO}): the plan expands every "
            f"member of every entity's graph again. Busiest node: "
            f"{shape.busiest[0]['node'] if shape.busiest else 'n/a'}. "
            f"fired={(gen.plan_decisions or {}).get('fired')}")

    async def test_the_fixture_is_hard_without_the_rewrites(
            self, wide_space, pg_conn, monkeypatch):
        """The control: same data, both rewrites off, PostgreSQL left to its
        own estimates. It must drive through the members, or the test above
        proves nothing about them. Also: the answer is the same."""
        from vitalgraph.db.sparql_sql import bgp_cardinality, slot_group_cte

        fixed_rows, _ = await _shape(pg_conn, await _generate(pg_conn, wide_space))

        monkeypatch.setattr(slot_group_cte, "find_groups", lambda *a, **k: [])
        monkeypatch.setattr(bgp_cardinality, "enforced_order", lambda *a, **k: None)
        rows, shape = await _shape(pg_conn, await _generate(pg_conn, wide_space))

        assert rows == fixed_rows, "the rewrites changed the answer"
        assert shape.ratio > MIN_RATIO_UNFIXED, (
            f"without the rewrites the plan ran only {shape.max_loops:,} loops "
            f"for {shape.rows} rows (ratio {shape.ratio:.1f}): the fixture is "
            f"no longer hard, so the proportionality test above is vacuous. "
            f"Widen the graphs.")
