"""SELECT DISTINCT keeps a sub-SELECT's LIMIT and the query's ORDER BY (issue 323).

Two defects of the DISTINCT, on the default path:

- Its push-down (`emit_distinct`) emitted the pattern directly, skipping the
  modifiers between: a sub-SELECT's own LIMIT among them. `SELECT DISTINCT ?t
  { { SELECT ?t … LIMIT 2 } }` deduplicated every row.
- Jena's algebra puts ORDER below the DISTINCT, and deduplicating does not keep an
  order. Only a LIMIT above re-applied it, and on the text column alone: without a
  LIMIT the rows came back in hash order (ascending for a DESC), and with one a
  number sorted as text ("9" above "10").
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

EX = "http://example.org/dko/"
PFX = f"PREFIX ex: <{EX}>\n"


@pytest_asyncio.fixture(loop_scope="session")
async def space(make_space, sparql_update):
    s = await make_space()
    # five items, each with a kind and a score; ?score 1 and 2 belong to kind a only
    await sparql_update(PFX + """INSERT DATA {
        ex:i1 ex:kind ex:a ; ex:score 1 .
        ex:i2 ex:kind ex:a ; ex:score 2 .
        ex:i3 ex:kind ex:b ; ex:score 9 .
        ex:i4 ex:kind ex:c ; ex:score 10 .
        ex:i5 ex:kind ex:d ; ex:score 30 .
    }""", s)
    return s


def _last(rows, var):
    return [b[var]["value"].rsplit("/", 1)[-1] for b in rows]


async def test_distinct_keeps_the_sub_select_limit(space, sparql_execute):
    rows = await sparql_execute(PFX + """SELECT DISTINCT ?k WHERE {
        { SELECT ?k ?s WHERE { ?i ex:kind ?k ; ex:score ?s } ORDER BY ?s LIMIT 2 } }""", space)
    assert _last(rows, "k") == ["a"]                       # the two lowest scores are both kind a


async def test_distinct_order_desc_without_limit(space, sparql_execute):
    rows = await sparql_execute(PFX + """SELECT DISTINCT ?k WHERE { ?i ex:kind ?k } ORDER BY DESC(?k)""", space)
    assert _last(rows, "k") == ["d", "c", "b", "a"]


async def test_distinct_order_asc_without_limit(space, sparql_execute):
    rows = await sparql_execute(PFX + """SELECT DISTINCT ?k WHERE { ?i ex:kind ?k } ORDER BY ?k""", space)
    assert _last(rows, "k") == ["a", "b", "c", "d"]


async def test_distinct_numeric_order_with_limit(space, sparql_execute):
    rows = await sparql_execute(PFX + """SELECT DISTINCT ?s WHERE { ?i ex:score ?s } ORDER BY DESC(?s) LIMIT 3""", space)
    assert [b["s"]["value"] for b in rows] == ["30", "10", "9"]


async def test_distinct_numeric_order_without_limit(space, sparql_execute):
    rows = await sparql_execute(PFX + """SELECT DISTINCT ?s WHERE { ?i ex:score ?s } ORDER BY ?s""", space)
    assert [b["s"]["value"] for b in rows] == ["1", "2", "9", "10", "30"]
