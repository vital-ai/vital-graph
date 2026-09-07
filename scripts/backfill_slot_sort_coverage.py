#!/usr/bin/env python3
"""Drive entity_slot_sort to COMPLETE and record the coverage marker.

`issues/161`. The FILTER fast path is gated on a per-(space, entity type) marker
saying `{space}_entity_slot_sort` is known complete. Without it the path
declines and the query is served by the general SPARQL plan — correct, and
measured at >90s against ~20ms on a 53.4M-quad space.

THE DEPLOY-TIME COUNTERPART TO THE STEADY-STATE JOB. `maintenance_job` repairs
ONE BOUNDED BATCH per cycle on purpose: a full backfill is not something a
periodic job should attempt while serving reads (`issues/150` measured 216-303s
per full walk at a 54% duty cycle). That is right for steady state and wrong for
a deploy, where a freshly migrated space would converge over an unknown number
of cycles with the fast path off throughout. This drives the same batch function
to completion, deliberately, in the foreground, where an operator is watching.

IT USES THE SAME FUNCTIONS AS THE JOB. `backfill_entity_slot_sort_batch` to
fill, `entity_slot_sort_all_types` to measure, `record_slot_sort_coverage` to
write. Not a second implementation of the derivation — a different schedule for
the same one, so the two cannot disagree about what a covered space is.

TERMINATION is on `selected == 0`, which the batch function documents as "this
type is DONE, nothing left that is absent". `--max-batches` bounds a run that
is not converging rather than letting it spin.

    python scripts/backfill_slot_sort_coverage.py --space my_space
    python scripts/backfill_slot_sort_coverage.py --all --dry-run
    python scripts/backfill_slot_sort_coverage.py --space my_space --record-only
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
from vitalgraph.db.sparql_sql.fast_slot_filter import (  # noqa: E402
    record_slot_sort_coverage,
)
from vitalgraph.db.sparql_sql.sync_entity_slot_sort import (  # noqa: E402
    backfill_entity_slot_sort_batch,
    entity_slot_sort_all_types,
)

logger = logging.getLogger("backfill_slot_sort_coverage")


async def _types(conn, space_id: str):
    """Per-type coverage as the maintenance probe sees it."""
    return await entity_slot_sort_all_types(conn, space_id)


async def process_space(conn, space_id: str, *, dry_run: bool,
                        record_only: bool, max_batches: int,
                        batch_size: int | None) -> dict:
    try:
        before = await _types(conn, space_id)
    except Exception as exc:
        return {"space": space_id, "status": f"no slot-sort table ({exc})"}
    if not before:
        return {"space": space_id, "status": "no KG entity types"}

    short = [c for c in before if c["in_table"] < c["of_type"]]
    if dry_run:
        return {"space": space_id, "status": "dry-run", "types": len(before),
                "short": len(short),
                "missing": sum(c["of_type"] - c["in_table"] for c in short)}

    filled = 0
    if not record_only:
        for cov in short:
            batches = 0
            while batches < max_batches:
                selected, inserted = await backfill_entity_slot_sort_batch(
                    conn, space_id, cov["entity_type_uuid"],
                    batch_size=batch_size)
                batches += 1
                filled += inserted
                # `selected == 0` is the documented "this type is DONE" signal.
                # `inserted == 0` with entities selected means those entities
                # derive no rows at all -- real, and it would spin forever.
                if selected == 0 or inserted == 0:
                    break
            else:
                logger.warning(
                    "  %s: hit --max-batches (%d) with work outstanding; "
                    "re-run to continue", space_id, max_batches)

    # RECORDED WHETHER OR NOT ANYTHING WAS FILLED. A space already complete
    # simply has no marker yet -- which is the exact state that made
    # lead_nurture_100k time out with a correct table underneath it.
    after = await _types(conn, space_id)
    complete = 0
    for cov in after:
        await record_slot_sort_coverage(conn, space_id, cov["entity_type_uuid"],
                                        cov["in_table"], cov["of_type"])
        if cov["in_table"] >= cov["of_type"]:
            complete += 1

    # RELEASE THE WHOLE-SPACE BLOCK. Nothing else does, and without this the
    # fast path stays off forever.
    #
    # `record_slot_sort_coverage` releases only the PER-TYPE block for a type it
    # just measured complete. `migrate_slot_sort_blocks` seeds a WHOLE-SPACE
    # block (`entity_type_uuid IS NULL`) for a space with no coverage rows —
    # which is every space at upgrade — and `slot_sort_is_blocked` matches
    # `entity_type_uuid IS NULL OR entity_type_uuid = $2`, so that one block
    # declines every type regardless of how complete they measure.
    #
    # Before this, the only code that released a whole-space block was
    # `resync_all`, which takes one itself. A block seeded by the migration had
    # NO releaser: this script would measure everything, report `fast_path: ON`,
    # and the fast path would still be off. Found on a production deploy, where
    # the shape stayed at a 60 s timeout after a run that reported success —
    # and not found here, because both local stacks already had per-type
    # coverage rows, so the migration seeded per-type blocks rather than
    # whole-space ones.
    #
    # RELEASED ON HAVING MEASURED, not on everything being complete. The block's
    # reason is "coverage never measured"; once measured that is false whatever
    # the result. A type that measures SHORT keeps its own per-type block, taken
    # by `record_slot_sort_coverage` above, so releasing the space-wide one does
    # not serve anything short.
    released_space_block = False
    if after:
        from vitalgraph.db.sparql_sql.fast_slot_filter import (
            release_slot_sort_block)
        held = await conn.fetchval(
            "SELECT 1 FROM slot_sort_block"
            " WHERE space_id = $1 AND entity_type_uuid IS NULL", space_id)
        if held:
            await release_slot_sort_block(conn, space_id, None)
            released_space_block = True

    # `fast_path` reports whether a query can actually be served, which needs
    # BOTH a complete type and no whole-space block still standing.
    still_blocked = await conn.fetchval(
        "SELECT count(*) FROM slot_sort_block WHERE space_id = $1"
        "   AND entity_type_uuid IS NULL", space_id)
    return {"space": space_id, "status": "ok", "types": len(after),
            "complete": complete, "rows_added": filled,
            "space_block_released": released_space_block,
            "fast_path": "ON" if (complete and not still_blocked) else "OFF"}


async def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--space")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what is short; change nothing")
    ap.add_argument("--record-only", action="store_true",
                    help="skip the backfill, just measure and record the marker")
    ap.add_argument("--max-batches", type=int, default=10_000)
    ap.add_argument("--batch-size", type=int, default=None)
    add_pg_arguments(ap)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(f"\U0001F5C4  target: {describe_target(args)}", flush=True)

    import asyncpg
    conn = await asyncpg.connect(host=args.host, port=args.port,
                                 database=args.database, user=args.user,
                                 password=args.password or None)
    try:
        if args.all:
            spaces = [r[0] for r in await conn.fetch(
                "SELECT replace(tablename,'_entity_slot_sort','') FROM pg_tables "
                "WHERE schemaname='public' "
                "AND tablename LIKE '%\\_entity\\_slot\\_sort' ORDER BY 1")]
        else:
            spaces = [args.space]
        off = 0
        for sp in spaces:
            t0 = time.monotonic()
            res = await process_space(
                conn, sp, dry_run=args.dry_run, record_only=args.record_only,
                max_batches=args.max_batches, batch_size=args.batch_size)
            res["seconds"] = round(time.monotonic() - t0, 1)
            if res.get("fast_path") == "OFF":
                off += 1
            logger.info("  %s", res)
        if off:
            # Named loudly: the run SUCCEEDED and the fast path is still off,
            # which is the combination that otherwise goes unnoticed.
            logger.warning(
                "\n%d space(s) still have NO complete entity type — the FILTER "
                "fast path stays OFF for them and their criteria queries will "
                "be served by the general SPARQL path.", off)
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
