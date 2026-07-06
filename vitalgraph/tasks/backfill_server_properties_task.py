"""
Internal incremental backfill task for server-managed entity properties.

Runs inside the VitalGraph service process as a periodic background
coroutine.  Iterates all spaces and graphs, processing one small batch
per iteration so the task remains lightweight and non-blocking.

Uses an **event-driven nudge model**: callers (import endpoints, CLI
loaders) signal that new un-stamped data exists by calling ``nudge()``
(in-process) or sending ``NOTIFY vitalgraph_backfill_nudge``
(out-of-process).  When nudged the task switches to a fast 0.5 s
polling cadence until a full cycle completes with no work, then backs
off to an idle timeout (default 30 min / safety-net poll).

All database access is direct SQL against the rdf_quad / term tables
(no Jena sidecar required).

Configuration (via environment or VitalGraphConfig):
    BACKFILL_ENABLED                 Enable/disable (default: true)
    BACKFILL_BATCH_SIZE              Entities per batch (default: 200)
    BACKFILL_ACTIVE_INTERVAL         Seconds between batches when active (default: 0.5)
    BACKFILL_IDLE_TIMEOUT            Seconds to wait when idle before safety-net poll (default: 1800)
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from vitalgraph.kg_impl.kg_server_properties import (
    backfill_entity_server_properties_sql,
    discover_graphs_sql,
)

logger = logging.getLogger(__name__)

# PostgreSQL NOTIFY channel used by out-of-process loaders to nudge the
# backfill task into its fast polling cadence.
BACKFILL_NUDGE_CHANNEL = "vitalgraph_backfill_nudge"


def _env_bool(key: str, default: bool = True) -> bool:
    val = os.environ.get(key, '').lower()
    if val in ('false', '0', 'no'):
        return False
    if val in ('true', '1', 'yes'):
        return True
    return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, str(default)))
    except ValueError:
        return default


@dataclass
class BackfillCursor:
    """Tracks position across spaces/graphs for round-robin progress."""
    targets: List[Tuple[str, str]] = field(default_factory=list)  # (space_id, graph_id)
    index: int = 0

    def next_target(self) -> Optional[Tuple[str, str]]:
        if not self.targets:
            return None
        if self.index >= len(self.targets):
            self.index = 0
        target = self.targets[self.index]
        self.index += 1
        return target

    def is_complete_cycle(self) -> bool:
        return self.index == 0 or self.index >= len(self.targets)


class BackfillServerPropertiesTask:
    """Event-driven background task that incrementally backfills server properties.

    Requires an asyncpg connection pool and a SpaceManager (for listing
    space_ids).  All SPARQL / sidecar logic is bypassed — backfill
    operates directly on the PostgreSQL rdf_quad and term tables.

    Call ``nudge()`` after any data-loading operation that may introduce
    entities without server-managed properties.  The task will switch to
    fast polling until it catches up, then back off.

    Out-of-process callers (CLI scripts) can achieve the same effect with
    ``NOTIFY vitalgraph_backfill_nudge`` on the database connection.
    """

    def __init__(self, pool, space_manager):
        """
        Args:
            pool: asyncpg connection pool.
            space_manager: A SpaceManager instance (has list_spaces).
        """
        self.pool = pool
        self.space_manager = space_manager
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._cursor = BackfillCursor()

        # Nudge event — set by nudge() or NOTIFY listener
        self._nudge_event = asyncio.Event()

        # Dedicated LISTEN connection for out-of-process nudges
        self._listen_conn = None

        # Configuration
        self.enabled = _env_bool('BACKFILL_ENABLED', True)
        self.batch_size = _env_int('BACKFILL_BATCH_SIZE', 200)
        self.active_interval = _env_float('BACKFILL_ACTIVE_INTERVAL', 0.5)
        self.idle_timeout = _env_float('BACKFILL_IDLE_TIMEOUT', 1800.0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def nudge(self) -> None:
        """Signal that new un-stamped data may exist.

        Wakes the task from its idle sleep so it enters the fast polling
        cadence.  Safe to call from any coroutine in the same event loop.
        Calling multiple times before the task wakes is harmless — the
        event is level-triggered.
        """
        self._nudge_event.set()

    def start(self) -> None:
        """Start the backfill task."""
        if not self.enabled:
            logger.info("Backfill task disabled (BACKFILL_ENABLED=false)")
            return
        if self._task is not None:
            logger.warning("Backfill task already started")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "Backfill task started (batch_size=%d, active_interval=%.1fs, idle_timeout=%.0fs)",
            self.batch_size, self.active_interval, self.idle_timeout,
        )

    async def stop(self) -> None:
        """Stop the backfill task and tear down LISTEN connection."""
        self._running = False
        self._nudge_event.set()  # unblock any wait_for
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._teardown_listener()
        logger.info("Backfill task stopped")

    # ------------------------------------------------------------------
    # LISTEN / NOTIFY helpers
    # ------------------------------------------------------------------

    async def _setup_listener(self) -> None:
        """Set up a dedicated LISTEN connection for the nudge channel."""
        try:
            import asyncpg
            # Create a standalone connection from the pool's connect kwargs
            pool = self.pool
            dsn = None
            if hasattr(pool, 'get_connect_kwargs'):
                dsn = pool.get_connect_kwargs()
            elif hasattr(pool, '_connect_kwargs'):
                dsn = pool._connect_kwargs
            if dsn and isinstance(dsn, dict):
                conn = await asyncpg.connect(**dsn)
            elif hasattr(pool, '_connect_args') and pool._connect_args:
                conn = await asyncpg.connect(*pool._connect_args, **(pool._connect_kwargs or {}))
            else:
                logger.warning("Backfill: could not create LISTEN connection — nudge via NOTIFY unavailable")
                return
            await conn.add_listener(BACKFILL_NUDGE_CHANNEL, self._on_notify)
            self._listen_conn = conn
            logger.info("Backfill: LISTEN on %s", BACKFILL_NUDGE_CHANNEL)
        except Exception as e:
            logger.warning("Backfill: LISTEN setup failed (nudge via NOTIFY unavailable): %s", e)

    async def _teardown_listener(self) -> None:
        """Remove listener and close dedicated connection."""
        if self._listen_conn is not None:
            try:
                await self._listen_conn.remove_listener(BACKFILL_NUDGE_CHANNEL, self._on_notify)
            except Exception:
                pass
            try:
                await self._listen_conn.close()
            except Exception:
                pass
            self._listen_conn = None

    def _on_notify(self, conn, pid, channel, payload) -> None:
        """asyncpg notification callback — sets the nudge event."""
        logger.info("Backfill: NOTIFY received on %s", channel)
        self._nudge_event.set()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Event-driven loop: fast poll while work exists, idle wait otherwise."""
        # Initial delay to let the service finish startup
        await asyncio.sleep(10)

        await self._setup_listener()

        cycle_had_work = False

        while self._running:
            try:
                did_work = await self._iteration()
                if did_work:
                    cycle_had_work = True
            except Exception as e:
                logger.error("Backfill iteration error: %s", e, exc_info=True)
                did_work = False

            # Decide sleep / wait strategy
            if self._cursor.is_complete_cycle() or not self._cursor.targets:
                if cycle_had_work:
                    # Completed a cycle that found work — start another
                    # cycle quickly in case there is more.
                    sleep_time = self.active_interval
                    logger.info(
                        "Backfill: cycle complete (work done), next cycle in %.1fs",
                        sleep_time,
                    )
                else:
                    # Full cycle with no work — go idle until nudged.
                    logger.info(
                        "Backfill: cycle complete (no work), waiting for nudge (timeout=%.0fs)",
                        self.idle_timeout,
                    )
                    self._nudge_event.clear()
                    try:
                        await asyncio.wait_for(
                            self._nudge_event.wait(),
                            timeout=self.idle_timeout,
                        )
                        logger.info("Backfill: woken by nudge")
                    except asyncio.TimeoutError:
                        logger.info("Backfill: safety-net poll (timeout=%.0fs)", self.idle_timeout)
                    except asyncio.CancelledError:
                        break
                    sleep_time = 0  # proceed immediately after wake
                cycle_had_work = False
            else:
                # Mid-cycle — short delay between targets
                sleep_time = self.active_interval if did_work else 0.1

            if sleep_time > 0:
                try:
                    await asyncio.sleep(sleep_time)
                except asyncio.CancelledError:
                    break

    # ------------------------------------------------------------------
    # Target discovery and iteration
    # ------------------------------------------------------------------

    async def _refresh_targets(self) -> List[Tuple[str, str]]:
        """Discover all (space_id, graph_id) pairs with KGEntity data."""
        targets: List[Tuple[str, str]] = []
        spaces = self.space_manager.list_spaces()
        for space_id in spaces:
            try:
                graphs = await discover_graphs_sql(self.pool, space_id)
                for gid in graphs:
                    targets.append((space_id, gid))
            except Exception as e:
                logger.warning("Failed to discover graphs for space %s: %s", space_id, e)
        logger.info(
            "Backfill: discovered %d graph(s) across %d space(s)",
            len(targets), len(spaces),
        )
        if targets:
            for sid, gid in targets:
                logger.info("  target: %s / %s", sid, gid)
        return targets

    async def _iteration(self) -> bool:
        """Run one backfill iteration.  Returns True if work was done."""
        # Refresh targets periodically (at the start of each cycle)
        if self._cursor.is_complete_cycle() or not self._cursor.targets:
            self._cursor.targets = await self._refresh_targets()
            self._cursor.index = 0
            if not self._cursor.targets:
                return False

        target = self._cursor.next_target()
        if not target:
            return False

        space_id, graph_id = target
        idx = self._cursor.index
        total = len(self._cursor.targets)

        try:
            result = await backfill_entity_server_properties_sql(
                self.pool, space_id, graph_id,
                batch_size=self.batch_size,
                batch_delay=0,  # no delay within a single batch in service mode
                max_batches=1,  # only one batch per iteration
            )
            if result.entities_patched > 0:
                logger.info(
                    "Backfill [%d/%d]: patched %d entities in %s/%s",
                    idx, total, result.entities_patched, space_id, graph_id,
                )
                return True
            else:
                logger.debug(
                    "Backfill [%d/%d]: %s/%s — nothing to patch",
                    idx, total, space_id, graph_id,
                )
                return False
        except Exception as e:
            logger.error("Backfill [%d/%d] failed for %s/%s: %s", idx, total, space_id, graph_id, e)
            return False


# ------------------------------------------------------------------
# Module-level singleton for convenient nudging from anywhere
# ------------------------------------------------------------------

_backfill_task_ref: Optional[BackfillServerPropertiesTask] = None


def set_backfill_task(task: BackfillServerPropertiesTask) -> None:
    """Register the active backfill task instance (called at startup)."""
    global _backfill_task_ref
    _backfill_task_ref = task


def nudge_backfill() -> None:
    """Convenience: nudge the backfill task if one is registered.

    Safe to call even when no task exists (e.g. during tests or when
    the backfill task is disabled).  This is the recommended entry
    point for SPARQL insert endpoints and other in-process callers
    that don't have a direct reference to the task instance.
    """
    if _backfill_task_ref is not None:
        _backfill_task_ref.nudge()
