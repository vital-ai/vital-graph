"""If an inline criterion were measured, would the query get faster? (issues/101 #2)

`?f hasCategory "theta"` is 193 of 20,423 — 0.9%, the most selective thing in the
query — and the gate never sees it, so the walk declines to the flat plan.

Wiring it up is a day's care (the structural leaves have to be excluded or every
unfiltered walk gets a bogus 50% criterion). This asks the question that decides
whether to spend it: force the criterion in, and measure what comes out.

Three arms, same query, same answers:

    flat          what ships today for an inline criterion
    pinned        criterion forced, head PINNED — the shape hop-wise was built
                  for, so the upper bound on what wiring this can win
    constrained   criterion forced, head kind-constrained — needs the hoist too
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
from vitalgraph.db.sparql_sql import traversal_decision as td

HALEY = "http://vital.ai/ontology/haley-ai-kg#"
VITAL = "http://vital.ai/ontology/vital-core#"
SPACE = os.environ.get("SPACE", "sp_graph_skew_2k")

# What the gate WOULD have been told, from rdf_stats + rdf_pred_stats.
#
# `theta` (193 of 20,423, 0.9%) is the most selective category and returns ZERO
# rows through two hops, so measuring it compares two ways of finding nothing.
# `delta` still returns rows at depth 2 and is the most selective that does —
# the criterion has to bite AND the answer has to be non-empty, or the number
# means nothing.
CATEGORY = os.environ.get("CATEGORY", "delta")
# Read from rdf_stats, not estimated: an invented denominator would make the
# whole measurement a comparison against a number nobody has.
CRIT_ROWS = {"alpha": 6559, "beta": 4844, "gamma": 3305, "delta": 2450,
             "epsilon": 1626, "zeta": 845, "eta": 601, "theta": 193}[CATEGORY]
PRED_ROWS = 20423


def hop(n, frm, to, criterion):
    return f"""
        ?f{n} a <{HALEY}KGFrame> .
        ?se{n} <{VITAL}hasEdgeSource> ?f{n} .
        ?se{n} <{VITAL}hasEdgeDestination> ?ss{n} .
        ?ss{n} <{HALEY}hasKGSlotType> <urn:hasSourceEntity> .
        ?ss{n} <{HALEY}hasEntitySlotValue> {frm} .
        ?de{n} <{VITAL}hasEdgeSource> ?f{n} .
        ?de{n} <{VITAL}hasEdgeDestination> ?ds{n} .
        ?ds{n} <{HALEY}hasKGSlotType> <urn:hasDestinationEntity> .
        ?ds{n} <{HALEY}hasEntitySlotValue> {to} .{criterion.format(n=n)}"""


INLINE = f'\n        ?f{{n}} <{HALEY}hasCategory> "{CATEGORY}" .'


def query(end, depth=2):
    body = "".join(hop(i, f"?e{i}", f"?e{i+1}", INLINE) for i in range(depth))
    if end == "pinned":
        body += '\n        FILTER(?e0 = <urn:graphsyn:entity:1992>)'
    else:
        body += (f'\n        ?e0 <{HALEY}hasKGEntityType> '
                 f'<urn:graphsyn:kind:Rare> .')
    return f"SELECT ?e0 ?e{depth} WHERE {{ GRAPH <urn:{SPACE}> {{{body}\n    }} }}"


async def build(conn, client, sparql, *, force_criterion):
    real = td.decide_for_plan
    if force_criterion:
        def spy(chains, criterion_rows, predicate_rows, pair_rows=None):
            # Exactly what wiring defect 2 would supply, and nothing else.
            return real(chains, CRIT_ROWS, PRED_ROWS, pair_rows=pair_rows)
        td.decide_for_plan = spy
    try:
        cr = map_compile_response(await client.compile(sparql))
        assert cr.ok, cr.error
        gen = await generate_sql(cr, SPACE, conn=conn)
        assert gen.ok, gen.error
        return gen
    finally:
        td.decide_for_plan = real


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
    client = AsyncSidecarClient(sidecar_url())
    try:
        for end in ("pinned", "constrained"):
            sparql = query(end)
            print(f"\n  === driving end: {end}")
            answers = {}
            for label, force in (("flat (today)", False), ("criterion wired", True)):
                gen = await build(conn, client, sparql, force_criterion=force)
                fenced = "OFFSET 0\n)" in gen.sql
                rows = await conn.fetch(gen.sql)
                cols = [k for k in (rows[0].keys() if rows else [])
                        if "__" not in k]
                answers[label] = sorted(tuple(r[c] for c in cols) for r in rows)
                buf, ms = await price(conn, gen.sql)
                d = getattr(gen, "traversal_decision", None)
                print(f"      {label:16} hop-wise={str(fenced):5} "
                      f"buffers={buf:>9,} {ms:8.1f} ms  rows={len(rows)}")
                print(f"          {d.reason if d else 'no chain'}")
            a, b = answers.values()
            print(f"      answers identical: {a == b}"
                  + ("" if a else "   (EMPTY — proves nothing)"))
    finally:
        await conn.close()
        await client.close()


asyncio.run(main())
