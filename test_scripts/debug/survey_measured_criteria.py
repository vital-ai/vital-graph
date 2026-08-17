"""Which criterion forms does the traversal gate actually measure?

`decide` requires a MEASURED criterion, and three stat families feed it:
range_stats (numeric/dateTime comparisons), in_stats (IN and equality over
terms) and text_stats (the LIKE family). Everything else reaches the gate as
"no measured criterion" and declines.

This puts one representative of every criterion form a query can plausibly carry
through the real generator against a loaded space, and reports what the gate saw.
Reading the code answers which forms are HANDLED; this answers which are
MEASURED, which is a different question wherever a handler exists but the
plumbing does not reach it.
"""
import asyncio
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
XSD = "http://www.w3.org/2001/XMLSchema#"
SPACE = os.environ.get("SPACE", "sp_graph_skew_2k")
GRAPH = f"urn:{SPACE}"

# (label, extra triples/filters bound to ?f{n}) — {n} is the hop number.
FORMS = [
    ("numeric >=          FILTER", f'?f{{n}} <{HALEY}hasScore> ?sc{{n}} . FILTER(?sc{{n}} >= 50)'),
    ("numeric <           FILTER", f'?f{{n}} <{HALEY}hasScore> ?sc{{n}} . FILTER(?sc{{n}} < 10)'),
    ("numeric =           FILTER", f'?f{{n}} <{HALEY}hasScore> ?sc{{n}} . FILTER(?sc{{n}} = 50)'),
    ("numeric !=          FILTER", f'?f{{n}} <{HALEY}hasScore> ?sc{{n}} . FILTER(?sc{{n}} != 50)'),
    ("double >=           FILTER", f'?f{{n}} <{HALEY}hasWeight> ?w{{n}} . FILTER(?w{{n}} >= 0.9)'),
    ("dateTime >=         FILTER", f'?f{{n}} <{HALEY}hasOccurredAt> ?oc{{n}} . '
                                   f'FILTER(?oc{{n}} >= "2024-01-01T00:00:00Z"^^<{XSD}dateTime>)'),
    ("string =            FILTER", f'?f{{n}} <{HALEY}hasCategory> ?ct{{n}} . FILTER(?ct{{n}} = "theta")'),
    ("string IN           FILTER", f'?f{{n}} <{HALEY}hasCategory> ?ct{{n}} . '
                                   f'FILTER(?ct{{n}} IN ("theta", "eta"))'),
    ("string NOT IN       FILTER", f'?f{{n}} <{HALEY}hasCategory> ?ct{{n}} . '
                                   f'FILTER(?ct{{n}} NOT IN ("alpha", "beta"))'),
    ("CONTAINS            FILTER", f'?f{{n}} <{HALEY}hasLabel> ?lb{{n}} . '
                                   f'FILTER(CONTAINS(?lb{{n}}, "label-7"))'),
    ("STRSTARTS           FILTER", f'?f{{n}} <{HALEY}hasLabel> ?lb{{n}} . '
                                   f'FILTER(STRSTARTS(?lb{{n}}, "label-7"))'),
    ("regex               FILTER", f'?f{{n}} <{HALEY}hasLabel> ?lb{{n}} . '
                                   f'FILTER(regex(?lb{{n}}, "^label-7"))'),
    ("boolean =           FILTER", f'?f{{n}} <{HALEY}hasActive> ?ac{{n}} . FILTER(?ac{{n}} = true)'),
    ("negated range       FILTER", f'?f{{n}} <{HALEY}hasScore> ?sc{{n}} . FILTER(!(?sc{{n}} < 50))'),
    # No FILTER at all — the constant sits in the triple pattern, which is how
    # anyone would naturally write a selective criterion.
    ("literal object      TRIPLE", f'?f{{n}} <{HALEY}hasCategory> "theta" .'),
    ("uri object          TRIPLE", f'?f{{n}} <{HALEY}hasTag> <urn:graphsyn:tag:t3> .'),
    ("frame type          TRIPLE", f'?f{{n}} <{VITAL}vitaltype> <{HALEY}KGFrame> .'),
]


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
        ?ds{n} <{HALEY}hasEntitySlotValue> {to} .
        {criterion.format(n=n)}"""


def query(criterion, depth=2):
    body = "".join(hop(i, f"?e{i}", f"?e{i + 1}", criterion) for i in range(depth))
    # A PINNED head, so the only thing that can vary between rows of the survey
    # is whether the criterion was measured.
    body += f'\n        FILTER(?e0 = <urn:graphsyn:entity:42>)'
    return f"SELECT ?e0 ?e{depth} WHERE {{ GRAPH <{GRAPH}> {{{body}\n    }} }}"


async def main():
    conn = await asyncpg.connect(host="localhost", port=5433, user="postgres",
                                 password="testpass", database="sparql_sql_graph")
    client = AsyncSidecarClient("http://localhost:7071")
    try:
        print(f"  {'criterion form':28} {'measured':9} decision")
        for label, criterion in FORMS:
            sparql = query(criterion)
            cr = map_compile_response(await client.compile(sparql))
            if not cr.ok:
                print(f"  {label:28} {'-':9} SPARQL did not compile: {cr.error}")
                continue
            gen = await generate_sql(cr, SPACE, conn=conn)
            if not gen.ok:
                print(f"  {label:28} {'-':9} SQL failed: {gen.error}")
                continue
            d = gen.traversal_decision
            if d is None:
                print(f"  {label:28} {'NO CHAIN':9} -")
                continue
            measured = "no" if "no measured criterion" in d.reason else "yes"
            print(f"  {label:28} {measured:9} {d.reason}")
    finally:
        await conn.close()
        await client.close()


asyncio.run(main())
