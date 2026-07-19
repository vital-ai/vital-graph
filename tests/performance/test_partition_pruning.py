"""P3 L1 validation: partitioned rdf_quad prunes, dedups, and uses UUIDv7.

Requires PostgreSQL 18 (uuidv7()); targets the vg-test PG18 on :5433 by default,
overridable via VG_TEST_PG18_* env vars. Skips if no PG18 is reachable.

Proves the P3 architectural core:
- HASH(context_uuid) partitioning prunes a graph-scoped query to ONE partition.
- The slim 4-col PK (s,p,o,c) dedups identical quads (ON CONFLICT).
- quad_uuid defaults to a time-ordered UUIDv7 (insert locality).
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import pytest_asyncio

from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
from .harness import explain_json, node_types

PG18 = dict(
    host=os.environ.get("VG_TEST_PG18_HOST", "localhost"),
    port=int(os.environ.get("VG_TEST_PG18_PORT", "5433")),
    database=os.environ.get("VG_TEST_PG18_DATABASE", "sparql_sql_graph"),
    user=os.environ.get("VG_TEST_PG18_USER", "postgres"),
    password=os.environ.get("VG_TEST_PG18_PASSWORD", "testpass"),
)
N_PARTITIONS = 4


def _has_pg18() -> bool:
    import asyncpg
    try:
        loop = asyncio.new_event_loop()

        async def chk():
            c = await asyncpg.connect(**PG18)
            try:
                await c.fetchval("SELECT uuidv7()")
                return True
            except Exception:
                return False
            finally:
                await c.close()
        ok = loop.run_until_complete(chk())
        loop.close()
        return ok
    except Exception:
        return False


HAS_PG18 = _has_pg18()
skip_no_pg18 = pytest.mark.skipif(
    not HAS_PG18, reason="Requires PostgreSQL 18 (uuidv7) on :5433")

pytestmark = [pytest.mark.performance, skip_no_pg18,
              pytest.mark.asyncio(loop_scope="session")]


@pytest_asyncio.fixture(loop_scope="session")
async def pg18_pool():
    import asyncpg
    pool = await asyncpg.create_pool(**PG18, min_size=1, max_size=4)
    yield pool
    await pool.close()


@pytest_asyncio.fixture(loop_scope="session")
async def part_space(pg18_pool):
    schema = SparqlSQLSchema()
    sid = f"p3test_{uuid.uuid4().hex[:8]}"
    async with pg18_pool.acquire() as conn:
        for s in schema.create_space_tables_sql(sid, partition_quads=N_PARTITIONS):
            await conn.execute(s)
        for s in schema.create_space_indexes_sql(sid):
            await conn.execute(s)
    yield sid
    async with pg18_pool.acquire() as conn:
        for s in schema.drop_space_tables_sql(sid):
            await conn.execute(s)


def _partitions_scanned(plan, sid):
    """Relation names in the plan that are partitions of this space's rdf_quad."""
    prefix = f"{sid}_rdf_quad_p"
    return sorted({n.get("Relation Name") for n in _walk(plan)
                   if (n.get("Relation Name") or "").startswith(prefix)})


def _walk(plan):
    root = plan["Plan"] if "Plan" in plan else plan
    stack = [root]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(n.get("Plans", []) or [])


async def test_graph_scoped_query_prunes_to_one_partition(pg18_pool, part_space):
    sid = part_space
    t = SparqlSQLSchema.get_table_names(sid)
    graphs = [uuid.uuid4() for _ in range(N_PARTITIONS + 2)]
    async with pg18_pool.acquire() as conn:
        rows = []
        for g in graphs:
            rows += [(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), g)
                     for _ in range(150)]
        await conn.executemany(
            f"INSERT INTO {t['rdf_quad']} "
            f"(subject_uuid, predicate_uuid, object_uuid, context_uuid) "
            f"VALUES ($1, $2, $3, $4)", rows)
        await conn.execute(f"ANALYZE {t['rdf_quad']}")

        # A graph-scoped query prunes to exactly one partition.
        for g in graphs[:3]:
            plan = await explain_json(
                conn, f"SELECT subject_uuid FROM {t['rdf_quad']} WHERE context_uuid = $1",
                g, analyze=False)
            scanned = _partitions_scanned(plan, sid)
            assert len(scanned) == 1, (g, scanned, node_types(plan))


async def test_edge_and_frame_entity_are_co_partitioned(pg18_pool, part_space):
    """rdf_quad, edge, frame_entity are all HASH(context_uuid)-partitioned with
    the same modulus, so edge-rewrite joins can be partition-wise."""
    sid = part_space
    async with pg18_pool.acquire() as conn:
        for tbl in ("rdf_quad", "edge", "frame_entity"):
            n = await conn.fetchval(
                "SELECT count(*) FROM pg_inherits i "
                "JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = $1",
                f"{sid}_{tbl}")
            assert n == N_PARTITIONS, (tbl, n)


async def test_slim_pk_dedups_identical_quads(pg18_pool, part_space):
    sid = part_space
    t = SparqlSQLSchema.get_table_names(sid)
    s, p, o, g = (uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    async with pg18_pool.acquire() as conn:
        for _ in range(3):
            await conn.execute(
                f"INSERT INTO {t['rdf_quad']} "
                f"(subject_uuid, predicate_uuid, object_uuid, context_uuid) "
                f"VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING", s, p, o, g)
        cnt = await conn.fetchval(
            f"SELECT count(*) FROM {t['rdf_quad']} WHERE subject_uuid = $1 "
            f"AND predicate_uuid = $2 AND object_uuid = $3 AND context_uuid = $4",
            s, p, o, g)
    assert cnt == 1, cnt


async def test_migrate_nonpartitioned_space_preserves_data(pg18_pool):
    """Per-space migration: non-partitioned space -> partitioned, with set-parity
    and correct (s,p,o,c) dedup."""
    from vitalgraph.db.sparql_sql.partition_migrate import (
        migrate_space_to_partitioned, distinct_quads)

    schema = SparqlSQLSchema()
    sid = f"p3mig_{uuid.uuid4().hex[:8]}"
    async with pg18_pool.acquire() as conn:
        for s in schema.create_space_tables_sql(sid):        # non-partitioned
            await conn.execute(s)
        for s in schema.create_space_indexes_sql(sid):
            await conn.execute(s)
    try:
        t = SparqlSQLSchema.get_table_names(sid)
        async with pg18_pool.acquire() as conn:
            g = uuid.uuid4()
            rows = [(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), g) for _ in range(300)]
            rows += [rows[0], rows[0]]                       # 2 duplicate quads
            await conn.executemany(
                f"INSERT INTO {t['rdf_quad']} "
                f"(subject_uuid, predicate_uuid, object_uuid, context_uuid) "
                f"VALUES ($1, $2, $3, $4)", rows)

            before = await distinct_quads(conn, sid)
            part_before = await conn.fetchval(
                "SELECT count(*) FROM pg_inherits i JOIN pg_class p "
                "ON p.oid = i.inhparent WHERE p.relname = $1", f"{sid}_rdf_quad")

            async with conn.transaction():
                summary = await migrate_space_to_partitioned(conn, sid, n_partitions=4)

            after = await distinct_quads(conn, sid)
            part_after = await conn.fetchval(
                "SELECT count(*) FROM pg_inherits i JOIN pg_class p "
                "ON p.oid = i.inhparent WHERE p.relname = $1", f"{sid}_rdf_quad")
            plan = await explain_json(
                conn, f"SELECT subject_uuid FROM {t['rdf_quad']} WHERE context_uuid = $1",
                g, analyze=False)
            scanned = _partitions_scanned(plan, sid)

        assert part_before == 0 and part_after == 4          # became partitioned
        assert before == after                               # set-semantics parity
        assert summary == {"old_quads": 302, "new_quads": 300, "dupes_dropped": 2}
        assert len(scanned) == 1                             # prunes post-migration
    finally:
        async with pg18_pool.acquire() as conn:
            for s in schema.drop_space_tables_sql(sid):
                await conn.execute(s)


async def test_quad_uuid_is_time_ordered_uuidv7(pg18_pool, part_space):
    sid = part_space
    t = SparqlSQLSchema.get_table_names(sid)
    g = uuid.uuid4()
    async with pg18_pool.acquire() as conn:
        u = []
        for _ in range(5):
            u.append(await conn.fetchval(
                f"INSERT INTO {t['rdf_quad']} "
                f"(subject_uuid, predicate_uuid, object_uuid, context_uuid) "
                f"VALUES ($1, $2, $3, $4) RETURNING quad_uuid",
                uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), g))
    assert all(str(x)[14] == "7" for x in u), u          # version nibble = 7
    assert u == sorted(u, key=str), "UUIDv7 quad_uuids not time-ordered"
