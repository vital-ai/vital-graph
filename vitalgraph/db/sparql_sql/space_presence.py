"""Is this space's schema still there?

Background work outlives the space it was queued for. A periodic probe or a
scheduled task picks a space id, the space is dropped a moment later, and the
work then runs against a schema that has gone — logging a wall of
`relation "…" does not exist`, once per table, per space, per cycle.

**It is not only noise.** PostgreSQL records every failed statement server-side
even though the client swallows the error, so the cost lands in the database log
as well as ours; `vectorization.auto_sync` names that explicitly as the reason it
checks before doing any work.

THREE CALLERS, ONE QUESTION. `auto_sync` asked it first and privately. The
maintenance job's referential sweep and the server-property backfill ask the same
thing and did not, which is how a routine API-suite teardown produced
`relation "apitest_…_frame_slot" does not exist` in production-shaped logs
(`issues/253`). One implementation so the next periodic job inherits the answer
rather than rediscovering the symptom.

WHY `rdf_quad` AND NOT THE `space` ROW. The row and the tables are dropped by one
transaction but a caller may hold either half: a space whose row is gone still has
tables to sweep, and a space whose tables are gone has nothing to do whatever the
catalogue says. The work is on the TABLES, so that is what is checked.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__all__ = ["space_tables_present"]


async def space_tables_present(conn, space_id: str) -> bool:
    """True if *space_id*'s quad table still exists.

    One catalogue lookup via `to_regclass`, which returns NULL rather than
    raising for a missing relation — so this cannot itself become the failed
    statement it exists to prevent.
    """
    try:
        return bool(await conn.fetchval(
            "SELECT to_regclass($1) IS NOT NULL", f"{space_id}_rdf_quad"))
    except Exception as e:                   # pragma: no cover - defensive
        # A broken connection is not an answer to "does this space exist", and
        # guessing either way would be worse than letting the caller proceed and
        # fail on its own terms.
        logger.debug("space_tables_present(%s) could not be checked: %s",
                     space_id, e)
        return True
