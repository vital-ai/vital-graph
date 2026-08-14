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


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def pg18_space_manager():
    """SpaceManager over a PG18-connected backend — spaces (incl. partitioned)
    are created via the manager, not SparqlSQLSchema directly."""
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl
    from vitalgraph.space.space_manager import SpaceManager
    impl = SparqlSQLSpaceImpl(
        postgresql_config={"host": PG18["host"], "port": PG18["port"],
                           "database": PG18["database"], "username": PG18["user"],
                           "password": PG18["password"],
                           "min_pool_size": 1, "max_pool_size": 4},
        sidecar_config={"url": os.environ.get("VG_TEST_SIDECAR_URL",
                                              "http://localhost:7071")})
    await impl.connect()
    yield SpaceManager(db_impl=getattr(impl, "db_impl", None), space_backend=impl)
    await impl.disconnect()


@pytest_asyncio.fixture(loop_scope="session")
async def make_pg18_space(pg18_space_manager):
    """Factory: create a (optionally partitioned) space via the manager, dropped
    on teardown."""
    created = []

    async def _make(partition_quads: int = 0) -> str:
        sid = f"p3test_{uuid.uuid4().hex[:8]}"
        ok = await pg18_space_manager.create_space_with_tables(
            sid, sid, partition_quads=partition_quads)
        assert ok, f"space manager failed to create {sid}"
        created.append(sid)
        return sid

    yield _make
    for sid in created:
        try:
            await pg18_space_manager.delete_space_with_tables(sid)
        except Exception:
            pass


@pytest_asyncio.fixture(loop_scope="session")
async def part_space(make_pg18_space):
    return await make_pg18_space(partition_quads=N_PARTITIONS)


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


@pytest.mark.bench("query.partition.graph_scoped_pruning")
async def test_graph_scoped_query_prunes_to_one_partition(pg18_pool, part_space, perf_record):
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

        perf_record(dataset=f"synthetic:{N_PARTITIONS}part",
                    metrics={"partitions_scanned": len(scanned),
                             "partitions_total": N_PARTITIONS,
                             "node_types": ",".join(node_types(plan))})


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


async def test_migrate_nonpartitioned_space_preserves_data(pg18_pool, make_pg18_space):
    """Per-space migration: non-partitioned space -> partitioned, with set-parity
    and correct (s,p,o,c) dedup."""
    from vitalgraph.db.sparql_sql.partition_migrate import (
        migrate_space_to_partitioned, distinct_quads)

    sid = await make_pg18_space(partition_quads=0)            # non-partitioned
    t = SparqlSQLSchema.get_table_names(sid)
    async with pg18_pool.acquire() as conn:
        g = uuid.uuid4()
        rows = [(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), g) for _ in range(300)]
        rows += [rows[0], rows[0]]                           # 2 duplicate quads
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

    assert part_before == 0 and part_after == 4              # became partitioned
    assert before == after                                   # set-semantics parity
    assert summary == {"old_quads": 302, "new_quads": 300, "dupes_dropped": 2}
    assert len(scanned) == 1                                 # prunes post-migration


async def test_migrate_preserves_every_core_column_and_its_data(
        pg18_pool, make_pg18_space):
    """The migration must not change what a core table HOLDS.

    This is the property that broke. `_new_core_ddl` restated the three core
    schemas by hand; `edge` later gained `edge_type_uuid` and the copy did not,
    so the backfill failed with "INSERT has more expressions than target
    columns". That was the LUCKY direction — rdf_quad's backfill named its
    columns, so identical drift there would have raised nothing and migrated the
    space with the new column's data dropped.

    The existing migration test only inserts quads, so both core tables are
    empty in it and it caught the edge case only because a column-count mismatch
    fails at parse time rather than on a row. This one puts a row in each table
    with every column populated, and compares the column sets across the swap.
    """
    from vitalgraph.db.sparql_sql.partition_migrate import (
        migrate_space_to_partitioned)

    sid = await make_pg18_space(partition_quads=0)
    t = SparqlSQLSchema.get_table_names(sid)

    async def columns(conn, table):
        return [r["column_name"] for r in await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = $1 ORDER BY ordinal_position", table)]

    async with pg18_pool.acquire() as conn:
        g = uuid.uuid4()
        await conn.execute(
            f"INSERT INTO {t['rdf_quad']} "
            f"(subject_uuid, predicate_uuid, object_uuid, context_uuid) "
            f"VALUES ($1, $2, $3, $4)",
            uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), g)

        # Populate EVERY column, so a dropped one shows up as lost data rather
        # than as a column that happened to be NULL either way.
        edge_cols = await columns(conn, f"{sid}_edge")
        edge_vals = [uuid.uuid4() for _ in edge_cols]
        edge_vals[edge_cols.index("context_uuid")] = g
        await conn.execute(
            f"INSERT INTO {sid}_edge ({', '.join(edge_cols)}) VALUES "
            f"({', '.join('$' + str(i + 1) for i in range(len(edge_cols)))})",
            *edge_vals)

        fe_cols = await columns(conn, f"{sid}_frame_entity")
        fe_vals = [uuid.uuid4() for _ in fe_cols]
        fe_vals[fe_cols.index("context_uuid")] = g
        await conn.execute(
            f"INSERT INTO {sid}_frame_entity ({', '.join(fe_cols)}) VALUES "
            f"({', '.join('$' + str(i + 1) for i in range(len(fe_cols)))})",
            *fe_vals)

        before = {c: await columns(conn, f"{sid}_{c}")
                  for c in ("rdf_quad", "edge", "frame_entity")}

        async with conn.transaction():
            await migrate_space_to_partitioned(conn, sid, n_partitions=4)

        after = {c: await columns(conn, f"{sid}_{c}")
                 for c in ("rdf_quad", "edge", "frame_entity")}
        edge_after = await conn.fetchrow(f"SELECT * FROM {sid}_edge")
        fe_after = await conn.fetchrow(f"SELECT * FROM {sid}_frame_entity")

    assert before == after, (
        "migration changed a core table's columns — a hand-maintained copy of "
        "the schema has drifted from the real one")
    assert edge_after is not None, "the edge row did not survive migration"
    assert [edge_after[c] for c in edge_cols] == edge_vals, (
        "an edge column's value was lost across the migration")
    assert fe_after is not None, "the frame_entity row did not survive migration"
    assert [fe_after[c] for c in fe_cols] == fe_vals


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
