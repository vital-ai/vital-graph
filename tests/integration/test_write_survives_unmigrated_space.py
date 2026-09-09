"""A space without the prop-sort tables must still accept writes.

`entity_prop_sort` and `frame_prop_sort` are created by an EXPLICIT migration,
never as a side effect of a data path. So "this space has not been migrated"
is a normal state — and it is the state every existing space is in the moment
this code ships, before anyone runs the migration.

The write path did not tolerate it. `sync_*_after_change` issued a DELETE
against a table that did not exist, `add_rdf_quads_batch_bulk` raised
`relation "sp_kg_types_entity_prop_sort" does not exist`, `update_quads`
returned False, and the endpoint answered 500. Every write to an unmigrated
space failed — an optimisation table taking the write path down with it.

Reads never had this problem: `fast_entity_prop_page` catches and falls back to
SPARQL. Only writes failed closed, and these tests hold them to the read's
standard.
"""

from __future__ import annotations

import uuid

import pytest

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]


async def test_entity_sync_skips_a_missing_table(pg_pool):
    from vitalgraph.db.sparql_sql import sync_entity_prop_sort as m

    async with pg_pool.acquire() as conn:
        # A space id that cannot have tables. If the guard is absent this
        # raises UndefinedTableError instead of returning.
        rows = await m.sync_entity_prop_sort_after_change(
            conn, "nosuchspace_xyz", [uuid.uuid4()])
        assert rows == 0

        # AND the transaction is still usable. A failed statement aborts it,
        # which is why this is checked rather than caught at the call site.
        assert await conn.fetchval("SELECT 1") == 1


async def test_frame_sync_skips_a_missing_table(pg_pool):
    from vitalgraph.db.sparql_sql import sync_frame_prop_sort as m

    async with pg_pool.acquire() as conn:
        rows = await m.sync_frame_prop_sort_after_change(
            conn, "nosuchspace_xyz", [uuid.uuid4()])
        assert rows == 0
        assert await conn.fetchval("SELECT 1") == 1


async def test_only_the_positive_answer_is_cached(pg_pool):
    """A space migrated after its first write must start being maintained.

    Caching "absent" would exclude it for the life of the process — the table
    would exist, the migration would report success, and writes would silently
    never populate it.
    """
    from vitalgraph.db.sparql_sql import sync_entity_prop_sort as m

    async with pg_pool.acquire() as conn:
        await m._table_present(conn, "nosuchspace_xyz",
                               "nosuchspace_xyz_entity_prop_sort")
        assert "nosuchspace_xyz" not in m._TABLE_PRESENT, (
            "a missing table was cached as a permanent answer; migrating the "
            "space later would not start maintaining it")
