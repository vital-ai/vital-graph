"""A page of rows must come back with its variables NAMED.

`issues/083`. Every test in this repo checked that the paging emitters produce
the right SQL and the right ROWS. None checked that the rows can be turned back
into SPARQL bindings, and that is where the criteria query was broken: the
unsorted paging path emitted correct SQL, returned 13 correct rows, and the API
reported a successful EMPTY page — because `var_map` was empty, so every row was
converted to a binding with no keys and the endpoint found no `?entity` in any
of them.

The gap was structural, not an oversight about one function. The perf benches
assert `len(rows)`, the plan tests assert SQL text, and the SQL is correct in
both. `sparql_execute` here goes one step further and runs
`_rows_to_sparql_bindings` with the generator's own `var_map` — the identical
conversion the server does — so a projection that cannot be named fails.

Both paging emitters build their own outer SELECT rather than delegating to
`emit_bgp`, and `emit_bgp` is what registers a variable. Neither registered, so
both are exercised here: two-phase at offset 0, and the deep-page emitter past
the first page.
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
EX = "http://example.org/kgb/"

ENTITY_TYPE = f"{KG}TestEntityType"
FRAME_TYPE = f"{KG}TestFrameType"
SLOT_TYPE = f"{KG}TestSlotType"

N_ENTITIES = 8


def _kg_insert() -> str:
    """Entity -> frame -> slot, wired with the edge shape KGQuery anchors on.

    The `vitaltype` edge triples matter: they are what lets the criteria become
    a semi-join, which is the precondition for the two-phase paging path. A
    flatter shape would emit ordinary SQL and would not exercise the bug.
    """
    lines = []
    for i in range(N_ENTITIES):
        e, f, s = f"{EX}e{i}", f"{EX}f{i}", f"{EX}s{i}"
        fe, se = f"{EX}fe{i}", f"{EX}se{i}"
        lines += [
            f"<{e}> <{KG}hasKGEntityType> <{ENTITY_TYPE}> .",
            f"<{fe}> <{CORE}vitaltype> <{KG}Edge_hasEntityKGFrame> .",
            f"<{fe}> <{CORE}hasEdgeSource> <{e}> .",
            f"<{fe}> <{CORE}hasEdgeDestination> <{f}> .",
            f"<{f}> <{KG}hasKGFrameType> <{FRAME_TYPE}> .",
            f"<{se}> <{CORE}vitaltype> <{KG}Edge_hasKGSlot> .",
            f"<{se}> <{CORE}hasEdgeSource> <{f}> .",
            f"<{se}> <{CORE}hasEdgeDestination> <{s}> .",
            f"<{s}> <{KG}hasKGSlotType> <{SLOT_TYPE}> .",
            f'<{s}> <{KG}hasTextSlotValue> "match_me"^^'
            f"<http://www.w3.org/2001/XMLSchema#string> .",
        ]
    return "INSERT DATA {\n" + "\n".join(lines) + "\n}"


def _criteria_sparql(limit: int, offset: int) -> str:
    """The unsorted criteria query, built the way the endpoint builds it."""
    from vitalgraph.sparql.kg_query_builder import (
        KGQueryCriteriaBuilder, EntityQueryCriteria, FrameCriteria, SlotCriteria)

    ec = EntityQueryCriteria(
        entity_type=ENTITY_TYPE,
        entity_uris=None,
        frame_criteria=[FrameCriteria(
            frame_type=FRAME_TYPE,
            slot_criteria=[SlotCriteria(slot_type=SLOT_TYPE, value="match_me",
                                        comparator="eq")])],
        sort_criteria=None,
        use_edge_pattern=True)
    return KGQueryCriteriaBuilder().build_entity_query_sparql(
        ec, None, limit, offset)


@pytest.mark.parametrize("offset", [0, 3])
async def test_criteria_page_bindings_carry_the_entity(
        test_space, sparql_update, sparql_execute, offset):
    """Every row of a criteria page must arrive as a NAMED `?entity` binding.

    offset 0 covers the two-phase emitter, offset 3 the deep-page emitter.
    Before the fix both returned rows whose bindings had no keys at all, which
    the endpoint reports as a successful empty page.
    """
    await sparql_update(_kg_insert(), test_space)

    bindings = await sparql_execute(_criteria_sparql(5, offset), test_space)

    assert bindings, (
        f"the criteria query returned NO bindings at offset {offset}; if the "
        f"SQL returned rows, the projection was not registered (issues/083)")

    # The failure this guards is not "wrong value" but "no key at all", so
    # check the key exists before checking what is under it.
    keyless = [b for b in bindings if "entity" not in b]
    assert not keyless, (
        f"{len(keyless)}/{len(bindings)} bindings have no 'entity' key — the "
        f"rows came back but var_map could not name them (issues/083). "
        f"Keys present: {sorted(bindings[0].keys())}")

    for b in bindings:
        assert b["entity"].get("value", "").startswith(EX), (
            f"unexpected entity value: {b['entity']}")
        assert b["entity"].get("type") == "uri"


async def test_pages_agree_with_the_whole_result_set(
        test_space, sparql_update, sparql_execute):
    """Paging must partition the match set — no row invented, none skipped.

    Pinned alongside the naming check because the two are easy to confuse: a
    page that returns nothing and a page that returns the wrong rows both look
    like "0 results" from the endpoint, and only one of them is a naming bug.
    """
    await sparql_update(_kg_insert(), test_space)

    everything = await sparql_execute(_criteria_sparql(100, 0), test_space)
    all_uris = [b["entity"]["value"] for b in everything]
    assert len(all_uris) == N_ENTITIES

    page1 = await sparql_execute(_criteria_sparql(5, 0), test_space)
    page2 = await sparql_execute(_criteria_sparql(5, 5), test_space)
    paged = [b["entity"]["value"] for b in page1] + \
            [b["entity"]["value"] for b in page2]

    assert len(set(paged)) == len(paged), "a row was returned on two pages"
    assert set(paged) == set(all_uris), (
        f"paging lost or invented rows: "
        f"missing={sorted(set(all_uris) - set(paged))} "
        f"extra={sorted(set(paged) - set(all_uris))}")
