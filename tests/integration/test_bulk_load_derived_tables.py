"""Integration tests: bulk loading leaves derived tables as a rebuild would.

The last of the four write modes to get coverage. It is the mode that has been
*working*, which is exactly why it needs its own test: it works by a DIFFERENT
mechanism from the other three. Bulk paths call the incremental hooks and, on
import, a full `resync_all_auxiliary_tables`; the REST and SPARQL paths call
only the hooks. A regression in the hooks is invisible to a bulk-load test, and
a regression in the resync is invisible to a CRUD test. Neither substitutes for
the other.

The assertion
-------------
After a bulk load, every derived table holds exactly what a full rebuild from
the quads would produce. Snapshot, rebuild, compare — rather than asserting
counts or spot-checking rows, both of which have already proven able to pass on
broken data during this work:

* an orphaned edge row is an EXTRA row, so a count check reads a table
  containing them as healthy, and orphans plus missing edges cancel exactly;
* a stale frame_entity row keeps the count unchanged while naming the wrong
  entity.

Comparing against the rebuild is the only form that catches both, because the
rebuild is the definition of correct.

See planning/planning_performance/performance_regression_tracking_plan.md R6
"""

from __future__ import annotations

import pytest
from rdflib import Literal, URIRef

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

CORE = "http://vital.ai/ontology/vital-core#"
KG = "http://vital.ai/ontology/haley-ai-kg#"

VITALTYPE = URIRef(f"{CORE}vitaltype")
HAS_EDGE_SOURCE = URIRef(f"{CORE}hasEdgeSource")
HAS_EDGE_DEST = URIRef(f"{CORE}hasEdgeDestination")
EDGE_HAS_SLOT = URIRef(f"{KG}Edge_hasKGSlot")
KG_FRAME = URIRef(f"{KG}KGFrame")
HAS_SLOT_TYPE = URIRef(f"{KG}hasKGSlotType")
HAS_ENTITY_SLOT_VALUE = URIRef(f"{KG}hasEntitySlotValue")
SOURCE_ENTITY = URIRef("urn:hasSourceEntity")
DEST_ENTITY = URIRef("urn:hasDestinationEntity")

GRAPH = URIRef("urn:test:bulk_graph")


def _dataset(n: int) -> list:
    """Connection frames, the shape that exercises every derived table at once.

    Each frame produces edge rows (two), a frame_entity row, and stats for
    several predicates — so one dataset covers all three structures rather than
    testing each against data shaped only for it.
    """
    quads = []
    for i in range(n):
        frame = URIRef(f"urn:test:bulk:frame:{i}")
        quads.append((frame, VITALTYPE, KG_FRAME, GRAPH))
        for role, stype in (("src", SOURCE_ENTITY), ("dst", DEST_ENTITY)):
            slot = URIRef(f"urn:test:bulk:slot:{role}:{i}")
            edge = URIRef(f"urn:test:bulk:edge:{role}:{i}")
            entity = URIRef(f"urn:test:bulk:entity:{role}:{i % 3}")
            quads += [
                (edge, VITALTYPE, EDGE_HAS_SLOT, GRAPH),
                (edge, HAS_EDGE_SOURCE, frame, GRAPH),
                (edge, HAS_EDGE_DEST, slot, GRAPH),
                (slot, HAS_SLOT_TYPE, stype, GRAPH),
                (slot, HAS_ENTITY_SLOT_VALUE, entity, GRAPH),
                (slot, URIRef("urn:test:bulk:label"), Literal(f"L{i % 4}"), GRAPH),
            ]
    return quads


async def _snapshot(conn, space_id: str) -> dict:
    """Every derived table, as comparable sets."""
    edges = await conn.fetch(
        f"SELECT edge_uuid, source_node_uuid, dest_node_uuid, context_uuid, "
        f"edge_type_uuid FROM {space_id}_edge")
    fe = await conn.fetch(
        f"SELECT frame_uuid, source_entity_uuid, dest_entity_uuid, context_uuid "
        f"FROM {space_id}_frame_entity")
    stats = await conn.fetch(
        f"SELECT predicate_uuid, object_uuid, row_count "
        f"FROM {space_id}_rdf_stats")
    preds = await conn.fetch(
        f"SELECT predicate_uuid, row_count FROM {space_id}_rdf_pred_stats")
    return {
        "edge": {tuple(r) for r in edges},
        "frame_entity": {tuple(r) for r in fe},
        "stats": {tuple(r) for r in stats},
        "pred_stats": {tuple(r) for r in preds},
    }


class TestBulkLoadDerivedTables:

    async def test_bulk_load_matches_a_full_rebuild(
        self, test_space, space_impl, pg_conn
    ):
        """What the bulk path leaves behind == what a rebuild produces."""
        from vitalgraph.db.sparql_sql.resync_all import resync_all_auxiliary_tables

        await space_impl.add_rdf_quads_batch_bulk(test_space, _dataset(12))

        after_load = await _snapshot(pg_conn, test_space)
        assert after_load["edge"], "bulk load produced no edge rows"
        assert after_load["frame_entity"], "bulk load produced no frame_entity rows"
        assert after_load["stats"], "bulk load produced no stats rows"

        await resync_all_auxiliary_tables(pg_conn, test_space)
        after_rebuild = await _snapshot(pg_conn, test_space)

        for table in ("edge", "frame_entity", "pred_stats"):
            missing = after_rebuild[table] - after_load[table]
            extra = after_load[table] - after_rebuild[table]
            assert not missing and not extra, (
                f"{table} after bulk load differs from a full rebuild: "
                f"{len(missing)} row(s) the rebuild has and the load did not "
                f"produce, {len(extra)} row(s) the load left that the rebuild "
                f"does not. The rebuild is the definition of correct.")

        # rdf_stats is pruned, so the rebuild may legitimately hold a different
        # SET of pairs. What must agree is every count present in both.
        load_map = {(p, o): n for p, o, n in after_load["stats"]}
        rebuild_map = {(p, o): n for p, o, n in after_rebuild["stats"]}
        disagreeing = {k: (load_map[k], rebuild_map[k])
                       for k in load_map.keys() & rebuild_map.keys()
                       if load_map[k] != rebuild_map[k]}
        assert not disagreeing, (
            f"{len(disagreeing)} stats count(s) disagree with a full rebuild: "
            f"{list(disagreeing.items())[:5]}")

    async def test_bulk_load_then_crud_still_matches_a_rebuild(
        self, test_space, space_impl, pg_conn
    ):
        """The mixed sequence, which is what production actually does.

        A bulk import followed by incremental edits is the normal lifecycle, and
        it is the case where the two mechanisms have to agree with each other
        rather than merely each be self-consistent. Every defect found in this
        area was a disagreement of exactly that kind.
        """
        from vitalgraph.db.sparql_sql.resync_all import resync_all_auxiliary_tables

        await space_impl.add_rdf_quads_batch_bulk(test_space, _dataset(8))

        # create, update, delete — through the non-bulk paths
        await space_impl.add_rdf_quads_batch(test_space, _dataset(2)[:6])
        await space_impl.execute_sparql_update(
            test_space,
            f"DELETE DATA {{ GRAPH <{GRAPH}> {{ "
            f"<urn:test:bulk:slot:src:0> <{HAS_ENTITY_SLOT_VALUE}> "
            f"<urn:test:bulk:entity:src:0> . }} }}")
        await space_impl.execute_sparql_update(
            test_space,
            f"INSERT DATA {{ GRAPH <{GRAPH}> {{ "
            f"<urn:test:bulk:slot:src:0> <{HAS_ENTITY_SLOT_VALUE}> "
            f"<urn:test:bulk:entity:src:9> . }} }}")

        after_crud = await _snapshot(pg_conn, test_space)
        await resync_all_auxiliary_tables(pg_conn, test_space)
        after_rebuild = await _snapshot(pg_conn, test_space)

        for table in ("edge", "frame_entity"):
            missing = after_rebuild[table] - after_crud[table]
            extra = after_crud[table] - after_rebuild[table]
            assert not missing and not extra, (
                f"{table} diverged from a rebuild after bulk load + CRUD: "
                f"{len(missing)} missing, {len(extra)} stale. The incremental "
                f"hooks and the full resync disagree about the same data.")
