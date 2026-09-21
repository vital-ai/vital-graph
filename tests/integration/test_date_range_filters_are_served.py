"""A dated listing is served from `entity_prop_sort`, and reads its bound as UTC.

`created_after` / `created_before` / `modified_after` / `modified_before` were
the only filters the fast path never served. The bound was bound as
`$n::timestamp`, which types the parameter as a timestamp, and asyncpg then
refuses the ISO string a listing actually holds:

    asyncpg.exceptions.DataError: invalid input for query argument $4:
        '2026-06-23T14:00:00.000Z' (expected a datetime.date or
        datetime.datetime instance, got 'str')

Both the page and the count caught that and declined, so the answer was right
and the listing paid the SPARQL walk every time. Nothing noticed because every
shape under test here filtered on `status` or sorted by name --
`test_count_and_page_move_together` has five shapes and not one of them carries
a date.

The second cell is the reason the fix is `vitalgraph_iso_to_utc` rather than a
`datetime` parsed in Python: `value_dt` is normalised to UTC, and a bound read
any other way compares against a column it does not agree with.

The frame twin's builder is pinned at unit level in
`tests/unit/sparql_sql/test_date_bounds_are_not_cast_to_timestamp.py`.
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
VITAL = "http://vital.ai/ontology/vital#"
AIMP = "http://vital.ai/ontology/vital-aimp#"
EX = "http://example.org/dated/"
GRAPH = "http://example.org/dated/graph"
ETYPE = f"{EX}DatedType"

# Created at three distinct instants, one per day, all in UTC.
ROWS = [("a", "2026-06-21T14:00:00.000Z"),
        ("b", "2026-06-22T14:00:00.000Z"),
        ("c", "2026-06-23T14:00:00.000Z")]


def _quads():
    from rdflib import URIRef, Literal
    from rdflib.namespace import XSD
    g = URIRef(GRAPH)
    out = []
    for n, created in ROWS:
        e = URIRef(f"{EX}{n}")
        out += [
            (e, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}KGEntity"), g),
            (e, URIRef(f"{KG}hasKGEntityType"), URIRef(ETYPE), g),
            (e, URIRef(f"{CORE}hasName"), Literal(n), g),
            (e, URIRef(f"{AIMP}hasObjectCreationTime"),
             Literal(created, datatype=XSD.dateTime), g),
            (e, URIRef(f"{VITAL}hasObjectModificationDateTime"),
             Literal(created, datatype=XSD.dateTime), g),
        ]
    return out


async def _page_and_count(space_impl, test_space, **kw):
    from vitalgraph.db.sparql_sql.fast_prop_sort import (
        fast_entity_prop_page, fast_entity_prop_count)
    page = await fast_entity_prop_page(space_impl, test_space, GRAPH, 50, 0, **kw)
    count = await fast_entity_prop_count(
        space_impl, test_space, GRAPH,
        **{k: v for k, v in kw.items() if k != "sort_order"})
    return page, count


@pytest.mark.parametrize("filters,expected", [
    ({"created_after": "2026-06-22T00:00:00.000Z"}, ["b", "c"]),
    ({"created_before": "2026-06-22T00:00:00.000Z"}, ["a"]),
    ({"modified_after": "2026-06-23T00:00:00.000Z"}, ["c"]),
    ({"modified_before": "2026-06-23T00:00:00.000Z"}, ["a", "b"]),
    # A range, which is two INTERSECTed arms rather than one.
    ({"created_after": "2026-06-22T00:00:00.000Z",
      "created_before": "2026-06-23T00:00:00.000Z"}, ["b"]),
    # A date filter beside one that already worked: the arms must compose.
    ({"created_after": "2026-06-22T00:00:00.000Z",
      "modified_before": "2026-06-23T00:00:00.000Z"}, ["b"]),
])
async def test_a_date_range_is_served_by_the_table(
        test_space, space_impl, filters, expected):
    await space_impl.add_rdf_quads_batch(test_space, _quads())

    page, count = await _page_and_count(
        test_space=test_space, space_impl=space_impl,
        entity_type_uri=ETYPE, filters=filters, sort_by=f"{CORE}hasName")

    assert page is not None, (
        f"the PAGE declined {filters} -- a dated listing falls back to the "
        f"SPARQL walk, which is the whole defect")
    assert count is not None, f"the COUNT declined {filters} while the page served it"
    assert [u.rsplit("/", 1)[-1] for u in page] == expected
    assert count == len(expected), f"count {count} != {len(expected)} for {filters}"


async def test_an_untyped_dated_listing_is_served_too(test_space, space_impl):
    """The untyped form builds its own SQL -- `fixed` is 1, not 2 -- and the
    count builds a `count(*)` over the INTERSECT rather than a
    `count(DISTINCT)`. Both carried the same cast, so both need a cell."""
    await space_impl.add_rdf_quads_batch(test_space, _quads())

    page, count = await _page_and_count(
        test_space=test_space, space_impl=space_impl,
        filters={"created_after": "2026-06-22T00:00:00.000Z"},
        sort_by=f"{CORE}hasName")

    assert page is not None, "the untyped PAGE declined a dated listing"
    assert count is not None, "the untyped COUNT declined a dated listing"
    assert [u.rsplit("/", 1)[-1] for u in page] == ["b", "c"]
    assert count == 2


async def test_the_bound_is_read_as_utc_like_the_column(test_space, space_impl):
    """An offset bound and its UTC equivalent must select the same entities.

    `value_dt` is `vitalgraph_iso_to_utc(term_text)`, so the row created at
    14:00Z is stored at 14:00. `::timestamp` would have read
    `2026-06-22T05:00:00+05:00` as 05:00 and taken in `b` as well -- a filter
    silently five hours wide, which is the failure that looks like working
    software.
    """
    await space_impl.add_rdf_quads_batch(test_space, _quads())

    as_utc, _ = await _page_and_count(
        test_space=test_space, space_impl=space_impl, entity_type_uri=ETYPE,
        filters={"created_after": "2026-06-23T00:00:00.000Z"},
        sort_by=f"{CORE}hasName")
    with_offset, _ = await _page_and_count(
        test_space=test_space, space_impl=space_impl, entity_type_uri=ETYPE,
        filters={"created_after": "2026-06-23T05:00:00+05:00"},
        sort_by=f"{CORE}hasName")

    assert as_utc is not None and with_offset is not None
    assert as_utc == with_offset == [f"{EX}c"], (
        f"the same instant written two ways selected different entities: "
        f"{as_utc} vs {with_offset}")
