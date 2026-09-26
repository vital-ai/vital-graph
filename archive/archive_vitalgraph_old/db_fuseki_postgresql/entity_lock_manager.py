"""
PostgreSQL advisory lock manager for entity-level serialization.

Uses a single dedicated PostgreSQL connection to hold all advisory locks.
Multiple locks coexist on one connection — PostgreSQL supports this natively.
Locks auto-release if the connection drops (crash safety).
"""

import asyncio
import hashlib
import logging
import struct
import time
from contextlib import asynccontextmanager
from typing import Dict, Optional

import asyncpg

from ...utils.resource_manager import track_connection

logger = logging.getLogger(__name__)


def uri_to_lock_key(uri: str) -> int:
    """
    Convert a URI to a stable 64-bit advisory lock key.
    
    Uses SHA-256 and takes the first 8 bytes as a signed bigint.
    Collision probability is negligible (~4 billion URIs for 50% chance).
    """
    digest = hashlib.sha256(uri.encode('utf-8')).digest()
    return struct.unpack('!q', digest[:8])[0]


class EntityLockManager:
    """
    Manages entity-level advisory locks via a single dedicated PostgreSQL connection.
    
    Two layers of locking:
    1. Per-entity asyncio.Lock — serializes concurrent requests within this process.
       This is required because PG session-level advisory locks are reentrant on the
       same connection (a second pg_try_advisory_lock for an already-held key returns
       true immediately).
    2. PG advisory lock — coordinates across multiple VitalGraph instances sharing
       the same PostgreSQL database.
    
    Usage:
        async with lock_manager.lock(entity_uri):
            # entity is locked for this service instance
            ...
        # lock released
    """
    
    def __init__(self, postgresql_config: dict):
        self._config = postgresql_config
        self._conn: Optional[asyncpg.Connection] = None
        self._conn_lock = asyncio.Lock()  # serialize SQL on shared connection
        self._held_locks: Dict[int, str] = {}  # lock_key -> entity_uri
        self._entity_locks: Dict[int, asyncio.Lock] = {}  # lock_key -> asyncio.Lock
        self._entity_locks_guard = asyncio.Lock()  # protects _entity_locks dict
    
    async def connect(self):
        """Establish dedicated lock connection."""
        self._conn = await asyncpg.connect(
            host=self._config.get('host', 'localhost'),
            port=self._config.get('port', 5432),
            database=self._config.get('database', 'vitalgraph'),
            user=self._config.get('username', 'vitalgraph_user'),
            password=self._config.get('password', 'vitalgraph_pass'),
            command_timeout=60
        )
        track_connection(self._conn)
        logger.info("EntityLockManager: dedicated lock connection established")
    
    async def disconnect(self):
        """Close lock connection — releases all advisory locks."""
        if self._conn and not self._conn.is_closed():
            try:
                await self._conn.close()
            except Exception as e:
                logger.warning(f"EntityLockManager: error closing connection: {e}")
        self._conn = None
        self._held_locks.clear()
        logger.info("EntityLockManager: disconnected, all locks released")
    
    async def _ensure_connection(self):
        """Reconnect if the lock connection was lost."""
        if self._conn is None or self._conn.is_closed():
            logger.warning("EntityLockManager: lock connection lost, reconnecting...")
            self._held_locks.clear()
            await self.connect()
    
    async def _get_entity_lock(self, lock_key: int) -> asyncio.Lock:
        """Get or create a per-entity asyncio.Lock."""
        async with self._entity_locks_guard:
            if lock_key not in self._entity_locks:
                self._entity_locks[lock_key] = asyncio.Lock()
            return self._entity_locks[lock_key]

    @asynccontextmanager
    async def lock(self, entity_uri: str, timeout_seconds: float = 10.0):
        """
        Async context manager to acquire and release an entity lock.
        
        Acquires an intra-process asyncio.Lock first (serializes within this
        Python process), then a PG advisory lock (coordinates across instances).
        
        Args:
            entity_uri: URI of the entity to lock
            timeout_seconds: Max time to wait for the lock
            
        Raises:
            TimeoutError: If lock cannot be acquired within timeout
        """
        lock_key = uri_to_lock_key(entity_uri)
        entity_lock = await self._get_entity_lock(lock_key)
        start = time.monotonic()

        # Layer 1: intra-process serialization
        waiting = entity_lock.locked()
        if waiting:
            logger.info(f"🔒 WAITING for local lock: {entity_uri} (key={lock_key})")
        try:
            acquired_local = await asyncio.wait_for(
                entity_lock.acquire(), timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"Could not acquire local lock for {entity_uri} within {timeout_seconds}s"
            )

        local_wait = (time.monotonic() - start) * 1000
        logger.info(f"🔒 LOCAL lock acquired: {entity_uri} (key={lock_key}, wait={local_wait:.0f}ms)")

        try:
            # Layer 2: cross-instance PG advisory lock
            remaining = timeout_seconds - (time.monotonic() - start)
            await self._acquire_pg(lock_key, entity_uri, max(remaining, 0.1))
            try:
                yield
            finally:
                await self._release_pg(lock_key, entity_uri)
        finally:
            entity_lock.release()
            elapsed = (time.monotonic() - start) * 1000
            logger.info(f"🔓 Lock RELEASED: {entity_uri} (key={lock_key}, held={elapsed:.0f}ms)")
    
    async def _acquire_pg(self, lock_key: int, entity_uri: str, timeout: float):
        """Acquire PG advisory lock with timeout via polling."""
        start = time.monotonic()
        deadline = start + timeout
        
        while True:
            await self._ensure_connection()
            async with self._conn_lock:
                try:
                    acquired = await self._conn.fetchval(
                        'SELECT pg_try_advisory_lock($1)', lock_key
                    )
                except Exception as e:
                    logger.error(f"EntityLockManager: error acquiring PG lock for {entity_uri}: {e}")
                    self._conn = None
                    acquired = False
            
            if acquired:
                self._held_locks[lock_key] = entity_uri
                elapsed = (time.monotonic() - start) * 1000
                if elapsed > 100:
                    logger.info(f"🔒 Lock acquired: {entity_uri} ({elapsed:.0f}ms wait)")
                else:
                    logger.debug(f"🔒 Lock acquired: {entity_uri} ({elapsed:.0f}ms)")
                return
            
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Could not acquire PG lock for {entity_uri} within {timeout}s"
                )
            await asyncio.sleep(0.05)  # 50ms poll interval
    
    async def _release_pg(self, lock_key: int, entity_uri: str):
        """Release PG advisory lock."""
        try:
            if self._conn and not self._conn.is_closed():
                async with self._conn_lock:
                    await self._conn.fetchval(
                        'SELECT pg_advisory_unlock($1)', lock_key
                    )
            self._held_locks.pop(lock_key, None)
            logger.debug(f"🔓 PG lock released: {entity_uri}")
        except Exception as e:
            logger.error(f"EntityLockManager: error releasing PG lock for {entity_uri}: {e}")
            self._held_locks.pop(lock_key, None)
    
    @property
    def active_lock_count(self) -> int:
        """Number of locks currently held by this instance."""
        return len(self._held_locks)
