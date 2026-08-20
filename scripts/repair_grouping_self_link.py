#!/usr/bin/env python3
"""Restore the `hasKGGraphURI` self-link on objects that group other objects.

THE INVARIANT. Every object in an entity's graph carries
`hasKGGraphURI -> <entity>`, and that includes the entity itself. The entity is
a member of its own graph. Without the self-link the entity is reachable only by
naming it directly, so "fetch this graph" returns the frames, slots and edges
but NOT the entity's own properties — its name, type and status simply vanish
from the result while the object count still looks plausible.

WHY THE RETRIEVAL CODE HIDES THIS. `get_entity_graph` is a UNION: one branch
fetches the entity's own triples by pinning its URI, the other fetches members
by grouping URI. The first branch papers over a missing self-link, which is why
619 broken URIs across 12 spaces produced no visible symptom. It also forces
every batched form of the query to keep a second branch that exists only to
compensate for data that should not be broken.

MEASURED on the local host cluster 2026-08-16, 619 grouping targets across 12
spaces with no self-link. Several spaces were 100% broken (500 of 500, 30 of
30, 11 of 11), which is the signature of a writer that never emitted it rather
than of occasional loss. On those the predicate is ABSENT on the entity, not
pointing somewhere else — checked, because "missing" and "wrong" need different
repairs and only one of them is safe to fix by inserting.

The create path is not the culprit: `set_dual_grouping_uris_with_frame_separation`
assigns `kGGraphURI` over every object in the set, the entity included. These
spaces were populated some other way.

WHAT THIS WRITES. One quad per (target, context) that lacks it, in the same
context the grouping quads already use. It never rewrites an existing value —
a target whose self-link points elsewhere is a different problem and is
reported rather than "corrected".

    python scripts/repair_grouping_self_link.py --all --dry-run
    python scripts/repair_grouping_self_link.py --all
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

logger = logging.getLogger("repair_grouping_self_link")

# What makes a grouping target a real object rather than a label.
TYPE_PREDS = ("http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
              "http://vital.ai/ontology/vital-core#vitaltype")

GRAPH_URI_PRED = "http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI"


async def _table_exists(conn, table: str) -> bool:
    return bool(await conn.fetchval(
        "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1", table))


async def survey_space(conn, space_id: str) -> dict | None:
    """Grouping targets with no self-link, and how many carry a wrong one."""
    if not await _table_exists(conn, f"{space_id}_rdf_quad"):
        return None
    pred = await conn.fetchval(
        f"SELECT term_uuid FROM {space_id}_term WHERE term_text = $1", GRAPH_URI_PRED)
    if not pred:
        return None                     # space does not use grouping URIs

    rows = await conn.fetch(f"""
        WITH targets AS (
            SELECT DISTINCT object_uuid AS e, context_uuid AS ctx
            FROM {space_id}_rdf_quad WHERE predicate_uuid = $1)
        SELECT t.e, t.ctx,
               EXISTS (SELECT 1 FROM {space_id}_rdf_quad q
                       WHERE q.predicate_uuid = $1 AND q.subject_uuid = t.e) AS has_any,
               EXISTS (SELECT 1 FROM {space_id}_rdf_quad ty
                       JOIN {space_id}_term typ ON typ.term_uuid = ty.predicate_uuid
                        AND typ.term_text = ANY($2::text[])
                       WHERE ty.subject_uuid = t.e) AS has_type
        FROM targets t
        WHERE NOT EXISTS (
            SELECT 1 FROM {space_id}_rdf_quad q
            WHERE q.predicate_uuid = $1 AND q.subject_uuid = t.e
              AND q.object_uuid = t.e AND q.context_uuid = t.ctx)
    """, pred, list(TYPE_PREDS))
    # Typeless targets REGARDLESS of self-link state. The `phantom` split below
    # only sees targets still missing a self-link, and after a repair run they
    # are not missing one — this script gave them one. So the 19 found on
    # 2026-08-20 were invisible to their own cause. A detector that stops seeing
    # a condition once it has written a row is reporting its own effect.
    typeless = await conn.fetchval(f"""
        SELECT count(*) FROM (
            SELECT DISTINCT object_uuid AS e
            FROM {space_id}_rdf_quad WHERE predicate_uuid = $1) t
        WHERE NOT EXISTS (
            SELECT 1 FROM {space_id}_rdf_quad ty
            JOIN {space_id}_term typ ON typ.term_uuid = ty.predicate_uuid
             AND typ.term_text = ANY($2::text[])
            WHERE ty.subject_uuid = t.e)
    """, pred, list(TYPE_PREDS))

    if not rows and not typeless:
        return None
    total = await conn.fetchval(
        f"SELECT count(DISTINCT object_uuid) FROM {space_id}_rdf_quad "
        f"WHERE predicate_uuid = $1", pred)
    rows = rows or []
    # A target that HAS the predicate but not pointing at itself is misdirected,
    # not missing. Inserting a second value would leave it with two grouping
    # URIs, so those are reported and skipped.
    misdirected = [r for r in rows if r["has_any"]]

    # A target with NO TYPE is not an object that lost its self-link — it is a
    # URI used as a group label with nothing behind it. Writing the self-link
    # does not repair it: a typeless subject builds no GraphObject, so the graph
    # still reads EMPTY, and the row makes a phantom look like an object.
    #
    # This script had no such check, and that is where `issues/092`'s shape came
    # from at scale. Scanned 2026-08-20, after the 2026-08-16 repair run: 19
    # typeless grouping targets across 4 spaces, EVERY ONE of them owning exactly
    # one triple — the self-link this script inserted.
    #
    #     kg_crud_stress_test            10   all 1 triple
    #     space_client_kgentities_test    5   all 1 triple
    #     space_multi_org_crud_test       3   all 1 triple
    #
    # Reported and skipped, on the same principle as `misdirected` above: a
    # repair that cannot restore the invariant should say so rather than write
    # something that makes the breakage harder to see.
    phantom = [r for r in rows if not r["has_any"] and not r["has_type"]]
    missing = [r for r in rows if not r["has_any"] and r["has_type"]]
    return {"space": space_id, "pred": pred, "total": total,
            "missing": missing, "misdirected": misdirected, "phantom": phantom,
            "typeless": typeless}


async def repair_space(conn, space_id: str, s: dict) -> int:
    if not s["missing"]:
        return 0
    written = [(r["e"], s["pred"], r["e"], r["ctx"]) for r in s["missing"]]
    async with conn.transaction():
        await conn.executemany(
            f"INSERT INTO {space_id}_rdf_quad "
            f"(subject_uuid, predicate_uuid, object_uuid, context_uuid) "
            f"VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING", written)
        # Quads written with raw SQL fire none of the incremental hooks in
        # sparql_sql_space_impl, which is exactly how rdf_pred_stats came to be
        # missing predicates entirely. Sync what was written.
        try:
            from vitalgraph.db.sparql_sql.sync_stats_tables import sync_stats_after_insert
            await sync_stats_after_insert(conn, space_id, written)
        except Exception as exc:
            logger.warning("%s: stats sync failed (%d quads) — run "
                           "repair_stats_tables: %s", space_id, len(written), exc)
    return len(written)


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
        n_spaces = n_quads = n_bad = n_typeless = 0
        for sid in targets:
            s = await survey_space(conn, sid)
            if s is None:
                continue
            n_spaces += 1
            n_bad += len(s["misdirected"]) + len(s["phantom"])
            n_typeless += s.get("typeless") or 0
            # One suffix, built once: the call used to take a separate
            # argument per category and gained more placeholders than the format
            # string had the moment a third was added.
            notes = []
            if s["misdirected"]:
                notes.append(f"{len(s['misdirected'])} MISDIRECTED, skipped")
            if s["phantom"]:
                notes.append(f"{len(s['phantom'])} TYPELESS, skipped — a grouping "
                             f"URI with no object behind it (issues/092)")
            if s.get("typeless"):
                notes.append(f"{s['typeless']} grouping target(s) carry NO TYPE, "
                             f"so their members are unreachable through the "
                             f"entity-graph read (issues/092)")
            suffix = f" [{'; '.join(notes)}]" if notes else ""

            if a.dry_run:
                logger.info("[dry-run] %s: %d of %d grouping URIs lack the "
                            "self-link%s", sid, len(s["missing"]), s["total"],
                            suffix)
                n_quads += len(s["missing"])
                continue
            t0 = time.time()
            wrote = await repair_space(conn, sid, s)
            n_quads += wrote
            logger.info("%s: wrote %d self-link(s) in %.1fs%s", sid, wrote,
                        time.time() - t0, suffix)
        logger.info("\n%d space(s) %s, %d self-link(s) %s", n_spaces,
                    "need repair" if a.dry_run else "repaired", n_quads,
                    "missing" if a.dry_run else "written")
        if n_bad:
            logger.warning("%d target(s) carry a grouping URI that is not their "
                           "own — inspect these by hand, inserting would give "
                           "them two", n_bad)
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
