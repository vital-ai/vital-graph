#!/usr/bin/env python3
"""What the recomputed rdf_stats costs to READ, and what it buys the planner.

Three questions, in the order they matter:

  1. THE READ. `_load_quad_stats` pulls the whole table on every query that
     consults the join reorder. That cost is paid per query, so it bounds how
     large the table may be — and it is why `keep_top_n` exists at all.
  2. THE COVERAGE. How much of the graph the kept pairs actually account for.
     A cheap table that prices nothing is not a bargain.
  3. THE DECISION. Whether a constrained end gets a NUMBER: priced from the
     table, or bounded by `absence_bounds`, or genuinely unknown. An unpriced
     end is one the planner cannot order against, which is the failure the
     whole change is about.
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


async def main():
    ap = argparse.ArgumentParser()
    add_pg_arguments(ap)
    ap.add_argument("--space", default="maint_large_trial")
    a = ap.parse_args()
    print(describe_target(a))
    sp = a.space

    from vitalgraph.db.sparql_sql.sync_stats_tables import absence_bounds

    conn = await asyncpg.connect(host=a.host, port=a.port, user=a.user,
                                 password=a.password, database=a.database,
                                 command_timeout=900)
    try:
        quads = await conn.fetchval(f"SELECT count(*) FROM {sp}_rdf_quad")
        print(f"\n{sp}: {quads:,} quads\n")

        # 1. THE READ — exactly the two queries the generator issues.
        best = None
        for _ in range(3):
            t0 = time.monotonic()
            pred_rows = await conn.fetch(
                f"SELECT predicate_uuid::text, row_count FROM {sp}_rdf_pred_stats")
            quad_rows = await conn.fetch(
                f"SELECT predicate_uuid::text, object_uuid::text, row_count "
                f"FROM {sp}_rdf_stats WHERE row_count >= 2")
            pred_stats = {r["predicate_uuid"]: r["row_count"] for r in pred_rows}
            quad_stats = {(r["predicate_uuid"], r["object_uuid"]): r["row_count"]
                          for r in quad_rows}
            ms = (time.monotonic() - t0) * 1000
            best = ms if best is None else min(best, ms)
        print(f"1. READ        {len(quad_stats):,} pairs + {len(pred_stats)} "
              f"predicates in {best:.0f} ms  (per query, best of 3)")

        # 2. COVERAGE
        total = sum(pred_stats.values())
        covered = sum(quad_stats.values())
        mx = max(quad_stats.values())
        print(f"2. COVERAGE    stored pairs account for {covered:,} of "
              f"{total:,} quads ({100*covered/total:.1f}%), largest pair "
              f"{mx:,} rows")

        # 3. THE DECISION — can a constrained end be priced?
        bounds = absence_bounds(quad_stats, pred_stats)
        sample = await conn.fetch(f"""
            SELECT predicate_uuid::text p, object_uuid::text o, count(*) n
              FROM (SELECT predicate_uuid, object_uuid FROM {sp}_rdf_quad
                     TABLESAMPLE SYSTEM (0.05)) s
             GROUP BY 1,2 LIMIT 20000""")
        priced = bounded = unknown = 0
        for r in sample:
            k = (r["p"], r["o"])
            if k in quad_stats:
                priced += 1
            elif r["p"] in bounds:
                bounded += 1
            else:
                unknown += 1
        n = max(len(sample), 1)
        print(f"3. DECISION    of {len(sample):,} sampled constrained ends:")
        print(f"                 priced exactly from the table : {priced:,} "
              f"({100*priced/n:.1f}%)")
        print(f"                 bounded by absence_bounds     : {bounded:,} "
              f"({100*bounded/n:.1f}%)")
        print(f"                 UNKNOWN (cannot be ordered)   : {unknown:,} "
              f"({100*unknown/n:.1f}%)")
        print(f"\n   before `issues/153` every one of the {bounded + unknown:,} "
              f"non-stored ends was UNKNOWN;\n   now {100*(priced+bounded)/n:.1f}% "
              f"of ends carry a number the reorder can compare.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
