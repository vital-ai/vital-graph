"""Re-measure issues/048's Problems 1 and 2 on current code.

Both prices were taken on 2026-08-08. Since then the criterion gate, the
direction choice and the hoist all landed, and Problem 2 is explicitly the thing
issues/090 was about — so its number is the one most likely to have moved.
Reading an issue's headline as current is how stale work gets picked up.

    Problem 1  adding `?slot a KGEntitySlot` disabled the collapse: 28,000x
    Problem 2  adding a per-hop criterion cost 150x - 5,700x
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

import asyncpg
from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
from vitalgraph.db.sparql_sql.generator import generate_sql

HALEY = "http://vital.ai/ontology/haley-ai-kg#"
VITAL = "http://vital.ai/ontology/vital-core#"
SPACE = os.environ.get("SPACE", "sp_graph_synth_10k")
GRAPH = f"urn:{SPACE}"
START = int(os.environ.get("START", "1992"))

SCORE = f'\n        ?f{{n}} <{HALEY}hasScore> ?sc{{n}} . FILTER(?sc{{n}} >= 50)'
SLOT_TYPE = (f'\n        ?ss{{n}} a <{HALEY}KGEntitySlot> .'
             f'\n        ?ds{{n}} a <{HALEY}KGEntitySlot> .')


def hop(n, frm, to, extra=""):
    return f"""
        ?f{n} a <{HALEY}KGFrame> .
        ?se{n} <{VITAL}hasEdgeSource> ?f{n} .
        ?se{n} <{VITAL}hasEdgeDestination> ?ss{n} .
        ?ss{n} <{HALEY}hasKGSlotType> <urn:hasSourceEntity> .
        ?ss{n} <{HALEY}hasEntitySlotValue> {frm} .
        ?de{n} <{VITAL}hasEdgeSource> ?f{n} .
        ?de{n} <{VITAL}hasEdgeDestination> ?ds{n} .
        ?ds{n} <{HALEY}hasKGSlotType> <urn:hasDestinationEntity> .
        ?ds{n} <{HALEY}hasEntitySlotValue> {to} .{extra.format(n=n)}"""


def query(depth, extra=""):
    body = "".join(hop(i, f"?e{i}", f"?e{i+1}", extra) for i in range(depth))
    body += f'\n        FILTER(?e0 = <urn:graphsyn:entity:{START}>)'
    return f"SELECT ?e0 ?e{depth} WHERE {{ GRAPH <{GRAPH}> {{{body}\n    }} }}"


CASES = [
    ("open walk           ", ""),
    ("+ criterion  (P2)   ", SCORE),
    ("+ slot type  (P1)   ", SLOT_TYPE),
    ("+ both              ", SCORE + SLOT_TYPE),
]


# A cap, because Problem 1 is not a slow query — it is an unbounded one. The
# first run of this probe sat on a single depth-2 statement for 613 seconds
# before it was cancelled, which tells you the shape but wastes the run.
TIMEOUT_MS = int(os.environ.get("TIMEOUT_MS", "30000"))


async def price(conn, sql):
    for _ in range(2):
        await conn.fetch("EXPLAIN (ANALYZE, BUFFERS) " + sql)
    rows = await conn.fetch("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql)
    doc = rows[0][0]
    doc = json.loads(doc) if isinstance(doc, str) else doc
    p = doc[0]["Plan"]
    return (p.get("Shared Hit Blocks", 0) + p.get("Shared Read Blocks", 0),
            doc[0]["Execution Time"])


async def main():
    conn = await asyncpg.connect(host="localhost", port=5433, user="postgres",
                                 password="testpass", database="sparql_sql_graph")
    client = AsyncSidecarClient("http://localhost:7071")
    try:
        for depth in (2, 3):
            print(f"\n  === {SPACE}, depth {depth}, start {START}")
            base = None
            for label, extra in CASES:
                cr = map_compile_response(await client.compile(query(depth, extra)))
                if not cr.ok:
                    print(f"      {label} did not compile: {cr.error}")
                    continue
                gen = await generate_sql(cr, SPACE, conn=conn)
                if not gen.ok:
                    print(f"      {label} SQL failed: {gen.error}")
                    continue
                try:
                    await conn.execute(f"SET statement_timeout = {TIMEOUT_MS}")
                    n = len(await conn.fetch(gen.sql))
                    buf, ms = await price(conn, gen.sql)
                except asyncpg.exceptions.QueryCanceledError:
                    joins = gen.sql.count(f"{SPACE}_frame_entity")
                    print(f"      {label} {'>' + str(TIMEOUT_MS // 1000) + ' s':>9}"
                          f"      TIMED OUT           "
                          f"        frame_entity joins={joins}")
                    continue
                finally:
                    await conn.execute("SET statement_timeout = 0")
                # Does the collapse still happen? The whole of Problem 1 is that
                # it stops.
                joins = gen.sql.count(f"{SPACE}_frame_entity")
                if base is None:
                    base = ms
                ratio = f"{ms / base:>8.1f}x" if base else "        -"
                print(f"      {label} {buf:>9,} buf {ms:>9.1f} ms {ratio} "
                      f"rows={n:<5} frame_entity joins={joins}")
    finally:
        await conn.close()
        await client.close()


asyncio.run(main())
