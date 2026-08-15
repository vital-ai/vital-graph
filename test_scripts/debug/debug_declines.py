"""Print the decline log for a few real traversal queries.

Scratch check that `declines.py` populates end to end, not just in unit tests.
Run against the vg-test stack:

    VG_TEST_PG_PORT=5433 python test_scripts/debug/debug_declines.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

import asyncpg  # noqa: E402

from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response  # noqa: E402
from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient  # noqa: E402
from vitalgraph.db.sparql_sql.generator import generate_sql  # noqa: E402

SIDECAR = os.environ.get("VG_TEST_SIDECAR_URL", "http://localhost:7071")
SPACE = os.environ.get("VG_SPACE", "sp_graph_synth_10k")


async def gen(conn, sparql):
    client = AsyncSidecarClient(SIDECAR)
    try:
        raw = await client.compile(sparql)
    finally:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close:
            r = close()
            if hasattr(r, "__await__"):
                await r
    cr = map_compile_response(raw)
    assert cr.ok, cr.error
    return await generate_sql(cr, SPACE, conn=conn)


QUERIES = {
    # No traversal at all — the shape rule should say so plainly.
    "no chain": """
        SELECT ?s WHERE { ?s <http://vital.ai/ontology/vital-core#vitaltype>
                             <http://vital.ai/ontology/haley-ai-kg#KGFrame> }
        LIMIT 10
    """,
    # A walk with no DISTINCT — dedup must decline on multiplicity, and say so.
    "walk, no DISTINCT": """
        PREFIX v: <http://vital.ai/ontology/vital-core#>
        PREFIX k: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT ?e2 WHERE {
          ?f1 v:vitaltype k:KGFrame .
          ?s1 k:hasKGSlotType <urn:hasSourceEntity> ; k:hasEntitySlotValue ?e1 .
          ?s2 k:hasKGSlotType <urn:hasDestinationEntity> ; k:hasEntitySlotValue ?e2 .
          ?ed1 v:hasEdgeSource ?f1 ; v:hasEdgeDestination ?s1 .
          ?ed2 v:hasEdgeSource ?f1 ; v:hasEdgeDestination ?s2 .
        } LIMIT 10
    """,
}


async def main():
    conn = await asyncpg.connect(
        host=os.environ.get("VG_TEST_PG_HOST", "localhost"),
        port=int(os.environ.get("VG_TEST_PG_PORT", "5433")),
        database=os.environ.get("VG_TEST_PG_DATABASE", "vitalgraphdb"),
        user=os.environ.get("VG_TEST_PG_USER", "postgres"),
        password=os.environ.get("VG_TEST_PG_PASSWORD", "testpass"))
    try:
        for label, q in QUERIES.items():
            g = await gen(conn, q)
            print(f"\n=== {label} — ok={g.ok}")
            if g.declines is None:
                print("  declines is None (NOT WIRED)")
            else:
                print(g.declines.summary())
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
