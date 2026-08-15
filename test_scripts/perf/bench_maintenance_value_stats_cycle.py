"""The new step must FIRE, not just return None on a clean database.

A cycle where every detector finds nothing reads exactly like a cycle whose
detectors are broken. This introduces drift, runs a real cycle, and asserts the
step picked the space up and repaired it.
"""
import asyncio, os, sys
sys.path.insert(0, "/Users/hadfield/Local/vital-git/vital-graph")
os.chdir("/Users/hadfield/Local/vital-git/vital-graph")
import asyncpg
from vitalgraph.process.maintenance_job import MaintenanceJob

SPACE = "sp_graph_synth_10k"

async def main():
    pool = await asyncpg.create_pool(host="localhost", port=5433,
        database="sparql_sql_graph", user="postgres", password="testpass",
        min_size=2, max_size=5, command_timeout=900)
    job = MaintenanceJob(pool, postgresql_config={
        "host": "localhost", "port": 5433, "database": "sparql_sql_graph",
        "username": "postgres", "password": "testpass"})

    async with pool.acquire() as conn:
        orig = await conn.fetch(
            f"SELECT predicate_uuid, lane, max(pred_rows) pr "
            f"FROM {SPACE}_rdf_value_stats GROUP BY 1,2")
        # Halve the reference: 2.00x drift, well past the 0.50 threshold.
        await conn.execute(f"UPDATE {SPACE}_rdf_value_stats SET pred_rows = pred_rows/2")

    summary = await job.run()
    vs = summary.get("value_stats")
    print("value_stats step:", vs)
    ok = bool(vs) and vs.get("space_id") == SPACE and not vs.get("failed")
    print("aborted:", summary.get("aborted"))

    async with pool.acquire() as conn:
        left = await conn.fetchval(f"""
            SELECT count(*) FROM {SPACE}_rdf_value_stats vs
            JOIN {SPACE}_rdf_pred_stats ps ON ps.predicate_uuid=vs.predicate_uuid
            WHERE vs.pred_rows IS NOT NULL AND vs.pred_rows > 0
              AND abs(ps.row_count::float8/vs.pred_rows - 1) > 0.50""")
    print(f"drifted histograms remaining after the cycle: {left}")
    print("\nSTEP FIRES AND REPAIRS" if (ok and left == 0) else "\n*** STEP DID NOT FIRE ***")
    await pool.close()
asyncio.run(main())
