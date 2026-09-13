"""Compute `{space}_entity_fanout`: how wide a traversal gets from one entity.

AN OPERATOR DIAGNOSTIC. NOT A QUERY-PATH INPUT. Decided 2026-08-15.
NO LONGER POPULATED AUTOMATICALLY. Decided 2026-09-13.
===================================================================
Nothing calls this on any automatic path any more. `resync_all` no longer
rebuilds the table and `repair_derived_tables` no longer repairs it — not even
the probe that decided whether to, which was the same self-join again and so
carried most of the cost while producing no result.

The reason is below and unchanged in substance: nothing reads the table, and
both uses it was kept for have now been measured and rejected. The rebuild was
therefore pure cost, and it scales with `frame_slot` — measured 1.21 s at 91k
rows, 2.51 s at 571k, 4.09 s at 947k, as a self-join with a count(DISTINCT).

The TABLE and this FUNCTION both remain. An operator who wants the hub list can
still call `resync_entity_fanout` deliberately, which is what the diagnostic was
always for; what has gone is paying for it on every resync whether anyone wants
it or not. Existing rows are left alone rather than dropped, so a space that has
one keeps it until something rebuilds or removes it.

Do not confuse this with `edge_fanout`, which looks like a sibling and is not:
`generator.py` loads it on every query and `emit_slice` reads it for the
traversal-direction gate. That one is maintained and must stay.
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

  * **Choosing traversal DIRECTION: MEASURED 2026-09-13, no value found.**
    This used to read "unavailable, not untested — `emit_hop_wise` declines tail
    pins outright, so no reverse BGP walk exists", and said this became the
    first real candidate consumer if reverse traversal were ever implemented.
    IT WAS, TWO DAYS LATER: `f7f2af46` (2026-08-17) made `emit_hop_wise` honour
    `choose_direction` by reversing the chain, and this note was never revisited.

    Measured on the shape where direction is genuinely live — general
    `node -edge-> node` traversal with a numeric criterion on `sp_graph_rel_10k`,
    which emits hop-wise; a frame walk cannot be used because hop-wise is gated
    off for `frame_slot` shapes, and without a criterion both alternatives
    decline for reasons unrelated to direction. Warm, median of 7, each query
    generated twice with the direction forced:

        depth  constrained  head_ms  tail_ms  faster  rule picked
        2      head           261.3    152.1  tail    head   WRONG
        2      tail           215.8    363.5  head    tail   WRONG
        3      head           404.8    515.3  head    head   right
        3      tail           172.0    321.5  head    tail   WRONG

    Two findings, and only the first is about this table.

    **This table cannot help.** The ends of these queries are kind-constrained
    SETS, not individual entities, and per-entity hub data has to be aggregated
    by kind to say anything: totalled that way it is near-uniform (avg fan-out
    49.1 to 62.3 across the five kinds), so the rule reduces to "which set is
    smaller" — which is what the pair counts already measure, and which is the
    answer being got wrong above.

    **The direction rule itself is wrong 3 of 4 here**, and not because its
    statistics are poor: it is not COMPARING the ends. Only the constrained end
    is priceable, so `choose_direction` takes its one-knowable-end branch and
    drives from it. `edge_fanout` — the table actually built for this, keyed on
    (edge type, relation type, direction) — does carry the asymmetry, forward
    2.18-2.21 avg against backward 2.32-2.36, max 68-71 against 91-98, pointing
    at "head", which matches 3 of the 4 measurements.

    That is NOT evidence `edge_fanout` works. Its signal is CONSTANT across
    every case testable here — forward is cheaper for all three relation types —
    so it cannot be told apart from "head happens to win on this graph". Four
    queries on one synthetic dataset. Confirming it needs a graph where backward
    is the cheaper direction, to check the signal FLIPS; fitting a rule to this
    would be the same mistake as the hub rule rejected above.

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

# `frame_entity` named two roles in its COLUMNS, and "forward" meant
# source_entity -> dest_entity. `frame_slot` carries the role as DATA
# (`issues/183`), so that direction no longer exists: the table records which
# entity fills which slot of which frame, and which of two roles counts as
# "forward" is a per-dataset question this module must not answer.
#
# The co-frame relation is SYMMETRIC — if A and B fill slots of one frame, A
# reaches B and B reaches A — so both directions are written with the same
# value rather than inventing an asymmetry. The column stays because the schema
# constrains it and because a future dataset-aware consumer may want it back.
_DIRECTIONS = ("forward", "backward")


async def resync_entity_fanout(conn, space_id: str,
                               top_n: int = TOP_N_DEFAULT,
                               min_fanout: int = MIN_FANOUT_DEFAULT) -> Dict[str, int]:
    """Rebuild the hub list from `frame_slot`. Returns rows written per direction.

    DISTINCT neighbours, not edge count: two frames connecting the same pair of
    entities are one step of a walk, not two, and it is the walk this exists to
    describe.
    """
    t_fe = f"{space_id}_entity_fanout"
    t_src = f"{space_id}_frame_slot"

    exists = await conn.fetchval(
        "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1", t_fe)
    if not exists:
        logger.info("resync_entity_fanout(%s): no %s table, skipping",
                    space_id, t_fe)
        return {}

    await conn.execute(f"TRUNCATE {t_fe}")
    written: Dict[str, int] = {}
    for direction in _DIRECTIONS:
        # A SELF-JOIN on the frame, where `frame_entity` had both ends on one
        # row. `IS DISTINCT FROM` rather than `<>` so a NULL-valued slot cannot
        # silently drop a neighbour, and DISTINCT neighbours rather than slot
        # count: two slots naming the same entity are one step of a walk.
        result = await conn.execute(f"""
            INSERT INTO {t_fe} (entity_uuid, context_uuid, direction, fanout)
            SELECT entity_uuid, context_uuid, $1, n FROM (
                SELECT a.entity_uuid, a.context_uuid,
                       count(DISTINCT b.entity_uuid) AS n
                FROM {t_src} a
                JOIN {t_src} b
                  ON b.frame_uuid = a.frame_uuid
                 AND b.context_uuid = a.context_uuid
                 AND b.entity_uuid IS DISTINCT FROM a.entity_uuid
                WHERE a.entity_uuid IS NOT NULL AND b.entity_uuid IS NOT NULL
                GROUP BY a.entity_uuid, a.context_uuid
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
