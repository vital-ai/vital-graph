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
    # SORTED, here and in every statement below, and in the same sequence in
    # sync_stats_after_delete: one global lock order across all writers.
    # `Counter` iterates in first-seen order, which comes from the caller's
    # quad_rows, so two batches holding the same predicates in a different
    # order locked the same rows in a different order and deadlocked outright
    # (issues/115 — reproduced as SQLSTATE 40P01, the loser's whole batch
    # discarded and, in the segmentation worker, recorded as a permanent job
    # failure).
    await conn.executemany(
        f"INSERT INTO {t_pred} (predicate_uuid, row_count) "
        f"VALUES ($1, $2) "
        f"ON CONFLICT (predicate_uuid) "
        f"DO UPDATE SET row_count = {t_pred}.row_count + EXCLUDED.row_count",
        sorted(pred_counts.items()),
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

    fresh = sorted((p, o, c) for (p, o), c in po_counts.items() if p not in pruned)
    if fresh:
        # The `pruned` test is repeated INSIDE the statement, not just in the
        # Python filter above, because the read and the write are not
        # serialised against `prune_stats_tables`:
        #
        #     read `pruned`   -> predicate not flagged
        #                        <- prune commits: drops the pair, sets the flag
        #     INSERT          -> pair is now absent, so ON CONFLICT does not
        #                        fire and this CREATES a row holding only the
        #                        delta
        #
        # That row is the `issues/062` corruption: a pair whose true count is
        # 76,346 recorded as 80. Once written, nothing detects it — a wrong
        # LOW value sorts away from the integrity check's sample
        # (`issues/141`), and the join reorder reads it as a rare pair.
        #
        # `WHERE NOT EXISTS (... AND pruned)` re-evaluates the flag at insert
        # time under the same snapshot as the write, so the losing side of the
        # race inserts nothing instead of inventing a count. An UPDATE to an
        # existing row is unaffected: ON CONFLICT still fires for a pair that
        # is present, which is the case this path exists to serve.
        await conn.executemany(
            f"INSERT INTO {t_stats} (predicate_uuid, object_uuid, row_count) "
            f"SELECT $1, $2, $3 WHERE NOT EXISTS ("
            f"  SELECT 1 FROM {t_pred} p "
            f"   WHERE p.predicate_uuid = $1 AND p.pruned) "
            f"ON CONFLICT (predicate_uuid, object_uuid) "
            f"DO UPDATE SET row_count = {t_stats}.row_count + EXCLUDED.row_count",
            fresh,
        )
    stale = [(c, p, o) for p, o, c in
             sorted((p, o, c) for (p, o), c in po_counts.items() if p in pruned)]
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
    # Sorted, and t_pred before t_stats, matching sync_stats_after_insert
    # exactly. See the lock-order note there (issues/115).
    await conn.executemany(
        f"UPDATE {t_pred} "
        f"SET row_count = GREATEST(0, row_count - $2) "
        f"WHERE predicate_uuid = $1",
        sorted(pred_counts.items()),
    )
    updated += len(pred_counts)

    # The insert path splits t_stats by whether the predicate is pruned and
    # issues the two groups as separate statements, so sorting alone would not
    # line the two paths up: a delete sorted across ALL pairs still crosses an
    # insert that does every unpruned pair first. Take the same split, so both
    # paths walk t_stats in one order: unpruned ascending, then pruned.
    pruned = {r["predicate_uuid"] for r in await conn.fetch(
        f"SELECT predicate_uuid FROM {t_pred} WHERE pruned")}
    ordered = ([t for t in sorted((p, o, c) for (p, o), c in po_counts.items())
                if t[0] not in pruned] +
               [t for t in sorted((p, o, c) for (p, o), c in po_counts.items())
                if t[0] in pruned])
    await conn.executemany(
        f"UPDATE {t_stats} "
        f"SET row_count = GREATEST(0, row_count - $3) "
        f"WHERE predicate_uuid = $1 AND object_uuid = $2",
        ordered,
    )
    updated += len(po_counts)

    # Prune (pred,obj) rows that just churned to empty. rdf_stats is the
    # unbounded stats table; leaving row_count=0 rows behind lets it grow
    # without bound under delete churn (they're re-created via the insert-path
    # upsert if the pair reappears). Only touches pairs we just decremented.
    await conn.executemany(
        f"DELETE FROM {t_stats} "
        f"WHERE predicate_uuid = $1 AND object_uuid = $2 AND row_count <= 0",
        [(p, o) for p, o, _c in ordered],
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

    # ONE rebuild per space at a time, or two of them corrupt each other.
    #
    # This is a TRUNCATE followed by an INSERT that takes minutes on a large
    # space. Run twice concurrently, the second INSERT meets rows the first has
    # already written and dies on the primary key:
    #
    #     duplicate key value violates unique constraint "…_rdf_stats_pkey"
    #
    # and the reported pair differs every run, because it is whichever row the
    # two happened to collide on (issues/103).
    #
    # It is SELF-TRIGGERING, which is why it took a 50M-quad load to surface.
    # `maintenance_job._audit_stats` samples the largest recorded pairs and
    # rebuilds a space whose counts disagree with the quad table. Mid-rebuild
    # they always disagree — the TRUNCATE above is what makes them disagree — so
    # a load's own resync invites the maintenance job to start a competing one.
    # On a small space the window is seconds and nothing collides; here it was
    # minutes.
    #
    # The lock BLOCKS rather than skipping. Skipping would return while another
    # rebuild is in flight, and that rebuild may have started before this
    # caller's writes landed — leaving stats that are silently stale rather than
    # merely late. Waiting costs one redundant rebuild and is always correct.
    lock_key = f"vitalgraph.stats.{space_id}"
    await conn.execute("SELECT pg_advisory_lock(hashtext($1))", lock_key)
    try:
        return await _resync_stats_locked(conn, space_id, t_quad, t_pred, t_stats)
    finally:
        await conn.execute("SELECT pg_advisory_unlock(hashtext($1))", lock_key)


async def _resync_stats_locked(conn, space_id: str, t_quad: str, t_pred: str,
                               t_stats: str) -> Dict[str, int]:
    """The rebuild itself. Callers go through `resync_stats_tables`, which holds
    the per-space advisory lock this body assumes."""
    # ONE TRANSACTION, so a failure cannot leave the tables EMPTY.
    #
    # Each `execute` autocommits on its own, so the TRUNCATE committed and a
    # failing INSERT left the table with nothing in it. That is the worst
    # available state rather than a neutral one: absence means ZERO to every
    # consumer of these tables — the criterion gate reads pairs as unmeasured,
    # `semijoin._selective_enough` divides by an understated anchor — so a
    # half-finished rebuild makes the planner confidently wrong where a stale one
    # only makes it out of date. Observed: a load died here and left 50M quads
    # against a 136-row stats table (issues/103).
    #
    # TRUNCATE is transactional in PostgreSQL, so rolling back restores the
    # previous contents. ANALYZE stays outside; it is not part of the swap and
    # does not need to be.
    async with conn.transaction():
        # Predicate cardinality
        await conn.execute(f"TRUNCATE {t_pred}")
        result = await conn.execute(f"""
            INSERT INTO {t_pred} (predicate_uuid, row_count)
            SELECT predicate_uuid, COUNT(*)
            FROM {t_quad}
            GROUP BY predicate_uuid
        """)
        pred_count = int(result.split()[-1]) if result else 0

        # Predicate+object co-occurrence, excluding extremely common pairs.
        #
        # The bound is STATS_MAX_ROW_COUNT, not a literal. It was written out here
        # as 200000 while the `pruned` update below has to use exactly the same
        # threshold to decide which predicates this rebuild covered — two copies of
        # a constant that must agree, where disagreement silently mislabels a
        # predicate as fully covered and re-opens the delta-only bug.
        await conn.execute(f"TRUNCATE {t_stats}")
        result = await conn.execute(f"""
            INSERT INTO {t_stats} (predicate_uuid, object_uuid, row_count)
            SELECT predicate_uuid, object_uuid, COUNT(*)
            FROM {t_quad}
            GROUP BY predicate_uuid, object_uuid
            HAVING COUNT(*) <= {STATS_MAX_ROW_COUNT}
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
    #
    # THE AMBIGUITY IS NOT INERT. Clearing the flag for a predicate whose pair
    # is above the cap tells the incremental sync that absence means zero, and
    # it then INSERTS a delta-only row over a pair holding hundreds of
    # thousands. Observed on a 5.1M-quad space: (rdf:type, Edge_hasKGSlot)
    # recorded 37 against 304,859 actual, (rdf:type, KGFrame) 6 against 60,054.
    #
    # The reasoning above is about what a CORRECT absent value would change,
    # and the damage is done by a WRONG present value — a different thing, and
    # not big-versus-bigger. `semijoin._selective_enough` divides the probe's
    # matches by the anchor's candidates, so 5/6 scored 83% selective where
    # 5/60,054 is 0.008%: it chose a per-row probe and evaluated 60,054
    # correlated EXISTS to return 5 rows. 269ms against 33ms end to end, 150ms
    # against 0.1ms for the generated SQL.
    #
    # So the flag is cleared only for predicates this rebuild fully covered.
    # A predicate with any pair above the cap keeps `pruned = TRUE`, which is
    # what it means: absence for this predicate is not evidence of zero.
    await conn.execute(f"""
        UPDATE {t_pred} SET pruned = EXISTS (
            SELECT 1 FROM {t_quad} q
            WHERE q.predicate_uuid = {t_pred}.predicate_uuid
            GROUP BY q.object_uuid
            HAVING COUNT(*) > {STATS_MAX_ROW_COUNT})
    """)

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

    KEEP-AND-REWRITE, NOT DELETE, and the difference is hundreds of megabytes.
    ------------------------------------------------------------------------
    This used to run three DELETEs. They removed ~99.8% of the rows — wordnet's
    rdf_stats goes 2,817,658 -> 6,427 — and a plain VACUUM returns those pages
    to the free space map, never to the OS. So the file stayed at its
    high-water mark for a table that now holds a few thousand rows. Measured
    before this change, live rows against total size:

        wordnet_frames         6,427 rows    375 MB
        sp_graph_synth_10k     8,710 rows     99 MB
        prolog_spike_synth     8,454 rows     68 MB
        sp_graph_synth_100k   10,687 rows    752 MB  -> 1,352 kB after rewrite

    Selecting the keepers into a temp table takes no exclusive lock, so the
    expensive part runs concurrently with readers; only the TRUNCATE and the
    re-insert of a few thousand rows hold one, and both are fast. TRUNCATE
    allocates a new relfilenode, so the space is returned rather than pooled.

    WHY NOT FIX THIS IN THE RESYNC INSTEAD, which is where the 2.8M rows are
    written: because `pruned` would then be permanent. The flag degrades
    `sync_stats_after_insert` to UPDATE-only so a pruned predicate never gains
    new pairs, and a full resync clearing it is the ONLY thing that restores
    "absence means zero". If the resync wrote a pruned set it would have to set
    the flag, nothing would ever clear it, and new (predicate, object) pairs
    would stop being recorded for good. The write amplification is real and it
    is the cheaper of the two problems.
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
    # The keeper set, computed in one pass with no exclusive lock held.
    #
    #   * `WHERE row_count BETWEEN` is old step 1 — drop the singletons the
    #     reorder never reads and the super-common pairs it filters out.
    #   * `rn <= per_predicate_n` is old step 2, and the comment that justified
    #     it still applies: a global "lowest N" ranking lets one
    #     high-cardinality predicate evict every other. Measured on
    #     sp_lead_synth_100k, 49,516 of 50,000 survivors were hasEdgeSource
    #     while vitaltype (10,054,000 quads), hasKGSlotType and hasKGFrameType
    #     were absent entirely — the predicates that decide plan shape, gone
    #     (issues/061). Per-predicate retention is the shape of PostgreSQL's own
    #     MCV lists: no predicate can starve another.
    #   * `ORDER BY rn` then `LIMIT` is old step 3. Ordering by the PER-PREDICATE
    #     rank rather than by row_count is deliberate — row_count would undo
    #     step 2, since the structural pairs it just protected are precisely the
    #     high-count ones and would sort to the end again. Taking rank 1 of every
    #     predicate, then rank 2, trims every predicate's tail evenly instead of
    #     one predicate whole.
    #
    # WITHIN a rank tier the tiebreak is row_count, and that is a fix rather
    # than a port. The DELETE form broke ties on `ctid` — physical order — which
    # a rewrite does not preserve and which carries no meaning about a pair.
    # `test_prune_hard_cap_keeps_lowest_row_counts` passed under it only by
    # accident: every row in that fixture has its own predicate so every row is
    # rank 1, and the fixture inserts in ascending row_count, so ctid happened
    # to equal selectivity order. In production it does not.
    #
    # Ordering by rn FIRST still protects step 2 — sorting by row_count alone
    # would undo it, putting the structural high-count pairs back at the end —
    # but within one tier the most selective pair is the one worth keeping, so
    # the cap now trims by selectivity instead of by where a row happens to sit.
    # (predicate_uuid, object_uuid) remains as a final tiebreak for determinism.
    async with conn.transaction():
        await conn.execute(
            f"CREATE TEMP TABLE _keep_stats ON COMMIT DROP AS "
            f"  SELECT predicate_uuid, object_uuid, row_count FROM ("
            f"    SELECT predicate_uuid, object_uuid, row_count,"
            f"           row_number() OVER ("
            f"             PARTITION BY predicate_uuid "
            f"             ORDER BY row_count ASC, object_uuid) AS rn"
            f"    FROM {t_stats}"
            f"    WHERE row_count >= $1 AND row_count <= $2) r"
            f"  WHERE r.rn <= $3"
            f"  ORDER BY r.rn ASC, r.row_count ASC, r.predicate_uuid, r.object_uuid"
            f"  LIMIT $4",
            STATS_MIN_ROW_COUNT, STATS_MAX_ROW_COUNT,
            per_predicate_n, keep_top_n)

        # Which predicates lose a row. Collected BEFORE the rewrite, because
        # afterwards there is nothing left to compare against.
        #
        # Marking them is what lets sync_stats_after_insert tell "absent because
        # pruned" from "absent because zero". Without that distinction it treats
        # a pruned pair's missing row as a zero base and stores only the
        # post-prune delta: 100,000 -> 1 after one write (issues/062).
        pruned_preds = [r["predicate_uuid"] for r in await conn.fetch(
            f"SELECT DISTINCT s.predicate_uuid FROM {t_stats} s "
            f"LEFT JOIN _keep_stats k "
            f"  ON k.predicate_uuid = s.predicate_uuid "
            f" AND k.object_uuid = s.object_uuid "
            f"WHERE k.predicate_uuid IS NULL")]

        # TRUNCATE allocates a new relfilenode, so the pages the old rows
        # occupied are returned to the OS rather than pooled in the FSM. That is
        # the whole point of the rewrite; a DELETE here reclaims nothing.
        await conn.execute(f"TRUNCATE {t_stats}")
        await conn.execute(
            f"INSERT INTO {t_stats} (predicate_uuid, object_uuid, row_count) "
            f"SELECT predicate_uuid, object_uuid, row_count FROM _keep_stats")

        if pruned_preds:
            await conn.execute(
                f"UPDATE {t_pred} SET pruned = TRUE WHERE predicate_uuid = ANY($1)",
                pruned_preds)

    kept = await conn.fetchval(f"SELECT count(*) FROM {t_stats}")
    logger.info("prune_stats_tables(%s): kept %d rows (cap %d)",
                space_id, kept, keep_top_n)
    return kept
