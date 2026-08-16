#!/usr/bin/env python3
"""Add `frame_type_uuid` to a space's frame_entity table and backfill it.

The frame's type, denormalised onto the collapsed row. Without it a typed
traversal hop joins back to `rdf_quad` once per row to ask "is this a KGFrame",
handing back the join reduction `frame_entity` exists to provide.

Measured on `wordnet_frames`, depth-3 walk: the type probe was **79% of all
buffers** (2,006,247 of 2,543,685), executed 501,538 times. As a column
predicate the same walk goes 53 ms -> 9 ms. On a filtered walk from a hub start,
1,037 ms -> 466 ms.

This is `issues/060` applied to `frame_entity`: that issue added
`edge_type_uuid` to `edge` for the same reason, and `emit_backward` consumes it
as `e0.edge_type_uuid = '...'::uuid`. Same shape, same rationale, one table
later.

WHY VITALTYPE AND NOT rdf:type

Three reasons that agree:

  * **It is single-valued by design**, so the column is well-defined. `rdf:type`
    may legitimately repeat, and a column cannot hold a set.
  * **`edge_type_uuid` uses it**, so the two denormalised type columns mean the
    same thing.
  * **It is what the product queries with.** `kgframes_endpoint` emits
    `<frame> vital-core:vitaltype <KGFrame>`.

On both loaded fixtures the two predicates agree exactly — 285,348 and 473,274
frames, zero disagreements, zero multi-typed — but agreement observed is not
agreement guaranteed, and vitaltype is the one with a guarantee behind it.

NULLABLE, and left NULL where there is no type

A frame reachable through its slots but carrying no vitaltype triple is still a
frame. Backfilling with an inner join would drop it, changing which rows the
table describes rather than only how fast it answers. The count of rows left
NULL is reported rather than hidden — on a space with no vitaltype quads at all
that is every row, and it is correct.

    python scripts/migrate_frame_entity_type_column.py --space wordnet_frames --dry-run
    python scripts/migrate_frame_entity_type_column.py --all
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger("migrate_frame_entity_type_column")

VITALTYPE_URI = "http://vital.ai/ontology/vital-core#vitaltype"
_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
VT_UUID = uuid.uuid5(_NS, f"{VITALTYPE_URI}\x00U")


async def _has_column(conn, table: str, column: str) -> bool:
    return bool(await conn.fetchval(
        "SELECT 1 FROM information_schema.columns WHERE table_schema='public' "
        "AND table_name=$1 AND column_name=$2", table, column))


async def migrate_space(conn, space_id: str, dry_run: bool = True) -> dict:
    t_fe = f"{space_id}_frame_entity"
    if not await conn.fetchval(
            "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1",
            t_fe):
        return {"space": space_id, "skipped": "no frame_entity table"}

    rows = await conn.fetchval(f"SELECT count(*) FROM {t_fe}")
    added = not await _has_column(conn, t_fe, "frame_type_uuid")
    if not added:
        missing = await conn.fetchval(
            f"SELECT count(*) FROM {t_fe} WHERE frame_type_uuid IS NULL")
        if not missing:
            return {"space": space_id, "skipped": "already current"}
    else:
        missing = rows

    # How many of THOSE could actually be filled — the rest have no vitaltype
    # quad, where NULL is the right answer rather than a gap.
    #
    # The NULL filter matters twice. Without it this counts every row carrying a
    # vitaltype quad including the ones already filled, so a space that is fully
    # migrated reports work outstanding; and because a space whose remaining
    # NULLs are all unfillable then never reaches "already current", it is
    # reported as needing migration on every future run, forever. Observed on a
    # fixture with 200 frames and no vitaltype quads at all: the migration
    # correctly left all 200 NULL and the next dry run still claimed 1 space
    # needed migrating.
    null_filter = "" if added else "AND fe.frame_type_uuid IS NULL"
    fillable = await conn.fetchval(f"""
        SELECT count(*) FROM {t_fe} fe
        WHERE EXISTS (SELECT 1 FROM {space_id}_rdf_quad q
                      WHERE q.subject_uuid = fe.frame_uuid
                        AND q.context_uuid = fe.context_uuid
                        AND q.predicate_uuid = $1)
          {null_filter}
    """, VT_UUID)

    # Column present and nothing left that CAN be filled: this space is done.
    # The remaining NULLs are the correct answer for frames with no vitaltype.
    if not added and not fillable:
        return {"space": space_id, "skipped": "already current",
                "unfillable_nulls": missing}

    summary = {"space": space_id, "rows": rows, "added_column": added,
               "unfilled_before": missing, "fillable": fillable}
    if dry_run:
        return summary

    if added:
        # Nullable with no default: metadata-only on PG11+, so no table rewrite.
        await conn.execute(
            f"ALTER TABLE {t_fe} ADD COLUMN IF NOT EXISTS frame_type_uuid UUID")
    await conn.execute(f"""
        UPDATE {t_fe} fe SET frame_type_uuid = q.object_uuid
        FROM {space_id}_rdf_quad q
        WHERE q.subject_uuid = fe.frame_uuid
          AND q.context_uuid = fe.context_uuid
          AND q.predicate_uuid = $1
          AND fe.frame_type_uuid IS DISTINCT FROM q.object_uuid
    """, VT_UUID)
    for stmt in (
        f"CREATE INDEX IF NOT EXISTS idx_{space_id}_fe_type_src ON {t_fe} "
        f"(frame_type_uuid, source_entity_uuid)",
        f"CREATE INDEX IF NOT EXISTS idx_{space_id}_fe_type_dst ON {t_fe} "
        f"(frame_type_uuid, dest_entity_uuid)",
    ):
        await conn.execute(stmt)
    await conn.execute(f"ANALYZE {t_fe}")
    summary["unfilled_after"] = await conn.fetchval(
        f"SELECT count(*) FROM {t_fe} WHERE frame_type_uuid IS NULL")
    return summary


async def spaces_on(conn):
    return [r["tablename"][: -len("_frame_entity")] for r in await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
        "AND tablename LIKE '%\\_frame\\_entity' ORDER BY tablename")]


async def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--space")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--host", default=os.environ.get("VG_TEST_PG_HOST", "localhost"))
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("VG_TEST_PG_PORT", "5432")))
    ap.add_argument("--database",
                    default=os.environ.get("VG_TEST_PG_DATABASE", "sparql_sql_graph"))
    ap.add_argument("--user", default=os.environ.get("VG_TEST_PG_USER", "postgres"))
    ap.add_argument("--password", default=os.environ.get("VG_TEST_PG_PASSWORD", ""))
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    import asyncpg
    conn = await asyncpg.connect(host=args.host, port=args.port,
                                 database=args.database, user=args.user,
                                 password=args.password or None)
    try:
        targets = await spaces_on(conn) if args.all else [args.space]
        changed = 0
        for sid in targets:
            s = await migrate_space(conn, sid, dry_run=args.dry_run)
            if s.get("skipped"):
                continue
            changed += 1
            logger.info(
                "%s%s: %d rows, %s, %d fillable of %d unfilled%s",
                "[dry-run] " if args.dry_run else "", sid, s["rows"],
                "ADD COLUMN" if s["added_column"] else "column present",
                s["fillable"], s["unfilled_before"],
                "" if args.dry_run
                else f" -> {s['unfilled_after']} still NULL")
            if not args.dry_run and s["unfilled_after"]:
                logger.info("    %d row(s) have no vitaltype quad; NULL is "
                            "correct for those", s["unfilled_after"])
        logger.info("\n%d space(s) %s of %d examined", changed,
                    "need migration" if args.dry_run else "migrated", len(targets))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
