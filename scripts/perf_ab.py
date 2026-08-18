"""A/B a planner setting across comparator cells, without fooling yourself.

Use this instead of writing a comparison loop inline. Twice in this effort an
inline loop of the shape

    for arm in (baseline, treatment):
        run()

produced a large fake win, because the FIRST arm pays first-touch I/O and the
second reads a warm cache. It reported `eq`/Integer at 54x and `eq`/Text at 51x;
both are actually unchanged (issues/072). The same mistake had already voided an
earlier round of measurements in the same effort.

So the harness, not the discipline, is the fix. This module:

  - alternates arms within each repetition, so neither is systematically first
  - discards repetition 0 entirely, in both arms, as cold
  - keeps the BEST of the remaining runs per arm, since the minimum is the least
    noisy estimator of a query's cost
  - applies `enable_sort = off` when the plan declares `needs_ordered_scan`,
    because that is what the executor does in production and omitting it
    measures a plan that never runs

Cold-start cost is a real thing to measure, but it is a DIFFERENT thing, and
`perf_comparator_timing.py` already measures it by running each cell once.

Usage:

    from perf_ab import ab_cells
    await ab_cells(conn, [("is_empty", TEXT)],
                   arms={"baseline": [], "nestloop=off": ["enable_nestloop = off"]})
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "scripts"))
from devtools.target import dsn, sidecar_url  # noqa: E402

from perf_shape_matrix import build_criteria, sql_for, KGENTITY  # noqa: E402

SPACE = os.environ.get("TSPACE", "sp_lead_synth_100k")
GRAPH = os.environ.get("TGRAPH", "urn:sp_lead_synth_100k")
SIDECAR = sidecar_url()
BUDGET = float(os.environ.get("TBUDGET", "60"))
REPS = int(os.environ.get("TREPS", "3"))


async def _run_once(conn, sql, settings, ordered_scan):
    t0 = time.time()
    async with conn.transaction():
        if ordered_scan:
            await conn.execute("SET LOCAL enable_sort = off")
        for s in settings:
            await conn.execute(f"SET LOCAL {s}")
        rows = await asyncio.wait_for(conn.fetch(sql), BUDGET)
    return (time.time() - t0) * 1000, len(rows)


async def ab_cells(conn, cells, arms, page=25):
    """Compare `arms` (name -> list of SET LOCAL clauses) over `cells`.

    Returns {cell_label: {arm_name: best_ms}}. Prints a table as it goes.
    """
    names = list(arms)
    header = "".join(f"{n:>15s}" for n in names)
    print(f"  {'cell':26s}{header}   rows")
    out = {}
    for comp, slot_class in cells:
        label = f"{comp}/{slot_class.split('#')[1]}"
        g = await sql_for(conn, build_criteria(comparator=comp, slot_class=slot_class),
                          SPACE, GRAPH, KGENTITY, page, SIDECAR)
        best = {n: None for n in names}
        n_rows = None
        for rep in range(REPS + 1):
            # alternate direction each rep so no arm is always first
            order = names if rep % 2 == 0 else list(reversed(names))
            for name in order:
                try:
                    ms, rows = await _run_once(conn, g.sql, arms[name],
                                               g.needs_ordered_scan)
                    n_rows = rows
                except asyncio.TimeoutError:
                    ms = BUDGET * 1000
                if rep == 0:
                    continue          # cold, discarded in EVERY arm
                if best[name] is None or ms < best[name]:
                    best[name] = ms
        cells_txt = "".join(f"{best[n]:>13,.0f}ms" for n in names)
        print(f"  {label:26s}{cells_txt}   {n_rows}")
        out[label] = best
    return out
