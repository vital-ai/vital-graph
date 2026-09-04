"""Incremental sync for the {space}_edge table.

Called after quad inserts and before/after quad deletes to keep the edge
table in sync with rdf_quad.  All functions accept an asyncpg connection
that is already inside a transaction.
"""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

logger = logging.getLogger(__name__)

EDGE_SOURCE_URI = "http://vital.ai/ontology/vital-core#hasEdgeSource"
EDGE_DEST_URI = "http://vital.ai/ontology/vital-core#hasEdgeDestination"
VITALTYPE_URI = "http://vital.ai/ontology/vital-core#vitaltype"

# Deterministic UUID namespace (same as sparql_sql_space_impl)
_VITALGRAPH_NS = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')

# Pre-computed predicate UUIDs (deterministic, never change)
_EDGE_SRC_UUID = uuid.uuid5(_VITALGRAPH_NS, f"{EDGE_SOURCE_URI}\x00U")
_EDGE_DST_UUID = uuid.uuid5(_VITALGRAPH_NS, f"{EDGE_DEST_URI}\x00U")
_VITALTYPE_UUID = uuid.uuid5(_VITALGRAPH_NS, f"{VITALTYPE_URI}\x00U")

# Cap the subject-array size per aux-sync statement. A bulk load can touch
# hundreds of thousands of subjects at once; passing them all as one ANY($)
# array makes a huge parameter and an unbounded self-join. Chunking keeps each
# statement's work bounded (per-write cost stays flat vs load size).
SYNC_CHUNK = 10_000


def chunk_uuids(seq: List[uuid.UUID], n: int = SYNC_CHUNK):
    """Yield successive n-sized slices of a UUID list."""
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


async def sync_edge_table_after_insert(
    conn,
    space_id: str,
    subject_uuids: List[uuid.UUID],
) -> int:
    """After quads are inserted, find new edge pairs and insert into edge table.

    Scans only the given subject_uuids for hasEdgeSource + hasEdgeDestination
    pairs.  Returns the number of edge rows inserted.
    """
    if not subject_uuids:
        return 0

    t_edge = f"{space_id}_edge"
    t_quad = f"{space_id}_rdf_quad"

    inserted = 0
    for chunk in chunk_uuids(subject_uuids):
        result = await conn.execute(f"""
            INSERT INTO {t_edge} (edge_uuid, source_node_uuid, dest_node_uuid,
                                  context_uuid, edge_type_uuid)
            SELECT
                src.subject_uuid,
                src.object_uuid,
                dst.object_uuid,
                src.context_uuid,
                vt.object_uuid
            FROM {t_quad} src
            JOIN {t_quad} dst
                ON dst.subject_uuid = src.subject_uuid
                AND dst.context_uuid = src.context_uuid
            LEFT JOIN {t_quad} vt
                ON vt.subject_uuid = src.subject_uuid
                AND vt.context_uuid = src.context_uuid
                AND vt.predicate_uuid = $4
            WHERE src.predicate_uuid = $1
              AND dst.predicate_uuid = $2
              AND src.subject_uuid = ANY($3)
            ON CONFLICT DO NOTHING
        """, _EDGE_SRC_UUID, _EDGE_DST_UUID, chunk, _VITALTYPE_UUID)
        inserted += int(result.split()[-1]) if result else 0

    if inserted:
        logger.debug("sync_edge_table_after_insert(%s): %d edge rows", space_id, inserted)
    return inserted


async def sync_edge_table_before_delete(
    conn,
    space_id: str,
    subject_uuids: List[uuid.UUID],
    context_uuid: Optional[uuid.UUID] = None,
) -> int:
    """Before quads are deleted, remove corresponding edge table rows.

    Deletes edge rows where edge_uuid is in subject_uuids.
    If context_uuid is provided, scopes the delete to that graph.
    Returns the number of edge rows deleted.
    """
    if not subject_uuids:
        return 0

    t_edge = f"{space_id}_edge"

    if context_uuid:
        result = await conn.execute(
            f"DELETE FROM {t_edge} WHERE edge_uuid = ANY($1) AND context_uuid = $2",
            subject_uuids, context_uuid,
        )
    else:
        result = await conn.execute(
            f"DELETE FROM {t_edge} WHERE edge_uuid = ANY($1)",
            subject_uuids,
        )

    deleted = int(result.split()[-1]) if result else 0
    if deleted:
        logger.debug("sync_edge_table_before_delete(%s): %d edge rows", space_id, deleted)
    return deleted


async def cleanup_orphan_edges_for_subjects(conn, space_id: str,
                                            subjects: List[uuid.UUID]) -> int:
    """Remove edge rows (among the given edge_uuids) whose defining quads are
    gone — the delete-side counterpart of sync_edge_table_after_insert.

    An edge row is valid only while BOTH its hasEdgeSource and hasEdgeDestination
    quads exist. After a delete that removed one of them, the row is orphaned.
    Scoped to `subjects` (the edge_uuids the caller touched) so it stays cheap,
    and it only removes rows that are genuinely broken (so it's safe to pass any
    touched subject, edge or not). Returns rows deleted.
    """
    if not subjects:
        return 0
    t_edge = f"{space_id}_edge"
    t_quad = f"{space_id}_rdf_quad"
    result = await conn.execute(f"""
        DELETE FROM {t_edge} e
        WHERE e.edge_uuid = ANY($3)
          AND (
            NOT EXISTS (
                SELECT 1 FROM {t_quad} s
                WHERE s.subject_uuid = e.edge_uuid AND s.predicate_uuid = $1
                  AND s.object_uuid = e.source_node_uuid
                  AND s.context_uuid = e.context_uuid)
            OR NOT EXISTS (
                SELECT 1 FROM {t_quad} d
                WHERE d.subject_uuid = e.edge_uuid AND d.predicate_uuid = $2
                  AND d.object_uuid = e.dest_node_uuid
                  AND d.context_uuid = e.context_uuid)
          )
    """, _EDGE_SRC_UUID, _EDGE_DST_UUID, subjects)
    deleted = int(result.split()[-1]) if result else 0
    if deleted:
        logger.debug("cleanup_orphan_edges_for_subjects(%s): %d rows", space_id, deleted)
    return deleted


# Rows the sweep may EXAMINE per pass. The old bound was on rows DELETED, which
# is the wrong quantity: when there is nothing to delete — the healthy case, and
# the common one — PostgreSQL still had to probe every row to establish that.
# Measured at 181,212 ms over 4,977,000 rows with zero orphans, against a 60 s
# command_timeout, so it never finished and the cleanup never happened
# (issues/079). Bounding the SCAN makes each pass fixed-cost.
_SWEEP_SCAN_ROWS = 100_000

# Where the next pass starts, per space. In-process and deliberately so: losing
# it on restart costs one repeated window, and the sweep is convergent — it does
# not need to be durable to be correct.
_sweep_cursor: dict = {}


# Spaces whose updates deferred a delete the per-subject hooks could not reach.
# The sweep rotates over every space anyway, so this is a PRIORITY hint, not a
# queue — losing it costs later cleanup, never correctness. In-process for the
# same reason the cursor is.
_sweep_pending: set = set()


def mark_sweep_needed(space_id: str) -> None:
    """Record that a WHERE-bound delete left work the subject hooks cannot do."""
    _sweep_pending.add(space_id)


def take_sweep_pending() -> set:
    """Drain the pending set. Callers sweep what they get."""
    pending = set(_sweep_pending)
    _sweep_pending.clear()
    return pending


async def cleanup_orphan_edges(conn, space_id: str,
                               limit: int = 50_000,
                               scan_rows: int = _SWEEP_SCAN_ROWS) -> int:
    """Remove edge rows whose defining quads are gone. SCAN-bounded, rotating.

    The delete-side counterpart to `backfill_edge_table`, and the piece that was
    missing. `cleanup_orphan_edges_for_subjects` needs a subject list, which the
    SPARQL UPDATE path cannot produce for WHERE-bound subjects, so those deletes
    were deferred to "background self-heal" — but the self-heal is
    `backfill_edge_table`, a plain INSERT, which only ever ADDS. The insert half
    of a deferred update was reconciled and the delete half never was
    (issues/064).

    That is how 20,461 orphans accumulated across four spaces, 5.3% of a
    production-shaped one, each answering traversals with an edge to nowhere.

    BOUNDED ON THE SCAN, not on the deletions (issues/079). The previous form
    put `LIMIT` on the rows to delete, which bounds nothing when there is
    nothing to delete: proving absence still walks the whole table. Each pass
    now examines at most `scan_rows` rows, starting after the last ctid the
    previous pass reached and wrapping at the end, so repeated maintenance ticks
    cover the table and every pass costs the same.

    Plain DELETE, so ROW EXCLUSIVE only and edge-rewrite queries are not
    blocked — unlike `resync_edge_table`, which TRUNCATEs under ACCESS
    EXCLUSIVE.

    The context is part of the check for the same reason it is in
    `edge_table_orphan_rate`: a space reloaded under a different graph URI keeps
    edge_uuids that still resolve, so an identity-only test calls every row
    healthy while every query filters on the new context and matches nothing.
    """
    t_edge = f"{space_id}_edge"
    t_quad = f"{space_id}_rdf_quad"
    cursor = _sweep_cursor.get(space_id) or "(0,0)"

    # One pass over a bounded window: which of these rows are orphans, and how
    # far did we get. `ctid > $2` with ORDER BY ctid gives a stable rotation.
    rows = await conn.fetch(f"""
        SELECT w.c::text AS ctid,
               NOT EXISTS (
                   SELECT 1 FROM {t_quad} q
                   WHERE q.subject_uuid = w.edge_uuid
                     AND q.predicate_uuid = $1
                     AND q.context_uuid = w.context_uuid
               ) AS orphan
        FROM (
            SELECT ctid AS c, edge_uuid, context_uuid
            FROM {t_edge}
            WHERE ctid > $2::text::tid
            ORDER BY ctid
            LIMIT {int(scan_rows)}
        ) w
    """, _EDGE_SRC_UUID, cursor)

    if not rows:
        _sweep_cursor[space_id] = None          # end of table: wrap next pass
        return 0
    _sweep_cursor[space_id] = rows[-1]["ctid"]

    orphan_ctids = [r["ctid"] for r in rows if r["orphan"]][:int(limit)]
    if not orphan_ctids:
        return 0

    result = await conn.execute(
        f"DELETE FROM {t_edge} WHERE ctid = ANY($1::text[]::tid[])", orphan_ctids)
    deleted = int(result.split()[-1]) if result else 0
    if deleted:
        logger.info("cleanup_orphan_edges(%s): removed %d orphaned row(s) "
                    "from a %d-row window", space_id, deleted, len(rows))
    return deleted


async def delete_edges_for_context(conn, space_id: str, context_uuid) -> int:
    """Remove every edge row for a graph. For DROP GRAPH / CLEAR GRAPH.

    Those update forms name no subjects, so `_concrete_subjects_from_update_ops`
    yields nothing and the per-subject hooks never fire — leaving the whole
    graph's edges orphaned while its quads are gone (issues/064).
    """
    t_edge = f"{space_id}_edge"
    result = await conn.execute(
        f"DELETE FROM {t_edge} WHERE context_uuid = $1", context_uuid)
    deleted = int(result.split()[-1]) if result else 0
    if deleted:
        logger.info("delete_edges_for_context(%s): removed %d row(s) for %s",
                    space_id, deleted, context_uuid)
    return deleted


async def resync_edge_table(conn, space_id: str) -> int:
    """Rebuild {space}_edge from scratch by scanning rdf_quad.

    Truncates the edge table and repopulates it from hasEdgeSource +
    hasEdgeDestination quad pairs.  Runs ANALYZE afterwards.
    Returns the number of rows inserted.

    A well-formed edge has exactly one hasEdgeSource and one hasEdgeDestination
    per (edge_uuid, context).  Malformed edges with more than one of either
    would make the src×dst product collide on the (edge_uuid, context_uuid)
    primary key, so we de-duplicate with DISTINCT ON (keeping one arbitrary
    pair per edge) and warn — otherwise the INSERT aborts and, because TRUNCATE
    already ran, leaves the edge table empty.
    """
    t_edge = f"{space_id}_edge"
    t_quad = f"{space_id}_rdf_quad"

    malformed = await conn.fetchval(f"""
        SELECT count(*) FROM (
            SELECT subject_uuid, context_uuid FROM {t_quad}
            WHERE predicate_uuid = ANY($1)
            GROUP BY subject_uuid, context_uuid, predicate_uuid
            HAVING count(*) > 1
        ) x
    """, [_EDGE_SRC_UUID, _EDGE_DST_UUID])
    if malformed:
        logger.warning(
            "resync_edge_table(%s): %d edges have >1 hasEdgeSource/hasEdgeDestination "
            "(malformed) — keeping one arbitrary pair each", space_id, malformed)

    await conn.execute(f"TRUNCATE {t_edge}")

    result = await conn.execute(f"""
        INSERT INTO {t_edge} (edge_uuid, source_node_uuid, dest_node_uuid,
                              context_uuid, edge_type_uuid)
        SELECT DISTINCT ON (src.subject_uuid, src.context_uuid)
            src.subject_uuid,
            src.object_uuid,
            dst.object_uuid,
            src.context_uuid,
            vt.object_uuid
        FROM {t_quad} src
        JOIN {t_quad} dst
            ON dst.subject_uuid = src.subject_uuid
            AND dst.context_uuid = src.context_uuid
        LEFT JOIN {t_quad} vt
            ON vt.subject_uuid = src.subject_uuid
            AND vt.context_uuid = src.context_uuid
            AND vt.predicate_uuid = $3
        WHERE src.predicate_uuid = $1
          AND dst.predicate_uuid = $2
        ORDER BY src.subject_uuid, src.context_uuid
    """, _EDGE_SRC_UUID, _EDGE_DST_UUID, _VITALTYPE_UUID)

    inserted = int(result.split()[-1]) if result else 0
    await conn.execute(f"ANALYZE {t_edge}")
    logger.info("resync_edge_table(%s): %d rows inserted", space_id, inserted)
    return inserted


async def backfill_edge_table(conn, space_id: str,
                              timeout: float | None = None) -> int:
    """Add only the MISSING edges to {space}_edge — no TRUNCATE, no rebuild.

    `timeout` is asyncpg's CLIENT-side bound and is not optional in practice.
    The pool is built with `command_timeout=60`, which fires in the DRIVER;
    `maintenance_timeouts` raises `statement_timeout` with SET, which is the
    SERVER half and cannot touch it. A full-space backfill on a 45M-quad space
    runs well past 60s, so without this the repair is cancelled by the client
    every cycle and the edge table stays short forever.

    That is not hypothetical — it is exactly `issues/149`, where the slot-sort
    backfill had never once run for the same reason, and this is its sibling
    path. Caller must ALSO raise the server fences.

    Unlike resync_edge_table (which TRUNCATEs and holds ACCESS EXCLUSIVE on the
    edge table for the whole rebuild, blocking edge-rewrite queries), this is a
    plain INSERT ... ON CONFLICT DO NOTHING: it takes only ROW EXCLUSIVE, which
    does NOT conflict with concurrent readers, so edge-table queries keep
    running while it backfills.  Deletes are kept in sync separately
    (sync_edge_table_before_delete), so the table has no orphans to remove —
    drift is always *missing* edges, which this adds.  Returns rows inserted.
    """
    t_edge = f"{space_id}_edge"
    t_quad = f"{space_id}_rdf_quad"

    result = await conn.execute(f"""
        INSERT INTO {t_edge} (edge_uuid, source_node_uuid, dest_node_uuid,
                              context_uuid, edge_type_uuid)
        SELECT DISTINCT ON (src.subject_uuid, src.context_uuid)
            src.subject_uuid,
            src.object_uuid,
            dst.object_uuid,
            src.context_uuid,
            vt.object_uuid
        FROM {t_quad} src
        JOIN {t_quad} dst
            ON dst.subject_uuid = src.subject_uuid
            AND dst.context_uuid = src.context_uuid
        LEFT JOIN {t_quad} vt
            ON vt.subject_uuid = src.subject_uuid
            AND vt.context_uuid = src.context_uuid
            AND vt.predicate_uuid = $3
        WHERE src.predicate_uuid = $1
          AND dst.predicate_uuid = $2
        ORDER BY src.subject_uuid, src.context_uuid
        ON CONFLICT DO NOTHING
    """, _EDGE_SRC_UUID, _EDGE_DST_UUID, _VITALTYPE_UUID, timeout=timeout)

    inserted = int(result.split()[-1]) if result else 0
    if inserted:
        # ANALYZE takes SHARE UPDATE EXCLUSIVE — does not block readers/writers.
        await conn.execute(f"ANALYZE {t_edge}", timeout=timeout)
    logger.info("backfill_edge_table(%s): %d rows inserted", space_id, inserted)
    return inserted


async def edge_table_drift(conn, space_id: str,
                           timeout: float | None = None) -> tuple[int, int]:
    """Return (expected_edges, edge_rows) — a cheap, fully-indexed drift signal.

    Takes a CLIENT-side `timeout` for the same reason the backfill it gates
    does (`issues/149`): a probe that dies in the driver reports nothing, and a
    repair gated on a probe that never completes never runs.

    expected_edges = DISTINCT (subject, context) among hasEdgeSource quads.
    edge_rows      = rows currently in {space}_edge.
    A large positive difference means the edge table has drifted behind rdf_quad
    (edges inserted via a path that didn't sync it) and should be resynced.

    DISTINCT, not `count(*)`. The edge table's primary key is
    (edge_uuid, context_uuid) and `resync_edge_table` builds it with
    `DISTINCT ON (src.subject_uuid, src.context_uuid)`, so ONE row exists per
    edge regardless of how many hasEdgeSource QUADS that edge has.

    STALE JUSTIFICATION, CORRECTED 2026-09-03. This used to say `rdf_quad`'s
    primary key includes `quad_uuid`, so identical (subject, predicate, object,
    context) could be stored twice and counting quads would report each
    duplicate as a missing edge. That was true of the schema it was written
    against and is NOT true now: the PK is FOUR columns —
    (subject, predicate, object, context) — so exact duplicates are impossible
    by construction. Measured on production, 3,245,117 quads and 3,245,117
    distinct pairs, zero overcount.

    DO NOT REMOVE THE DISTINCT ON THAT BASIS. It is still required, for a
    different reason: `resync_edge_table` builds this table with
    `DISTINCT ON (src.subject_uuid, src.context_uuid)`, and the four-column PK
    still permits two DIFFERENT objects for the same subject+context. A
    multi-source edge would make `count(*)` overcount against what the table
    actually stores. Zero such edges exist on production today, but that is a
    data invariant, not a schema guarantee. The DISTINCT mirrors the
    DISTINCT ON; that is its real justification.

    THIS QUERY SHOULD NOT EXIST ON A SCHEDULE AT ALL. Both sides are counts the
    write path already knows, and recomputing them from ~50M rows every cycle is
    the defect. See
    `planning/planning_performance/maintenance_incremental_only_plan.md`.

    Measured on the local host cluster 2026-08-16: two spaces reported 31.3% and
    50.0% "missing" and were byte-for-byte correct. 67 source quads over 46
    distinct edges against 46 rows, and 70 over 35 against 35 — and crucially
    `count(DISTINCT (subject, object, context))` was ALSO 46 and 35, so those
    edges are not multi-valued, the surplus quads are exact duplicates. A resync
    changed nothing, twice, which is what a permanently unreachable zero looks
    like from the outside.

    This measure now sees through the duplication. The duplication itself is a
    separate defect in rdf_quad and is not this function's to fix.
    """
    t_edge = f"{space_id}_edge"
    t_quad = f"{space_id}_rdf_quad"
    expected = await conn.fetchval(
        f"SELECT count(DISTINCT (subject_uuid, context_uuid)) FROM {t_quad} "
        f"WHERE predicate_uuid = $1", _EDGE_SRC_UUID, timeout=timeout)
    edge_rows = await conn.fetchval(f"SELECT count(*) FROM {t_edge}", timeout=timeout)
    return int(expected or 0), int(edge_rows or 0)


async def edge_table_orphan_rate(conn, space_id: str, sample: int = 200,
                                 timeout: float | None = None) -> float:
    """Fraction of sampled edge rows that no longer correspond to any quad.

    Carries a CLIENT-side `timeout` for the same reason as its siblings
    (`issues/149`). This one decides backfill-vs-resync, so losing it silently
    does not just delay a repair — it picks the wrong repair.

    `edge_table_drift` compares COUNTS, which cannot see the failure mode in
    issues/041: a space reloaded in place leaves an edge table that is a
    faithful materialisation of the *previous* contents. Observed on wordnet —
    570,696 quads, 570,696 edge rows, and **zero** edge_uuid values in common.
    Identical sizes, disjoint sets, every count check green, every frame
    traversal returning nothing.

    Zero rows is the worst failure mode available here, because an empty result
    satisfies every upper-bound a performance test asserts.

    This asks a different question: do these rows still refer to anything? Each
    sampled edge_uuid should appear as the subject of a hasEdgeSource quad. A
    high orphan rate means stale rather than merely incomplete, and calls for a
    full resync rather than a backfill — backfill only adds, so it cannot
    repair a table whose existing rows are all wrong.

    The context is part of the check, not just the edge identity. Reloading a
    space under a DIFFERENT graph URI leaves every edge row pointing at the old
    context: the edge_uuids still resolve, so an identity-only probe reports a
    healthy 0%, while every edge-rewrite query filters on the new context and
    matches nothing. That happened — sp_lead_synth_100k reloaded from
    urn:lead_synth_100k to urn:sp_lead_synth_100k returned 0 rows for a
    criterion with 9,220 matches, and this probe called it healthy until the
    context was added here.

    Bounded by `sample`: one index probe each, so a few hundred lookups
    regardless of table size.
    """
    t_edge = f"{space_id}_edge"
    t_quad = f"{space_id}_rdf_quad"
    orphans = await conn.fetchval(
        f"""
        SELECT count(*) FROM (
            SELECT edge_uuid, context_uuid FROM {t_edge} LIMIT {int(sample)}
        ) s
        WHERE NOT EXISTS (
            SELECT 1 FROM {t_quad} q
            WHERE q.subject_uuid = s.edge_uuid AND q.predicate_uuid = $1
              AND q.context_uuid = s.context_uuid
        )
        """, _EDGE_SRC_UUID, timeout=timeout)
    checked = await conn.fetchval(
        f"SELECT count(*) FROM (SELECT 1 FROM {t_edge} LIMIT {int(sample)}) s",
        timeout=timeout)
    if not checked:
        return 0.0
    return float(orphans or 0) / float(checked)


async def edge_table_untyped_rate(conn, space_id: str) -> float:
    """Fraction of edge rows with no `edge_type_uuid`. EXACT, not sampled.

    This is a CAPABILITY signal, not a drift signal: it says those rows will not
    match a typed traversal. It is NOT an orphan detector, and reading it as one
    is wrong in the common case.

    Three different conditions produce a NULL, and this number cannot tell them
    apart:

      1. **The column has not been backfilled.** `edge_type_uuid` was added by a
         migration, so every row of a newly-altered table reads NULL until it is
         populated. This is the usual reason, and it means nothing is wrong.
      2. **The space carries no vitaltype triples.** `wordnet_exp` has 1,536,485
         `type` quads and zero `vitaltype`, so all 570,696 of its edge rows read
         untyped while being perfectly live — a property of how it was exported.
      3. **The row is orphaned** — its defining quads were deleted and the edge
         row survived.

    Only (3) is drift, and establishing it needs the referential check that
    `edge_table_orphan_rate` does, or a rebuild from the quads. Orphans were
    real when this was first run — 20,461 across four spaces, 20,306 of them
    (5.3%) in a production-shaped space — but they were confirmed by those rows
    having no quads at all, and by a rebuild removing exactly that many. The
    NULL count agreed only because the backfill had already completed there.

    Returns 0.0 for a space with no edge rows or no column yet.
    """
    t_edge = f"{space_id}_edge"
    try:
        total = await conn.fetchval(f"SELECT count(*) FROM {t_edge}")
        if not total:
            return 0.0
        untyped = await conn.fetchval(
            f"SELECT count(*) FROM {t_edge} WHERE edge_type_uuid IS NULL")
    except Exception:
        return 0.0        # column not migrated in yet
    return float(untyped or 0) / float(total)
