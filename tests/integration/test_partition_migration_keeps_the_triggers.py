"""Integration: partitioning a space keeps the triggers on its core tables (`issues/303`).

`migrate_space_to_partitioned` builds `{space}_rdf_quad_new` with `LIKE`, which
copies no triggers, then drops the old table and renames the new one in. A
migrated space lost its index-sync outbox (`issues/291`), so vectors and FTS
silently stopped following writes, and its write log (`issues/302`).

Pinned: the same triggers, in the same state, after the migration; and a write
after it still queues its subject for index sync and counts in the write log.
"""

from __future__ import annotations

import pytest
from rdflib import Literal, URIRef

from .conftest import skip_no_infra

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]

GRAPH = URIRef("urn:ptrig:g")
P = URIRef("urn:ptrig:p")


async def _triggers(conn, table):
    return [(r["tgname"], r["tgenabled"]) for r in await conn.fetch(
        "SELECT tgname, tgenabled::text AS tgenabled FROM pg_trigger "
        "WHERE tgrelid = $1::regclass AND NOT tgisinternal ORDER BY tgname", table)]


async def test_the_triggers_survive_and_still_fire(make_space, space_impl, pg_conn):
    from vitalgraph.db.sparql_sql import write_log
    from vitalgraph.db.sparql_sql.partition_migrate import migrate_space_to_partitioned
    from vitalgraph.db.sparql_sql.space_names import space_prefix

    space = await make_space()
    pfx = space_prefix(space)
    quad, isq = f"{pfx}_rdf_quad", f"{pfx}_index_sync_queue"
    async with pg_conn.transaction():
        for stmt in write_log.create_sql(space):
            await pg_conn.execute(stmt)
    await space_impl.add_rdf_quads_batch(
        space, [(URIRef(f"urn:ptrig:s{i}"), P, Literal(f"v{i}"), GRAPH) for i in range(5)])

    before = await _triggers(pg_conn, quad)
    names = {n for n, _ in before}
    assert write_log.trigger_name(space) in names, before
    assert any("isq" in n for n in names), f"the index-sync triggers are not there to keep: {before}"
    relkind = "SELECT relkind::text FROM pg_class WHERE oid = to_regclass($1)"
    assert await pg_conn.fetchval(relkind, quad) == "r"

    async with pg_conn.transaction():
        await migrate_space_to_partitioned(pg_conn, space, n_partitions=4)

    assert await pg_conn.fetchval(relkind, quad) == "p", "not partitioned"
    assert await _triggers(pg_conn, quad) == before, "the migration lost or changed triggers"

    # ...and they fire on the partitioned table.
    await pg_conn.execute(f"DELETE FROM {isq}")
    writes0 = await pg_conn.fetchval(f"SELECT coalesce(sum(n), 0) FROM {write_log.table_name(space)}")
    await space_impl.add_rdf_quads_batch(space, [(URIRef("urn:ptrig:after"), P, Literal("x"), GRAPH)])
    queued = await pg_conn.fetchval(f"SELECT count(*) FROM {isq}")
    writes1 = await pg_conn.fetchval(f"SELECT coalesce(sum(n), 0) FROM {write_log.table_name(space)}")
    assert queued >= 1, "a write after the migration queued nothing for index sync"
    assert writes1 == writes0 + 1, f"the write log did not count it ({writes0} -> {writes1})"


async def test_a_disabled_trigger_stays_disabled(make_space, space_impl, pg_conn):
    from vitalgraph.db.sparql_sql import write_log
    from vitalgraph.db.sparql_sql.partition_migrate import migrate_space_to_partitioned
    from vitalgraph.db.sparql_sql.space_names import space_prefix

    space = await make_space()
    quad = f"{space_prefix(space)}_rdf_quad"
    async with pg_conn.transaction():
        for stmt in write_log.create_sql(space):
            await pg_conn.execute(stmt)
    await space_impl.add_rdf_quads_batch(space, [(URIRef("urn:ptrig:s"), P, Literal("v"), GRAPH)])
    await pg_conn.execute(f'ALTER TABLE {quad} DISABLE TRIGGER "{write_log.trigger_name(space)}"')
    before = await _triggers(pg_conn, quad)
    assert (write_log.trigger_name(space), "D") in before

    async with pg_conn.transaction():
        await migrate_space_to_partitioned(pg_conn, space, n_partitions=2)
    assert await _triggers(pg_conn, quad) == before
