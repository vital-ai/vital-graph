"""API: an FTS index language list is validated before anything is created.

`issues/333`. An unknown language used to be accepted: the index was created,
and every write into it then failed inside auto-sync, which only logs, so the
subject was silently never indexed. The name was also pasted unquoted into DDL.
Now the server refuses it as a domain outcome — `invalid_request` in an HTTP
200 body — and creates or changes nothing.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from vitalgraph.db.sparql_sql.space_names import space_prefix
from vitalgraph.model.result_status import OperationStatus

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

INJECTION = "english'::regconfig, ''); CREATE TABLE apitest_pwned(x int); --"


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def fts_space(vg_client, test_space):
    good = f"lang_ok_{uuid.uuid4().hex[:8]}"
    resp = await vg_client.fts_indexes.create_index(
        space_id=test_space, index_name=good, languages=["english"])
    assert resp.status == OperationStatus.CREATED, resp.message
    yield {"space_id": test_space, "good": good}
    try:
        await vg_client.fts_indexes.delete_index(test_space, good)
    except Exception:
        pass


async def _fts_tables(pg_conn, space_id):
    rows = await pg_conn.fetch(
        "SELECT tablename FROM pg_tables WHERE tablename LIKE $1",
        f"{space_prefix(space_id)}_fts_%")
    return sorted(r["tablename"] for r in rows)


class TestCreate:
    @pytest.mark.parametrize("languages", [
        ["english", "klingon"], [INJECTION], ["english", "english"]],
        ids=["unknown", "injection", "duplicate"])
    async def test_a_bad_list_is_refused_and_creates_nothing(
            self, vg_client, pg_conn, fts_space, languages):
        space_id = fts_space["space_id"]
        name = f"lang_bad_{uuid.uuid4().hex[:8]}"
        before = await _fts_tables(pg_conn, space_id)
        resp = await vg_client.fts_indexes.create_index(
            space_id=space_id, index_name=name, languages=languages)
        assert resp.status == OperationStatus.INVALID_REQUEST, resp.message
        assert resp.success is False
        listed = await vg_client.fts_indexes.list_indexes(space_id)
        assert name not in [i.index_name for i in listed.indexes]
        assert await _fts_tables(pg_conn, space_id) == before
        assert not await pg_conn.fetchval(
            "SELECT to_regclass('apitest_pwned') IS NOT NULL")

    async def test_the_reason_names_the_language(self, vg_client, fts_space):
        resp = await vg_client.fts_indexes.create_index(
            space_id=fts_space["space_id"],
            index_name=f"lang_bad_{uuid.uuid4().hex[:8]}",
            languages=["english", "klingon"])
        assert "klingon" in (resp.message or "")


class TestUpdate:
    async def test_a_bad_list_is_refused_and_changes_nothing(
            self, vg_client, fts_space):
        space_id, good = fts_space["space_id"], fts_space["good"]
        resp = await vg_client.fts_indexes.update_languages(
            space_id=space_id, index_name=good, languages=["english", "klingon"])
        assert resp.status == OperationStatus.INVALID_REQUEST, resp.message
        listed = await vg_client.fts_indexes.list_indexes(space_id)
        [idx] = [i for i in listed.indexes if i.index_name == good]
        assert idx.languages == ["english"]

    async def test_a_valid_list_is_applied(self, vg_client, fts_space):
        space_id, good = fts_space["space_id"], fts_space["good"]
        resp = await vg_client.fts_indexes.update_languages(
            space_id=space_id, index_name=good, languages=["english", "spanish"])
        assert resp.status == OperationStatus.UPDATED, resp.message
        assert resp.languages == ["english", "spanish"]
