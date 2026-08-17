#!/usr/bin/env python3
"""Deduplicate `{space}_rdf_quad` and narrow its primary key to (s,p,o,c).

WHY. An RDF graph is a SET of triples. SPARQL 1.1 Update says a triple "MAY be
considered to be processed with no action if that triple already exists in the
graph", so (subject, predicate, object, context) is unique by the data model.

The non-partitioned table's key did not say so: it included `quad_uuid`, which
defaults to `gen_random_uuid()`. An identical quad therefore got a fresh key and
never conflicted, which made every `ON CONFLICT DO NOTHING` on this table a
no-op. Verified by re-inserting an existing quad — `INSERT 0 1`, row count 1
to 2. The partitioned variant already used the slim 4-column key and its own
comment calls that "true (s,p,o,c) dedup"; this brings the classic table into
line.

WHAT IT COSTS. Building the new key is an index build over the whole table, and
the DELETE rewrites only the duplicate rows. Both take a lock: the ALTER holds
ACCESS EXCLUSIVE for the duration. Sizes are reported before acting.

STATS AFTER, done here rather than advised. rdf_stats and rdf_pred_stats
counted the duplicates, because they count rows — so removing rows leaves them
high by exactly that many, and this script is the only thing that knows which
spaces changed. Advising `repair_stats_tables.py` instead was not enough: that
script samples the LARGEST recorded pairs, and duplicates concentrated in small
pairs leave those matching. Run over the 5 spaces this changed, it found 3 and
reported the other 2 as clean.

    python scripts/migrate_quad_pk_dedup.py --all --dry-run
    python scripts/migrate_quad_pk_dedup.py --space my_space
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vitalgraph_sparql_sql_dev.db import add_pg_arguments, describe_target  # noqa: E402

logger = logging.getLogger("migrate_quad_pk_dedup")

KEY_COLS = ("subject_uuid", "predicate_uuid", "object_uuid", "context_uuid")


async def _pk_columns(conn, table: str) -> list[str]:
    rows = await conn.fetch("""
        SELECT a.attname
        FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
        WHERE c.conrelid = $1::regclass AND c.contype = 'p'
        ORDER BY array_position(c.conkey, a.attnum)
    """, table)
    return [r["attname"] for r in rows]


async def _pk_name(conn, table: str) -> str | None:
    return await conn.fetchval(
        "SELECT conname FROM pg_constraint "
        "WHERE conrelid = $1::regclass AND contype = 'p'", table)


async def survey_space(conn, space_id: str) -> dict | None:
    t = f"{space_id}_rdf_quad"
    if not await conn.fetchval(
            "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1", t):
        return None
    # Partitioned tables already carry the slim key and are out of scope; a
    # partitioned parent cannot be ALTERed the same way regardless.
    is_part = await conn.fetchval(
        "SELECT relkind = 'p' FROM pg_class WHERE oid = $1::regclass", t)
    pk = await _pk_columns(conn, t)
    if list(pk) == list(KEY_COLS):
        return None                       # already correct
    total = await conn.fetchval(f"SELECT count(*) FROM {t}")
    distinct = await conn.fetchval(
        f"SELECT count(*) FROM (SELECT DISTINCT {', '.join(KEY_COLS)} FROM {t}) d")
    size = await conn.fetchval(f"SELECT pg_size_pretty(pg_total_relation_size('{t}'))")
    return {"space": space_id, "pk": pk, "partitioned": bool(is_part),
            "total": total, "distinct": distinct, "dupes": total - distinct,
            "size": size}


async def migrate_space(conn, space_id: str, s: dict) -> dict:
    t = f"{space_id}_rdf_quad"
    out = {"dropped": 0}
    t0 = time.time()
    async with conn.transaction():
        if s["dupes"]:
            # Keep one row per (s,p,o,c) — the oldest ctid, so the choice is
            # deterministic rather than whatever the planner returns.
            res = await conn.execute(f"""
                DELETE FROM {t} a USING {t} b
                WHERE a.ctid > b.ctid
                  AND a.subject_uuid = b.subject_uuid
                  AND a.predicate_uuid = b.predicate_uuid
                  AND a.object_uuid = b.object_uuid
                  AND a.context_uuid = b.context_uuid
            """)
            out["dropped"] = int(res.rsplit(" ", 1)[-1]) if res else 0
        name = await _pk_name(conn, t)
        if name:
            await conn.execute(f'ALTER TABLE {t} DROP CONSTRAINT "{name}"')
        await conn.execute(
            f"ALTER TABLE {t} ADD PRIMARY KEY ({', '.join(KEY_COLS)})")
    out["seconds"] = round(time.time() - t0, 1)
    return out


async def spaces_on(conn):
    # SMALLEST FIRST. Each space rebuilds a primary-key index under ACCESS
    # EXCLUSIVE, and the largest here is 24 GB / 50M rows. Ordering by size
    # means a mistake in this script surfaces on a 300-row table rather than
    # after twenty minutes of index build on the biggest one.
    return [r["tablename"][: -len("_rdf_quad")] for r in await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
        "AND tablename LIKE '%\\_rdf\\_quad' "
        "ORDER BY pg_total_relation_size(tablename::regclass) ASC, tablename")]


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
        n = total_dupes = 0
        needs_stats = []
        for sid in targets:
            s = await survey_space(conn, sid)
            if s is None:
                continue
            if s["partitioned"]:
                logger.info("%s: partitioned, already has the slim key — skipped", sid)
                continue
            n += 1
            total_dupes += s["dupes"]
            if a.dry_run:
                logger.info("[dry-run] %s: %s rows, %s duplicate(s), %s — PK %s -> (s,p,o,c)",
                            sid, f"{s['total']:,}", f"{s['dupes']:,}", s["size"],
                            "+".join(c.replace("_uuid", "") for c in s["pk"]))
                if s["dupes"]:
                    needs_stats.append(sid)
                continue
            r = await migrate_space(conn, sid, s)
            if r["dropped"]:
                # Resync HERE rather than advising it. rdf_stats counted the
                # removed rows, so this space is now wrong by exactly that many
                # — a fact this script knows and nothing downstream can
                # rediscover reliably: repair_stats_tables samples the LARGEST
                # recorded pairs, and duplicates concentrated in small pairs
                # leave those matching. Run against 5 changed spaces it found 3
                # and passed the other 2 as clean.
                from vitalgraph.db.sparql_sql.sync_stats_tables import (
                    resync_stats_tables)
                await resync_stats_tables(conn, sid)
                needs_stats.append(sid)
            logger.info("%s: dropped %s duplicate(s), PK narrowed, stats "
                        "resynced, %.1fs",
                        sid, f"{r['dropped']:,}", r["seconds"])
        logger.info("\n%d space(s) %s, %s duplicate quad(s) %s", n,
                    "need migration" if a.dry_run else "migrated",
                    f"{total_dupes:,}", "found" if a.dry_run else "removed")
        if needs_stats and a.dry_run:
            logger.info(
                "these spaces will have rows removed, so their rdf_stats will "
                "be resynced as part of the migration: %s", ", ".join(needs_stats))
        elif needs_stats:
            logger.info("stats resynced for: %s", ", ".join(needs_stats))
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
