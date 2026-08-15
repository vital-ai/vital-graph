"""Does restoring the 13 excluded `rdf_stats` pairs change any plan?

`rdf_stats` is rebuilt with `HAVING COUNT(*) <= 200000`, so the largest pairs in
a space are absent. `_load_missing_pair_stats` then falls back to a bounded
count that SATURATES at `_PAIR_COUNT_CAP`, so the join reorderer, the semijoin
marker and the slice direction gate all see 10,000 for pairs that are hundreds
of thousands of rows:

    vitaltype / KGEntity          946,548        rdf:type / KGFrame       473,274
    hasKGSlotType / hasSource...  473,274        hasKGSlotType / hasDest  473,274

`graph_fixtures.frame_hop` emits `?f a <KGFrame>` and both slot roles, so the
existing traversal corpus already touches three of them.

THE CHEAP CHECK FIRST. Three consumers read these counts, so the statistic can
only matter if the GENERATED SQL differs. That is a string comparison, not a
benchmark, and it costs one pass per arm. Only shapes whose SQL actually changes
are worth timing — and if none do, the answer is "this statistic changes no
decision", which is the same shape as the phase 0 finding that the DP and
`reorder_joins` pick the same driving end 8/8 while disagreeing 75% of the time.

    VG_TEST_PG_PORT=5433 python test_scripts/perf/bench_anchor_pair_stats.py
"""

import asyncio
import difflib
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

import asyncpg  # noqa: E402

from tests.performance.graph_fixtures import (  # noqa: E402
    CRITERIA, HALEY, LARGE, chain_query, relation_hop)
from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response  # noqa: E402
from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient  # noqa: E402
from vitalgraph.db.sparql_sql import generator

SIDECAR = os.environ.get("VG_TEST_SIDECAR_URL", "http://localhost:7071")
REPS = 7
SPACE = LARGE.space

ADD_PAIRS = f"""
INSERT INTO {SPACE}_rdf_stats (predicate_uuid, object_uuid, row_count)
SELECT predicate_uuid, object_uuid, count(*) FROM {SPACE}_rdf_quad
GROUP BY 1,2 HAVING count(*) > 200000 ON CONFLICT DO NOTHING"""
DROP_PAIRS = f"DELETE FROM {SPACE}_rdf_stats WHERE row_count > 200000"


def _anchor(criterion, limit=25, offset=0, entity_type="KGEntity"):
    """The shape the anchor pair actually appears in: type + criterion + page."""
    off = f" OFFSET {offset}" if offset else ""
    return f"""
    SELECT ?e ?sc WHERE {{ GRAPH <{LARGE.graph}> {{
        ?e a <{HALEY}{entity_type}> .
        ?e <{HALEY}hasScore> ?sc .
        {criterion}
    }} }} LIMIT {limit}{off}"""


def _relation(start, depth):
    hops = "".join(relation_hop(i + 1, f"?e{i}", f"?e{i + 1}")
                   for i in range(depth))
    return f"""
    SELECT DISTINCT ?e{depth} WHERE {{ GRAPH <{LARGE.graph}> {{
        {hops}
        FILTER(?e0 = <{LARGE.entity_uri(start)}>)
    }} }}"""


def corpus():
    s0 = LARGE.sample_starts()[0]
    s1 = LARGE.sample_starts()[2]
    score, _ = CRITERIA["score_gte_50"]
    cat, _ = CRITERIA["category_in_alpha_beta"]
    out = {
        "anchor + score, page 0": _anchor("FILTER(?sc >= 50)"),
        "anchor + score, deep page": _anchor("FILTER(?sc >= 50)", offset=5000),
        "anchor + score, no limit": _anchor("FILTER(?sc >= 90)", limit=100000),
        "anchor KGFrame + score": _anchor("FILTER(?sc >= 50)",
                                          entity_type="KGFrame"),
        "relation d2": _relation(s0, 2),
        "relation d3": _relation(s0, 3),
    }
    for d in (1, 2, 3):
        out[f"frame walk d{d}"] = chain_query(LARGE, s0, d)
        out[f"frame walk d{d} score"] = chain_query(LARGE, s0, d, criterion=score)
    out["frame walk d3 dense"] = chain_query(LARGE, s1, 3)
    out["frame walk d3 dense cat"] = chain_query(LARGE, s1, 3, criterion=cat)
    return out


async def compile_all(queries):
    c = AsyncSidecarClient(SIDECAR)
    try:
        out = {}
        for label, q in queries.items():
            cr = map_compile_response(await c.compile(q))
            assert cr.ok, f"{label}: {cr.error}"
            out[label] = cr
        return out
    finally:
        cl = getattr(c, "aclose", None) or getattr(c, "close", None)
        if cl:
            r = cl()
            if hasattr(r, "__await__"):
                await r


def clear_caches():
    """The pair counts are cached per process, keyed by space and pair."""
    # `_stats_cache` holds the loaded rdf_stats window per space and is the one
    # that would silently carry arm A's view into arm B.
    for name in ("_pair_count_cache", "_stats_cache", "_value_stats_cache",
                 "_datatype_cache"):
        c = getattr(generator, name, None)
        if isinstance(c, dict):
            c.clear()


async def gen_all(conn, compiled):
    clear_caches()
    out = {}
    for label, cr in compiled.items():
        g = await generator.generate_sql(cr, SPACE, conn=conn)
        assert g.ok, f"{label}: {g.error}"
        out[label] = g.sql
    return out


async def timed(conn, sql):
    t0 = time.perf_counter()
    rows = await conn.fetch(sql)
    return (time.perf_counter() - t0) * 1000.0, len(rows)


async def main():
    conn = await asyncpg.connect(
        host=os.environ.get("VG_TEST_PG_HOST", "localhost"),
        port=int(os.environ.get("VG_TEST_PG_PORT", "5433")),
        database=os.environ.get("VG_TEST_PG_DATABASE", "sparql_sql_graph"),
        user=os.environ.get("VG_TEST_PG_USER", "postgres"),
        password=os.environ.get("VG_TEST_PG_PASSWORD", "testpass"))
    await conn.execute("SET statement_timeout = '240s'")
    queries = corpus()
    compiled = await compile_all(queries)
    try:
        # Arm A — as it ships: the 13 pairs absent, counts saturate at the cap.
        await conn.execute(DROP_PAIRS)
        await conn.execute(f"ANALYZE {SPACE}_rdf_stats")
        sql_today = await gen_all(conn, compiled)

        # Arm B — the pairs restored, counts exact.
        print("adding the 13 pairs...", flush=True)
        await conn.execute(ADD_PAIRS)
        await conn.execute(f"ANALYZE {SPACE}_rdf_stats")
        sql_fixed = await gen_all(conn, compiled)

        changed = [k for k in queries if sql_today[k] != sql_fixed[k]]
        print(f"\n{len(changed)} of {len(queries)} shapes generate DIFFERENT "
              f"SQL:\n")
        for k in changed:
            d = list(difflib.unified_diff(
                sql_today[k].split("\n"), sql_fixed[k].split("\n"),
                lineterm="", n=0))
            print(f"  {k}: {len(d) - 2} diff lines")
            for line in d[2:8]:
                print(f"      {line[:110]}")
        if not changed:
            print("  (none — the statistic changes no decision on this corpus)")
            return

        print(f"\n{'shape':28s} {'today ms':>10s} {'fixed ms':>10s} "
              f"{'ratio':>7s}  rows")
        for k in changed:
            a, b = sql_today[k], sql_fixed[k]
            await timed(conn, a)
            await timed(conn, b)
            ta, tb, na, nb = [], [], None, None
            for _ in range(REPS):
                x, na = await timed(conn, a)
                y, nb = await timed(conn, b)
                ta.append(x)
                tb.append(y)
            ma, mb = statistics.median(ta), statistics.median(tb)
            warn = "" if na == nb else f"  ROWS DIFFER {na} vs {nb}"
            print(f"{k:28s} {ma:10.1f} {mb:10.1f} {ma / mb:6.2f}x  {na}{warn}")
    finally:
        # Leave the fixture as the documented rebuild produces it.
        await conn.execute(DROP_PAIRS)
        await conn.execute(f"ANALYZE {SPACE}_rdf_stats")
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
