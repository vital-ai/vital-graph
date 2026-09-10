"""Streaming COPY export/import of a space's core data (backup / migration).

Exports the three core data tables — ``datatype``, ``term``, ``rdf_quad`` — via
binary ``COPY … TO`` (streamed to files, constant memory regardless of size).
``import_space`` restores them into a fresh space with ``COPY … FROM``, then
rebuilds everything derived from them (the datatype sequence, and the edge /
frame_entity / stats tables) so the restored space is immediately queryable.

Only the core tables are exported: the edge/frame_entity/geo/stats tables are
deterministic functions of the quads, so shipping them would just bloat the
backup — they are resynced on import instead.

``export_space`` runs all three COPYs in one ``REPEATABLE READ`` snapshot and
records that snapshot in a ``manifest.json`` sidecar, so an export is internally
consistent and can anchor a later catch-up sync.  See
``planning/planning_db/space_sync_and_cutover_plan.md`` §5b.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Dict

from .sparql_sql_schema import SparqlSQLSchema

logger = logging.getLogger(__name__)

# Core data tables, in a safe restore order (no FKs among them today, but keep
# datatype before term before rdf_quad for clarity).
_EXPORT_TABLES = ("datatype", "term", "rdf_quad")

# Sidecar file recording the export's snapshot watermark (see export_space).
_MANIFEST_NAME = "manifest.json"
_MANIFEST_VERSION = 1


def _bare(name: str) -> str:
    return name.split(".")[-1]


async def export_space(conn, space_id: str, dest_dir: str) -> Dict[str, str]:
    """Binary-COPY each core table to ``<dest_dir>/<table>.bin``.

    All three COPYs run inside a single ``REPEATABLE READ`` read-only
    transaction, so they share one snapshot.  This matters twice over:

    - **Consistency.** Under concurrent writes, per-statement snapshots let the
      later ``rdf_quad`` COPY see rows whose terms the earlier ``term`` COPY
      missed, producing an export with quads referencing absent terms.
    - **Catch-up sync.** A single snapshot gives the export one well-defined
      point in time, so a later delta can ask exactly "what changed since?".

    That snapshot is recorded in ``<dest_dir>/manifest.json`` (see
    ``read_export_manifest``) as a ``pg_snapshot`` watermark — the correct basis
    for a catch-up, unlike a wall-clock time: a transaction that starts before
    the export and commits after it writes rows with an *earlier* timestamp that
    were nonetheless invisible to the export, so a ``ts > watermark`` delta
    silently loses them.  ``pg_visible_in_snapshot(xmin, watermark)`` does not.

    Returns a ``{logical_table: file_path}`` map (plus a ``"manifest"`` key).
    Streams row-by-row, so peak memory is independent of table size.
    """
    t = SparqlSQLSchema.get_table_names(space_id)
    os.makedirs(dest_dir, exist_ok=True)
    paths: Dict[str, str] = {}

    async with conn.transaction(isolation="repeatable_read", readonly=True):
        # Read the watermark INSIDE the transaction, before any COPY: it must
        # describe the same snapshot the COPYs see.
        snapshot = await conn.fetchval("SELECT pg_current_snapshot()::text")
        # WAL position, for a slot/LSN-based catch-up. Unavailable on a standby
        # (and irrelevant there), so never let it fail the export.
        try:
            lsn = await conn.fetchval("SELECT pg_current_wal_lsn()::text")
        except Exception:
            lsn = None

        for key in _EXPORT_TABLES:
            table = _bare(t[key])
            path = os.path.join(dest_dir, f"{table}.bin")
            await conn.copy_from_table(table, output=path, format="binary")
            paths[key] = path
            logger.info("export_space(%s): %s -> %s", space_id, table, path)

    manifest = {
        "space_id": space_id,
        "version": _MANIFEST_VERSION,
        "snapshot": snapshot,
        "wal_lsn": lsn,
        "tables": {k: os.path.basename(v) for k, v in paths.items()},
    }
    manifest_path = os.path.join(dest_dir, _MANIFEST_NAME)
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    paths["manifest"] = manifest_path
    logger.info("export_space(%s): snapshot watermark %s -> %s",
                space_id, snapshot, manifest_path)
    return paths


def read_export_manifest(dest_dir: str) -> Dict[str, object]:
    """Load the manifest written alongside an export (see ``export_space``).

    The ``snapshot`` field is the watermark for a catch-up sync:

    .. code-block:: sql

        SELECT … FROM {space}_rdf_quad
        WHERE NOT pg_visible_in_snapshot(xmin::text::xid8, $1::text::pg_snapshot)

    Raises ``FileNotFoundError`` for exports taken before manifests existed —
    those have no single point in time and cannot anchor a catch-up.
    """
    with open(os.path.join(dest_dir, _MANIFEST_NAME), encoding="utf-8") as fh:
        return json.load(fh)


async def import_space(conn, space_id: str, paths: Dict[str, str],
                       resync: bool = True) -> Dict[str, int]:
    """Restore core tables from binary-COPY files into ``space_id``.

    TRUNCATEs the core tables first (a fresh space still has the seeded standard
    datatypes, which the import overwrites with the source's exact rows), COPYs
    each file in, resets the datatype id sequence, and — when ``resync`` —
    rebuilds EVERY derived table.  Returns core-table row counts.  Runs inside
    the caller's transaction.

    NOTHING IS LEFT DESCRIBING THE PREVIOUS CONTENTS (``issues/168``).  This
    used to rebuild a hand-picked list — edge, frame_entity, stats — and the
    list went stale when a fourth derived table arrived: ``entity_slot_sort``
    was never rebuilt and ``slot_sort_coverage`` was never cleared.

    Since this TRUNCATEs and re-COPYs, it is designed to restore OVER an
    existing space, so a restore left the quads holding the NEW contents, the
    slot-sort table holding rows derived from the OLD ones, and a marker still
    vouching for it — and ``fast_slot_filter`` served a confident, plausible
    answer computed from data that was no longer there.

    The same omission this function already had once: ``graph_registry`` records
    it copying a whole space in and registering NO graphs (``issues/116``).

    THE SHORT DERIVATIONS RUN INLINE, THE LONG ONE IS HANDED OFF.  This holds
    ACCESS EXCLUSIVE on the core tables until the caller commits, so every
    statement here extends the window in which the space answers nothing.
    ``entity_slot_sort`` is rebuilt in MINUTES on a large space, so it is
    emptied and left to the batched backfill job rather than rebuilt under the
    lock — blocking application queries behind a rebuild is the outage this work
    exists to remove, not a cost to pay for it.

    ``resync=False`` CLEARS THE MARKER rather than leaving it.  A caller opting
    out of the rebuild is opting into a derived set that does not describe the
    restored quads, and the marker must not keep vouching for it.
    """
    t = SparqlSQLSchema.get_table_names(space_id)
    core = [_bare(t[k]) for k in _EXPORT_TABLES]
    await conn.execute(f"TRUNCATE {', '.join(core)}")

    for key in _EXPORT_TABLES:
        await conn.copy_to_table(_bare(t[key]), source=paths[key], format="binary")

    # COPY does not advance the datatype_id BIGSERIAL — realign it so later
    # datatype inserts don't collide with restored ids.
    dt = _bare(t["datatype"])
    await conn.execute(
        f"SELECT setval(pg_get_serial_sequence('{dt}', 'datatype_id'), "
        f"COALESCE((SELECT max(datatype_id) FROM {dt}), 1))")

    # Register the graphs the restored quads are in. COPY writes context_uuid
    # and nothing else, so none of the impl's write hooks fire and the
    # destination ended up holding data in a graph the catalog had never heard
    # of — the same space, exported and re-imported, disagreeing with itself
    # (issues/116).
    #
    # BEFORE the derivations, not after. Anything deriving per-graph reads this
    # catalog, so registering afterwards means those steps see an empty graph
    # list and silently produce nothing.
    from .graph_registry import register_graphs_from_data
    await register_graphs_from_data(conn, space_id)

    if resync:
        # THE HEAVY DERIVATION IS DEFERRED, NOT SKIPPED (`issues/168`).
        #
        # This runs inside the caller's transaction, and the TRUNCATE above took
        # ACCESS EXCLUSIVE on the core tables — so every statement between here
        # and COMMIT extends the window in which this space answers nothing.
        # `resync_entity_slot_sort` is by far the longest of the derivations
        # (measured in MINUTES on a 53M-quad space), and holding an exclusive
        # lock across it is the shape of outage this repository already has an
        # issue about: rebuild work blocking the application queries it exists
        # to make fast (`issues/161`).
        #
        # So the restore does the SHORT derivations that queries cannot be
        # correct without — edge, frame_entity, stats — and hands the long one
        # to the job that is built for it: `backfill_entity_slot_sort_batch`,
        # bounded per batch, fenced, and already running on a duty cycle
        # (`issues/150`).
        #
        # SAFE ONLY BECAUSE BOTH READ PATHS ARE GATED. The slot-sort table is
        # emptied rather than left stale, and the marker is cleared, so the
        # filter AND sort paths decline and every query is answered by the
        # general SPARQL pipeline — slower, and correct. Before the sort path
        # was gated this would have served empty pages as "no results".
        from .sync_edge_table import resync_edge_table
        from .sync_frame_slot_table import resync_frame_slot_table
        from .sync_stats_tables import recompute_stats_tables
        await resync_edge_table(conn, space_id)
        await resync_frame_slot_table(conn, space_id)
        await recompute_stats_tables(conn, space_id)
        try:
            async with conn.transaction():
                await conn.execute(f"TRUNCATE {_bare(t['entity_slot_sort'])}")
        except Exception as exc:
            # A space predating the table. Nothing to empty, nothing stale.
            logger.debug("import_space(%s): no entity_slot_sort to clear (%s)",
                         space_id, exc)
        # GEO IS REBUILT INLINE (`issues/169`), unlike entity_slot_sort.
        #
        # It is derived from the quads, so a restore that leaves it holding the
        # PREVIOUS contents produces wrong geo answers, not slow ones — and
        # emptying it is no safer, because the read path is a correlated
        # subquery, `SELECT MIN(ST_Distance(...)) FROM {space}_geo WHERE
        # subject_uuid = ...`, which yields NULL for an absent row. A geo filter
        # over an empty table therefore excludes every entity, silently.
        #
        # So it cannot be deferred the way the slot-sort table is: there is no
        # marker gating the geo read, and both stale and empty are wrong. It is
        # rebuilt here because it is CHEAP ENOUGH TO BE — measured 2,268 ms on a
        # 74.2M-quad space and 476 ms on an 8.9M one, against the 45 minutes
        # entity_slot_sort takes. Detection is datatype-driven, so the cost
        # tracks geo literals rather than the size of the space.
        try:
            from ...vectorization.geo_populator import populate_geo
            n_geo = 0
            for gr in await conn.fetch(
                    "SELECT graph_uri FROM graph WHERE space_id = $1", space_id):
                gctx = await conn.fetchval(
                    f"SELECT term_uuid FROM {_bare(t['term'])} "
                    f" WHERE term_text = $1 AND term_type = 'U' LIMIT 1",
                    gr["graph_uri"])
                if gctx is not None:
                    st = await populate_geo(conn, space_id, gctx)
                    n_geo += getattr(st, "points_upserted", 0) or 0
            logger.info("import_space(%s): geo rebuilt, %d point(s)",
                        space_id, n_geo)
        except Exception as exc:
            # Fail-safe and LOUD. A geo table left describing the previous
            # contents answers geo queries wrongly, so this is not a
            # nice-to-have that can be swallowed at debug level.
            logger.warning(
                "import_space(%s): geo NOT rebuilt (%s) — geo queries on this "
                "space may answer from the PREVIOUS contents until "
                "resync_all_auxiliary_tables is run", space_id, exc)

        from .fast_slot_filter import (clear_slot_sort_coverage,
                                       take_slot_sort_block)
        await clear_slot_sort_coverage(conn, space_id)
        # The block is what makes the deferral safe (`issues/167`). Clearing the
        # measurements is not a refusal under a block-list — absence means
        # SERVE — so without this the emptied table would be served as an
        # authoritative empty answer. Released by the backfill job when it
        # verifies coverage, not by this function.
        await take_slot_sort_block(
            conn, space_id, None,
            reason="restored; entity_slot_sort awaiting backfill")
        logger.info(
            "import_space(%s): edge/frame_entity/stats rebuilt inline; "
            "entity_slot_sort emptied and its coverage cleared — the fast "
            "paths decline until the backfill job converges, or until "
            "scripts/backfill_slot_sort_coverage.py --space %s is run",
            space_id, space_id)
    else:
        # The derived tables now describe the PREVIOUS contents. Absence of a
        # marker makes `fast_slot_filter` decline, which is slow and correct;
        # leaving a stale one makes it serve rows for entities that no longer
        # exist.
        from .fast_slot_filter import (clear_slot_sort_coverage,
                                       take_slot_sort_block)
        await clear_slot_sort_coverage(conn, space_id)
        await take_slot_sort_block(
            conn, space_id, None,
            reason="restored with resync=False; derived tables not rebuilt")
        logger.warning(
            "import_space(%s): resync=False — the derived tables still describe "
            "the PREVIOUS contents. Slot-sort coverage cleared so the filter "
            "fast path declines; run resync_all_auxiliary_tables (or "
            "scripts/backfill_slot_sort_coverage.py) before serving this space.",
            space_id)

    counts = {}
    for key in _EXPORT_TABLES:
        counts[key] = await conn.fetchval(f"SELECT count(*) FROM {_bare(t[key])}")
    logger.info("import_space(%s): restored %s", space_id, counts)
    return counts


# ---------------------------------------------------------------------------
# RDF (N-Quads) export — reconstruct portable RDF from the UUID-encoded tables
# ---------------------------------------------------------------------------

def _nt_term_sql(alias: str, dt_alias: str = None) -> str:
    """SQL expression rendering term row `alias` as an N-Triples/N-Quads term.

    'U'/'G' -> <iri>; 'B' -> _:label; 'L' -> "escaped"(@lang | ^^<datatype>).
    Literal text is escaped per the N-Triples grammar (backslash first).
    """
    esc = (f"replace(replace(replace(replace(replace({alias}.term_text, "
           r"E'\\', E'\\\\'), E'\"', E'\\\"'), E'\n', E'\\n'), "
           r"E'\r', E'\\r'), E'\t', E'\\t')")
    lit_suffix = (
        f"CASE WHEN {alias}.lang IS NOT NULL AND {alias}.lang <> '' "
        f"THEN '@' || {alias}.lang ")
    if dt_alias:
        lit_suffix += (f"WHEN {dt_alias}.datatype_uri IS NOT NULL "
                       f"THEN '^^<' || {dt_alias}.datatype_uri || '>' ")
    lit_suffix += "ELSE '' END"
    return (
        f"CASE {alias}.term_type "
        f"WHEN 'U' THEN '<' || {alias}.term_text || '>' "
        f"WHEN 'G' THEN '<' || {alias}.term_text || '>' "
        f"WHEN 'B' THEN '_:' || {alias}.term_text "
        f"WHEN 'L' THEN '\"' || {esc} || '\"' || ({lit_suffix}) "
        f"ELSE '<' || {alias}.term_text || '>' END")


async def export_space_to_nquads(conn, space_id: str, output_path: str,
                                 graph_uri: str = None, limit: int = None) -> int:
    """Stream a space's quads to `output_path` as N-Quads (one quad per line).

    Reconstructs real RDF from the UUID tables (4-way term join + datatype),
    formatting each row server-side and COPYing the text stream to the file, so
    peak memory is independent of size. Optionally restrict to one `graph_uri`
    (context) and/or `limit` rows. Returns the number of quads written.
    """
    t = SparqlSQLSchema.get_table_names(space_id)
    q, term, dtab = _bare(t["rdf_quad"]), _bare(t["term"]), _bare(t["datatype"])

    where = ""
    if graph_uri is not None:
        from .sparql_sql_space_impl import _generate_term_uuid
        g_uuid = _generate_term_uuid(graph_uri, "U")
        where = f"WHERE q.context_uuid = '{g_uuid}'"
    lim = f"LIMIT {int(limit)}" if limit else ""

    line = (f"{_nt_term_sql('ts')} || ' ' || {_nt_term_sql('tp')} || ' ' || "
            f"{_nt_term_sql('tobj', 'd')} || ' ' || {_nt_term_sql('tc')} || ' .'")
    query = (
        f"SELECT {line} FROM {q} q "
        f"JOIN {term} ts ON ts.term_uuid = q.subject_uuid "
        f"JOIN {term} tp ON tp.term_uuid = q.predicate_uuid "
        f"JOIN {term} tobj ON tobj.term_uuid = q.object_uuid "
        f"JOIN {term} tc ON tc.term_uuid = q.context_uuid "
        f"LEFT JOIN {dtab} d ON d.datatype_id = tobj.datatype_id "
        f"{where} {lim}")

    # Server-side cursor (constant memory), batched. NOT COPY: COPY's text
    # format would re-escape the already-N-Triples-escaped lines.
    written = 0
    with open(output_path, "w", encoding="utf-8") as fh:
        async with conn.transaction():
            cur = await conn.cursor(query)
            while True:
                rows = await cur.fetch(10_000)
                if not rows:
                    break
                fh.write("\n".join(r[0] for r in rows))
                fh.write("\n")
                written += len(rows)

    # The 4 term joins are INNER, so any quad whose subject/predicate/object/
    # context term is absent from the term table is dropped (unrenderable).
    # Report it rather than silently losing rows.
    if graph_uri is None and not limit:
        total = await conn.fetchval(f"SELECT count(*) FROM {q}")
        if written < total:
            logger.warning(
                "export_space_to_nquads(%s): dropped %d of %d quads with a "
                "term missing from the term table (unrenderable)",
                space_id, total - written, total)

    logger.info("export_space_to_nquads(%s): %d quads -> %s",
                space_id, written, output_path)
    return written
