"""Does a SYMMETRIC shift slip past the median probe?

The probe asks whether the live data still splits at the stored median. A shift
that adds mass equally to BOTH tails leaves that fraction at 0.5 while the
bucket boundaries go badly wrong — the one hole named when the guard shipped.

Arms:
  SYMMETRIC   half the new rows at the bottom of the range, half at the top
  ASYMMETRIC  the control from the original experiment (top only), which the
              probe is known to catch

If SYMMETRIC produces a large error with a small median move, one probe is not
enough and quartile probes are the fix. If it produces a small error, the hole
is theoretical and costs nothing to leave open.
"""
import asyncio, os, random, sys
sys.path.insert(0, "/Users/hadfield/Local/vital-git/vital-graph")
os.chdir("/Users/hadfield/Local/vital-git/vital-graph")
import asyncpg, importlib.util
sys.argv = [sys.argv[0]]
spec = importlib.util.spec_from_file_location("bh", "test_scripts/perf/bench_histogram_drift_curve.py")
bh = importlib.util.module_from_spec(spec); spec.loader.exec_module(bh)
from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
from vitalgraph.db.sparql_sql.sync_value_stats import (
    estimate_range, load_value_stats, resync_value_stats)

async def arm(conn, label, mode):
    rng = random.Random(4242)
    await bh._ensure_space(conn)
    await bh._insert(conn, [rng.randrange(20, 80) for _ in range(bh.BASE_ROWS)], 0)
    await conn.execute(f"ANALYZE {bh.SPACE}_rdf_quad")
    await conn.execute(f"TRUNCATE {bh.SPACE}_rdf_pred_stats")
    await conn.execute(f"INSERT INTO {bh.SPACE}_rdf_pred_stats (predicate_uuid,row_count) "
                       f"SELECT predicate_uuid,count(*) FROM {bh.SPACE}_rdf_quad GROUP BY 1")
    await resync_value_stats(conn, bh.SPACE)
    st = await load_value_stats(conn, bh.SPACE)
    pu = str(bh._u(bh.SCORE))
    n = bh.BASE_ROWS
    if mode == "symmetric":
        new = ([rng.randrange(0, 20) for _ in range(n // 2)] +
               [rng.randrange(80, 100) for _ in range(n // 2)])
    else:
        new = [rng.randrange(80, 100) for _ in range(n)]
    await bh._insert(conn, new, bh.BASE_ROWS)
    # pred_stats is maintained on write in production; this harness writes with
    # raw inserts, so refresh it or the guard's pre-filter sees no drift at all.
    await conn.execute(f"TRUNCATE {bh.SPACE}_rdf_pred_stats")
    await conn.execute(f"INSERT INTO {bh.SPACE}_rdf_pred_stats (predicate_uuid,row_count) "
                       f"SELECT predicate_uuid,count(*) FROM {bh.SPACE}_rdf_quad GROUP BY 1")
    live = await conn.fetchval(
        f"SELECT count(*) FROM {bh.SPACE}_rdf_quad WHERE predicate_uuid=$1", bh._u(bh.SCORE))
    raw, scaled, detail = await bh._errors(conn, st, live, st[(pu,'num')]['total'])
    from vitalgraph.db.sparql_sql.sync_value_stats import apply_freshness, invalidate_freshness_cache
    invalidate_freshness_cache()
    st2 = await load_value_stats(conn, bh.SPACE)
    summ = await apply_freshness(conn, bh.SPACE, st2)
    caught = st2[(pu,'num')]['stale']
    after = estimate_range(st2, pu, "num", ">=", 75)
    print(f"{label:26s} worst err raw {raw:6.1%}  scaled {scaled:6.1%}   "
          f"shipped guard: {'DETECTED (withdrawn)' if caught else '*** MISSED ***'}"
          f"   >=75 now: {after}   {summ}", flush=True)
    for th, act, est, sc in detail:
        print(f"      >= {th:3d}: actual {act:7,}  scaled {sc:7,}", flush=True)

async def main():
    conn = await asyncpg.connect(host="localhost", port=5433,
        database="sparql_sql_graph", user="postgres", password="testpass")
    await conn.execute("SET statement_timeout='600s'")
    try:
        await arm(conn, "SYMMETRIC (both tails)", "symmetric")
        await arm(conn, "ASYMMETRIC (top only)", "asymmetric")
    finally:
        try:
            await SparqlSQLSchema.drop_space(conn, bh.SPACE)
            await conn.execute("DELETE FROM space WHERE space_id=$1", bh.SPACE)
        except Exception as e: print("cleanup:", e)
        await conn.close()
asyncio.run(main())
