"""A frame/slot sort must execute, and must return one row per entity.

`issues/096`, the half the unit test cannot reach. Two separate failures, and
the second only appears against data:

1. **It did not run at all.** `ORDER BY ?sort_val_0` over `SELECT DISTINCT
   ?entity` compiled (Jena accepts it despite SPARQL 1.1 §15.1) and then failed
   in Postgres — `column s0.v5 does not exist` — because the DISTINCT subquery
   never projected the ordering column. Every `entity_frame_slot` and
   `frame_slot` sort 500'd.

2. **Projecting the variable alone would have been wrong.** A value reached
   through a frame or slot is many-per-entity, so `SELECT DISTINCT ?entity
   ?sort_val_0` returns one row PER VALUE. On `cardiff_kg` that is not
   theoretical: 9,354 (entity-graph, slot-type) pairs carry more than one slot
   of the same type, and the naive form returned 4 rows for 1 entity. A page of
   25 rows is then fewer than 25 entities, with some repeated.

The fixture below gives ONE entity two slots of the sort type for exactly this
reason. A fixture with clean 1:1 data passes under both the correct fix and the
naive one, which is how a test like this ends up guarding nothing — the first
25 leads in `cardiff_kg` are 1:1 and did not distinguish them either.
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
EX = "http://example.org/kgsort/"

ENTITY_TYPE = f"{EX}TestEntityType"
FRAME_TYPE = f"{EX}TestFrameType"
SLOT_TYPE = f"{EX}TestSlotType"
TEXT_SLOT = f"{KG}KGTextSlot"

# Sort values chosen so lexical order is unambiguous and does not coincide with
# URI order: entity e0 must sort LAST ascending, so a query that silently orders
# by ?entity instead of by the slot value fails rather than passing by accident.
SORT_VALUES = {
    "e0": ["zulu"],
    "e1": ["alpha"],
    "e2": ["mike"],
    "e3": ["bravo"],
}
# e3 carries a SECOND slot of the same type, and that value is the largest in
# the set. Ascending, MIN("bravo", "zzz") keeps e3 second; descending, MAX picks
# "zzz" and moves it to the FRONT — past e0, which leads on its own value. One
# entity, one row, a different position by direction, which is what a DISTINCT
# projection cannot express and what picking MIN for both directions would miss
# (that would leave e3 third descending, sorted on "bravo").
#
# The first draft used "yankee" here, which is less than "zulu", so e3 landed in
# the same slot under MIN and MAX and the test could not tell them apart.
SORT_VALUES["e3"].append("zzz")

ASC_ORDER = ["e1", "e3", "e2", "e0"]     # alpha, bravo(MIN), mike, zulu
DESC_ORDER = ["e3", "e0", "e2", "e1"]    # zzz(MAX), zulu, mike, alpha


def _insert() -> str:
    """entity -> Edge_hasEntityKGFrame -> frame -> Edge_hasKGSlot -> slot.

    The `vitaltype` edge triples are what the builder's edge patterns anchor on;
    a flatter shape would not exercise the emitted query.
    """
    lines = []
    for name, values in SORT_VALUES.items():
        e, f = f"{EX}{name}", f"{EX}{name}_frame"
        fe = f"{EX}{name}_fe"
        lines += [
            f"<{e}> <{KG}hasKGEntityType> <{ENTITY_TYPE}> .",
            f"<{fe}> <{CORE}vitaltype> <{KG}Edge_hasEntityKGFrame> .",
            f"<{fe}> <{CORE}hasEdgeSource> <{e}> .",
            f"<{fe}> <{CORE}hasEdgeDestination> <{f}> .",
            f"<{f}> <{KG}hasKGFrameType> <{FRAME_TYPE}> .",
        ]
        for i, value in enumerate(values):
            s, se = f"{EX}{name}_slot{i}", f"{EX}{name}_se{i}"
            lines += [
                f"<{se}> <{CORE}vitaltype> <{KG}Edge_hasKGSlot> .",
                f"<{se}> <{CORE}hasEdgeSource> <{f}> .",
                f"<{se}> <{CORE}hasEdgeDestination> <{s}> .",
                f"<{s}> <{KG}hasKGSlotType> <{SLOT_TYPE}> .",
                f'<{s}> <{KG}hasTextSlotValue> "{value}"^^'
                f"<http://www.w3.org/2001/XMLSchema#string> .",
            ]
    return "INSERT DATA {\n" + "\n".join(lines) + "\n}"


def _sorted_sparql(order: str, limit: int = 10, offset: int = 0) -> str:
    """The sorted criteria query, built the way the endpoint builds it."""
    from vitalgraph.sparql.kg_query_builder import (
        EntityQueryCriteria, KGQueryCriteriaBuilder, SortCriteria)

    ec = EntityQueryCriteria(
        entity_type=ENTITY_TYPE,
        sort_criteria=[SortCriteria(
            "entity_frame_slot", slot_type=SLOT_TYPE, slot_class_uri=TEXT_SLOT,
            frame_path=[FRAME_TYPE], sort_order=order, priority=1)],
        use_edge_pattern=True)
    return KGQueryCriteriaBuilder().build_entity_query_sparql(ec, None, limit, offset)


def _names(bindings) -> list[str]:
    """Entity local names, in the order returned."""
    return [b["entity"]["value"].rsplit("/", 1)[-1] for b in bindings]


async def test_a_frame_slot_sort_executes_at_all(
        test_space, sparql_update, sparql_execute):
    """The regression proper: this raised `column s0.v5 does not exist`.

    Asserted before ordering, because a query that cannot run makes every other
    assertion here fail for the wrong reason.
    """
    await sparql_update(_insert(), test_space)

    bindings = await sparql_execute(_sorted_sparql("asc"), test_space)

    assert bindings, (
        "the sorted criteria query returned no bindings — before issues/096 it "
        "failed in SQL because ORDER BY named a column the DISTINCT subquery "
        "did not project")
    assert all("entity" in b for b in bindings)


@pytest.mark.parametrize("order,expected", [("asc", ASC_ORDER), ("desc", DESC_ORDER)])
async def test_entities_come_back_in_slot_value_order(
        test_space, sparql_update, sparql_execute, order, expected):
    """Sorted by the SLOT VALUE, not by URI and not by insertion order.

    e3 moves from second (ascending, MIN=bravo) to first (descending, MAX=zzz),
    so a builder that aggregated with the wrong function, or that ordered on the
    anchor, fails here rather than looking plausible.
    """
    await sparql_update(_insert(), test_space)

    bindings = await sparql_execute(_sorted_sparql(order), test_space)

    assert _names(bindings) == expected, (
        f"{order}: expected {expected}, got {_names(bindings)}")


async def test_an_entity_with_two_matching_slots_occupies_one_row(
        test_space, sparql_update, sparql_execute):
    """The half a 1:1 fixture cannot catch.

    e3 has two slots of the sort type. Under `SELECT DISTINCT ?entity
    ?sort_val_0` it occupies two rows, so a LIMIT 25 page holds 24 entities and
    shows one of them twice.
    """
    await sparql_update(_insert(), test_space)

    bindings = await sparql_execute(_sorted_sparql("asc"), test_space)
    names = _names(bindings)

    assert len(names) == len(set(names)), (
        f"duplicate entities in one page: {names}. The sort value is "
        f"many-per-entity, so it must be aggregated, not projected beside "
        f"?entity under DISTINCT (issues/096)")
    assert len(names) == len(SORT_VALUES), (
        f"expected {len(SORT_VALUES)} entities, got {len(names)}: {names}")


async def test_paging_partitions_the_sorted_set(
        test_space, sparql_update, sparql_execute):
    """Pages must tile the result set — none repeated, none skipped.

    Row duplication shows up as a short page long before it shows up as a wrong
    total, and paging is where a user would actually meet it.
    """
    await sparql_update(_insert(), test_space)

    everything = _names(await sparql_execute(_sorted_sparql("asc", 100, 0), test_space))
    page1 = _names(await sparql_execute(_sorted_sparql("asc", 2, 0), test_space))
    page2 = _names(await sparql_execute(_sorted_sparql("asc", 2, 2), test_space))

    assert everything == ASC_ORDER
    assert page1 + page2 == everything, (
        f"pages {page1} + {page2} do not reconstruct {everything}")
    assert not set(page1) & set(page2), "an entity appeared on two pages"
