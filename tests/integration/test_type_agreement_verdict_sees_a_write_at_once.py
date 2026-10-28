"""A stored type-agreement verdict is declined the moment a write can make it false (issue 302).

The verdict (`rdf:type` agrees with `frame_slot.frame_type_uuid`) lets a frame type
constraint be read off the derived column. It was accepted while a token of the
table's statistics was unchanged, and those counters are flushed asynchronously: a
committed write was missing from them for 10-60 s, and a verdict it had made false
was used in that window (rows dropped or added). With the space's write log
installed, the token carries the log's write count, which a reader sees exactly
when it sees the write.
"""

from __future__ import annotations

import pytest
from rdflib import URIRef

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

RDF_TYPE = URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
VITALTYPE = URIRef("http://vital.ai/ontology/vital-core#vitaltype")
KG_FRAME = URIRef("http://vital.ai/ontology/haley-ai-kg#KGFrame")
OTHER = URIRef("http://example.org/tav/OtherType")
HAS_EDGE_SOURCE = URIRef("http://vital.ai/ontology/vital-core#hasEdgeSource")
HAS_EDGE_DEST = URIRef("http://vital.ai/ontology/vital-core#hasEdgeDestination")
EDGE_HAS_SLOT = URIRef("http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot")
HAS_SLOT_TYPE = URIRef("http://vital.ai/ontology/haley-ai-kg#hasKGSlotType")
HAS_ENTITY_SLOT_VALUE = URIRef("http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue")
GRAPH = URIRef("urn:test:tav_graph")


def _frame(tag: str):
    f = URIRef(f"urn:test:tav_frame_{tag}")
    slot, edge = URIRef(f"urn:test:tav_slot_{tag}"), URIRef(f"urn:test:tav_edge_{tag}")
    return f, [
        (f, VITALTYPE, KG_FRAME, GRAPH),
        (f, RDF_TYPE, KG_FRAME, GRAPH),                  # agrees with vitaltype
        (edge, VITALTYPE, EDGE_HAS_SLOT, GRAPH),
        (edge, HAS_EDGE_SOURCE, f, GRAPH),
        (edge, HAS_EDGE_DEST, slot, GRAPH),
        (slot, HAS_SLOT_TYPE, URIRef("urn:hasSourceEntity"), GRAPH),
        (slot, HAS_ENTITY_SLOT_VALUE, URIRef(f"urn:test:tav_entity_{tag}"), GRAPH),
    ]


async def test_a_disagreeing_write_is_seen_at_once(make_space, space_impl, pg_conn, pg_pool):
    from vitalgraph.db.sparql_sql import edge_type_agreement as eta
    from vitalgraph.db.sparql_sql import write_log

    space = await make_space()
    quads = []
    for tag in ("a", "b", "c"):
        f, q = _frame(tag)
        quads += q
    await space_impl.add_rdf_quads_batch(space, quads)
    for stmt in write_log.create_sql(space):
        await pg_conn.execute(stmt)

    eta.clear_cache()
    out = await eta.refresh_type_agreement(pg_conn, space, force=True)
    frame = next(r for r in out if r["kind"] == "frame")
    assert frame["agrees"] is True, out

    async with pg_pool.acquire() as reader:
        eta.ACCEPTED_GUARD.set(None)
        assert await eta.frame_type_absorbable(space, str(RDF_TYPE), reader) is True
        guard = eta.ACCEPTED_GUARD.get()
        assert guard is not None and guard[0] == space          # the executor's guard

        # a frame now says it is ALSO another type: rdf:type and vitaltype disagree
        f, _ = _frame("a")
        await space_impl.add_rdf_quads_batch(space, [(f, RDF_TYPE, OTHER, GRAPH)])

        eta.clear_cache()
        # immediately, from another connection: the stored verdict is no longer usable
        assert await eta.frame_type_absorbable(space, str(RDF_TYPE), reader) is None


async def test_the_planning_guard_moves_with_a_write(make_space, space_impl, pg_conn, pg_pool):
    """The guard handed to the executor is the write log's state: a later write moves
    it, so a query planned on the verdict re-plans without it (`guard_holds`)."""
    from vitalgraph.db.sparql_sql import edge_type_agreement as eta
    from vitalgraph.db.sparql_sql import write_log
    from vitalgraph.db.sparql_sql.pattern_verdict import guard_holds

    space = await make_space()
    _, q = _frame("g")
    await space_impl.add_rdf_quads_batch(space, q)
    for stmt in write_log.create_sql(space):
        await pg_conn.execute(stmt)
    eta.clear_cache()
    await eta.refresh_type_agreement(pg_conn, space, force=True)
    async with pg_pool.acquire() as reader:
        eta.ACCEPTED_GUARD.set(None)
        assert await eta.frame_type_absorbable(space, str(RDF_TYPE), reader) is True
        guard = eta.ACCEPTED_GUARD.get()
        assert await guard_holds(reader, guard[0], guard[1:])
        _, q2 = _frame("h")
        await space_impl.add_rdf_quads_batch(space, q2)
        assert not await guard_holds(reader, guard[0], guard[1:])
