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

# The join-reorder loader (generator._load_quad_stats) reads only pairs with
# STATS_MIN_ROW_COUNT <= row_count <= STATS_MAX_ROW_COUNT, taking the lowest
# STATS_LOAD_LIMIT of them. Everything else in rdf_stats is dead weight — at 1B
# quads the row_count=1 singletons (one per distinct object) alone reach
# 50-200M rows. prune_stats_tables bounds the table to what the reorder uses.
STATS_MIN_ROW_COUNT = 2
STATS_MAX_ROW_COUNT = 200_000
STATS_LOAD_LIMIT = 10_000
# Keep comfortably more than the load limit so the lowest-N window is intact.
STATS_KEEP_DEFAULT = 50_000
# Rows retained per predicate before the global cap. Bounds any single predicate
# so it cannot evict the others: with a few hundred distinct predicates this
# stays well under STATS_KEEP_DEFAULT, and it guarantees the structural
# predicates (vitaltype, hasKGSlotType, hasKGFrameType) survive even when a
# high-cardinality literal predicate has orders of magnitude more pairs.
STATS_PER_PREDICATE_DEFAULT = 2_000


async def sync_stats_after_insert(
    conn,
    space_id: str,
    quad_rows: List[Tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]],
) -> int:
    """After quads are inserted, increment predicate and pred+object stats.

    quad_rows: list of (subject_uuid, predicate_uuid, object_uuid, context_uuid).
    Returns total stats rows upserted.
    """
    if not quad_rows:
        return 0

    t_pred = f"{space_id}_rdf_pred_stats"
    t_stats = f"{space_id}_rdf_stats"

    # Count occurrences per predicate and per (predicate, object)
    pred_counts: Counter = Counter()
    po_counts: Counter = Counter()
    for _s, p, o, _g in quad_rows:
        pred_counts[p] += 1
        po_counts[(p, o)] += 1

    # Upsert predicate stats
    upserted = 0
    await conn.executemany(
        f"INSERT INTO {t_pred} (predicate_uuid, row_count) "
        f"VALUES ($1, $2) "
        f"ON CONFLICT (predicate_uuid) "
        f"DO UPDATE SET row_count = {t_pred}.row_count + EXCLUDED.row_count",
        [(p, cnt) for p, cnt in pred_counts.items()],
    )
    upserted += len(pred_counts)

    # Upsert predicate+object stats
    # For a predicate whose rows have been pruned, a MISSING pair does not mean
    # "count is zero" — it means "count is unknown". Inserting the delta as
    # though the base were zero is what turned a pair holding 100,000 quads into
    # a stored count of 1 after a single write (issues/062), and a
    # wrong-but-present row is worse than an absent one: the reader trusts what
    # it finds and only counts what it does not.
    #
    # So for pruned predicates this degrades to UPDATE-only. Existing rows stay
    # accurate — their base is right and the delta is right — and absent ones
    # stay absent, which sends the reader to the bounded count that answers
    # honestly.
    pruned = {r["predicate_uuid"] for r in await conn.fetch(
        f"SELECT predicate_uuid FROM {t_pred} WHERE pruned")}

    fresh = [(p, o, c) for (p, o), c in po_counts.items() if p not in pruned]
    if fresh:
        await conn.executemany(
            f"INSERT INTO {t_stats} (predicate_uuid, object_uuid, row_count) "
            f"VALUES ($1, $2, $3) "
            f"ON CONFLICT (predicate_uuid, object_uuid) "
            f"DO UPDATE SET row_count = {t_stats}.row_count + EXCLUDED.row_count",
            fresh,
        )
    stale = [(c, p, o) for (p, o), c in po_counts.items() if p in pruned]
    if stale:
        await conn.executemany(
            f"UPDATE {t_stats} SET row_count = row_count + $1 "
            f"WHERE predicate_uuid = $2 AND object_uuid = $3",
            stale,
        )
    upserted += len(po_counts)

    logger.debug("sync_stats_after_insert(%s): %d pred + %d po upserts",
                 space_id, len(pred_counts), len(po_counts))
    return upserted


async def sync_stats_after_delete(
    conn,
    space_id: str,
    quad_rows: List[Tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]],
) -> int:
    """After quads are deleted, decrement predicate and pred+object stats.

    quad_rows: list of (subject_uuid, predicate_uuid, object_uuid, context_uuid).
    Decrements counts, flooring at 0.  Returns total rows updated.
    """
    if not quad_rows:
        return 0

    t_pred = f"{space_id}_rdf_pred_stats"
    t_stats = f"{space_id}_rdf_stats"

    pred_counts: Counter = Counter()
    po_counts: Counter = Counter()
    for _s, p, o, _g in quad_rows:
        pred_counts[p] += 1
        po_counts[(p, o)] += 1

    updated = 0
    await conn.executemany(
        f"UPDATE {t_pred} "
        f"SET row_count = GREATEST(0, row_count - $2) "
        f"WHERE predicate_uuid = $1",
        [(p, cnt) for p, cnt in pred_counts.items()],
    )
    updated += len(pred_counts)

    await conn.executemany(
        f"UPDATE {t_stats} "
        f"SET row_count = GREATEST(0, row_count - $3) "
        f"WHERE predicate_uuid = $1 AND object_uuid = $2",
        [(p, o, cnt) for (p, o), cnt in po_counts.items()],
    )
    updated += len(po_counts)

    # Prune (pred,obj) rows that just churned to empty. rdf_stats is the
    # unbounded stats table; leaving row_count=0 rows behind lets it grow
    # without bound under delete churn (they're re-created via the insert-path
    # upsert if the pair reappears). Only touches pairs we just decremented.
    await conn.executemany(
        f"DELETE FROM {t_stats} "
        f"WHERE predicate_uuid = $1 AND object_uuid = $2 AND row_count <= 0",
        [(p, o) for (p, o) in po_counts.keys()],
    )

    logger.debug("sync_stats_after_delete(%s): %d pred + %d po decrements",
                 space_id, len(pred_counts), len(po_counts))
    return updated


async def sync_stats_for_deleted_subjects(
    conn,
    space_id: str,
    subject_uuids: List[uuid.UUID],
    context_uuid: uuid.UUID = None,
) -> int:
    """Before quads for subjects are deleted, fetch their pred+object pairs
    and decrement stats.  Used by delete_entity_graph_bulk.

    Returns total stats rows updated.
    """
    if not subject_uuids:
        return 0

    t_quad = f"{space_id}_rdf_quad"

    # Fetch the quads that are about to be deleted
    if context_uuid:
        rows = await conn.fetch(
            f"SELECT subject_uuid, predicate_uuid, object_uuid, context_uuid "
            f"FROM {t_quad} WHERE subject_uuid = ANY($1) AND context_uuid = $2",
            subject_uuids, context_uuid,
        )
    else:
        rows = await conn.fetch(
            f"SELECT subject_uuid, predicate_uuid, object_uuid, context_uuid "
            f"FROM {t_quad} WHERE subject_uuid = ANY($1)",
            subject_uuids,
        )

    if not rows:
        return 0

    quad_rows = [(r['subject_uuid'], r['predicate_uuid'],
                  r['object_uuid'], r['context_uuid']) for r in rows]
    return await sync_stats_after_delete(conn, space_id, quad_rows)


async def resync_stats_tables(conn, space_id: str) -> Dict[str, int]:
    """Rebuild both stats tables from scratch by scanning rdf_quad.

    Truncates and repopulates both tables.  Runs ANALYZE afterwards.
    Returns {'pred_stats': N, 'quad_stats': M}.
    """
    t_quad = f"{space_id}_rdf_quad"
    t_pred = f"{space_id}_rdf_pred_stats"
    t_stats = f"{space_id}_rdf_stats"

    # Predicate cardinality
    await conn.execute(f"TRUNCATE {t_pred}")
    result = await conn.execute(f"""
        INSERT INTO {t_pred} (predicate_uuid, row_count)
        SELECT predicate_uuid, COUNT(*)
        FROM {t_quad}
        GROUP BY predicate_uuid
    """)
    pred_count = int(result.split()[-1]) if result else 0

    # Predicate+object co-occurrence (cap at 200k to exclude extremely common pairs)
    await conn.execute(f"TRUNCATE {t_stats}")
    result = await conn.execute(f"""
        INSERT INTO {t_stats} (predicate_uuid, object_uuid, row_count)
        SELECT predicate_uuid, object_uuid, COUNT(*)
        FROM {t_quad}
        GROUP BY predicate_uuid, object_uuid
        HAVING COUNT(*) <= 200000
    """)
    stats_count = int(result.split()[-1]) if result else 0

    await conn.execute(f"ANALYZE {t_pred}")
    await conn.execute(f"ANALYZE {t_stats}")

    # A full rebuild makes rdf_stats complete WITHIN THE WINDOW, so absence
    # means zero again for every predicate as far as any consumer of the
    # window is concerned. Leaving the flags set would keep the incremental
    # sync permanently degraded to UPDATE-only long after the reason was
    # gone, and nothing would ever have cleared it.
    #
    # "Complete" is not literal, and the earlier wording said it was. The
    # rebuild above carries `HAVING COUNT(*) <= 200000`, so absence means
    # "zero OR larger than STATS_MAX_ROW_COUNT" — opposite answers. On
    # graph_synth_100k that is 13 pairs of 5,669,790, covering 7,304,903 of
    # 19,632,351 quads (37% of the space): vitaltype/Edge_hasKGSlot and
    # vitaltype/KGEntitySlot at 946,548, the KGFrame and hasKGSlotType pairs
    # at 473,274.
    #
    # MEASURED 2026-08-15 and left as it is. Restoring those 13 rows changes
    # what `_load_missing_pair_stats` reports from 50,000 SATURATED to 473,274
    # exact — a 9.5x difference in the input to join reordering, the semijoin
    # marker and the slice direction gate — and produced BYTE-IDENTICAL SQL on
    # all 14 shapes tried (traversals at three depths, anchored+paged queries,
    # relation walks). Both values are "much larger than everything else", and
    # the reorder ranks by cardinality, so big-versus-bigger reorders nothing.
    # The one consumer that did read a restored value, the IN criterion gate,
    # measured a NET LOSS when fed (test_scripts/perf/bench_in_criterion_gate.py).
    # So the ambiguity is real and, on the evidence, inert. Do not "fix" it
    # without a consumer that demonstrably needs it.
    await conn.execute(f"UPDATE {t_pred} SET pruned = FALSE WHERE pruned")

    logger.info("resync_stats_tables(%s): %d pred_stats, %d quad_stats",
                space_id, pred_count, stats_count)
    return {'pred_stats': pred_count, 'quad_stats': stats_count}


async def resync_stats_for_predicates(conn, space_id: str,
                                      predicate_uuids: List[uuid.UUID],
                                      max_rows: int = 2_000_000) -> int:
    """Recompute stats for specific predicates from the quad table.

    The repair for a write whose affected quads cannot be enumerated. A SPARQL
    `DELETE WHERE { ?s <p> ?o }` binds its subject and object but names the
    PREDICATE concretely, so while the individual quads are unknowable without
    executing, the set of predicates whose counts moved is known exactly — and
    recomputing those is bounded by one predicate's rows rather than the table.

    Without this, `execute_sparql_update` left rdf_stats untouched entirely and
    nothing else repaired it: unlike the edge table, the maintenance job only
    PRUNES stats and never resyncs. A stale count does not produce a wrong
    answer; it produces a wrong PLAN, silently, and the query returns the right
    rows too slowly.

    Skipped for a predicate above `max_rows`, because the recompute is a GROUP BY
    over that predicate's quads and doing it inline on `vitaltype` (10,054,000
    rows in one measured space) would be a serious per-write regression. Skips
    are logged rather than silent — the alternative is drift nobody knows about.

    Returns the number of predicates recomputed.
    """
    if not predicate_uuids:
        return 0

    t_stats = f"{space_id}_rdf_stats"
    t_pred = f"{space_id}_rdf_pred_stats"
    t_quad = f"{space_id}_rdf_quad"
    done = 0

    for p_uuid in set(predicate_uuids):
        n = await conn.fetchval(
            f"SELECT count(*) FROM (SELECT 1 FROM {t_quad} "
            f"WHERE predicate_uuid = $1 LIMIT {int(max_rows) + 1}) s", p_uuid)
        if n > max_rows:
            logger.warning(
                "resync_stats_for_predicates(%s): predicate %s has >%d quads, "
                "skipping inline recompute — its stats may now be stale",
                space_id, p_uuid, max_rows)
            continue

        await conn.execute(
            f"DELETE FROM {t_stats} WHERE predicate_uuid = $1", p_uuid)
        await conn.execute(f"""
            INSERT INTO {t_stats} (predicate_uuid, object_uuid, row_count)
            SELECT predicate_uuid, object_uuid, count(*)
            FROM {t_quad} WHERE predicate_uuid = $1
            GROUP BY predicate_uuid, object_uuid
            ON CONFLICT (predicate_uuid, object_uuid)
            DO UPDATE SET row_count = EXCLUDED.row_count
        """, p_uuid)

        # pred_stats is not pruned, so it must be exactly right; a delete that
        # empties a predicate has to leave 0, not a stale row.
        # This predicate is complete again, so absence of one of its pairs
        # once more means zero rather than unknown.
        await conn.execute(f"""
            INSERT INTO {t_pred} (predicate_uuid, row_count, pruned)
            SELECT $1, count(*), FALSE FROM {t_quad} WHERE predicate_uuid = $1
            ON CONFLICT (predicate_uuid)
            DO UPDATE SET row_count = EXCLUDED.row_count, pruned = FALSE
        """, p_uuid)
        done += 1

    if done:
        logger.debug("resync_stats_for_predicates(%s): %d predicate(s)",
                     space_id, done)
    return done


async def prune_stats_tables(conn, space_id: str,
                             keep_top_n: int = STATS_KEEP_DEFAULT,
                             per_predicate_n: int = STATS_PER_PREDICATE_DEFAULT
                             ) -> int:
    """Bound {space}_rdf_stats to what the join reorder actually reads.

    rdf_stats accumulates one row per distinct (predicate, object) pair — at
    scale dominated by row_count=1 singletons (one per unique object) that the
    reorder loader never reads (it filters row_count >= 2). This removes the
    pairs outside the reorder's window (row_count < MIN or > MAX), keeps the
    ``per_predicate_n`` most selective objects FOR EACH PREDICATE, and then
    applies ``keep_top_n`` as an overall size bound.

    The per-predicate step is what stops one high-cardinality predicate evicting
    every other — see the comment at step 2. Returns rows kept. pred_stats is
    left alone (bounded by the distinct-predicate count).
    """
    t_stats = f"{space_id}_rdf_stats"
    t_pred = f"{space_id}_rdf_pred_stats"

    # Every predicate that loses a row here. Collected with RETURNING rather
    # than inferred afterwards, because inferring it means comparing stats
    # against the quad table — the expensive thing pruning exists to avoid.
    #
    # Marking them is what lets sync_stats_after_insert tell "absent because
    # pruned" from "absent because zero". Without that distinction it treats a
    # pruned pair's missing row as a zero base and stores only the post-prune
    # delta: 100,000 -> 1 after one write (issues/062).
    pruned_preds: set = set()

    # 1. Drop pairs the reorder never uses: singletons and super-common pairs.
    rows = await conn.fetch(
        f"DELETE FROM {t_stats} "
        f"WHERE row_count < $1 OR row_count > $2 "
        f"RETURNING predicate_uuid",
        STATS_MIN_ROW_COUNT, STATS_MAX_ROW_COUNT)
    pruned_preds.update(r["predicate_uuid"] for r in rows)

    # 2. Hard cap, PER PREDICATE rather than globally.
    #
    # A global "lowest N" ranking lets one high-cardinality predicate evict every
    # other. Measured on sp_lead_synth_100k: of 50,000 surviving rows, 49,516
    # were hasEdgeSource and 484 were hasDateTimeSlotValue, every one with
    # row_count=2 — while vitaltype (10,054,000 quads), hasKGSlotType (3,877,000)
    # and hasKGFrameType (1,100,000) were absent entirely. Those are exactly the
    # predicates that decide plan shape, so the table held nothing useful for the
    # queries that needed it (issues/061).
    #
    # The fixture's unique-per-row datetimes made it extreme (409,017 distinct
    # values at ~2 occurrences each, issues/050), but any high-cardinality
    # literal does the same in production — the flooding predicate is whichever
    # one happens to have the most distinct objects.
    #
    # Per-predicate retention is the same shape as PostgreSQL's own MCV lists:
    # every predicate keeps its own most-selective objects, so no predicate can
    # starve another. The global cap still applies afterwards as a size bound.
    rows = await conn.fetch(
        f"DELETE FROM {t_stats} WHERE ctid IN ("
        f"  SELECT ctid FROM ("
        f"    SELECT ctid, row_number() OVER ("
        f"      PARTITION BY predicate_uuid "
        f"      ORDER BY row_count ASC, object_uuid) AS rn"
        f"    FROM {t_stats}) r"
        f"  WHERE r.rn > $1) RETURNING predicate_uuid",
        per_predicate_n)
    pruned_preds.update(r["predicate_uuid"] for r in rows)

    # 3. Global size bound. Ordered by the PER-PREDICATE rank, not by row_count:
    #    ordering by row_count here would undo step 2, since the structural
    #    pairs it just protected are precisely the high-count ones and would sort
    #    to the end again. Taking rank 1 of every predicate, then rank 2, and so
    #    on, trims every predicate's tail evenly instead of one predicate whole.
    rows = await conn.fetch(
        f"DELETE FROM {t_stats} WHERE ctid IN ("
        f"  SELECT ctid FROM ("
        f"    SELECT ctid, row_number() OVER ("
        f"      PARTITION BY predicate_uuid "
        f"      ORDER BY row_count ASC, object_uuid) AS rn"
        f"    FROM {t_stats}) r"
        f"  ORDER BY r.rn ASC, r.ctid "
        f"  OFFSET $1) RETURNING predicate_uuid",
        keep_top_n)
    pruned_preds.update(r["predicate_uuid"] for r in rows)

    if pruned_preds:
        await conn.execute(
            f"UPDATE {t_pred} SET pruned = TRUE WHERE predicate_uuid = ANY($1)",
            list(pruned_preds))

    kept = await conn.fetchval(f"SELECT count(*) FROM {t_stats}")
    logger.info("prune_stats_tables(%s): kept %d rows (cap %d)",
                space_id, kept, keep_top_n)
    return kept
