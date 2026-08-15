"""The rewrite must keep exactly the rows the DELETE form kept.

Same keeper rules, different mechanism — so the check is set equality against
an independent implementation of the OLD three-step logic, run on a copy of the
same starting table. Space reclaimed is the point, but a smaller table that
keeps the wrong rows is a silent planner regression.
"""
import asyncio, os, sys
sys.path.insert(0, "/Users/hadfield/Local/vital-git/vital-graph")
os.chdir("/Users/hadfield/Local/vital-git/vital-graph")
import asyncpg
from vitalgraph.db.sparql_sql.sync_stats_tables import (
    prune_stats_tables, STATS_KEEP_DEFAULT, STATS_PER_PREDICATE_DEFAULT,
    STATS_MIN_ROW_COUNT, STATS_MAX_ROW_COUNT, resync_stats_tables)

SPACE = "sp_graph_synth_10k"
SHADOW = "zz_prune_shadow"

async def main():
    conn = await asyncpg.connect(host="localhost", port=5433,
        database="sparql_sql_graph", user="postgres", password="testpass")
    await conn.execute("SET statement_timeout='600s'")
    # Rebuild so we start from a full, unpruned table.
    await resync_stats_tables(conn, SPACE)
    n0 = await conn.fetchval(f"SELECT count(*) FROM {SPACE}_rdf_stats")
    sz0 = await conn.fetchval(f"SELECT pg_total_relation_size('{SPACE}_rdf_stats')")
    print(f"start: {n0:,} rows, {sz0/1024/1024:.1f} MB", flush=True)

    # A shadow copy, pruned by the OLD three-DELETE logic, independently coded.
    await conn.execute(f"DROP TABLE IF EXISTS {SHADOW}")
    await conn.execute(f"CREATE TABLE {SHADOW} AS SELECT * FROM {SPACE}_rdf_stats")
    await conn.execute(f"DELETE FROM {SHADOW} WHERE row_count < $1 OR row_count > $2",
                       STATS_MIN_ROW_COUNT, STATS_MAX_ROW_COUNT)
    await conn.execute(f"""DELETE FROM {SHADOW} WHERE ctid IN (
        SELECT ctid FROM (SELECT ctid, row_number() OVER (
          PARTITION BY predicate_uuid ORDER BY row_count ASC, object_uuid) AS rn
        FROM {SHADOW}) r WHERE r.rn > $1)""", STATS_PER_PREDICATE_DEFAULT)
    await conn.execute(f"""DELETE FROM {SHADOW} WHERE ctid IN (
        SELECT ctid FROM (SELECT ctid, row_number() OVER (
          PARTITION BY predicate_uuid ORDER BY row_count ASC, object_uuid) AS rn
        FROM {SHADOW}) r ORDER BY r.rn ASC, r.ctid OFFSET $1)""", STATS_KEEP_DEFAULT)
    n_shadow = await conn.fetchval(f"SELECT count(*) FROM {SHADOW}")

    kept = await prune_stats_tables(conn, SPACE)
    sz1 = await conn.fetchval(f"SELECT pg_total_relation_size('{SPACE}_rdf_stats')")

    only_new = await conn.fetchval(f"""
        SELECT count(*) FROM {SPACE}_rdf_stats s
        LEFT JOIN {SHADOW} d ON d.predicate_uuid=s.predicate_uuid
                            AND d.object_uuid=s.object_uuid
        WHERE d.predicate_uuid IS NULL""")
    only_old = await conn.fetchval(f"""
        SELECT count(*) FROM {SHADOW} d
        LEFT JOIN {SPACE}_rdf_stats s ON s.predicate_uuid=d.predicate_uuid
                                     AND s.object_uuid=d.object_uuid
        WHERE s.predicate_uuid IS NULL""")
    mism = await conn.fetchval(f"""
        SELECT count(*) FROM {SPACE}_rdf_stats s
        JOIN {SHADOW} d ON d.predicate_uuid=s.predicate_uuid
                       AND d.object_uuid=s.object_uuid
        WHERE d.row_count <> s.row_count""")
    print(f"rewrite kept {kept:,} rows   DELETE form kept {n_shadow:,}", flush=True)
    print(f"only in rewrite: {only_new}   only in DELETE form: {only_old}   "
          f"count mismatches: {mism}", flush=True)
    print(f"size: {sz0/1024/1024:.1f} MB -> {sz1/1024:.0f} kB "
          f"({sz0/max(sz1,1):.0f}x)", flush=True)
    print("\nEQUIVALENT" if (only_new == 0 and only_old == 0 and mism == 0)
          else "\n*** ROW SETS DIFFER ***", flush=True)
    await conn.execute(f"DROP TABLE IF EXISTS {SHADOW}")
    await conn.close()
asyncio.run(main())
