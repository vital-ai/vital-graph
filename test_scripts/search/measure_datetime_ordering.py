#!/usr/bin/env python3
"""Entity-datetime ordering vs rank ordering vs unordered, on the message FTS index.

The question this settles: ranked top-N on GIN is O(matches) because ts_rank_cd
is computed from the heap tuple, so every match is read and sorted before LIMIT
(issues/218). Ordering by an entity datetime instead MIGHT stream, via the
partial DESC index on entity_prop_sort. Until 2026-09-21 this was unmeasurable:
value_dt was NULL on every row because the export dropped datatypes (issues/221).

Three shapes per query, each LIMIT 25:
    A  unordered                  — the floor
    B  ORDER BY ts_rank_cd DESC   — what we do now
    C  ORDER BY entity value_dt DESC

Run A/B/C and then C/B/A. A first-run advantage is cache, not a plan: the first
A/B in issues/218 showed a 4.3x "win" that reversed when the order was swapped.

ROWS ARE REPORTED because a fast query returning nothing is the issues/171
failure, and is exactly how the datatype defect stayed hidden.
"""
from __future__ import annotations
import argparse, asyncio, os, statistics, sys, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MOD_DT = "http://vital.ai/ontology/vital#hasObjectModificationDateTime"

BASE = """
FROM {fts} f
JOIN {ess} ess ON ess.slot_uuid = f.subject_uuid AND ess.context_uuid = f.context_uuid
WHERE f.tsv @@ websearch_to_tsquery('english', $1)
"""

SHAPES = {
    "A_unordered": "SELECT f.subject_uuid " + BASE + " LIMIT 25",
    "B_rank":      "SELECT f.subject_uuid " + BASE +
                   " ORDER BY ts_rank_cd(f.tsv, websearch_to_tsquery('english',$1)) DESC LIMIT 25",
    "C_entity_dt": "SELECT f.subject_uuid, ps.value_dt " + BASE +
                   " AND ps.value_dt IS NOT NULL ORDER BY ps.value_dt DESC LIMIT 25",
}


def build(shape: str, space: str, prop_uuid: str) -> str:
    sql = SHAPES[shape].format(fts=f"{space}_fts_message_content", ess=f"{space}_entity_slot_sort")
    if shape == "C_entity_dt":
        sql = sql.replace(
            "WHERE f.tsv",
            f"JOIN {space}_entity_prop_sort ps ON ps.entity_uuid = ess.entity_uuid "
            f"AND ps.context_uuid = ess.context_uuid AND ps.property_uuid = '{prop_uuid}'::uuid "
            "WHERE f.tsv")
    return sql


async def timed(conn, sql: str, term: str, reps: int):
    """Returns (median_ms, rows). Discards the first run as warm-up."""
    times, rows = [], None
    for _ in range(reps + 1):
        t0 = time.monotonic()
        r = await conn.fetch(sql, term)
        times.append((time.monotonic() - t0) * 1000)
        rows = len(r)
    return statistics.median(times[1:]), rows


async def main():
    import asyncpg
    ap = argparse.ArgumentParser()
    ap.add_argument("--space", default="nurture_typed")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--host", default="localhost"); ap.add_argument("--port", type=int, default=5433)
    ap.add_argument("--db", default="sparql_sql_graph"); ap.add_argument("--user", default="postgres")
    ap.add_argument("--password", default="testpass")
    a = ap.parse_args()

    conn = await asyncpg.connect(host=a.host, port=a.port, database=a.db,
                                 user=a.user, password=a.password)
    try:
        prop_uuid = await conn.fetchval(
            f"SELECT term_uuid FROM {a.space}_term WHERE term_text = $1 LIMIT 1", MOD_DT)
        if not prop_uuid:
            print(f"FAIL: {MOD_DT} not in {a.space}_term"); return

        terms = ["app", "saved application", '"saved application"', "reschedule", "xylophone"]
        print(f"space={a.space}  reps={a.reps} (median, warm-up discarded)\n")

        for term in terms:
            total = await conn.fetchval(
                f"SELECT count(*) FROM {a.space}_fts_message_content "
                "WHERE tsv @@ websearch_to_tsquery('english',$1)", term)
            print(f"{term!r}  — {total:,} matching slots")
            # forward, then reverse: a first-run advantage is cache, not a plan
            for label, order in (("fwd", ["A_unordered", "B_rank", "C_entity_dt"]),
                                 ("rev", ["C_entity_dt", "B_rank", "A_unordered"])):
                out = []
                for shape in order:
                    ms, n = await timed(conn, build(shape, a.space, prop_uuid), term, a.reps)
                    out.append(f"{shape}={ms:8.1f}ms/{n:2d}r" + ("!!" if total and not n else ""))
                print(f"    {label}  " + "  ".join(out))
            print()
    finally:
        await conn.close()

asyncio.run(main())
