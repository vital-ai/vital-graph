"""
Internal incremental backfill task for server-managed entity properties.

Runs inside the VitalGraph service process as a periodic background
coroutine.  Iterates all spaces and graphs, processing one small batch
per iteration so the task remains lightweight and non-blocking.

All database access is direct SQL against the rdf_quad / term tables
(no Jena sidecar required).

Configuration (via environment or VitalGraphConfig):
    BACKFILL_ENABLED                 Enable/disable (default: true)
    BACKFILL_INTERVAL_SECONDS        Seconds between iterations (default: 60)
    BACKFILL_BATCH_SIZE              Entities per batch (default: 200)
    BACKFILL_IDLE_INTERVAL_SECONDS   Interval when no work remains (default: 600)
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
    """Periodic background task that incrementally backfills server properties.

    Requires an asyncpg connection pool and a SpaceManager (for listing
    space_ids).  All SPARQL / sidecar logic is bypassed — backfill
    operates directly on the PostgreSQL rdf_quad and term tables.
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

        # Configuration
        self.enabled = _env_bool('BACKFILL_ENABLED', True)
        self.interval = _env_int('BACKFILL_INTERVAL_SECONDS', 60)
        self.batch_size = _env_int('BACKFILL_BATCH_SIZE', 200)
        self.idle_interval = _env_int('BACKFILL_IDLE_INTERVAL_SECONDS', 600)

    def start(self) -> None:
        """Start the periodic backfill task."""
        if not self.enabled:
            logger.info("Backfill task disabled (BACKFILL_ENABLED=false)")
            return
        if self._task is not None:
            logger.warning("Backfill task already started")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "Backfill task started (interval=%ds, batch_size=%d, idle_interval=%ds)",
            self.interval, self.batch_size, self.idle_interval,
        )

    async def stop(self) -> None:
        """Stop the periodic backfill task."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("Backfill task stopped")

    async def _run_loop(self) -> None:
        """Main loop: sleep → process one batch → repeat."""
        # Initial delay to let the service finish startup
        await asyncio.sleep(10)

        cycle_had_work = False

        while self._running:
            try:
                did_work = await self._iteration()
                if did_work:
                    cycle_had_work = True
            except Exception as e:
                logger.error("Backfill iteration error: %s", e, exc_info=True)
                did_work = False

            # At end of a cycle, decide sleep duration based on whether
            # any work was done across the whole cycle.
            if self._cursor.is_complete_cycle() or not self._cursor.targets:
                if cycle_had_work:
                    sleep_time = self.interval
                    logger.info(
                        "Backfill: cycle complete (work done), next cycle in %ds",
                        sleep_time,
                    )
                else:
                    sleep_time = self.idle_interval
                    logger.info(
                        "Backfill: cycle complete (no work), sleeping %ds",
                        sleep_time,
                    )
                cycle_had_work = False
            else:
                # Within a cycle — always use the short interval
                sleep_time = self.interval if did_work else 1  # 1s between idle targets
            try:
                await asyncio.sleep(sleep_time)
            except asyncio.CancelledError:
                break

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
                logger.info("Backfill: no targets found, sleeping %ds", self.idle_interval)
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
