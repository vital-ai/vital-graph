"""Under FROM / FROM NAMED a basic graph pattern keeps every triple (`issues/334`).

`collect._collect_bgp` handled the dataset clause inside its per-triple loop
and ended that branch with `return plan`, so the FIRST triple was collected and
the rest of the pattern was silently dropped. Since `605a9db2` (2026-08-24),
`SELECT ... FROM <g> WHERE { ?s :a ?x . ?s :b ?y }` matched every subject with
an `:a`, whether or not it had a `:b`: a WIDER answer, not an error.
"""

from __future__ import annotations

import pytest

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

G = "urn:inttest:from:g"
A, B, C = "urn:inttest:p:a", "urn:inttest:p:b", "urn:inttest:p:c"


async def _load(sparql_update, space):
    await sparql_update(
        f"INSERT DATA {{ GRAPH <{G}> {{ "
        f'<urn:s:all> <{A}> "1" . <urn:s:all> <{B}> "2" . <urn:s:all> <{C}> "3" . '
        f'<urn:s:a_only> <{A}> "1" . '
        f'<urn:s:ab> <{A}> "1" . <urn:s:ab> <{B}> "2" . }} }}', space)


@pytest.mark.parametrize("dataset", [f"FROM <{G}>", f"FROM <{G}> FROM NAMED <{G}>"])
async def test_every_triple_constrains_the_answer(
        sparql_execute, sparql_update, sparql_query_sql, test_space, dataset):
    await _load(sparql_update, test_space)
    q = f"SELECT ?s {dataset} WHERE {{ ?s <{A}> ?x . ?s <{B}> ?y . ?s <{C}> ?z }}"
    sql = await sparql_query_sql(q, test_space)
    assert sql.count("_rdf_quad AS q") == 3, "all three triple patterns are emitted"
    rows = await sparql_execute(q, test_space)
    subjects = sorted(r["s"]["value"] if isinstance(r["s"], dict) else r["s"] for r in rows)
    assert subjects == ["urn:s:all"]


async def test_graph_var_under_from_named(sparql_execute, sparql_update, test_space):
    await _load(sparql_update, test_space)
    q = (f"SELECT ?g ?s FROM NAMED <{G}> WHERE {{ GRAPH ?g {{ "
         f"?s <{A}> ?x . ?s <{B}> ?y }} }}")
    rows = await sparql_execute(q, test_space)
    subjects = sorted(r["s"]["value"] if isinstance(r["s"], dict) else r["s"] for r in rows)
    assert subjects == ["urn:s:ab", "urn:s:all"]
