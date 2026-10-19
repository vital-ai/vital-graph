"""A long value is written, and the sort tables answer correctly around the bound.

`issues/283`. The three sort tables btree-indexed the whole `value_text` (and
GIN-indexed `value_all`), and both index types cap an entry near 2.7 KB, so a
write carrying any longer value failed outright:

    index row size 3320 exceeds btree version 4 maximum 2704 for index
    "idx_<space>_ess_text"

Every space, every slot type -- `KGLongTextSlot` included, since the table
copies every slot's value. The indexes now cover the bounded `value_key`.

WRITES GO THROUGH `space_impl`, so the real sync modules derive the rows; the
`sparql_update` fixture bypasses them (see `test_entity_slot_sort_maintenance`).

THE VALUES ARE INCOMPRESSIBLE. PostgreSQL compresses an index entry before the
size check, so `"x" * 6000` would fit and this test would pass on the old
schema. Random hex does not compress.
"""

from __future__ import annotations

import re
import secrets

import pytest

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

KG = "http://vital.ai/ontology/haley-ai-kg#"
CORE = "http://vital.ai/ontology/vital-core#"
EX = "http://example.org/longval/"

ENTITY_TYPE = f"{EX}EntityType"
FRAME_TYPE = f"{EX}FrameType"
SLOT_TYPE = f"{EX}SlotType"
GRAPH = "http://example.org/longval/graph"


def _random_text(n: int) -> str:
    return secrets.token_hex(n // 2 + 1)[:n]


def _quads(entities: dict[str, dict]) -> list[tuple]:
    """Entity -> frame -> text slot, plus the entity's name and the frame's
    type description, so all three sort tables receive the values."""
    from rdflib import Literal, URIRef

    g = URIRef(GRAPH)
    out = []
    for name, spec in entities.items():
        e, f, s = (URIRef(f"{EX}{name}{x}") for x in ("", "_frame", "_slot"))
        fe, se = URIRef(f"{EX}{name}_fe"), URIRef(f"{EX}{name}_se")
        out += [
            (e, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}KGEntity"), g),
            (e, URIRef(f"{KG}hasKGEntityType"), URIRef(ENTITY_TYPE), g),
            (e, URIRef(f"{CORE}hasName"), Literal(spec.get("name", name)), g),
            (fe, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}Edge_hasEntityKGFrame"), g),
            (fe, URIRef(f"{CORE}hasEdgeSource"), e, g),
            (fe, URIRef(f"{CORE}hasEdgeDestination"), f, g),
            (f, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}KGFrame"), g),
            (f, URIRef(f"{KG}hasKGFrameType"), URIRef(FRAME_TYPE), g),
            (f, URIRef(f"{KG}hasKGFrameTypeDescription"),
             Literal(spec.get("description", "d")), g),
            (se, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}Edge_hasKGSlot"), g),
            (se, URIRef(f"{CORE}hasEdgeSource"), f, g),
            (se, URIRef(f"{CORE}hasEdgeDestination"), s, g),
            (s, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}KGTextSlot"), g),
            (s, URIRef(f"{KG}hasKGSlotType"), URIRef(SLOT_TYPE), g),
            (s, URIRef(f"{KG}hasTextSlotValue"), Literal(spec["value"]), g),
        ]
    return out


def _criteria(value=None, sort=False):
    from vitalgraph.sparql.kg_query_builder import (
        EntityQueryCriteria, FrameCriteria, SlotCriteria, SortCriteria)
    c = EntityQueryCriteria(entity_type=ENTITY_TYPE, entity_uris=None,
                            frame_criteria=[], use_edge_pattern=True)
    if value is not None:
        c.frame_criteria = [FrameCriteria(
            frame_type=FRAME_TYPE,
            slot_criteria=[SlotCriteria(slot_type=SLOT_TYPE,
                                        slot_class_uri=KG + "KGTextSlot",
                                        value=value, comparator="eq")])]
    if sort:
        c.sort_criteria = [SortCriteria(sort_type="entity_frame_slot",
                                        slot_type=SLOT_TYPE,
                                        slot_class_uri=KG + "KGTextSlot",
                                        frame_path=[FRAME_TYPE],
                                        sort_order="asc")]
    return c


async def test_long_values_are_written_to_all_three_tables(
        test_space, space_impl, pg_pool):
    """The failure itself: this write raised before the fix."""
    from vitalgraph.db.sparql_sql.sort_value_key import VALUE_KEY_CHARS
    from vitalgraph.db.sparql_sql.sync_entity_prop_sort import _u

    slot_value = _random_text(6000)
    name = _random_text(5000)
    description = _random_text(4000)
    await space_impl.add_rdf_quads_batch(test_space, _quads({
        "big": {"value": slot_value, "name": name, "description": description}}))

    async with pg_pool.acquire() as conn:
        ess = await conn.fetchrow(
            f"SELECT value_text, value_key FROM {test_space}_entity_slot_sort "
            f"WHERE entity_uuid = $1", _u(f"{EX}big"))
        eps = await conn.fetchrow(
            f"SELECT value_text, value_key, value_all FROM {test_space}_entity_prop_sort "
            f"WHERE entity_uuid = $1 AND property_uuid = $2",
            _u(f"{EX}big"), _u(f"{CORE}hasName"))
        fps = await conn.fetchrow(
            f"SELECT value_text, value_key, value_all FROM {test_space}_frame_prop_sort "
            f"WHERE frame_uuid = $1 AND property_uuid = $2",
            _u(f"{EX}big_frame"), _u(f"{KG}hasKGFrameTypeDescription"))

    assert ess is not None, "the slot row was not derived"
    assert ess["value_text"] == slot_value, (
        "value_text must stay whole -- slot_projection returns it to list views")
    assert ess["value_key"] == slot_value[:VALUE_KEY_CHARS]

    assert eps is not None and fps is not None, "a prop-sort row was not derived"
    for row, full in ((eps, name), (fps, description)):
        assert row["value_text"] == full
        assert row["value_key"] == full[:VALUE_KEY_CHARS]
        assert list(row["value_all"]) == [full[:VALUE_KEY_CHARS]], (
            "value_all elements must be bounded, or the GIN index rejects the write")


async def test_the_slot_paths_are_exact_around_the_bound(
        test_space, space_impl, pg_pool):
    """Short literals answered exactly from the key; long ones declined.

    `shared` is a prefix longer than the key, so `long_a` and `long_b` have
    IDENTICAL keys. Anything that answered from the key without the guard
    would treat them as equal.
    """
    from vitalgraph.db.sparql_sql.fast_slot_filter import (
        can_serve_filter, fast_slot_filter_page)
    from vitalgraph.db.sparql_sql.fast_slot_sort import (
        fast_slot_sort_count, fast_slot_sort_page)
    from vitalgraph.db.sparql_sql.sort_value_key import VALUE_KEY_CHARS

    shared = _random_text(VALUE_KEY_CHARS + 100)
    values = {"short_a": "alpha", "short_b": "bravo",
              "long_a": shared + "a" + _random_text(3000),
              "long_b": shared + "b" + _random_text(3000)}
    await space_impl.add_rdf_quads_batch(
        test_space, _quads({k: {"value": v} for k, v in values.items()}))

    async with pg_pool.acquire() as conn:
        # A short literal is served and exact.
        page = await fast_slot_filter_page(
            conn, test_space, GRAPH, _criteria("alpha"), 50, 0)
        assert page == [f"{EX}short_a"], page

        # The bounded key itself, as a literal one char short of the bound,
        # must match NOTHING: no stored value equals it, though it is a prefix
        # of two stored keys.
        probe = shared[:VALUE_KEY_CHARS - 1]
        assert can_serve_filter(_criteria(probe))
        assert await fast_slot_filter_page(
            conn, test_space, GRAPH, _criteria(probe), 50, 0) == []

        # A long literal is declined, not answered from a key it shares with
        # its neighbour.
        assert not can_serve_filter(_criteria(values["long_a"]))
        assert await fast_slot_filter_page(
            conn, test_space, GRAPH, _criteria(values["long_a"]), 50, 0) is None

        # The sort serves every entity, in key order. The two long values tie
        # on the key -- the documented caveat -- so only their position as a
        # pair is asserted.
        sort = _criteria(sort=True)
        assert await fast_slot_sort_count(conn, test_space, GRAPH, sort) >= 4
        page = await fast_slot_sort_page(conn, test_space, GRAPH, sort, 50, 0)
    # Key order, with the two long values collapsed to one position: they tie
    # on the key, so which comes first is the tie-break's business.
    def positions(names):
        out = []
        for n in names:
            n = "long" if n.startswith("long_") else n
            if not out or out[-1] != n:
                out.append(n)
        return out
    # The space is shared across this module, so other tests' entities are in
    # the page too.
    got = [n for n in (u.rsplit("/", 1)[-1] for u in page) if n in values]
    want = sorted(values, key=lambda k: values[k][:VALUE_KEY_CHARS])
    assert set(got) == set(values), got
    assert positions(got) == positions(want), got


async def test_the_text_sort_is_an_index_only_scan_on_the_key(
        test_space, pg_pool):
    """The point of the table is the index-only scan; moving the index to
    `value_key` must not lose it."""
    from vitalgraph.db.sparql_sql.fast_slot_sort import _term_uuid
    async with pg_pool.acquire() as conn:
        await conn.execute(f"ANALYZE {test_space}_entity_slot_sort")
        async with conn.transaction():
            await conn.execute("SET LOCAL enable_seqscan = off")
            await conn.execute("SET LOCAL enable_bitmapscan = off")
            plan = "\n".join(r[0] for r in await conn.fetch(
                f"EXPLAIN SELECT entity_uuid FROM {test_space}_entity_slot_sort "
                f"WHERE context_uuid = $1 AND entity_type_uuid = $2 "
                f"AND frame_type_path = $3 AND slot_type_uuid = $4 "
                f'ORDER BY value_key COLLATE "C", entity_uuid LIMIT 10',
                _term_uuid(GRAPH), _term_uuid(ENTITY_TYPE),
                [_term_uuid(FRAME_TYPE)], _term_uuid(SLOT_TYPE)))
    assert "Index Only Scan" in plan and "_ess_text" in plan, plan
    assert not re.search(r"^\s*(->\s+)?Sort\s+\(", plan, re.M), (
        f"the index no longer supplies the order:\n{plan}")
