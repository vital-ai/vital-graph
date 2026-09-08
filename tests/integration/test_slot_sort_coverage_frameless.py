"""An entity that owns no frames is not a coverage shortfall.

FOUND IN PRODUCTION, 2026-09-08. `urn:test:safety:prod:check:entity1` — five
quads, zero frames — made `entity_slot_sort_coverage` report
`KGEntityType_KGEntity` at 0/1. That took a per-type block, which turns the fast
slot filter and sort OFF for the type. The backfill then produced nothing for it
(correctly: there is nothing to derive), coverage stayed 0/1, and the block was
re-taken every cycle. Observed churning every 30-50 s, `created_at` resetting
01:22:24 -> 01:27:01 -> 01:27:52, with no path to convergence.

`entity_slot_sort` holds one row per SLOT reached by
`entity -> frame -> slot -> value`. An entity with no frames therefore has no
rows BY CONSTRUCTION. Counting it in the denominator asks the table to contain
something it can never contain.

THE DENOMINATOR IS STILL QUAD-SIDE, which is the property `issues/149` exists to
protect. It tests frame ownership through the QUADS that make up an
`Edge_hasEntityKGFrame` — not through `{space}_edge` and not through
`entity_slot_sort` — so the probe still cannot be fooled by the derived table it
is checking, nor by the edge table that table is derived from.
"""

from __future__ import annotations

import pytest

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

KG = "http://vital.ai/ontology/haley-ai-kg#"
CORE = "http://vital.ai/ontology/vital-core#"
EX = "http://example.org/cov/"
GRAPH = "http://example.org/cov/graph"
ETYPE = f"{EX}TypeWithFrames"
LONELY_TYPE = f"{EX}TypeWithNoFrames"


def _entity_with_frame(name: str, value: str):
    from rdflib import URIRef, Literal
    g = URIRef(GRAPH)
    e, f, s = URIRef(f"{EX}{name}"), URIRef(f"{EX}{name}_f"), URIRef(f"{EX}{name}_s")
    fe, se = URIRef(f"{EX}{name}_fe"), URIRef(f"{EX}{name}_se")
    return [
        (e, URIRef(f"{KG}hasKGEntityType"), URIRef(ETYPE), g),
        (fe, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}Edge_hasEntityKGFrame"), g),
        (fe, URIRef(f"{CORE}hasEdgeSource"), e, g),
        (fe, URIRef(f"{CORE}hasEdgeDestination"), f, g),
        (f, URIRef(f"{KG}hasKGFrameType"), URIRef(f"{EX}FT"), g),
        (se, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}Edge_hasKGSlot"), g),
        (se, URIRef(f"{CORE}hasEdgeSource"), f, g),
        (se, URIRef(f"{CORE}hasEdgeDestination"), s, g),
        (s, URIRef(f"{KG}hasKGSlotType"), URIRef(f"{EX}ST"), g),
        (s, URIRef(f"{KG}hasTextSlotValue"), Literal(value), g),
    ]


def _frameless_entity(name: str):
    """The production shape: typed, a few properties, no frames at all."""
    from rdflib import URIRef, Literal
    g = URIRef(GRAPH)
    e = URIRef(f"{EX}{name}")
    return [
        (e, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}KGEntity"), g),
        (e, URIRef(f"{KG}hasKGEntityType"), URIRef(LONELY_TYPE), g),
        (e, URIRef(f"{CORE}hasName"), Literal("safety check"), g),
    ]


async def test_a_frameless_entity_is_not_reported_as_a_shortfall(
        test_space, space_impl, pg_pool):
    """The production bug, directly.

    Without the fix this reports `TypeWithNoFrames` at 0/1 — a shortfall no
    backfill can ever close, so the block that follows it never clears.
    """
    from vitalgraph.db.sparql_sql.sync_entity_slot_sort import entity_slot_sort_coverage

    await space_impl.add_rdf_quads_batch(test_space, _entity_with_frame("a", "alpha"))
    await space_impl.add_rdf_quads_batch(test_space, _frameless_entity("lonely"))

    async with pg_pool.acquire() as conn:
        gaps = await entity_slot_sort_coverage(conn, test_space)

    lonely = [g for g in gaps if g["entity_type"] == LONELY_TYPE]
    assert not lonely, (
        f"an entity owning no frames was counted as a coverage shortfall: "
        f"{lonely}. `entity_slot_sort` holds one row per slot reached through a "
        f"frame, so such an entity has no rows BY CONSTRUCTION — the backfill "
        f"can never close this and the block it triggers never clears.")
    assert gaps == [], f"unexpected shortfall on a fully covered space: {gaps}"


async def test_a_real_shortfall_is_still_reported(test_space, space_impl, pg_pool):
    """The fix must not blind the probe — this is what it exists to catch.

    An entity that DOES own a frame with a valued slot, but has no rows, is a
    genuine gap. `issues/149` measured that at 1.05% on production while the
    drift probe reported converged.
    """
    from vitalgraph.db.sparql_sql.sync_entity_slot_sort import entity_slot_sort_coverage

    await space_impl.add_rdf_quads_batch(test_space, _entity_with_frame("b", "bravo"))

    async with pg_pool.acquire() as conn:
        # Remove its rows behind the sync's back, exactly as a stale table looks.
        await conn.execute(f"DELETE FROM {test_space}_entity_slot_sort")
        gaps = await entity_slot_sort_coverage(conn, test_space)

    assert gaps, (
        "an entity that owns a frame with a valued slot, and has no rows, is a "
        "REAL shortfall and must still be reported — otherwise the fix has "
        "turned the probe off rather than corrected it")
    assert any(g["entity_type"] == ETYPE for g in gaps), f"wrong type reported: {gaps}"
