"""A SERVICE clause silently annihilates the whole result set.

Federation is not implemented. That is a reasonable thing for a store to
choose — what is not reasonable is the way the choice is expressed. The
generator compiles the SERVICE block to an empty relation and INNER joins it:

    JOIN (SELECT 1 WHERE FALSE) AS j1 ON TRUE

An inner join against an empty relation annihilates everything. So a query
whose local pattern matches 3 subjects returns 0 rows, with no error, no
warning and no `vg:` marker in the SQL. The caller cannot tell "the remote
service had nothing for you" from "this store ignored a third of your query".

SPARQL 1.1 §10.2 defines both halves, and BOTH are wrong here:

  * plain `SERVICE` against an endpoint that cannot be reached is an ERROR.
    Returning zero rows is the one thing it must not do quietly.
  * `SERVICE SILENT` must behave as though the pattern matched a single empty
    solution, so the surrounding solutions SURVIVE. Here they are destroyed,
    which is the opposite of what SILENT asks for.

FIXED by rejecting at translation time (`map_op` fails closed). Both forms now
raise `UnsupportedSparqlElement`, which `execute_sparql_query` returns as
`success: False` with the message — a domain outcome, not a 500.

REJECTING `SILENT` IS A DELIBERATE DEVIATION from §10.2, and the cell below
says so rather than asserting compliance we do not have. SILENT exists to mean
"carry on if the remote is unavailable", and a strictly compliant store would
return the 3 local solutions. This store never attempts the call at all, so
"carrying on" would mean quietly returning an answer assembled from half the
query — the same silence this issue was filed about, merely better spelled. An
explicit refusal is the honest outcome while federation is unimplemented.

If federation is ever implemented, the SILENT cell is the one to change back.
See issues/211.
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

EX = "http://example.org/svc/"
KIND = f"{EX}kind"
REMOTE = "http://unreachable.invalid/sparql"


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def svc_space(make_space):
    return await make_space(f"{TEST_SPACE_PREFIX}svc_{uuid.uuid4().hex[:8]}")


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def seeded(svc_space, space_impl):
    graph = URIRef(f"urn:{svc_space}")
    backend = (space_impl.get_db_space_impl()
               if hasattr(space_impl, "get_db_space_impl") else space_impl)
    quads = [(URIRef(f"{EX}s{i}"), URIRef(KIND), URIRef(f"{EX}shared"), graph)
             for i in range(3)]
    await backend.add_rdf_quads_batch(svc_space, quads)
    return svc_space, str(graph)


async def _run(backend_adapter, space_id, sparql):
    from vitalgraph.kg_impl.kgentity_list_impl import _extract_bindings
    r = await backend_adapter.execute_sparql_query(space_id, sparql)
    return r, _extract_bindings(r) if r.get("success") is not False else []


def _local(graph):
    return f"SELECT ?s WHERE {{ GRAPH <{graph}> {{ ?s <{KIND}> <{EX}shared> }} }}"


def _with_service(graph, silent: bool):
    kw = "SERVICE SILENT" if silent else "SERVICE"
    return f"""
    SELECT ?s WHERE {{
        GRAPH <{graph}> {{ ?s <{KIND}> <{EX}shared> }}
        {kw} <{REMOTE}> {{ ?s ?p ?o }}
    }}"""


async def test_the_local_pattern_alone_matches(seeded, backend_adapter):
    """The control. Without it, every assertion below is vacuous."""
    space_id, graph = seeded
    _, rows = await _run(backend_adapter, space_id, _local(graph))
    assert len(rows) == 3, f"fixture did not seed: {len(rows)} rows"


async def test_unreachable_service_is_an_error_not_an_empty_answer(
        seeded, backend_adapter):
    space_id, graph = seeded
    result, rows = await _run(backend_adapter, space_id,
                              _with_service(graph, silent=False))
    failed = result.get("success") is False or result.get("error")
    assert failed or rows, (
        "an unreachable SERVICE returned success with zero rows — the caller "
        "cannot distinguish that from a legitimately empty remote result")


async def test_silent_service_is_refused_rather_than_silently_emptied(
        seeded, backend_adapter):
    """SILENT is refused too, and the refusal is explicit.

    §10.2 would have SILENT preserve the 3 local solutions. It does not here,
    and that is the deviation recorded in the module docstring: returning
    solutions assembled from half the query, without saying so, is the defect
    this file exists to prevent. What is asserted is the part that matters —
    the caller is TOLD, rather than handed a quietly wrong answer.
    """
    space_id, graph = seeded
    result, rows = await _run(backend_adapter, space_id,
                              _with_service(graph, silent=True))
    assert result.get("success") is False and result.get("error"), (
        "SERVICE SILENT returned success — either it federated (in which case "
        "assert the 3 solutions per §10.2 and update issues/211) or it "
        "annihilated them silently again")
    assert "SERVICE" in str(result["error"]), (
        f"the error must name what was refused, or the caller cannot act on "
        f"it: {result['error']!r}")
