"""Compute `{space}_entity_fanout`: how wide a traversal gets from one entity.

AN OPERATOR DIAGNOSTIC. NOT A QUERY-PATH INPUT. Decided 2026-08-15.
===================================================================
Nothing in the SQL pipeline reads this table and nothing should start to
without new evidence. It exists to answer an operator's question — "why is this
query slow" answered by "the start entity has out-degree 432" — and it is kept
because that question keeps coming up, not because a planner needs it.

Read this before wiring it into a decision, because the obvious use was already
tried and measured:

  * **Choosing the emission shape by the start's fan-out: TESTED AND REJECTED.**
    The hypothesis was that dedup loses at hubs, since the one recorded loss was
    a hub start. Measured with the statistic live, 3 criteria x depths 2-3 x 5
    starts, of which exactly one is a hub at fan-out 432: **dedup wins 5 of the
    6 hub cases.** The single loss needs hub AND depth 2 AND a highly selective
    criterion — a three-way conjunction on one data point, which is a rule
    fitted to noise. See `traversal_chain_plan.md` GAP 7b for the table.

  * **Choosing traversal DIRECTION: unavailable, not untested.** A per-entity
    forward/backward split is exactly what a direction choice would want, and
    there is no direction to choose: `emit_hop_wise` declines tail pins
    outright, so no reverse BGP walk exists. (`emit_path` gained a reverse
    recursion in `6a83ebe`, but that is the property-path emitter and it does
    not consult this table.) If reverse BGP traversal is ever implemented, this
    becomes the first real candidate consumer and should be measured then.

So: query it from a shell, put it in an operator report, use it to explain a
slow query. Do not branch on it in the planner without a measurement that
beats those two.


The statistic nothing else expresses. `edge_fanout` is keyed on
`(edge type, relation type, direction)` and is an aggregate over the whole
space — built to choose a traversal DIRECTION, where a per-type average is the
right granularity. It cannot say anything about a particular start entity, and
every traversal question left open in `traversal_chain_plan.md` comes back to
the same quantity: *how wide does the walk get from THIS entity?*

  * GAP 7 — `score >= 50` loses to the path-wise form from one start and wins
    from four others. The criterion is identical; the start is not.
  * The criterion gate (GAP 6) refuses unfiltered walks wholesale because it
    cannot tell a hub from a leaf.
  * Whether materialising a whole walk is acceptable depends on how wide it is.

WHY A LIST, NOT A ROW PER ENTITY

The distribution is scale-free and only the tail costs anything. Measured:

    fixture      entities   fanout >= 100        mean   p99   max
    wordnet       109,734        80  (0.073%)    2.60    20   671
    synth_100k    100,000        39  (0.039%)    3.86    21   432

So the top N captures the entire cost profile in hundreds of rows rather than
millions, and an entity ABSENT from the list is by construction not a hub. A row
per entity would be the wrong shape: millions of rows, an index to maintain, and
almost all of it describing entities whose fan-out never changes a decision.

FRESHNESS: A PERIODIC REBUILD, AND NOTHING ELSE

No incremental path and no drift detector, which makes this the cheapest
statistic here to keep correct rather than the most expensive. Two reasons:

  * **Advisory and fail-safe.** A hub missing from the list yields the behaviour
    the pipeline has today — the status quo, never a regression. Every other
    statistic actively misleads when stale: a wrong `rdf_stats` count sends the
    planner to the wrong join order, a stale histogram displaces an accurate
    count (`stats_table_freshness_plan.md`). This one can only ever withhold an
    improvement.
  * **Churn at the boundary cannot matter.** p99 fan-out is 20 while a hub is
    100+, so an entity crossing the threshold is nowhere near where any decision
    flips. The common write — two neighbours becoming three — cannot change
    anything. Membership changing and the DECISION changing are different, and
    conflating them is what first made this look hard to maintain.

Rebuild cost, measured on the real resync rather than on a single GROUP BY:

    sp_graph_synth_10k      254 ms      68 forward hubs,  110 backward
    wordnet_frames        1,377 ms     746 forward,       749 backward
    sp_graph_synth_100k   2,330 ms     743 forward,       927 backward

An earlier estimate of ~190 ms came from timing one `GROUP BY ... HAVING` and
omitted the second direction, the TRUNCATE and the ANALYZE. Seconds, not
hundreds of milliseconds — still comfortably a periodic task, but worth stating
as measured rather than as projected.

NOT CONSUMED BY THE QUERY PATH, deliberately — see the header. Landing it inert
is what allowed the emission-choice hypothesis to be tested against real spaces
before anything depended on it, and that test is the reason it is still inert.
"""

from __future__ import annotations

import logging
from typing import Dict

logger = logging.getLogger(__name__)

# How many hubs to keep, per direction. Bounded regardless of space size, which
# is the point — the table must not scale with the entity count.
TOP_N_DEFAULT = 1000

# Below this, an entity is not a hub in any useful sense and storing it only
# adds rows. p99 is ~20 on both fixtures, so this sits comfortably above the
# body of the distribution and below the tail that matters.
MIN_FANOUT_DEFAULT = 25

_DIRECTIONS = {
    # direction -> (the column a walk starts FROM, the column it arrives at)
    "forward": ("source_entity_uuid", "dest_entity_uuid"),
    "backward": ("dest_entity_uuid", "source_entity_uuid"),
}


async def resync_entity_fanout(conn, space_id: str,
                               top_n: int = TOP_N_DEFAULT,
                               min_fanout: int = MIN_FANOUT_DEFAULT) -> Dict[str, int]:
    """Rebuild the hub list from `frame_entity`. Returns rows written per direction.

    DISTINCT neighbours, not edge count: two frames connecting the same pair of
    entities are one step of a walk, not two, and it is the walk this exists to
    describe.
    """
    t_fe = f"{space_id}_entity_fanout"
    t_src = f"{space_id}_frame_entity"

    exists = await conn.fetchval(
        "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1", t_fe)
    if not exists:
        logger.info("resync_entity_fanout(%s): no %s table, skipping",
                    space_id, t_fe)
        return {}

    await conn.execute(f"TRUNCATE {t_fe}")
    written: Dict[str, int] = {}
    for direction, (from_col, to_col) in _DIRECTIONS.items():
        result = await conn.execute(f"""
            INSERT INTO {t_fe} (entity_uuid, context_uuid, direction, fanout)
            SELECT {from_col}, context_uuid, $1, n FROM (
                SELECT {from_col}, context_uuid,
                       count(DISTINCT {to_col}) AS n
                FROM {t_src}
                WHERE {from_col} IS NOT NULL AND {to_col} IS NOT NULL
                GROUP BY {from_col}, context_uuid
            ) d
            WHERE n >= $2
            ORDER BY n DESC
            LIMIT {int(top_n)}
        """, direction, int(min_fanout))
        written[direction] = int(result.split()[-1]) if result else 0

    await conn.execute(f"ANALYZE {t_fe}")
    logger.info("resync_entity_fanout(%s): %s hubs (>= %d neighbours, top %d)",
                space_id, written, min_fanout, top_n)
    return written


async def entity_fanout(conn, space_id: str, entity_uuid, direction: str = "forward"):
    """This entity's fan-out, or None if it is not a recorded hub.

    For operators and diagnostics — see the module header before calling this
    from anything that decides a plan.

    None means "not a hub", which is the answer for all but a few hundred
    entities and is why the table stays small. It does NOT mean "unknown" — a
    caller may treat None as "small" here, unlike every other statistic in this
    package, because absence from the list is a positive statement.
    """
    t_fe = f"{space_id}_entity_fanout"
    try:
        return await conn.fetchval(
            f"SELECT max(fanout) FROM {t_fe} "
            f"WHERE entity_uuid = $1 AND direction = $2", entity_uuid, direction)
    except Exception as exc:
        logger.debug("entity_fanout(%s) unavailable: %s", space_id, exc)
        return None
