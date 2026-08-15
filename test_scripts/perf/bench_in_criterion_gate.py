"""What the criterion gate is worth once an IN criterion is measurable.

The gate (`traversal_decision`) only chooses between FLAT and HOP-WISE, and it
is consulted only when `emit_dedup_chain` has already declined — dedup is tried
first and is deliberately not gated. So the gate's value is not "what the IN fix
is worth to traversals" generally; it is what it is worth on the shapes where
dedup is unavailable. Those are:

    S1  depth 1                        dedup requires depth >= 2
    S2  SELECT DISTINCT ?e1 ?e3        projection not confined to survivors
    S3  no DISTINCT                    path multiplicity is part of the answer

Each is measured with `category IN ("alpha","beta")` — unmeasurable until the
13 pairs excluded by `HAVING COUNT(*) <= 200000` were restored — and with
`score >= 50` as a control that was already measurable, so a null result on the
IN arm can be told apart from a harness that cannot see a difference at all.

Arms are forced at the decision, not by toggling statistics, so the only thing
that varies is the emitted shape. Answers are compared between arms: a faster
plan that returns a different bag is not a faster plan.

    VG_TEST_PG_PORT=5433 python test_scripts/perf/bench_in_criterion_gate.py
"""

import asyncio
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

import asyncpg  # noqa: E402

from tests.performance.graph_fixtures import (  # noqa: E402
    CRITERIA, LARGE, frame_hop)
from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response  # noqa: E402
from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient  # noqa: E402
from vitalgraph.db.sparql_sql import generator, traversal_decision

REPS = 5
SIDECAR = os.environ.get("VG_TEST_SIDECAR_URL", "http://localhost:7071")

_force = {"hop_wise": None}
_real_decide_for_plan = traversal_decision.decide_for_plan


def _patched(chains, criterion_rows=None, predicate_rows=None):
    d = _real_decide_for_plan(chains, criterion_rows, predicate_rows)
    if _force["hop_wise"] is not None and d.chain is not None:
        d.hop_wise = _force["hop_wise"]
    return d


traversal_decision.decide_for_plan = _patched


def _query(start, depth, criterion, *, distinct=True, project_mid=False):
    hops = "".join(frame_hop(i + 1, f"?e{i}", f"?e{i + 1}", criterion)
                   for i in range(depth))
    proj = f"?e1 ?e{depth}" if project_mid else f"?e{depth}"
    return f"""
    SELECT {'DISTINCT ' if distinct else ''}{proj} WHERE {{
      GRAPH <{LARGE.graph}> {{
        {hops}
        FILTER(?e0 = <{LARGE.entity_uri(start)}>)
    }} }}"""


SHAPES = {
    "S1 depth 1": lambda s, c: _query(s, 1, c),
    "S2 d3, project ?e1 too": lambda s, c: _query(s, 3, c, project_mid=True),
    "S3 d2, no DISTINCT": lambda s, c: _query(s, 2, c, distinct=False),
}


async def compile_sparql(q):
    c = AsyncSidecarClient(SIDECAR)
    try:
        raw = await c.compile(q)
    finally:
        cl = getattr(c, "aclose", None) or getattr(c, "close", None)
        if cl:
            r = cl()
            if hasattr(r, "__await__"):
                await r
    cr = map_compile_response(raw)
    assert cr.ok, cr.error
    return cr


async def gen_for(conn, cr, hop_wise):
    _force["hop_wise"] = hop_wise
    try:
        return await generator.generate_sql(cr, LARGE.space, conn=conn)
    finally:
        _force["hop_wise"] = None


async def timed(conn, sql):
    t0 = time.perf_counter()
    rows = await conn.fetch(sql)
    return (time.perf_counter() - t0) * 1000.0, len(rows)


def shape_of(sql):
    if "MATERIALIZED" in sql:
        return "dedup"
    if "CROSS JOIN LATERAL" in sql:
        return "hop-wise"
    return "flat"


async def main():
    conn = await asyncpg.connect(
        host=os.environ.get("VG_TEST_PG_HOST", "localhost"),
        port=int(os.environ.get("VG_TEST_PG_PORT", "5433")),
        database=os.environ.get("VG_TEST_PG_DATABASE", "sparql_sql_graph"),
        user=os.environ.get("VG_TEST_PG_USER", "postgres"),
        password=os.environ.get("VG_TEST_PG_PASSWORD", "testpass"))
    await conn.execute("SET statement_timeout = '180s'")
    starts = LARGE.sample_starts()[:3]
    print(f"{'shape':24s} {'criterion':16s} {'start':>7s} "
          f"{'flat ms':>10s} {'hop-wise':>10s} {'ratio':>7s}  rows")
    try:
        for label, build in SHAPES.items():
            for cname in ("category_in_alpha_beta", "score_gte_50"):
                tpl, _k = CRITERIA[cname]
                for start in starts:
                    cr = await compile_sparql(build(start, tpl))
                    g_flat = await gen_for(conn, cr, False)
                    g_hop = await gen_for(conn, cr, True)
                    s_flat, s_hop = shape_of(g_flat.sql), shape_of(g_hop.sql)
                    if s_flat == "dedup" or s_hop == "dedup":
                        print(f"{label:24s} {cname[:16]:16s} {start:7d}  "
                              f"SKIP — dedup applies, the gate does not decide")
                        break
                    if s_flat == s_hop:
                        print(f"{label:24s} {cname[:16]:16s} {start:7d}  "
                              f"SKIP — both arms emitted {s_flat}")
                        continue
                    # Warm, then interleave so drift hits both arms equally.
                    await timed(conn, g_flat.sql)
                    await timed(conn, g_hop.sql)
                    tf, th, nf, nh = [], [], None, None
                    for _ in range(REPS):
                        a, nf = await timed(conn, g_flat.sql)
                        b, nh = await timed(conn, g_hop.sql)
                        tf.append(a)
                        th.append(b)
                    mf, mh = statistics.median(tf), statistics.median(th)
                    same = "" if nf == nh else f"  ROWS DIFFER {nf} vs {nh}"
                    print(f"{label:24s} {cname[:16]:16s} {start:7d} "
                          f"{mf:10.1f} {mh:10.1f} {mf / mh:6.2f}x  {nf}{same}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
