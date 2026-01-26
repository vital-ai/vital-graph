#!/usr/bin/env python3
"""
Resource Manager for VitalGraph

This module provides utilities for proper cleanup of asyncio resources
to prevent ResourceWarning messages from unclosed connections and sessions.
"""

import asyncio
import logging
import weakref
from typing import Set, Any, Optional
import aiohttp
import asyncpg

logger = logging.getLogger(__name__)


class ResourceManager:
    """
    Global resource manager to track and cleanup asyncio resources.
    
    This helps prevent ResourceWarning messages by ensuring all
    asyncpg connections and aiohttp client sessions are properly closed.
    """
    
    def __init__(self):
        self._connections: Set[asyncpg.Connection] = set()
        self._sessions: Set[aiohttp.ClientSession] = set()
        self._pools: Set[asyncpg.Pool] = set()
        self._cleanup_callbacks = []
        
    def register_connection(self, connection: asyncpg.Connection) -> None:
        """Register an asyncpg connection for cleanup."""
        if connection:
            self._connections.add(connection)
            # Don't use weak references for connections as they may be removed prematurely
            # We'll rely on explicit cleanup in cleanup_all() method
    
    def register_session(self, session: aiohttp.ClientSession) -> None:
        """Register an aiohttp client session for cleanup."""
        if session and not session.closed:
            self._sessions.add(session)
            # Use weak reference to avoid keeping session alive
            weakref.finalize(session, self._remove_session, session)
    
    def register_pool(self, pool: asyncpg.Pool) -> None:
        """Register an asyncpg connection pool for cleanup."""
        if pool:
            self._pools.add(pool)
            # Note: asyncpg.Pool doesn't support weak references, so we track directly
    
    def _remove_connection(self, connection: asyncpg.Connection) -> None:
        """Remove connection from tracking."""
        self._connections.discard(connection)
    
    def _remove_session(self, session: aiohttp.ClientSession) -> None:
        """Remove session from tracking."""
        self._sessions.discard(session)
    
    def _remove_pool(self, pool: asyncpg.Pool) -> None:
        """Remove pool from tracking."""
        self._pools.discard(pool)
    
    async def cleanup_all(self) -> None:
        """Clean up all tracked resources."""
        logger.info(f"🧹 ResourceManager: Cleaning up {len(self._connections)} connections, {len(self._sessions)} sessions, {len(self._pools)} pools")
        
        # Log details of all tracked connections
        if self._connections:
            logger.info(f"🧹 Connection details:")
            for i, connection in enumerate(self._connections, 1):
                try:
                    conn_info = f"  {i:2d}. {connection} (closed: {connection.is_closed()})"
                    if hasattr(connection, '_addr'):
                        conn_info += f" addr: {connection._addr}"
                    if hasattr(connection, '_params'):
                        conn_info += f" db: {getattr(connection._params, 'database', 'unknown')}"
                    logger.info(conn_info)
                except Exception as e:
                    logger.info(f"  {i:2d}. {connection} (error getting details: {e})")
        
        # Log details of all tracked sessions
        if self._sessions:
            logger.info(f"🧹 Session details:")
            for i, session in enumerate(self._sessions, 1):
                try:
                    sess_info = f"  {i:2d}. {session} (closed: {session.closed})"
                    if hasattr(session, '_connector'):
                        sess_info += f" connector: {session._connector}"
                    logger.info(sess_info)
                except Exception as e:
                    logger.info(f"  {i:2d}. {session} (error getting details: {e})")
        
        # Log details of all tracked pools
        if self._pools:
            logger.info(f"🧹 Pool details:")
            for i, pool in enumerate(self._pools, 1):
                try:
                    pool_info = f"  {i:2d}. {pool}"
                    if hasattr(pool, '_closed'):
                        pool_info += f" (closed: {pool._closed})"
                    if hasattr(pool, '_con'):
                        pool_info += f" connections: {len(pool._con) if pool._con else 0}"
                    logger.info(pool_info)
                except Exception as e:
                    logger.info(f"  {i:2d}. {pool} (error getting details: {e})")
        
        # Run cleanup callbacks first
        for callback in self._cleanup_callbacks:
            try:
                await callback()
            except Exception as e:
                logger.debug(f"Error in cleanup callback: {e}")
        
        # Close all sessions with aggressive cleanup
        sessions_closed = 0
        for session in list(self._sessions):
            try:
                if not session.closed:
                    # Close the session
                    await session.close()
                    sessions_closed += 1
                    
                    # Wait for connector to close properly
                    if hasattr(session, '_connector') and session._connector:
                        await session._connector.close()
                    
                    # Extended delay for complete cleanup
                    await asyncio.sleep(0.2)
            except Exception as e:
                logger.debug(f"Error closing session: {e}")
        
        # Close all pools (which will close their connections)
        pools_closed = 0
        for pool in list(self._pools):
            try:
                logger.info(f"🧹 Closing pool: {pool}")
                await pool.close()
                logger.info(f"🧹 Pool closed successfully: {pool}")
                pools_closed += 1
            except Exception as e:
                logger.warning(f"🧹 Error closing pool {pool}: {e}")
                # Try to terminate if close failed
                try:
                    pool.terminate()
                    pools_closed += 1
                    logger.info(f"🧹 Pool terminated after close error: {pool}")
                except Exception as term_e:
                    logger.warning(f"🧹 Error terminating pool after close error: {term_e}")
        
        # Close all individual connections
        connections_closed = 0
        connections_already_closed = 0
        for connection in list(self._connections):
            try:
                if not connection.is_closed():
                    logger.debug(f"Closing open connection: {connection}")
                    await connection.close()
                    connections_closed += 1
                else:
                    connections_already_closed += 1
                    logger.debug(f"Connection already closed: {connection}")
            except Exception as e:
                logger.debug(f"Error closing connection {connection}: {e}")
                # Try to close anyway in case is_closed() is unreliable
                try:
                    await connection.close()
                    connections_closed += 1
                except Exception as close_e:
                    logger.debug(f"Failed to force close connection: {close_e}")
        
        logger.info(f"🧹 Connection summary: {connections_closed} closed, {connections_already_closed} already closed")
        
        # Clear all collections
        self._connections.clear()
        self._sessions.clear()
        self._pools.clear()
        self._cleanup_callbacks.clear()
        
        logger.info(f"🧹 ResourceManager: Closed {sessions_closed} sessions, {pools_closed} pools, {connections_closed} connections")
        
        # Extended final delay to ensure all async cleanup completes
        await asyncio.sleep(0.5)
        
        # Force garbage collection to help with cleanup
        import gc
        gc.collect()
        
        # Additional delay for any remaining async operations
        await asyncio.sleep(0.3)
    
    def add_cleanup_callback(self, callback) -> None:
        """Add a cleanup callback to be called during cleanup_all."""
        self._cleanup_callbacks.append(callback)


# Global resource manager instance
_resource_manager = ResourceManager()


def get_resource_manager() -> ResourceManager:
    """Get the global resource manager instance."""
    return _resource_manager


async def cleanup_resources() -> None:
    """Clean up all tracked resources globally."""
    await _resource_manager.cleanup_all()


def track_connection(connection: asyncpg.Connection) -> asyncpg.Connection:
    """Track an asyncpg connection for cleanup."""
    _resource_manager.register_connection(connection)
    return connection


def track_session(session: aiohttp.ClientSession) -> aiohttp.ClientSession:
    """Track an aiohttp client session for cleanup."""
    _resource_manager.register_session(session)
    return session


def track_pool(pool: asyncpg.Pool) -> asyncpg.Pool:
    """Track an asyncpg connection pool for cleanup."""
    _resource_manager.register_pool(pool)
    return pool
