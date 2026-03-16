"""
Pure-PostgreSQL database implementation for the sparql_sql backend.

Owns its own asyncpg connection pool — no Fuseki dependency.
The pipeline's ``db_provider.configure()`` accepts this instance and
uses ``connection_pool`` for all SQL operations.

Follows the same pattern as ``FusekiPostgreSQLDbImpl`` but without any
Fuseki-related components.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Union, Any

import asyncpg

from ..db_inf import DbImplInterface
from ...utils.resource_manager import track_pool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Transaction wrapper
# ---------------------------------------------------------------------------

class SparqlSQLTransaction:
    """Transaction wrapper with async context manager support."""

    def __init__(self, connection, transaction, pool):
        self.connection = connection
        self.transaction = transaction
        self.pool = pool
        self._committed = False
        self._rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None and not self._committed and not self._rolled_back:
            await self.commit()
        elif not self._rolled_back:
            await self.rollback()

        # Always release connection back to pool
        await self.pool.release(self.connection)

    async def commit(self):
        """Commit the transaction."""
        if not self._committed and not self._rolled_back:
            await self.transaction.commit()
            self._committed = True

    async def rollback(self):
        """Rollback the transaction."""
        if not self._committed and not self._rolled_back:
            await self.transaction.rollback()
            self._rolled_back = True

    def get_connection(self):
        """Get the underlying connection for direct database operations."""
        return self.connection


# ---------------------------------------------------------------------------
# DbImplInterface implementation
# ---------------------------------------------------------------------------

class SparqlSQLDbImpl(DbImplInterface):
    """
    Pure-PostgreSQL database implementation for the sparql_sql backend.

    Manages an asyncpg connection pool used by:
    - The V2 SPARQL-to-SQL pipeline (via ``db_provider.configure(self)``)
    - The service layer (via ``DbImplInterface`` methods)
    - ``SparqlSQLSpaceImpl`` (shared pool)

    Args:
        postgresql_config: Dict with keys: host, port, database, username, password.
            Optional keys: min_pool_size (default 2), max_pool_size (default 10),
            command_timeout (default 60).
    """

    def __init__(self, postgresql_config: dict):
        self.config = postgresql_config
        self.connection_pool: Optional[asyncpg.Pool] = None
        self.connected = False
        self._signal_manager = None

        logger.info("SparqlSQLDbImpl initialized")

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Create the asyncpg connection pool and verify connectivity."""
        try:
            logger.debug("Connecting to PostgreSQL for sparql_sql backend...")

            self.connection_pool = await asyncpg.create_pool(
                host=self.config.get('host', 'localhost'),
                port=self.config.get('port', 5432),
                database=self.config.get('database', 'vitalgraph'),
                user=self.config.get('username', 'vitalgraph_user'),
                password=self.config.get('password', 'vitalgraph_pass'),
                min_size=self.config.get('min_pool_size', 5),
                max_size=self.config.get('max_pool_size', 30),
                command_timeout=self.config.get('command_timeout', 60),
            )

            # Track pool for service-level cleanup
            track_pool(self.connection_pool)

            # Verify the pool works
            async with self.connection_pool.acquire() as conn:
                result = await conn.fetchval('SELECT 1')
                if result == 1:
                    self.connected = True
                    logger.debug("sparql_sql PostgreSQL pool established")
                    return True
                else:
                    logger.error("sparql_sql PostgreSQL connection test failed")
                    return False

        except Exception as e:
            logger.error(f"Failed to connect sparql_sql PostgreSQL: {e}")
            self.connected = False
            return False

    async def disconnect(self) -> bool:
        """Close the asyncpg connection pool."""
        try:
            if self.connection_pool:
                logger.debug("Closing sparql_sql PostgreSQL pool...")

                try:
                    await asyncio.wait_for(
                        self.connection_pool.close(), timeout=3.0
                    )
                    logger.debug("sparql_sql pool closed gracefully")
                except asyncio.TimeoutError:
                    logger.warning("Pool close timed out, terminating...")
                    self.connection_pool.terminate()

                self.connection_pool = None

            self.connected = False
            return True

        except Exception as e:
            logger.error(f"Error closing sparql_sql pool: {e}")
            return False

    async def is_connected(self) -> bool:
        """Check if the connection pool is alive."""
        if not self.connected or not self.connection_pool:
            return False

        try:
            async with self.connection_pool.acquire() as conn:
                await conn.fetchval('SELECT 1')
            return True
        except Exception:
            self.connected = False
            return False

    # ------------------------------------------------------------------
    # Query execution
    # ------------------------------------------------------------------

    async def execute_query(
        self,
        query: str,
        params: Optional[Union[Dict, List]] = None,
    ) -> List[Dict[str, Any]]:
        """Execute a SQL query and return rows as list of dicts."""
        if not self.connected:
            raise RuntimeError("sparql_sql backend not connected")

        try:
            async with self.connection_pool.acquire() as conn:
                if params:
                    if isinstance(params, dict):
                        param_values = list(params.values())
                    else:
                        param_values = params
                    rows = await conn.fetch(query, *param_values)
                else:
                    rows = await conn.fetch(query)

                return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"sparql_sql execute_query error: {e}")
            raise

    async def execute_update(
        self,
        query: str,
        params: Optional[Union[Dict, List]] = None,
    ) -> bool:
        """Execute a SQL update/insert/delete operation."""
        if not self.connected:
            raise RuntimeError("sparql_sql backend not connected")

        try:
            async with self.connection_pool.acquire() as conn:
                if params:
                    if isinstance(params, dict):
                        param_values = list(params.values())
                    else:
                        param_values = params
                    await conn.execute(query, *param_values)
                else:
                    await conn.execute(query)
                return True

        except Exception as e:
            logger.error(f"sparql_sql execute_update error: {e}")
            return False

    # ------------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------------

    async def create_transaction(self) -> SparqlSQLTransaction:
        """Create a transaction with async context manager support."""
        return await self.begin_transaction()

    async def begin_transaction(self) -> SparqlSQLTransaction:
        """Begin a transaction: acquire connection, start txn, return wrapper."""
        if not self.connected:
            raise RuntimeError("sparql_sql backend not connected")

        connection = None
        try:
            connection = await self.connection_pool.acquire()

            from ...utils.resource_manager import track_connection
            track_connection(connection)

            transaction = connection.transaction()
            await transaction.start()

            return SparqlSQLTransaction(connection, transaction, self.connection_pool)

        except Exception as e:
            logger.error(f"sparql_sql begin_transaction error: {e}")
            if connection is not None:
                await self.connection_pool.release(connection)
            raise

    async def commit_transaction(self, transaction: SparqlSQLTransaction) -> bool:
        """Commit a transaction and release its connection."""
        try:
            await transaction.commit()
            await transaction.pool.release(transaction.connection)
            return True
        except Exception as e:
            logger.error(f"sparql_sql commit_transaction error: {e}")
            try:
                await transaction.pool.release(transaction.connection)
            except Exception:
                pass
            return False

    async def rollback_transaction(self, transaction: SparqlSQLTransaction) -> bool:
        """Rollback a transaction and release its connection."""
        try:
            await transaction.rollback()
            await transaction.pool.release(transaction.connection)
            return True
        except Exception as e:
            logger.error(f"sparql_sql rollback_transaction error: {e}")
            try:
                await transaction.pool.release(transaction.connection)
            except Exception:
                pass
            return False

    # ------------------------------------------------------------------
    # Connection info & signal manager
    # ------------------------------------------------------------------

    def get_connection_info(self) -> Dict[str, Any]:
        """Get connection information for diagnostics."""
        return {
            'type': 'postgresql',
            'backend': 'sparql_sql',
            'host': self.config.get('host', 'localhost'),
            'port': self.config.get('port', 5432),
            'database': self.config.get('database', 'vitalgraph'),
            'connected': self.connected,
            'pool_size': self.connection_pool.get_size() if self.connection_pool else 0,
            'pool_max_size': self.connection_pool.get_max_size() if self.connection_pool else 0,
        }

    def set_signal_manager(self, signal_manager):
        """Set the signal manager for this database implementation."""
        self._signal_manager = signal_manager
        logger.debug("Signal manager set on SparqlSQLDbImpl")

    def get_signal_manager(self):
        """Get the signal manager for this database implementation."""
        return self._signal_manager

    # ------------------------------------------------------------------
    # Schema helpers
    # ------------------------------------------------------------------

    async def initialize_schema(self) -> bool:
        """Verify admin tables exist (created during service initialization)."""
        try:
            check_query = """
            SELECT COUNT(*) as table_count
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name IN ('install', 'space', 'graph', 'user', 'process',
                              'agent_type', 'agent', 'agent_endpoint', 'agent_function', 'agent_change_log')
            """
            result = await self.execute_query(check_query)
            table_count = result[0]['table_count'] if result else 0

            if table_count == 10:
                logger.debug("sparql_sql admin tables verified (10/10)")
                return True
            else:
                logger.error(
                    "sparql_sql admin tables missing (%d/10 found)", table_count
                )
                return False

        except Exception as e:
            logger.error(f"Error verifying sparql_sql schema: {e}")
            return False

    async def space_data_tables_exist(self, space_id: str) -> bool:
        """Check if term and rdf_quad tables exist for a space."""
        try:
            check_query = """
            SELECT COUNT(*) as table_count
            FROM information_schema.tables
            WHERE table_name IN ($1, $2)
            AND table_schema = 'public'
            """
            results = await self.execute_query(
                check_query,
                [f'{space_id}_term', f'{space_id}_rdf_quad'],
            )

            if results and len(results) > 0:
                return results[0]['table_count'] == 2
            return False

        except Exception as e:
            logger.error(f"Error checking data tables for space {space_id}: {e}")
            return False
