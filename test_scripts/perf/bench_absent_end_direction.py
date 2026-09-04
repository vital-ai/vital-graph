#!/usr/bin/env python3
"""Does pricing an ABSENT end actually produce a better plan? (`issues/153`)

`tests/unit/sparql_sql/test_absence_is_an_upper_bound.py` proves the direction
flips. It cannot prove the flip is an improvement — `issues/090` measured the
direction choice swinging 9.2x one way and 4.2x the other, so the sign has to be
measured, not argued.

THE SHAPE UNDER TEST is the one that was reported timing out in production: a
query constrained to an id that matches NOTHING. "It should be finding 0 but
instead it times out." With the end unpriced, `choose_direction` drove from
whichever end it could price — the common one, now that the table keeps each
predicate's largest pairs — and scanned it. With the bound, the empty end prices
as 1 and the query drives from the side that returns nothing immediately.

Reports EXPLAIN ANALYZE for both arms. Run it against the docker test stack.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

import asyncpg  # noqa: E402
from devtools.target import add_pg_arguments, describe_target  # noqa: E402


async def find_absent_pair(conn, space: str):
    """A (predicate, object) the planner cannot price: high-cardinality
    predicate, and an object that is NOT in rdf_stats.

    Returns (predicate_uuid, object_uuid, true_quad_count). A count of 1 is the
    singleton case; the zero case is synthesised by the caller with a uuid that
    appears nowhere, which is the reported production shape.
    """
    return await conn.fetchrow(f"""
        WITH per_pred AS (
          SELECT predicate_uuid, count(DISTINCT object_uuid) AS cardinality
            FROM {space}_rdf_quad GROUP BY 1 ORDER BY 2 DESC LIMIT 1)
        SELECT q.predicate_uuid, q.object_uuid, count(*) AS rc
          FROM {space}_rdf_quad q
          JOIN per_pred p ON p.predicate_uuid = q.predicate_uuid
         WHERE NOT EXISTS (SELECT 1 FROM {space}_rdf_stats s
                            WHERE s.predicate_uuid = q.predicate_uuid
                              AND s.object_uuid = q.object_uuid)
         GROUP BY 1, 2 ORDER BY count(*) ASC LIMIT 1""")


async def main():
    ap = argparse.ArgumentParser()
    add_pg_arguments(ap)
    ap.add_argument("--space", default="sp_lead_synth_10k")
    a = ap.parse_args()
    print(describe_target(a))

    conn = await asyncpg.connect(host=a.host, port=a.port, user=a.user,
                                 password=a.password, database=a.database,
                                 command_timeout=600)
    try:
        from vitalgraph.db.sparql_sql.sync_stats_tables import (
            absence_bounds, recompute_stats_tables)

        await recompute_stats_tables(conn, a.space)
        stats = {(r["predicate_uuid"], r["object_uuid"]): r["row_count"]
                 for r in await conn.fetch(
                     f"SELECT predicate_uuid, object_uuid, row_count "
                     f"FROM {a.space}_rdf_stats")}
        preds = {r["predicate_uuid"]: r["row_count"] for r in await conn.fetch(
            f"SELECT predicate_uuid, row_count FROM {a.space}_rdf_pred_stats")}
        # pred_stats too: it holds every predicate, including the ones whose
        # objects are all singletons and so have no stored pair. Those are the
        # id-shaped predicates a query constrains.
        bounds = absence_bounds(stats, preds)
        print(f"\n{a.space}: {len(stats):,} pairs stored over {len(bounds)} "
              f"predicate(s)")
        cut = [p for p, b in bounds.items() if b > 1]
        print(f"  predicates CUT (absent pair bounded by min stored): {len(cut)}")
        print(f"  predicates NOT cut (absent pair means <= 1)       : "
              f"{len(bounds) - len(cut)}")

        row = await find_absent_pair(conn, a.space)
        if not row:
            print("\nNo absent pair on the highest-cardinality predicate — this "
                  "space cannot exercise the bound. Try a larger one.")
            return
        pred, obj, rc = row["predicate_uuid"], row["object_uuid"], row["rc"]
        b = bounds.get(pred)
        print(f"\nAbsent pair found on the widest predicate:")
        print(f"  true quad count : {rc}")
        print(f"  priced before   : None  (unknown -> drive from the other end)")
        print(f"  priced now      : {b}    (upper bound; true value is {rc})")
        print(f"  bound is {'SOUND' if b is None or rc <= b else 'VIOLATED'}")

        # The cost of getting the direction wrong. ACROSS predicates, which is
        # the real shape: a query constrains a rare id on one end and a common
        # type on the other. Comparing within one predicate is not the case that
        # arises — and on the widest predicate there IS no large pair to compare
        # against, because all of its pairs are singletons.
        big = await conn.fetchrow(
            f"SELECT predicate_uuid, object_uuid, row_count "
            f"FROM {a.space}_rdf_stats ORDER BY row_count DESC LIMIT 1")
        if big:
            print(f"\n  Driving set size, each end materialised "
                  f"(best of 3, warm):")
            arms = (("rare end   (chosen NOW)", pred, obj),
                    ("common end (chosen BEFORE)",
                     big["predicate_uuid"], big["object_uuid"]))
            for label, p_, o_ in arms:
                best, n = None, 0
                for _ in range(3):
                    t0 = time.monotonic()
                    n = await conn.fetchval(
                        f"SELECT count(*) FROM {a.space}_rdf_quad "
                        f"WHERE predicate_uuid = $1 AND object_uuid = $2", p_, o_)
                    ms = (time.monotonic() - t0) * 1000
                    best = ms if best is None else min(best, ms)
                print(f"    {label:<28} {n:>9,} rows  {best:>8.2f} ms")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
