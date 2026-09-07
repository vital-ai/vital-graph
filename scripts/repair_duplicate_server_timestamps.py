#!/usr/bin/env python3
"""Collapse duplicated server-stamped timestamps to one value per subject.

WHAT IS WRONG
    `hasObjectCreationTime` and `hasObjectModificationDateTime` are
    single-valued, and some subjects carry two to four values. The object layer
    groups repeated predicates into a LIST, a list is not a datetime, and
    `from_property_maps` then raises for the whole batch it is given — so ONE
    such subject blanked an entire 25-row page of the KG entity listing
    (`sparql_sql_db_objects._materialize` now bounds that to the one row, but
    the row is still missing until the data is fixed).

HOW IT HAPPENED
    UPSERT is `delete_object` followed by `store_objects`, with NO TRANSACTION
    around the pair. A client that times out and retries while the first request
    is still in flight gets: A deletes (nothing there yet) and begins storing;
    B checks `object_exists`, sees nothing committed, so does not delete, and
    stores too. Both inserts land.

    This is also why ONLY these two predicates are affected. Every other
    property carries the same value on each attempt, so the quad primary key
    (subject, predicate, object, context) silently dedupes the retry. These two
    are stamped SERVER-SIDE per request — `stamp_entity_server_properties` uses
    `datetime.now()` — so each attempt writes a DIFFERENT value and each one is
    a distinct row. The corruption is exactly the shape a retry race produces.

    On the production space the duplicates cluster into two incidents
    (2026-06-08 and 2026-07-29), spans under ~95s, values ~31s apart — a client
    retry interval, two to four attempts deep.

WHICH VALUE IS KEPT
    Creation time keeps the EARLIEST: the later stamps are retries of a create
    that had already happened. Modification time keeps the LATEST: it records
    when the subject was last written, and the last attempt is the one that
    wrote it. Neither is a guess about business meaning — both follow from what
    the property means and from the retry being the thing that produced them.

    Repairing rather than deduping: the values genuinely differ, so there is no
    identical-row collapse available. Rows are removed, never rewritten, so the
    surviving quad is one the system actually wrote.

Dry-run by default. `--apply` performs the delete in ONE transaction and then
recomputes the stats tables, whose per-predicate counts the delete invalidates.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from devtools.target import add_pg_arguments, describe_target  # noqa: E402
from vitalgraph.db.sparql_sql.sync_stats_tables import recompute_stats_tables  # noqa: E402

logger = logging.getLogger("repair_dupe_timestamps")

# (predicate URI, which value survives). ASC keeps the earliest, DESC the latest.
TARGETS = [
    ("http://vital.ai/ontology/vital-aimp#hasObjectCreationTime", "ASC"),
    ("http://vital.ai/ontology/vital#hasObjectModificationDateTime", "DESC"),
]


async def _predicate_uuid(conn, space_id: str, uri: str):
    return await conn.fetchval(
        f"SELECT term_uuid FROM {space_id}_term "
        f"WHERE term_text = $1 AND term_type = 'U' LIMIT 1", uri)


async def _graph_uuid(conn, space_id: str, graph_uri: str):
    return await conn.fetchval(
        f"SELECT term_uuid FROM {space_id}_term "
        f"WHERE term_text = $1 AND term_type = 'U' LIMIT 1", graph_uri)


def _victims_sql(space_id: str, keep: str) -> str:
    """Rows to remove: every value but the one that survives, per subject.

    Ordered by the TERM TEXT, not by anything in the quad row — these are
    ISO-8601 timestamps, which sort correctly as text, and the quad table has no
    column carrying the value's ordering.
    """
    return f"""
        SELECT subject_uuid, object_uuid FROM (
            SELECT q.subject_uuid, q.object_uuid,
                   row_number() OVER (PARTITION BY q.subject_uuid
                                      ORDER BY t.term_text {keep}) AS rn
              FROM {space_id}_rdf_quad q
              JOIN {space_id}_term t ON t.term_uuid = q.object_uuid
             WHERE q.predicate_uuid = $1 AND q.context_uuid = $2
               AND q.subject_uuid IN (
                   SELECT subject_uuid FROM {space_id}_rdf_quad
                    WHERE predicate_uuid = $1 AND context_uuid = $2
                    GROUP BY subject_uuid HAVING count(*) > 1)
        ) x WHERE rn > 1
    """


async def repair(conn, space_id: str, graph_uri: str, apply: bool) -> int:
    g_uuid = await _graph_uuid(conn, space_id, graph_uri)
    if g_uuid is None:
        logger.error("graph %s not found in %s_term", graph_uri, space_id)
        return 0

    total = 0
    for uri, keep in TARGETS:
        p_uuid = await _predicate_uuid(conn, space_id, uri)
        if p_uuid is None:
            logger.info("  %-62s not present in this space", uri.rsplit('#', 1)[-1])
            continue

        rows = await conn.fetch(_victims_sql(space_id, keep), p_uuid, g_uuid)
        subjects = len({r["subject_uuid"] for r in rows})
        label = "earliest" if keep == "ASC" else "latest"
        logger.info("  %-32s %5d redundant row(s) across %4d subject(s) — keeping %s",
                    uri.rsplit('#', 1)[-1], len(rows), subjects, label)
        total += len(rows)

        if apply and rows:
            await conn.executemany(
                f"DELETE FROM {space_id}_rdf_quad "
                f" WHERE subject_uuid = $1 AND predicate_uuid = $2 "
                f"   AND object_uuid = $3 AND context_uuid = $4",
                [(r["subject_uuid"], p_uuid, r["object_uuid"], g_uuid) for r in rows])
    return total


async def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_pg_arguments(ap)
    ap.add_argument("--space", required=True, help="space id")
    ap.add_argument("--graph", required=True, help="graph URI")
    ap.add_argument("--apply", action="store_true",
                    help="perform the delete (default is a dry run)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(f"\U0001F5C4  target: {describe_target(args)}", flush=True)

    import asyncpg
    conn = await asyncpg.connect(host=args.host, port=args.port,
                                 database=args.database, user=args.user,
                                 password=args.password or None)
    try:
        mode = "APPLY" if args.apply else "DRY RUN"
        logger.info("%s — space=%s graph=%s", mode, args.space, args.graph)
        if args.apply:
            # One transaction: a half-collapsed subject is still unreadable, so
            # there is no useful partial outcome to preserve.
            async with conn.transaction():
                n = await repair(conn, args.space, args.graph, apply=True)
                # The delete changes per-predicate row counts, and the planner
                # reads those. Recomputing inside the same transaction keeps the
                # stats consistent with the quads for any reader.
                if n:
                    await recompute_stats_tables(conn, args.space)
            logger.info("removed %d row(s); stats tables recomputed", n)
        else:
            n = await repair(conn, args.space, args.graph, apply=False)
            logger.info("would remove %d row(s). Re-run with --apply.", n)
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
