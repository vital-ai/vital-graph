#!/usr/bin/env python3
"""issues/220: what over-fetch-and-retry would cost, simulated on perf220_vec_100k.

Each pass pulls the top-N nearest from the HNSW index alone (no child restriction),
joins them to the filtered pattern, and stops once K rows survive; otherwise N x4.
Measured against the exact answer. pgvector caps an HNSW scan at hnsw.ef_search
rows unless iterative scan is on, so each pass sets ef_search >= N (strict) or
uses iterative_scan (iter): the two ways a real implementation could get N rows.

    python test_scripts/perf/_issue220_overfetch.py
"""
import asyncio, os, statistics, sys, time, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import asyncpg

src = open(os.path.join(os.path.dirname(__file__), "_issue220_vector_topk.py")).read()
m = {"__file__": os.path.join(os.path.dirname(__file__), "_issue220_vector_topk.py")}
exec(compile(src.replace('if __name__ == "__main__":', "if False:"), "m", "exec"), m)
SPACE, INDEX, K, TIER, PG = m["SPACE"], m["INDEX"], m["K"], m["TIER"], m["PG"]
T = f"{SPACE}_vec_{INDEX}"
KGE = "http://vital.ai/ontology/haley-ai-kg#KGEntity"


def survivors_sql(tier):
    f = "" if tier is None else (
        f"AND EXISTS (SELECT 1 FROM {SPACE}_rdf_quad q2 JOIN {SPACE}_term p ON p.term_uuid = q2.predicate_uuid "
        f"AND p.term_text = '{TIER}' JOIN {SPACE}_term o ON o.term_uuid = q2.object_uuid AND o.term_text = '{tier}' "
        f"WHERE q2.subject_uuid = c.subject_uuid)")
    # the candidate batch joined to the pattern: is a KGEntity (+ the filter)
    return (f"SELECT c.subject_uuid, c.d FROM (SELECT subject_uuid, embedding <=> $1::vector AS d FROM {T} "
            f"ORDER BY embedding <=> $1::vector LIMIT $2) c "
            f"WHERE EXISTS (SELECT 1 FROM {SPACE}_rdf_quad q JOIN {SPACE}_term t ON t.term_uuid = q.object_uuid "
            f"AND t.term_text = '{KGE}' WHERE q.subject_uuid = c.subject_uuid) {f} ORDER BY c.d LIMIT {K}")


async def overfetch(conn, probe, tier, mode):
    n, passes, t0 = K, 0, time.perf_counter()
    while True:
        passes += 1
        async with conn.transaction():
            if mode == "strict":
                await conn.execute(f"SET LOCAL hnsw.ef_search = {min(max(40, n), 1000)}")
            else:
                await conn.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
            rows = await conn.fetch(survivors_sql(tier), probe, n)
        if len(rows) >= K or n >= 100_000:
            return (time.perf_counter() - t0) * 1000, passes, n, {r[0] for r in rows}
        n *= 4


async def main():
    probe = m["vec"](random.Random(4220))
    conn = await asyncpg.connect(**PG)
    print(f"{'filter':9} {'mode':7} {'passes':>6} {'final N':>8} {'rows':>4} {'exact':>6} {'ms min/med/max':>22}")
    for tier in (None, "common", "uncommon", "rare"):
        where = "" if tier is None else (
            f"AND v.subject_uuid IN (SELECT q.subject_uuid FROM {SPACE}_rdf_quad q "
            f"JOIN {SPACE}_term p ON p.term_uuid = q.predicate_uuid AND p.term_text = '{TIER}' "
            f"JOIN {SPACE}_term o ON o.term_uuid = q.object_uuid AND o.term_text = '{tier}')")
        async with conn.transaction():
            await conn.execute("SET LOCAL enable_indexscan = off")
            truth = {r[0] for r in await conn.fetch(
                f"SELECT v.subject_uuid FROM {T} v WHERE TRUE {where} ORDER BY v.embedding <=> $1::vector LIMIT {K}", probe)}
        for mode in ("strict", "iter"):
            await overfetch(conn, probe, tier, mode)       # warm
            res = [await overfetch(conn, probe, tier, mode) for _ in range(5)]
            ms = sorted(r[0] for r in res)
            _, passes, n, got = res[-1]
            print(f"{tier or 'none':9} {mode:7} {passes:6} {n:8,} {len(got):4} {len(got & truth):>3}/{K:<2} "
                  f"{ms[0]:7.1f}/{statistics.median(ms):7.1f}/{ms[-1]:7.1f}")
    await conn.close()

asyncio.run(main())
