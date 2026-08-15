"""The maintenance detector must find a drifted space and repair it.

Simulates drift by lowering the stored reference — non-destructive and
reversible — then runs the detector, asserts it picks the space, and confirms
the rebuild resets the drift to zero.
"""
import asyncio, os, sys
sys.path.insert(0, "/Users/hadfield/Local/vital-git/vital-graph")
os.chdir("/Users/hadfield/Local/vital-git/vital-graph")
import asyncpg
from vitalgraph.process.maintenance_job import VALUE_STATS_DRIFT_THRESHOLD

SPACE = "sp_graph_synth_10k"

async def drift_count(conn, space):
    return await conn.fetchrow(f"""
        SELECT count(*) AS n,
               max(abs(ps.row_count::float8 / vs.pred_rows - 1)) AS d
        FROM {space}_rdf_value_stats vs
        JOIN {space}_rdf_pred_stats ps ON ps.predicate_uuid = vs.predicate_uuid
        WHERE vs.pred_rows IS NOT NULL AND vs.pred_rows > 0
          AND abs(ps.row_count::float8 / vs.pred_rows - 1)
              > {VALUE_STATS_DRIFT_THRESHOLD}""")

async def main():
    conn = await asyncpg.connect(host="localhost", port=5433,
        database="sparql_sql_graph", user="postgres", password="testpass")
    await conn.execute("SET statement_timeout='600s'")
    orig = await conn.fetch(
        f"SELECT predicate_uuid, lane, max(pred_rows) pr "
        f"FROM {SPACE}_rdf_value_stats GROUP BY 1,2")
    before = await drift_count(conn, SPACE)
    print(f"threshold {VALUE_STATS_DRIFT_THRESHOLD}")
    print(f"clean space: {before['n']} drifted histogram(s)  <- must be 0")
    # Halve the reference: the space now looks 2.00x grown, well past 0.50.
    await conn.execute(f"UPDATE {SPACE}_rdf_value_stats SET pred_rows = pred_rows / 2")
    mid = await drift_count(conn, SPACE)
    print(f"after 2.00x drift: {mid['n']} drifted, worst {mid['d']:.2f}  <- must be > 0")
    # A 10% drift must NOT trip it — that is the whole point of the gap between
    # this threshold and the read path's 2%.
    for r in orig:
        await conn.execute(
            f"UPDATE {SPACE}_rdf_value_stats SET pred_rows = $1 "
            f"WHERE predicate_uuid=$2 AND lane=$3",
            int(r["pr"] / 1.10), r["predicate_uuid"], r["lane"])
    small = await drift_count(conn, SPACE)
    print(f"after 1.10x drift: {small['n']} drifted  <- must be 0 (below threshold)")
    # Repair, and confirm drift goes to zero.
    from vitalgraph.db.sparql_sql.sync_value_stats import resync_value_stats
    await conn.execute(f"UPDATE {SPACE}_rdf_value_stats SET pred_rows = pred_rows / 2")
    await resync_value_stats(conn, SPACE)
    after = await drift_count(conn, SPACE)
    print(f"after rebuild: {after['n']} drifted  <- must be 0")
    ok = (before["n"] == 0 and mid["n"] > 0 and small["n"] == 0 and after["n"] == 0)
    print("\nDETECTOR", "OK" if ok else "*** WRONG ***")
    await conn.close()
asyncio.run(main())
