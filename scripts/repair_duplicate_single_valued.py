#!/usr/bin/env python3
"""Collapse duplicated single-valued properties to one value per subject.

WHAT IS WRONG
    Several properties the KG layer treats as single-valued — the two object
    timestamps and the text, datetime and integer slot values — have subjects
    carrying two or more values. The object layer
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

V = "http://vital.ai/ontology/vital"
H = "http://vital.ai/ontology/haley-ai-kg#"

# (predicate URI, SQL ORDER BY over t.term_text, human description). Row 1 of the
# ordering survives; the rest are removed.
#
# THE RULE COMES FROM WHAT THE PROPERTY MEANS, and only the first two get it for
# free. A creation time is the earliest stamp and a modification time the latest,
# because that is what those words denote — the value is derivable, not chosen.
#
# The slot values have no such derivation. Two text values on one slot are both
# plausible edits of the same message, nothing stored orders them (quads carry no
# insertion time, the frame's modification time cannot separate two values on the
# SAME slot, term UUIDs are content hashes, and `ctid` disagrees with itself
# across samples and is meaningless after a VACUUM anyway). The rules below are
# therefore a DECISION, taken deliberately on old data judged not worth manual
# review, not a fact recovered from the data:
#
#   text     -> longest    (proxy for the more complete edit)
#   datetime -> newest
#   integer  -> largest
#
# Recorded here because a future reader will otherwise assume these were derived
# the way the timestamps were. At least one sampled pair shows the rule picking
# the arguably wrong value — a shorter text that fixed a grammatical error in a
# longer one — which is the accepted cost of not reviewing 374 rows by hand.
TARGETS = [
    (f"{V}-aimp#hasObjectCreationTime", "t.term_text ASC", "earliest"),
    (f"{V}#hasObjectModificationDateTime", "t.term_text DESC", "latest"),
    # length first, then the text itself so equal-length values resolve
    # deterministically instead of by whatever order the scan returns.
    (f"{H}hasTextSlotValue", "length(t.term_text) DESC, t.term_text DESC", "longest"),
    (f"{H}hasDateTimeSlotValue", "t.term_text DESC", "newest"),
    # Cast, do not sort as text: '9' sorts above '10' lexically. Non-numeric
    # text sorts last rather than raising, so one malformed value cannot fail
    # the run for every other subject.
    (f"{H}hasIntegerSlotValue",
     "(CASE WHEN t.term_text ~ '^-?[0-9]+$' THEN t.term_text::numeric END) "
     "DESC NULLS LAST, t.term_text DESC", "largest"),
]


async def _predicate_uuid(conn, space_id: str, uri: str):
    return await conn.fetchval(
        f"SELECT term_uuid FROM {space_id}_term "
        f"WHERE term_text = $1 AND term_type = 'U' LIMIT 1", uri)


async def _graph_uuid(conn, space_id: str, graph_uri: str):
    return await conn.fetchval(
        f"SELECT term_uuid FROM {space_id}_term "
        f"WHERE term_text = $1 AND term_type = 'U' LIMIT 1", graph_uri)


def _victims_sql(space_id: str, order_by: str) -> str:
    """Rows to remove: every value but the one that survives, per subject.

    Ordered by the TERM TEXT rather than by anything in the quad row, because the
    quad table carries no column expressing the value's order — no insertion
    time, and `ctid` is physical placement rather than history.
    """
    return f"""
        SELECT subject_uuid, object_uuid FROM (
            SELECT q.subject_uuid, q.object_uuid,
                   row_number() OVER (PARTITION BY q.subject_uuid
                                      ORDER BY {order_by}) AS rn
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
    for uri, order_by, rule in TARGETS:
        p_uuid = await _predicate_uuid(conn, space_id, uri)
        if p_uuid is None:
            logger.info("  %-62s not present in this space", uri.rsplit('#', 1)[-1])
            continue

        rows = await conn.fetch(_victims_sql(space_id, order_by), p_uuid, g_uuid)
        subjects = len({r["subject_uuid"] for r in rows})
        logger.info("  %-32s %5d redundant row(s) across %4d subject(s) — keeping %s",
                    uri.rsplit('#', 1)[-1], len(rows), subjects, rule)
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
