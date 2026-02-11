"""
Event Loop Stall Monitor

Detects when the asyncio event loop is blocked for longer than a configurable
threshold.  Also instruments Python's garbage collector to log collection
durations, so stalls can be correlated with GC activity.

Does NOT manipulate GC behavior — Python's automatic GC remains in control.
"""

import asyncio
import gc
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class EventLoopMonitor:
    """Monitors the asyncio event loop for stalls and logs GC durations."""

    def __init__(
        self,
        threshold_ms: float = 100.0,
        check_interval_ms: float = 50.0,
    ):
        """
        Args:
            threshold_ms: Log a warning when the loop is blocked for this many ms.
            check_interval_ms: How often (ms) to schedule the heartbeat callback.
        """
        self._threshold_s = threshold_ms / 1000.0
        self._interval_s = check_interval_ms / 1000.0
        self._running = False
        self._task: Optional[asyncio.Task] = None
        # Stall tracking
        self._stall_count = 0
        self._max_stall_s = 0.0
        # GC tracking
        self._gc_start_time: Optional[float] = None
        self._gc_total_pause_s = 0.0
        self._gc_count = 0
        self._gc_max_pause_s = 0.0
        self._gc_callbacks_installed = False

    def record_request_activity(self) -> None:
        """No-op placeholder for middleware compatibility."""
        pass

    async def start(self) -> None:
        """Start the monitor loop and install GC callbacks."""
        if self._running:
            return
        self._running = True
        self._stall_count = 0
        self._max_stall_s = 0.0
        self._gc_total_pause_s = 0.0
        self._gc_count = 0
        self._gc_max_pause_s = 0.0

        self._install_gc_callbacks()
        self._task = asyncio.create_task(self._monitor_loop())

        thresholds = gc.get_threshold()
        counts = gc.get_count()
        logger.info(
            f"🔍 Event loop monitor started (threshold={self._threshold_s*1000:.0f}ms, "
            f"interval={self._interval_s*1000:.0f}ms, gc=observe-only)"
        )
        logger.info(
            f"🔍 GC thresholds: gen0={thresholds[0]}, gen1={thresholds[1]}, gen2={thresholds[2]} | "
            f"counts: gen0={counts[0]}, gen1={counts[1]}, gen2={counts[2]}"
        )

    async def stop(self) -> None:
        """Stop the monitor loop and remove GC callbacks."""
        self._running = False
        self._remove_gc_callbacks()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info(
            f"🔍 Event loop monitor stopped — "
            f"stalls: {self._stall_count} (max {self._max_stall_s*1000:.0f}ms), "
            f"gc_collections: {self._gc_count} (total {self._gc_total_pause_s*1000:.0f}ms, "
            f"max {self._gc_max_pause_s*1000:.0f}ms)"
        )

    def _install_gc_callbacks(self) -> None:
        """Install GC callbacks to measure collection duration."""
        if self._gc_callbacks_installed:
            return
        gc.callbacks.append(self._gc_callback)
        self._gc_callbacks_installed = True

    def _remove_gc_callbacks(self) -> None:
        """Remove GC callbacks."""
        if not self._gc_callbacks_installed:
            return
        try:
            gc.callbacks.remove(self._gc_callback)
        except ValueError:
            pass
        self._gc_callbacks_installed = False

    def _gc_callback(self, phase: str, info: dict) -> None:
        """Called by the GC at the start and end of each collection."""
        if phase == "start":
            self._gc_start_time = time.monotonic()
        elif phase == "stop" and self._gc_start_time is not None:
            duration = time.monotonic() - self._gc_start_time
            self._gc_start_time = None
            self._gc_count += 1
            self._gc_total_pause_s += duration
            if duration > self._gc_max_pause_s:
                self._gc_max_pause_s = duration
            generation = info.get("generation", "?")
            collected = info.get("collected", 0)
            uncollectable = info.get("uncollectable", 0)
            if duration > self._threshold_s:
                logger.warning(
                    f"⚠️ GC PAUSE: gen{generation} took {duration*1000:.0f}ms "
                    f"(collected={collected}, uncollectable={uncollectable}) "
                    f"[gc #{self._gc_count}]"
                )
            elif duration > 0.010:
                logger.info(
                    f"🗑️ GC: gen{generation} took {duration*1000:.1f}ms "
                    f"(collected={collected})"
                )

    async def _monitor_loop(self) -> None:
        """Periodically sleep and check if more wall-clock time elapsed than expected."""
        try:
            while self._running:
                before = time.monotonic()
                await asyncio.sleep(self._interval_s)
                after = time.monotonic()

                elapsed = after - before
                overshoot = elapsed - self._interval_s

                if overshoot > self._threshold_s:
                    self._stall_count += 1
                    if elapsed > self._max_stall_s:
                        self._max_stall_s = elapsed
                    logger.warning(
                        f"⚠️ EVENT LOOP STALL: blocked for {overshoot*1000:.0f}ms "
                        f"(expected sleep {self._interval_s*1000:.0f}ms, "
                        f"actual {elapsed*1000:.0f}ms) "
                        f"[stall #{self._stall_count}]"
                    )
        except asyncio.CancelledError:
            pass

    @property
    def stall_count(self) -> int:
        return self._stall_count

    @property
    def max_stall_ms(self) -> float:
        return self._max_stall_s * 1000.0
