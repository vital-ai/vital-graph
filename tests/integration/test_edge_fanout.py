"""Integration tests: `{space}_edge_fanout` records what a traversal multiplies by.

Fan-out is the statistic that decides which direction a multi-hop traversal
should be walked, and nothing else in the schema expresses it. `rdf_stats` and
PostgreSQL's `stat_*_quad_po` describe single-table selectivity; the errors that
matter here are join cardinality, measured at 305x and 4,761x underestimates
(`issues/059`).

These tests assert the two properties a caller will rely on, using shapes whose
answers are known by construction rather than by reading them back off the same
query that produced them:

  1. a containment hierarchy has backward fan-out 1 — a slot has exactly one
     parent, so walking it backward can never amplify;
  2. a hub does not, and the difference is visible per RELATION TYPE rather than
     being averaged away by the edge type they share.

(2) is the one that matters. On `sp_kg_rel`, `reportsTo` and `worksFor` are both
`Edge_hasKGRelation` with backward fan-out of 5 and 886 — pooled by edge type
they average into a number describing neither, and pooled by space the whole
table reports 1.51.
"""

from __future__ import annotations

import uuid

import pytest
from rdflib import URIRef

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
HAS_RELATION_TYPE = URIRef(f"{KG}hasKGRelationType")
EDGE_HAS_SLOT = URIRef(f"{KG}Edge_hasKGSlot")
EDGE_RELATION = URIRef(f"{KG}Edge_hasKGRelation")

GRAPH = URIRef("urn:test:fanout_graph")
NO_RELATION = uuid.UUID("00000000-0000-0000-0000-000000000000")


async def _fanout(conn, space_id: str) -> dict:
    """{(edge_type_text, relation_type_text|None, direction): row}."""
    rows = await conn.fetch(f"""
        SELECT te.term_text AS etype, tr.term_text AS rtype, f.direction,
               f.avg_fanout, f.p99_fanout, f.max_fanout
        FROM {space_id}_edge_fanout f
        JOIN {space_id}_term te ON te.term_uuid = f.edge_type_uuid
        LEFT JOIN {space_id}_term tr ON tr.term_uuid = f.relation_type_uuid
    """)
    return {(r["etype"], r["rtype"], r["direction"]): r for r in rows}


class TestEdgeFanout:

    async def test_containment_is_a_tree_backward(
        self, test_space, space_impl, pg_conn
    ):
        """One parent per child, many children per parent.

        The property that makes walking containment backward safe by
        construction rather than by measurement — and the reason a negation
        rewrite can start from the constrained end without risking
        amplification.
        """
        from vitalgraph.db.sparql_sql.sync_edge_fanout import compute_edge_fanout

        quads = []
        for parent in range(3):
            for child in range(4):          # fan out 4 forward, 1 backward
                edge = URIRef(f"urn:test:fo:edge:{parent}:{child}")
                quads += [
                    (edge, VITALTYPE, EDGE_HAS_SLOT, GRAPH),
                    (edge, HAS_EDGE_SOURCE,
                     URIRef(f"urn:test:fo:frame:{parent}"), GRAPH),
                    (edge, HAS_EDGE_DEST,
                     URIRef(f"urn:test:fo:slot:{parent}:{child}"), GRAPH),
                ]
        await space_impl.add_rdf_quads_batch(test_space, quads)
        await compute_edge_fanout(pg_conn, test_space)

        f = await _fanout(pg_conn, test_space)
        back = f[(str(EDGE_HAS_SLOT), None, "backward")]
        fwd = f[(str(EDGE_HAS_SLOT), None, "forward")]

        assert back["max_fanout"] == 1, (
            f"containment backward fan-out is {back['max_fanout']}, expected 1 "
            f"— a slot has exactly one parent, and a rewrite that walks "
            f"backward relies on that not amplifying")
        assert fwd["max_fanout"] == 4, (
            f"forward fan-out is {fwd['max_fanout']}, expected 4")

    async def test_relation_types_are_recorded_separately(
        self, test_space, space_impl, pg_conn
    ):
        """Two relation types on ONE edge type, with opposite shapes.

        The case that decides the granularity. `narrow` is a tree backward,
        `hub` is many-to-one — if the table keyed only on edge type, both would
        collapse into an average describing neither, which is exactly what the
        pooled figures do on real data.
        """
        from vitalgraph.db.sparql_sql.sync_edge_fanout import compute_edge_fanout

        narrow = URIRef("urn:test:fo:rel:narrow")
        hub = URIRef("urn:test:fo:rel:hub")
        quads = []
        # narrow: each source to its own destination — 1 backward.
        for i in range(6):
            e = URIRef(f"urn:test:fo:rel:n:{i}")
            quads += [
                (e, VITALTYPE, EDGE_RELATION, GRAPH),
                (e, HAS_RELATION_TYPE, narrow, GRAPH),
                (e, HAS_EDGE_SOURCE, URIRef(f"urn:test:fo:p:{i}"), GRAPH),
                (e, HAS_EDGE_DEST, URIRef(f"urn:test:fo:q:{i}"), GRAPH),
            ]
        # hub: every source to the SAME destination — 6 backward.
        for i in range(6):
            e = URIRef(f"urn:test:fo:rel:h:{i}")
            quads += [
                (e, VITALTYPE, EDGE_RELATION, GRAPH),
                (e, HAS_RELATION_TYPE, hub, GRAPH),
                (e, HAS_EDGE_SOURCE, URIRef(f"urn:test:fo:p:{i}"), GRAPH),
                (e, HAS_EDGE_DEST, URIRef("urn:test:fo:hubnode"), GRAPH),
            ]
        await space_impl.add_rdf_quads_batch(test_space, quads)
        await compute_edge_fanout(pg_conn, test_space)

        f = await _fanout(pg_conn, test_space)
        n_back = f[(str(EDGE_RELATION), str(narrow), "backward")]
        h_back = f[(str(EDGE_RELATION), str(hub), "backward")]

        assert n_back["max_fanout"] == 1, (
            f"narrow relation backward fan-out {n_back['max_fanout']}, "
            f"expected 1")
        assert h_back["max_fanout"] == 6, (
            f"hub relation backward fan-out {h_back['max_fanout']}, expected 6")
        assert h_back["max_fanout"] > n_back["max_fanout"] * 5, (
            "the two relation types must be distinguishable; if they are "
            "pooled by edge type the difference is averaged away and a "
            "direction choice has nothing to go on")

    async def test_tail_is_recorded_not_just_the_mean(
        self, test_space, space_impl, pg_conn
    ):
        """max must exceed avg on a skewed shape.

        wordnet's slot-value in-degree averages 5.20 with a maximum of 1,342 —
        a plan chosen on the mean can be 258x wrong, and the cost of being wrong
        is a timeout rather than a slightly worse plan.
        """
        from vitalgraph.db.sparql_sql.sync_edge_fanout import compute_edge_fanout

        quads = []
        # one destination with 20 sources, plus 20 with one each
        for i in range(20):
            e = URIRef(f"urn:test:fo:sk:h:{i}")
            quads += [
                (e, VITALTYPE, EDGE_HAS_SLOT, GRAPH),
                (e, HAS_EDGE_SOURCE, URIRef(f"urn:test:fo:sk:s:{i}"), GRAPH),
                (e, HAS_EDGE_DEST, URIRef("urn:test:fo:sk:hub"), GRAPH),
            ]
        for i in range(20):
            e = URIRef(f"urn:test:fo:sk:t:{i}")
            quads += [
                (e, VITALTYPE, EDGE_HAS_SLOT, GRAPH),
                (e, HAS_EDGE_SOURCE, URIRef(f"urn:test:fo:sk:u:{i}"), GRAPH),
                (e, HAS_EDGE_DEST, URIRef(f"urn:test:fo:sk:v:{i}"), GRAPH),
            ]
        await space_impl.add_rdf_quads_batch(test_space, quads)
        await compute_edge_fanout(pg_conn, test_space)

        f = await _fanout(pg_conn, test_space)
        back = f[(str(EDGE_HAS_SLOT), None, "backward")]
        assert back["max_fanout"] == 20, (
            f"max backward fan-out {back['max_fanout']}, expected 20")
        assert back["avg_fanout"] < 3, (
            f"avg {back['avg_fanout']} should be small — the point is that it "
            f"does not resemble the max")
        assert back["max_fanout"] > back["avg_fanout"] * 5, (
            "a caller planning on the average would be off by this ratio; "
            "storing only the mean would hide it")
