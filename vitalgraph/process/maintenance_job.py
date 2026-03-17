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

# Cleanup
CLEANUP_RETENTION_DAYS = 30
_SECONDS_PER_DAY = 86_400


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

    def __init__(self, pool, process_tracker=None):
        """
        Args:
            pool: asyncpg connection pool.
            process_tracker: Optional ProcessTracker for recording results.
        """
        self._pool = pool
        self._tracker = process_tracker
        self._instance_id = _get_instance_id()
        self._last_cleanup: Optional[float] = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self) -> Dict:
        """Execute one maintenance cycle. Returns summary dict."""
        summary: Dict = {"analyze": None, "vacuum": None, "cleanup": False}
        start = time.monotonic()

        try:
            stats = await self._fetch_space_stats()
            if not stats:
                logger.debug("MaintenanceJob: no space tables found, skipping")
                return summary

            # --- ANALYZE ---
            analyze_space = self._pick_worst_for_analyze(stats)
            if analyze_space:
                summary["analyze"] = await self._run_analyze(analyze_space)

            # --- VACUUM ---
            vacuum_space = self._pick_worst_for_vacuum(stats)
            if vacuum_space:
                summary["vacuum"] = await self._run_vacuum(vacuum_space)

            # --- Cleanup (once per day) ---
            if self._should_cleanup():
                summary["cleanup"] = await self._run_cleanup()

        except Exception as e:
            logger.error("MaintenanceJob cycle error: %s", e, exc_info=True)

        elapsed = (time.monotonic() - start) * 1000
        logger.info(
            "MaintenanceJob cycle complete in %.0fms — analyze=%s vacuum=%s cleanup=%s",
            elapsed,
            summary["analyze"],
            summary["vacuum"],
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

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    async def _fetch_space_stats(self) -> Dict[str, Dict]:
        """Query pg_stat_user_tables for space tables, grouped by space_id.

        Returns:
            {space_id: {n_mod_since_analyze, last_analyze, n_dead_tup, last_vacuum, ...}}
        """
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

        # Aggregate per space
        spaces: Dict[str, Dict] = {}
        for row in rows:
            relname = row["relname"]
            # Extract space_id: everything before the last _rdf_quad or _term suffix
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

            # Take the oldest (most stale) analyze/vacuum time across tables in the space
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

            # Score: mods weighted by staleness
            score = mods * (1.0 + minutes_since / 60.0)
            if score > best_score:
                best_score = score
                best_space = sid

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

            # Score: dead tuples weighted by staleness
            score = dead * (1.0 + minutes_since / 60.0)
            if score > best_score:
                best_score = score
                best_space = sid

        return best_space

    # ------------------------------------------------------------------
    # Execution helpers
    # ------------------------------------------------------------------

    async def _run_analyze(self, space_id: str) -> Dict:
        """Run ANALYZE on space tables using autocommit connection."""
        process_id = None
        if self._tracker:
            process_id = await self._tracker.create_process(
                "analyze", process_subtype=space_id, instance_id=self._instance_id, status="running"
            )
            await self._tracker.mark_running(process_id, self._instance_id)

        tables = self._space_tables(space_id)
        analyzed = 0
        try:
            # ANALYZE must run outside a transaction (autocommit)
            conn = await self._pool.acquire()
            try:
                for table in tables:
                    try:
                        await conn.execute(f"ANALYZE {table}")
                        analyzed += 1
                    except Exception as e:
                        logger.warning("ANALYZE %s failed: %s", table, e)
            finally:
                await self._pool.release(conn)

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
        """Run VACUUM on space tables using autocommit connection."""
        process_id = None
        if self._tracker:
            process_id = await self._tracker.create_process(
                "vacuum", process_subtype=space_id, instance_id=self._instance_id, status="running"
            )
            await self._tracker.mark_running(process_id, self._instance_id)

        tables = self._space_tables(space_id)
        vacuumed = 0
        try:
            conn = await self._pool.acquire()
            try:
                for table in tables:
                    try:
                        await conn.execute(f"VACUUM {table}")
                        vacuumed += 1
                    except Exception as e:
                        logger.warning("VACUUM %s failed: %s", table, e)
            finally:
                await self._pool.release(conn)

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
