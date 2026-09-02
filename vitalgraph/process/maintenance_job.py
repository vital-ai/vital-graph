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
from ..db.connection_config import require

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Freshness thresholds
# ---------------------------------------------------------------------------
ANALYZE_MOD_THRESHOLD = 10_000       # skip if fewer mods since last analyze
ANALYZE_STALENESS_MINUTES = 10       # skip if analyzed within this many minutes
VACUUM_DEAD_THRESHOLD = 10_000       # skip if fewer dead tuples
VACUUM_STALENESS_MINUTES = 30        # skip if vacuumed within this many minutes

# Timeouts for the MAINTENANCE connections, which are not the read path's.
#
# A deployment can set `statement_timeout` at the database or parameter-group
# level, and every session inherits it — including the short-lived psycopg
# connections this module opens for ANALYZE / VACUUM. Measured on production
# 2026-09-01 with a 60s parameter-group default: `VACUUM {space}_rdf_quad` was
# killed on 223 of 244 attempts (91%), 3.7 hours of cancelled VACUUM per day on
# a 2-vCPU instance, while the job logged "VACUUM complete" each time.
#
# The cost is NOT the heap. That table's visibility map was already 96.9%
# all-visible, so the heap scan is ~20k pages; the time goes to index cleanup
# over 18 GB across nine indexes, which is proportional to index size and does
# not shrink after a successful pass. A read-shaped fence can never fit it.
#
# BOUNDED rather than 0. Zero is defensible — there is no caller waiting on a
# VACUUM — but it removes the only thing that would stop a pathological run,
# and a generous explicit bound fails loudly once instead of silently every six
# minutes. Override per deployment if a table outgrows it.
MAINTENANCE_STATEMENT_TIMEOUT_MS = int(
    os.environ.get("VG_MAINTENANCE_STATEMENT_TIMEOUT_MS", 15 * 60 * 1000))
# The database-level `lock_timeout` is a read-path guard too (production sets
# 10s via ALTER DATABASE). VACUUM takes ShareUpdateExclusive and does not block
# readers or writers, so waiting a little longer for it is cheap.
MAINTENANCE_LOCK_TIMEOUT_MS = int(
    os.environ.get("VG_MAINTENANCE_LOCK_TIMEOUT_MS", 60 * 1000))


def maintenance_conn_options() -> str:
    """libpq `options` string clearing the read-path fences for maintenance.

    Applied at CONNECT time rather than by a later `SET`, so there is no window
    in which the session still carries the inherited value.
    """
    return (f"-c statement_timeout={MAINTENANCE_STATEMENT_TIMEOUT_MS} "
            f"-c lock_timeout={MAINTENANCE_LOCK_TIMEOUT_MS}")

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


def _log_table_op_outcome(command: str, space_id: str,
                          completed: int, attempted: int) -> None:
    """Log a table-loop outcome, and do NOT call a partial run complete.

    `_sync_run_tables` catches per table, so one table failing returns a lower
    count and the caller used to log "VACUUM complete: tables=6" at INFO either
    way. On production that read as 244 clean runs a day while the ONE table
    that mattered was the one missing from the count — the failure was a WARNING
    several lines above and nothing tied them together.
    """
    if completed < attempted:
        logger.error("%s INCOMPLETE: space=%s %d/%d tables — see the warnings "
                     "above for which failed", command, space_id, completed,
                     attempted)
    else:
        logger.info("%s complete: space=%s tables=%d", command, space_id,
                    completed)


def _latest(a, b):
    """The later of two nullable timestamps, or whichever is set, or None."""
    if a is None:
        return b
    if b is None:
        return a
    return a if a > b else b


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
        # Spaces this deployment has declared exempt from maintenance
        # (issues/112 option 3). Empty unless set; see _drop_excluded.
        self._excluded = {
            sid.strip() for sid in
            os.environ.get("VG_MAINTENANCE_EXCLUDE_SPACES", "").split(",")
            if sid.strip()
        }
        if self._excluded:
            logger.info("MaintenanceJob: %d space(s) exempt from maintenance: %s",
                        len(self._excluded), ", ".join(sorted(self._excluded)))
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

            # --- Entity/slot sort integrity (derived from edge; issues/096) ---
            ess_result = await self._run_entity_slot_sort_integrity(list(stats.keys()))
            if ess_result:
                summary["entity_slot_sort_integrity"] = ess_result

            # --- Grouping self-link (entity-graph reads depend on it) ---
            selflink_result = await self._run_grouping_self_link_check(list(stats.keys()))
            if selflink_result:
                summary["grouping_self_link"] = selflink_result

            # --- Graph registration (quads in a graph nothing lists; issues/116) ---
            graphreg_result = await self._run_graph_registration_check(list(stats.keys()))
            if graphreg_result:
                summary["graph_registration"] = graphreg_result

            # --- Stats integrity (wrong counts => wrong plans, silently) ---
            stats_int_result = await self._run_stats_integrity(list(stats.keys()))
            if stats_int_result:
                summary["stats_integrity"] = stats_int_result

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

    async def trigger_maintenance(self, space_id: str) -> Optional[Dict]:
        """Run the whole maintenance pass against ONE space.

        `ProcessScheduler.trigger_now` scopes a request by looking for
        `trigger_<process_type>` on the handler. There was no
        `trigger_maintenance`, so `process_type="maintenance"` with a `space_id`
        fell through to `run()` — the full sweep — and the parameter documented
        as "Target space (omit for auto-select)" was accepted and DISCARDED. A
        caller who scoped the request got no error and no scoping.

        Measured on a stack with 17 spaces:

            analyze     + space_id     0.16 s
            vacuum      + space_id     0.14 s
            maintenance + space_id     109 s     <- ignored the space entirely

        The 109 s is not the work for one space. `run()` scores every space and
        the six integrity phases each sweep all of them; that cost tracks the
        NUMBER OF SPACES, which is why it grows as fixtures are loaded and why
        `tests/api::test_trigger_maintenance` timed out here and not on a fresh
        stack.

        This runs the same phases in the same order, over `[space_id]` alone.
        It deliberately does NOT skip the freshness checks the way
        `trigger_analyze` does — "maintenance for this space" should mean what
        the tick would do for it, not more.
        """
        summary: Dict = {"space_id": space_id}
        try:
            summary["analyze"] = await self._run_analyze(space_id)
            summary["vacuum"] = await self._run_vacuum(space_id)
            one = [space_id]
            for key, phase in (
                ("edge_integrity", self._run_edge_integrity),
                ("frame_entity_integrity", self._run_frame_entity_integrity),
                ("entity_slot_sort_integrity", self._run_entity_slot_sort_integrity),
                ("grouping_self_link", self._run_grouping_self_link_check),
                ("graph_registration", self._run_graph_registration_check),
                ("stats_integrity", self._run_stats_integrity),
                ("stats_prune", self._run_stats_prune),
            ):
                try:
                    result = await phase(one)
                except Exception as exc:
                    # One phase failing must not hide the others, and the caller
                    # asked about a single space — say which phase, not just
                    # that "maintenance" failed.
                    logger.error("trigger_maintenance(%s): %s failed: %s",
                                 space_id, key, exc)
                    summary[key] = {"error": str(exc)[:200]}
                    continue
                if result:
                    summary[key] = result
        except Exception as exc:
            logger.error("trigger_maintenance(%s) failed: %s", space_id, exc)
            summary["error"] = str(exc)[:200]
        return summary

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

    async def _only_registered(self, stats: Dict[str, Dict]) -> Dict[str, Dict]:
        """Drop space-shaped tables that no live space owns, and any space this
        deployment has declared exempt."""
        registered = await self._registered_space_ids()
        if registered is None:
            return stats
        kept = {sid: v for sid, v in stats.items() if sid in registered}
        kept = self._drop_excluded(kept)
        dropped = len(stats) - len(kept)
        if dropped:
            logger.info("MaintenanceJob: ignoring %d space-shaped table group(s) "
                        "with no row in `space` (scored %d, maintaining %d)",
                        dropped, len(stats), len(kept))
        return kept

    def _drop_excluded(self, stats: Dict[str, Dict]) -> Dict[str, Dict]:
        """Remove spaces named in VG_MAINTENANCE_EXCLUDE_SPACES.

        `issues/112`, option 3. The benchmark fixtures are not spaces anyone
        serves, and maintaining them moves the ground the benchmarks stand on:
        a cycle re-ANALYZEd them mid-session and a bench read +91% worse with
        identical code, because the plan flipped on refreshed statistics.

        Configured per deployment rather than hardcoded, for two reasons. The
        fixture names are a property of a dev machine, not of the product, so
        a list of them does not belong in shipped code. And the exclusion is a
        real divergence from production — the maintenance job IS part of how a
        served space behaves — so it should be something a deployment opts
        into visibly, not a default that quietly makes benchmarks unlike
        production everywhere.

        Empty by default. Set it in the environment that runs benchmarks:

            VG_MAINTENANCE_EXCLUDE_SPACES=sp_lead_synth_100k,wordnet_frames
        """
        if not self._excluded:
            return stats
        kept = {sid: v for sid, v in stats.items() if sid not in self._excluded}
        skipped = len(stats) - len(kept)
        if skipped:
            logger.info(
                "MaintenanceJob: skipping %d space(s) declared exempt via "
                "VG_MAINTENANCE_EXCLUDE_SPACES (%s). Their statistics and "
                "bloat are NOT maintained — see issues/112.",
                skipped, ", ".join(sorted(self._excluded & set(stats))))
        return kept

    async def _registered_space_ids(self):
        """The spaces that actually exist, per the `space` registry.

        Stats discovery pattern-matches `pg_stat_user_tables` for `%_rdf_quad`
        and `%_term`, which finds every table that LOOKS like a space —
        including orphans from dropped or half-created spaces. On this stack
        that is **58 scored against 17 registered**, and every integrity phase
        then sweeps all 58. The cost of a cycle tracked a number nobody manages.

        Spaces are explicitly created and dropped through the space manager, so
        the registry is the authority on which ones are live. Orphan TABLES are
        a separate problem with their own tool
        (`scripts/cleanup_orphan_space_tables.py`); this just stops maintaining
        them.

        Returns None when the registry cannot be read — the caller then keeps
        every space rather than silently maintaining nothing, because "the
        registry is unavailable" and "there are no spaces" must not look alike.
        """
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch("SELECT space_id FROM space")
            return {r["space_id"] for r in rows}
        except Exception as exc:
            logger.warning("MaintenanceJob: cannot read the space registry (%s); "
                           "scoring every space-shaped table this cycle", exc)
            return None

    async def _fetch_space_stats(self) -> Dict[str, Dict]:
        """Query pg_stat_user_tables for space tables, grouped by space_id.

        If a psycopg config is available the query runs in a background thread
        so it never blocks the event loop.

        Returns:
            {space_id: {n_mod_since_analyze, last_analyze, n_dead_tup, last_vacuum, ...}}
        """
        if self._pg_config:
            stats = await asyncio.to_thread(self._sync_fetch_space_stats)
            return await self._only_registered(stats)

        # Fallback: use the asyncpg pool directly
        return await self._only_registered(await self._async_fetch_space_stats())

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

            # The LATER of the two, not "manual if present". `or` returned the
            # manual timestamp whenever it was non-NULL, so a table autovacuumed
            # or autoanalyzed perfectly well but last touched by hand weeks ago
            # read as weeks stale forever — and kept being re-picked.
            last_a = _latest(row["last_analyze"], row["last_autoanalyze"])
            if last_a is not None:
                if entry["last_analyze"] is None or last_a < entry["last_analyze"]:
                    entry["last_analyze"] = last_a

            last_v = _latest(row["last_vacuum"], row["last_autovacuum"])
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

            attempted = len(tables)
            result = {"space_id": space_id, "tables_analyzed": analyzed,
                      "tables_attempted": attempted}
            if self._tracker and process_id:
                await self._tracker.mark_completed(process_id, result_details=result)
            _log_table_op_outcome("ANALYZE", space_id, analyzed, attempted)
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

            attempted = len(tables)
            result = {"space_id": space_id, "tables_vacuumed": vacuumed,
                      "tables_attempted": attempted}
            if self._tracker and process_id:
                await self._tracker.mark_completed(process_id, result_details=result)
            _log_table_op_outcome("VACUUM", space_id, vacuumed, attempted)
            return result

        except Exception as e:
            if self._tracker and process_id:
                await self._tracker.mark_failed(process_id, str(e))
            logger.error("VACUUM failed for space %s: %s", space_id, e)
            return {"space_id": space_id, "error": str(e)}

    async def _run_grouping_self_link_check(self, space_ids: List[str]) -> Optional[Dict]:
        """Report grouping URIs that are not members of their own graph.

        Every object in an entity's graph carries `hasKGGraphURI -> <entity>`,
        the entity included. The retrieval queries now rely on that: they select
        the graph in ONE branch by grouping URI, where they used to UNION in a
        second branch that re-fetched the entity by pinning its URI.

        That second branch was compensation, and it hid the breakage completely
        — 619 targets across 12 spaces had no self-link and nothing surfaced,
        because the branch supplied the entity's own properties anyway. With the
        compensation gone a missing self-link means the entity's name, type and
        status silently vanish from its graph while the object count still looks
        plausible. So the invariant has to be watched rather than assumed.

        REPORTS, does not repair. Writing the quad is a data change on a path
        that never wrote quads before, and the repair already exists as
        `scripts/repair_grouping_self_link.py` where it can be reviewed before
        it runs.
        """
        GRAPH_URI_PRED = "http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI"
        for space_id in space_ids:
            try:
                async with self._pool.acquire() as conn:
                    pred = await conn.fetchval(
                        f"SELECT term_uuid FROM {space_id}_term WHERE term_text = $1",
                        GRAPH_URI_PRED)
                    if not pred:
                        continue
                    broken = await conn.fetchval(f"""
                        WITH targets AS (
                            SELECT DISTINCT object_uuid AS e, context_uuid AS ctx
                            FROM {space_id}_rdf_quad WHERE predicate_uuid = $1)
                        SELECT count(*) FROM targets t WHERE NOT EXISTS (
                            SELECT 1 FROM {space_id}_rdf_quad q
                            WHERE q.predicate_uuid = $1 AND q.subject_uuid = t.e
                              AND q.object_uuid = t.e AND q.context_uuid = t.ctx)
                    """, pred)
                    # A grouping target with NO type is the other way a
                    # grouping graph comes back empty. The self-link may be
                    # present, but a typeless subject builds no GraphObject, so
                    # the entity is absent from its own graph and the read
                    # returns nothing. Observed once on a 5.1M-quad space: a
                    # campaign URI carrying only the three server properties,
                    # with 26 objects grouped under it. Neither the import-time
                    # stamping nor either SQL backfill can create that — all
                    # three require rdf:type = KGEntity — so the origin is
                    # unexplained, which is precisely why it is worth watching
                    # rather than assuming it cannot happen again.
                    typeless = await conn.fetchval(f"""
                        WITH targets AS (
                            SELECT DISTINCT object_uuid AS e
                            FROM {space_id}_rdf_quad WHERE predicate_uuid = $1)
                        SELECT count(*) FROM targets t WHERE NOT EXISTS (
                            SELECT 1 FROM {space_id}_rdf_quad q
                            JOIN {space_id}_term p ON p.term_uuid = q.predicate_uuid
                            WHERE q.subject_uuid = t.e
                              AND p.term_text IN (
                                'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
                                'http://vital.ai/ontology/vital-core#vitaltype'))
                    """, pred)
                    if not broken and not typeless:
                        continue
                    if broken:
                        logger.warning(
                            "Grouping self-link: %s has %d URI(s) that group "
                            "objects but are not members of their own graph — "
                            "those ROOTS lose their own properties from "
                            "graph reads. A root is not necessarily an entity: "
                            "hasKGGraphURI also groups document graphs, and "
                            "KGDocument roots carry the self-link for the same "
                            "reason (see _set_document_grouping_uris). Run "
                            "scripts/repair_grouping_self_link.py --space %s",
                            space_id, broken, space_id)
                    if typeless:
                        logger.warning(
                            "Grouping target without a type: %s has %d URI(s) "
                            "that group objects but carry no rdf:type or "
                            "vitaltype. Their graphs read as EMPTY, "
                            "because a typeless subject builds no object. "
                            "Decide whether the URI should be typed or whether "
                            "its members are grouped under the wrong URI.",
                            space_id, typeless)
                    return {"space_id": space_id, "missing_self_links": broken,
                            "typeless_targets": typeless}
            except Exception as exc:
                logger.debug("Self-link check skipped for %s: %s", space_id, exc)
                continue
        return None

    async def _run_graph_registration_check(self, space_ids: List[str]) -> Optional[Dict]:
        """Report quads sitting in a graph the `graph` catalog does not list.

        `issues/116`. Registration is implicit on three impl functions —
        `add_rdf_quad`, `add_rdf_quads_batch`, `add_rdf_quads_batch_bulk`, all
        of which call `_ensure_graphs_registered` — rather than on the act of
        landing quads. Any path that writes another way skips it silently, and
        the data is then queryable by naming the URI while everything that
        LISTS graphs sees nothing.

        Two writers did exactly that, found one at a time and months apart:
        `scripts/load_wordnet_csv.py` left three fixtures holding 31M quads
        with no catalog row, and `bulk_export.import_space` copied whole spaces
        in and registered nothing. Both are fixed. Nothing stops a third, which
        is what this watches for — it is one query, and it would have caught
        both.

        REPORTS, does not repair, on the same principle as the self-link check
        above and for a sharper reason: registering from a sweep fixes the
        symptom on a schedule and leaves every writer free to keep skipping it.
        `register_graphs_from_data` is the repair, callable where it can be
        reviewed before it runs.
        """
        for space_id in space_ids:
            try:
                async with self._pool.acquire() as conn:
                    rows = await conn.fetch(
                        f"""
                        SELECT t.term_text
                        FROM (SELECT DISTINCT context_uuid
                              FROM {space_id}_rdf_quad) c
                        JOIN {space_id}_term t ON t.term_uuid = c.context_uuid
                        WHERE NOT EXISTS (
                            SELECT 1 FROM graph g
                            WHERE g.space_id = $1 AND g.graph_uri = t.term_text)
                        LIMIT 20
                        """, space_id)
                if not rows:
                    continue
                unlisted = [r["term_text"] for r in rows]
                logger.warning(
                    "Unregistered graph: %s holds quads in %d graph(s) the "
                    "catalog does not list (%s). The data is queryable by URI "
                    "but invisible to anything that lists graphs — some writer "
                    "landed quads without registering. See issues/116; repair "
                    "with graph_registry.register_graphs_from_data.",
                    space_id, len(unlisted), ", ".join(unlisted[:5]))
                return {"space_id": space_id, "unlisted_graphs": unlisted}
            except Exception as exc:
                # A space with no quad table yet, or mid-creation. Not a finding.
                logger.debug("Graph registration check skipped for %s: %s",
                             space_id, exc)
                continue
        return None

    async def _run_stats_integrity(self, space_ids: List[str]) -> Optional[Dict]:
        """Catch rdf_stats counts that have gone wrong, and rebuild that space.

        A wrong count does not produce a wrong answer, it produces a wrong PLAN,
        so nothing about the result reveals it. `semijoin._selective_enough`
        divides the probe's match count by the anchor's candidate count: with
        the anchor understated the gate takes a per-row probe over a set-based
        join and the query stays correct while running orders of magnitude
        slower. Found on a 5.1M-quad space only because someone profiled a slow
        endpoint — (rdf:type, Edge_hasKGSlot) stored 37 against 304,859 actual,
        269ms against 33ms once repaired.

        Checked by SAMPLING the largest recorded pairs, not by recounting the
        table. Understatement is what flips the gate, and the largest rows are
        where it shows; an exact count on a handful of pairs is an index scan
        each, which is what makes this affordable per cycle.

        Runs BEFORE the prune, deliberately. The prune removes pairs and flags
        their predicates, so auditing after it would be reading a table that was
        just rewritten — and one space per cycle is already the pattern here.
        """
        from ..db.sparql_sql.sync_stats_tables import resync_stats_tables

        SAMPLE = 3
        for space_id in space_ids:
            try:
                async with self._pool.acquire() as conn:
                    rows = await conn.fetch(
                        f"SELECT predicate_uuid, object_uuid, row_count "
                        f"FROM {space_id}_rdf_stats "
                        f"ORDER BY row_count DESC LIMIT {SAMPLE}")
                    bad = None
                    for r in rows:
                        actual = await conn.fetchval(
                            f"SELECT count(*) FROM {space_id}_rdf_quad "
                            f"WHERE predicate_uuid = $1 AND object_uuid = $2",
                            r["predicate_uuid"], r["object_uuid"])
                        if actual != r["row_count"]:
                            bad = (r["row_count"], actual)
                            break
                    if bad is None:
                        continue
                    # One space per cycle, like every other step here.
                    logger.warning(
                        "Stats integrity: %s has a recorded pair of %d against "
                        "%d actual — rebuilding", space_id, bad[0], bad[1])
                    await resync_stats_tables(conn, space_id)
                    return {"space_id": space_id, "stored": bad[0],
                            "actual": bad[1], "rebuilt": True}
            except Exception as exc:
                # Same reason every step here is guarded: one `except` covers
                # the whole cycle, so a throw would silently skip the prune,
                # the histogram refresh, the reindex and the cleanup.
                logger.debug("Stats integrity check skipped for %s: %s",
                             space_id, exc)
                continue
        return None

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

        # Guarded for the reason this cycle documents about itself: one
        # `except` covers the whole run, so a throw here silently skips every
        # step after it — and the completion line then reports those steps as
        # None, which reads exactly like a cycle that had nothing to do. The
        # prune now rewrites the table (TRUNCATE plus re-insert) rather than
        # deleting from it, so it briefly takes an exclusive lock and can lose
        # a lock race. Failing to bound one stats table must not also cost the
        # value-histogram refresh, the vector reindex and the cleanup.
        try:
            async with self._pool.acquire() as conn:
                kept = await prune_stats_tables(conn, worst_space)
        except Exception as exc:
            logger.warning("Stats prune failed for %s: %s — the table stays "
                           "over its cap until the next cycle", worst_space, exc)
            return {"space_id": worst_space, "est_before": int(worst_rows),
                    "failed": f"{type(exc).__name__}: {exc}"}
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
                "Backfill cannot fix this; repair with:\n"
                "    python scripts/rebuild_edge_tables.py --space %s\n"
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
            frame_entity_drift, frame_entity_orphan_rate,
            backfill_frame_entity_table)

        worst_space = None
        worst_drift = 0
        stale_space = None
        for space_id in space_ids:
            try:
                async with self._pool.acquire() as conn:
                    expected, actual = await frame_entity_drift(conn, space_id)
                    # Counts agreeing does not mean the rows are RIGHT. A space
                    # reloaded in place — or under a new graph URI — leaves this
                    # table a faithful materialisation of the PREVIOUS contents:
                    # same size, disjoint set, drift 0, every traversal empty
                    # (issues/041). Only a referential probe sees that, and
                    # until now only the edge table had one.
                    orphan_rate = await frame_entity_orphan_rate(conn, space_id)
            except Exception:
                continue  # no frame_entity table (e.g. non-KG) — skip
            if orphan_rate > EDGE_ORPHAN_STALE_PCT:
                stale_space = stale_space or (space_id, orphan_rate)
                continue
            drift = expected - actual
            if drift > max(EDGE_DRIFT_MIN_ABS, int(EDGE_DRIFT_MIN_PCT * expected)):
                if drift > worst_drift:
                    worst_drift, worst_space = drift, space_id

        if stale_space:
            # Backfill only ADDS rows, so it cannot repair a table whose rows are
            # all wrong; that needs a resync, which TRUNCATEs and takes ACCESS
            # EXCLUSIVE. Unattended on a tick that is a worse outage than the
            # fault, so: log loudly, name the exact command, leave it to an
            # operator. Same reasoning as the edge table.
            sid, rate = stale_space
            logger.error(
                "frame_entity for %s is STALE, not merely behind: %.0f%% of "
                "sampled rows derive from quads that no longer exist in their "
                "context. Frame traversals on this space return zero rows with "
                "no error, and the drift check reads healthy because the counts "
                "agree. Backfill cannot fix it; repair with:\n"
                "    python scripts/repair_derived_tables.py --space %s\n"
                "See issues/041.", sid, rate * 100, sid)

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

    async def _run_entity_slot_sort_integrity(self, space_ids: List[str]) -> Optional[Dict]:
        """Backfill the worst-drifted {space}_entity_slot_sort table, if any.

        Same shape as _run_frame_entity_integrity, and after it for the same
        reason: both are derived from the edge table, so repairing them before
        the edge step would reproduce whatever the edge table is missing.

        A stale row here is a WRONG SORT ORDER rather than a slow query
        (issues/096), which is why this table gets a drift step at all rather
        than relying on the next bulk resync.

        The backfill only ADDS, so this closes the "rows missing" direction.
        Rows that are present but describe a value that has moved are prevented
        at the write path (delete-then-re-derive) — see `entity_slot_sort_drift`.
        """
        from ..db.sparql_sql.sync_entity_slot_sort import (
            entity_slot_sort_drift, backfill_entity_slot_sort)

        worst_space = None
        worst_drift = 0
        for space_id in space_ids:
            try:
                async with self._pool.acquire() as conn:
                    expected, actual = await entity_slot_sort_drift(conn, space_id)
            except Exception:
                continue  # space predates the table, or is not a KG space
            drift = expected - actual
            if drift > max(EDGE_DRIFT_MIN_ABS, int(EDGE_DRIFT_MIN_PCT * expected)):
                if drift > worst_drift:
                    worst_drift, worst_space = drift, space_id

        if not worst_space:
            return None

        process_id = None
        if self._tracker:
            process_id = await self._tracker.create_process(
                "entity_slot_sort_backfill", process_subtype=worst_space,
                instance_id=self._instance_id, status="running")
            await self._tracker.mark_running(process_id, self._instance_id)
        try:
            async with self._pool.acquire() as conn:
                inserted = await backfill_entity_slot_sort(conn, worst_space)
            result = {"space_id": worst_space, "drift": worst_drift,
                      "rows_added": inserted}
            if self._tracker and process_id:
                await self._tracker.mark_completed(process_id, result_details=result)
            logger.info("Entity-slot-sort integrity: backfilled %s (drift=%d → +%d rows)",
                        worst_space, worst_drift, inserted)
            return result
        except Exception as e:
            if self._tracker and process_id:
                await self._tracker.mark_failed(process_id, str(e))
            logger.error("Entity-slot-sort backfill failed for %s: %s", worst_space, e)
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
            host=require(cfg, 'host'),
            port=require(cfg, 'port'),
            dbname=require(cfg, 'database'),
            user=require(cfg, 'username'),
            password=require(cfg, 'password'),
            autocommit=True,
            options=maintenance_conn_options(),
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
