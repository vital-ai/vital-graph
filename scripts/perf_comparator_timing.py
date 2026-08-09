"""Time every comparator x slot class at scale, page of 25."""
import asyncio, os, sys, time
sys.path.insert(0, os.getcwd()); sys.path.insert(0, os.path.join(os.getcwd(), "scripts"))
import asyncpg
from perf_shape_matrix import build_criteria, sql_for, COMPARATORS, SLOTS, KGENTITY
SP  = os.environ.get("TSPACE", "sp_lead_synth_100k")
GR  = os.environ.get("TGRAPH", "urn:lead_synth_100k")
DSN = os.environ.get("TDSN", "postgresql://hadfield@localhost:5432/sparql_sql_graph")
SIDE= os.environ.get("TSIDE", "http://localhost:7070")
BUDGET = float(os.environ.get("TBUDGET", "60"))

async def main():
    conn = await asyncpg.connect(DSN, command_timeout=int(BUDGET) + 30)
    slow = []
    for comp, classes in COMPARATORS.items():
        for sc in classes:
            label = f"{comp}/{sc.split('#')[1]}"
            try:
                g = await sql_for(conn, build_criteria(comparator=comp, slot_class=sc),
                                  SP, GR, KGENTITY, 25, SIDE)
            except Exception as e:
                print(f"  {label:34s} GEN FAILED {type(e).__name__}"); continue
            t0 = time.time()
            try:
                if g.needs_ordered_scan:
                    async with conn.transaction():
                        await conn.execute("SET LOCAL enable_sort = off")
                        rows = await asyncio.wait_for(conn.fetch(g.sql), BUDGET)
                else:
                    rows = await asyncio.wait_for(conn.fetch(g.sql), BUDGET)
                ms = (time.time()-t0)*1000
                flag = "  <-- SLOW" if ms > 1000 else ""
                if ms > 1000: slow.append((label, ms))
                print(f"  {label:34s} {len(rows):>3} rows {ms:>9,.0f} ms{flag}")
            except asyncio.TimeoutError:
                slow.append((label, BUDGET*1000))
                print(f"  {label:34s} TIMED OUT (>{BUDGET:.0f}s)  <-- SLOW")
    print(f"\n  {len(slow)} of the swept cells exceed 1s")
    for l, ms in sorted(slow, key=lambda x: -x[1]):
        print(f"    {l:34s} {ms:>9,.0f} ms")
    await conn.close()
asyncio.run(main())
