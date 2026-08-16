"""`{space}_entity_slot_sort` must never describe a graph that has moved.

`issues/096`. This table carries the VALUE a sort orders by, so a stale row is a
WRONG ORDER — not a slow query, and not an empty result either. It is the third
structural mirror in this schema and the two before it both shipped stale in
production (`issues/041`, and an edge table ~25% incomplete), so the failure
modes are known rather than hypothetical and are tested here directly.

THE DANGEROUS ONE IS `test_a_changed_value_is_not_left_behind`. Repointing a
slot's value touches only the SLOT — not the entity, not the frame — and the row
COUNT does not change. So an insert-only sync leaves the old value in place, the
drift probe reports zero, and the sort silently orders by data that no longer
exists. `sync_frame_entity_before_delete` documents having shipped exactly that
bug one table over, which is why the sync here deletes before it re-derives and
why this test exists rather than being left to the drift check.

WRITES GO THROUGH `space_impl`, NOT THE `sparql_update` FIXTURE. That fixture
compiles SPARQL straight to SQL and executes it against the pool, bypassing
`sparql_sql_space_impl` entirely — so NO derived table is maintained by it, and
a first draft of this file using it reported an empty edge table and zero rows
everywhere. It would have "passed" trivially had the assertions been weaker,
while testing none of the write-path wiring this file exists to cover.
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
EX = "http://example.org/ess/"

ENTITY_TYPE = f"{EX}TestEntityType"
FRAME_TYPE = f"{EX}TestFrameType"
SLOT_TYPE = f"{EX}TestSlotType"
GRAPH = "http://example.org/ess/graph"

ENTITIES = {"a": "alpha", "b": "bravo", "c": "charlie"}


def _quads(values: dict[str, str]) -> list[tuple]:
    """(s, p, o, g) rdflib terms, the form the space impl's batch writers take."""
    from rdflib import URIRef, Literal

    g = URIRef(GRAPH)
    out = []
    for name, value in values.items():
        e = URIRef(f"{EX}{name}")
        f = URIRef(f"{EX}{name}_frame")
        s = URIRef(f"{EX}{name}_slot")
        fe = URIRef(f"{EX}{name}_fe")
        se = URIRef(f"{EX}{name}_se")
        out += [
            (e, URIRef(f"{KG}hasKGEntityType"), URIRef(ENTITY_TYPE), g),
            (fe, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}Edge_hasEntityKGFrame"), g),
            (fe, URIRef(f"{CORE}hasEdgeSource"), e, g),
            (fe, URIRef(f"{CORE}hasEdgeDestination"), f, g),
            (f, URIRef(f"{KG}hasKGFrameType"), URIRef(FRAME_TYPE), g),
            (se, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}Edge_hasKGSlot"), g),
            (se, URIRef(f"{CORE}hasEdgeSource"), f, g),
            (se, URIRef(f"{CORE}hasEdgeDestination"), s, g),
            (s, URIRef(f"{KG}hasKGSlotType"), URIRef(SLOT_TYPE), g),
            (s, URIRef(f"{KG}hasTextSlotValue"), Literal(value), g),
        ]
    return out


async def _rows(pg_pool, space: str) -> list[tuple]:
    """(entity local name, value) currently in the table, ordered."""
    async with pg_pool.acquire() as conn:
        recs = await conn.fetch(f"""
            SELECT t.term_text, s.value_text
            FROM {space}_entity_slot_sort s
            JOIN {space}_term t ON t.term_uuid = s.entity_uuid
            ORDER BY s.value_text COLLATE "C" """)
    return [(r[0].rsplit("/", 1)[-1], r[1]) for r in recs]


async def _drift(pg_pool, space: str) -> int:
    from vitalgraph.db.sparql_sql.sync_entity_slot_sort import entity_slot_sort_drift
    async with pg_pool.acquire() as conn:
        expected, actual = await entity_slot_sort_drift(conn, space)
    return expected - actual


async def test_insert_populates_the_table(test_space, space_impl, pg_pool):
    """The write path maintains it — not only the bulk resync."""
    await space_impl.add_rdf_quads_batch(test_space, _quads(ENTITIES))

    rows = await _rows(pg_pool, test_space)

    assert sorted(rows) == sorted([("a", "alpha"), ("b", "bravo"), ("c", "charlie")]), (
        f"the table does not describe the graph just written: {rows}")
    assert await _drift(pg_pool, test_space) == 0


async def test_a_changed_value_is_not_left_behind(
        test_space, space_impl, pg_pool):
    """The silent one: repoint a slot's value, count unchanged.

    Touches the SLOT only. An insert-only sync hits ON CONFLICT DO NOTHING, the
    row keeps the OLD value, the row count is identical so drift reads zero —
    and every subsequent sort orders by a value that is no longer in the graph.
    """
    await space_impl.add_rdf_quads_batch(test_space, _quads(ENTITIES))

    # Repoint b: bravo -> zulu, which also MOVES it in the sort order.
    await space_impl.remove_rdf_quads_batch(test_space, _quads({"b": "bravo"}))
    await space_impl.add_rdf_quads_batch(test_space, _quads({"b": "zulu"}))

    rows = dict(await _rows(pg_pool, test_space))

    assert rows.get("b") == "zulu", (
        f"entity b still reads {rows.get('b')!r} — the row was not re-derived, "
        f"so the sort orders by a value the graph no longer contains "
        f"(issues/096)")
    assert "bravo" not in rows.values(), f"stale value survives: {rows}"
    assert await _drift(pg_pool, test_space) == 0


async def test_sparql_update_re_derives_rather_than_only_inserting(
        test_space, space_impl, pg_pool):
    """The path where delete-before-re-derive is the ONLY thing protecting us.

    `execute_sparql_update` calls `sync_entity_slot_sort_after_edge_insert` and
    nothing else — there is no separate before_delete on that path — so the
    delete INSIDE that function is what corrects a changed value. Remove it and
    the re-derive hits ON CONFLICT DO NOTHING, the row keeps the old value, and
    the row count is unchanged so drift still reads zero.

    Written after discovering that the batch-writer test above does NOT cover
    this: `remove_rdf_quads_batch` deletes the row itself, so that test passed
    with the internal delete removed. Verified to fail without it.
    """
    await space_impl.add_rdf_quads_batch(test_space, _quads(ENTITIES))

    ok = await space_impl.execute_sparql_update(test_space, f"""
        DELETE DATA {{ GRAPH <{GRAPH}> {{
            <{EX}b_slot> <{KG}hasTextSlotValue> "bravo" .
        }} }} ;
        INSERT DATA {{ GRAPH <{GRAPH}> {{
            <{EX}b_slot> <{KG}hasTextSlotValue> "zulu" .
        }} }}
    """)
    assert ok, "the SPARQL update itself failed — the test proves nothing"

    rows = dict(await _rows(pg_pool, test_space))
    assert rows.get("b") == "zulu", (
        f"entity b still reads {rows.get('b')!r} after a SPARQL UPDATE changed "
        f"its value. The re-derive did not replace the row, so every sort now "
        f"orders by a value the graph no longer contains — and the row count is "
        f"unchanged, so no drift check will ever report it (issues/096)")
    assert await _drift(pg_pool, test_space) == 0


async def test_delete_removes_the_rows(test_space, space_impl, pg_pool):
    """A deleted entity must not keep sorting.

    The other direction from `041`: not a table left empty, but one left too
    full, which sorts entities that are gone into the middle of a page.
    """
    await space_impl.add_rdf_quads_batch(test_space, _quads(ENTITIES))
    await space_impl.remove_rdf_quads_batch(test_space, _quads({"c": "charlie"}))

    rows = await _rows(pg_pool, test_space)

    assert ("c", "charlie") not in rows, f"deleted entity still present: {rows}"
    assert len(rows) == 2, rows
    assert await _drift(pg_pool, test_space) == 0


async def test_drift_probe_sees_a_table_emptied_behind_its_back(
        test_space, space_impl, pg_pool):
    """The probe must detect `041` — the failure that shipped on two tables.

    Deleting the rows directly simulates a space whose derived table was
    created empty by a migration and never repopulated.
    """
    await space_impl.add_rdf_quads_batch(test_space, _quads(ENTITIES))
    async with pg_pool.acquire() as conn:
        await conn.execute(f"DELETE FROM {test_space}_entity_slot_sort")

    assert await _drift(pg_pool, test_space) == 3, (
        "the drift probe did not notice an emptied table — this is exactly "
        "issues/041, which went unnoticed on every space")

    from vitalgraph.db.sparql_sql.sync_entity_slot_sort import (
        backfill_entity_slot_sort)
    async with pg_pool.acquire() as conn:
        added = await backfill_entity_slot_sort(conn, test_space)

    assert added == 3
    assert await _drift(pg_pool, test_space) == 0
    assert len(await _rows(pg_pool, test_space)) == 3


async def test_a_slot_under_a_nested_frame_is_covered(
        test_space, space_impl, pg_pool):
    """A slot two frames below the entity must be in the table, with its PATH.

    The first version of this table walked ONE hop and stored a single frame
    type, so every child-frame slot was silently absent — on `prod_kg` that
    was `GuarantorEmail` and `GuarantorPhone`, 2,863 each, two of the eight
    columns the portal's lead list renders. Nothing about the table said so;
    they simply were not there.
    """
    from rdflib import URIRef, Literal

    g = URIRef(GRAPH)
    e = URIRef(f"{EX}n")
    outer, inner = URIRef(f"{EX}n_outer"), URIRef(f"{EX}n_inner")
    fe, cfe, se = URIRef(f"{EX}n_fe"), URIRef(f"{EX}n_cfe"), URIRef(f"{EX}n_se")
    slot = URIRef(f"{EX}n_slot")
    OUTER_T, INNER_T = URIRef(f"{EX}OuterFrame"), URIRef(f"{EX}InnerFrame")

    await space_impl.add_rdf_quads_batch(test_space, [
        (e, URIRef(f"{KG}hasKGEntityType"), URIRef(ENTITY_TYPE), g),
        # entity -> outer frame
        (fe, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}Edge_hasEntityKGFrame"), g),
        (fe, URIRef(f"{CORE}hasEdgeSource"), e, g),
        (fe, URIRef(f"{CORE}hasEdgeDestination"), outer, g),
        (outer, URIRef(f"{KG}hasKGFrameType"), OUTER_T, g),
        # outer -> inner frame, the hop the first version could not follow
        (cfe, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}Edge_hasKGFrame"), g),
        (cfe, URIRef(f"{CORE}hasEdgeSource"), outer, g),
        (cfe, URIRef(f"{CORE}hasEdgeDestination"), inner, g),
        (inner, URIRef(f"{KG}hasKGFrameType"), INNER_T, g),
        # inner frame -> slot
        (se, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}Edge_hasKGSlot"), g),
        (se, URIRef(f"{CORE}hasEdgeSource"), inner, g),
        (se, URIRef(f"{CORE}hasEdgeDestination"), slot, g),
        (slot, URIRef(f"{KG}hasKGSlotType"), URIRef(SLOT_TYPE), g),
        (slot, URIRef(f"{KG}hasTextSlotValue"), Literal("nested"), g),
    ])

    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow(f"""
            SELECT s.value_text,
                   (SELECT array_agg(tt.term_text ORDER BY o)
                    FROM unnest(s.frame_type_path) WITH ORDINALITY u(x, o)
                    JOIN {test_space}_term tt ON tt.term_uuid = u.x) AS path
            FROM {test_space}_entity_slot_sort s
            WHERE s.value_text = 'nested'""")

    assert row is not None, (
        "a slot under a CHILD frame is missing from the table — the walk stopped "
        "at one hop, which is what hid GuarantorEmail/GuarantorPhone entirely")
    assert list(row["path"]) == [str(OUTER_T), str(INNER_T)], (
        f"frame_type_path is {row['path']} — it must be the ORDERED types from "
        f"the entity down to the slot's parent, because that is what a "
        f"SortCriteria.frame_path names and what the reader matches against")
    assert await _drift(pg_pool, test_space) == 0


async def test_resync_and_incremental_agree(test_space, space_impl, pg_pool):
    """A full rebuild must reproduce what the write path built incrementally.

    The two derivations are the same SQL by construction (`_select_rows`), and
    this is what keeps that true — `edge` had an ensure path and a resync path
    that were separately defective, which is how a production table drifted 25%
    incomplete.
    """
    await space_impl.add_rdf_quads_batch(test_space, _quads(ENTITIES))
    incremental = await _rows(pg_pool, test_space)

    from vitalgraph.db.sparql_sql.sync_entity_slot_sort import resync_entity_slot_sort
    async with pg_pool.acquire() as conn:
        await resync_entity_slot_sort(conn, test_space)
    rebuilt = await _rows(pg_pool, test_space)

    assert sorted(incremental) == sorted(rebuilt), (
        f"incremental {incremental} != rebuilt {rebuilt}")
