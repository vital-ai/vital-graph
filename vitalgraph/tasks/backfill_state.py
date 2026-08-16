"""Completion markers, so a finished space stops paying to prove it is finished.

`backfill_entity_server_properties_sql` answers "is anything missing?" by
scanning every KGEntity in the graph with four correlated `NOT EXISTS`. Proving
a space is DONE therefore costs the same as finding work in it. Measured
2026-08-13, all three fully backfilled:

    sp_lead_synth_100k      2,593.1 ms     0 missing
    prod_kg                 30.8 ms     0 missing
    kg_load_test                0.9 ms     0 missing

It scales with entity count, so the largest spaces are the most expensive to
prove idle — every safety-net cycle, forever. Same family as `issues/079`:
bounded on work DONE, unbounded on work EXAMINED, with the healthy case being
the common one.

THE INVALIDATION SIGNAL HAS TO BE FREE, or this trades one scan for another.
`pg_stat_user_tables.n_tup_ins` for the space's `rdf_quad` is a counter
PostgreSQL maintains anyway: record it when a graph completes, and if it has not
moved, nothing was inserted and the scan can be skipped without touching the
data.

**Paired with `pg_stat_database.stats_reset`, and checking real values is why.**
Observed on this database:

    sp_lead_synth_100k_rdf_quad   n_tup_ins 101,140,000   n_live_tup 50,570,042
    kg_load_test_rdf_quad         n_tup_ins           0   n_live_tup      6,550

A populated table reporting ZERO inserts — the counter is since the last
statistics reset, not for all time. "Counter went backwards" catches the obvious
case but not this one: reset to 0, re-insert back to exactly the recorded value,
and the space looks untouched when it is not. Recording `stats_reset` alongside
makes reset detection exact rather than inferred.

DEFENCE IN DEPTH, because a skipped backfill is silent:

* a nudge forces a full check, ignoring markers entirely — the caller told us
  data arrived, and the statistics view lags commits by design;
* a marker older than `recheck_after_s` (default 24 h) is ignored, so a missed
  signal self-heals within a day rather than never;
* every failure path returns "not complete", which costs a scan and never skips
  one. The table may not exist on an older install — `backfill_state` is created
  by the explicit schema path, not implicitly — and that must degrade to today's
  behaviour, not to a backfill that silently stops running.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# A marker older than this is ignored and the graph re-checked, so a missed
# invalidation self-heals. One day: long enough that the saving is real, short
# enough that a silently-unstamped space is found before anyone relies on it.
DEFAULT_RECHECK_AFTER_S = 86_400.0


async def quad_activity(pool, space_id: str) -> Tuple[Optional[int], Optional[object]]:
    """`(n_tup_ins, stats_reset)` for the space's quad table.

    Both may be None — a table PostgreSQL has no statistics for yet, or a
    database whose `stats_reset` has never been set. None is not an error; it is
    handled by the comparison, which treats "cannot tell" as "re-check".
    """
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT (SELECT n_tup_ins FROM pg_stat_user_tables
                         WHERE relname = $1) AS n_tup_ins,
                       (SELECT stats_reset FROM pg_stat_database
                         WHERE datname = current_database()) AS stats_reset
                """,
                f"{space_id}_rdf_quad")
        if row is None:
            return None, None
        return row["n_tup_ins"], row["stats_reset"]
    except Exception as e:
        logger.debug("backfill_state: could not read quad activity for %s: %s",
                     space_id, e)
        return None, None


async def is_complete(pool, space_id: str, graph_uri: str,
                      recheck_after_s: float = DEFAULT_RECHECK_AFTER_S) -> bool:
    """True only when this graph is marked done AND nothing has changed since.

    Every uncertain answer is False. Skipping a graph that needs work leaves
    entities permanently unstamped, which is the failure the backfill exists to
    prevent; scanning one that does not need it costs a few seconds.
    """
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT quad_inserts, stats_reset,
                       EXTRACT(EPOCH FROM (NOW() - completed_at)) AS age_s
                FROM backfill_state
                WHERE space_id = $1 AND graph_uri = $2
                """,
                space_id, graph_uri)
    except Exception as e:
        # Most likely the table does not exist on this install. Behave exactly
        # as before markers existed.
        logger.debug("backfill_state: lookup failed for %s/%s: %s",
                     space_id, graph_uri, e)
        return False

    if row is None:
        return False
    if row["age_s"] is None or float(row["age_s"]) > recheck_after_s:
        return False

    now_inserts, now_reset = await quad_activity(pool, space_id)

    # Statistics were reset since the mark was taken: the counter is no longer
    # comparable to the recorded one, whatever it reads.
    if row["stats_reset"] != now_reset:
        return False
    # Cannot read the counter now, or none was recorded: no basis to skip.
    if now_inserts is None or row["quad_inserts"] is None:
        return False
    # Anything other than "unchanged" — including a decrease, which should not
    # happen — is a reason to look.
    return int(now_inserts) == int(row["quad_inserts"])


async def mark_complete(pool, space_id: str, graph_uri: str) -> bool:
    """Record that this graph has no work, with the activity counter it had.

    Returns False if the marker could not be stored, which simply means the next
    cycle scans again.
    """
    inserts, reset = await quad_activity(pool, space_id)
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO backfill_state
                    (space_id, graph_uri, completed_at, quad_inserts, stats_reset)
                VALUES ($1, $2, NOW(), $3, $4)
                ON CONFLICT (space_id, graph_uri) DO UPDATE
                    SET completed_at = NOW(),
                        quad_inserts = EXCLUDED.quad_inserts,
                        stats_reset  = EXCLUDED.stats_reset
                """,
                space_id, graph_uri, inserts, reset)
        return True
    except Exception as e:
        logger.debug("backfill_state: could not mark %s/%s complete: %s",
                     space_id, graph_uri, e)
        return False


async def clear(pool, space_id: Optional[str] = None) -> int:
    """Drop markers, for one space or all. Returns rows removed (0 on failure).

    Not used by the nudge path — a nudge sets a force flag instead, which is
    cheaper and does not lose the counters. This exists for operators and tests.
    """
    try:
        async with pool.acquire() as conn:
            if space_id:
                res = await conn.execute(
                    "DELETE FROM backfill_state WHERE space_id = $1", space_id)
            else:
                res = await conn.execute("DELETE FROM backfill_state")
        return int(res.split()[-1]) if res else 0
    except Exception as e:
        logger.debug("backfill_state: clear failed: %s", e)
        return 0
