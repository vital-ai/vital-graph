"""Report and record `entity_slot_sort` coverage for one or more spaces.

The operator half of `issues/161`. Both runbooks call for verifying coverage
after a backfill — `deploy_slot_value_filter_fast_path.md` §3.4 and
`deploy_main_to_production.md` §7 step G — and this is that step.

USES `entity_slot_sort_all_types`, NOT `entity_slot_sort_coverage`. The latter
carries `HAVING in_table < of_type`, so it is EMPTY exactly when everything is
covered: it can confirm a gap and can never confirm success. Wiring the marker
to it would leave the FILTER fast path switched off while looking implemented.

Recording the marker is what lets that path serve a space at all — an unset or
`complete = false` marker makes it decline and fall back to the BGP join, which
is slow and correct. Measured at 818 ms on a 53.4M-quad space, so it is cheap
enough to run on demand.

    python test_scripts/perf/verify_slot_sort_coverage.py [space_id ...]

Connects to the vg-test stack on localhost:5433 by default; override with
VG_PGHOST / VG_PGPORT / VG_PGUSER / VG_PGPASSWORD / VG_PGDATABASE.
"""

import asyncio
import os
import sys
import time

sys.path.insert(0, os.getcwd())

import logging

logging.disable(logging.CRITICAL)

import asyncpg

from vitalgraph.db.sparql_sql.fast_slot_filter import record_slot_sort_coverage
from vitalgraph.db.sparql_sql.sync_entity_slot_sort import (
    entity_slot_sort_all_types)

SPACES = sys.argv[1:] or ["lead_nurture_100k"]


async def main():
    conn = await asyncpg.connect(
        host=os.getenv("VG_PGHOST", "localhost"),
        port=int(os.getenv("VG_PGPORT", "5433")),
        user=os.getenv("VG_PGUSER", "postgres"),
        password=os.getenv("VG_PGPASSWORD", "testpass"),
        database=os.getenv("VG_PGDATABASE", "sparql_sql_graph"),
    )
    try:
        for space in SPACES:
            t0 = time.monotonic()
            try:
                # A generous CLIENT-side timeout on purpose: the pool's default
                # is 60s and this walk is proportional to the space, which is
                # the whole of `issues/149`.
                cov = await entity_slot_sort_all_types(conn, space, timeout=600)
            except Exception as exc:
                print(f"  {space}: {type(exc).__name__}: {exc}", flush=True)
                continue
            print(f"  {space}: {(time.monotonic() - t0) * 1000:.0f} ms, "
                  f"{len(cov)} type(s)", flush=True)
            for c in cov:
                complete = c["in_table"] >= c["of_type"] and c["of_type"] > 0
                print(f"    {c['entity_type'][:46]:<46} "
                      f"{c['in_table']:>8}/{c['of_type']:<8} "
                      f"{'complete' if complete else 'SHORT'}", flush=True)
                await record_slot_sort_coverage(
                    conn, space, c["entity_type_uuid"],
                    c["in_table"], c["of_type"])
    finally:
        await conn.close()


asyncio.run(main())
