"""Tail-pinned paths: same answers as the unseeded plan, and faster.

The seeded arm walks BACKWARD from the pin. That is a different recursion, not
a filtered one, so correctness cannot be assumed from the forward case — a
reversed walk that extends past the pin would be fast and wrong.

Ground truth is a hand-written anchored closure in SQL, independent of both.
"""
import asyncio, os, statistics, sys, time
sys.path.insert(0, "/Users/hadfield/Local/vital-git/vital-graph")
from devtools.target import sidecar_url  # noqa: E402
os.chdir("/Users/hadfield/Local/vital-git/vital-graph")
import asyncpg
from tests.performance.graph_fixtures import SMALL, EDGE_SOURCE, EDGE_DEST
from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
from vitalgraph.db.sparql_sql import emit_path
from vitalgraph.db.sparql_sql.generator import generate_sql

_real = emit_path._path_to_sql
def _noseed(*a, **kw):
    kw["seed_start_sql"] = None; kw["seed_end_sql"] = None
    return _real(*a, **kw)

async def gen(conn, q):
    c = AsyncSidecarClient(sidecar_url())
    raw = await c.compile(q)
    cl = getattr(c,"aclose",None) or getattr(c,"close",None)
    if cl:
        r=cl()
        if hasattr(r,"__await__"): await r
    cr = map_compile_response(raw); assert cr.ok, cr.error
    g = await generate_sql(cr, SMALL.space, conn=conn); assert g.ok, g.error
    return g

async def truth_ancestors(conn, uri):
    """Everything that reaches `uri` via one or more edges — hand-written."""
    return await conn.fetchval(f"""
    WITH RECURSIVE
     src AS (SELECT term_uuid FROM {SMALL.space}_term WHERE term_text=$1),
     dst AS (SELECT term_uuid FROM {SMALL.space}_term WHERE term_text=$2),
     tgt AS (SELECT term_uuid FROM {SMALL.space}_term WHERE term_text=$3),
     step AS (SELECT a.object_uuid AS frm, b.object_uuid AS too
              FROM {SMALL.space}_rdf_quad a
              JOIN {SMALL.space}_rdf_quad b ON b.subject_uuid=a.subject_uuid
              WHERE a.predicate_uuid=(SELECT * FROM src)
                AND b.predicate_uuid=(SELECT * FROM dst)),
     walk(n) AS (SELECT frm FROM step WHERE too=(SELECT * FROM tgt)
                 UNION SELECT s.frm FROM walk w JOIN step s ON s.too=w.n)
    SELECT count(*) FROM walk""", EDGE_SOURCE, EDGE_DEST, uri)

async def main():
    conn = await asyncpg.connect(host="localhost", port=5433,
        database="sparql_sql_graph", user="postgres", password="testpass")
    await conn.execute("SET statement_timeout='75s'")
    dr = SMALL.deep_roots()
    # A frame deep in a chain has real ancestors; its root has none.
    for root in sorted(dr, key=int)[:2]:
        tail_idx = dr[root][max(dr[root], key=int)][0]
        uri = SMALL.nested_frame_uri(tail_idx)
        truth = await truth_ancestors(conn, uri)
        step = f"^<{EDGE_SOURCE}>/<{EDGE_DEST}>"
        for label, path in (("+", f"({step})+"), ("*", f"({step})*")):
            q = (f"SELECT DISTINCT ?x WHERE {{ GRAPH <{SMALL.graph}> {{ "
                 f"?x {path} <{uri}> }} }}")
            emit_path._path_to_sql = _real
            gs = await gen(conn, q)
            emit_path._path_to_sql = _noseed
            gu = await gen(conn, q)
            emit_path._path_to_sql = _real
            t0 = time.perf_counter(); rs = await conn.fetch(gs.sql)
            ts = (time.perf_counter()-t0)*1000
            want = truth + (1 if label == "*" else 0)
            ok = "OK" if len(rs) == want else f"*** got {len(rs)} want {want} ***"
            try:
                t0 = time.perf_counter(); ru = await conn.fetch(gu.sql)
                tu = (time.perf_counter()-t0)*1000
                same = {tuple(x) for x in rs} == {tuple(x) for x in ru}
                print(f"  nframe {tail_idx} {label}: seeded {ts:8.1f} ms ({len(rs)} rows)  "
                      f"unseeded {tu:9.1f} ms  agree={same}  vs truth {want}: {ok}", flush=True)
            except Exception:
                print(f"  nframe {tail_idx} {label}: seeded {ts:8.1f} ms ({len(rs)} rows)  "
                      f"unseeded TIMED OUT  vs truth {want}: {ok}", flush=True)
    await conn.close()
asyncio.run(main())
