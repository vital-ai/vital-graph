"""A `vg:` search inside `GRAPH <g>` reads g's side-table rows (`issues/333`).

The FTS and vector tables are per SPACE, keyed (subject, context). The score
and match subqueries were keyed on the subject alone, scoped to a graph only
under a server-side graph lock. A query's own `GRAPH <g>`, the usual way to
scope a search to one graph, scoped nothing, so in a space
holding the same subject in two graphs the lookup read whichever row came
first. `_context_clause` now scopes to the one constant graph the entity
variable is bound in.
"""

from __future__ import annotations

import re

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

G1, G2 = "urn:inttest:scoped:g1", "urn:inttest:scoped:g2"
S = "urn:inttest:scoped:msg"
TEXT = "urn:inttest:p:text"
DIMS = 384


def _vec(x: float) -> str:
    return "[" + ",".join([str(x)] + ["0.0"] * (DIMS - 1)) + "]"


def _query_vector(sql: str, x: float) -> str:
    return re.sub(r"'__VG_EMBED_\d+__'::vector", f"'{_vec(x)}'::vector", sql)


async def _setup(pg_conn, space, sparql_update):
    """The SAME subject in two graphs: g1 says 樓梯 (stairs), g2 says 海邊
    (beach); g1's vector points one way, g2's the opposite way."""
    assert await ensure_fts_index(pg_conn, space, "msg", ["english", "cjk"])
    assert await ensure_index(pg_conn, space, "msg", {
        "dimensions": DIMS, "distance_metric": "cosine",
        "provider": "paraphrase_multilingual_minilm_l12_v2",
        "model_name": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"})
    p = space_prefix(space)
    for g, text, x in ((G1, "我夢到樓梯", 1.0), (G2, "我去了海邊", -1.0)):
        await sparql_update(f'INSERT DATA {{ GRAPH <{g}> {{ <{S}> <{TEXT}> "{text}" . }} }}', space)
        await pg_conn.execute(
            f"INSERT INTO {p}_fts_msg (subject_uuid, context_uuid, search_text) "
            f"VALUES (vitalgraph_term_uuid($1, 'U'), vitalgraph_term_uuid($2, 'U'), $3) "
            f"ON CONFLICT DO NOTHING", S, g, text)
        await pg_conn.execute(
            f"INSERT INTO {p}_vec_msg (subject_uuid, context_uuid, embedding) "
            f"VALUES (vitalgraph_term_uuid($1, 'U'), vitalgraph_term_uuid($2, 'U'), $3::vector) "
            f"ON CONFLICT DO NOTHING", S, g, _vec(x))


def _hybrid(graph, text):
    return ('PREFIX vg: <http://vital.ai/ontology/vitalgraph#>\n'
            f'SELECT ?score WHERE {{ GRAPH <{graph}> {{ ?s <{TEXT}> ?t . '
            f'BIND(vg:hybridSearch(?s, "{text}", "msg", 0.0) AS ?score) }} }}')


def _match(graph, text):
    return ('PREFIX vg: <http://vital.ai/ontology/vitalgraph#>\n'
            f'SELECT ?s WHERE {{ GRAPH <{graph}> {{ ?s <{TEXT}> ?t . '
            f'FILTER(vg:textMatch(?s, "{text}", "msg")) }} }}')


def _value(row) -> float:
    """The projected variable's value column: the one without a `__` suffix."""
    [k] = [k for k in row.keys() if "__" not in k]
    return float(row[k] or 0)


async def test_the_full_text_score_comes_from_the_queried_graph(
        pg_conn, test_space, sparql_update, sparql_query_sql):
    await _setup(pg_conn, test_space, sparql_update)
    # alpha 0: full text only. 樓梯 is g1's text, not g2's.
    for graph, expect_positive in ((G1, True), (G2, False)):
        sql = _query_vector(await sparql_query_sql(_hybrid(graph, "樓梯"), test_space), 1.0)
        assert f"context_uuid = '" in sql, "the score subquery is scoped to the graph"
        [row] = await pg_conn.fetch(sql)
        score = _value(row)
        assert (score > 0) is expect_positive, (graph, score)


async def test_a_text_match_filter_reads_the_queried_graph(
        pg_conn, test_space, sparql_update, sparql_query_sql):
    await _setup(pg_conn, test_space, sparql_update)
    for graph, text, n in ((G1, "樓梯", 1), (G2, "樓梯", 0), (G2, "海邊", 1), (G1, "海邊", 0)):
        sql = await sparql_query_sql(_match(graph, text), test_space)
        assert len(await pg_conn.fetch(sql)) == n, (graph, text)


async def test_graph_var_scope_is_left_unscoped(sparql_query_sql, test_space, pg_conn, sparql_update):
    """`GRAPH ?g` binds no constant graph: no clause, as before."""
    await _setup(pg_conn, test_space, sparql_update)
    q = ('PREFIX vg: <http://vital.ai/ontology/vitalgraph#>\n'
         f'SELECT ?g ?s WHERE {{ GRAPH ?g {{ ?s <{TEXT}> ?t . '
         f'FILTER(vg:textMatch(?s, "樓梯", "msg")) }} }}')
    sql = await sparql_query_sql(q, test_space)
    assert "context_uuid = '" not in sql.split("tsv @@", 1)[-1][:400]
