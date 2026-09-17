"""Does `rewrite_merge_bgp` already reach 096's shape, as it did 181's?

096 wants a direction gate. 181 wanted the same widening ("let a constraint
count as a driving set"), measured it at 8.6x WORSE with ORDER BY + LIMIT, and
closed as superseded by `rewrite_merge_bgp`. 096's shape is ALSO ORDER BY +
LIMIT, so the same question applies before building anything.

Reproduces 096's own two rows on 096's own fixture (cardiff_kg, CompanyName,
2,863 KGLead):

    as generated today      507,492 buffers   360 ms
    entity pinned to ONE      222 buffers     0.7 ms
"""
import asyncio, os, sys, re
sys.path.insert(0, os.getcwd())
import logging; logging.disable(logging.CRITICAL)
import asyncpg
from vitalgraph.sparql.kg_query_builder import (
    KGQueryCriteriaBuilder, EntityQueryCriteria, SortCriteria)
from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
from vitalgraph.db.sparql_sql.generator import generate_sql

SPACE, GRAPH = "cardiff_kg", "urn:cardiff_kg"
NS, KG = "urn:cardiff:kg", "http://vital.ai/ontology/haley-ai-kg#"
PAGE = 25


def _sort(slot):
    return SortCriteria(
        sort_type="entity_frame_slot", slot_type=f"{NS}:slot:{slot}",
        slot_class_uri=KG + "KGTextSlot",
        frame_path=[f"{NS}:frame:KGLeadInfoFrame"], sort_order="asc")


def crit(entity_uris=None, second_key=False):
    c = EntityQueryCriteria(
        entity_type=f"{NS}:entity:KGLead", entity_uris=entity_uris,
        sort_criteria=[SortCriteria(
            sort_type="entity_frame_slot",
            slot_type=f"{NS}:slot:CompanyName",
            slot_class_uri=KG + "KGTextSlot",
            frame_path=[f"{NS}:frame:KGLeadInfoFrame"],
            sort_order="asc")])
    if second_key:
        # DECLINES can_serve (len(sc) != 1), so this one really does reach the
        # general pipeline -- unlike the plain list, which the table serves.
        c.sort_criteria.append(_sort("SFLeadId"))
    return c


async def compile_sparql(sparql):
    cl = AsyncSidecarClient("http://localhost:7071")
    try:
        raw = await cl.compile(sparql)
    finally:
        cf = getattr(cl, "aclose", None) or getattr(cl, "close", None)
        if cf:
            r = cf()
            if hasattr(r, "__await__"):
                await r
    return map_compile_response(raw)


async def run(conn, label, entity_uris, second_key=False):
    from vitalgraph.db.sparql_sql.fast_slot_sort import can_serve
    served = can_serve(crit(entity_uris, second_key))
    sparql = KGQueryCriteriaBuilder().build_entity_query_sparql(
        crit(entity_uris, second_key), GRAPH, PAGE, 0)
    cr = await compile_sparql(sparql)
    if not cr.ok:
        print(f"  {label:34s} compile failed: {str(cr.error)[:70]}"); return
    g = await generate_sql(cr, SPACE, conn=conn)
    if not g.ok:
        print(f"  {label:34s} generate failed: {str(g.error)[:70]}"); return

    pd = g.plan_decisions or {}
    fired = [k for k in _fired(pd)]
    merge = any("merge" in f for f in fired)

    await conn.execute("SET jit = off")
    # EXPLAIN returns ONE ROW PER LINE -- fetchval would give only the root.
    q = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {g.sql}"
    await conn.fetch(q)  # warm
    plan = "\n".join(r[0] for r in await conn.fetch(q))
    lines = plan.split("\n")
    root = lines[0]
    ms = re.search(r"actual time=[\d.]+\.\.([\d.]+)", root)
    # FIRST Buffers line after the root is the root's own accumulated total.
    buffers = -1
    for ln in lines[1:]:
        b = re.search(r"Buffers: shared hit=(\d+)(?: read=(\d+))?", ln)
        if b:
            buffers = int(b.group(1)) + int(b.group(2) or 0)
            break
    rows = re.search(r"rows=(\d+) loops", root) or re.search(r"rows=(\d+)", root)
    print(f"  {label:34s} {'TABLE' if served else 'pipe ':5s} "
          f"{buffers:>10,} buf  {float(ms.group(1)) if ms else -1:8.1f} ms  "
          f"rows={rows.group(1) if rows else '?'}")
    return fired


def _fired(pd):
    out = []
    for k, v in (pd.items() if isinstance(pd, dict) else []):
        if k in ("rewrites", "fired", "decisions") and isinstance(v, (list, dict)):
            out += list(v)
        elif isinstance(v, dict) and v.get("fired"):
            out.append(k)
    return [str(x) for x in out]


async def main():
    conn = await asyncpg.connect(host="localhost", port=5432,
                                 database="sparql_sql_graph", user="hadfield")
    try:
        uri = await conn.fetchval(
            "select t.term_text from cardiff_kg_entity_slot_sort s "
            "join cardiff_kg_term t on t.term_uuid=s.entity_uuid "
            "where s.slot_type_uuid='125ec323-2dff-58ed-afbf-b1e4490e8cef' limit 1")
        print(f"\n  fixture: {SPACE}  2,863 KGLead  CompanyName  page {PAGE}")
        print(f"  096 recorded: list 507,492 buf / 360 ms   pinned 222 buf / 0.7 ms\n")
        f1 = await run(conn, "list (entity end open)", None)
        f2 = await run(conn, "pinned to ONE entity", [uri])
        f3 = await run(conn, "list, TWO sort keys", None, second_key=True)
        print(f"\n  rewrites fired, list shape: {sorted(set(f1 or []))[:12]}")
        if os.environ.get("DUMP"):
            sparql = KGQueryCriteriaBuilder().build_entity_query_sparql(
                crit(None), GRAPH, PAGE, 0)
            cr = await compile_sparql(sparql)
            g = await generate_sql(cr, SPACE, conn=conn)
            import json
            print(json.dumps(g.plan_decisions, indent=1, default=str)[:3000])
    finally:
        await conn.close()

asyncio.run(main())
