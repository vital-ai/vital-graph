"""FTS index languages, against real PostgreSQL (`issues/333`).

Two live defects, both fixed here:

1. The KGQuery FTS fast path searched only the FIRST configured language, so
   on an `['english', 'spanish']` index a document matched only through the
   Spanish stemmer was found by the pipeline and silently missing from the
   fast path's page and count.

2. Index languages were never validated. An unknown name created the index
   cleanly (PL/pgSQL resolves `'x'::regconfig` only when the trigger fires),
   then every write into it failed inside auto-sync, which only logs, so
   the subject was never indexed. The name was also pasted unquoted into DDL
   run over the simple-query protocol: SQL injection for a space writer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, List, Optional

import pytest

from vitalgraph.db.sparql_sql import fast_fts_frame
from vitalgraph.db.sparql_sql.config_apply import apply_space_config
from vitalgraph.db.sparql_sql.config_export import CONFIG_VERSION
from vitalgraph.db.sparql_sql.space_names import space_prefix
from vitalgraph.vectorization.fts_index_lifecycle import (
    InvalidFtsLanguages, ensure_fts_index, get_fts_index, update_fts_languages,
)

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

GRAPH = "urn:inttest:fts_languages"
ENTITY_TYPE = "urn:inttest:kg:entity:Message"
SLOT_TYPE = "urn:inttest:kg:slot:MessageText"
FRAME_URI = "urn:inttest:frame:1"
# Only the Spanish stemmer links these: english keeps `corrimos` and
# `corrían` as different lexemes, spanish stems both to `corr`.
SPANISH_DOC = "los niños corrían por el parque"
SPANISH_QUERY = "corrimos"
INJECTION = "english'::regconfig, ''); CREATE TABLE inttest_pwned(x int); --"


@dataclass
class _Target:
    slot_type: str = SLOT_TYPE


@dataclass
class _Fts:
    text: str = SPANISH_QUERY
    index_name: str = "msg"
    targets: List[_Target] = field(default_factory=lambda: [_Target()])


@dataclass
class _Criteria:
    entity_type: str = ENTITY_TYPE
    fts_criteria: _Fts = field(default_factory=_Fts)
    graph_uri: str = GRAPH
    entity_property_filters: Optional[list] = None
    sort_criteria: Optional[list] = None


async def _fts_tables(conn, space_id) -> List[str]:
    rows = await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE tablename LIKE $1",
        f"{space_prefix(space_id)}_fts_%")
    return sorted(r["tablename"] for r in rows)


async def _trigger_source(conn, space_id, index_name) -> str:
    return await conn.fetchval(
        "SELECT prosrc FROM pg_proc WHERE proname = $1",
        f"{space_prefix(space_id)}_fts_{index_name}_tsv_trigger")


class TestTheFastPathSearchesEveryLanguage:
    async def test_a_spanish_only_hit_is_found(self, pg_conn, test_space):
        assert await ensure_fts_index(pg_conn, test_space, "msg",
                                      ["english", "spanish"])
        p = space_prefix(test_space)
        ctx = fast_fts_frame._term_uuid(GRAPH)
        slot, entity = uuid.uuid4(), uuid.uuid4()
        frame = fast_fts_frame._term_uuid(FRAME_URI)
        # The trigger computes tsv, through BOTH languages.
        await pg_conn.execute(
            f"INSERT INTO {p}_fts_msg (subject_uuid, context_uuid, search_text) "
            f"VALUES ($1, $2, $3)", slot, ctx, SPANISH_DOC)
        await pg_conn.execute(
            f"INSERT INTO {p}_term (term_uuid, term_text, term_type) "
            f"VALUES ($1, $2, 'U')", frame, FRAME_URI)
        await pg_conn.execute(
            f"INSERT INTO {p}_entity_slot_sort (slot_uuid, context_uuid, "
            f"entity_uuid, frame_uuid, entity_type_uuid, slot_type_uuid, value_text) "
            f"VALUES ($1, $2, $3, $4, $5, $6, $7)",
            slot, ctx, entity, frame, fast_fts_frame._term_uuid(ENTITY_TYPE),
            fast_fts_frame._term_uuid(SLOT_TYPE), SPANISH_DOC)

        resolved = await fast_fts_frame._resolve_index(pg_conn, test_space, "msg")
        assert resolved == (f"{p}_fts_msg", ["english", "spanish"])

        page_sql, page_args = fast_fts_frame._build(
            test_space, _Criteria(), *resolved, for_count=False, cap=None,
            page_size=25, offset=0)
        rows = await pg_conn.fetch(page_sql, *page_args)
        assert [r["frame_uri"] for r in rows] == [FRAME_URI]

        count_sql, count_args = fast_fts_frame._build(
            test_space, _Criteria(), *resolved, for_count=True, cap=1000,
            page_size=0, offset=0)
        assert await pg_conn.fetchval(count_sql, *count_args) == 1

        # What the defect did: the first language alone misses the document.
        old_sql, old_args = fast_fts_frame._build(
            test_space, _Criteria(), resolved[0], ["english"], for_count=True,
            cap=1000, page_size=0, offset=0)
        assert await pg_conn.fetchval(old_sql, *old_args) == 0


class TestLanguagesAreValidated:
    async def test_an_unknown_language_creates_nothing(self, pg_conn, test_space):
        before = await _fts_tables(pg_conn, test_space)
        with pytest.raises(InvalidFtsLanguages, match="klingon"):
            await ensure_fts_index(pg_conn, test_space, "bad", ["english", "klingon"])
        assert await get_fts_index(pg_conn, test_space, "bad") is None
        assert await _fts_tables(pg_conn, test_space) == before

    async def test_an_injected_name_runs_nothing(self, pg_conn, test_space):
        with pytest.raises(InvalidFtsLanguages):
            await ensure_fts_index(pg_conn, test_space, "inj", [INJECTION])
        assert await get_fts_index(pg_conn, test_space, "inj") is None
        assert not await pg_conn.fetchval(
            "SELECT to_regclass('inttest_pwned') IS NOT NULL")

    async def test_a_refused_update_changes_nothing(self, pg_conn, test_space):
        assert await ensure_fts_index(pg_conn, test_space, "upd", ["english"])
        trigger_before = await _trigger_source(pg_conn, test_space, "upd")
        for bad in (["english", "klingon"], [INJECTION], []):
            with pytest.raises(InvalidFtsLanguages):
                await update_fts_languages(pg_conn, test_space, "upd", bad)
        assert (await get_fts_index(pg_conn, test_space, "upd"))["languages"] == ["english"]
        assert await _trigger_source(pg_conn, test_space, "upd") == trigger_before

    async def test_a_valid_update_still_works(self, pg_conn, test_space):
        assert await ensure_fts_index(pg_conn, test_space, "ok", ["english"])
        assert await update_fts_languages(pg_conn, test_space, "ok",
                                          ["english", "spanish"])
        assert (await get_fts_index(pg_conn, test_space, "ok"))["languages"] == [
            "english", "spanish"]
        assert "'spanish'::regconfig" in await _trigger_source(pg_conn, test_space, "ok")

    async def test_an_existing_index_is_not_revalidated(self, pg_conn, test_space):
        """`ensure_fts_index` on an existing index ignores *languages*, so it
        must not start refusing callers that pass a stale or default list."""
        assert await ensure_fts_index(pg_conn, test_space, "keep", ["english"])
        assert await ensure_fts_index(pg_conn, test_space, "keep", ["klingon"])


class TestConfigApply:
    def _doc(self, *fts_indexes):
        return {"version": CONFIG_VERSION, "fts_indexes": list(fts_indexes)}

    async def test_the_dry_run_refuses_what_the_real_run_would(
            self, pg_conn, test_space):
        doc = self._doc({"index_name": "cfg_new", "languages": ["klingon"]})
        for dry_run in (True, False):
            report = await apply_space_config(pg_conn, test_space, doc,
                                              dry_run=dry_run)
            assert report["failed"] == ["fts_index/cfg_new"]
            assert "klingon" in report["reasons"]["fts_index/cfg_new"]
            assert report["created"] == []
        assert await get_fts_index(pg_conn, test_space, "cfg_new") is None

    async def test_a_refused_language_change_is_not_reported_updated(
            self, pg_conn, test_space):
        assert await ensure_fts_index(pg_conn, test_space, "cfg_have", ["english"])
        doc = self._doc({"index_name": "cfg_have", "languages": ["english", "klingon"]})
        report = await apply_space_config(pg_conn, test_space, doc)
        assert report["updated"] == []
        assert report["failed"] == ["fts_index/cfg_have"]
        assert (await get_fts_index(pg_conn, test_space, "cfg_have"))["languages"] == ["english"]

    async def test_a_valid_language_change_is_applied(self, pg_conn, test_space):
        assert await ensure_fts_index(pg_conn, test_space, "cfg_ok", ["english"])
        doc = self._doc({"index_name": "cfg_ok", "languages": ["english", "spanish"]})
        report = await apply_space_config(pg_conn, test_space, doc)
        assert report["updated"] == ["fts_index/cfg_ok"]
        assert report["failed"] == []

    async def test_a_rank_normalization_is_reported_and_applied_once(
            self, pg_conn, test_space):
        """`get_fts_index` did not return `rank_normalization`, so the
        comparison read it as 0 and an index whose document set 1 was
        reported `updated` (and rewritten) on EVERY apply."""
        doc = self._doc({"index_name": "cfg_rank", "languages": ["english"],
                         "rank_normalization": 1})
        first = await apply_space_config(pg_conn, test_space, doc)
        assert first["created"] == ["fts_index/cfg_rank"]
        assert (await get_fts_index(pg_conn, test_space, "cfg_rank"))["rank_normalization"] == 1
        again = await apply_space_config(pg_conn, test_space, doc)
        assert again["updated"] == [] and again["changed"] is False
        doc["fts_indexes"][0]["rank_normalization"] = 0
        changed = await apply_space_config(pg_conn, test_space, doc)
        assert changed["updated"] == ["fts_index/cfg_rank"]
        assert (await get_fts_index(pg_conn, test_space, "cfg_rank"))["rank_normalization"] == 0
