"""Answers still match the manifest, and every decline is legible.

The negative-space check for `declines.py`: replacing ~30 `logger.debug` calls
with `Rule.decline(...)` must change no SQL and no answer. A typo in a fact
keyword raises NameError at exactly the sites the fast paths run through, so
this walks the fixture and compares against ground truth rather than trusting
that the unit tests reach them.

    VG_TEST_PG_PORT=5433 VG_TEST_PG_DATABASE=sparql_sql_graph \
        python test_scripts/debug/debug_declines_differential.py
"""

import asyncio
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from devtools.target import sidecar_url  # noqa: E402

import asyncpg  # noqa: E402

from tests.performance.graph_fixtures import (  # noqa: E402
    CRITERIA, LARGE, chain_query, entity_indexes)
from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response  # noqa: E402
from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient  # noqa: E402
from vitalgraph.db.sparql_sql.generator import generate_sql  # noqa: E402

SIDECAR = sidecar_url()


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
    return await generate_sql(cr, LARGE.space, conn=conn)


async def main():
    conn = await asyncpg.connect(
        host=os.environ.get("VG_TEST_PG_HOST", "localhost"),
        port=int(os.environ.get("VG_TEST_PG_PORT", "5433")),
        database=os.environ.get("VG_TEST_PG_DATABASE", "sparql_sql_graph"),
        user=os.environ.get("VG_TEST_PG_USER", "postgres"),
        password=os.environ.get("VG_TEST_PG_PASSWORD", "testpass"))
    await conn.execute("SET statement_timeout = '120s'")
    cases = [("", "frame_traversal")] + [
        (tpl, key) for tpl, key in CRITERIA.values()]
    starts = LARGE.sample_starts()[:3]
    seen, checked, failed = Counter(), 0, 0
    try:
        for tpl, key in cases:
            for start in starts:
                for depth in (1, 2, 3):
                    q = chain_query(LARGE, start, depth, criterion=tpl)
                    g = await gen(conn, q)
                    assert g.ok, g.error
                    got = entity_indexes(await conn.fetch(g.sql))
                    want = LARGE.expected(key, start, depth)
                    checked += 1
                    if got != want:
                        failed += 1
                        print(f"MISMATCH {key} start={start} d={depth}: "
                              f"+{sorted(got - want)[:5]} "
                              f"-{sorted(want - got)[:5]}")
                    for d in (g.declines or []):
                        seen[(d.rule, d.detail)] += 1
    finally:
        await conn.close()

    print(f"\n{checked} cases checked, {failed} mismatched")
    print("\ndeclines seen:")
    for (rule, detail), n in seen.most_common():
        print(f"  {n:4d}x  {rule}: {detail}")


if __name__ == "__main__":
    asyncio.run(main())
