"""An edge deleted WHOLE leaves nothing dangling and a subgraph unreachable.

`edge_table_dangling_endpoints` follows arrows, so it needs an arrow to follow.
Remove the entity at an edge's tail and the edge dangles — that probe sees it.
Remove the EDGE OBJECT instead and nothing dangles at all: the frame it held up
is simply unreachable, and the space reports clean.

Found on dev while explaining why a space stayed blocked — 5 slots carrying text
values on 5 intact frames, none reachable from an entity, 3 of them with nothing
pointing at them at all, on a space the dangling probe had just called clean.

The pairing is the test. A cell that only asserted the new probe finds something
would pass against a probe that flags everything; what makes it meaningful is
that the OLD probe reports zero on the same data.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from rdflib import URIRef

from .conftest import skip_no_infra, TEST_SPACE_PREFIX

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

EX = "http://example.org/unref/"
KG = "http://vital.ai/ontology/haley-ai-kg#"
CORE = "http://vital.ai/ontology/vital-core#"


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def unref_space(make_space):
    return await make_space(f"{TEST_SPACE_PREFIX}unref_{uuid.uuid4().hex[:8]}")


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def seeded(unref_space, space_impl):
    """One attached frame and one frame nothing points at.

    Both are complete KGFrame objects; the only difference is the edge.
    """
    graph = URIRef(f"urn:{unref_space}")
    backend = (space_impl.get_db_space_impl()
               if hasattr(space_impl, "get_db_space_impl") else space_impl)
    ent, attached, orphan, edge = (URIRef(f"{EX}entity"), URIRef(f"{EX}attached"),
                                   URIRef(f"{EX}orphan"), URIRef(f"{EX}edge"))
    quads = [
        (ent, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}KGEntity"), graph),
        (attached, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}KGFrame"), graph),
        (orphan, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}KGFrame"), graph),
        # the edge that reaches `attached`; NOTHING reaches `orphan`
        (edge, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}Edge_hasEntityKGFrame"), graph),
        (edge, URIRef(f"{CORE}hasEdgeSource"), ent, graph),
        (edge, URIRef(f"{CORE}hasEdgeDestination"), attached, graph),
    ]
    await backend.add_rdf_quads_batch(unref_space, quads)
    return unref_space


async def test_a_frame_nothing_points_at_is_reported(seeded, pg_conn):
    from vitalgraph.db.sparql_sql.sync_edge_table import unreferenced_kg_objects
    r = await unreferenced_kg_objects(pg_conn, seeded)
    assert r["frames"] == 1, (
        f"exactly the orphan frame should be reported; the attached one has an "
        f"incoming Edge_hasEntityKGFrame and must not be: {r}")


async def test_the_dangling_probe_reports_clean_on_the_same_data(seeded, pg_conn):
    """The whole reason a second probe exists.

    Every edge here has both endpoints present, so nothing dangles. If this ever
    starts failing, the two probes have converged and one may be redundant.
    """
    from vitalgraph.db.sparql_sql.sync_edge_table import (
        edge_table_dangling_endpoints)
    r = await edge_table_dangling_endpoints(pg_conn, seeded)
    assert r == {"dangling_source": 0, "dangling_dest": 0}, (
        f"the dangling probe must see nothing here — that blindness is what "
        f"unreferenced_kg_objects was written for: {r}")


async def test_a_slot_with_no_slot_edge_is_reported(seeded, pg_conn, space_impl):
    """The partial-write shape: a slot written without its Edge_hasKGSlot.

    Seven schedule groups on production were exactly this — four slots written
    while the parent frame and both its edges never were (`issues/212`).
    """
    from vitalgraph.db.sparql_sql.sync_edge_table import unreferenced_kg_objects
    graph = URIRef(f"urn:{seeded}")
    backend = (space_impl.get_db_space_impl()
               if hasattr(space_impl, "get_db_space_impl") else space_impl)
    before = await unreferenced_kg_objects(pg_conn, seeded)
    slot = URIRef(f"{EX}loose_slot")
    await backend.add_rdf_quads_batch(seeded, [
        (slot, URIRef(f"{KG}hasKGSlotType"), URIRef(f"{EX}SomeSlotType"), graph),
        (slot, URIRef(f"{KG}hasTextSlotValue"), URIRef(f"{EX}v"), graph),
    ])
    after = await unreferenced_kg_objects(pg_conn, seeded)
    assert after["slots"] == before["slots"] + 1, (
        f"a slot no Edge_hasKGSlot points at must be reported: {before} -> {after}")
