"""`{space}_entity_prop_sort` must never describe a graph that has moved.

The sibling of `test_entity_slot_sort_maintenance.py`, and the failure modes are
the sibling's, so the reasoning there applies here unchanged: a stale row is a
WRONG ORDER rather than a slow query, and for the filter gate it is a plausible
SUBSET rather than an error.

THE DANGEROUS ONE IS `test_removing_one_value_recomputes_the_min`, and it is
dangerous in a way the sibling has no equivalent of. This table stores the MIN of
a multi-valued property, so deleting ONE value of three must CHANGE the stored
key while the row survives. A sync that treats delete as "drop the row" gets a
missing entity; one that treats it as "nothing to do" keeps a MIN that is no
longer in the graph. Both leave the row COUNT either unchanged or changed in a
direction the drift probe reads as converged, so no count-based check can see it.

WRITES GO THROUGH `space_impl`, NOT THE `sparql_update` FIXTURE, for the reason
the sibling records: that fixture compiles SPARQL straight to SQL and maintains
no derived table, so a file written against it passes while testing none of the
write-path wiring.
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
AIMP = "http://vital.ai/ontology/vital-aimp#"
EX = "http://example.org/eps/"

ENTITY_TYPE = f"{EX}TestEntityType"
GRAPH = "http://example.org/eps/graph"

NAMES = {"a": "alpha", "b": "bravo", "c": "charlie"}
ACTIONS = [f"{EX}ActionM", f"{EX}ActionA", f"{EX}ActionZ"]


def _entity_quads(names: dict[str, str], actions: list[str] | None = None) -> list[tuple]:
    """(s, p, o, g) rdflib terms, the form the space impl's batch writers take."""
    from rdflib import URIRef, Literal

    g = URIRef(GRAPH)
    out = []
    for name, value in names.items():
        e = URIRef(f"{EX}{name}")
        out += [
            # Population membership: `fast_entity_page` pages on this, so an
            # entity without it is not one as far as this table is concerned.
            (e, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}KGEntity"), g),
            (e, URIRef(f"{KG}hasKGEntityType"), URIRef(ENTITY_TYPE), g),
            (e, URIRef(f"{CORE}hasName"), Literal(value), g),
            (e, URIRef(f"{AIMP}hasObjectStatusType"), URIRef(f"{EX}Active"), g),
        ]
        for a in (actions or []):
            out.append((e, URIRef(f"{KG}hasKGActionTypeList"), URIRef(a), g))
    return out


async def _rows(pg_pool, space: str, prop: str) -> dict[str, str]:
    """{entity local name: value_text} for one property."""
    async with pg_pool.acquire() as conn:
        recs = await conn.fetch(f"""
            SELECT et.term_text AS entity, s.value_text
            FROM {space}_entity_prop_sort s
            JOIN {space}_term et ON et.term_uuid = s.entity_uuid
            JOIN {space}_term pt ON pt.term_uuid = s.property_uuid
            WHERE pt.term_text = $1""", prop)
    return {r["entity"].rsplit("/", 1)[-1]: r["value_text"] for r in recs}


async def _all_values(pg_pool, space: str, entity: str, prop: str) -> list[str]:
    async with pg_pool.acquire() as conn:
        return await conn.fetchval(f"""
            SELECT s.value_all
            FROM {space}_entity_prop_sort s
            JOIN {space}_term et ON et.term_uuid = s.entity_uuid
            JOIN {space}_term pt ON pt.term_uuid = s.property_uuid
            WHERE et.term_text = $1 AND pt.term_text = $2""",
            f"{EX}{entity}", prop)


async def _drift(pg_pool, space: str) -> int:
    from vitalgraph.db.sparql_sql.sync_entity_prop_sort import entity_prop_sort_drift
    async with pg_pool.acquire() as conn:
        expected, actual = await entity_prop_sort_drift(conn, space)
    return expected - actual


async def test_insert_populates_the_table(test_space, space_impl, pg_pool):
    """The write path maintains it — not only the bulk resync."""
    await space_impl.add_rdf_quads_batch(test_space, _entity_quads(NAMES))

    rows = await _rows(pg_pool, test_space, f"{CORE}hasName")

    assert rows == {"a": "alpha", "b": "bravo", "c": "charlie"}, (
        f"the table does not describe the graph just written: {rows}")
    assert await _drift(pg_pool, test_space) == 0


async def test_a_changed_value_is_not_left_behind(test_space, space_impl, pg_pool):
    """Repoint a single-valued property; the row must follow it."""
    await space_impl.add_rdf_quads_batch(test_space, _entity_quads(NAMES))

    await space_impl.remove_rdf_quads_batch(test_space, _entity_quads({"b": "bravo"}))
    await space_impl.add_rdf_quads_batch(test_space, _entity_quads({"b": "zulu"}))

    rows = await _rows(pg_pool, test_space, f"{CORE}hasName")

    assert rows.get("b") == "zulu", (
        f"entity b still reads {rows.get('b')!r} — the row was not re-derived, "
        f"so the sort orders by a value the graph no longer contains")
    assert "bravo" not in rows.values(), f"stale value survives: {rows}"
    assert await _drift(pg_pool, test_space) == 0


async def test_multi_valued_property_keeps_the_min_and_every_value(
        test_space, space_impl, pg_pool):
    """The two gates read different columns of the same row.

    Sorting must see ONE key per entity or the entity is emitted once per value;
    filtering must see them all, because every `uri_list` operator is a
    membership test that the MIN cannot answer.
    """
    await space_impl.add_rdf_quads_batch(
        test_space, _entity_quads({"a": "alpha"}, actions=ACTIONS))

    prop = f"{KG}hasKGActionTypeList"
    rows = await _rows(pg_pool, test_space, prop)

    assert len(rows) == 1, (
        f"an entity with {len(ACTIONS)} values produced {len(rows)} rows; "
        f"sorting by this property would emit it once per value")
    assert rows["a"] == f"{EX}ActionA", (
        f"stored sort key is {rows['a']!r}, not the MIN of {sorted(ACTIONS)}")

    values = await _all_values(pg_pool, test_space, "a", prop)
    assert sorted(values) == sorted(ACTIONS), (
        f"value_all is {values} — a membership filter (has/has_any/has_all) "
        f"cannot be answered from what is stored")


async def test_removing_one_value_recomputes_the_min(
        test_space, space_impl, pg_pool):
    """THE INVISIBLE ONE. Delete of a multi-valued property is a RECOMPUTE.

    Removing `ActionA` — the lexically first of three — must move the stored key
    to `ActionM` and shorten `value_all`. The entity still has values, so the row
    must SURVIVE; a sync that drops it loses the entity from every sort, and one
    that does nothing keeps a MIN the graph no longer contains.

    Neither shows up in a row count, which is why this is asserted directly
    rather than left to the drift probe.
    """
    await space_impl.add_rdf_quads_batch(
        test_space, _entity_quads({"a": "alpha"}, actions=ACTIONS))
    prop = f"{KG}hasKGActionTypeList"
    assert (await _rows(pg_pool, test_space, prop))["a"] == f"{EX}ActionA"

    from rdflib import URIRef
    await space_impl.remove_rdf_quads_batch(test_space, [
        (URIRef(f"{EX}a"), URIRef(prop), URIRef(f"{EX}ActionA"), URIRef(GRAPH))])

    rows = await _rows(pg_pool, test_space, prop)
    assert "a" in rows, (
        "the row vanished when one of three values was removed — the entity "
        "still has values and must still be sortable")
    assert rows["a"] == f"{EX}ActionM", (
        f"stored sort key is still {rows['a']!r}; the MIN was not recomputed "
        f"after the value it named was deleted")

    values = await _all_values(pg_pool, test_space, "a", prop)
    assert f"{EX}ActionA" not in values, (
        f"deleted value survives in value_all {values} — a membership filter "
        f"would still match on it")
    assert await _drift(pg_pool, test_space) == 0


async def test_coverage_is_complete_once_written(test_space, space_impl, pg_pool):
    """Coverage is EXACT here, not a heuristic.

    `hasKGEntityType` is both the grouping key and one of the indexed
    properties, so every entity in the denominator must have at least that row.
    There is no "entity that legitimately has none" to explain a shortfall away.
    """
    from vitalgraph.db.sparql_sql.sync_entity_prop_sort import entity_prop_sort_coverage

    await space_impl.add_rdf_quads_batch(test_space, _entity_quads(NAMES))

    async with pg_pool.acquire() as conn:
        gaps = await entity_prop_sort_coverage(conn, test_space)

    assert gaps == [], f"coverage reports a shortfall on a freshly written space: {gaps}"


async def test_deleting_an_entity_removes_its_rows(test_space, space_impl, pg_pool):
    """The other direction: `041` left tables empty, a missing delete leaves them
    too full. Both have shipped."""
    await space_impl.add_rdf_quads_batch(test_space, _entity_quads(NAMES))
    await space_impl.remove_rdf_quads_batch(test_space, _entity_quads({"c": "charlie"}))

    rows = await _rows(pg_pool, test_space, f"{CORE}hasName")
    assert "c" not in rows, f"rows survive the entity they describe: {rows}"
    assert await _drift(pg_pool, test_space) == 0
