"""
Maintenance Job — periodic ANALYZE / VACUUM scoring and execution.

Runs every N minutes (default 5). Each cycle:
1. Queries pg_stat_user_tables for all space tables
2. Scores each space independently for ANALYZE need and VACUUM need
3. Runs at most one AnalyzeOp and one VacuumOp per cycle (possibly different spaces)
4. Records results in the process table
5. Optionally runs cleanup of old process records (once per day)

Freshness thresholds (skip if ALL true):
- ANALYZE: n_mod_since_analyze < 10,000 AND last_analyze < 10 min ago
- VACUUM:  n_dead_tup < 10,000 AND last_vacuum < 30 min ago
"""

import asyncio
import logging
import os
import platform
import socket
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Freshness thresholds
# ---------------------------------------------------------------------------
ANALYZE_MOD_THRESHOLD = 10_000       # skip if fewer mods since last analyze
ANALYZE_STALENESS_MINUTES = 10       # skip if analyzed within this many minutes
VACUUM_DEAD_THRESHOLD = 10_000       # skip if fewer dead tuples
VACUUM_STALENESS_MINUTES = 30        # skip if vacuumed within this many minutes

# Edge-table integrity: resync {space}_edge when it has drifted behind rdf_quad
# (edges inserted via a path that didn't sync it). Drift = hasEdgeSource quads
# minus edge rows; resync when it exceeds both an absolute and a relative floor.
EDGE_DRIFT_MIN_ABS = 1_000           # ignore drift below this many edges
EDGE_DRIFT_MIN_PCT = 0.01            # ...and below this fraction of edges

# Value histograms: rebuild a space once a predicate's row count has moved this
# far from the count its histogram was built at.
#
# Deliberately far above the read path's DRIFT_EPSILON (0.02). That one decides
# whether a shape probe is worth a QUERY; this decides whether seconds of
# rebuild are worth spending, and at 2% a busy space would rebuild constantly.
# 0.50 is chosen against the measured curve rather than by feel: growth is
# CORRECTED by scaling to at least 3.00x with the error flat at the histogram's
# own resolution, so waiting this long costs accuracy only for a genuine shape
# change — and a shape change is WITHDRAWN at read time, not served wrong. So
# the cost of a late rebuild is exact counts, never a bad estimate.
VALUE_STATS_DRIFT_THRESHOLD = 0.50
# Above this fraction of sampled edge rows referencing vanished quads, the table
# is stale rather than incomplete. Set high because a partially-backfilled table
# has a genuinely low orphan rate; only a wholesale mismatch should trip it.
EDGE_ORPHAN_STALE_PCT = 0.5
# Fraction of edge rows with no edge_type_uuid worth mentioning. Informational
# only: a NULL means the row will not match a TYPED traversal, which is most
# often just an un-backfilled column after the migration that added it. It is
# not a staleness signal — see the note at the log site.
EDGE_UNTYPED_WARN_PCT = 0.01

# Spaces to sweep for orphans per cycle. Each pass examines a bounded window and
# costs real time (~12 s per 100k rows), so this trades convergence speed for a
# predictable cycle length. Unswept spaces are re-queued, not dropped.
_SWEEP_SPACES_PER_CYCLE = 2

# Cleanup
CLEANUP_RETENTION_DAYS = 30
_SECONDS_PER_DAY = 86_400

# Vector index REINDEX thresholds
VECTOR_REINDEX_DEAD_RATIO = 0.20     # reindex if dead_tup / n_live_tup > 20%
VECTOR_REINDEX_MIN_DEAD = 1_000      # skip if fewer dead tuples than this
VECTOR_REINDEX_COOLDOWN_HOURS = 24   # skip if reindexed within this many hours


def _get_instance_id() -> str:
    """Resolve instance identifier: ECS task ID → hostname fallback."""
    # ECS task metadata v4
    meta_uri = os.environ.get("ECS_CONTAINER_METADATA_URI_V4")
    if meta_uri:
        try:
            import urllib.request, json
            with urllib.request.urlopen(meta_uri + "/task", timeout=2) as resp:
                data = json.loads(resp.read())
                task_arn = data.get("TaskARN", "")
                # arn:aws:ecs:region:account:task/cluster/task-id
                return task_arn.rsplit("/", 1)[-1] if "/" in task_arn else task_arn
        except Exception:
            pass
    return socket.gethostname()


class MaintenanceJob:
    """
    Evaluates ANALYZE and VACUUM needs across all spaces and executes
    at most one of each per cycle.

    Also handles process-record cleanup (once per day).
    """

    def __init__(self, pool, process_tracker=None, postgresql_config: Optional[Dict] = None):
        """
        Args:
            pool: asyncpg connection pool (used for lightweight async ops).
            process_tracker: Optional ProcessTracker for recording results.
            postgresql_config: PostgreSQL connection dict (host, port, database,
                username, password).  When provided, ANALYZE / VACUUM / stats
                queries run in a background thread via a dedicated psycopg
                sync connection so they never block the event loop.
        """
        self._pool = pool
        self._tracker = process_tracker
        self._pg_config = postgresql_config
        self._instance_id = _get_instance_id()
        self._last_cleanup: Optional[float] = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self) -> Dict:
        """Execute one maintenance cycle. Returns summary dict."""
        summary: Dict = {"analyze": None, "vacuum": None, "cleanup": False,
                         "vector_reindex": None, "value_stats": None,
                         "aborted": None}
        start = time.monotonic()

        try:
            stats = await self._fetch_space_stats()
            if not stats:
                logger.info("MaintenanceJob: no space tables found, skipping")
                return summary

            logger.info(
                "MaintenanceJob: scored %d space(s): %s",
                len(stats),
                ", ".join(
                    f"{sid}(mods={s['n_mod_since_analyze']}, dead={s['n_dead_tup']})"
                    for sid, s in stats.items()
                ),
            )

            # --- ANALYZE ---
            analyze_space = self._pick_worst_for_analyze(stats)
            if analyze_space:
                summary["analyze"] = await self._run_analyze(analyze_space)

            # --- VACUUM ---
            vacuum_space = self._pick_worst_for_vacuum(stats)
            if vacuum_space:
                summary["vacuum"] = await self._run_vacuum(vacuum_space)

            # --- Edge-table integrity (backfill worst-drifted space) ---
            edge_result = await self._run_edge_integrity(list(stats.keys()))
            if edge_result:
                summary["edge_integrity"] = edge_result

            # --- Frame-entity integrity (derived from edge; backfill after) ---
            fe_result = await self._run_frame_entity_integrity(list(stats.keys()))
            if fe_result:
                summary["frame_entity_integrity"] = fe_result

            # --- Stats prune (bound rdf_stats to the reorder window) ---
            stats_prune_result = await self._run_stats_prune(list(stats.keys()))
            if stats_prune_result:
                summary["stats_prune"] = stats_prune_result

            # --- Value histograms (rebuild the worst-drifted space) ---
            vstats_result = await self._run_value_stats_refresh(list(stats.keys()))
            if vstats_result:
                summary["value_stats"] = vstats_result

            # --- Vector index REINDEX ---
            vector_result = await self._run_vector_reindex(list(stats.keys()))
            if vector_result:
                summary["vector_reindex"] = vector_result

            # --- Cleanup (once per day) ---
            if self._should_cleanup():
                summary["cleanup"] = await self._run_cleanup()

        except Exception as e:
            # One `except` covers the whole cycle, so a failure in ANY step
            # silently skips every step after it. The completion line below then
            # reports the untouched steps as None/False, which reads exactly
            # like a cycle that had nothing to do — which is how a per-cycle
            # InterfaceError went unnoticed. Record it so it cannot.
            summary["aborted"] = f"{type(e).__name__}: {e}"
            logger.error("MaintenanceJob cycle error: %s", e, exc_info=True)

        elapsed = (time.monotonic() - start) * 1000
        if summary["aborted"]:
            logger.error(
                "MaintenanceJob cycle ABORTED after %.0fms (%s) — analyze=%s "
                "vacuum=%s; every later step was SKIPPED, not clean",
                elapsed, summary["aborted"], summary["analyze"],
                summary["vacuum"],
            )
        else:
            logger.info(
                "MaintenanceJob cycle complete in %.0fms — analyze=%s vacuum=%s vector_reindex=%s cleanup=%s",
                elapsed,
                summary["analyze"],
                summary["vacuum"],
                summary["vector_reindex"],
                summary["cleanup"],
            )
        return summary

    # ------------------------------------------------------------------
    # On-demand triggers (bypass freshness checks)
    # ------------------------------------------------------------------

    async def trigger_analyze(self, space_id: str) -> Optional[Dict]:
        """Run ANALYZE on a specific space immediately."""
        return await self._run_analyze(space_id)

    async def trigger_vacuum(self, space_id: str) -> Optional[Dict]:
        """Run VACUUM on a specific space immediately."""
        return await self._run_vacuum(space_id)

    async def trigger_stats_rebuild(self, space_id: str) -> Optional[Dict]:
        """Run stats rebuild on a specific space immediately."""
        return await self._run_stats_rebuild(space_id)

    async def trigger_vector_reindex(self, space_id: str) -> Optional[Dict]:
        """Run vector index REINDEX on a specific space immediately (bypasses cooldown)."""
        return await self._run_vector_reindex([space_id], force=True)

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    async def _fetch_space_stats(self) -> Dict[str, Dict]:
        """Query pg_stat_user_tables for space tables, grouped by space_id.

        If a psycopg config is available the query runs in a background thread
        so it never blocks the event loop.

        Returns:
            {space_id: {n_mod_since_analyze, last_analyze, n_dead_tup, last_vacuum, ...}}
        """
        if self._pg_config:
            return await asyncio.to_thread(self._sync_fetch_space_stats)

        # Fallback: use the asyncpg pool directly
        return await self._async_fetch_space_stats()

    async def _async_fetch_space_stats(self) -> Dict[str, Dict]:
        """asyncpg-based stats fetch (original implementation)."""
        query = """
            SELECT
                relname,
                n_dead_tup,
                n_mod_since_analyze,
                last_analyze,
                last_autoanalyze,
                last_vacuum,
                last_autovacuum
            FROM pg_stat_user_tables
            WHERE relname LIKE '%\\_rdf\\_quad' OR relname LIKE '%\\_term'
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query)
        return self._aggregate_space_stats(rows)

    def _sync_fetch_space_stats(self) -> Dict[str, Dict]:
        """Thread-safe stats fetch using a dedicated psycopg connection."""
        import psycopg
        import psycopg.rows
        conn = self._make_sync_connection()
        try:
            with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                cur.execute("""
                    SELECT
                        relname,
                        n_dead_tup,
                        n_mod_since_analyze,
                        last_analyze,
                        last_autoanalyze,
                        last_vacuum,
                        last_autovacuum
                    FROM pg_stat_user_tables
                    WHERE relname LIKE '%\\_rdf\\_quad' OR relname LIKE '%\\_term'
                """)
                rows = cur.fetchall()
        finally:
            conn.close()
        return self._aggregate_space_stats(rows)

    @staticmethod
    def _aggregate_space_stats(rows) -> Dict[str, Dict]:
        """Aggregate per-table pg_stat rows into per-space summaries."""
        spaces: Dict[str, Dict] = {}
        for row in rows:
            relname = row["relname"]
            if relname.endswith("_rdf_quad"):
                sid = relname[: -len("_rdf_quad")]
            elif relname.endswith("_term"):
                sid = relname[: -len("_term")]
            else:
                continue

            if sid not in spaces:
                spaces[sid] = {
                    "n_mod_since_analyze": 0,
                    "last_analyze": None,
                    "n_dead_tup": 0,
                    "last_vacuum": None,
                }

            entry = spaces[sid]
            entry["n_mod_since_analyze"] += row["n_mod_since_analyze"] or 0
            entry["n_dead_tup"] += row["n_dead_tup"] or 0

            last_a = row["last_analyze"] or row["last_autoanalyze"]
            if last_a is not None:
                if entry["last_analyze"] is None or last_a < entry["last_analyze"]:
                    entry["last_analyze"] = last_a

            last_v = row["last_vacuum"] or row["last_autovacuum"]
            if last_v is not None:
                if entry["last_vacuum"] is None or last_v < entry["last_vacuum"]:
                    entry["last_vacuum"] = last_v

        return spaces

    def _pick_worst_for_analyze(self, stats: Dict[str, Dict]) -> Optional[str]:
        """Pick the space most in need of ANALYZE, or None if all are fresh."""
        now = datetime.now(timezone.utc)
        best_space = None
        best_score = -1.0

        for sid, s in stats.items():
            mods = s["n_mod_since_analyze"]
            last = s["last_analyze"]
            minutes_since = (
                (now - last).total_seconds() / 60.0 if last else float("inf")
            )

            # Fresh enough → skip
            if mods < ANALYZE_MOD_THRESHOLD and minutes_since < ANALYZE_STALENESS_MINUTES:
                continue

            # Score: mods weighted by staleness.  When mods == 0 but
            # last_analyze is None (never analyzed), use staleness alone
            # so the space is still eligible.
            if mods == 0:
                score = minutes_since   # inf when never analyzed
            else:
                score = mods * (1.0 + minutes_since / 60.0)
            if score > best_score:
                best_score = score
                best_space = sid

        if best_space:
            logger.info("MaintenanceJob: ANALYZE pick → %s (score=%.1f)", best_space, best_score)
        else:
            logger.info("MaintenanceJob: all spaces fresh for ANALYZE, skipping")
        return best_space

    def _pick_worst_for_vacuum(self, stats: Dict[str, Dict]) -> Optional[str]:
        """Pick the space most in need of VACUUM, or None if all are fresh."""
        now = datetime.now(timezone.utc)
        best_space = None
        best_score = -1.0

        for sid, s in stats.items():
            dead = s["n_dead_tup"]
            last = s["last_vacuum"]
            minutes_since = (
                (now - last).total_seconds() / 60.0 if last else float("inf")
            )

            # Fresh enough → skip
            if dead < VACUUM_DEAD_THRESHOLD and minutes_since < VACUUM_STALENESS_MINUTES:
                continue

            # Score: dead tuples weighted by staleness.  When dead == 0
            # but last_vacuum is None (never vacuumed), use staleness alone.
            if dead == 0:
                score = minutes_since   # inf when never vacuumed
            else:
                score = dead * (1.0 + minutes_since / 60.0)
            if score > best_score:
                best_score = score
                best_space = sid

        if best_space:
            logger.info("MaintenanceJob: VACUUM pick → %s (score=%.1f)", best_space, best_score)
        else:
            logger.info("MaintenanceJob: all spaces fresh for VACUUM, skipping")
        return best_space

    # ------------------------------------------------------------------
    # Execution helpers
    # ------------------------------------------------------------------

    async def _run_analyze(self, space_id: str) -> Dict:
        """Run ANALYZE on space tables.

        When *postgresql_config* is available, the work runs in a background
        thread via a dedicated psycopg connection (autocommit=True) so the
        event loop is never blocked.
        """
        process_id = None
        if self._tracker:
            process_id = await self._tracker.create_process(
                "analyze", process_subtype=space_id, instance_id=self._instance_id, status="running"
            )
            await self._tracker.mark_running(process_id, self._instance_id)

        tables = self._space_tables(space_id)
        try:
            if self._pg_config:
                analyzed = await asyncio.to_thread(self._sync_run_tables, "ANALYZE", tables)
            else:
                analyzed = await self._async_run_tables("ANALYZE", tables)

            result = {"space_id": space_id, "tables_analyzed": analyzed}
            if self._tracker and process_id:
                await self._tracker.mark_completed(process_id, result_details=result)
            logger.info("ANALYZE complete: space=%s tables=%d", space_id, analyzed)
            return result

        except Exception as e:
            if self._tracker and process_id:
                await self._tracker.mark_failed(process_id, str(e))
            logger.error("ANALYZE failed for space %s: %s", space_id, e)
            return {"space_id": space_id, "error": str(e)}

    async def _run_vacuum(self, space_id: str) -> Dict:
        """Run VACUUM on space tables.

        When *postgresql_config* is available, the work runs in a background
        thread via a dedicated psycopg connection (autocommit=True) so the
        event loop is never blocked.
        """
        process_id = None
        if self._tracker:
            process_id = await self._tracker.create_process(
                "vacuum", process_subtype=space_id, instance_id=self._instance_id, status="running"
            )
            await self._tracker.mark_running(process_id, self._instance_id)

        tables = self._space_tables(space_id)
        try:
            if self._pg_config:
                vacuumed = await asyncio.to_thread(self._sync_run_tables, "VACUUM", tables)
            else:
                vacuumed = await self._async_run_tables("VACUUM", tables)

            result = {"space_id": space_id, "tables_vacuumed": vacuumed}
            if self._tracker and process_id:
                await self._tracker.mark_completed(process_id, result_details=result)
            logger.info("VACUUM complete: space=%s tables=%d", space_id, vacuumed)
            return result

        except Exception as e:
            if self._tracker and process_id:
                await self._tracker.mark_failed(process_id, str(e))
            logger.error("VACUUM failed for space %s: %s", space_id, e)
            return {"space_id": space_id, "error": str(e)}

    async def _run_stats_prune(self, space_ids: List[str]) -> Optional[Dict]:
        """Prune the single space whose rdf_stats is most over its cap.

        rdf_stats accumulates one row per (predicate, object) pair — at scale
        dominated by row_count=1 singletons the join reorder never reads.
        prune_stats_tables bounds it to the reorder's window without changing the
        reorder's input (two DELETEs, cheap). One space per cycle. Uses the
        pg_class.reltuples estimate to pick the target (no full COUNT).
        """
        from ..db.sparql_sql.sync_stats_tables import (
            prune_stats_tables, STATS_KEEP_DEFAULT)

        worst_space = None
        worst_rows = 0.0
        for space_id in space_ids:
            try:
                async with self._pool.acquire() as conn:
                    rows = await conn.fetchval(
                        "SELECT reltuples FROM pg_class WHERE relname = $1",
                        f"{space_id}_rdf_stats")
            except Exception:
                continue  # no rdf_stats table (e.g. non-KG) — skip
            if rows and rows > STATS_KEEP_DEFAULT and rows > worst_rows:
                worst_rows, worst_space = rows, space_id

        if not worst_space:
            return None

        async with self._pool.acquire() as conn:
            kept = await prune_stats_tables(conn, worst_space)
        result = {"space_id": worst_space, "est_before": int(worst_rows), "kept": kept}
        logger.info("Stats prune: %s ~%d → %d rows", worst_space, int(worst_rows), kept)
        return result

    async def _run_value_stats_refresh(self, space_ids: List[str]) -> Optional[Dict]:
        """Rebuild the value histograms for the single worst-drifted space.

        THE MIDDLE CASE, which nothing else covers. A bulk load rebuilds these
        (`add_rdf_quads_batch_bulk`), and `apply_freshness` keeps a drifted
        histogram SAFE at read time by scaling it for growth or withdrawing it
        on a shape change. Neither ever makes one ACCURATE again. A space that
        accumulates small writes therefore degrades permanently: estimates get
        withdrawn, every range criterion falls back to an exact count, and the
        traversal criterion gate stops seeing a measured criterion at all.

        There is no incremental form — bucket boundaries move as the
        distribution does (`stats_table_freshness_plan.md`, candidate 4) — so
        repair is a full rebuild, which is why it belongs here rather than on a
        write path. Measured: 1.3 s on 2.5M quads, 9.3 s on 19.6M.

        DETECTION IS FREE AND USES WHAT IS ALREADY STORED. `pred_rows` is the
        predicate's row count as of the build; `rdf_pred_stats` is maintained on
        every write. Their ratio is the drift, and both tables are tiny, so this
        is one small indexed join per space with no scan of anything.

        The threshold is deliberately far above the read path's. `DRIFT_EPSILON`
        (2%) decides whether a shape probe is worth a query; this decides
        whether seconds of rebuild are worth spending, and rebuilding for a 2%
        change would mean rebuilding constantly. Growth up to this point is
        already CORRECTED by scaling rather than merely tolerated, so waiting
        costs accuracy only for a genuine shape change — which the read-time
        guard withdraws rather than serving wrong.
        """
        from ..db.sparql_sql.sync_value_stats import resync_value_stats

        worst_space, worst_drift, worst_n = None, 0.0, 0
        for space_id in space_ids:
            try:
                async with self._pool.acquire() as conn:
                    row = await conn.fetchrow(f"""
                        SELECT count(*) AS n,
                               max(abs(ps.row_count::float8 / vs.pred_rows - 1)) AS d
                        FROM {space_id}_rdf_value_stats vs
                        JOIN {space_id}_rdf_pred_stats ps
                          ON ps.predicate_uuid = vs.predicate_uuid
                        WHERE vs.pred_rows IS NOT NULL AND vs.pred_rows > 0
                          AND abs(ps.row_count::float8 / vs.pred_rows - 1)
                              > {VALUE_STATS_DRIFT_THRESHOLD}""")
            except Exception:
                continue          # no histograms yet, or a non-KG space
            if row and row["n"] and (row["d"] or 0) > worst_drift:
                worst_space, worst_drift, worst_n = space_id, row["d"], row["n"]

        if not worst_space:
            return None

        # Guarded, unlike the neighbouring steps, because of the hazard this
        # cycle documents about itself: one `except` covers the whole run, so a
        # throw here would silently skip every step after it. A full rebuild is
        # up to 9.3 s of real work against a live pool, which makes it the most
        # plausible place in the cycle to time out — and losing an accurate
        # histogram must not also cost the vector reindex and the cleanup.
        try:
            async with self._pool.acquire() as conn:
                built = await resync_value_stats(conn, worst_space)
        except Exception as exc:
            logger.warning("Value stats refresh failed for %s: %s — estimates "
                           "stay scaled or withdrawn until the next cycle",
                           worst_space, exc)
            return {"space_id": worst_space, "drifted_histograms": worst_n,
                    "failed": f"{type(exc).__name__}: {exc}"}
        # The rebuild moves the reference every cached freshness verdict was
        # taken against, so they have to go with it.
        try:
            from ..db.sparql_sql.generator import invalidate_stats_cache
            invalidate_stats_cache(worst_space)
        except Exception:
            pass
        result = {"space_id": worst_space, "drifted_histograms": worst_n,
                  "worst_drift": round(worst_drift, 3), "rebuilt": built}
        logger.info("Value stats refresh: %s — %d histogram(s) past %.0f%% "
                    "drift (worst %.2fx), rebuilt %s",
                    worst_space, worst_n, VALUE_STATS_DRIFT_THRESHOLD * 100,
                    1 + worst_drift, built)
        return result

    async def _run_edge_integrity(self, space_ids: List[str]) -> Optional[Dict]:
        """Resync the single worst-drifted {space}_edge table, if any.

        The edge table is a denormalized mirror of the edge quads that several
        write paths (SPARQL UPDATE, single/batch quad inserts historically) did
        not keep in sync, so it can silently drift behind rdf_quad and make the
        edge-table query rewrite under-count. Here we cheaply measure drift for
        each space and backfill the worst one per cycle, so a stale table
        self-heals in the background.

        Uses backfill_edge_table (a plain INSERT ... ON CONFLICT DO NOTHING,
        ROW EXCLUSIVE lock only) rather than the TRUNCATE-based
        resync_edge_table, so concurrent edge-rewrite queries are NOT blocked
        while it runs.  Backfill only *adds* missing edges — deletes stay in
        sync via sync_edge_table_before_delete, so there are no orphans to prune.
        """
        from ..db.sparql_sql.sync_edge_table import (
            edge_table_drift, edge_table_orphan_rate,
            edge_table_untyped_rate, backfill_edge_table,
            cleanup_orphan_edges, VITALTYPE_URI)

        # Spaces whose SPARQL UPDATEs deferred a delete the per-subject hooks
        # could not reach. This used to run INLINE in the update request, where
        # it was O(edge table) — 181,212 ms over 4.98M rows with zero orphans
        # against a 60 s command_timeout, so it never completed and never
        # cleaned anything (issues/079). Here it is bounded per pass and the
        # connection is not answering a user.
        #
        # Capped per cycle because each pass is real work (~12 s per 100k-row
        # window). Whatever is not swept this tick is put back, so nothing is
        # dropped — it just waits for the next one.
        from ..db.sparql_sql.sync_edge_table import (
            take_sweep_pending, mark_sweep_needed)
        pending = take_sweep_pending()
        from ..db.sparql_sql.sync_frame_entity_table import (
            cleanup_stale_frame_entity)
        for sid in sorted(pending)[:_SWEEP_SPACES_PER_CYCLE]:
            try:
                async with self._pool.acquire() as conn:
                    # frame_entity BEFORE edges, and the order is load-bearing:
                    # a frame_entity row is validated against the edge table, so
                    # cleaning it after the edges it reads have gone makes it
                    # look stale for the wrong reason and the two passes
                    # disagree about why. This ordering came from the inline
                    # cleanup that used to run in execute_sparql_update; moving
                    # the sweep here dropped the frame_entity half entirely,
                    # leaving it called from NOWHERE (issues/064).
                    stale = await cleanup_stale_frame_entity(conn, sid)
                    removed = await cleanup_orphan_edges(conn, sid)
                if stale:
                    logger.info("Frame-entity integrity: swept %d stale row(s) "
                                "from %s after a WHERE-bound delete", stale, sid)
                if removed:
                    logger.info("Edge integrity: swept %d orphan(s) from %s "
                                "after a WHERE-bound delete", removed, sid)
            except Exception as e:
                logger.warning("referential sweep for %s failed: %s", sid, e)
        for sid in sorted(pending)[_SWEEP_SPACES_PER_CYCLE:]:
            mark_sweep_needed(sid)

        worst_space = None
        worst_drift = 0
        stale_space = None
        # Tracked independently of drift — see the note at the selection below.
        worst_orphan_space = None
        worst_orphan_rate = 0.0
        for space_id in space_ids:
            try:
                async with self._pool.acquire() as conn:
                    src_quads, edge_rows = await edge_table_drift(conn, space_id)
                    # Counts agreeing does not mean the rows are right. A space
                    # reloaded in place leaves an edge table that is a faithful
                    # materialisation of the PREVIOUS contents — same size,
                    # disjoint set, every count check green and every frame
                    # traversal returning nothing (issues/041). Only a
                    # referential probe sees that.
                    orphan_rate = await edge_table_orphan_rate(conn, space_id)
                    # Capability, NOT drift. A NULL edge_type_uuid means the row
                    # will not match a typed traversal; it does not mean the row
                    # is stale. The usual cause is simply that the column was
                    # added by a migration and not yet backfilled, in which case
                    # every row reads NULL and nothing is wrong. Orphan
                    # detection stays with the referential probe above.
                    untyped_rate = await edge_table_untyped_rate(conn, space_id)
            except Exception:
                continue  # space has no edge table (e.g. non-KG) — skip
            if untyped_rate > EDGE_UNTYPED_WARN_PCT:
                # Reported, never acted on, and deliberately not called drift.
                # Three conditions produce it and only one is actionable: the
                # column is not backfilled yet (actionable — a rebuild fixes
                # it), the space carries no vitaltype triples at all (nothing to
                # backfill FROM, so the rebuild would be a no-op), or the rows
                # are orphaned (the referential probe establishes that, not this
                # number). Rebuilding on this signal alone would churn healthy
                # tables.
                #
                # The first two ARE separable, cheaply, and this used to lump
                # them together — so it advised a rebuild that could not
                # possibly help, once per cycle, forever, for every ephemeral
                # inttest_* space in the database. A recurring INFO nobody can
                # act on is how the ones that matter get skimmed past.
                # A FRESH connection, deliberately. `conn` above belongs to the
                # `async with` that has already exited, so using it here raised
                # InterfaceError and — because one `except` wraps the whole
                # cycle — took edge integrity, frame-entity integrity, stats
                # prune, vector reindex and cleanup down with it, every cycle.
                # Not inside the try above either: that one means "this space
                # has no edge table" and would swallow a real failure here.
                async with self._pool.acquire() as probe_conn:
                    has_vitaltype = await probe_conn.fetchval(f"""
                        SELECT EXISTS (
                            SELECT 1 FROM {space_id}_rdf_quad q
                            JOIN {space_id}_term t
                              ON t.term_uuid = q.predicate_uuid
                            WHERE t.term_text = $1 LIMIT 1)
                    """, VITALTYPE_URI)
                if not has_vitaltype:
                    # Nothing to derive a type from. Permanent and expected for
                    # an export that carries only rdf:type, so it is not news.
                    logger.debug(
                        "edge table for %s is %.1f%% untyped, and the space has "
                        "no vitaltype triples at all — nothing to backfill from",
                        space_id, 100.0 * untyped_rate)
                else:
                    logger.info(
                        "edge table for %s has %.1f%% rows with no "
                        "edge_type_uuid, so typed traversals will not match "
                        "them, and the space DOES carry vitaltype triples — so "
                        "the column is unbackfilled rather than underivable. "
                        "Not itself evidence of staleness; "
                        "scripts/rebuild_edge_tables.py --space %s repopulates "
                        "it (and drops orphans, if there are any).",
                        space_id, 100.0 * untyped_rate, space_id)
            if orphan_rate > EDGE_ORPHAN_STALE_PCT:
                stale_space = stale_space or (space_id, orphan_rate)
                continue
            # Orphan cleanup is selected SEPARATELY from drift, because drift
            # cannot see orphans: an orphan is an extra row, so it makes
            # `src_quads - edge_rows` smaller, and a space with orphans but no
            # missing edges scores as healthier than one with neither. They can
            # also cancel exactly, which is the whole reason edge_table_drift
            # missed this for so long.
            if orphan_rate > 0 and orphan_rate > worst_orphan_rate:
                worst_orphan_rate, worst_orphan_space = orphan_rate, space_id
            drift = src_quads - edge_rows
            if drift > max(EDGE_DRIFT_MIN_ABS, int(EDGE_DRIFT_MIN_PCT * src_quads)):
                if drift > worst_drift:
                    worst_drift, worst_space = drift, space_id

        if stale_space:
            # Backfill only ADDS rows, so it cannot repair a table whose
            # existing rows are all wrong. This needs a full rebuild, which
            # takes ACCESS EXCLUSIVE and blocks edge-rewrite queries — so it is
            # logged loudly rather than done silently on a maintenance tick.
            sid, rate = stale_space
            logger.error(
                "edge table for %s is STALE, not merely behind: %.0f%% of "
                "sampled rows reference quads that no longer exist. Every frame "
                "traversal on this space returns zero rows with no error. "
                "Backfill cannot fix this; run resync_edge_table(%s). "
                "See issues/041.", sid, rate * 100, sid)

        if not worst_space:
            # No space needs edges ADDED — but one may still need orphans
            # removed, and that is the case this returned early on. Orphans do
            # not produce positive drift (they are extra rows), so "nothing to
            # backfill" was silently read as "the edge tables are fine".
            if not worst_orphan_space:
                return None
            async with self._pool.acquire() as conn:
                removed = await cleanup_orphan_edges(conn, worst_orphan_space)
            if not removed:
                return None
            logger.info("Edge integrity: removed %d orphaned row(s) from %s "
                        "(no backfill needed)", removed, worst_orphan_space)
            return {"space_id": worst_orphan_space, "orphans_removed": removed}

        process_id = None
        if self._tracker:
            process_id = await self._tracker.create_process(
                "edge_backfill", process_subtype=worst_space,
                instance_id=self._instance_id, status="running")
            await self._tracker.mark_running(process_id, self._instance_id)
        try:
            # Non-blocking backfill (ROW EXCLUSIVE only) — edge-rewrite queries
            # keep running while missing edges are added.
            #
            # Then the delete side. Backfill only ADDS, so for years this
            # "self-heal" reconciled exactly half of what it claimed: a SPARQL
            # UPDATE whose subjects are WHERE-bound is deferred here, and its
            # inserts were eventually backfilled while its deletes left edge
            # rows pointing at quads that no longer exist. 20,461 of them had
            # accumulated across four spaces (issues/064). Also bounded and
            # ROW EXCLUSIVE, so it cannot block readers either.
            async with self._pool.acquire() as conn:
                inserted = await backfill_edge_table(conn, worst_space)
                removed = await cleanup_orphan_edges(conn, worst_space)
                # The orphan target is usually a DIFFERENT space, because the
                # two problems are selected on different evidence.
                if worst_orphan_space and worst_orphan_space != worst_space:
                    removed += await cleanup_orphan_edges(conn, worst_orphan_space)
            result = {"space_id": worst_space, "drift": worst_drift,
                      "edges_added": inserted, "orphans_removed": removed}
            if self._tracker and process_id:
                await self._tracker.mark_completed(process_id, result_details=result)
            logger.info("Edge integrity: %s (drift=%d → +%d edges, -%d orphans)",
                        worst_space, worst_drift, inserted, removed)
            return result
        except Exception as e:
            if self._tracker and process_id:
                await self._tracker.mark_failed(process_id, str(e))
            logger.error("Edge integrity backfill failed for %s: %s", worst_space, e)
            return {"space_id": worst_space, "error": str(e)}

    async def _run_frame_entity_integrity(self, space_ids: List[str]) -> Optional[Dict]:
        """Backfill the single worst-drifted {space}_frame_entity table, if any.

        Same shape as _run_edge_integrity: measure drift cheaply per space and
        backfill the worst one per cycle with the non-blocking
        `backfill_frame_entity_table` (ROW EXCLUSIVE, no TRUNCATE), so
        frame-entity-rewrite queries are not blocked. No-op for spaces without
        connector-frame data (drift 0). frame_entity is derived from the edge
        table, so this runs after the edge integrity step.
        """
        from ..db.sparql_sql.sync_frame_entity_table import (
            frame_entity_drift, backfill_frame_entity_table)

        worst_space = None
        worst_drift = 0
        for space_id in space_ids:
            try:
                async with self._pool.acquire() as conn:
                    expected, actual = await frame_entity_drift(conn, space_id)
            except Exception:
                continue  # no frame_entity table (e.g. non-KG) — skip
            drift = expected - actual
            if drift > max(EDGE_DRIFT_MIN_ABS, int(EDGE_DRIFT_MIN_PCT * expected)):
                if drift > worst_drift:
                    worst_drift, worst_space = drift, space_id

        if not worst_space:
            return None

        process_id = None
        if self._tracker:
            process_id = await self._tracker.create_process(
                "frame_entity_backfill", process_subtype=worst_space,
                instance_id=self._instance_id, status="running")
            await self._tracker.mark_running(process_id, self._instance_id)
        try:
            async with self._pool.acquire() as conn:
                inserted = await backfill_frame_entity_table(conn, worst_space)
            result = {"space_id": worst_space, "drift": worst_drift, "rows_added": inserted}
            if self._tracker and process_id:
                await self._tracker.mark_completed(process_id, result_details=result)
            logger.info("Frame-entity integrity: backfilled %s (drift=%d → +%d rows)",
                        worst_space, worst_drift, inserted)
            return result
        except Exception as e:
            if self._tracker and process_id:
                await self._tracker.mark_failed(process_id, str(e))
            logger.error("Frame-entity integrity backfill failed for %s: %s", worst_space, e)
            return {"space_id": worst_space, "error": str(e)}

    async def _run_stats_rebuild(self, space_id: str) -> Dict:
        """Rebuild rdf_pred_stats and rdf_stats for a space."""
        from ..ops.database_op import StatsRebuildOp

        process_id = None
        if self._tracker:
            process_id = await self._tracker.create_process(
                "stats_rebuild", process_subtype=space_id, instance_id=self._instance_id, status="running"
            )
            await self._tracker.mark_running(process_id, self._instance_id)

        try:
            conn = await self._pool.acquire()
            try:
                op = StatsRebuildOp(space_id, conn=conn)
                op_result = await op.execute()
            finally:
                await self._pool.release(conn)

            result = {"space_id": space_id, "status": op_result.status.value, "message": op_result.message}
            if self._tracker and process_id:
                if op_result.is_success():
                    await self._tracker.mark_completed(process_id, result_details=result)
                else:
                    await self._tracker.mark_failed(process_id, op_result.message)
            return result

        except Exception as e:
            if self._tracker and process_id:
                await self._tracker.mark_failed(process_id, str(e))
            logger.error("Stats rebuild failed for space %s: %s", space_id, e)
            return {"space_id": space_id, "error": str(e)}

    # ------------------------------------------------------------------
    # Sync / async table operation helpers
    # ------------------------------------------------------------------

    def _make_sync_connection(self):
        """Create a short-lived psycopg sync connection with autocommit.

        Used by thread-offloaded helpers so ANALYZE / VACUUM never touch the
        asyncpg pool or the event loop.
        """
        import psycopg
        cfg = self._pg_config
        assert cfg is not None, "_make_sync_connection requires postgresql_config"
        return psycopg.connect(
            host=cfg.get('host', 'localhost'),
            port=cfg.get('port', 5432),
            dbname=cfg.get('database', 'vitalgraph'),
            user=cfg.get('username', 'vitalgraph_user'),
            password=cfg.get('password', 'vitalgraph_pass'),
            autocommit=True,
        )

    _SQL_COMMANDS = {"ANALYZE": "ANALYZE", "VACUUM": "VACUUM"}

    def _sync_run_tables(self, command: str, tables: List[str]) -> int:
        """Run *command* (ANALYZE | VACUUM) on each table via psycopg sync.

        Runs in a background thread — safe to call via asyncio.to_thread().
        """
        from psycopg import sql as psql
        verb = self._SQL_COMMANDS.get(command)
        if verb is None:
            raise ValueError(f"Unsupported maintenance command: {command}")
        conn = self._make_sync_connection()
        completed = 0
        try:
            for table in tables:
                try:
                    stmt = psql.SQL("ANALYZE {}") if verb == "ANALYZE" else psql.SQL("VACUUM {}")
                    conn.execute(stmt.format(psql.Identifier(table)))
                    completed += 1
                except Exception as e:
                    logger.warning("%s %s failed: %s", command, table, e)
        finally:
            conn.close()
        return completed

    async def _async_run_tables(self, command: str, tables: List[str]) -> int:
        """Fallback: run *command* on each table via the asyncpg pool.

        Used when no *postgresql_config* was provided.  Inserts explicit
        ``asyncio.sleep(0)`` between operations to yield the event loop.
        """
        conn = await self._pool.acquire()
        completed = 0
        try:
            for table in tables:
                try:
                    await conn.execute(f"{command} {table}")
                    completed += 1
                except Exception as e:
                    logger.warning("%s %s failed: %s", command, table, e)
                await asyncio.sleep(0)  # yield to event loop between tables
        finally:
            await self._pool.release(conn)
        return completed

    # ------------------------------------------------------------------
    # Vector index REINDEX
    # ------------------------------------------------------------------

    async def _run_vector_reindex(self, space_ids: List[str], *, force: bool = False) -> Optional[Dict]:
        """Check vector index HNSW bloat and REINDEX CONCURRENTLY if needed.

        Runs at most ONE reindex operation per cycle (to limit I/O impact).
        Uses REINDEX INDEX CONCURRENTLY which doesn't block queries.

        Args:
            space_ids: List of space IDs to check.
            force: If True, skip cooldown/threshold checks.

        Returns:
            Result dict or None if nothing was reindexed.
        """
        best_index: Optional[str] = None
        best_space: Optional[str] = None
        best_score: float = -1.0

        try:
            if self._pg_config:
                candidates = await asyncio.to_thread(
                    self._sync_find_vector_reindex_candidates, space_ids, force
                )
            else:
                candidates = await self._async_find_vector_reindex_candidates(space_ids, force)
        except Exception as e:
            logger.debug("Vector reindex candidate scan failed: %s", e)
            return None

        if not candidates:
            return None

        # Pick the worst (highest score)
        for cand in candidates:
            if cand["score"] > best_score:
                best_score = cand["score"]
                best_space = cand["space_id"]
                best_index = cand["index_name"]

        if best_index is None or best_space is None:
            return None

        logger.info(
            "MaintenanceJob: VECTOR REINDEX pick → %s/%s (score=%.2f)",
            best_space, best_index, best_score,
        )

        # Execute REINDEX INDEX CONCURRENTLY
        process_id = None
        if self._tracker:
            process_id = await self._tracker.create_process(
                "vector_reindex", process_subtype=f"{best_space}/{best_index}",
                instance_id=self._instance_id, status="running",
            )
            await self._tracker.mark_running(process_id, self._instance_id)

        hnsw_index_name = f"idx_{best_space}_vec_{best_index}_hnsw"
        try:
            if self._pg_config:
                await asyncio.to_thread(self._sync_reindex_concurrently, hnsw_index_name)
            else:
                await self._async_reindex_concurrently(hnsw_index_name)

            result = {
                "space_id": best_space,
                "index_name": best_index,
                "hnsw_index": hnsw_index_name,
                "status": "reindexed",
            }
            if self._tracker and process_id:
                await self._tracker.mark_completed(process_id, result_details=result)
            logger.info("VECTOR REINDEX complete: %s", hnsw_index_name)
            return result

        except Exception as e:
            if self._tracker and process_id:
                await self._tracker.mark_failed(process_id, str(e))
            logger.error("VECTOR REINDEX failed for %s: %s", hnsw_index_name, e)
            return {"space_id": best_space, "index_name": best_index, "error": str(e)}

    def _sync_find_vector_reindex_candidates(
        self, space_ids: List[str], force: bool,
    ) -> List[Dict]:
        """Thread-safe: scan pg_stat_user_tables for vector tables needing reindex."""
        import psycopg
        import psycopg.rows
        conn = self._make_sync_connection()
        try:
            return self._scan_vector_candidates(conn, space_ids, force, sync=True)
        finally:
            conn.close()

    async def _async_find_vector_reindex_candidates(
        self, space_ids: List[str], force: bool,
    ) -> List[Dict]:
        """asyncpg-based vector reindex candidate scan."""
        async with self._pool.acquire() as conn:
            return await self._scan_vector_candidates_async(conn, space_ids, force)

    def _scan_vector_candidates(
        self, conn, space_ids: List[str], force: bool, sync: bool = True,
    ) -> List[Dict]:
        """Scan for vector table candidates using psycopg sync connection."""
        import psycopg.rows
        candidates = []
        # Build LIKE patterns for vector tables
        patterns = [f"{sid}_vec_%" for sid in space_ids]
        if not patterns:
            return candidates

        # Query pg_stat for all matching vector tables
        pattern_clauses = " OR ".join(["relname LIKE %s" for _ in patterns])
        query = f"""
            SELECT relname, n_live_tup, n_dead_tup, last_vacuum, last_autovacuum
            FROM pg_stat_user_tables
            WHERE {pattern_clauses}
        """
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(query, patterns)
            rows = cur.fetchall()

        now = datetime.now(timezone.utc)
        for row in rows:
            cand = self._evaluate_vector_candidate(row, space_ids, now, force)
            if cand:
                candidates.append(cand)
        return candidates

    async def _scan_vector_candidates_async(
        self, conn, space_ids: List[str], force: bool,
    ) -> List[Dict]:
        """Scan for vector table candidates using asyncpg connection."""
        candidates = []
        patterns = [f"{sid}_vec_%" for sid in space_ids]
        if not patterns:
            return candidates

        # Build query with OR clauses
        conditions = []
        args = []
        for i, pat in enumerate(patterns, 1):
            conditions.append(f"relname LIKE ${i}")
            args.append(pat)

        query = f"""
            SELECT relname, n_live_tup, n_dead_tup, last_vacuum, last_autovacuum
            FROM pg_stat_user_tables
            WHERE {" OR ".join(conditions)}
        """
        rows = await conn.fetch(query, *args)

        now = datetime.now(timezone.utc)
        for row in rows:
            cand = self._evaluate_vector_candidate(dict(row), space_ids, now, force)
            if cand:
                candidates.append(cand)
        return candidates

    @staticmethod
    def _evaluate_vector_candidate(
        row: Dict, space_ids: List[str], now: datetime, force: bool,
    ) -> Optional[Dict]:
        """Evaluate a single vector table row for REINDEX eligibility."""
        relname = row["relname"]
        n_live = row["n_live_tup"] or 0
        n_dead = row["n_dead_tup"] or 0

        # Determine space_id and index_name from table name: {space_id}_vec_{index_name}
        # Find which space_id prefix matches
        space_id = None
        index_name = None
        for sid in space_ids:
            prefix = f"{sid}_vec_"
            if relname.startswith(prefix):
                space_id = sid
                index_name = relname[len(prefix):]
                break
        if not space_id or not index_name:
            return None

        # Skip if table is too small or no significant dead tuples
        if not force:
            if n_dead < VECTOR_REINDEX_MIN_DEAD:
                return None
            if n_live > 0 and (n_dead / n_live) < VECTOR_REINDEX_DEAD_RATIO:
                return None

            # Cooldown: skip if recently vacuumed (proxy for recently reindexed)
            last_v = row.get("last_vacuum") or row.get("last_autovacuum")
            if last_v is not None:
                hours_since = (now - last_v).total_seconds() / 3600.0
                if hours_since < VECTOR_REINDEX_COOLDOWN_HOURS:
                    return None

        # Score: dead tuple ratio weighted by absolute count
        ratio = (n_dead / max(n_live, 1))
        score = n_dead * ratio

        return {
            "space_id": space_id,
            "index_name": index_name,
            "table": relname,
            "n_live": n_live,
            "n_dead": n_dead,
            "score": score,
        }

    def _sync_reindex_concurrently(self, index_name: str) -> None:
        """Run REINDEX INDEX CONCURRENTLY via psycopg sync (thread-safe)."""
        from psycopg import sql as psql
        conn = self._make_sync_connection()
        try:
            conn.execute(
                psql.SQL("REINDEX INDEX CONCURRENTLY {}").format(psql.Identifier(index_name))
            )
        finally:
            conn.close()

    async def _async_reindex_concurrently(self, index_name: str) -> None:
        """Run REINDEX INDEX CONCURRENTLY via asyncpg (fallback)."""
        conn = await self._pool.acquire()
        try:
            await conn.execute(f"REINDEX INDEX CONCURRENTLY {index_name}")
        finally:
            await self._pool.release(conn)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _should_cleanup(self) -> bool:
        """Return True if we should run process record cleanup this cycle."""
        now = time.monotonic()
        if self._last_cleanup is None or (now - self._last_cleanup) > _SECONDS_PER_DAY:
            return True
        return False

    async def _run_cleanup(self) -> bool:
        """Delete old process records."""
        try:
            if self._tracker:
                deleted = await self._tracker.cleanup_old_processes(CLEANUP_RETENTION_DAYS)
                self._last_cleanup = time.monotonic()
                logger.info("Process cleanup: deleted %d old records", deleted)
                return True
        except Exception as e:
            logger.error("Process cleanup failed: %s", e)
        return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _space_tables(space_id: str) -> List[str]:
        """Return the list of tables for a space (sparql_sql backend)."""
        return [
            f"{space_id}_term",
            f"{space_id}_rdf_quad",
            f"{space_id}_datatype",
            f"{space_id}_rdf_pred_stats",
            f"{space_id}_rdf_stats",
            f"{space_id}_edge",
            f"{space_id}_frame_entity",
        ]
