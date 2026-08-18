"""Is the `enable_sort = off` fence a pessimization on near-empty match sets?

ANSWER: no. Measured 2026-08-10 on sp_lead_synth_100k, three reps per arm —
eq, gt and gte on KGDateTimeSlot all TIMED OUT at 45s with the fence both on
and off, identically. The fence is not what costs those cells.

(That was measured before the datetime semi-join gate was fixed; gt and gte are
now 70 ms and 36 ms, so the question is moot for them. Kept because the harness
— alternating arms, repeating, discarding the first run of each — is the shape
any "is this knob responsible" question should be answered in, and because a
recorded negative result stops the hypothesis being proposed again.)


`needs_ordered_scan` disables sorting so the planner walks the ORDER BY index and
early-terminates at LIMIT. That is a win when the match set is broad — a page
fills after a few index rows. It should be a LOSS when the match set is
near-empty: proving there is nothing to return means walking the entire index,
where a plain selective probe plus a sort over ~0 rows is instant.

`eq`/DateTime is the extreme case: this fixture's datetimes are unique per row
(issues/050), so an equality match finds essentially nothing.

Runs each cell both ways, alternating and repeating, discarding the first run of
each arm so cold cache does not decide the answer (the mistake in issues/053).
"""
import asyncio, os, sys, time
sys.path.insert(0, os.getcwd()); sys.path.insert(0, os.path.join(os.getcwd(), "scripts"))
from devtools.target import dsn, sidecar_url  # noqa: E402
import asyncpg
from perf_shape_matrix import build_criteria, sql_for, KGENTITY, SLOTS

SP  = os.environ.get("TSPACE", "sp_lead_synth_100k")
GR  = os.environ.get("TGRAPH", "urn:sp_lead_synth_100k")
DSN = dsn()
SIDE = sidecar_url()
BUDGET = float(os.environ.get("TBUDGET", "60"))
REPS = int(os.environ.get("TREPS", "3"))

DATETIME = [s for s in SLOTS if "DateTime" in s][0]
CELLS = [("eq", DATETIME), ("gt", DATETIME), ("gte", DATETIME)]


async def run(conn, sql, fence):
    t0 = time.time()
    async with conn.transaction():
        if fence:
            await conn.execute("SET LOCAL enable_sort = off")
        rows = await asyncio.wait_for(conn.fetch(sql), BUDGET)
    return (time.time() - t0) * 1000, len(rows)


async def main():
    conn = await asyncpg.connect(DSN, command_timeout=int(BUDGET) + 30)
    for comp, sc in CELLS:
        label = f"{comp}/{sc.split('#')[1]}"
        g = await sql_for(conn, build_criteria(comparator=comp, slot_class=sc),
                          SP, GR, KGENTITY, 25, SIDE)
        print(f"\n  {label}   needs_ordered_scan={g.needs_ordered_scan}")
        best = {True: None, False: None}
        for rep in range(REPS + 1):
            for fence in (True, False):
                try:
                    ms, n = await run(conn, g.sql, fence)
                    tag = "fence on " if fence else "fence off"
                    note = "  (discarded, cold)" if rep == 0 else ""
                    print(f"      {tag}  rep{rep}  {n:>3} rows {ms:>9,.0f} ms{note}")
                    if rep > 0 and (best[fence] is None or ms < best[fence]):
                        best[fence] = ms
                except asyncio.TimeoutError:
                    tag = "fence on " if fence else "fence off"
                    print(f"      {tag}  rep{rep}  TIMED OUT (>{BUDGET:.0f}s)")
                    if rep > 0 and best[fence] is None:
                        best[fence] = BUDGET * 1000
        on, off = best[True], best[False]
        if on and off:
            print(f"      -> best on={on:,.0f} ms  off={off:,.0f} ms  "
                  f"{'FENCE HURTS' if off < on / 2 else 'fence helps or neutral'}")
    await conn.close()

asyncio.run(main())
