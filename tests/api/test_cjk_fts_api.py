"""API: Chinese/Japanese message search through a `cjk` FTS index (`issues/333`).

End to end through the server: messages are written as entity -> frame -> text
slot, auto-sync indexes each slot into an `['english', 'cjk']` index under a
kgslot mapping, and a KGQuery frame search finds them. Before 333 an unspaced
run was ONE lexeme, so "樓梯" could not find "我夢到樓梯".

The match sets here are small, so the KGQuery FTS fast path declines and the
pipeline answers; the fast path's SQL is exercised on real data in
`tests/integration/test_cjk_fts.py`.

Needs the `vitalgraph_cjk_*` functions on the test database
(`scripts/install_sql_functions.py --apply`).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio

from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from vitalgraph.db.sparql_sql.space_names import space_prefix
from vitalgraph.model.kgentities_model import EntityQueryCriteria
from vitalgraph.model.kgqueries_model import FTSCriteria, FTSTarget, KGQueryCriteria
from vitalgraph.model.result_status import OperationStatus

pytestmark = [pytest.mark.api, pytest.mark.asyncio(loop_scope="session")]

NS = "http://vital.ai/test/cjk_fts/"
ENTITY_TYPE = f"{NS}entity:Conversation"
FRAME_TYPE = f"{NS}frame:Message"
SLOT_TYPE = f"{NS}slot:MessageText"
HAS_TEXT_SLOT_VALUE = "http://vital.ai/ontology/haley-ai-kg#hasTextSlotValue"
INDEX = f"cjk_msg_{uuid.uuid4().hex[:8]}"

MESSAGES = {
    "dream": "我夢到樓梯，海邊。",
    "beach": "我去了海邊",
    "simplified": "我梦到楼梯",
    "cat": "貓在樓梯上",
    "japanese": "ひらがなとカタカナと漢字",
    "mixed": "我在 Starbucks 等你",
    "english": "I dreamed of running down the stairs",
}


def _conversation(key: str, text: str):
    base = f"{NS}{key}_{uuid.uuid4().hex[:8]}"
    e = KGEntity()
    e.URI, e.name, e.kGEntityType = f"{base}/entity", f"conversation {key}", ENTITY_TYPE
    f = KGFrame()
    f.URI, f.name, f.kGFrameType = f"{base}/frame", f"message {key}", FRAME_TYPE
    s = KGTextSlot()
    s.URI, s.name, s.kGSlotType, s.textSlotValue = f"{base}/slot", "text", SLOT_TYPE, text
    ef = Edge_hasEntityKGFrame()
    ef.URI, ef.edgeSource, ef.edgeDestination = f"{base}/ef", e.URI, f.URI
    fs = Edge_hasKGSlot()
    fs.URI, fs.edgeSource, fs.edgeDestination = f"{base}/fs", f.URI, s.URI
    return str(f.URI), str(s.URI), [e, f, s, ef, fs]


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def cjk_space(vg_client, test_space, test_graph, pg_conn):
    missing = await pg_conn.fetch(
        "SELECT sig FROM unnest($1::text[]) sig WHERE to_regprocedure(sig) IS NULL",
        ["vitalgraph_cjk_tsvector(text)", "vitalgraph_cjk_tsquery(text)"])
    if missing:
        pytest.fail("cjk functions missing on the test database; run "
                    "scripts/install_sql_functions.py --apply")

    r = await vg_client.fts_indexes.create_index(
        space_id=test_space, index_name=INDEX, languages=["english", "cjk"])
    assert r.status == OperationStatus.CREATED, r.message
    m = await vg_client.search_mappings.create_mapping(
        space_id=test_space, index_name=INDEX, mapping_type="kgslot",
        type_uri=SLOT_TYPE, source_type="properties")
    await vg_client.search_mappings.add_property(
        space_id=test_space, mapping_id=m.mapping_id, property_uri=HAS_TEXT_SLOT_VALUE)

    # ONE CONVERSATION PER CREATE. A multi-entity batch leaves its frames and
    # slots without `hasKGGraphURI` (`issues/257`), so a frame query, which
    # joins the slot to its entity through it, finds none of them.
    frames, slots = {}, []
    for key, text in MESSAGES.items():
        frame_uri, slot_uri, objs = _conversation(key, text)
        frames[frame_uri] = key
        slots.append(slot_uri)
        cr = await vg_client.kgentities.create_kgentities(
            space_id=test_space, graph_id=test_graph, objects=objs)
        assert cr.is_success, cr.error_message

    # Auto-sync runs after the write returns.
    table = f"{space_prefix(test_space)}_fts_{INDEX}"
    n = 0
    for _ in range(60):
        n = await pg_conn.fetchval(f"SELECT count(*) FROM {table}")
        if n >= len(slots):
            break
        await asyncio.sleep(0.5)
    assert n == len(slots), f"auto-sync indexed {n} of {len(slots)} slots"
    yield {"space_id": test_space, "graph_id": test_graph, "frames": frames}
    try:
        await vg_client.fts_indexes.delete_index(test_space, INDEX)
    except Exception:
        pass


async def _search(vg_client, env, text):
    criteria = KGQueryCriteria(
        query_type="frame_query",
        source_entity_criteria=EntityQueryCriteria(entity_type=ENTITY_TYPE),
        fts_criteria=FTSCriteria(
            text=text, index_name=INDEX,
            targets=[FTSTarget(slot_type=SLOT_TYPE, frame_type=FRAME_TYPE, kind="msg")]),
    )
    resp = await vg_client.kgqueries.query_connections(
        space_id=env["space_id"], graph_id=env["graph_id"], criteria=criteria,
        page_size=50, offset=0)
    assert resp.success, getattr(resp, "message", resp)
    return sorted(env["frames"][f.frame_uri] for f in (resp.frame_results or []))


@pytest.mark.parametrize("query,expected", [
    ("樓梯", ["cat", "dream"]),
    ("夢", ["dream"]),
    ('"夢到樓梯"', ["dream"]),
    ("海邊 -樓梯", ["beach"]),
    ("楼梯", ["simplified"]),
    ("記得我夢到樓梯那個夢嗎", ["cat", "dream"]),
    ("漢字", ["japanese"]),
    ("等你", ["mixed"]),
    ("starbucks", ["mixed"]),
    ("stairs", ["english"]),
])
async def test_message_search(vg_client, cjk_space, query, expected):
    assert await _search(vg_client, cjk_space, query) == expected


async def test_ranked_text_search_scores_the_closer_message_higher(
        vg_client, cjk_space, pg_conn):
    """`ts_rank_cd` over the combined index: the message sharing more pairs
    with the question ranks first."""
    from vitalgraph.db.sparql_sql.fts_languages import tsquery_expr
    table = f"{space_prefix(cjk_space['space_id'])}_fts_{INDEX}"
    rows = await pg_conn.fetch(
        f"SELECT search_text FROM {table} WHERE tsv @@ {tsquery_expr(['english', 'cjk'], '$1')} "
        f"ORDER BY ts_rank_cd(tsv, {tsquery_expr(['english', 'cjk'], '$1')}) DESC",
        "我夢到樓梯")
    assert rows[0]["search_text"] == MESSAGES["dream"]
