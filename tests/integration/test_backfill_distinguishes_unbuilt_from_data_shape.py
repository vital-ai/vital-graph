""""0 rows derived" is not evidence of a data shape while the edge table is empty.

The slot-sort backfill used to report three things as settled fact when a batch
derived nothing — no chain exists, it will repeat forever, and it is DATA rather
than a failure — and two of them can be false at once (`issues/159`).

The walk goes entity -> frame -> slot through `{space}_edge`, so an unbuilt edge
table derives nothing from entities that are perfectly well formed. Measured on
`lead_nurture_100k` during its bulk import: six cycles of "0 rows derived", then
100,000 of 100,000 entities and 4,064,500 rows once the import finished. "Can
never reach 100%" was wrong by four million rows, at WARNING, in the log someone
reads to decide whether the backfill is broken.

BOTH HALVES OF THE DISCRIMINATOR ARE TESTED, because either alone is useless. An
empty edge table on an EMPTY space is not a diagnosis, it is an empty space; and
a populated edge table means the original message was right all along.
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

EX = "http://example.org/unbuilt/"
CORE = "http://vital.ai/ontology/vital-core#"
KG = "http://vital.ai/ontology/haley-ai-kg#"


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def ub_space(make_space):
    return await make_space(f"{TEST_SPACE_PREFIX}unbuilt_{uuid.uuid4().hex[:8]}")


async def test_an_empty_space_is_not_diagnosed_as_unbuilt(ub_space, pg_conn):
    """The control, and the half that stops a false positive.

    No quads and no edges is an empty space, not a derivation waiting to
    happen. Reporting "not built yet" here would replace one wrong claim
    with another.
    """
    from vitalgraph.db.sparql_sql.sync_edge_table import edge_table_unbuilt
    assert await edge_table_unbuilt(pg_conn, ub_space) is False, (
        "an empty space must not be reported as an unbuilt derivation")


async def test_quads_without_edges_reads_as_unbuilt(ub_space, space_impl, pg_conn):
    """Quads present, edge table empty — the mid-import state."""
    from vitalgraph.db.sparql_sql.sync_edge_table import edge_table_unbuilt
    graph = URIRef(f"urn:{ub_space}")
    backend = (space_impl.get_db_space_impl()
               if hasattr(space_impl, "get_db_space_impl") else space_impl)
    await backend.add_rdf_quads_batch(ub_space, [
        (URIRef(f"{EX}e"), URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}KGEntity"), graph),
    ])
    await pg_conn.execute(f"DELETE FROM {ub_space}_edge")
    assert await edge_table_unbuilt(pg_conn, ub_space) is True, (
        "quads present and no edges is the precondition case: the walk cannot "
        "derive anything yet, and saying 'can never' there was wrong by 4M rows")


async def test_a_built_edge_table_reads_as_built(ub_space, space_impl, pg_conn):
    """The other half: with edges present the original DATA-shape message stands.

    Without this cell the discriminator could return True unconditionally and
    still pass the test above, which would suppress a warning that is correct.
    """
    from vitalgraph.db.sparql_sql.sync_edge_table import edge_table_unbuilt
    graph = URIRef(f"urn:{ub_space}")
    backend = (space_impl.get_db_space_impl()
               if hasattr(space_impl, "get_db_space_impl") else space_impl)
    edge = URIRef(f"{EX}edge1")
    await backend.add_rdf_quads_batch(ub_space, [
        (edge, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}Edge_hasKGSlot"), graph),
        (edge, URIRef(f"{CORE}hasEdgeSource"), URIRef(f"{EX}e"), graph),
        (edge, URIRef(f"{CORE}hasEdgeDestination"), URIRef(f"{EX}s"), graph),
    ])
    n = await pg_conn.fetchval(f"SELECT count(*) FROM {ub_space}_edge")
    assert n > 0, "fixture failed: the write path should have built an edge row"
    assert await edge_table_unbuilt(pg_conn, ub_space) is False, (
        "with the edge table built, 0 rows derived IS a data shape and the "
        "warning must not be downgraded")
