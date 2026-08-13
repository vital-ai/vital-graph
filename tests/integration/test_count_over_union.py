"""An aggregate over a UNION must count the rows the UNION actually returns.

This exists because a change that looked purely like an optimisation returned
ZERO for every such count, and returned it silently.

`compute_text_needed_vars` was taught to skip term-table text resolution for a
variable that is only ever COUNTed, on the grounds that COUNT aggregates the
UUID column. That is true of the aggregate — and false of the JOIN that feeds
it. `emit_join` compares the two sides on their TEXT columns:

    ON CAST(j0.v0 AS TEXT) = CAST(j1.v3 AS TEXT)

With text withheld, both sides are NULL, `NULL = NULL` never holds, the join
returns nothing, and COUNT reports 0. Measured on a real space: the same
pattern returned 4 rows as `SELECT DISTINCT ?slot` and 0 as
`COUNT(DISTINCT ?slot)`.

Two properties are asserted, and the pairing is the point — either alone can be
satisfied by a broken implementation:

  * the count equals the number of distinct rows the same pattern lists, so a
    count computed by a different path than the list cannot drift from it;
  * the count is non-zero for data that plainly exists, so "0" cannot pass as
    a legitimate empty answer.

The UNION is what triggers it. A count over a plain BGP was correct throughout,
which is why unit tests over simple aggregates did not catch this.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from rdflib import URIRef

from .conftest import skip_no_infra, TEST_SPACE_PREFIX

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

EX = "http://example.org/cou/"
TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
KIND = f"{EX}kind"
A, B = f"{EX}ClassA", f"{EX}ClassB"


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def union_space(make_space):
    return await make_space(f"{TEST_SPACE_PREFIX}cou_{uuid.uuid4().hex[:8]}")


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def seeded(union_space, space_impl):
    """Three subjects sharing a predicate, split across two classes.

    A UNION over the two classes must therefore see all three.
    """
    graph = URIRef(f"urn:{union_space}")
    backend = (space_impl.get_db_space_impl()
               if hasattr(space_impl, "get_db_space_impl") else space_impl)
    quads = []
    for i, cls in enumerate((A, A, B)):
        s = URIRef(f"{EX}s{i}")
        quads.append((s, URIRef(KIND), URIRef(f"{EX}shared"), graph))
        quads.append((s, URIRef(TYPE), URIRef(cls), graph))
    await backend.add_rdf_quads_batch(union_space, quads)
    return union_space, str(graph)


def _pattern(graph, aggregate: bool) -> str:
    select = ("SELECT (COUNT(DISTINCT ?s) AS ?c)" if aggregate
              else "SELECT DISTINCT ?s")
    return f"""
    {select} WHERE {{ GRAPH <{graph}> {{
        ?s <{KIND}> <{EX}shared> .
        {{ ?s a <{A}> . }} UNION {{ ?s a <{B}> . }}
    }} }}"""


async def _bindings(backend_adapter, space_id, sparql):
    from vitalgraph.kg_impl.kgentity_list_impl import _extract_bindings
    r = await backend_adapter.execute_sparql_query(space_id, sparql)
    assert r.get("success") is not False, f"query failed: {r.get('error')}"
    return _extract_bindings(r)


async def test_count_over_a_union_matches_the_listed_rows(seeded, backend_adapter):
    space_id, graph = seeded

    listed = await _bindings(backend_adapter, space_id, _pattern(graph, False))
    counted = await _bindings(backend_adapter, space_id, _pattern(graph, True))

    n = int(str(counted[0]["c"]["value"] if isinstance(counted[0]["c"], dict)
                else counted[0]["c"]))

    assert len(listed) == 3, (
        f"the UNION itself is wrong: expected 3 subjects, listed {len(listed)}")
    assert n == len(listed), (
        f"COUNT over the UNION returned {n} while the same pattern lists "
        f"{len(listed)} rows. A count that disagrees with its own list is the "
        f"shape of the text-vs-uuid join defect: the join compares text columns "
        f"that were never resolved, so it matches nothing.")


async def test_the_count_is_not_zero(seeded, backend_adapter):
    """Stated separately because zero is the value that reads as legitimate.

    A wrong count of 2 looks like a bug; a wrong count of 0 looks like an empty
    frame, an empty graph, or a filter that matched nothing.
    """
    space_id, graph = seeded
    counted = await _bindings(backend_adapter, space_id, _pattern(graph, True))
    n = int(str(counted[0]["c"]["value"] if isinstance(counted[0]["c"], dict)
                else counted[0]["c"]))
    assert n > 0, (
        "COUNT over a UNION returned 0 for data that exists — indistinguishable "
        "from a genuinely empty result, which is why this shipped unnoticed")


async def test_a_count_without_a_union_is_unaffected(seeded, backend_adapter):
    """The control. This case was correct throughout, so a failure here means
    something broader than the UNION path is wrong."""
    space_id, graph = seeded
    q = f"""
    SELECT (COUNT(DISTINCT ?s) AS ?c) WHERE {{ GRAPH <{graph}> {{
        ?s <{KIND}> <{EX}shared> .
    }} }}"""
    counted = await _bindings(backend_adapter, space_id, q)
    n = int(str(counted[0]["c"]["value"] if isinstance(counted[0]["c"], dict)
                else counted[0]["c"]))
    assert n == 3, f"plain-BGP count returned {n}, expected 3"
