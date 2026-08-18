"""Every comparator x slot class at scale, page of 25: cold, warm, and buffers.

This used to print ONE cold execution per cell and nothing else. That was enough
for its original job — separating "completes" from "times out" — and actively
misleading for anything finer, in two ways that both bit hard:

  * A cold single shot is 8-63x the warm cost on these cells (eq/Integer 2,348 ms
    cold, 37 ms warm). Reading the output as query cost puts most of the
    attention on cache behaviour. After the comparator work the sweep reported
    "4 cells exceed 1s" and exactly ONE of the four was a query-cost problem.
  * Wall time cannot be compared across runs without repetition discipline. Two
    rounds of A/B numbers in this effort were voided by cold-cache ordering
    (issues/072), and one of them was written up and committed first.

Buffer counts have neither problem. They are identical cold or warm, they do not
move with machine or load, and they are absurd on their face when something is
wrong: is_empty touches 18.4M buffers to return 25 rows. Had this script emitted
them, four false positives would have been visibly zero-delta and the one real
finding visibly the outlier — without any repetition at all. So buffers lead and
wall time is context, per performance_regression_tracking_plan.md R1/R1.1.

    TSPACE  TGRAPH  TDSN  TSIDE      fixture / connection
    TBUDGET                          per-execution timeout, seconds (default 60)
    TCOLD=0                          skip the cold pass — HALVES THE RUNTIME AND
                                     THE MEANING. With no first pass to warm the
                                     cache, the single execution IS the cold one,
                                     so the "warm" column reports cold numbers
                                     under a warm heading. Use it only to compare
                                     TCOLD=0 runs against each other, never
                                     against a full run.
"""
import asyncio
import os
import re
import sys
import time

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "scripts"))
from devtools.target import dsn, sidecar_url  # noqa: E402
import asyncpg
from perf_shape_matrix import build_criteria, sql_for, COMPARATORS, KGENTITY

SP = os.environ.get("TSPACE", "sp_lead_synth_100k")
GR = os.environ.get("TGRAPH", "urn:sp_lead_synth_100k")
DSN = dsn()
SIDE = sidecar_url()
BUDGET = float(os.environ.get("TBUDGET", "60"))
WANT_COLD = os.environ.get("TCOLD", "1") != "0"

# A 25-row page reading more than this is doing something structurally wrong,
# whatever the clock says. Set from observation: healthy cells here sit in the
# hundreds to low tens of thousands; is_empty reads 18.4M.
BUFFER_ALARM = 500_000

_BUF_RE = re.compile(r"shared hit=(\d+)(?: read=(\d+))?")


async def _run(conn, g, sql=None):
    """Execute, honouring the ordered-scan fence the executor applies."""
    async with conn.transaction():
        if g.needs_ordered_scan:
            await conn.execute("SET LOCAL enable_sort = off")
        return await asyncio.wait_for(conn.fetch(sql or g.sql), BUDGET)


async def _buffers(conn, g):
    """Shared buffers touched, from EXPLAIN (ANALYZE, BUFFERS).

    The MAXIMUM over nodes, not the sum. EXPLAIN reports each node's buffers
    CUMULATIVELY — a node's line already includes everything its children
    touched — so summing multiply-counts by the depth of the tree. The first
    version of this function summed, and reported `not_exists` at 7,236,171
    buffers when the true figure is 1,336,741: inflated 5.4x, and the wrong
    number reached an issue before the mistake was caught.

    The root is cumulative for the whole plan, so max() is it. Caveat worth
    knowing: a CTE evaluated as its own subtree can be reported outside the
    root's count, so this is a lower bound for plans with CTEs — which the
    candidate-driven negation path produces. Better a documented lower bound
    than a number that grows with plan depth.
    """
    try:
        rows = await _run(conn, g, "EXPLAIN (ANALYZE, BUFFERS, TIMING OFF, COSTS OFF) " + g.sql)
    except asyncio.TimeoutError:
        return None
    best = 0
    for r in rows:
        m = _BUF_RE.search(r[0])
        if m:
            best = max(best, int(m.group(1)) + int(m.group(2) or 0))
    return best


async def server_config(conn) -> str:
    """The settings a timing here depends on. Printed, not just available.

    Every number this script ever produced was taken with `shared_buffers` at
    1 GB on a 64 GB machine, and nobody noticed because no output said so. On a
    fixture whose queries touch 400,000+ buffers that made a sorted page 27x
    slower than it is on a correct configuration (`issues/081`), and cost four
    implementation attempts chasing a query-shape explanation for a memory
    setting. A number without its configuration is not reproducible.
    """
    rows = await conn.fetch(
        "SELECT name, setting, unit FROM pg_settings WHERE name = ANY($1)",
        ["shared_buffers", "effective_cache_size", "work_mem",
         "random_page_cost", "max_parallel_workers_per_gather"])
    parts = []
    for r in rows:
        v = int(r["setting"]) if r["setting"].isdigit() else r["setting"]
        if r["unit"] == "8kB" and isinstance(v, int):
            v = f"{v * 8 // 1024}MB" if v * 8 < 1024 * 1024 else f"{v * 8 // 1048576}GB"
        elif r["unit"] == "kB" and isinstance(v, int):
            v = f"{v // 1024}MB"
        parts.append(f"{r['name']}={v}")
    return "  ".join(parts)


async def main():
    conn = await asyncpg.connect(DSN, command_timeout=int(BUDGET) + 30)
    slow_warm, heavy, cold_only = [], [], []

    print(f"  server: {await server_config(conn)}")
    print(f"  fixture: {SP}\n")
    print(f"  {'cell':30s} {'cold':>9s} {'warm':>9s} {'buffers':>12s}  rows")
    for comp, classes in COMPARATORS.items():
        for sc in classes:
            label = f"{comp}/{sc.split('#')[1]}"
            try:
                g = await sql_for(conn, build_criteria(comparator=comp, slot_class=sc),
                                  SP, GR, KGENTITY, 25, SIDE)
            except Exception as e:
                print(f"  {label:30s} GEN FAILED {type(e).__name__}")
                continue

            cold = warm = None
            n = None
            if WANT_COLD:
                t0 = time.time()
                try:
                    rows = await _run(conn, g)
                    cold = (time.time() - t0) * 1000
                    n = len(rows)
                except asyncio.TimeoutError:
                    cold = BUDGET * 1000
            # Warm: whatever the cold pass left cached, plus one more.
            t0 = time.time()
            try:
                rows = await _run(conn, g)
                warm = (time.time() - t0) * 1000
                n = len(rows)
            except asyncio.TimeoutError:
                warm = BUDGET * 1000

            bufs = await _buffers(conn, g)

            if warm > 1000:
                slow_warm.append((label, warm))
            elif cold is not None and cold > 1000:
                cold_only.append((label, cold, warm))
            if bufs is not None and bufs > BUFFER_ALARM:
                heavy.append((label, bufs))

            c_txt = f"{cold:,.0f}ms" if cold is not None else "-"
            b_txt = f"{bufs:,}" if bufs is not None else "timeout"
            flag = "  <-- SLOW WARM" if warm > 1000 else ""
            print(f"  {label:30s} {c_txt:>9s} {warm:>7,.0f}ms {b_txt:>12s}  {n}{flag}")

    print(f"\n  {len(slow_warm)} cells are slow WARM — these are query-cost problems")
    for l, ms in sorted(slow_warm, key=lambda x: -x[1]):
        print(f"    {l:30s} {ms:>9,.0f} ms")

    print(f"\n  {len(cold_only)} cells are slow COLD ONLY — first-touch I/O, not query cost")
    for l, c, w in sorted(cold_only, key=lambda x: -x[1]):
        print(f"    {l:30s} {c:>9,.0f} ms cold  ->{w:>8,.0f} ms warm")

    print(f"\n  {len(heavy)} cells read more than {BUFFER_ALARM:,} buffers for 25 rows")
    print("  (machine-independent, identical cold or warm — the signal to trust)")
    for l, b in sorted(heavy, key=lambda x: -x[1]):
        print(f"    {l:30s} {b:>14,} buffers")

    await conn.close()

asyncio.run(main())
