"""A `vg:` score BIND is computed ONCE per row (`issues/333`).

The memory service's recall query is `BIND(vg:hybridSearch(...) AS ?score)
FILTER(?score > 0) ORDER BY DESC(?score) LIMIT 12` inside one member graph.
The hybrid compiles to a correlated subquery per candidate, and it was emitted
inline in every companion column, so PostgreSQL re-evaluated it for each
reference: three times per candidate on the default path (measured on 20,000
messages: 967 ms -> 403 ms once it is computed once). `emit_extend.compute_once`
puts it in a `LEFT JOIN LATERAL (... OFFSET 0)`.

Checked on real rows through EXPLAIN ANALYZE: the FTS side table is probed
exactly once per candidate, and the page is still the right one.
"""

from __future__ import annotations

import json

import pytest

from vitalgraph.db.sparql_sql.space_names import space_prefix
from vitalgraph.vectorization.fts_index_lifecycle import ensure_fts_index
from vitalgraph.vectorization.vector_index_lifecycle import ensure_index

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

GRAPH = "urn:inttest:score_once"
TEXT = "urn:inttest:p:text"
DIMS = 384
DOCS = {                       # id -> (text, first embedding component)
    "a": ("我夢到樓梯", 0.9),
    "b": ("貓在樓梯上", 0.5),
    "c": ("我去了海邊", 0.1),
    "d": ("stairs everywhere", 0.3),
    "e": ("nothing relevant", 0.2),
}


def _vec(x: float) -> str:
    return "[" + ",".join([str(x)] + ["0.01"] * (DIMS - 1)) + "]"


QUERY = (
    'PREFIX vg: <http://vital.ai/ontology/vitalgraph#>\n'
    f'SELECT ?s ?score ?t WHERE {{ GRAPH <{GRAPH}> {{\n'
    f'  ?s <{TEXT}> ?t .\n'
    '  BIND(vg:hybridSearch(?s, "樓梯", "msg", 0.5) AS ?score)\n'
    '  FILTER(?score > 0)\n'
    '} } ORDER BY DESC(?score) LIMIT 3'
)


async def _setup(pg_conn, space, sparql_update):
    assert await ensure_fts_index(pg_conn, space, "msg", ["english", "cjk"])
    assert await ensure_index(pg_conn, space, "msg", {
        "dimensions": DIMS, "distance_metric": "cosine",
        "provider": "paraphrase_multilingual_minilm_l12_v2",
        "model_name": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"})
    triples = " ".join(f'<urn:inttest:m:{k}> <{TEXT}> "{t}" .' for k, (t, _) in DOCS.items())
    await sparql_update(f"INSERT DATA {{ GRAPH <{GRAPH}> {{ {triples} }} }}", space)
    p = space_prefix(space)
    for k, (t, x) in DOCS.items():
        await pg_conn.execute(
            f"INSERT INTO {p}_fts_msg (subject_uuid, context_uuid, search_text) "
            f"VALUES (vitalgraph_term_uuid($1, 'U'), vitalgraph_term_uuid($2, 'U'), $3)",
            f"urn:inttest:m:{k}", GRAPH, t)
        await pg_conn.execute(
            f"INSERT INTO {p}_vec_msg (subject_uuid, context_uuid, embedding) "
            f"VALUES (vitalgraph_term_uuid($1, 'U'), vitalgraph_term_uuid($2, 'U'), $3::vector)",
            f"urn:inttest:m:{k}", GRAPH, _vec(x))


def _resolve_vectors(sql: str) -> str:
    """The query vector the server would embed: here a fixed one."""
    import re
    return re.sub(r"'__VG_EMBED_\d+__'::vector", f"'{_vec(0.9)}'::vector", sql)


def _loops_on(plan, table: str) -> int:
    """Total executions of every scan node on `table`."""
    n = 0
    if plan.get("Relation Name") == table:
        n += int(plan.get("Actual Loops", 0))
    for c in plan.get("Plans", []):
        n += _loops_on(c, table)
    return n


async def test_the_hybrid_score_is_computed_once_per_candidate(
        pg_conn, test_space, sparql_update, sparql_query_sql):
    await _setup(pg_conn, test_space, sparql_update)
    sql = _resolve_vectors(await sparql_query_sql(QUERY, test_space))
    assert "LEFT JOIN LATERAL" in sql
    vec_table = f"{space_prefix(test_space)}_vec_msg"
    assert sql.count(f"FROM {space_prefix(test_space)}_fts_msg f") == 1, (
        "the score subquery is emitted once, not once per companion column")

    [row] = await pg_conn.fetch(f"EXPLAIN (ANALYZE, FORMAT JSON) {sql}")
    plan = json.loads(row[0])[0]["Plan"]
    assert _loops_on(plan, f"{space_prefix(test_space)}_fts_msg") == len(DOCS), (
        "one FTS probe per candidate: the score is not re-evaluated for the "
        "FILTER, the ORDER BY or a companion column")
    assert _loops_on(plan, vec_table) == len(DOCS)

    rows = await pg_conn.fetch(sql)
    got = [r["v0"] if "v0" in r.keys() else r[0] for r in rows]
    # 樓梯 matches a and b lexically; a also has the closest vector.
    assert got[:2] == ["urn:inttest:m:a", "urn:inttest:m:b"]
    assert len(got) == 3
