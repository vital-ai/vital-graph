"""What would a constant-object triple contribute as a criterion? (issues/101 #2)

`?f hasCategory "theta"` measures nothing today: the criterion gate reads
range/text/in stats only, so the query reports "no measured criterion" and
declines hop-wise entirely — even though `rdf_stats` already holds the count.

The blocker is not the plumbing. The pair stats ALSO hold the chain's structural
leaves (`hasKGSlotType = hasSourceEntity`, the frame type check), and feeding
those in unfiltered hands every UNFILTERED walk a criterion, which re-enables the
shape the requirement exists to refuse.

So this prints, for one query of each kind, every pair the gate would see, its
selectivity against its predicate total, and whether it is structural — so the
exclusion rule can be designed against what is actually there rather than
against what it is assumed to be.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

import asyncpg
from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
from vitalgraph.db.sparql_sql import generator as gen_mod
from vitalgraph.db.sparql_sql.generator import generate_sql

HALEY = "http://vital.ai/ontology/haley-ai-kg#"
VITAL = "http://vital.ai/ontology/vital-core#"
SPACE = os.environ.get("SPACE", "sp_graph_skew_2k")


def hop(n, frm, to, criterion=""):
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


def query(criterion, depth=2):
    body = "".join(hop(i, f"?e{i}", f"?e{i+1}", criterion) for i in range(depth))
    body += '\n        FILTER(?e0 = <urn:graphsyn:entity:1992>)'
    return f"SELECT ?e0 ?e{depth} WHERE {{ GRAPH <urn:{SPACE}> {{{body}\n    }} }}"


CASES = [
    ("no criterion at all", ""),
    ("inline literal  hasCategory \"theta\"",
     f'\n        ?f{{n}} <{HALEY}hasCategory> "theta" .'),
    ("inline uri      hasTag <t3>",
     f'\n        ?f{{n}} <{HALEY}hasTag> <urn:graphsyn:tag:t3> .'),
    ("FILTER          score >= 50  (already measured)",
     f'\n        ?f{{n}} <{HALEY}hasScore> ?sc{{n}} . FILTER(?sc{{n}} >= 50)'),
]


async def main():
    conn = await asyncpg.connect(host="localhost", port=5433, user="postgres",
                                 password="testpass", database="sparql_sql_graph")
    client = AsyncSidecarClient("http://localhost:7071")

    # Term text for each uuid, so the pairs are readable rather than hex.
    names = {r["term_uuid"]: r["term_text"] for r in await conn.fetch(
        f"SELECT term_uuid, term_text FROM {SPACE}_term")}

    def short(u):
        t = names.get(u, str(u))
        return t.rsplit("#", 1)[-1].rsplit("/", 1)[-1] if "#" in t or "/" in t else t

    captured = {}
    orig = gen_mod.decide_for_plan if hasattr(gen_mod, "decide_for_plan") else None

    try:
        for label, crit in CASES:
            from vitalgraph.db.sparql_sql import traversal_decision as td
            real_decide = td.decide_for_plan

            def spy(chains, criterion_rows, predicate_rows, pair_rows=None,
                    _real=real_decide):
                # `pair_rows` is the whole preloaded quad_stats for the SPACE —
                # thousands of pairs this query never mentions. The candidate
                # set is the query's OWN constant leaves, which is what
                # `needed_pairs` computes.
                captured["pairs"] = dict(pair_rows or {})
                captured["chains"] = chains
                return _real(chains, criterion_rows, predicate_rows,
                             pair_rows=pair_rows)

            td.decide_for_plan = spy
            real_load = gen_mod._load_missing_pair_stats

            async def load_spy(plan, aliases, *a, **kw):
                captured["plan"], captured["aliases"] = plan, aliases
                return await real_load(plan, aliases, *a, **kw)

            gen_mod._load_missing_pair_stats = load_spy
            try:
                cr = map_compile_response(await client.compile(query(crit)))
                g = await generate_sql(cr, SPACE, conn=conn)
            finally:
                td.decide_for_plan = real_decide
                gen_mod._load_missing_pair_stats = real_load

            d = getattr(g, "traversal_decision", None)
            print(f"\n  === {label}")
            print(f"      decision: {d.reason if d else 'no chain'}")
            all_pairs = captured.get("pairs") or {}
            plan = captured.get("plan")
            from vitalgraph.db.sparql_sql.semijoin import needed_pairs
            leaf = needed_pairs(plan, captured["aliases"]) if plan is not None else set()
            pairs = {k: all_pairs.get(k) for k in leaf}
            chain = (captured.get("chains") or [None])[0]
            structural = set()
            if chain is not None:
                for attr in ("head_constraint", "tail_constraint"):
                    v = getattr(chain, attr, None)
                    if v:
                        structural.add(v)
            preds = {r["predicate_uuid"]: r["row_count"] for r in await conn.fetch(
                f"SELECT predicate_uuid, row_count FROM {SPACE}_rdf_pred_stats")}
            print(f"      {len(all_pairs)} pair(s) preloaded for the space; "
                  f"{len(pairs)} are THIS QUERY's leaves:")
            for (p, o), n in sorted(pairs.items(), key=lambda kv: -kv[1]):
                total = preds.get(p)
                n = n if n is not None else 0
                sel = f"{n/total:.0%}" if total and n else ("unpriced" if not n else "?")
                tag = " <- chain end constraint" if (p, o) in structural else ""
                print(f"        {short(p):22} = {short(o):24} {n:>7} of "
                      f"{total if total else '?':>7}  {sel:>5}{tag}")
    finally:
        await conn.close()
        await client.close()


asyncio.run(main())
