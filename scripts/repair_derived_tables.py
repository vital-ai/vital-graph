#!/usr/bin/env python3
"""Populate `frame_slot`, `entity_fanout`, `rdf_value_stats` and
`entity_slot_sort` where empty.

THE GAP. `migrate_space_schema.py` CREATES a missing derived table and says so
("Recreated derived tables are EMPTY — run the resync to repopulate them"), but
nothing runs that resync. A table that exists and is empty passes every schema
check we have: the column is present, the reconcile is clean, and the drift
reports read zero. It is only wrong at query time, where an empty derived table
is indistinguishable from a graph that genuinely has no frames.

Measured on the local host cluster 2026-08-15: 43 of 77 spaces had at least one
unpopulated derived table, and `frame_slot` / `entity_fanout` were empty on
EVERY space with data — including one where frame_slot should hold 200,000
rows. The edge tables were populated throughout, so this is specifically the
layer derived FROM edge that never got built.

WHAT DEPENDS ON THEM, i.e. why an empty table is not a cosmetic problem:
  * `frame_slot` collapses six tables per hop into one for entity/frame
    traversal. Without it, that plan is unavailable.
  * `entity_fanout` records hub entities so the planner can avoid driving a
    walk from a high-degree node.
  * `rdf_value_stats` holds the value histograms behind the criterion gate.
    Empty means every value criterion reads as unmeasured.

ORDER IS NOT OPTIONAL. `resync_entity_fanout` rebuilds from `frame_slot`, so
running it first writes an empty hub list from an empty source and reports
success. frame_slot therefore always runs first here rather than leaving the
ordering to whoever calls this — the same footgun as backfilling
`value_stats.pred_rows` before `rdf_pred_stats` exists.

NOT INCLUDED: the edge table. `frame_slot` is derived from `edge`, so an
incomplete edge table yields an incomplete frame_slot — but the edge resync
has its own known defect (an edge table ~25% incomplete in production was
traced to both the ensure and resync paths), and rebuilding it is a bigger
decision than this script should make silently. If edge is wrong, this
faithfully reproduces that wrongness one layer up.

    python scripts/repair_derived_tables.py --all --dry-run
    python scripts/repair_derived_tables.py --space my_space
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

logger = logging.getLogger("repair_derived_tables")

# `frame_slot` indexes CONNECTOR FRAMES: a frame joining two entities through
# a source-entity slot and a destination-entity slot. It does NOT index
# entity->frame membership.
#
# Getting this wrong is easy and produces a confident false alarm. Counting
# `Edge_hasEntityKGFrame` (entity-to-frame membership) and calling that the
# expected frame_slot size reported one space as missing 41,730 rows when the
# correct answer for its data shape was zero — it has no connector frames at
# all, so the resync wrote nothing and was right to.
#
# The honest test is whether the space uses the pattern, which is exactly what
# `_resolve_uuids` checks before doing any work: all four URIs present in the
# term table. Absent, frame_slot is not applicable rather than empty.
# Above this fraction of sampled rows failing the referential probe, the table
# is STALE rather than merely behind, and only a resync fixes it. Matches
# EDGE_ORPHAN_STALE_PCT in the maintenance job so the two agree about what
# 'stale' means — a healthy table reads 0%, not 'a bit'.
STALE_ORPHAN_PCT = 0.5

CONNECTOR_URIS = (
    "http://vital.ai/ontology/haley-ai-kg#hasKGSlotType",
    "http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue",
    "urn:hasSourceEntity",
    "urn:hasDestinationEntity",
)


async def _exists(conn, table: str) -> bool:
    return bool(await conn.fetchval(
        "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1", table))


async def _count(conn, space_id: str, suffix: str):
    t = f"{space_id}_{suffix}"
    if not await _exists(conn, t):
        return None
    return await conn.fetchval(f"SELECT count(*) FROM {t}")


async def survey_space(conn, space_id: str) -> dict | None:
    """What is empty that should not be.

    Emptiness alone is not evidence: a space with no entity/frame edges SHOULD
    have an empty frame_slot. So the expected row count is derived from the
    quads and compared, rather than treating zero as automatically wrong.
    """
    if not await _exists(conn, f"{space_id}_rdf_quad"):
        return None
    quads = await conn.fetchval(f"SELECT count(*) FROM {space_id}_rdf_quad")
    if not quads:
        return None

    fe = await _count(conn, space_id, "frame_slot")
    ef = await _count(conn, space_id, "entity_fanout")
    vs = await _count(conn, space_id, "rdf_value_stats")
    edge = await _count(conn, space_id, "edge")

    present = await conn.fetchval(f"""
        SELECT count(*) FROM {space_id}_term WHERE term_text = ANY($1::text[])
    """, list(CONNECTOR_URIS))
    uses_connectors = present == len(CONNECTOR_URIS)

    need = []
    stale = []
    if fe is not None and not fe and uses_connectors:
        need.append("frame_slot")
    elif fe:
        # POPULATED IS NOT THE SAME AS CORRECT. This script only ever repaired an
        # EMPTY table, so the one failure it could not fix was the one that most
        # needs it: a space reloaded in place — or under a new graph URI — leaves
        # frame_slot a faithful materialisation of the PREVIOUS contents. Same
        # row count, disjoint set, drift zero, every traversal returning nothing
        # (issues/041). The maintenance job now names this script for exactly
        # that fault, so it has to be able to repair it.
        #
        # Resync TRUNCATEs and holds ACCESS EXCLUSIVE, which is why the
        # maintenance tick will not do it unattended. Here an operator asked.
        from vitalgraph.db.sparql_sql.sync_frame_slot_table import (
            frame_slot_orphan_rate)
        rate = await frame_slot_orphan_rate(conn, space_id)
        if rate > STALE_ORPHAN_PCT:
            need.append("frame_slot")
            stale.append(f"frame_slot {rate * 100:.0f}% orphaned")
    # entity_fanout is rebuilt FROM frame_slot, so it is only meaningful where
    # frame_slot has rows — AND only where some entity actually clears
    # min_fanout. It is a HUB list, not a copy: a space whose busiest entity has
    # one neighbour has no hubs, and zero rows is the right answer. Mirroring
    # the threshold here, like the value_stats test above, is the difference
    # between a report that converges and one that always says "1 remaining".
    if ef is not None and not ef and fe:
        from vitalgraph.db.sparql_sql.sync_entity_fanout import MIN_FANOUT_DEFAULT
        hubbed = await conn.fetchval(f"""
            SELECT EXISTS (
              SELECT 1 FROM {space_id}_frame_slot
              GROUP BY source_entity_uuid, context_uuid
              HAVING count(DISTINCT dest_entity_uuid) >= $1)""", MIN_FANOUT_DEFAULT)
        if hubbed:
            need.append("entity_fanout")
    # Same trap as frame_slot: empty is only wrong if there is something to
    # put in it. Histograms are built from numeric and temporal literals, so a
    # space carrying neither has zero rows correctly, and flagging it queues a
    # resync that can only ever write zero — reporting "needs repair" forever.
    if vs is not None and not vs:
        # MIRROR THE RESYNC'S OWN CONDITION rather than approximating it.
        # resync_value_stats only builds a histogram for a predicate with at
        # least `buckets` values in a lane — three numeric rows do not deserve
        # 33 buckets. Testing merely "has any numeric or temporal value" flagged
        # spaces whose single predicate had two datetime values, queuing a
        # resync that correctly wrote nothing and left them reported as needing
        # repair on every subsequent run.
        from vitalgraph.db.sparql_sql.sync_value_stats import DEFAULT_BUCKETS
        buildable = await conn.fetchval(f"""
            SELECT EXISTS (
              SELECT 1 FROM {space_id}_rdf_quad q
              JOIN {space_id}_term t ON t.term_uuid = q.object_uuid
              WHERE t.num_val IS NOT NULL OR t.dt_val IS NOT NULL
              GROUP BY q.predicate_uuid,
                       (t.num_val IS NOT NULL)
              HAVING count(*) >= $1)""", DEFAULT_BUCKETS)
        if buildable:
            need.append("value_stats")
    # entity_slot_sort (issues/096). Same trap once more, and the mirror is
    # exact here rather than approximated: ask the DERIVATION whether it would
    # produce a row. A space with no entity->frame->slot walk carrying a value
    # correctly has zero, and a proxy like "has slot edges" would flag it
    # forever.
    ess = await _count(conn, space_id, "entity_slot_sort")
    if ess is not None and not ess:
        from vitalgraph.db.sparql_sql.sync_entity_slot_sort import (
            _select_rows, _type_args)
        try:
            row = await conn.fetchrow(
                f"SELECT 1 FROM ({_select_rows(space_id, 'TRUE')}) s LIMIT 1",
                *(await _type_args(space_id)))
            if row:
                need.append("entity_slot_sort")
        except Exception:
            # A space predating the table has no schema for it; not applicable
            # rather than empty, exactly as the connector check treats a term
            # table without the connector URIs.
            pass

    # entity_prop_sort, tested the same way: empty is only a defect if the
    # derivation would produce a row. A space with no KG entities correctly has
    # zero, and a proxy would flag it forever.
    eps = await _count(conn, space_id, "entity_prop_sort")
    if eps is not None and not eps:
        from vitalgraph.db.sparql_sql.sync_entity_prop_sort import (
            _select_rows as _eps_select, _args as _eps_args)
        try:
            row = await conn.fetchrow(
                f"SELECT 1 FROM ({_eps_select(space_id, 'TRUE')}) s LIMIT 1",
                *_eps_args())
            if row:
                need.append("entity_prop_sort")
        except Exception:
            # A space predating the table has no schema for it; not applicable
            # rather than empty.
            pass

    # frame_prop_sort, tested the same way as its entity sibling: empty is only
    # a defect if the derivation would produce a row.
    fps = await _count(conn, space_id, "frame_prop_sort")
    if fps is not None and not fps:
        from vitalgraph.db.sparql_sql.sync_frame_prop_sort import (
            _select_rows as _fps_select, _args as _fps_args)
        try:
            row = await conn.fetchrow(
                f"SELECT 1 FROM ({_fps_select(space_id, 'TRUE')}) s LIMIT 1",
                *_fps_args())
            if row:
                need.append("frame_prop_sort")
        except Exception:
            pass

    if not need:
        return None
    return {"space": space_id, "quads": quads, "need": need, "stale": stale,
            "frame_slot": fe, "uses_connectors": uses_connectors,
            "edge": edge, "value_stats": vs, "entity_slot_sort": ess,
            "entity_prop_sort": eps}


async def repair_space(conn, space_id: str, need: list[str]) -> dict:
    from vitalgraph.db.sparql_sql.sync_frame_slot_table import resync_frame_slot_table
    from vitalgraph.db.sparql_sql.sync_entity_fanout import resync_entity_fanout
    from vitalgraph.db.sparql_sql.sync_value_stats import resync_value_stats

    out: dict = {}
    # frame_slot FIRST — entity_fanout reads from it.
    if "frame_slot" in need:
        t0 = time.time()
        out["frame_slot"] = await resync_frame_slot_table(conn, space_id)
        out["frame_slot_s"] = round(time.time() - t0, 1)
    if "entity_fanout" in need or "frame_slot" in need:
        t0 = time.time()
        r = await resync_entity_fanout(conn, space_id)
        out["entity_fanout"] = sum(r.values()) if isinstance(r, dict) else r
        out["entity_fanout_s"] = round(time.time() - t0, 1)
    if "value_stats" in need:
        t0 = time.time()
        r = await resync_value_stats(conn, space_id)
        out["value_stats"] = r.get("rows") if isinstance(r, dict) else r
        out["value_stats_s"] = round(time.time() - t0, 1)
    # entity_slot_sort is derived from `edge` like frame_slot, and from
    # nothing this script rebuilds, so its position here is free.
    if "entity_slot_sort" in need:
        from vitalgraph.db.sparql_sql.sync_entity_slot_sort import (
            resync_entity_slot_sort)
        t0 = time.time()
        out["entity_slot_sort"] = await resync_entity_slot_sort(conn, space_id)
        out["entity_slot_sort_s"] = round(time.time() - t0, 1)
    if "entity_prop_sort" in need:
        from vitalgraph.db.sparql_sql.sync_entity_prop_sort import (
            resync_entity_prop_sort)
        t0 = time.time()
        out["entity_prop_sort"] = await resync_entity_prop_sort(conn, space_id)
        out["entity_prop_sort_s"] = round(time.time() - t0, 1)
    if "frame_prop_sort" in need:
        from vitalgraph.db.sparql_sql.sync_frame_prop_sort import (
            resync_frame_prop_sort)
        t0 = time.time()
        out["frame_prop_sort"] = await resync_frame_prop_sort(conn, space_id)
        out["frame_prop_sort_s"] = round(time.time() - t0, 1)
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
        n = 0
        for sid in targets:
            s = await survey_space(conn, sid)
            if s is None:
                continue
            n += 1
            if a.dry_run:
                logger.info("[dry-run] %s: %s empty (%s quads, connector frames: %s)",
                            sid, "+".join(s["need"]), f"{s['quads']:,}",
                            "yes" if s["uses_connectors"] else "no")
                continue
            r = await repair_space(conn, sid, s["need"])
            parts = [f"{k}={v:,}" for k, v in r.items()
                     if not k.endswith("_s") and isinstance(v, int)]
            secs = sum(v for k, v in r.items() if k.endswith("_s"))
            logger.info("%s: %s in %.1fs", sid, ", ".join(parts) or "nothing", secs)
        logger.info("\n%d space(s) %s of %d examined", n,
                    "need repair" if a.dry_run else "repaired", len(targets))
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
