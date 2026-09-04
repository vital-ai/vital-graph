#!/usr/bin/env python3
"""Rebuild `{space}_rdf_pred_stats` for spaces whose predicates went unrecorded.

THE DRIFT. `rdf_pred_stats` holds one row per predicate with its quad count. It
was maintained incrementally by the write paths (removed 2026-09-03), so
a predicate that was written by a path which did NOT sync gets no row — ever.
The count does not merely go stale; the predicate is INVISIBLE to every reader.

WHAT WROTE WITHOUT SYNCING. The server-property quads —
`vital-aimp#hasObjectCreationTime`, `vital#hasObjectModificationDateTime`, and
`vital-aimp#hasObjectStatusType` — were stamped onto imported objects by a path
that did not sync stats. Both writers now cover them (the bulk loader folds them
into `quad_rows` before the stats sync, and the backfill in
`kg_server_properties` syncs what it wrote), so nothing new drifts. This repairs
spaces loaded before those fixes.

WHY IT MATTERS, given the counts are only estimates anyway: a MISSING row is not
a wrong estimate, it is no estimate. Measured on the host space `wordnet_frames`
2026-08-15 — 3 predicates absent, each with 109,745 quads, against 15 recorded.
Two of them carry the space's only temporal histograms, so:

  * `rdf_value_stats.pred_rows` backfills to NULL, because it reads its
    reference count from `rdf_pred_stats`. That silently disables freshness
    scaling for those histograms — the whole layer reads as inert.
  * The join reorder sees no cardinality for the predicate and the criterion
    gate cannot measure it, so a filter on a server property is unweighted.

ORDER MATTERS. Run this BEFORE `migrate_value_stats_pred_rows.py`: the backfill
copies `row_count` out of `rdf_pred_stats`, so backfilling first just writes
NULL again. This runs the backfill itself for that reason.

COST. A full `recompute_stats_tables` scans `rdf_quad`. Measured: 19s for 8.9M
quads. It does not lock the table against readers.

    python scripts/repair_stats_tables.py --all --dry-run
    python scripts/repair_stats_tables.py --space wordnet_frames
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from devtools.target import add_pg_arguments, describe_target  # noqa: E402

logger = logging.getLogger("repair_stats_tables")


async def _table_exists(conn, table: str) -> bool:
    return bool(await conn.fetchval(
        "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1",
        table))


async def sampled_counts_wrong(conn, space_id: str, sample: int = 5) -> tuple | None:
    """Is `rdf_stats` UNDERSTATING pairs it already records?

    Absence was the only thing this script originally tested, and a recorded
    count can be arbitrarily wrong while every predicate is present. Measured on
    a 5.1M-quad host space: the pair (rdf:type, KGFrame) was recorded as 6
    against 60,054 actual, and (rdf:type, Edge_hasKGSlot) as 37 against 304,859
    — four orders of magnitude, on a table that passed the missing-predicate
    check cleanly.

    That is not a cosmetic drift. `semijoin._selective_enough` divides the
    probe's match count by the ANCHOR's candidate count to decide between a
    per-row probe and a set-based join. With the anchor reading 6 instead of
    60,054, a genuinely 0.008%-selective query scored 83% selective and took the
    probe: 60,054 correlated EXISTS evaluations to return 5 rows, 269 ms where
    the set-based plan is 33 ms.

    Checks the LARGEST recorded pairs, because understatement is what flips the
    gate and the largest rows are where it shows. Exact counts on `sample`
    pairs are index scans on (predicate_uuid, object_uuid) — bounded work.
    """
    t_stats = f"{space_id}_rdf_stats"
    if not await _table_exists(conn, t_stats):
        return None
    rows = await conn.fetch(
        f"SELECT predicate_uuid, object_uuid, row_count FROM {t_stats} "
        f"ORDER BY row_count DESC LIMIT {int(sample)}")
    for r in rows:
        actual = await conn.fetchval(
            f"SELECT count(*) FROM {space_id}_rdf_quad "
            f"WHERE predicate_uuid = $1 AND object_uuid = $2",
            r["predicate_uuid"], r["object_uuid"])
        if actual != r["row_count"]:
            return (r["row_count"], actual)
    return None


async def survey_space(conn, space_id: str) -> dict | None:
    """Predicates present in rdf_quad but absent from rdf_pred_stats.

    Absence is the test, not staleness: an incremental counter that is merely
    behind still gives the planner a number to work with, while a missing row
    gives it nothing and is not self-healing.
    """
    t_quad, t_ps = f"{space_id}_rdf_quad", f"{space_id}_rdf_pred_stats"
    if not await _table_exists(conn, t_quad) or not await _table_exists(conn, t_ps):
        return None
    quads = await conn.fetchval(f"SELECT count(*) FROM {t_quad}")
    if not quads:
        return None
    missing = await conn.fetch(f"""
        SELECT q.predicate_uuid, count(*) AS n
        FROM {t_quad} q
        WHERE NOT EXISTS (SELECT 1 FROM {t_ps} p
                          WHERE p.predicate_uuid = q.predicate_uuid)
        GROUP BY 1 ORDER BY 2 DESC
    """)
    stale = await sampled_counts_wrong(conn, space_id)
    if not missing and not stale:
        return None
    return {
        "space": space_id,
        "quads": quads,
        "missing": len(missing),
        "missing_quads": sum(r["n"] for r in missing),
        "recorded": await conn.fetchval(f"SELECT count(*) FROM {t_ps}"),
        "stale": stale,
    }


async def repair_space(conn, space_id: str) -> dict:
    # `recompute_stats_tables`, the SAME function the maintenance job runs.
    #
    # Not `resync_stats_tables`, which is what this used to call and which now
    # means something different: it keeps `row_count = 1` pairs and DROPS
    # everything above STATS_MAX_ROW_COUNT, while the recompute has a floor of 2
    # and no upper bound. Repairing with the old one would have put rdf_stats
    # back into the shape the recompute replaces — without the large pairs that
    # are 36% of all quads and the structural anchors the join reorder most
    # needs — and reported it as a repair.
    from vitalgraph.db.sparql_sql.sync_stats_tables import recompute_stats_tables

    t0 = time.time()
    result = await recompute_stats_tables(conn, space_id)
    out = {"seconds": round(time.time() - t0, 1),
           "pred_stats": result.get("pred_stats")}

    # Backfill pred_rows now that the reference counts exist. Doing it here
    # rather than telling the operator to run the other script keeps the
    # ordering dependency from being a footgun.
    t_vs = f"{space_id}_rdf_value_stats"
    if await _table_exists(conn, t_vs):
        has_col = await conn.fetchval(
            "SELECT 1 FROM information_schema.columns WHERE table_schema='public' "
            "AND table_name=$1 AND column_name='pred_rows'", t_vs)
        if has_col:
            await conn.execute(f"""
                UPDATE {t_vs} vs SET pred_rows = ps.row_count
                FROM {space_id}_rdf_pred_stats ps
                WHERE ps.predicate_uuid = vs.predicate_uuid
                  AND vs.pred_rows IS DISTINCT FROM ps.row_count
            """)
            out["value_stats_null"] = await conn.fetchval(
                f"SELECT count(*) FROM {t_vs} WHERE pred_rows IS NULL")
    return out


async def spaces_on(conn):
    return [r["tablename"][: -len("_rdf_quad")] for r in await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
        "AND tablename LIKE '%\\_rdf\\_quad' ORDER BY tablename")]


async def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--space")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    add_pg_arguments(ap)
    a = ap.parse_args()
    print(f"🗄  target: {describe_target(a)}", flush=True)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    import asyncpg
    conn = await asyncpg.connect(host=a.host, port=a.port, database=a.database,
                                 user=a.user, password=a.password or None)
    try:
        targets = await spaces_on(conn) if a.all else [a.space]
        drifted = 0
        for sid in targets:
            s = await survey_space(conn, sid)
            if s is None:
                continue
            drifted += 1
            if a.dry_run:
                stale = ("" if not s.get("stale") else
                         f", largest recorded pair says {s['stale'][0]:,} "
                         f"against {s['stale'][1]:,} actual")
                logger.info(
                    "[dry-run] %s: %d predicate(s) unrecorded covering %s quads "
                    "(%d recorded, %s total quads)%s",
                    sid, s["missing"], f"{s['missing_quads']:,}", s["recorded"],
                    f"{s['quads']:,}", stale)
                continue
            r = await repair_space(conn, sid)
            logger.info(
                "%s: %d -> %s predicates in %ss%s", sid, s["recorded"],
                r["pred_stats"], r["seconds"],
                "" if r.get("value_stats_null") is None
                else f", {r['value_stats_null']} value_stats row(s) still NULL")
        logger.info("\n%d space(s) %s of %d examined", drifted,
                    "need repair" if a.dry_run else "repaired", len(targets))
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
