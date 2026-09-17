"""Record the entity_slot_sort coverage marker for one space.

The periodic maintenance job does this, and `lead_nurture_100k` is deliberately
excluded from periodic jobs -- so on this stack it has to be run by hand. With
no marker the FILTER fast path declines and every criteria query falls back to
the SPARQL plan that times out.
"""
import asyncio, os, sys, time
sys.path.insert(0, os.getcwd())
import logging; logging.disable(logging.CRITICAL)
import asyncpg
from vitalgraph.db.sparql_sql.sync_entity_slot_sort import entity_slot_sort_all_types
from vitalgraph.db.sparql_sql.fast_slot_filter import record_slot_sort_coverage

SPACE = sys.argv[1] if len(sys.argv) > 1 else "lead_nurture_100k"

async def main():
    # Same defaults as before, but read through the shared selector: a script
    # with its own hardcoded parameters is how a measurement gets taken against
    # the host cluster and reported as the test stack's (devtools/vg-test.env).
    conn = await asyncpg.connect(
        host=os.environ.get("VG_TEST_PG_HOST", "localhost"),
        port=int(os.environ.get("VG_TEST_PG_PORT", "5433")),
        database=os.environ.get("VG_TEST_PG_DATABASE", "sparql_sql_graph"),
        user=os.environ.get("VG_TEST_PG_USER", "postgres"),
        password=os.environ.get("VG_TEST_PG_PASSWORD", "testpass"))
    try:
        await conn.execute("SET statement_timeout = '600s'")
        t0 = time.monotonic()
        covs = await entity_slot_sort_all_types(conn, SPACE, timeout=600)
        print(f"  probed {len(covs)} entity type(s) in "
              f"{(time.monotonic()-t0):.1f}s", flush=True)
        for cov in covs:
            await record_slot_sort_coverage(conn, SPACE, cov["entity_type_uuid"],
                                            cov["in_table"], cov["of_type"])
            flag = "COMPLETE" if cov["in_table"] >= cov["of_type"] else "short"
            print(f"    in_table={cov['in_table']:<9} of_type={cov['of_type']:<9} {flag}")
    finally:
        await conn.close()

asyncio.run(main())
