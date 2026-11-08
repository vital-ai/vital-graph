"""The `cjk` arm ranks by rarity, not by how often a common pair repeats (`issues/333` D2).

A question shares its common pairs with many messages and its distinctive pair
with the one it means. `ts_rank_cd` weighs every matched pair alike and rewards
repetition, so a message repeating the common pair outranks the one with the
rare pair. Weighted by rarity (`fts_rarity`, from ANALYZE's element
statistics), the rare one comes first. Measured on DRCD: 0.682 -> 0.811 hit@3.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.space_names import space_prefix
from vitalgraph.vectorization.fts_index_lifecycle import ensure_fts_index

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

G = "urn:inttest:rarity:g"
T = "urn:inttest:p:text"
RARE = "urn:inttest:rarity:rare"


def _query(text):
    return ('PREFIX vg: <http://vital.ai/ontology/vitalgraph#>\n'
            f'SELECT ?s ?score WHERE {{ GRAPH <{G}> {{ ?s <{T}> ?t . '
            f'BIND(vg:textSearch(?s, "{text}", "msg") AS ?score) }} }} '
            f'ORDER BY DESC(?score) ?s LIMIT 3')


async def test_the_rare_pair_outranks_a_repeated_common_one(
        pg_conn, test_space, sparql_update, sparql_query_sql):
    assert await ensure_fts_index(pg_conn, test_space, "msg", ["english", "cjk"])
    p = space_prefix(test_space)
    assert await pg_conn.fetchval(
        "SELECT attstattarget FROM pg_attribute WHERE attrelid = $1::regclass "
        "AND attname = 'tsv'", f"{p}_fts_msg") == 1000, "a cjk index raises its tsv statistics"

    docs = {f"urn:inttest:rarity:common{i}": f"那個那個那個人說了那個{i}" for i in range(60)}
    docs[RARE] = "我夢到樓梯"
    triples = " ".join(f'<{s}> <{T}> "{t}" .' for s, t in docs.items())
    await sparql_update(f"INSERT DATA {{ GRAPH <{G}> {{ {triples} }} }}", test_space)
    for s, t in docs.items():
        await pg_conn.execute(
            f"INSERT INTO {p}_fts_msg (subject_uuid, context_uuid, search_text) "
            f"VALUES (vitalgraph_term_uuid($1, 'U'), vitalgraph_term_uuid($2, 'U'), $3)",
            s, G, t)
    await pg_conn.execute(f"ANALYZE {p}_fts_msg")

    sql = await sparql_query_sql(_query("那個樓梯"), test_space)
    assert "'樓梯'::tsquery THEN" in sql, "the score is rarity-weighted coverage"
    rows = await pg_conn.fetch(sql)
    top = [r for r in rows[0].values() if isinstance(r, str) and r.startswith("urn:")]
    assert top and top[0] == RARE, rows[0]

    # The same question scored by ts_rank_cd alone puts a repeated common pair first:
    # the defect this replaces, pinned as a control.
    tsq = ("COALESCE(websearch_to_tsquery('english'::regconfig, $1) || "
           "vitalgraph_cjk_tsquery($1), websearch_to_tsquery('english'::regconfig, $1))")
    [first] = await pg_conn.fetch(
        f"SELECT search_text FROM {p}_fts_msg WHERE tsv @@ {tsq} "
        f"ORDER BY ts_rank_cd(tsv, {tsq}) DESC LIMIT 1", "那個樓梯")
    assert first["search_text"] != docs[RARE]
