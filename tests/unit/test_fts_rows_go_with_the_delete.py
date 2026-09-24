"""Deleting an entity graph removes its FTS rows, in the same transaction.

`issues/217` fixed this for the single-entity path and recorded the BULK path as
still open. It stayed open because of where the information lives: an FTS row is
keyed on the SUBJECT, and the subjects of an entity graph are its frames and
slots, while the delete endpoint hands `auto_sync(..., "delete")` the ENTITY
uris. The entity carries no FTS row, so the cleanup had nothing to do and every
slot row outlived its data.

`delete_entity_graph_bulk` already computes the exact subject set it is about to
delete, and already syncs `frame_slot`, `entity_slot_sort` and `edge` from it.
`sync_fts_before_delete` joins that group.

MEASURED: deleting 1,387 entities from a production archive left the space at 0
quads and 5,409 FTS rows, every one orphaned; the only repair was dropping the
index and recreating it, which is not available on a live space whose index has
324,869 rows. After the fix, deleting 40 entity graphs removed 79 FTS rows and
left 0 orphans attributable to them.

EVERY INDEX, not just one. A subject may be indexed by several mappings, so a
cleanup that knows about one index leaves the others behind — which is the same
shape of bug one level down.
"""

import pytest

from vitalgraph.db.sparql_sql.sync_fts_delete import sync_fts_before_delete

SPACE = "sp"
CTX = "ctx-uuid"
SUBJECTS = ["s1", "s2", "s3"]


class _Conn:
    """Records the DELETEs issued; `fetch` lists the space's FTS indexes."""

    def __init__(self, indexes, fail_on=()):
        self._indexes = indexes
        self._fail_on = set(fail_on)
        self.deletes = []

    async def fetch(self, sql, *args):
        assert "_fts_index" in sql
        return [{"index_name": n} for n in self._indexes]

    async def execute(self, sql, *args):
        table = sql.split("DELETE FROM ")[1].split()[0]
        if table in self._fail_on:
            raise RuntimeError("relation does not exist")
        self.deletes.append((table, args))
        return "DELETE 7"


@pytest.mark.asyncio
async def test_every_index_is_cleaned():
    conn = _Conn(["message_content", "document_segments"])
    removed = await sync_fts_before_delete(conn, SPACE, SUBJECTS, CTX)
    tables = [t for t, _ in conn.deletes]
    assert tables == [f"{SPACE}_fts_message_content", f"{SPACE}_fts_document_segments"]
    assert removed == 14, "counts from both indexes must be summed"


@pytest.mark.asyncio
async def test_scoped_to_the_subjects_and_the_context():
    """A delete that ignored context_uuid would strip another graph's rows."""
    conn = _Conn(["message_content"])
    await sync_fts_before_delete(conn, SPACE, SUBJECTS, CTX)
    _table, args = conn.deletes[0]
    assert args == (SUBJECTS, CTX)


@pytest.mark.asyncio
async def test_no_subjects_issues_no_delete():
    conn = _Conn(["message_content"])
    assert await sync_fts_before_delete(conn, SPACE, [], CTX) == 0
    assert conn.deletes == []


@pytest.mark.asyncio
async def test_a_missing_data_table_does_not_abort_the_delete():
    """An index registered but never populated has no data table yet. That is
    not an error at delete time, and must not stop the other indexes or roll
    back a delete whose quads are already gone."""
    conn = _Conn(["never_populated", "message_content"],
                 fail_on=[f"{SPACE}_fts_never_populated"])
    removed = await sync_fts_before_delete(conn, SPACE, SUBJECTS, CTX)
    assert [t for t, _ in conn.deletes] == [f"{SPACE}_fts_message_content"]
    assert removed == 7


@pytest.mark.asyncio
async def test_bulk_delete_calls_it():
    """Pin the wiring, not just the helper — this was unreferenced for months."""
    import inspect
    from vitalgraph.db.sparql_sql import sparql_sql_space_impl as impl
    src = inspect.getsource(impl.SparqlSQLSpaceImpl.delete_entity_graph_bulk)
    assert "sync_fts_before_delete" in src, (
        "delete_entity_graph_bulk must clean FTS alongside its other "
        "derived-table syncs")
