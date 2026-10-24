"""Does a stats recompute refresh the generator's in-process stats cache?

Reproduces the claim from planning_planner/08: `_stats_cache` (generator.py:283)
has no TTL, and `MaintenanceJob._run_stats_recompute` / `StatsRebuildOp` rewrite
rdf_stats / rdf_pred_stats without invalidating it. The maintenance job runs
INSIDE the server process (vitalgraphapp_impl.py:548), so this script runs the
same code in one process: the generator's cache and the maintenance job share
module state exactly as they do in the server.

Scratch space is created and deleted through the API (vg test stack, :8002).

    LOCAL_CLIENT_SERVER_URL=http://localhost:8002 \
    /opt/homebrew/anaconda3/envs/vital-graph/bin/python \
        test_scripts/debug/_stats_cache_stale_after_recompute.py
"""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import asyncpg  # noqa: E402

PG = dict(host=os.getenv("VG_TEST_PG_HOST", "localhost"),
          port=int(os.getenv("VG_TEST_PG_PORT", "5433")),
          database=os.getenv("VG_TEST_PG_DATABASE", "sparql_sql_graph"),
          user="postgres", password=os.getenv("VG_TEST_PG_PASSWORD", "testpass"))
GRAPH = "urn:zzcache:g"
P = "urn:zzcache:p"


def _insert(prefix, obj, n):
    triples = " ".join(f"<urn:zzcache:{prefix}{i}> <{P}> <{obj}> ." for i in range(n))
    return f"INSERT DATA {{ GRAPH <{GRAPH}> {{ {triples} }} }}"


def _cached_p(gen, space_id, p_uuid):
    entry = gen._stats_cache.get((space_id, None))
    if entry is None:
        return None
    return entry[1].get(p_uuid)


async def main():
    from vitalgraph.client.vitalgraph_client import VitalGraphClient
    from vitalgraph.model.spaces_model import Space
    from vitalgraph.model.sparql_model import SPARQLUpdateRequest
    from vitalgraph.db.sparql_sql import generator as gen
    from vitalgraph.db.sparql_sql.space_storage_key import load_storage_keys
    from vitalgraph.db.sparql_sql.space_names import space_prefix
    from vitalgraph.process.maintenance_job import MaintenanceJob
    from vitalgraph.ops.database_op import StatsRebuildOp

    space_id = f"zzcache_{uuid.uuid4().hex[:8]}"
    client = VitalGraphClient()
    await client.open()
    pool = await asyncpg.create_pool(**PG, min_size=1, max_size=3)
    try:
        cr = await client.spaces.create_space(Space(
            space=space_id, space_name=space_id,
            space_description="stats-cache staleness probe (deleted on exit)"))
        assert cr.is_success, cr.error_message
        await client.graphs.create_graph(space_id, GRAPH)
        async with pool.acquire() as c:
            await load_storage_keys(c, space_id)
        sp = space_prefix(space_id)

        async def update(q):
            r = await client.sparql.execute_sparql_update(space_id, SPARQLUpdateRequest(update=q))
            assert getattr(r, "success", True), r

        async def db_p_count():
            async with pool.acquire() as c:
                return await c.fetchval(
                    f"SELECT ps.row_count FROM {sp}_rdf_pred_stats ps "
                    f"JOIN {sp}_term t ON t.term_uuid = ps.predicate_uuid "
                    f"WHERE t.term_text = $1", P)

        async with pool.acquire() as c:
            p_uuid = None

        job = MaintenanceJob(pool)

        # 1. 10 quads, recompute, warm the cache as a query would.
        await update(_insert("a", "urn:zzcache:A", 10))
        await job._run_stats_recompute([space_id], force=True)
        async with pool.acquire() as c:
            p_uuid = await c.fetchval(f"SELECT term_uuid::text FROM {sp}_term WHERE term_text = $1", P)
            gen.invalidate_stats_cache(space_id)
            await gen.warm_stats_cache(space_id, conn=c)
        print(f"[1] db pred_stats={await db_p_count()}  cache={_cached_p(gen, space_id, p_uuid)}")

        # 2. +50 quads, the hourly path's recompute, same process.
        await update(_insert("b", "urn:zzcache:B", 50))
        await job._run_stats_recompute([space_id], force=True)
        async with pool.acquire() as c:
            await gen.warm_stats_cache(space_id, conn=c)   # what the next query does
        print(f"[2] after _run_stats_recompute: db={await db_p_count()}  cache={_cached_p(gen, space_id, p_uuid)}")

        # 3. +40 quads, the operator's explicit stats rebuild (trigger 'stats_rebuild').
        await update(_insert("c", "urn:zzcache:C", 40))
        async with pool.acquire() as c:
            await StatsRebuildOp(space_id, conn=c).execute()
            await gen.warm_stats_cache(space_id, conn=c)
        print(f"[3] after StatsRebuildOp:       db={await db_p_count()}  cache={_cached_p(gen, space_id, p_uuid)}")

        # 4. control: an explicit invalidate reloads.
        gen.invalidate_stats_cache(space_id)
        async with pool.acquire() as c:
            await gen.warm_stats_cache(space_id, conn=c)
        print(f"[4] after invalidate_stats_cache: db={await db_p_count()}  cache={_cached_p(gen, space_id, p_uuid)}")
    finally:
        try:
            await client.spaces.delete_space(space_id)
        finally:
            await client.close()
            await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
