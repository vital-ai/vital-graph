"""Problem 4's two remaining options, priced by hand before either is built.

    baseline   what ships: a correlated EXISTS, probed per surviving row
    fenced     the same set built ONCE in a MATERIALIZED CTE and probed
    dropped    no check at all — the CEILING, and what the tautology proof buys

`dropped` is only a legitimate comparison where the constraint really is a
tautology, which is why this runs on sp_graph_synth_10k (every slot a
KGEntitySlot) and asserts the row counts match rather than assuming they do.
"""
import asyncio
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
from devtools.target import sidecar_url  # noqa: E402

import asyncpg
from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
from vitalgraph.db.sparql_sql.generator import generate_sql

H = "http://vital.ai/ontology/haley-ai-kg#"
V = "http://vital.ai/ontology/vital-core#"
S = os.environ.get("SPACE", "sp_graph_synth_10k")
START = os.environ.get("START", "1658")
DEPTH = int(os.environ.get("DEPTH", "3"))


def hop(n, frm, to):
    return f"""
        ?se{n} <{V}hasEdgeSource> ?f{n} . ?se{n} <{V}hasEdgeDestination> ?ss{n} .
        ?ss{n} <{H}hasKGSlotType> <urn:hasSourceEntity> .
        ?ss{n} <{H}hasEntitySlotValue> {frm} .
        ?de{n} <{V}hasEdgeSource> ?f{n} . ?de{n} <{V}hasEdgeDestination> ?ds{n} .
        ?ds{n} <{H}hasKGSlotType> <urn:hasDestinationEntity> .
        ?ds{n} <{H}hasEntitySlotValue> {to} .
        ?ss{n} a <{H}KGEntitySlot> ."""


SPARQL = (f"SELECT ?e0 ?e{DEPTH} WHERE {{ GRAPH <urn:{S}> {{"
          + "".join(hop(i, f"?e{i}", f"?e{i+1}") for i in range(DEPTH))
          + f"\n        FILTER(?e0 = <urn:graphsyn:entity:{START}>) }} }}")

def _absorbed_checks(sql):
    """Each `EXISTS (...)` the rewrite absorbed, by BALANCED parens.

    A regex was tried and silently matched nothing: the emitted check ends in one
    close paren and the pattern wanted two, so the script reported "no absorbed
    EXISTS" for SQL that plainly contained it.
    """
    out, i = [], 0
    while True:
        i = sql.find("EXISTS (SELECT 1 FROM", i)
        if i < 0:
            return out
        depth, j = 0, sql.index("(", i)
        while j < len(sql):
            if sql[j] == "(":
                depth += 1
            elif sql[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out.append(sql[i:j + 1])
        i = j + 1


def variants(sql):
    """(label, sql) for each option, built from the generated statement."""
    found = _absorbed_checks(sql)
    if not found:
        return None, "no absorbed EXISTS in the generated SQL"

    dropped = sql
    for f in found:
        dropped = dropped.replace(f"AND {f}", "").replace(f, "TRUE")

    # The fence: hoist each check's set into a MATERIALIZED CTE, then probe it.
    ctes, fenced = [], sql
    for i, f in enumerate(found):
        body = f[len("EXISTS (SELECT 1 "):-1]
        # `SELECT 1 FROM ... WHERE e.source = femv.frame AND e.ctx = femv.ctx`
        # becomes an uncorrelated set of (frame, ctx) pairs.
        # Strip the WHOLE correlated WHERE clause. Stripping only the `AND ...`
        # conjuncts left the first one — it is introduced by WHERE, not AND — so
        # the CTE still referenced femv1 and PostgreSQL rejected it with
        # "missing FROM-clause entry".
        body = re.sub(
            r"\s*WHERE e_slotchk\d+\.source_node_uuid = \S+\.frame_uuid"
            r"\s*AND e_slotchk\d+\.context_uuid = \S+\.context_uuid", "", body)
        alias = re.search(r"AS (e_slotchk\d+)", f).group(1)
        ctes.append(f"p4_{i} AS MATERIALIZED (SELECT DISTINCT "
                    f"{alias}.source_node_uuid AS fr, {alias}.context_uuid AS cx "
                    f"{body})")
        fe = re.search(r"(\w+)\.frame_uuid", f).group(1)
        fenced = fenced.replace(
            f, f"({fe}.frame_uuid, {fe}.context_uuid) IN (SELECT fr, cx FROM p4_{i})")
    fenced = "WITH " + ",\n".join(ctes) + "\n" + fenced
    return [("baseline (ships)", sql), ("fenced (MATERIALIZED)", fenced),
            ("dropped (ceiling)", dropped)], None


async def price(conn, sql):
    for _ in range(2):
        await conn.fetch("EXPLAIN (ANALYZE, BUFFERS) " + sql)
    r = await conn.fetch("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql)
    d = r[0][0]
    d = json.loads(d) if isinstance(d, str) else d
    p = d[0]["Plan"]
    return (p.get("Shared Hit Blocks", 0) + p.get("Shared Read Blocks", 0),
            d[0]["Execution Time"])


async def main():
    conn = await asyncpg.connect(host="localhost", port=5433, user="postgres",
                                 password="testpass", database="sparql_sql_graph")
    c = AsyncSidecarClient(sidecar_url())
    try:
        await conn.execute("SET statement_timeout = 120000")
        gen = await generate_sql(map_compile_response(await c.compile(SPARQL)),
                                 S, conn=conn)
        assert gen.ok, gen.error
        vs, err = variants(gen.sql)
        if err:
            print(f"  {err}")
            return
        base_rows = None
        print(f"  {S}, depth {DEPTH}, start {START}")
        for label, sql in vs:
            try:
                rows = len(await conn.fetch(sql))
            except Exception as exc:
                print(f"  {label:24} FAILED: {str(exc)[:80]}")
                continue
            buf, ms = await price(conn, sql)
            if base_rows is None:
                base_rows = rows
            flag = "" if rows == base_rows else "   !! ROWS DIFFER"
            print(f"  {label:24} {buf:>9,} buf {ms:>8.1f} ms  rows={rows}{flag}")
    finally:
        await conn.close()
        await c.close()


if __name__ == "__main__":
    asyncio.run(main())
