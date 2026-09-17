"""A deleted node leaves edges pointing at nothing, and nothing noticed.

`issues/212`: production carried 298 edge rows of 3,466,543 whose SOURCE node
had no quads at all, holding up 298 intact child frames and 828 intact slots
carrying values. No probe reported it. It surfaced through an
`entity_slot_sort` row shortfall, several inferences away, and the first two
explanations offered for it were both wrong.

WHY THE EXISTING PROBE COULD NOT SEE IT. `edge_table_orphan_rate` asks whether
a row's own defining quad is gone — is this EDGE stale. That is the opposite
question. These rows were perfect materialisations of live edge quads; what had
gone was the node at the end of the arrow. A table can be 100% faithful and
describe a disconnected graph.

The asymmetry is asserted, not just the total: production measured 298 dangling
SOURCES and ZERO dangling destinations, and that difference says which deletion
went wrong — a parent removed without its children, rather than a child removed
while something still referenced it. A single combined count would have hidden
it.
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

EX = "http://example.org/dang/"
KG = "http://vital.ai/ontology/haley-ai-kg#"
CORE = "http://vital.ai/ontology/vital-core#"


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def dang_space(make_space):
    return await make_space(f"{TEST_SPACE_PREFIX}dang_{uuid.uuid4().hex[:8]}")


async def _probe(pg_conn, space_id):
    from vitalgraph.db.sparql_sql.sync_edge_table import (
        edge_table_dangling_endpoints)
    return await edge_table_dangling_endpoints(pg_conn, space_id)


async def test_a_healthy_edge_table_reports_zero(dang_space, space_impl,
                                                 pg_conn):
    """The control. Without it, a probe returning 0 proves nothing."""
    graph = URIRef(f"urn:{dang_space}")
    backend = (space_impl.get_db_space_impl()
               if hasattr(space_impl, "get_db_space_impl") else space_impl)
    src, dst, edge = (URIRef(f"{EX}src"), URIRef(f"{EX}dst"),
                      URIRef(f"{EX}edge1"))
    await backend.add_rdf_quads_batch(dang_space, [
        (src, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}KGFrame"), graph),
        (dst, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}KGFrame"), graph),
        (edge, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}Edge_hasKGFrame"), graph),
        (edge, URIRef(f"{CORE}hasEdgeSource"), src, graph),
        (edge, URIRef(f"{CORE}hasEdgeDestination"), dst, graph),
    ])
    r = await _probe(pg_conn, dang_space)
    assert r == {"dangling_source": 0, "dangling_dest": 0}, (
        f"a table whose nodes all exist must report clean, got {r}")


async def test_deleting_the_source_node_is_detected(dang_space, space_impl,
                                                    pg_conn):
    """Remove the parent's own quads, exactly as the production residue was.

    The edge row and the child survive; only the node at the tail of the arrow
    goes. That is the shape `edge_table_orphan_rate` calls healthy.
    """
    from vitalgraph.db.sparql_sql.sync_edge_table import (
        edge_table_orphan_rate)
    before = await _probe(pg_conn, dang_space)

    await pg_conn.execute(
        f"DELETE FROM {dang_space}_rdf_quad q USING {dang_space}_term t "
        f" WHERE t.term_uuid = q.subject_uuid AND t.term_text = $1",
        f"{EX}src")

    after = await _probe(pg_conn, dang_space)
    assert after["dangling_source"] == before["dangling_source"] + 1, (
        f"deleting the source node must be reported: {before} -> {after}")
    assert after["dangling_dest"] == before["dangling_dest"], (
        "the destination still exists; counting it here would hide which "
        "deletion went wrong")

    # And the reason this probe had to be written: the existing one is blind
    # to it, because the edge's OWN quads are untouched.
    rate = await edge_table_orphan_rate(pg_conn, dang_space)
    assert rate == 0.0, (
        f"edge_table_orphan_rate is expected to report 0 here — it asks "
        f"whether the EDGE is stale, not whether its endpoints exist. If this "
        f"ever fails, the two probes have converged and this one may be "
        f"redundant; got {rate}")
