"""Is the hoist worth building? (issues/090)

`emit_hop_wise` declines a constrained driving end because the constraint lands
inside the criteria fence and the outer relation stays the whole link table.
The proposed fix moves that one table up beside the link.

Rather than argue about whether that would pay, this builds it by hand and
measures it. Three arms, same query, same answers:

    flat            what ships today for this shape
    hop-wise        what the emitter would produce if the guard were removed
    hop-wise-hoist  the same SQL with the driving constraint moved into the
                    outer FROM — the shape the fix would emit

If the hoisted arm does not beat flat, the hoist is not worth building and the
decline is the whole answer.
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
from devtools.target import sidecar_url  # noqa: E402

import asyncpg
from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
from vitalgraph.db.sparql_sql.generator import generate_sql
from vitalgraph.db.sparql_sql import emit_traversal as et
from vitalgraph.db.sparql_sql import traversal_decision as td

HALEY = "http://vital.ai/ontology/haley-ai-kg#"
VITAL = "http://vital.ai/ontology/vital-core#"
SPACE = os.environ.get("SPACE", "sp_graph_skew_2k")
KIND = os.environ.get("KIND", "urn:graphsyn:kind:Rare")
DEPTH = int(os.environ.get("DEPTH", "2"))


def hop(n, frm, to):
    return f"""
        ?f{n} a <{HALEY}KGFrame> .
        ?se{n} <{VITAL}hasEdgeSource> ?f{n} .
        ?se{n} <{VITAL}hasEdgeDestination> ?ss{n} .
        ?ss{n} <{HALEY}hasKGSlotType> <urn:hasSourceEntity> .
        ?ss{n} <{HALEY}hasEntitySlotValue> {frm} .
        ?de{n} <{VITAL}hasEdgeSource> ?f{n} .
        ?de{n} <{VITAL}hasEdgeDestination> ?ds{n} .
        ?ds{n} <{HALEY}hasKGSlotType> <urn:hasDestinationEntity> .
        ?ds{n} <{HALEY}hasEntitySlotValue> {to} .
        ?f{n} <{HALEY}hasScore> ?sc{n} . FILTER(?sc{n} >= 50)"""


BODY = "".join(hop(i, f"?e{i}", f"?e{i + 1}") for i in range(DEPTH))
BODY += f'\n        ?e0 <{HALEY}hasKGEntityType> <{KIND}> .'
SPARQL = (f"SELECT ?e0 ?e{DEPTH} WHERE {{ GRAPH <urn:{SPACE}> {{{BODY}\n"
          f"    }} }} ORDER BY ?e0 ?e{DEPTH}")


def hoist(sql: str):
    """Move the driving-end constraint out of the fence and beside the link.

    The driving constraint is the quad table joined to the OUTER link's driving
    column — `femvN.source_entity_uuid` — from inside the first lateral. The
    criteria lateral nests inside the body, so everything below keeps it in
    lexical scope and only the JOIN moves.
    """
    lines = sql.splitlines()
    link = next((i for i, l in enumerate(lines)
                 if l.startswith("FROM ") and "_frame_entity AS femv" in l), None)
    if link is None:
        return None, "no frame_entity link in the outer FROM"
    alias = lines[link].split("AS ")[-1].strip()
    driving = f"{alias}.source_entity_uuid"
    cand = [i for i, l in enumerate(lines)
            if l.startswith("JOIN ") and driving in l and i > link]
    if len(cand) != 1:
        return None, f"expected one join to {driving}, found {len(cand)}"
    moved = lines.pop(cand[0])
    lines.insert(link + 1, moved)
    return "\n".join(lines), moved.split(" ON ")[0]


async def build(conn, client, mode):
    orig_decide, orig_emit = td.decide, et.emit_hop_wise
    try:
        if mode == "flat":
            td.decide = lambda *a, **k: td.Decision(hop_wise=False, reason="off")
        else:
            # Bypass ONLY the pin guard, keeping every other decline intact.
            def _no_guard(plan, chain, quad_tables, sql_names, direction=None):
                object.__setattr__(chain, "pinned_head", True) \
                    if not chain.pinned_head else None
                return orig_emit(plan, chain, quad_tables, sql_names, direction)
            et.emit_hop_wise = _no_guard
        cr = map_compile_response(await client.compile(SPARQL))
        assert cr.ok, cr.error
        gen = await generate_sql(cr, SPACE, conn=conn)
        assert gen.ok, gen.error
        return gen.sql
    finally:
        td.decide, et.emit_hop_wise = orig_decide, orig_emit


async def price(conn, sql):
    for _ in range(2):
        await conn.fetch("EXPLAIN (ANALYZE, BUFFERS) " + sql)
    plan = await conn.fetch("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql)
    p = plan[0][0]
    d = json.loads(p) if isinstance(p, str) else p
    root = d[0]["Plan"]
    return (root.get("Shared Hit Blocks", 0) + root.get("Shared Read Blocks", 0),
            d[0]["Execution Time"])


async def main():
    conn = await asyncpg.connect(host="localhost", port=5433, user="postgres",
                                 password="testpass", database="sparql_sql_graph")
    client = AsyncSidecarClient(sidecar_url())
    try:
        flat = await build(conn, client, "flat")
        hw = await build(conn, client, "hopwise")
        if "OFFSET 0" not in hw:
            print("  hop-wise did not emit; nothing to hoist"); return
        hoisted, note = hoist(hw)
        if hoisted is None:
            print(f"  could not hoist: {note}"); return
        print(f"  hoisted: {note}\n")

        answers = {}
        for label, sql in (("flat", flat), ("hop-wise", hw),
                           ("hop-wise+hoist", hoisted)):
            rows = await conn.fetch(sql)
            cols = [k for k in (rows[0].keys() if rows else [])
                    if "__" not in k and not k.startswith("_")]
            answers[label] = sorted(tuple(r[c] for c in cols) for r in rows)
            buf, ms = await price(conn, sql)
            print(f"  {label:16} rows={len(rows):4} buffers={buf:9,} {ms:8.1f} ms")
        base = answers["flat"]
        for k, v in answers.items():
            if v != base:
                print(f"  !! {k} DISAGREES with flat")
        print(f"\n  all arms agree: {all(v == base for v in answers.values())}, "
              f"{len(base)} rows")
    finally:
        await conn.close()
        await client.close()


asyncio.run(main())
