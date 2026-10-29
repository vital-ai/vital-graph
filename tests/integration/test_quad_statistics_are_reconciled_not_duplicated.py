"""Replaying the schema leaves ONE (predicate, object) statistics object per quad table.

The index DDL is replayed on existing spaces (`ensure_space_indexes.py`, the
schema migrations). It used to say `CREATE STATISTICS IF NOT EXISTS
stat_<key>_quad_po`, and a space created before storage keys carries that object
as `stat_<space id>_quad_po` on its keyed table, so a replay added a second
object on the same columns and every ANALYZE built both 1,000-entry MCV lists
on the biggest table. Found on the vg test stack: 26 old-named objects, one
duplicate. `quad_po_statistics_sql` reconciles by table and columns.
"""

from __future__ import annotations

import pytest

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

_OBJECTS = ("SELECT stxname, stxstattarget FROM pg_statistic_ext "
            "WHERE stxrelid = $1::regclass ORDER BY stxname")


async def _objects(conn, table):
    return [(r["stxname"], r["stxstattarget"]) for r in await conn.fetch(_OBJECTS, table)]


async def test_every_state_converges_on_one_object(make_space, pg_conn):
    from vitalgraph.db.sparql_sql.space_names import space_prefix
    from vitalgraph.db.sparql_sql.sparql_sql_schema import quad_po_statistics_sql

    space = await make_space()
    table = f"{space_prefix(space)}_rdf_quad"
    name = f"stat_{space_prefix(space)}_quad_po"
    want = [(name, 1000)]
    stmt = quad_po_statistics_sql(space, table)

    # a new space: created by the schema, once
    assert await _objects(pg_conn, table) == want

    # named before storage keys: renamed, not duplicated
    await pg_conn.execute(f"ALTER STATISTICS {name} RENAME TO stat_{space}_quad_po")
    await pg_conn.execute(stmt)
    assert await _objects(pg_conn, table) == want

    # a duplicate beside it (what the old replay left): dropped
    await pg_conn.execute(
        f"CREATE STATISTICS stat_{space}_quad_po (mcv, ndistinct) "
        f"ON predicate_uuid, object_uuid FROM {table}")
    await pg_conn.execute(stmt)
    assert await _objects(pg_conn, table) == want

    # none at all: created
    await pg_conn.execute(f"DROP STATISTICS {name}")
    await pg_conn.execute(stmt)
    assert await _objects(pg_conn, table) == want

    # and a replay changes nothing
    await pg_conn.execute(stmt)
    assert await _objects(pg_conn, table) == want
