"""A query must do work proportional to its ANSWER, not to the corpus.

The `issues/178` reference CONSTRUCT ran 285,348 loops to return 425 rows — a
ratio of 671. Fixed, it runs 341 loops for the same 425 rows: 0.8. Six shape
rewrites were implemented, measured and reverted before the one that worked,
and **every failed attempt left the ratio near 671 while the successful one
took it to 0.8.** Wall-clock did not separate them; two of the failures looked
like improvements on a warm cache.

So this file asserts the RATIO, not a duration. A timing test on this shape
would be flaky on a busy machine and would not have caught any of the six.

It also asserts that `rewrite_merge_bgp` FIRES. That rewrite declined silently
twice on the query it was written for, while `rewrite_distribute_union` above it
fired and duplicated the pattern — all of the cost, none of the benefit, and
invisible until someone read the generated SQL. A rewrite that is wired is not
the same as a rewrite that runs.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from rdflib import RDF, URIRef, Literal

from .conftest import skip_no_infra, SIDECAR_URL

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

KG = "http://vital.ai/ontology/haley-ai-kg#"
CORE = "http://vital.ai/ontology/vital-core#"
EX = "http://example.org/proportional/"

VITALTYPE = URIRef(f"{CORE}vitaltype")
HAS_EDGE_SOURCE = URIRef(f"{CORE}hasEdgeSource")
HAS_EDGE_DEST = URIRef(f"{CORE}hasEdgeDestination")
HAS_SLOT_TYPE = URIRef(f"{KG}hasKGSlotType")
HAS_ENTITY_SLOT_VALUE = URIRef(f"{KG}hasEntitySlotValue")
HAS_DESCRIPTION = URIRef(f"{KG}hasKGraphDescription")
EDGE_HAS_SLOT = URIRef(f"{KG}Edge_hasKGSlot")
KG_ENTITY = URIRef(f"{KG}KGEntity")
KG_FRAME = URIRef(f"{KG}KGFrame")

# Roles as DATA. Naming them in the SQL is what `issues/183` retired.
SRC_ROLE = URIRef("urn:test:prop:sourceEntity")
DST_ROLE = URIRef("urn:test:prop:destEntity")

# The ratio the reference query measured after the fix was 0.8, and 671 before.
# 50 is deliberately loose: this guards against a REGRESSION IN KIND, not a
# small drift, and a tight bound on shared infrastructure is a flaky test.
MAX_RATIO = 50.0

# Enough frames that an unanchored traversal is visibly disproportionate, AND
# enough rows that the term table is not small enough to seq-scan.
#
# At 5 frames the wrong plan walks a handful of rows either way and the test
# passes however broken the plan is — the trap `issues/178` calls a fixture too
# easy to have an answer. At 60 the opposite bit: `{space}_term` was small
# enough that PostgreSQL correctly chose a Seq Scan inside a nested loop, and
# the RATIO then measured table size rather than plan quality (120 loops for 2
# rows, ratio 60, on a perfectly good plan).
N_FRAMES = 400


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def proportional_space(make_space):
    # NO fixed name. `make_space` is unique-by-default and only collides when a
    # caller supplies one — and a fixed name SURVIVES an interrupted run, so
    # the next run fails with `SpaceAlreadyExistsError` forever rather than
    # once. That is what happened here after a suite was stopped mid-flight.
    return await make_space()


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def seeded(proportional_space, space_impl):
    """Frames with a source and destination slot; ONE entity matches the text."""
    graph = URIRef(f"urn:{proportional_space}")
    # The DB-level impl, as `test_frame_entity_collapse` does: the manager-level
    # wrapper does not expose the batch insert these fixtures need.
    backend = (space_impl.get_db_space_impl()
               if hasattr(space_impl, "get_db_space_impl") else space_impl)
    quads = []
    for i in range(N_FRAMES):
        frame = URIRef(f"{EX}frame/{i}")
        # BOTH: `a` in SPARQL is rdf:type, while the derived tables are built
        # from vitaltype. Seeding only one makes the query match nothing.
        quads += [(frame, VITALTYPE, KG_FRAME, graph),
                  (frame, RDF.type, KG_FRAME, graph)]
        for tag, role in (("src", SRC_ROLE), ("dst", DST_ROLE)):
            slot = URIRef(f"{EX}slot/{tag}/{i}")
            edge = URIRef(f"{EX}edge/{tag}/{i}")
            entity = URIRef(f"{EX}entity/{tag}/{i}")
            # Exactly one entity carries the term the query filters on, so the
            # anchor is genuinely selective and the traversal is not.
            desc = "the needle description" if i == 7 else f"filler {i}"
            quads += [
                (edge, VITALTYPE, EDGE_HAS_SLOT, graph),
                (edge, HAS_EDGE_SOURCE, frame, graph),
                (edge, HAS_EDGE_DEST, slot, graph),
                (slot, HAS_SLOT_TYPE, role, graph),
                (slot, HAS_ENTITY_SLOT_VALUE, entity, graph),
                (entity, VITALTYPE, KG_ENTITY, graph),
                (entity, RDF.type, KG_ENTITY, graph),
                (entity, HAS_DESCRIPTION, Literal(desc), graph),
            ]
    await backend.add_rdf_quads_batch(proportional_space, quads)

    # A MAINTAINED space. Without this the derived tables are empty, the
    # frame-slot collapse declines, and the traversal is raw quad joins that
    # walk every frame however well the join is ordered — measured at a ratio
    # of 400 on this very fixture. The rewrites still FIRE; they simply have
    # nothing collapsed to drive into.
    #
    # That is a real limitation worth stating rather than hiding: the anchored
    # traversal depends on maintenance having run, so a freshly loaded space
    # does not get it until the first cycle.
    # Its own connection from the pool: this fixture is module-scoped and
    # `pg_conn` is per-test, so it cannot be requested here.
    from vitalgraph.db.sparql_sql.resync_all import resync_all_auxiliary_tables
    pool = backend._db._pool if hasattr(backend, "_db") else space_impl._db._pool
    async with pool.acquire() as conn:
        await resync_all_auxiliary_tables(conn, proportional_space)
    return proportional_space


def _query(space_id: str) -> str:
    graph = f"urn:{space_id}"
    return f"""
PREFIX kg: <{KG}>
PREFIX core: <{CORE}>
SELECT ?entity ?frame ?sourceSlot ?destinationSlot WHERE {{
  GRAPH <{graph}> {{
    {{
      ?sourceSlotEntity a kg:KGEntity .
      ?sourceSlotEntity kg:hasKGraphDescription ?d1 .
      FILTER(CONTAINS(LCASE(STR(?d1)), "needle"))
      BIND(?sourceSlotEntity AS ?entity)
    }} UNION {{
      ?destinationSlotEntity a kg:KGEntity .
      ?destinationSlotEntity kg:hasKGraphDescription ?d2 .
      FILTER(CONTAINS(LCASE(STR(?d2)), "needle"))
      BIND(?destinationSlotEntity AS ?entity)
    }}
    ?frame a kg:KGFrame .
    ?sourceEdge core:hasEdgeSource ?frame .
    ?sourceEdge core:hasEdgeDestination ?sourceSlot .
    ?sourceSlot kg:hasKGSlotType <{SRC_ROLE}> .
    ?sourceSlot kg:hasEntitySlotValue ?sourceSlotEntity .
    ?destinationEdge core:hasEdgeSource ?frame .
    ?destinationEdge core:hasEdgeDestination ?destinationSlot .
    ?destinationSlot kg:hasKGSlotType <{DST_ROLE}> .
    ?destinationSlot kg:hasEntitySlotValue ?destinationSlotEntity .
  }}
}}"""


async def _generate(conn, space_id: str, sparql: str):
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql

    client = AsyncSidecarClient(SIDECAR_URL)
    try:
        raw = await client.compile(sparql)
    finally:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close:
            res = close()
            if hasattr(res, "__await__"):
                await res
    cr = map_compile_response(raw)
    assert cr.ok, f"SPARQL failed to compile: {cr.error}"
    return await generate_sql(cr, space_id, conn=conn)


class TestWorkIsProportionalToTheAnswer:

    async def test_the_traversal_is_driven_by_the_text_anchor(
        self, seeded, pg_conn
    ):
        from vitalgraph.db.sparql_sql.plan_shape import analyse

        gen = await _generate(pg_conn, seeded, _query(seeded))
        assert gen.ok and gen.sql, f"generation failed: {gen.error}"

        rows = await pg_conn.fetch(gen.sql)
        assert rows, ("the fixture produced no rows, so any ratio below would "
                      "pass vacuously")

        plan = await pg_conn.fetch("EXPLAIN (ANALYZE, BUFFERS) " + gen.sql)
        shape = analyse([r[0] for r in plan], rows_returned=len(rows))

        assert shape.ratio < MAX_RATIO, (
            f"the query ran {shape.max_loops:,} loops to return {shape.rows} "
            f"row(s) — a ratio of {shape.ratio:.1f}, against a limit of "
            f"{MAX_RATIO}. Work is proportional to the CORPUS, not the answer: "
            f"the selective anchor is not driving the traversal. Busiest node: "
            f"{shape.busiest[0]['node'] if shape.busiest else 'n/a'}")

    async def test_the_bgp_merge_actually_fires(self, seeded, pg_conn):
        """Wired is not the same as firing.

        `rewrite_merge_bgp` declined silently TWICE on the query it was written
        for — the arms arrive as `Filter(Extend(BGP))`, not bare BGPs — while
        distribution above it fired and duplicated the pattern. The row counts
        stayed correct throughout, so only a decision record catches it.
        """
        gen = await _generate(pg_conn, seeded, _query(seeded))
        decisions = gen.plan_decisions or {}
        fired = decisions.get("fired", [])
        assert "merge_bgp" in fired, (
            f"rewrite_merge_bgp did not fire. Without it the anchor and the "
            f"traversal reach separate join-ordering decisions and the anchor "
            f"cannot drive. declined={decisions.get('declined')}")
        assert "distribute_union" in fired, (
            f"rewrite_distribute_union did not fire; the merge alone has "
            f"nothing to merge under a UNION. declined={decisions.get('declined')}")
