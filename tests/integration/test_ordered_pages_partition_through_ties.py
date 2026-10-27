"""Pages of a user's ORDER BY partition the result, ties at the boundary included (issue 312).

SPARQL leaves the order of rows with equal sort keys undefined, so a page boundary
falling among ties took any of them: consecutive pages could repeat or skip rows,
differently per execution and per path. A page now sorts its projected variables
by term uuid after the user's keys (`collect._add_paging_tiebreak`).
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

EX = "http://example.org/opt/"
PFX = f"PREFIX ex: <{EX}>\n"
N = 40


@pytest_asyncio.fixture(loop_scope="session")
async def space(make_space, sparql_update):
    s = await make_space()
    # 40 subjects, 4 distinct ratings: 10-way ties at every page boundary of 7
    triples = " ".join(f"ex:s{i} ex:rating {i % 4} ; ex:name \"n{i % 3}\" ." for i in range(N))
    await sparql_update(PFX + f"INSERT DATA {{ {triples} }}", s)
    return s


async def _pages(sparql_execute, space, order: str, size: int):
    out = []
    for off in range(0, N, size):
        rows = await sparql_execute(PFX + f"""SELECT ?s ?r WHERE {{ ?s ex:rating ?r }}
            ORDER BY {order} LIMIT {size} OFFSET {off}""", space)
        out.append([b["s"]["value"] for b in rows])
    return out


@pytest.mark.parametrize("order", ["DESC(?r)", "?r", "?r DESC(?s)"])
async def test_pages_partition_the_ordered_result(space, sparql_execute, order):
    pages = await _pages(sparql_execute, space, order, 7)
    flat = [s for p in pages for s in p]
    assert len(flat) == N and len(set(flat)) == N      # no repeats, no gaps
    # and the same pages again: deterministic across executions
    assert await _pages(sparql_execute, space, order, 7) == pages


async def test_pages_follow_the_user_order(space, sparql_execute):
    rows = []
    for off in range(0, N, 7):
        rows += await sparql_execute(PFX + f"""SELECT ?s ?r WHERE {{ ?s ex:rating ?r }}
            ORDER BY DESC(?r) LIMIT 7 OFFSET {off}""", space)
    ratings = [int(b["r"]["value"]) for b in rows]
    assert ratings == sorted(ratings, reverse=True)
