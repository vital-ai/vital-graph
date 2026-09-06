"""A filtered, sorted list must be served from the slot-sort table.

`issues/172`. `can_serve_filter` declines when a sort is present and the sort
path declined when frame criteria were present, so a FILTERED, SORTED LIST — the
main list view — was served by neither and fell through to the general pipeline.

Measured on a 74.2M-quad fixture before the fix: the filter alone answered in
4-5ms, and the same filter WITH a sort did not finish in 120s. The plan showed
why — it materialised the whole match set through a GroupAggregate and sorted it
three times before the LIMIT applied, so all 78,496 matches were paid for to
return 50 rows.

Both halves are in one index: `idx_{space}_ess_text` is
(context, entity_type, frame_type_path, slot_type, value_text, entity_uuid).

THE ASSERTIONS THAT MATTER ARE THE CORRECTNESS ONES. A filtered sort that is
fast and wrong is worse than the timeout it replaces: it returns a page that
looks right. So these check the count agrees with the filter, that every
returned entity satisfies the criterion, and that a filter changes the result at
all — the last because a filter silently dropped would still be fast and would
still return fifty plausible rows.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import uuid

import pytest

from vitalgraph.db.sparql_sql.fast_slot_sort import can_serve

pytestmark = pytest.mark.asyncio(loop_scope="session")

_KG = "http://vital.ai/ontology/haley-ai-kg#"


def _criteria(with_filter, comparator="eq"):
    from vitalgraph.sparql.kg_query_builder import (
        EntityQueryCriteria, FrameCriteria, SlotCriteria, SortCriteria)
    c = EntityQueryCriteria(entity_type="urn:t:entity:E", entity_uris=None,
                            frame_criteria=[], use_edge_pattern=True)
    if with_filter:
        c.frame_criteria = [FrameCriteria(
            frame_type="urn:t:frame:F",
            slot_criteria=[SlotCriteria(slot_type="urn:t:slot:A",
                                        slot_class_uri=_KG + "KGURISlot",
                                        value="v1", comparator=comparator)])]
    c.sort_criteria = [SortCriteria(sort_type="entity_frame_slot",
                                    slot_type="urn:t:slot:B",
                                    slot_class_uri=_KG + "KGTextSlot",
                                    frame_path=["urn:t:frame:F"],
                                    sort_order="asc")]
    return c


def test_the_sort_path_now_accepts_equality_frame_criteria():
    """It declined these outright, which is what created the cliff."""
    assert can_serve(_criteria(with_filter=True)), (
        "a filtered, sorted list must be servable — declining it sends the "
        "main list view to a plan that did not finish in 120s")


def test_a_comparator_the_table_cannot_answer_still_declines():
    """A conjunction is served only when EVERY conjunct is.

    Applying part of a filter and ignoring the rest is a WRONG ANSWER, not a
    slow one, and it would look like a working page.
    """
    assert not can_serve(_criteria(with_filter=True, comparator="gte"))


def test_sort_only_is_unaffected():
    assert can_serve(_criteria(with_filter=False))


async def test_the_filter_is_actually_applied(pg_conn, test_space):
    """The assertion a silently-dropped filter would fail.

    Builds two entities, one matching the criterion and one not, and asserts the
    filtered page returns only the match. Without this, a filter that never
    reached the SQL would still return a fast, plausible page.
    """
    from vitalgraph.db.sparql_sql.fast_slot_sort import (
        fast_slot_sort_count, fast_slot_sort_page, _term_uuid)
    sp = test_space
    # The context is DERIVED from the graph URI (`_term_uuid` is a UUIDv5 over
    # it), not chosen — rows written under a random uuid are invisible to the
    # query, which is what a first version of this test did.
    graph = "urn:t:graph"
    ctx, ent_t = _term_uuid(graph), _term_uuid("urn:t:entity:E")
    fpath = [_term_uuid("urn:t:frame:F")]
    a, b = _term_uuid("urn:t:slot:A"), _term_uuid("urn:t:slot:B")

    rows = []
    for i, (e_uri, a_val) in enumerate((("urn:t:e:match", "v1"),
                                        ("urn:t:e:other", "v2"))):
        e = _term_uuid(e_uri)
        for tid, txt in ((e, e_uri),):
            await pg_conn.execute(
                f"INSERT INTO {sp}_term (term_uuid, term_text, term_type) "
                f"VALUES ($1,$2,'U') ON CONFLICT (term_uuid) DO NOTHING", tid, txt)
        rows += [(uuid.uuid4(), ctx, e, uuid.uuid4(), ent_t, fpath, a, a_val),
                 (uuid.uuid4(), ctx, e, uuid.uuid4(), ent_t, fpath, b, f"s{i}")]
    await pg_conn.executemany(
        f"INSERT INTO {sp}_entity_slot_sort (slot_uuid, context_uuid, entity_uuid,"
        f" frame_uuid, entity_type_uuid, frame_type_path, slot_type_uuid, value_text)"
        f" VALUES ($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT DO NOTHING", rows)

    await pg_conn.execute(
        f"INSERT INTO {sp}_term (term_uuid, term_text, term_type) "
        f"VALUES ($1,$2,'U') ON CONFLICT (term_uuid) DO NOTHING", ctx, graph)

    filtered = _criteria(with_filter=True)
    unfiltered = _criteria(with_filter=False)

    n_all = await fast_slot_sort_count(pg_conn, sp, graph, unfiltered)
    n_flt = await fast_slot_sort_count(pg_conn, sp, graph, filtered)
    assert n_all == 2, f"expected both entities unfiltered, got {n_all}"
    assert n_flt == 1, (
        f"expected the filter to exclude one entity, got {n_flt} — the count "
        f"ignoring the criteria would offer pages that do not exist")

    uris = await fast_slot_sort_page(pg_conn, sp, graph, filtered, 50, 0)
    assert uris == ["urn:t:e:match"], f"filtered page returned {uris}"
