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
import hashlib
import logging
import os
import platform
import socket
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import asyncpg
from ..db.connection_config import require

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Freshness thresholds
# ---------------------------------------------------------------------------
ANALYZE_MOD_THRESHOLD = 10_000       # skip if fewer mods since last analyze
ANALYZE_STALENESS_MINUTES = 10       # skip if analyzed within this many minutes
VACUUM_DEAD_THRESHOLD = 10_000       # skip if fewer dead tuples
VACUUM_STALENESS_MINUTES = 30        # skip if vacuumed within this many minutes

# The stats coverage audit, the `pruned` semantics and the oversized-pair
# sample went with `_run_stats_integrity` and `_run_stats_prune`
# (`issues/142`). There is nothing left to audit: `recompute_stats_tables`
# derives the table from the quads in one statement, so it cannot disagree
# with them, and absence means exactly one thing. STATS_COVERAGE_RATIO,
# STATS_OVERSIZED_SAMPLE and the STATS_MAX_ROW_COUNT import all described a
# world with two writers and a flag licensing absence; none of it survives.

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

@asynccontextmanager
async def maintenance_timeouts(conn):
    """Raise the read-path fences for maintenance work, then restore.

    Applies to REPAIRS as well as probes, and the name says so because the
    previous one -- `probe_timeouts` -- was read literally: `issues/149`'s fix
    raised the budget on the drift probe and left the BACKFILL it gates running
    on the read path's fences. The probe then completed, correctly reported a
    2.7M-row gap, triggered the repair, and the repair died:

        3 x  canceling statement due to statement timeout   (60s, on the INSERT)
        43 x LockNotAvailableError                          (10s lock_timeout)

    so `entity_slot_sort` crept 26.5k -> 40k instead of reaching ~2.83M. A gate
    that is fixed while the thing behind it is not looks exactly like a fixed
    gate.

    RAISES BOTH FENCES, matching `maintenance_conn_options`. The first version
    raised only `statement_timeout`, which is why the backfill lost 43 lock
    races at the read path's 10s: a 133s walk-INSERT cannot hold to a fence
    sized for user queries.

    The probes run on the shared pool, which carries the read path's
    `statement_timeout` (60s on prod). That is a fence for USER queries; a probe
    is maintenance and should get the maintenance budget, exactly as
    `maintenance_conn_options` gives it to ANALYZE/VACUUM.

    Not academic. `entity_slot_sort_drift` computes its expected count with the
    full unseeded `WITH RECURSIVE frame_walk`, measured at **76s on prod against
    a 60s limit** — so it has never once completed, and the bare `except` around
    it read the timeout as "not a KG space" and skipped the repair every cycle
    for months. The table it should have been backfilling is 0.6% populated
    (`issues/144`), which is why the entity listing page is O(total).

    Restores explicitly rather than trusting the pool's reset, so the raised
    budget cannot outlive the probe on a connection handed to a user query.
    """
    prev_stmt = await conn.fetchval("SHOW statement_timeout")
    prev_lock = await conn.fetchval("SHOW lock_timeout")
    await conn.execute(
        f"SET statement_timeout = {MAINTENANCE_STATEMENT_TIMEOUT_MS}")
    await conn.execute(
        f"SET lock_timeout = {MAINTENANCE_LOCK_TIMEOUT_MS}")
    try:
        yield conn
    finally:
        try:
            await conn.execute(f"SET statement_timeout = '{prev_stmt}'")
            await conn.execute(f"SET lock_timeout = '{prev_lock}'")
        except Exception:  # pragma: no cover - abort path
            logger.debug("could not restore timeouts to %s / %s",
                         prev_stmt, prev_lock)


def log_probe_failure(probe: str, space_id: str, exc: BaseException) -> None:
    """Report a drift probe that failed for a reason other than "no table".

    Every one of these probes used to sit under a bare `except Exception:
    continue` whose comment asserted the cause was a non-KG space. Skipping is
    still the right ACTION -- a probe that cannot answer must not trigger a
    repair -- but asserting the reason hid a permanent, total failure of the
    repair path behind a comment about a benign one (`issues/144`). Skipping
    quietly and skipping *knowingly* are different things.
    """
    logger.warning(
        "%s: drift probe FAILED for %s (%s: %s) — skipping this space, so its "
        "derived table will NOT be repaired this cycle",
        probe, space_id, type(exc).__name__, exc, exc_info=True)


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

# Below this fraction of a type's entities being present in
# {space}_entity_slot_sort, warn: queries sorting that type cannot use the
# derived table. Deliberately low -- this is not a drift threshold, it is a
# "the fast path does not exist for this type" alarm, and the case it was
# written for measured 1.05% (`issues/149`).
ENTITY_COVERAGE_MIN_RATIO = 0.90

# ...and at least this many entities short before it is worth saying anything.
#
# Without a floor a single uncovered entity — production has exactly one, a
# `KGEntityType_KGEntity` node at 0 of 1 — trips the ratio at 0% and warns
# every cycle forever, while a batch selects it, derives nothing (it has no
# frame/slot chain) and leaves it absent. That is a permanent false alarm
# wrapped around a permanent no-op. A type nobody can sort 25 rows of is not a
# missing fast path.
ENTITY_COVERAGE_MIN_SHORTFALL = int(
    os.environ.get("VG_ENTITY_COVERAGE_MIN_SHORTFALL", "50"))

# Client-side bound for maintenance probes AND repairs, in seconds.
#
# asyncpg's pool sets `command_timeout=60`, which fires in the DRIVER and is
# untouched by `SET statement_timeout` -- so `probe_timeouts` alone raised only
# the server half and the driver still abandoned the call at 60s with a bare
# `TimeoutError`. `entity_slot_sort_drift` measures 97-133s on a 45M-quad space,
# so it had never once completed on production and the backfill it gates had
# never run (`issues/149`). Matched to the maintenance budget, not to the read
# path's.
PROBE_CLIENT_TIMEOUT_S = MAINTENANCE_STATEMENT_TIMEOUT_MS / 1000.0

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


# --- issues/143: watch cadence is not repair cadence -------------------------
#
# The maintenance cycle runs every 300s. Measured on prod over 46 minutes, the
# job accounted for 87% of all slow database time and 38% of wall-clock -- ~115s
# of sequential scans inside every 300s cycle, on a 4 vCPU box. Two of those
# scans are pure WATCHES: they write nothing, they only log a warning, and they
# re-derive their answer from the whole table every single cycle.
#
#     grouping self-link (typeless probe)   38.6s max, ~35s/cycle across spaces
#     graph registration                    same shape
#
# The self-link typeless probe's own comment says its finding is "unexplained,
# which is precisely why it is worth watching". A watch whose finding has
# occurred once, ever, does not belong on a five-minute loop -- and the cost is
# not just CPU: these scan the quad table and evict the buffer cache that the
# read path depends on, which is the mechanism behind the same listing query
# taking 1,216ms and 11,187ms an hour apart.
#
# Repairs keep the 300s cadence. Only watches are slowed, and the first cycle
# after a restart always runs them, so a fresh deploy still gets a full report.
WATCH_INTERVAL_S = float(os.getenv("VITALGRAPH_WATCH_INTERVAL_S", "3600"))

_watch_last_run: Dict[Tuple[str, str], float] = {}


def should_run_watch(name: str, space_id: str,
                     interval_s: Optional[float] = None,
                     now: Optional[float] = None) -> bool:
    """True when this read-only watch is due for *space_id*.

    Deliberately per (watch, space): one space being due does not drag the
    others along, which spreads the cost across cycles instead of spiking it.

    `time.monotonic` rather than wall-clock, so a clock adjustment cannot make a
    watch either fire every cycle or never fire again.
    """
    key = (name, space_id)
    t = time.monotonic() if now is None else now
    last = _watch_last_run.get(key)
    if last is not None and (t - last) < (
            WATCH_INTERVAL_S if interval_s is None else interval_s):
        return False
    _watch_last_run[key] = t
    return True


# --- Per-space recompute schedule, phase-offset by space id ------------------
#
# The recompute is a GROUP BY over the whole quad table. Running several at once
# is safe from a LOCKING standpoint -- the tables are per-space and TRUNCATE
# takes its AccessExclusiveLock on one space only -- but they share a buffer
# cache, and that is the resource the P1 was about: prod's working set (11.21GB)
# already exceeds shared_buffers (7.69GB), so N concurrent full scans evict the
# read path's cache N times faster.
#
# So the spaces are not coordinated and not queued. Each gets its OWN schedule,
# running on a long interval with a start time offset by a hash of its space id.
# Independent schedules spread across the interval rarely coincide, which gets
# the spread without a central round-robin, a queue, or a concurrency limit --
# and nothing needs to know how many spaces there are.
#
# THE HASH MUST BE STABLE ACROSS PROCESSES. Python's built-in `hash()` is salted
# per interpreter (PYTHONHASHSEED), so two instances would compute different
# offsets for the same space and the offsets would move on every restart --
# which is precisely the clustering this exists to avoid. blake2b is stable.
#
# WALL CLOCK, not `time.monotonic`, unlike `should_run_watch` above. A phase
# offset is only meaningful against a shared epoch, and monotonic's origin is
# arbitrary per process. The cost is that a clock adjustment can make a space
# run twice or skip an interval; a recompute is idempotent and the next one is
# an interval away, so that is the cheaper failure.
STATS_RECOMPUTE_INTERVAL_S = float(
    os.getenv("VITALGRAPH_STATS_RECOMPUTE_INTERVAL_S", "3600"))

# Wall-clock a cycle will spend recomputing before deferring the rest. Due
# spaces that do not fit keep their slot and are picked up next cycle, so this
# bounds a cycle without dropping work. Deferrals are LOGGED: a silent cap reads
# as "everything was covered" when it was not.
STATS_RECOMPUTE_CYCLE_BUDGET_S = float(
    os.getenv("VITALGRAPH_STATS_RECOMPUTE_CYCLE_BUDGET_S", "120"))

_recompute_slot: Dict[str, int] = {}


def recompute_phase_offset(space_id: str, interval_s: float) -> float:
    """Where in the interval this space runs, in [0, interval_s).

    Deterministic in the space id alone, so every instance and every restart
    agrees without any shared state.
    """
    digest = hashlib.blake2b(space_id.encode("utf-8"), digest_size=8).digest()
    return (int.from_bytes(digest, "big") % 10_000_000) / 10_000_000 * interval_s


def _recompute_slot_of(space_id: str, interval_s: float, now: float) -> int:
    return int((now - recompute_phase_offset(space_id, interval_s)) // interval_s)


def stats_recompute_due(space_id: str, interval_s: Optional[float] = None,
                        now: Optional[float] = None) -> bool:
    """True when *space_id* has entered a new interval since it last ran.

    Does NOT consume the slot -- `mark_stats_recompute_done` does. They are
    separate because a due space can be deferred by the cycle budget, and a
    deferred space has to stay due or it waits a whole interval for work it was
    already scheduled for.
    """
    iv = STATS_RECOMPUTE_INTERVAL_S if interval_s is None else interval_s
    t = time.time() if now is None else now
    last = _recompute_slot.get(space_id)
    return last is None or _recompute_slot_of(space_id, iv, t) != last


def mark_stats_recompute_done(space_id: str, interval_s: Optional[float] = None,
                              now: Optional[float] = None) -> None:
    """Record that this space has been handled for its current interval."""
    iv = STATS_RECOMPUTE_INTERVAL_S if interval_s is None else interval_s
    t = time.time() if now is None else now
    _recompute_slot[space_id] = _recompute_slot_of(space_id, iv, t)


def reset_stats_recompute_schedule() -> None:
    """Test hook: forget every space's schedule."""
    _recompute_slot.clear()


# --- issues/150: an O(graph) probe must not run when nothing changed ---------
#
# `entity_slot_sort_drift` computes `expected` with the full unseeded
# `WITH RECURSIVE frame_walk`. Measured on production 2026-09-03, AFTER 478fa06
# gave it the maintenance budget:
#
#     durations: 216s, 216s, 122s, 303s, 252s, 59s, 256s
#     DUTY CYCLE = 54% of wall-clock inside this ONE probe
#
# Before 478fa06 asyncpg's `command_timeout=60` killed it at 60s. That was a bug
# -- it meant the probe never completed and the backfill never ran -- but it was
# also accidentally BOUNDING the damage. Removing the fence without gating the
# cadence turned "fails fast every cycle" into "runs for four minutes every
# cycle", sequential-scanning the quad table and evicting the read path's cache.
# A user query measured 1.5s when the probe was idle and 58s when it was not.
#
# The gate is CHANGED DATA, not a clock. If no quads were written, drift cannot
# have changed, and re-deriving it is pure waste. `n_tup_ins + n_tup_upd +
# n_tup_del` is monotonic and survives ANALYZE, unlike `n_mod_since_analyze`
# which resets and would make this fire constantly.
#
# UNCONVERGED WORK OVERRIDES THE GATE. The backfill only ADDs, so a 2.7M-row
# gap takes many passes. Gating on writes alone would skip those passes on a
# quiet space and strand the table half-filled forever -- the same "looks fixed,
# repairs nothing" outcome this whole line of work has been about.
_probe_watermark: Dict[Tuple[str, str], int] = {}
_probe_unconverged: Dict[Tuple[str, str], bool] = {}


async def probe_data_changed(conn, space_id: str, probe: str) -> bool:
    """True when *probe* should re-derive for *space_id*.

    False only when BOTH: the quad table is unchanged since this probe last ran,
    AND that probe last reported no outstanding work.
    """
    key = (probe, space_id)
    if _probe_unconverged.get(key):
        return True
    try:
        wm = await conn.fetchval(
            "SELECT COALESCE(n_tup_ins,0) + COALESCE(n_tup_upd,0) "
            "     + COALESCE(n_tup_del,0) "
            "FROM pg_stat_user_tables WHERE relname = $1",
            f"{space_id}_rdf_quad")
    except Exception:
        return True  # cannot tell -> do the work
    if wm is None:
        return True
    prev = _probe_watermark.get(key)
    _probe_watermark[key] = int(wm)
    # `pg_stat_reset()` moves the counter DOWN; != is the honest test, and it
    # fails toward running.
    return prev is None or int(wm) != prev


def mark_probe_converged(space_id: str, probe: str, converged: bool) -> None:
    """Record whether *probe* still has outstanding work for *space_id*."""
    _probe_unconverged[(probe, space_id)] = not converged


def reset_probe_gate() -> None:
    """Test seam; also forces a full re-derive on the next cycle."""
    _probe_watermark.clear()
    _probe_unconverged.clear()


def reset_watch_schedule() -> None:
    """Test seam; also what a caller would use to force a full sweep."""
    _watch_last_run.clear()


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

            # --- Stats: ONE recompute, replacing integrity + prune + rebuild ---
            stats_result = await self._run_stats_recompute(list(stats.keys()))
            if stats_result:
                summary["stats_recompute"] = stats_result

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
                # Forced: an explicit trigger must not be declined by the
                # per-space schedule (see `_run_stats_recompute`).
                ("stats_recompute",
                 lambda ids: self._run_stats_recompute(ids, force=True)),
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
        # DELIBERATELY NOT under `maintenance_timeouts`, unlike the repairs.
        #
        # This is a WATCH: it writes nothing and only logs. Giving it the
        # 15-minute maintenance budget would let it run LONGER, and it is one of
        # the two things `issues/143` measured burning the box -- 38.6s per pass,
        # ~35s/cycle across spaces, sequential-scanning the quad table and
        # evicting the buffer cache the read path depends on. The read fence is
        # the right ceiling for it: if it cannot answer in 60s, the honest
        # outcome is to give up and say so, not to keep scanning.
        #
        # The same reasoning covers `_run_graph_registration_check`.
        for space_id in space_ids:
            if not should_run_watch("grouping_self_link", space_id):
                continue
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
            if not should_run_watch("graph_registration", space_id):
                continue
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

    async def _run_stats_recompute(self, space_ids: List[str],
                                   force: bool = False) -> Optional[Dict]:
        """Rebuild `rdf_stats` from the quads. Replaces integrity + prune + rebuild.

        `planning/planning_performance/rdf_stats_recompute_not_accumulate_plan.md`.

        There is nothing to audit, prune or repair any more: the table is
        derived in one statement, bounded by a LIMIT, with absence meaning
        exactly one thing. The three steps this replaces existed to manage an
        accumulator that could not validate itself and, under normal update
        churn, ratcheted to zero (`issues/142`).

        CHANGE-GATED. A recompute over the whole quad table is a full scan, so
        it obeys `maintenance_incremental_only_plan.md`'s category-2 rule: it
        runs only when quads were written, and it is cheaper than what it
        replaces (a resync at 19.6-49.0 s PLUS a prune PLUS an audit PLUS an
        oversized repair, every cycle). Measured at 13-20 s across three
        production spaces, flat in quad count.

        SCHEDULE-GATED TOO, per space and independently. Each space runs on its
        own long interval, phase-offset by a hash of its space id, so the spaces
        spread themselves across the interval instead of taking turns in a
        queue. Two gates, in cost order: the schedule is free, the change probe
        is one `pg_stat` read, the recompute is the scan.

        This used to do at most ONE space per cycle -- it returned after the
        first space that actually recomputed. That bounded the cycle, but it
        also meant N changed spaces took N cycles to cover regardless of how
        cheap they were, and which space went first was an artefact of dict
        order rather than anything about the space. Independent schedules give
        the same bound in practice (they rarely coincide) without the queue.
        `STATS_RECOMPUTE_CYCLE_BUDGET_S` is the backstop for when they do.
        """
        from ..db.sparql_sql.sync_stats_tables import recompute_stats_tables

        # Spaces run on INDEPENDENT hash-phased schedules, so "due" is a
        # property of the space and its own clock, not of a position in a queue.
        # Usually none or one is due; occasionally two coincide, and that is
        # fine — they are separate tables and the schedules spread the rest.
        # FORCE bypasses both gates. `trigger_maintenance` is documented as
        # bypassing freshness checks, and an operator who names a space and gets
        # silence has been told the opposite of the truth — the schedule would
        # simply decline until that space's next slot, up to an interval away.
        # This is why the parameter exists rather than the caller pre-seeding
        # the schedule.
        due: List[str] = list(space_ids) if force else []
        for sid in ([] if force else space_ids):
            if sid in _recompute_slot:
                if stats_recompute_due(sid):
                    due.append(sid)
                continue
            # FIRST SIGHT this process. The schedule lives in memory, so every
            # space would be "due" immediately after a restart — which is the
            # clustering the phase offset exists to prevent, arriving by another
            # door, and worst on a deploy that restarts several instances.
            #
            # So a space seen for the first time waits for its next boundary
            # instead, UNLESS its stats table is empty. Empty is not stale: the
            # join reorder has nothing at all to plan with, and waiting an
            # interval for the first fill is a real cost. Stale-but-populated
            # can wait, which is the whole premise of recomputing periodically.
            try:
                async with self._pool.acquire() as conn:
                    empty = not await conn.fetchval(
                        f"SELECT EXISTS(SELECT 1 FROM {sid}_rdf_stats)")
            except asyncpg.UndefinedTableError:
                mark_stats_recompute_done(sid)
                continue
            except Exception as exc:
                # Cannot tell — treat as populated. Guessing "empty" here would
                # make an unreachable database produce the herd.
                #
                # WARNING, not DEBUG. Production runs at INFO, and this is a
                # repair step degrading: the space now waits a whole interval
                # before its first recompute, and if its stats really were empty
                # the join reorder plans on nothing for that interval. That is
                # `issues/144` exactly — a dead path whose only trace was
                # invisible at the level production logs at.
                logger.warning(
                    "Stats recompute first-sight probe FAILED for %s (%s: %s) — "
                    "cannot tell whether rdf_stats is empty, so it waits for "
                    "its next scheduled slot instead of running now",
                    sid, type(exc).__name__, exc)
                mark_stats_recompute_done(sid)
                continue
            if empty:
                due.append(sid)
            else:
                mark_stats_recompute_done(sid)
        if not due:
            return None

        started = time.monotonic()
        done: List[Dict] = []
        for i, space_id in enumerate(due):
            # Budget checked BEFORE starting, never mid-recompute: a partial
            # recompute is not a thing — it is one transaction — so the choice
            # is to start it or not. The unstarted ones keep their slot and stay
            # due, so nothing is dropped.
            if done and (time.monotonic() - started) > STATS_RECOMPUTE_CYCLE_BUDGET_S:
                logger.info(
                    "Stats recompute DEFERRED for %d space(s) (%s) — the "
                    "%.0fs cycle budget went on %d space(s). They keep their "
                    "slot and run next cycle; this is a deferral, not a skip",
                    len(due) - i, ", ".join(due[i:][:5]),
                    STATS_RECOMPUTE_CYCLE_BUDGET_S, len(done))
                break
            try:
                async with self._pool.acquire() as conn:
                    async with maintenance_timeouts(conn):
                        if not force and not await probe_data_changed(
                                conn, space_id, "stats_recompute"):
                            # Nothing written since the last one, so the table is
                            # already right. Consume the slot: re-deciding this
                            # every cycle is what the schedule exists to stop.
                            mark_stats_recompute_done(space_id)
                            continue
                        result = await recompute_stats_tables(
                            conn, space_id, timeout=PROBE_CLIENT_TIMEOUT_S)
            except asyncpg.UndefinedTableError:
                mark_stats_recompute_done(space_id)
                continue  # space has no stats tables (e.g. non-KG) — skip
            except Exception as exc:
                # NOT silent. This is now the ONLY thing keeping rdf_stats
                # correct; if it stops working there is no audit behind it to
                # notice (`issues/148` is the record of what a quiet failure
                # here costs).
                logger.warning(
                    "Stats recompute FAILED for %s (%s: %s) — the join reorder "
                    "will plan on whatever is currently in rdf_stats until the "
                    "next cycle",
                    space_id, type(exc).__name__, exc, exc_info=True)
                mark_probe_converged(space_id, "stats_recompute", False)
                # NOT marked done: a failure must stay due so the next cycle
                # retries it. Marking it here would turn one transient error
                # into a whole interval of planning on a stale table.
                continue
            mark_probe_converged(space_id, "stats_recompute", True)
            mark_stats_recompute_done(space_id)
            done.append({"space_id": space_id, **result})
        if not done:
            return None
        # Shape kept for one space so existing readers of this summary still
        # work; `spaces` carries the rest.
        return {**done[0], "spaces": [d["space_id"] for d in done]} \
            if len(done) == 1 else {"spaces": [d["space_id"] for d in done],
                                    "results": done}

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
                async with maintenance_timeouts(conn):
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
                    async with maintenance_timeouts(conn):
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
                    async with maintenance_timeouts(conn):
                        # `issues/143` rec #1, same gate as the slot-sort walk:
                        # this is a count(DISTINCT (subject,context)) over ~50M
                        # rows, measured at 17.7s. With no quad writes there is
                        # nothing new to count.
                        if not await probe_data_changed(
                                conn, space_id, "edge_table_drift"):
                            continue
                        src_quads, edge_rows = await edge_table_drift(
                            conn, space_id, timeout=PROBE_CLIENT_TIMEOUT_S)
                        mark_probe_converged(
                            space_id, "edge_table_drift",
                            (src_quads - edge_rows) <= EDGE_DRIFT_MIN_ABS)
                    # Counts agreeing does not mean the rows are right. A space
                    # reloaded in place leaves an edge table that is a faithful
                    # materialisation of the PREVIOUS contents — same size,
                    # disjoint set, every count check green and every frame
                    # traversal returning nothing (issues/041). Only a
                    # referential probe sees that.
                    orphan_rate = await edge_table_orphan_rate(
                        conn, space_id, timeout=PROBE_CLIENT_TIMEOUT_S)
                    # Capability, NOT drift. A NULL edge_type_uuid means the row
                    # will not match a typed traversal; it does not mean the row
                    # is stale. The usual cause is simply that the column was
                    # added by a migration and not yet backfilled, in which case
                    # every row reads NULL and nothing is wrong. Orphan
                    # detection stays with the referential probe above.
                    untyped_rate = await edge_table_untyped_rate(conn, space_id)
            except asyncpg.UndefinedTableError:
                continue  # space has no edge table (e.g. non-KG) — skip
            except Exception as exc:
                log_probe_failure("edge_integrity", space_id, exc)
                continue
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
                async with maintenance_timeouts(conn):
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
                # Same budget as the probe above (`issues/149`). A repair left on
                # the read path's fences is the defect that let entity_slot_sort
                # sit at 40k rows against a 2.83M target while its probe
                # reported the gap correctly every cycle.
                async with maintenance_timeouts(conn):
                    inserted = await backfill_edge_table(
                        conn, worst_space, timeout=PROBE_CLIENT_TIMEOUT_S)
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
                    async with maintenance_timeouts(conn):
                        if not await probe_data_changed(
                                conn, space_id, "frame_entity_drift"):
                            continue
                        expected, actual = await frame_entity_drift(
                            conn, space_id, timeout=PROBE_CLIENT_TIMEOUT_S)
                        mark_probe_converged(
                            space_id, "frame_entity_drift",
                            (expected - actual) <= EDGE_DRIFT_MIN_ABS)
                    # Counts agreeing does not mean the rows are RIGHT. A space
                    # reloaded in place — or under a new graph URI — leaves this
                    # table a faithful materialisation of the PREVIOUS contents:
                    # same size, disjoint set, drift 0, every traversal empty
                    # (issues/041). Only a referential probe sees that, and
                    # until now only the edge table had one.
                    orphan_rate = await frame_entity_orphan_rate(conn, space_id)
            except asyncpg.UndefinedTableError:
                continue  # no frame_entity table (e.g. non-KG) — skip
            except Exception as exc:
                log_probe_failure("frame_entity_integrity", space_id, exc)
                continue
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
                async with maintenance_timeouts(conn):
                    inserted = await backfill_frame_entity_table(
                        conn, worst_space, timeout=PROBE_CLIENT_TIMEOUT_S)
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
        """Fill {space}_entity_slot_sort one BOUNDED BATCH per cycle.

        `issues/151`. This used to pick the worst-drifted space with an O(graph)
        `WITH RECURSIVE` walk and then repair it with another one. Measured on
        production: 216-303s per walk, 54% of wall-clock, and a user query that
        ran 1.5s idle took 58s alongside it (`issues/150`). It could not be run
        often enough to converge, so the table sat at 40k rows against a ~2.83M
        target for months (`issues/149`, `issues/144`).

        Now:

          DETECT   `entity_slot_sort_coverage` — 130 ms, counts entities from
                   the QUADS, so it cannot be fooled by the derivation it is
                   checking. That independence is `issues/141`'s lesson and the
                   reason drift could report "converged" on a 1%-full table.
          REPAIR   one seeded batch of ONE short type. The seed is the same one
                   the write path has used since `045988f`, measured
                   row-identical against the full walk. Local sizing (P2):
                   100 -> 53ms, 500 -> 30ms, 2000 -> 151ms.

        Drift's full walk is NOT on this path any more. It survives as an
        advisory number elsewhere; nothing gates a repair on it.
        """
        from ..db.sparql_sql.sync_entity_slot_sort import (
            entity_slot_sort_coverage, backfill_entity_slot_sort_batch)

        worst = None          # (shortfall, space_id, gap)
        for space_id in space_ids:
            try:
                async with self._pool.acquire() as conn:
                    async with maintenance_timeouts(conn):
                        gaps = await entity_slot_sort_coverage(
                            conn, space_id, timeout=PROBE_CLIENT_TIMEOUT_S)
            except asyncpg.UndefinedTableError:
                continue  # space predates the table, or is not a KG space
            except Exception as exc:
                log_probe_failure("entity_slot_sort_coverage", space_id, exc)
                continue

            # Record what the table covers, per entity type, for the FILTER path
            # (`issues/161`). `fast_slot_filter` cannot compute this inline —
            # measured 5,677ms for the table side against 31ms for the quad side
            # — so the marker is maintained here, where both numbers are already
            # being produced.
            #
            # From `entity_slot_sort_all_types`, not from `gaps`: `gaps` carries
            # `HAVING in_table < of_type` and is EMPTY when everything is
            # covered, so it can only ever record incompleteness. A marker that
            # can never be set to complete would switch the fast path off
            # permanently.
            try:
                from ..db.sparql_sql.sync_entity_slot_sort import (
                    entity_slot_sort_all_types)
                from ..db.sparql_sql.fast_slot_filter import (
                    record_slot_sort_coverage)
                async with self._pool.acquire() as conn:
                    async with maintenance_timeouts(conn):
                        for cov in await entity_slot_sort_all_types(
                                conn, space_id, timeout=PROBE_CLIENT_TIMEOUT_S):
                            await record_slot_sort_coverage(
                                conn, space_id, cov["entity_type_uuid"],
                                cov["in_table"], cov["of_type"])
            except Exception as exc:
                # Not silent, at WARNING. Failing to record is SAFE — an unset
                # marker makes the filter path decline, which is slow and
                # correct — but it is not benign: the shape it serves measured
                # 13.9s against 46.9ms, so a marker that never gets written is a
                # permanent performance cliff with no other symptom. DEBUG would
                # hide it, production runs at INFO, and that is exactly how
                # `issues/144` hid a dead repair path for months.
                logger.warning("slot_sort_coverage not recorded for %s: %s — "
                               "the slot-value filter path stays off for this "
                               "space until it is", space_id, exc)

            for gap in gaps:
                short = gap["of_type"] - gap["in_table"]
                if (gap["ratio"] >= ENTITY_COVERAGE_MIN_RATIO
                        or short < ENTITY_COVERAGE_MIN_SHORTFALL):
                    continue
                logger.warning(
                    "entity_slot_sort coverage: %s type %s has %d of %d "
                    "entities (%.2f%%) — queries sorting this type "
                    "cannot use the derived table"
                    " and will do a full frame walk (issues/149)",
                    space_id, gap["entity_type"], gap["in_table"],
                    gap["of_type"], gap["ratio"] * 100)
                if worst is None or short > worst[0]:
                    worst = (short, space_id, gap)

        if worst is None:
            return None
        shortfall, space_id, gap = worst

        process_id = None
        if self._tracker:
            process_id = await self._tracker.create_process(
                "entity_slot_sort_backfill", process_subtype=space_id,
                instance_id=self._instance_id, status="running")
            await self._tracker.mark_running(process_id, self._instance_id)
        try:
            async with self._pool.acquire() as conn:
                async with maintenance_timeouts(conn):
                    selected, inserted = await backfill_entity_slot_sort_batch(
                        conn, space_id, gap["entity_type_uuid"],
                        timeout=PROBE_CLIENT_TIMEOUT_S)
        except Exception as exc:
            logger.warning(
                "entity_slot_sort batch failed for %s type %s: %s — the table "
                "stays short until the next cycle",
                space_id, gap["entity_type"], exc, exc_info=True)
            if self._tracker and process_id:
                await self._tracker.mark_failed(process_id, str(exc))
            return {"space_id": space_id, "failed": f"{type(exc).__name__}: {exc}"}

        # SELECTED BUT NOTHING INSERTED means these entities derive no rows at
        # all -- no frames, or slots with types but no VALUES (both joins in the
        # outer SELECT are INNER). They stay absent, so the same batch is picked
        # again next cycle, forever. Say so once rather than spinning silently.
        if selected and not inserted:
            logger.warning(
                "entity_slot_sort: %s type %s — %d entities selected, 0 rows "
                "derived. They have no frame/slot/value chain to walk, so they "
                "will be re-selected every cycle and coverage can never reach "
                "100%% for this type. This is a DATA shape, not a backfill "
                "failure (issues/151)",
                space_id, gap["entity_type"], selected)

        logger.info(
            "entity_slot_sort backfill: %s type %s +%d rows from %d entities "
            "(%d still short)",
            space_id, gap["entity_type"], inserted, selected, shortfall)
        result = {"space_id": space_id, "entity_type": gap["entity_type"],
                  "selected": selected, "rows_added": inserted,
                  "shortfall": shortfall}
        if self._tracker and process_id:
            await self._tracker.mark_completed(process_id, result_details=result)
        return result

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
                # THE HIGHEST-CONSEQUENCE ONE. This is the full stats resync --
                # the thing that repairs a corrupt rdf_stats -- and on production
                # its aggregate alone measured 25,768 ms (`CREATE TEMP TABLE
                # _new_stats ... GROUP BY`), with the pred aggregate and the
                # re-insert on top. On the read path's 60s fence that is close,
                # and on a larger space it simply cannot finish: the transaction
                # rolls back (safe, by design) and the stats stay corrupt
                # FOREVER, because the only thing that repairs them is the thing
                # timing out. That is `issues/139`'s shape.
                async with maintenance_timeouts(conn):
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
          # The SYNC path gets these fences at CONNECT time via
          # `maintenance_conn_options`; this async fallback had neither. ANALYZE
          # on the big quad table measured 50,224 ms on production against the
          # read path's 60s -- under it, but only just, and `issues/136` is the
          # record of what happens when a maintenance operation is run inside a
          # read-shaped fence: 91% of VACUUMs cancelled while the job logged
          # "VACUUM complete" each time.
          async with maintenance_timeouts(conn):
            for table in tables:
                try:
                    await conn.execute(f"{command} {table}",
                                       timeout=PROBE_CLIENT_TIMEOUT_S)
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
            # REINDEX CONCURRENTLY on a large index runs for minutes and takes
            # locks; the read path's 60s/10s fences guarantee it never finishes.
            async with maintenance_timeouts(conn):
                await conn.execute(
                    f"REINDEX INDEX CONCURRENTLY {index_name}",
                    timeout=PROBE_CLIENT_TIMEOUT_S)
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
