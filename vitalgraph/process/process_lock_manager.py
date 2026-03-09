"""
Process Lock Manager — distributed advisory lock coordination for jobs.

Adapted from EntityLockManager. Uses PostgreSQL session-level advisory locks
to ensure only one instance (across N ECS tasks) runs a given maintenance
job at a time.

Each (process_type, process_subtype) pair maps to a stable 64-bit lock key
via SHA-256 hashing. Locks auto-release if the connection drops (crash safety).
"""

import asyncio
import hashlib
import logging
import struct
import time
from contextlib import asynccontextmanager
from typing import Dict, Optional

import asyncpg

logger = logging.getLogger(__name__)


# Use a distinct namespace prefix so process lock keys never collide
# with entity lock keys from EntityLockManager.
_LOCK_NAMESPACE = "vitalgraph_process_lock:"


def process_lock_key(process_type: str, process_subtype: Optional[str] = None) -> int:
    """Convert a (process_type, process_subtype) pair to a stable 64-bit advisory lock key.

    Args:
        process_type: E.g. 'analyze', 'vacuum', 'maintenance'.
        process_subtype: E.g. space_id. May be None for global jobs.

    Returns:
        Signed 64-bit integer suitable for pg_try_advisory_lock.
    """
    raw = f"{_LOCK_NAMESPACE}{process_type}:{process_subtype or ''}"
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return struct.unpack("!q", digest[:8])[0]


class ProcessLockManager:
    """Cross-instance job locking using PostgreSQL advisory locks.

    Uses a single dedicated connection (like EntityLockManager) so that
    all held locks share one session and auto-release on disconnect.

    Usage::

        acquired = await lock_manager.try_acquire("analyze", "space_001")
        if acquired:
            try:
                # do work ...
            finally:
                await lock_manager.release("analyze", "space_001")
    """

    def __init__(self, postgresql_config: dict):
        self._config = postgresql_config
        self._conn: Optional[asyncpg.Connection] = None
        self._conn_lock = asyncio.Lock()
        self._held_locks: Dict[int, str] = {}  # lock_key -> description

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self):
        """Establish dedicated lock connection."""
        self._conn = await asyncpg.connect(
            host=self._config.get("host", "localhost"),
            port=self._config.get("port", 5432),
            database=self._config.get("database", "vitalgraph"),
            user=self._config.get("username", "vitalgraph_user"),
            password=self._config.get("password", "vitalgraph_pass"),
            command_timeout=60,
        )
        logger.info("ProcessLockManager: dedicated lock connection established")

    async def disconnect(self):
        """Close lock connection — releases all advisory locks."""
        if self._conn and not self._conn.is_closed():
            try:
                await self._conn.close()
            except Exception as e:
                logger.warning(f"ProcessLockManager: error closing connection: {e}")
        self._conn = None
        self._held_locks.clear()
        logger.info("ProcessLockManager: disconnected, all locks released")

    async def _ensure_connection(self):
        """Reconnect if the lock connection was lost."""
        if self._conn is None or self._conn.is_closed():
            logger.warning("ProcessLockManager: lock connection lost, reconnecting...")
            self._held_locks.clear()
            await self.connect()

    # ------------------------------------------------------------------
    # Lock operations
    # ------------------------------------------------------------------

    async def try_acquire(
        self, process_type: str, process_subtype: Optional[str] = None
    ) -> bool:
        """Try to acquire an advisory lock for a job. Non-blocking.

        Args:
            process_type: Job type (e.g. 'analyze', 'vacuum', 'maintenance').
            process_subtype: Optional sub-key (e.g. space_id).

        Returns:
            True if lock was acquired, False if another instance holds it.
        """
        key = process_lock_key(process_type, process_subtype)
        desc = f"{process_type}:{process_subtype or '*'}"

        await self._ensure_connection()
        async with self._conn_lock:
            try:
                acquired = await self._conn.fetchval(
                    "SELECT pg_try_advisory_lock($1)", key
                )
            except Exception as e:
                logger.error("ProcessLockManager: error acquiring lock for %s: %s", desc, e)
                self._conn = None
                return False

        if acquired:
            self._held_locks[key] = desc
            logger.debug("ProcessLockManager: acquired lock for %s (key=%d)", desc, key)
        else:
            logger.debug("ProcessLockManager: lock busy for %s (key=%d)", desc, key)
        return bool(acquired)

    async def release(
        self, process_type: str, process_subtype: Optional[str] = None
    ) -> None:
        """Release a previously acquired advisory lock.

        Safe to call even if the lock was not held (no-op in that case).
        """
        key = process_lock_key(process_type, process_subtype)
        desc = f"{process_type}:{process_subtype or '*'}"

        if key not in self._held_locks:
            return

        try:
            if self._conn and not self._conn.is_closed():
                async with self._conn_lock:
                    await self._conn.fetchval(
                        "SELECT pg_advisory_unlock($1)", key
                    )
            self._held_locks.pop(key, None)
            logger.debug("ProcessLockManager: released lock for %s", desc)
        except Exception as e:
            logger.error("ProcessLockManager: error releasing lock for %s: %s", desc, e)
            self._held_locks.pop(key, None)

    @asynccontextmanager
    async def lock(self, process_type: str, process_subtype: Optional[str] = None):
        """Context manager that acquires a lock or raises if unavailable.

        Usage::

            async with lock_manager.lock("maintenance"):
                # guaranteed single-instance execution
                ...

        Raises:
            RuntimeError: If the lock could not be acquired (another instance holds it).
        """
        acquired = await self.try_acquire(process_type, process_subtype)
        if not acquired:
            desc = f"{process_type}:{process_subtype or '*'}"
            raise RuntimeError(f"Could not acquire process lock for {desc}")
        try:
            yield
        finally:
            await self.release(process_type, process_subtype)

    # ------------------------------------------------------------------
    # Info
    # ------------------------------------------------------------------

    @property
    def active_lock_count(self) -> int:
        """Number of locks currently held by this instance."""
        return len(self._held_locks)
