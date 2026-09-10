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
            # An empty table may mean "never built" or may mean "this space has
            # no frames". Build it once; if it is still empty afterwards the
            # space genuinely has none, and the collapse stays off — which costs
            # nothing, because there is nothing to collapse.
            if conn is not None:
                from .sync_frame_slot_table import resync_frame_slot_table
                built = await resync_frame_slot_table(conn, space_id)
                populated = built > 0
                logger.info("ensure_frame_slot_table(%s): populated %d row(s)",
                            space_id, built)

        _frame_slot_ready[space_id] = populated
        return populated
    except Exception as exc:
        logger.debug("ensure_frame_slot_table(%s): %s", space_id, exc)
        _frame_slot_ready[space_id] = False
        return False
