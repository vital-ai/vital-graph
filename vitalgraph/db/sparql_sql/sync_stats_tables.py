"""Incremental and full sync for the {space}_rdf_pred_stats and {space}_rdf_stats tables.

These tables drive the join reorder heuristic in the v2 SPARQL-to-SQL
generator.  They must stay fresh as data changes through the REST API.

Incremental functions accept an asyncpg connection already inside a
transaction.  The resync function can be called standalone.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

# The join-reorder loader (generator._load_quad_stats) reads every stored pair —
# there is no upper bound on row_count and no LIMIT, because the pairs it most
# needs to price are the largest ones. What bounds the table is the recompute's
# own `keep_top_n`: at 1B quads the row_count=1 singletons alone would reach
# 50-200M rows, which is why STATS_MIN_ROW_COUNT exists and why 85-94% of all
# pairs are never stored.
STATS_MIN_ROW_COUNT = 2
# Pairs kept per rebuild, fairness-ordered across predicates. Sized so the
# reader's whole-table load stays cheap: measured at 38-54 ms against 1.8-2.1 s
# for an uncapped table on a 50M-quad space.
STATS_KEEP_DEFAULT = 50_000

def absence_bounds(quad_stats, pred_stats=None) -> Dict:
    """Per predicate, the size to assume for a pair that is NOT stored.

    `issues/153`. `recompute_stats_tables` keeps each predicate's LARGEST pairs,
    fairness-ordered, so absence is an UPPER bound rather than a mystery:

      * predicate NOT cut -- every pair with `count(*) >= STATS_MIN_ROW_COUNT`
        is stored, so an absent pair holds at most STATS_MIN_ROW_COUNT - 1;
      * predicate CUT -- its stored pairs are its biggest, so an absent pair is
        at most the smallest one stored for it.

    HOW "CUT" IS KNOWN WITHOUT STORING IT. `ORDER BY rn ASC LIMIT n` fills rank
    1 of every predicate, then rank 2, and so on, so D -- the largest number of
    pairs any predicate ended up with -- is the depth the budget reached. No
    extra column and no extra query; the reader already loads the whole table.

    THE BOUNDARY IS `D - 1`, NOT `D`. The LIMIT is a row count, not a rank, so
    it truncates PARTWAY THROUGH rank D: of the predicates that had a rank-D
    pair, some got it and some did not, and the latter hold D-1 rows while still
    having pairs that were dropped. Testing `n >= D` called those "not cut" and
    handed them a bound of 1 while their absent pairs held 2.

    That is not hypothetical -- it was measured on `sp_graph_forms_20k`, where
    15,096 absent pairs exceeded the bound they were given. A bound that is too
    SMALL is the one direction that must never happen: it tells the planner an
    end is tiny when it is not, which is how the wrong end gets driven.

    A predicate with fewer than D-1 stored pairs cannot have been cut. Fairness
    seats rank k for every predicate before rank k+1 for any, so if it had a
    rank-(n+1) pair it would have got it while the budget was still filling
    rank n+1 for others. Fewer than D-1 rows therefore means it ran out of
    pairs, not out of budget.

    A predicate holding D or D-1 pairs that was NOT actually cut is read as cut.
    That is the safe direction: it weakens a known 1 into `<= min stored`,
    losing precision rather than inventing it.

    A PREDICATE WITH NO STORED PAIRS AT ALL is the case that matters most, and
    it is not "unknown" either. Fairness seats rank 1 of EVERY predicate before
    rank 2 of any, so a predicate that has any pair reaching
    STATS_MIN_ROW_COUNT is guaranteed a row. Absent entirely, therefore, means
    every one of its objects appears once -- and that is the shape of a
    high-cardinality id predicate, which is exactly what a query constrains when
    it looks up one lead or one campaign. Measured on `sp_lead_synth_10k`: the
    widest predicate has 50,000 stored pairs across the space and NONE of its
    own, because every one of its pairs is a singleton.

    Reading that as "no information" is how the end a query most wants to drive
    from stays unpriced. So `pred_stats` (which holds every predicate, not just
    the ones with a stored pair) supplies those, bounded at
    `STATS_MIN_ROW_COUNT - 1`.

    ONLY WHEN THE CAP DID NOT BIND AT DEPTH 1. If the cut depth is 1, the LIMIT
    was exhausted partway through seating rank 1 and some predicate with a large
    pair may have been starved -- so absence there could hide anything, and no
    bound is inferred. At depth >= 2 every predicate got its rank 1 and the
    inference is sound.

    Takes the loaded `{(predicate, object): row_count}` map, optionally the
    `{predicate: total}` map, and returns `{predicate: bound}`.
    """
    per_pred: Dict = {}
    for (pred, _obj), rc in (quad_stats or {}).items():
        n, lo = per_pred.get(pred, (0, None))
        per_pred[pred] = (n + 1, rc if lo is None else min(lo, rc))
    if not per_pred:
        return {}
    depth = max(n for n, _ in per_pred.values())
    out = {pred: (lo if n >= depth - 1 else STATS_MIN_ROW_COUNT - 1)
           for pred, (n, lo) in per_pred.items()}
    if depth >= 2:
        for pred in (pred_stats or {}):
            if pred not in out:
                out[pred] = STATS_MIN_ROW_COUNT - 1
    return out



async def recompute_stats_tables(conn, space_id: str,
                                 keep_top_n: int = None,
                                 timeout: float | None = None) -> Dict[str, int]:
    """Rebuild `{space}_rdf_stats` from the quads. The ONLY writer.

    `planning/planning_performance/rdf_stats_recompute_not_accumulate_plan.md`.

    This replaces an incrementally-maintained accumulator that could not
    validate itself and had a systematic downward bias. The accumulator's write
    path decremented on delete and, for a `pruned` predicate, refused to
    re-increment on insert -- so under normal update churn every pruned pair
    ratcheted monotonically to zero and was then deleted. A table of millions
    drained to single digits. That is `issues/142`, and it is why `rdf_stats`
    kept "mysteriously" collapsing.

    Three properties follow from recomputing instead:

      * absence has ONE meaning -- "not in the top N" -- so `pruned` is not
        needed, and neither is the audit that existed to detect when absence
        meant something else;
      * there are no deltas, so there is no wrong delta to accumulate;
      * the failure mode is STALE rather than SILENTLY WRONG, and the recovery
        for any bad outcome is running this again (~17 s).

    THE BIGGEST PAIRS PER PREDICATE, and that is the point of the table. The
    planner consults it to recognise an end that is HUGE so it does not drive
    from it. A pair the table cannot see is a pair the planner cannot avoid, so
    the two directions of error are not symmetric: a missing SMALL pair costs a
    missed optimisation, a missing ANCHOR leaves the semi-join gate unable to
    price it at all and falling back to a 10.4 s runtime probe that saturates
    and decides nothing.

    The distribution is what makes this cheap. Any realistic graph has a few
    very large pairs and a long tail of tiny ones -- measured here, 85-94% of
    all pairs are singletons (15.6M of them on a 50M-quad space). So the pairs
    worth storing are a small, bounded set, and the enormous tail is exactly
    what the cap should drop. It is also why recomputing beats accumulating:
    the accumulator spent its writes on the tail, where nearly all the CHANGES
    are and almost none of the value is.

    So `rn` ranks each predicate's pairs by `count(*) DESC` and the LIMIT takes
    rank 1 of every predicate, then rank 2, and so on -- the largest pair of
    every predicate before the second-largest of any, cut at the depth that
    fits rather than a depth guessed in advance.

    TWO SEPARATE THINGS HAD TO CHANGE, and fixing only one of them looks fixed.

      1. FAIRNESS ACROSS PREDICATES (`ORDER BY rn ASC`). Introduced against the
         ASC form, where a global limit was catastrophic -- measured on
         production, 10,000 rows drawn from 6 of 22 predicates, none above
         row_count 2, sixteen predicates with nothing.

         THAT JUSTIFICATION NO LONGER APPLIES once the order is DESC, and it
         should not be cited as if it did. A plain global `DESC LIMIT n` covers
         nearly everything on its own. Measured here at cap 50,000:

             wordnet_frames       global 14 of 15 preds   fairness 15 of 15
             sp_lead_synth_100k   global 18 of 19 preds   fairness 19 of 19

         What fairness still buys is that LAST predicate, and the reason is
         interpretive rather than statistical. With at least one pair stored for
         a predicate, a missing pair on it is `<= min(stored)`. With the
         predicate absent entirely there is no way to tell "has no pairs >= 2"
         from "was starved", and any query constraining it gets no price at all.

         It costs almost nothing: the starved predicate's largest pair was 2
         rows in both cases, and the quads covered differ by 1.1% and 0.01%.
         It also matters more as predicates multiply -- these spaces hold 9-23,
         so round-robin depth is ~2,500 each; with hundreds, a global limit
         would starve many.

      2. DIRECTION WITHIN A PREDICATE. The fairness fix inherited `ASC` from the
         global form it replaced, which keeps each predicate's SMALLEST pairs
         and drops its largest -- the opposite of the purpose above. Removing
         the `<= STATS_MAX_ROW_COUNT` bound only makes a large pair ELIGIBLE;
         `ASC` then discarded it anyway for any predicate holding more pairs
         than the cut depth. Reproduced at `keep_top_n=1000` against a predicate
         with one 5,000-row pair and 3,000 pairs of 2:

             ASC    5,000-row anchor DROPPED, a smaller 4,000-row pair kept
             DESC   5,000-row anchor KEPT, both predicates still represented

         That is the `(rdf:type, Edge_hasKGSlot) = 304,859` shape exactly: a
         high-cardinality predicate whose one enormous pair is the anchor.

    NO UPPER BOUND on `row_count`. The old `<= STATS_MAX_ROW_COUNT` existed to
    bound an unbounded accumulator; `LIMIT` bounds this one. Keeping it would
    discard the 24 pairs above the cap -- 36% of all quads, and the structural
    anchors the reorder most needs.

    WHAT ABSENCE MEANS, therefore: smaller than every stored pair of the same
    predicate, or below `STATS_MIN_ROW_COUNT` if that predicate was not cut at
    all. An upper bound either way -- absence can never hide a huge end.

    Cost, measured across three production spaces (12.7M / 21.5M / 45.8M quads):
    20.3 s / 13.1 s / 16.9 s. Flat, not superlinear -- the cost is the
    aggregate's index scan, not the table size.
    """
    n = int(keep_top_n if keep_top_n is not None else STATS_KEEP_DEFAULT)
    t_quad = f"{space_id}_rdf_quad"
    t_pred = f"{space_id}_rdf_pred_stats"
    t_stats = f"{space_id}_rdf_stats"

    # ONE transaction. A TRUNCATE that commits without its INSERT leaves the
    # table EMPTY, and absence means "not in the top N" to every consumer --
    # so a half-finished rebuild is read as a confident "no selective pairs
    # exist" rather than as missing data (`issues/103`).
    #
    # The aggregate runs BEFORE the TRUNCATE: locks are taken per statement,
    # not at BEGIN, so staging first keeps the exclusive lock to the truncate
    # and a bulk insert rather than spanning the scan (`issues/145`).
    async with conn.transaction():
        # STREAM THE PAIR AGGREGATE, do not hash it.
        #
        # Grouping by (predicate, object) makes one group per distinct pair --
        # 16.6M of them on a 50M-quad space -- so the hash table cannot fit in
        # work_mem and Postgres spills it. Measured on `sp_lead_synth_100k`:
        # `temp written=441,905` blocks, about 3.5 GB through the temp files.
        #
        # `idx_{space}_quad_po` is on exactly this key, so an index-only scan
        # delivers the rows already grouped and the aggregate can stream them
        # with no hash and no spill. The planner does not choose it on its own:
        # since PG13 a hash aggregate CAN spill, so it is costed as viable and
        # wins on the estimate.
        #
        #     as shipped (hash, spills)   48.2 s
        #     streaming GroupAggregate    13.7 s      3.5x
        #     work_mem = 1GB              48.2 s      no change
        #
        # Raising work_mem is not the fix and was measured not to be: 16.6M
        # groups do not fit at any setting worth configuring.
        #
        # Held across shapes -- 1.9x on wordnet_frames, 2.0x on
        # sp_graph_synth_100k, 2.2x on sp_lead_synth_10k, and 1.1x (harmless) on
        # a 280k-quad space where nothing spills anyway.
        #
        # SAVE AND RESTORE rather than `SET LOCAL`. A caller can already hold a
        # transaction -- the import endpoint, bulk_export and the migration
        # scripts all call this directly -- and inside one,
        # asyncpg's `transaction()` opens a SAVEPOINT, so `SET LOCAL` would
        # outlive this function and silently disable hashing for the caller's
        # remaining work.
        #
        # THE INDEX IS THE PRECONDITION. Without it this forces a sort of the
        # whole quad table, which is far worse than the spill it replaces. Every
        # space gets it from `create_space_indexes_sql`
        # (`sparql_sql_schema.py:1128`); `test_recompute_streams_the_aggregate`
        # pins that it is still emitted.
        _hashagg = await conn.fetchval("SHOW enable_hashagg")
        await conn.execute("SET enable_hashagg = off")
        try:
            await conn.execute(f"""
                CREATE TEMP TABLE _new_stats ON COMMIT DROP AS
                SELECT predicate_uuid, object_uuid, rc FROM (
                  SELECT predicate_uuid, object_uuid, count(*) AS rc,
                         row_number() OVER (PARTITION BY predicate_uuid
                                            ORDER BY count(*) DESC, object_uuid) AS rn
                    FROM {t_quad}
                   GROUP BY 1, 2
                  HAVING count(*) >= {STATS_MIN_ROW_COUNT}) r
                     ORDER BY rn ASC, rc DESC
                     LIMIT {n}
            """, timeout=timeout)
        finally:
            await conn.execute(f"SET enable_hashagg = {_hashagg}")

        # NOT fenced: this groups by predicate alone, which is ~20 groups, so
        # the hash is tiny and the planner already picks a parallel index-only
        # scan. Measured at 1.6 s against the same table, with no spill at all.
        await conn.execute(f"""
            CREATE TEMP TABLE _new_pred_stats ON COMMIT DROP AS
            SELECT predicate_uuid, count(*) AS row_count
              FROM {t_quad}
             GROUP BY predicate_uuid
        """, timeout=timeout)

        await conn.execute(f"TRUNCATE {t_stats}", timeout=timeout)
        res = await conn.execute(
            f"INSERT INTO {t_stats} (predicate_uuid, object_uuid, row_count) "
            f"SELECT predicate_uuid, object_uuid, rc FROM _new_stats",
            timeout=timeout)
        stats_count = int(res.split()[-1]) if res else 0

        await conn.execute(f"TRUNCATE {t_pred}", timeout=timeout)
        res = await conn.execute(
            f"INSERT INTO {t_pred} (predicate_uuid, row_count) "
            f"SELECT predicate_uuid, row_count FROM _new_pred_stats",
            timeout=timeout)
        pred_count = int(res.split()[-1]) if res else 0

    await conn.execute(f"ANALYZE {t_stats}", timeout=timeout)
    await conn.execute(f"ANALYZE {t_pred}", timeout=timeout)

    logger.info("recompute_stats_tables(%s): %d pred_stats, %d quad_stats "
                "(cap %d, no upper row_count bound)",
                space_id, pred_count, stats_count, n)
    return {"pred_stats": pred_count, "quad_stats": stats_count}
