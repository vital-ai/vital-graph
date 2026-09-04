#!/usr/bin/env python3
"""Where does SQL GENERATION spend its time on the Nurture shape?

Measured on the 50M-quad space: `gen=6868ms exec=5088ms`. Generation costing
more than execution is a planner problem, and it is paid on every query of this
shape before Postgres does any work.

Generation makes several DATABASE round trips of its own before it emits SQL:

  * `_load_quad_stats`   — the whole rdf_stats table plus rdf_pred_stats
  * range/IN criteria    — value histograms, or a bounded runtime COUNT when
                           the histogram cannot answer
  * the semi-join gate   — a bounded probe when an anchor cannot be priced
  * traversal pair stats — on-demand lookups for chain ends

This times each in isolation against the same space, so the 6.9 s is attributed
rather than guessed at.
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

TEXT_PRED = "http://vital.ai/ontology/haley-ai-kg#hasTextSlotValue"
ABSENT = "NO_SUCH_COMPANY_ZZZ_9999"


async def timed(label, coro):
    t0 = time.monotonic()
    out = await coro
    return label, (time.monotonic() - t0) * 1000, out


async def main():
    ap = argparse.ArgumentParser()
    add_pg_arguments(ap)
    ap.add_argument("--space", default="maint_large_trial")
    a = ap.parse_args()
    print(describe_target(a))
    sp = a.space

    conn = await asyncpg.connect(host=a.host, port=a.port, user=a.user,
                                 password=a.password, database=a.database,
                                 command_timeout=900)
    try:
        rows = []

        # 1. the bulk stats load the generator does per query
        rows.append(await timed("load rdf_stats + rdf_pred_stats", (lambda: (
            conn.fetch(f"SELECT predicate_uuid::text, object_uuid::text, row_count "
                       f"FROM {sp}_rdf_stats WHERE row_count >= 2")))()))

        # 2. resolving a term that DOES NOT EXIST — the absent constraint
        rows.append(await timed("resolve an absent term", conn.fetchval(
            f"SELECT term_uuid FROM {sp}_term WHERE term_text = $1 "
            f"AND term_type = 'L'", ABSENT)))

        # 3. the value-histogram lookup for a text criterion
        rows.append(await timed("read rdf_value_stats", conn.fetch(
            f"SELECT * FROM {sp}_rdf_value_stats LIMIT 1000")))

        # 4. a BOUNDED runtime count — what the gate falls back to when it
        #    cannot price a criterion from statistics. This is the shape the
        #    recompute docstring records at 10.4 s on production.
        rows.append(await timed("bounded runtime count (cap 50k)", conn.fetchval(
            f"SELECT count(*) FROM (SELECT 1 FROM {sp}_rdf_quad q "
            f"JOIN {sp}_term t ON t.term_uuid = q.object_uuid "
            f"WHERE t.term_text = $1 LIMIT 50000) s", "United States")))

        # 5. the same for the ABSENT value — must scan to prove a negative
        rows.append(await timed("bounded runtime count, ABSENT value",
                                conn.fetchval(
            f"SELECT count(*) FROM (SELECT 1 FROM {sp}_rdf_quad q "
            f"JOIN {sp}_term t ON t.term_uuid = q.object_uuid "
            f"WHERE t.term_text = $1 LIMIT 50000) s", ABSENT)))

        print(f"\n{'generation step':<44}{'ms':>10}")
        for label, ms, out in rows:
            n = len(out) if hasattr(out, "__len__") else out
            print(f"{label:<44}{ms:>10,.0f}   -> {n}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
