"""Is `{space}_frame_slot` present and populated, so the rewrite may use it?

The frame-slot collapse emits joins against this table. If it is absent or
empty the joins match nothing and the query returns ZERO rows — silently, and
with a plan that looks fine. So the rewrite must be gated on this, exactly as
the frame-entity collapse is gated on `ensure_frame_entity_table`.

The table is NOT created here. Schema is created by an explicit action — the
space manager, or `scripts/migrate_frame_slot_table.py` — never as a side effect
of a read. `ensure_edge_table` records what happened the last time a read path
created a table: two sources for one schema, and the inline copy silently
missing a column the real DDL had.

Populating an EMPTY table is different from creating one, and is allowed here
for the same reason the neighbouring ensure paths allow it: an empty derived
table is indistinguishable from a table nobody has built yet, and the cost is
bounded by the space.
"""

from __future__ import annotations

import logging
from typing import Dict

logger = logging.getLogger(__name__)

_frame_slot_ready: Dict[str, bool] = {}


def reset_ready_cache() -> None:
    _frame_slot_ready.clear()


async def ensure_frame_slot_table(space_id: str, conn=None,
                                  conn_params=None) -> bool:
    """True when the table exists and holds rows, so the rewrite may fire."""
    if _frame_slot_ready.get(space_id):
        return True
    if conn is None and conn_params is None:
        return False

    from . import db_provider as db

    table_name = f"{space_id}_frame_slot"
    try:
        exists = await db.execute_query(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = %s",
            params=(table_name,), conn=conn, conn_params=conn_params)
        if not exists:
            logger.debug(
                "ensure_frame_slot_table(%s): %s absent — the frame-slot "
                "collapse is disabled for this space until "
                "`python scripts/migrate_frame_slot_table.py --space %s "
                "--apply` has run",
                space_id, table_name, space_id)
            _frame_slot_ready[space_id] = False
            return False

        rows = await db.execute_query(
            f"SELECT EXISTS (SELECT 1 FROM {table_name}) AS present",
            conn=conn, conn_params=conn_params)
        populated = bool(rows and rows[0]["present"])

        if not populated:
            # DECLINE. Never rebuild here.
            #
            # This used to call `resync_frame_slot_table` inline, to tell
            # "never built" apart from "this space has no frames". That is a
            # TRUNCATE plus a full rebuild — on the QUERY PATH, paid by whoever
            # asked first, holding ACCESS EXCLUSIVE while every other reader
            # waits. On a space the size of the one this was measured against
            # that is 570,696 rows and ~9 s; it scales with the space.
            #
            # It is also unnecessary now, twice over:
            #
            #   * `frame_slot_drift` gets the same answer CHEAPLY — it computes
            #     the expected count from the edge table, so `expected > 0` with
            #     `actual == 0` means "never built" and `expected == 0` means
            #     "no frames here", with no rebuild.
            #   * the maintenance tick backfills the worst-drifted space with
            #     `backfill_frame_slot_table`, which is non-blocking
            #     (`INSERT ... ON CONFLICT DO NOTHING`, ROW EXCLUSIVE). A
            #     never-built table is maximally drifted, so it is exactly what
            #     that step picks up.
            #
            # Declining costs correctness nothing: the rewrite falls back to the
            # quad joins, which is the answer it would give on a space that has
            # no `frame_slot` at all. It is slower until maintenance runs, and
            # slower is not an outage.
            logger.warning(
                "ensure_frame_slot_table(%s): %s exists but is EMPTY — the "
                "frame-slot collapse is disabled for this space until it is "
                "populated. The maintenance backfill will do it, or run "
                "`python scripts/migrate_frame_slot_table.py --space %s "
                "--apply` to do it now. NOT rebuilding here: that is a "
                "TRUNCATE on the query path.",
                space_id, table_name, space_id)

        _frame_slot_ready[space_id] = populated
        return populated
    except Exception as exc:
        logger.debug("ensure_frame_slot_table(%s): %s", space_id, exc)
        _frame_slot_ready[space_id] = False
        return False
