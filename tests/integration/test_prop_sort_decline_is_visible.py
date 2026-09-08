"""Every decline says why, at INFO.

A fast path that declines silently is undiagnosable in a deployment running at
INFO. Production hit exactly that: `entity_prop_sort` was populated, correct,
owned by the app user, unblocked and readable, the wiring was deployed — and
the listing still fell to the SPARQL walk (3.7 s warm, 30 s when the
transaction timeout killed it) with nothing in the log saying why. Establishing
that took static analysis and a hand-off, because the one line that would have
answered it was at DEBUG.

Asserted on the LOG, not on the return value, because "returns None" was never
the problem — the problem was returning None without a reason.
"""

from __future__ import annotations

import logging

import pytest

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

CORE = "http://vital.ai/ontology/vital-core#"
GRAPH = "http://example.org/decl/graph"


async def test_an_untyped_unsorted_listing_says_why_it_declined(
        test_space, space_impl, caplog):
    """The remaining decline, and it must still explain itself.

    A TYPED listing with no sort is now served — that was the shape production
    was hitting, and it is fixed. What still defers is the UNTYPED default,
    which `fast_typed_subject_page` owns; serving it here too would give two
    paths that order pages differently.
    """
    from vitalgraph.db.sparql_sql.fast_prop_sort import fast_entity_prop_page

    with caplog.at_level(logging.INFO,
                         logger="vitalgraph.db.sparql_sql.fast_prop_sort"):
        got = await fast_entity_prop_page(
            space_impl, test_space, GRAPH, 25, 0,
            entity_type_uri=None, filters={}, sort_by=None)

    assert got is None
    msgs = [r.getMessage() for r in caplog.records]
    assert any("DECLINE" in m for m in msgs), (
        f"the decline was silent at INFO; production could not tell a declining "
        f"fast path from an absent one. records={msgs}")
    assert any("plain default path owns it" in m for m in msgs), (
        f"the reason is not in the message: {msgs}")


async def test_an_unexpressible_filter_names_the_key(test_space, space_impl, caplog):
    from vitalgraph.db.sparql_sql.fast_prop_sort import fast_entity_prop_page

    with caplog.at_level(logging.INFO,
                         logger="vitalgraph.db.sparql_sql.fast_prop_sort"):
        got = await fast_entity_prop_page(
            space_impl, test_space, GRAPH, 25, 0,
            filters={"something_new": "x"}, sort_by=f"{CORE}hasName")

    assert got is None
    msgs = [r.getMessage() for r in caplog.records]
    assert any("unexpressible filter key" in m for m in msgs), msgs


async def test_a_block_says_it_is_a_block(test_space, space_impl, pg_pool, caplog):
    """Distinguishable from every other decline — a block is an operator
    action, and the log has to name it as one."""
    from vitalgraph.db.sparql_sql.fast_prop_sort import fast_entity_prop_page

    async with pg_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO prop_sort_block (space_id, entity_type_uuid, reason) "
            "VALUES ($1, NULL, 'test') ON CONFLICT DO NOTHING", test_space)
    try:
        with caplog.at_level(logging.INFO,
                             logger="vitalgraph.db.sparql_sql.fast_prop_sort"):
            got = await fast_entity_prop_page(
                space_impl, test_space, GRAPH, 25, 0, sort_by=f"{CORE}hasName")
        assert got is None
        msgs = [r.getMessage() for r in caplog.records]
        assert any("blocked" in m for m in msgs), (
            f"a block did not identify itself: {msgs}")
    finally:
        async with pg_pool.acquire() as conn:
            await conn.execute("DELETE FROM prop_sort_block WHERE space_id = $1",
                               test_space)
