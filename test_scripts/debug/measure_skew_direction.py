"""Hop-wise vs as-is on the skewed fixture, same query, same answers.

Three arms: as-is (gate off), hop-wise driving from the end the gate chose, and
hop-wise forced the WRONG way. The third is the one that matters — if the two
hop-wise arms cost the same, the direction was decided but not expressed.
"""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pathlib
import asyncpg
from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
from vitalgraph.db.sparql_sql.generator import generate_sql
from vitalgraph.db.sparql_sql import traversal_decision as td
from vitalgraph.db.sparql_sql import emit_traversal as et

HALEY = "http://vital.ai/ontology/haley-ai-kg#"
VITAL = "http://vital.ai/ontology/vital-core#"
SPACE = os.environ.get("SPACE", "sp_graph_skew_2k")

def hop(n, frm, to, src_role, crit=True):
    c = (f'\n        ?f{n} <{HALEY}hasScore> ?sc{n} . FILTER(?sc{n} >= 50)'
         if crit else "")
    return f"""
        ?f{n} a <{HALEY}KGFrame> .
        ?se{n} <{VITAL}hasEdgeSource> ?f{n} .
        ?se{n} <{VITAL}hasEdgeDestination> ?ss{n} .
        ?ss{n} <{HALEY}hasKGSlotType> <{src_role}> .
        ?ss{n} <{HALEY}hasEntitySlotValue> {frm} .
        ?de{n} <{VITAL}hasEdgeSource> ?f{n} .
        ?de{n} <{VITAL}hasEdgeDestination> ?ds{n} .
        ?ds{n} <{HALEY}hasKGSlotType> <urn:hasDestinationEntity> .
        ?ds{n} <{HALEY}hasEntitySlotValue> {to} .{c}"""


DEPTH = int(os.environ.get("DEPTH", "2"))
# Hop 0 enters through the RARE slot type (186 frames); every later hop uses the
# common one (9,266). So the chain has a small end and a large one, and which
# end it is driven from is a question with an answer.
_body = "".join(hop(_i, f"?e{_i}", f"?e{_i+1}", "urn:hasSourceEntity")
                for _i in range(DEPTH))
# Constrain ONE end by entity kind, leaving the other open. That is the shape
# the gate exists for: a priced end against an unpriced one.
END = os.environ.get("END", "head")
_end = "?e0" if END == "head" else f"?e{DEPTH}"
if os.environ.get("PIN"):
    # A PINNED end: one uri, expressed as a FILTER so the slot group is still
    # recognised (graph_fixtures.frame_hop says why a constant in the object
    # position is not).
    _body += f'\n        FILTER({_end} = <{os.environ["PIN"]}>)'
else:
    _body += (f'\n        {_end} <{HALEY}hasKGEntityType> '
              f'<{os.environ.get("KIND", "urn:graphsyn:kind:Person")}> .')
_last = f"?e{DEPTH}"
SPARQL = f"""SELECT ?e0 {_last} WHERE {{ GRAPH <urn:{SPACE}> {{{_body}
    }} }} ORDER BY ?e0 {_last}"""


async def build(conn, client, mode):
    orig_decide, orig_choose = td.decide, td.choose_direction
    try:
        if mode == "as-is":
            td.decide = lambda *a, **k: td.Decision(hop_wise=False, reason="forced off")
        elif mode in ("head", "tail"):
            td.choose_direction = lambda c, p: mode
        cr = map_compile_response(await client.compile(SPARQL))
        assert cr.ok, cr.error
        gen = await generate_sql(cr, SPACE, conn=conn)
        assert gen.ok, gen.error
        return gen.sql
    finally:
        td.decide, td.choose_direction = orig_decide, orig_choose


async def main():
    conn = await asyncpg.connect(host="localhost", port=5433, user="postgres",
                                 password="testpass", database="sparql_sql_graph")
    client = AsyncSidecarClient("http://localhost:7071")
    try:
        answers, sqls = {}, {}
        for mode in ("as-is", "tail", "head"):
            sql = await build(conn, client, mode)
            fenced = "OFFSET 0\n)" in sql
            rows = await conn.fetch(sql)
            cols = [k for k in (rows[0].keys() if rows else [])
                    if not k.startswith("_") and "__" not in k]
            answers[mode] = sorted(tuple(r[c] for c in cols) for r in rows)
            sqls[mode] = sql
            pathlib.Path(f"/tmp/skew_{mode}.sql").write_text(sql)
            for _ in range(2):
                await conn.fetch("EXPLAIN (ANALYZE, BUFFERS) " + sql)
            plan = await conn.fetch("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql)
            p = plan[0][0]
            import json
            d = json.loads(p) if isinstance(p, str) else p
            root = d[0]["Plan"]
            buffers = root.get("Shared Hit Blocks", 0) + root.get("Shared Read Blocks", 0)
            ms = d[0]["Execution Time"]
            print(f"  {mode:6} hop-wise={str(fenced):5} rows={len(rows):4} "
                  f"buffers={buffers:9,} {ms:8.1f} ms")
        print(f"  head/tail SQL identical: {sqls['head'] == sqls['tail']}")
        base = answers["as-is"]
        for m in ("tail", "head"):
            print(f"  answers {m} == as-is: {answers[m] == base}")
    finally:
        await conn.close()
        await client.close()

asyncio.run(main())
