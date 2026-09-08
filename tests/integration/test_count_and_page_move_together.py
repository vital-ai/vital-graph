"""The count and the page must serve the same shapes.

They run CONCURRENTLY and the request waits for both, so a fast page beside a
slow count buys nothing. That is what shipped: `fast_entity_page` was taught to
serve typed/filtered/sorted listings while `fast_entity_count` still declined
the identical shape, so the page returned in 0.4 ms and the count took a
`COUNT(DISTINCT)` over the quads — 30 s, killed by PROD_TRANSACTION_TIMEOUT.

It was deterministic and looked like contention: the FIRST page of a filter
combination paid it; every later page hit the count cache and came back in ~2 s.
Measured on production for the failing shape (typed + status=ACTIVE): 79,995
entities in 76.9 ms from the table.
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
EX = "http://example.org/cnt/"
GRAPH = "http://example.org/cnt/graph"
ETYPE = f"{EX}CountedType"
ROWS = [("a", "Active"), ("b", "Active"), ("c", "Closed")]


def _quads():
    from rdflib import URIRef, Literal
    g = URIRef(GRAPH)
    out = []
    for n, st in ROWS:
        e = URIRef(f"{EX}{n}")
        out += [
            (e, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}KGEntity"), g),
            (e, URIRef(f"{KG}hasKGEntityType"), URIRef(ETYPE), g),
            (e, URIRef(f"{CORE}hasName"), Literal(n), g),
            (e, URIRef(f"{AIMP}hasObjectStatusType"), URIRef(f"{EX}{st}"), g),
        ]
    return out


@pytest.mark.parametrize("kw,expected", [
    ({"entity_type_uri": ETYPE}, 3),
    ({"entity_type_uri": ETYPE, "filters": {"status": f"{EX}Active"}}, 2),
    ({"entity_type_uri": ETYPE, "sort_by": f"{CORE}hasName"}, 3),
])
async def test_the_count_serves_what_the_page_serves(
        test_space, space_impl, kw, expected):
    from vitalgraph.db.sparql_sql.fast_prop_sort import (
        fast_entity_prop_page, fast_entity_prop_count)

    await space_impl.add_rdf_quads_batch(test_space, _quads())

    page = await fast_entity_prop_page(space_impl, test_space, GRAPH, 50, 0, **kw)
    count = await fast_entity_prop_count(space_impl, test_space, GRAPH, **kw)

    assert page is not None, f"the PAGE declined {kw}"
    assert count is not None, (
        f"the COUNT declined {kw} while the page served it — they run "
        f"concurrently, so the request waits for the slow one and the fast "
        f"page buys nothing")
    assert count == expected, f"count {count} != {expected} for {kw}"
    assert len(page) == expected, f"page {len(page)} != {expected} for {kw}"


async def test_count_and_page_agree_on_every_shape_the_page_takes(
        test_space, space_impl):
    """Structural: any shape the page serves, the count must serve too."""
    from vitalgraph.db.sparql_sql.fast_prop_sort import (
        fast_entity_prop_page, fast_entity_prop_count)

    await space_impl.add_rdf_quads_batch(test_space, _quads())
    shapes = [
        {"entity_type_uri": ETYPE},
        {"entity_type_uri": ETYPE, "sort_by": f"{CORE}hasName"},
        {"entity_type_uri": ETYPE, "filters": {"status": f"{EX}Active"}},
        {"entity_type_uri": ETYPE, "filters": {"status": f"{EX}Active"},
         "sort_by": f"{CORE}hasName"},
        {"filters": {"status": f"{EX}Active"}},
    ]
    mismatched = []
    for kw in shapes:
        page = await fast_entity_prop_page(space_impl, test_space, GRAPH, 50, 0, **kw)
        count = await fast_entity_prop_count(space_impl, test_space, GRAPH, **kw)
        if (page is None) != (count is None):
            mismatched.append(f"{kw}: page={'served' if page is not None else 'declined'} "
                              f"count={'served' if count is not None else 'declined'}")
        elif page is not None and len(page) != count:
            mismatched.append(f"{kw}: page has {len(page)} rows, count says {count}")
    assert not mismatched, (
        "the page and the count disagree about what they can serve:\n  "
        + "\n  ".join(mismatched))
