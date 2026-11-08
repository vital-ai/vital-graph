"""The `cjk` FTS pseudo-language, against real PostgreSQL (`issues/333`).

PostgreSQL's default parser makes an unspaced Chinese/Japanese run ONE lexeme,
so "樓梯" could not match "我夢到樓梯". A `cjk` index indexes each run of CJK
characters as bigrams + unigrams (`vitalgraph_cjk_*`, `sparql_sql_admin`),
and a query becomes the same units.

Needs the functions on the database: `scripts/install_sql_functions.py
--apply` (a new database gets them from `init_tables`).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import List, Optional

import pytest
import pytest_asyncio

from vitalgraph.db.sparql_sql import fast_fts_frame
from vitalgraph.db.sparql_sql.fts_languages import (
    missing_cjk_functions, tsquery_expr, tsvector_expr,
)
from vitalgraph.db.sparql_sql.space_names import space_prefix
from vitalgraph.vectorization import fts_index_lifecycle
from vitalgraph.vectorization.fts_index_lifecycle import (
    FtsRefreshIncomplete, ensure_fts_index, get_fts_index, refresh_fts_tsv,
    update_fts_languages,
)

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

GRAPH = "urn:inttest:cjk"
ENTITY_TYPE = "urn:inttest:kg:entity:Message"
SLOT_TYPE = "urn:inttest:kg:slot:MessageText"

# id -> text. The expectations below are by id.
DOCS = {
    "dream": "我夢到樓梯，海邊。",              # zh-Hant
    "beach": "我去了海邊",                     # zh-Hant, shares 海邊
    "simplified": "我梦到楼梯",                # zh-Hans: different code points
    "cat": "貓在樓梯上",                       # zh-Hant, shares 樓梯
    "japanese": "ひらがなとカタカナと漢字",
    "mixed": "我在 Starbucks 等你",
    "english": "I dreamed of running down the stairs",
}


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _functions_installed(pg_conn):
    missing = await missing_cjk_functions(pg_conn)
    if missing:
        pytest.fail(f"cjk functions missing on the test database: {missing}; "
                    f"run scripts/install_sql_functions.py --apply")


async def _hits(pg_conn, languages, query) -> List[str]:
    """Which DOCS match `query` under `languages`, through the shared builders
    — the exact expressions the trigger and every query path emit."""
    rows = await pg_conn.fetch(
        f"SELECT id FROM (SELECT d.key AS id, {tsvector_expr(languages, 'd.value')} AS tsv "
        f"FROM jsonb_each_text($2::jsonb) d) x "
        f"WHERE tsv @@ {tsquery_expr(languages, '$1')} ORDER BY id",
        query, json.dumps(DOCS))
    return [r["id"] for r in rows]


class TestTheFunctions:
    async def test_they_are_immutable_and_parallel_safe(self, pg_conn):
        rows = await pg_conn.fetch(
            "SELECT proname, provolatile::text, proparallel::text FROM pg_proc "
            "WHERE proname LIKE 'vitalgraph_cjk_%' ORDER BY 1")
        assert [r["proname"] for r in rows] == [
            "vitalgraph_cjk_index_text", "vitalgraph_cjk_query_terms",
            "vitalgraph_cjk_runs", "vitalgraph_cjk_tsquery", "vitalgraph_cjk_tsvector"]
        assert all(r["provolatile"] == "i" and r["proparallel"] == "s" for r in rows)

    @pytest.mark.parametrize("text,lexemes", [
        ("我夢到樓梯，海邊。", {"我夢", "夢到", "到樓", "樓梯", "海邊",
                             "我", "夢", "到", "樓", "梯", "海", "邊"}),
        ("夢", {"夢"}),
        ("ｶﾀｶﾅ", {"カタ", "タカ", "カナ", "カ", "タ", "ナ"}),       # NFKC half-width
        ("豈", {"豈"}),                                        # compatibility ideograph
        ("\U00020BB7野", {"\U00020BB7野", "\U00020BB7", "野"}),       # Extension B
        ("hello world 123", set()),
        ("", set()),
    ])
    async def test_index_lexemes(self, pg_conn, text, lexemes):
        got = await pg_conn.fetchval(
            "SELECT array_agg(lexeme) FROM unnest(vitalgraph_cjk_tsvector($1))", text)
        assert set(got or []) == lexemes

    async def test_null_indexes_as_empty(self, pg_conn):
        assert await pg_conn.fetchval(
            "SELECT vitalgraph_cjk_tsvector(NULL) = ''::tsvector")

    async def test_bigrams_come_first_so_phrases_hold(self, pg_conn):
        assert await pg_conn.fetchval(
            "SELECT vitalgraph_cjk_tsvector('我夢到樓梯') @@ "
            "'夢到 <-> 到樓 <-> 樓梯'::tsquery")

    @pytest.mark.parametrize("query,expected", [
        ("記得我夢到樓梯那個夢嗎",
         "'記得' | '得我' | '我夢' | '夢到' | '到樓' | '樓梯' | '梯那' | '那個' | '個夢' | '夢嗎'"),
        ("夢", "'夢'"),
        ('"夢到樓梯"', "'夢到' <-> '到樓' <-> '樓梯'"),
        ("海邊 -樓梯", "'海邊' & !'樓梯'"),
        ('海邊 -"夢到樓梯"', "'海邊' & !( '夢到' <-> '到樓' <-> '樓梯' )"),
        ("樓梯 or dream", "'樓梯'"),
        ("樓梯' | !x \\ ) & (", "'樓梯'"),            # nothing reaches tsquery syntax
    ])
    async def test_query_shapes(self, pg_conn, query, expected):
        assert await pg_conn.fetchval(
            "SELECT vitalgraph_cjk_tsquery($1)::text", query) == expected

    @pytest.mark.parametrize("query", ["dream", "-樓梯", "", "   ", None])
    async def test_no_positive_cjk_is_null(self, pg_conn, query):
        assert await pg_conn.fetchval("SELECT vitalgraph_cjk_tsquery($1)", query) is None


class TestMatching:
    LANGS = ["english", "cjk"]

    @pytest.mark.parametrize("query,expected", [
        ("樓梯", ["cat", "dream"]),
        ("夢", ["dream"]),                       # one character inside a run
        ('"夢到樓梯"', ["dream"]),
        ('"樓梯海邊"', []),                       # spans a punctuation boundary
        ("海邊 -樓梯", ["beach"]),
        ("楼梯", ["simplified"]),                # Simplified does NOT match Traditional
        ("記得我夢到樓梯那個夢嗎", ["cat", "dream"]),
        ("漢字", ["japanese"]),
        ("カタカナ", ["japanese"]),
        ("等你", ["mixed"]),
        ("starbucks", ["mixed"]),                 # the english arm still works
        ("stairs", ["english"]),
        ("running", ["english"]),
    ])
    async def test_english_plus_cjk(self, pg_conn, query, expected):
        assert await _hits(pg_conn, self.LANGS, query) == expected

    async def test_cjk_alone_matches_nothing_for_latin(self, pg_conn):
        assert await _hits(pg_conn, ["cjk"], "stairs") == []
        assert await _hits(pg_conn, ["cjk"], "樓梯") == ["cat", "dream"]

    async def test_without_cjk_a_run_is_one_lexeme(self, pg_conn):
        """The defect this fixes, pinned as a control."""
        assert await _hits(pg_conn, ["english"], "樓梯") == []

    async def test_ranking_prefers_more_shared_pairs(self, pg_conn):
        q = tsquery_expr(["cjk"], "$1")
        rows = await pg_conn.fetch(
            f"SELECT t, ts_rank_cd(vitalgraph_cjk_tsvector(t), {q}) AS r "
            f"FROM unnest($2::text[]) t ORDER BY r DESC",
            "我夢到樓梯", ["貓在樓梯上", "我夢到樓梯，海邊。"])
        assert rows[0]["t"] == "我夢到樓梯，海邊。"


@dataclass
class _Target:
    slot_type: str = SLOT_TYPE


@dataclass
class _Fts:
    text: str = ""
    index_name: str = "msg"
    targets: List[_Target] = field(default_factory=lambda: [_Target()])


@dataclass
class _Criteria:
    fts_criteria: _Fts
    entity_type: str = ENTITY_TYPE
    graph_uri: str = GRAPH
    entity_property_filters: Optional[list] = None
    sort_criteria: Optional[list] = None


async def _load(pg_conn, space, index, languages):
    """An index with one slot per DOCS entry, each in its own frame, written
    through the trigger, plus the `entity_slot_sort` rows the fast path reads."""
    assert await ensure_fts_index(pg_conn, space, index, languages)
    p = space_prefix(space)
    ctx = fast_fts_frame._term_uuid(GRAPH)
    for key, text in DOCS.items():
        slot = uuid.uuid4()
        frame_uri = f"urn:inttest:cjk:frame:{key}"
        frame = fast_fts_frame._term_uuid(frame_uri)
        await pg_conn.execute(
            f"INSERT INTO {p}_fts_{index} (subject_uuid, context_uuid, search_text) "
            f"VALUES ($1, $2, $3)", slot, ctx, text)
        await pg_conn.execute(
            f"INSERT INTO {p}_term (term_uuid, term_text, term_type) VALUES ($1, $2, 'U') "
            f"ON CONFLICT DO NOTHING", frame, frame_uri)
        await pg_conn.execute(
            f"INSERT INTO {p}_entity_slot_sort (slot_uuid, context_uuid, entity_uuid, "
            f"frame_uuid, entity_type_uuid, slot_type_uuid, value_text) "
            f"VALUES ($1, $2, $3, $4, $5, $6, $7)",
            slot, ctx, uuid.uuid4(), frame, fast_fts_frame._term_uuid(ENTITY_TYPE),
            fast_fts_frame._term_uuid(SLOT_TYPE), text)


async def _fast_path(pg_conn, space, index, text):
    resolved = await fast_fts_frame._resolve_index(pg_conn, space, index)
    crit = _Criteria(fts_criteria=_Fts(text=text, index_name=index))
    sql, args = fast_fts_frame._build(space, crit, *resolved, for_count=False,
                                      cap=None, page_size=100, offset=0)
    page = sorted(r["frame_uri"].rsplit(":", 1)[1] for r in await pg_conn.fetch(sql, *args))
    csql, cargs = fast_fts_frame._build(space, crit, *resolved, for_count=True,
                                        cap=1000, page_size=0, offset=0)
    return page, await pg_conn.fetchval(csql, *cargs)


class TestAnIndex:
    async def test_the_trigger_and_the_fast_path(self, pg_conn, test_space):
        await _load(pg_conn, test_space, "msg", ["english", "cjk"])
        for query, expected in [("樓梯", ["cat", "dream"]), ("夢", ["dream"]),
                                ("stairs", ["english"]), ("楼梯", ["simplified"])]:
            page, count = await _fast_path(pg_conn, test_space, "msg", query)
            assert page == expected, query
            assert count == len(expected), query

    async def test_cjk_only_index_with_a_latin_query(self, pg_conn, test_space):
        await _load(pg_conn, test_space, "only", ["cjk"])
        assert await _fast_path(pg_conn, test_space, "only", "stairs") == ([], 0)
        assert await _fast_path(pg_conn, test_space, "only", "樓梯") == (["cat", "dream"], 2)


class TestAddingCjkToAnIndex:
    async def _tsv_matches_a_fresh_build(self, pg_conn, space, index, languages):
        p = space_prefix(space)
        expr = tsvector_expr(languages, "COALESCE(search_text, '')")
        return await pg_conn.fetchval(
            f"SELECT count(*) FROM {p}_fts_{index} WHERE tsv IS DISTINCT FROM {expr}")

    async def test_update_refreshes_every_row_in_batches(self, pg_conn, test_space):
        await _load(pg_conn, test_space, "grow", ["english"])
        assert (await _fast_path(pg_conn, test_space, "grow", "樓梯"))[1] == 0
        # batch_size 2 over 7 rows: four batches, the keyset walk exercised.
        assert await update_fts_languages(pg_conn, test_space, "grow",
                                          ["english", "cjk"], batch_size=2)
        assert await self._tsv_matches_a_fresh_build(
            pg_conn, test_space, "grow", ["english", "cjk"]) == 0
        assert (await _fast_path(pg_conn, test_space, "grow", "樓梯"))[1] == 2

    async def test_an_interrupted_refresh_completes_on_rerun(self, pg_conn, test_space):
        await _load(pg_conn, test_space, "resume", ["english"])
        assert await update_fts_languages(pg_conn, test_space, "resume",
                                          ["english", "cjk"], refresh_tsv=False)
        # Every row with CJK text is stale; the English-only one is not, since
        # the cjk arm contributes nothing to Latin text.
        stale = await self._tsv_matches_a_fresh_build(
            pg_conn, test_space, "resume", ["english", "cjk"])
        assert stale == len(DOCS) - 1

        class Stop(Exception):
            pass

        def stop_after_first_batch(total):
            raise Stop

        with pytest.raises(Stop):
            await refresh_fts_tsv(pg_conn, test_space, "resume", batch_size=3,
                                  progress=stop_after_first_batch)
        partial = await self._tsv_matches_a_fresh_build(
            pg_conn, test_space, "resume", ["english", "cjk"])
        assert stale - 3 <= partial < stale, "the first batch was not committed"
        assert await refresh_fts_tsv(pg_conn, test_space, "resume",
                                     batch_size=3) == len(DOCS)
        assert await self._tsv_matches_a_fresh_build(
            pg_conn, test_space, "resume", ["english", "cjk"]) == 0

    async def test_new_writes_use_the_new_list_at_once(self, pg_conn, test_space):
        assert await ensure_fts_index(pg_conn, test_space, "trig", ["english"])
        assert await update_fts_languages(pg_conn, test_space, "trig",
                                          ["english", "cjk"], refresh_tsv=False)
        p = space_prefix(test_space)
        await pg_conn.execute(
            f"INSERT INTO {p}_fts_trig (subject_uuid, context_uuid, search_text) "
            f"VALUES ($1, $2, '我夢到樓梯')", uuid.uuid4(), uuid.uuid4())
        assert await pg_conn.fetchval(
            f"SELECT count(*) FROM {p}_fts_trig WHERE tsv @@ "
            f"{tsquery_expr(['english', 'cjk'], '$1')}", "樓梯") == 1

    async def test_a_failed_refresh_says_the_change_was_made(
            self, pg_conn, test_space, monkeypatch):
        assert await ensure_fts_index(pg_conn, test_space, "half", ["english"])

        async def boom(*a, **k):
            raise RuntimeError("statement timeout")

        monkeypatch.setattr(fts_index_lifecycle, "refresh_fts_tsv", boom)
        with pytest.raises(FtsRefreshIncomplete, match="refresh-fts"):
            await update_fts_languages(pg_conn, test_space, "half", ["english", "cjk"])
        assert (await get_fts_index(pg_conn, test_space, "half"))["languages"] == [
            "english", "cjk"]

    async def test_a_failed_trigger_replace_changes_nothing(
            self, pg_conn, test_space, monkeypatch):
        """Registry and trigger move in one transaction."""
        assert await ensure_fts_index(pg_conn, test_space, "atomic", ["english"])
        monkeypatch.setattr(
            fts_index_lifecycle.SparqlSQLSchema, "_build_tsv_concat_expr",
            staticmethod(lambda langs: "this is not sql"))
        with pytest.raises(Exception):
            await update_fts_languages(pg_conn, test_space, "atomic", ["english", "cjk"])
        assert (await get_fts_index(pg_conn, test_space, "atomic"))["languages"] == ["english"]
