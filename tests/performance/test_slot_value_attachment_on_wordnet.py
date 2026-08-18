"""KGQuery entity criteria must return rows on a slot-value-attached dataset.

`issues/043`. `wordnet_frames` holds 109,745 entities and 285,348 frames and
attaches them the way a relation naturally does — the frame owns source and
destination slots whose VALUES are the entities:

    KGFrame --Edge_hasKGSlot--> KGEntitySlot --hasEntitySlotValue--> KGEntity

It has no `Edge_hasEntityKGFrame` and no `vg-direct:hasEntityFrame` anywhere, so
the only topology the builder could emit matched nothing and EVERY entity query
over this space returned zero rows. Nothing raised and nothing logged: a bench, a
test or a UI panel driven by such a query looked like it was working on an empty
result set.

That is why this asserts EXACT COUNTS rather than `> 0`. A non-empty assertion
would be satisfied by a pattern that fans out or that quietly ignores the role
constraint, and the failure being replaced here is precisely one that looked like
a legitimate answer. The expected values are computed independently in SQL, by
walking the quads without the builder — see the query in `_ground_truth`.

Skips rather than fails when the space is absent: it is a loaded fixture, not
something the suite creates.
"""

from __future__ import annotations

import os

import pytest

from .conftest import skip_no_pg

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

SPACE = "wordnet_frames"
GRAPH = f"urn:{SPACE}"
SIDECAR_URL = os.environ.get("VG_TEST_SIDECAR_URL", "http://localhost:7071")

HALEY = "http://vital.ai/ontology/haley-ai-kg#"
CORE = "http://vital.ai/ontology/vital-core#"
FRAME_TYPE = "urn:Edge_WordnetHyponym"
SRC = "urn:hasSourceEntity"
DEST = "urn:hasDestinationEntity"

GROUND_TRUTH_SQL = f"""
SELECT count(DISTINCT val.object_uuid)
FROM {SPACE}_rdf_quad ft
JOIN {SPACE}_term pft ON pft.term_uuid = ft.predicate_uuid
 AND pft.term_text = '{HALEY}hasKGFrameType'
JOIN {SPACE}_term oft ON oft.term_uuid = ft.object_uuid AND oft.term_text = $1
JOIN {SPACE}_rdf_quad es ON es.object_uuid = ft.subject_uuid
JOIN {SPACE}_term pes ON pes.term_uuid = es.predicate_uuid
 AND pes.term_text = '{CORE}hasEdgeSource'
JOIN {SPACE}_rdf_quad ed ON ed.subject_uuid = es.subject_uuid
JOIN {SPACE}_term ped ON ped.term_uuid = ed.predicate_uuid
 AND ped.term_text = '{CORE}hasEdgeDestination'
JOIN {SPACE}_rdf_quad st ON st.subject_uuid = ed.object_uuid
JOIN {SPACE}_term pst ON pst.term_uuid = st.predicate_uuid
 AND pst.term_text = '{HALEY}hasKGSlotType'
JOIN {SPACE}_term role ON role.term_uuid = st.object_uuid
JOIN {SPACE}_rdf_quad val ON val.subject_uuid = ed.object_uuid
JOIN {SPACE}_term pval ON pval.term_uuid = val.predicate_uuid
 AND pval.term_text = '{HALEY}hasEntitySlotValue'
WHERE ($2::text IS NULL OR role.term_text = $2)
"""


async def _skip_unless_loaded(conn):
    present = await conn.fetchval(
        "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1",
        f"{SPACE}_rdf_quad")
    if not present:
        pytest.skip(f"{SPACE} is not loaded on this stack")


async def _ground_truth(conn, role):
    return await conn.fetchval(GROUND_TRUTH_SQL, FRAME_TYPE, role)


async def _entities(conn, role):
    """Run the criteria query the way the API does, and return the entity URIs."""
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql
    from vitalgraph.sparql.kg_query_builder import (
        EntityQueryCriteria, FrameCriteria, KGQueryCriteriaBuilder)

    sparql = KGQueryCriteriaBuilder().build_entity_query_sparql(
        EntityQueryCriteria(
            frame_criteria=[FrameCriteria(frame_type=FRAME_TYPE)],
            frame_attachment="slot_value",
            attachment_slot_type=role,
            use_edge_pattern=True),
        GRAPH, 500_000, 0)

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
    if not cr.ok:
        pytest.fail(f"criteria SPARQL failed to compile: {cr.error}\n\n{sparql}")
    gen = await generate_sql(cr, SPACE, conn=conn)
    assert gen.ok, gen.error
    return [r[0] for r in await conn.fetch(gen.sql)]


@pytest.mark.parametrize("role", [SRC, DEST, None],
                         ids=["source-role", "destination-role", "any-role"])
async def test_slot_value_attachment_matches_ground_truth(perf_conn, role):
    await _skip_unless_loaded(perf_conn)
    expected = await _ground_truth(perf_conn, role)
    assert expected, "ground truth is zero — this case would assert nothing"

    rows = await _entities(perf_conn, role)
    assert len(set(rows)) == expected, (
        f"role={role}: builder returned {len(set(rows))} distinct entities, "
        f"the data holds {expected}")
    # A frame->slot->entity path can emit an entity once per attaching frame.
    # Paging is built on row counts, so a fan-out here would silently corrupt
    # every page boundary.
    assert len(rows) == len(set(rows)), "attachment path duplicated entities"


async def test_the_role_constraint_actually_discriminates(perf_conn):
    """Otherwise the role filter could be inert and every assertion above still pass."""
    await _skip_unless_loaded(perf_conn)
    src = set(await _entities(perf_conn, SRC))
    dest = set(await _entities(perf_conn, DEST))
    assert src != dest, "source and destination roles returned the same entities"
    assert src - dest, "no entity is exclusively a source — the filter may be inert"
    assert dest - src, "no entity is exclusively a destination"


async def test_any_role_is_the_union_of_the_roles(perf_conn):
    """An unconstrained attachment must widen the result, not silently pick a role."""
    await _skip_unless_loaded(perf_conn)
    src = set(await _entities(perf_conn, SRC))
    dest = set(await _entities(perf_conn, DEST))
    assert set(await _entities(perf_conn, None)) == src | dest
