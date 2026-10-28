"""The KG list sort puts subjects missing the sort property last, both ways (issue 326).

`KGSparqlUtils.build_sort_clauses` documents "subjects WITHOUT it sort last — in BOTH
directions". For sequence properties it said so with an `IF(BOUND(?v), 0, 1)` key;
for every other property it left the missing subjects to the engine's ordering of
an unbound value, so a descending sort put them FIRST, against the contract and the
SQL fast paths (`NULLS LAST` both ways). Built here exactly as the frames listing
builds its page.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from vitalgraph.kg_impl.kg_sparql_utils import KGSparqlUtils

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

EX = "http://example.org/ksm/"
NAME = f"{EX}name"


@pytest_asyncio.fixture(loop_scope="session")
async def space(make_space, sparql_update):
    s = await make_space()
    await sparql_update(f"""PREFIX ex: <{EX}>
        INSERT DATA {{
            ex:f1 a ex:F ; ex:name "bravo" .
            ex:f2 a ex:F ; ex:name "alpha" .
            ex:f3 a ex:F .
            ex:f4 a ex:F ; ex:name "charlie" .
            ex:f5 a ex:F .
        }}""", s)
    return s


async def _page(sparql_execute, space, order):
    optional, projection, order_clause = KGSparqlUtils.build_sort_clauses("?frame", NAME, order)
    q = f"""PREFIX ex: <{EX}>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?frame WHERE {{
            {{ SELECT DISTINCT ?frame {projection} WHERE {{
                ?frame a ex:F .
                {optional}
            }} }}
        }}
        {order_clause}"""
    rows = await sparql_execute(q, space)
    return [b["frame"]["value"].rsplit("/", 1)[-1] for b in rows]


async def test_ascending_missing_last(space, sparql_execute):
    assert await _page(sparql_execute, space, "asc") == ["f2", "f1", "f4", "f3", "f5"]


async def test_descending_missing_last(space, sparql_execute):
    assert await _page(sparql_execute, space, "desc") == ["f4", "f1", "f2", "f3", "f5"]
