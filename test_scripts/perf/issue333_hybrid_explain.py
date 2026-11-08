#!/usr/bin/env python3
"""A graph-scoped hybrid search, through both generators (`issues/333`).

Builds the hybrid search query (`issue333_search_common.hybrid_query`:
`vg:hybridSearch` scoped to one graph, `ORDER BY DESC(?score) LIMIT 12`),
generates SQL in-process the way the server does, with the planner
off (today's generation) and on (`planner_ext=True`, `VG_PLANNER_FEATURES`
honoured, e.g. `qtree`), substitutes a stored message embedding for the
query-vector placeholder (the cost is the same; the server would embed the
text), and runs each 5x with EXPLAIN (ANALYZE, BUFFERS) on the target database,
the way the executor runs it.

    VG_PLANNER_FEATURES=qtree python test_scripts/perf/issue333_hybrid_explain.py \
        --space perf_cjksearch --graph-name heavy --text 記得我夢到樓梯那個夢嗎

Prints, per generator: where the SQL came from (`plan_source`), min/med/max
execution ms, and the slowest run's plan.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from devtools.target import add_pg_arguments, describe_target, sidecar_url  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "test_scripts", "perf"))
import issue333_search_common as sc  # noqa: E402


async def compile_sparql(sparql: str):
    import httpx
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    async with httpx.AsyncClient(base_url=sidecar_url(), timeout=30.0) as c:
        r = await c.post("/v1/sparql/compile", json={"sparql": sparql})
        r.raise_for_status()
    cr = map_compile_response(r.json())
    if not cr.ok:
        raise RuntimeError(cr.error)
    return cr


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--space", default="perf_cjksearch")
    ap.add_argument("--index", default="messages")
    ap.add_argument("--graph-name", default="heavy",
                    help="the fixture graph (`urn:<space>:graph:<name>`)")
    ap.add_argument("--graph", default=None, help="a graph URI, overriding --graph-name")
    ap.add_argument("--text", default="記得我夢到樓梯那個夢嗎")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--show-sql", action="store_true")
    ap.add_argument("--plan-lines", type=int, default=60)
    ap.add_argument("--only", choices=["default", "planner"], default=None)
    add_pg_arguments(ap)
    a = ap.parse_args()
    import logging
    logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s")
    # One line per statement: which rewrites fired and which declined, and why.
    logging.getLogger("vitalgraph.db.sparql_sql.plan_decisions").setLevel(logging.INFO)
    from vitalgraph.db.sparql_sql.generator import generate_sql
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import (
        _apply_join_order, _apply_planner_advice)
    from vitalgraph.db.sparql_sql.space_names import space_prefix
    from vitalgraph.db.sparql_sql.space_storage_key import load_storage_keys

    graph = a.graph or f"urn:{a.space}:graph:{a.graph_name}"
    sparql = sc.hybrid_query(graph, a.text, a.index)
    print(f"target: {describe_target(a)}\nspace={a.space} graph={graph}\n{sparql}\n")

    import asyncpg
    conn = await asyncpg.connect(host=a.host, port=a.port, database=a.database,
                                 user=a.user, password=a.password or None)
    try:
        await load_storage_keys(conn)
        p = space_prefix(a.space)
        vec = await conn.fetchval(f"SELECT embedding::text FROM {p}_vec_{a.index} LIMIT 1")
        n_graph = await conn.fetchval(
            f"SELECT count(*) FROM {p}_fts_{a.index} WHERE context_uuid = "
            f"vitalgraph_term_uuid($1, 'U')", graph)
        langs = await conn.fetchval(
            f"SELECT languages FROM {p}_fts_index WHERE index_name = $1", a.index)
        print(f"graph FTS rows: {n_graph:,}   index languages: {list(langs)}\n")
        cr = await compile_sparql(sparql)
        for label, ext in (("default", False), ("planner", True)):
            if a.only and a.only != label:
                continue
            gen = await generate_sql(cr, a.space, conn=conn, planner_ext=ext)
            if not gen.ok:
                print(f"== {label}: generation failed: {gen.error}")
                continue
            sql = gen.sql
            for vr in gen.vector_requests or []:
                sql = sql.replace(f"'{vr.placeholder}'::vector", f"'{vec}'::vector")
            sql = re.sub(r"'__VG_EMBED_\d+__'::vector", f"'{vec}'::vector", sql)
            advice = getattr(gen, "plan_advice", None) or ""
            if a.show_sql:
                print(sql)
            times, plan = [], None
            for _ in range(a.runs):
                # AS THE EXECUTOR RUNS IT: its own helpers, in a transaction, so
                # the SET LOCALs it adds (the join-order pin for a fixed order,
                # which every qtree plan has; the advice mismatch policy) apply
                # here too. Without them the plan measured is not the one served.
                async with conn.transaction():
                    await _apply_join_order(conn, gen)
                    await _apply_planner_advice(conn, gen)
                    rows = await conn.fetch(
                        f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {advice}\n{sql}")
                text = "\n".join(r[0] for r in rows)
                ms = float(re.search(r"Execution Time: ([\d.]+) ms", text).group(1))
                times.append(ms)
                if plan is None or ms >= max(times):
                    plan = text
            print(f"== {label}  plan_source={getattr(gen, 'plan_source', None)!r}  "
                  f"advice={'yes' if advice else 'no'}  "
                  f"pinned={bool(getattr(gen, 'fixed_join_order', False))}  "
                  f"sql={len(sql):,} chars")
            print(f"   exec ms min/med/max  {min(times):.1f} / "
                  f"{statistics.median(times):.1f} / {max(times):.1f}")
            plan = re.sub(r"'\[[-0-9.e, ]{100,}\]'::vector", "'<vec>'::vector", plan)
            print("   " + "\n   ".join(plan.splitlines()[:a.plan_lines]) + "\n")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
