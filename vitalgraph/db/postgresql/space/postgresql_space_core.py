import logging
import asyncio
from typing import Dict, List, Optional, Any, Union, Tuple
from contextlib import asynccontextmanager
import psycopg
from psycopg.rows import dict_row

# Import PostgreSQL utilities
from ..postgresql_log_utils import PostgreSQLLogUtils
from .postgresql_space_utils import PostgreSQLSpaceUtils
from .postgresql_space_transaction import PostgreSQLSpaceTransaction


class PostgreSQLSpaceCore:
    """
    Core connection management for PostgreSQL space operations.
    
    Handles all database connection lifecycle, pooling, and health monitoring.
    This class is instantiated by PostgreSQLSpaceImpl and provides connection
    services to all space operations.
    """
    
    # core orchestrator and db connection management

    # include transaction and context object definiitions
    # that are passed to functions in place of "self"


    def __init__(self, connection_string: str, global_prefix: str = "vitalgraph", 
                 pool_config: Optional[Dict[str, Any]] = None, shared_pool=None):
        """
        Initialize PostgreSQL space core with connection management.
        
        Args:
            connection_string: PostgreSQL connection string
            global_prefix: Global prefix for table names
            pool_config: Optional connection pool configuration
            shared_pool: Optional shared psycopg3 ConnectionPool instance
        """
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        self.connection_string = connection_string
        self.global_prefix = global_prefix
        
        self.rdf_pool = None
        self.shared_pool = shared_pool
        
        # Initialize utils instance for timing operations
        self.utils = PostgreSQLLogUtils()
        
        # Transaction management
        self.active_transactions: Dict[str, PostgreSQLSpaceTransaction] = {}
        
        # Validate global prefix using utils
        PostgreSQLSpaceUtils.validate_global_prefix(global_prefix)
    
    def get_connection(self):
        """
        Get a database connection. 
        
        WARNING: This method is deprecated for pooled connections.
        Use get_db_connection() context manager instead to ensure proper connection lifecycle.
        
        Returns:
            psycopg.Connection: Database connection (direct connection only)
        """
        # Always use direct connections for get_connection() to avoid leaks
        # Pooled connections should use the context manager
        try:
            self.logger.debug("Creating direct connection (get_connection method)")
            conn = psycopg.connect(self.connection_string, row_factory=dict_row)
            self.logger.debug("Successfully created direct connection")
            return conn
        except Exception as e:
            self.logger.error(f"Failed to create direct connection: {e}")
            raise
    
    def return_connection(self, conn) -> None:
        """
        Return a connection to the shared psycopg3 pool or close it if direct connection.
        
        Args:
            conn: Database connection to return
        """
        if self.shared_pool and conn:
            # Return connection to shared psycopg3 pool
            try:
                self.shared_pool.putconn(conn)
                self.logger.debug("Returned connection to shared psycopg3 pool")
            except Exception as e:
                self.logger.warning(f"Failed to return connection to pool, closing directly: {e}")
                try:
                    conn.close()
                except Exception:
                    pass
        elif conn:
            # Close direct connection (fallback case)
            try:
                conn.close()
                self.logger.debug("Closed direct connection")
            except Exception as e:
                self.logger.warning(f"Error closing connection: {e}")
    
    @asynccontextmanager
    async def get_db_connection(self):
        """
        Async context manager for automatic connection management using shared or dedicated psycopg3 pool.
        
        Usage:
            async with self.get_db_connection() as conn:
                # Use connection
                cursor = conn.cursor()
                # ... database operations
        """
        if self.shared_pool:
            # Use shared psycopg3 ConnectionPool (shared with SQLAlchemy)
            with self.shared_pool.connection() as conn:
                self.logger.debug("Using shared psycopg3 ConnectionPool connection")
                yield conn
        elif self.rdf_pool:
            # Use dedicated RDF psycopg3 ConnectionPool
            with self.rdf_pool.connection() as conn:
                self.logger.debug("Using dedicated RDF psycopg3 ConnectionPool connection")
                yield conn
        else:
            # Fallback to direct connection
            conn = None
            try:
                self.logger.debug("Creating direct connection for RDF operation (fallback)")
                conn = psycopg.connect(self.connection_string, row_factory=dict_row)
                yield conn
            finally:
                if conn:
                    try:
                        conn.close()
                        self.logger.debug("Closed direct connection")
                    except Exception as e:
                        self.logger.warning(f"Error closing connection: {e}")
    
    def get_pool_stats(self) -> dict:
        """
        Get connection pool statistics for shared or dedicated RDF psycopg3 ConnectionPool.
        
        Returns:
            dict: Pool statistics including size, available connections, etc.
        """
        if self.shared_pool:
            try:
                # Get shared psycopg3 ConnectionPool statistics
                return {
                    'pool_enabled': True,
                    'pool_type': 'shared_psycopg3',
                    'min_size': self.shared_pool.min_size,
                    'max_size': self.shared_pool.max_size,
                    'name': getattr(self.shared_pool, 'name', 'shared_pool'),
                    'open': getattr(self.shared_pool, 'open', True),
                    'closed': getattr(self.shared_pool, 'closed', False)
                }
            except Exception as e:
                self.logger.warning(f"Failed to get shared pool stats: {e}")
        elif self.rdf_pool:
            try:
                # Get dedicated psycopg3 ConnectionPool statistics
                return {
                    'pool_enabled': True,
                    'pool_type': 'dedicated_rdf_psycopg3',
                    'min_size': self.rdf_pool.min_size,
                    'max_size': self.rdf_pool.max_size,
                    'name': getattr(self.rdf_pool, 'name', 'rdf_pool'),
                    'open': getattr(self.rdf_pool, 'open', True),
                    'closed': getattr(self.rdf_pool, 'closed', False)
                }
            except Exception as e:
                self.logger.warning(f"Failed to get psycopg3 pool stats: {e}")
                return {'pool_enabled': True, 'pool_type': 'shared_psycopg3', 'error': str(e)}
        else:
            return {'pool_enabled': False, 'pool_type': 'direct_connections'}
    
    async def health_check(self) -> bool:
        """
        Perform a health check on the connection pool.
        
        Returns:
            bool: True if pool is healthy, False otherwise
        """
        try:
            # Use the async context manager for health check
            async with self.get_db_connection() as conn:
                cursor = conn.cursor()
                await cursor.execute('SELECT 1')
                result = await cursor.fetchone()
                return result is not None
        except Exception as e:
            self.logger.error(f"Health check failed: {e}")
            return False
    
    def close(self):
        """
        Close the RDF connection pool and clean up resources.
        """
        if self.rdf_pool:
            try:
                self.logger.info("Closing dedicated RDF psycopg3 ConnectionPool")
                self.rdf_pool.close()
                self.rdf_pool = None
                self.logger.info("Successfully closed RDF ConnectionPool")
            except Exception as e:
                self.logger.warning(f"Error closing RDF ConnectionPool: {e}")
    
    def get_manager_info(self, space_impl) -> Dict[str, Any]:
        """
        Get general information about this space manager.
        
        Args:
            space_impl: Reference to the space implementation for accessing cached spaces
        
        Returns:
            dict: Manager information
        """
        pool_stats = self.get_pool_stats()
        return {
            "global_prefix": self.global_prefix,
            "connected": self.connection_string is not None,
            "cached_spaces": list(space_impl._schema_cache.keys()),
            "cache_size": len(space_impl._schema_cache),
            "pool_info": pool_stats
        }
    
    def _ensure_text_search_extensions(self) -> bool:
        """
        Ensure that required PostgreSQL extensions for text search are enabled.
        This includes pg_trgm for trigram-based regex matching.
        
        Returns:
            bool: True if extensions are available, False otherwise
        """
        try:
            conn = self.get_connection()
            try:
                with conn.cursor() as cursor:
                    # Check if pg_trgm extension is available and create if needed
                    cursor.execute("""
                        CREATE EXTENSION IF NOT EXISTS pg_trgm;
                    """)
                    
                    # Verify the extension is working by testing a simple trigram query
                    cursor.execute("""
                        SELECT 'test' % 'test' AS trigram_test;
                    """)
                    result = cursor.fetchone()
                    
                    if result and result[0]:
                        self.logger.info("✅ PostgreSQL text search extensions (pg_trgm) are available")
                        return True
                    else:
                        self.logger.warning("⚠️ pg_trgm extension test failed")
                        return False
                        
            finally:
                conn.close()
                
        except Exception as e:
            self.logger.error(f"❌ Failed to ensure text search extensions: {e}")
            return False
    
    def space_exists(self, space_id: str, space_impl) -> bool:
        """
        Check if tables for a space exist in the database.
        
        Args:
            space_id: Space identifier
            space_impl: Reference to the space implementation for accessing table names
            
        Returns:
            bool: True if space tables exist, False otherwise
        """
        from ..postgresql_log_utils import PostgreSQLLogUtils
        PostgreSQLSpaceUtils.validate_space_id(space_id)
        
        try:
            table_names = space_impl._get_table_names(space_id)
            
            conn = self.get_connection()
            try:
                cursor = conn.cursor()
                # Check if the main rdf_quad table exists
                rdf_quad_table = table_names.get('rdf_quad')
                if not rdf_quad_table:
                    self.logger.debug(f"No rdf_quad table name found for space '{space_id}'")
                    return False
                
                self.logger.debug(f"Checking if table '{rdf_quad_table}' exists for space '{space_id}'")
                
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = %s
                    )
                """, (rdf_quad_table,))
                
                result = cursor.fetchone()
                self.logger.debug(f"Raw result from query: {result} (type: {type(result)})")
                if result:
                    # Handle different result formats
                    if isinstance(result, (tuple, list)) and len(result) > 0:
                        exists = bool(result[0])
                    else:
                        # If result is not indexable, try to convert directly
                        exists = bool(result)
                else:
                    exists = False
                self.logger.debug(f"Table '{rdf_quad_table}' exists: {exists}")
                return exists
                
            finally:
                conn.close()
                
        except Exception as e:
            import traceback
            self.logger.error(f"Error checking if space '{space_id}' exists: {type(e).__name__}: {e}")
            self.logger.error(f"Full traceback: {traceback.format_exc()}")
            return False
    
    def list_spaces(self) -> List[str]:
        """
        List all spaces that have tables in the database.
        
        Returns:
            list: List of space IDs
        """
        try:
            conn = self.get_connection()
            try:
                with conn.cursor() as cursor:
                    # Look for tables matching the pattern: {global_prefix}__{space_id}__rdf_quad
                    pattern = f"{self.global_prefix}__%%__rdf_quad"
                    
                    cursor.execute("""
                        SELECT table_name 
                        FROM information_schema.tables 
                        WHERE table_name LIKE %s
                        ORDER BY table_name
                    """, (pattern,))
                    
                    results = cursor.fetchall()
                    
                    # Extract space IDs from table names
                    spaces = []
                    for row in results:
                        table_name = row[0]
                        # Parse: {global_prefix}__{space_id}__rdf_quad
                        parts = table_name.split('__')
                        if len(parts) >= 3 and parts[0] == self.global_prefix and parts[-1] == 'rdf_quad':
                            space_id = '__'.join(parts[1:-1])  # Handle space IDs with underscores
                            spaces.append(space_id)
                    
                    return spaces
                    
            finally:
                conn.close()
                
        except Exception as e:
            self.logger.error(f"Error listing spaces: {e}")
            return []
    
    def get_space_info(self, space_id: str, space_impl) -> Dict[str, Any]:
        """
        Get information about a specific space.
        
        Args:
            space_id: Space identifier
            space_impl: Reference to the space implementation for accessing methods
            
        Returns:
            dict: Space information including table details
        """
        from ..postgresql_log_utils import PostgreSQLLogUtils
        PostgreSQLSpaceUtils.validate_space_id(space_id)
        
        try:
            if not self.space_exists(space_id, space_impl):
                return {
                    "space_id": space_id,
                    "exists": False,
                    "error": "Space does not exist"
                }
            
            table_names = space_impl._get_table_names(space_id)
            
            conn = self.get_connection()
            try:
                with conn.cursor(row_factory=dict_row) as cursor:
                    # Get table sizes and row counts
                    table_info = {}
                    
                    for table_base, table_name in table_names.items():
                        try:
                            # Get row count
                            cursor.execute(f"SELECT COUNT(*) as count FROM {table_name}")
                            count_result = cursor.fetchone()
                            row_count = count_result['count'] if count_result else 0
                            
                            # Get table size
                            cursor.execute("""
                                SELECT pg_size_pretty(pg_total_relation_size(%s)) as size
                            """, (table_name,))
                            size_result = cursor.fetchone()
                            table_size = size_result['size'] if size_result else 'Unknown'
                            
                            table_info[table_base] = {
                                "name": table_name,
                                "rows": row_count,
                                "size": table_size
                            }
                            
                        except Exception as e:
                            table_info[table_base] = {
                                "name": table_name,
                                "error": str(e)
                            }
                    
                    return {
                        "space_id": space_id,
                        "exists": True,
                        "tables": table_info,
                        "global_prefix": self.global_prefix
                    }
                    
            finally:
                conn.close()
                
        except Exception as e:
            self.logger.error(f"Error getting space info for '{space_id}': {e}")
            return {
                "space_id": space_id,
                "exists": False,
                "error": str(e)
            }
    
    async def create_transaction(self, space_impl) -> PostgreSQLSpaceTransaction:
        """
        Create a new transaction object with a database connection.
        
        Args:
            space_impl: Reference to the PostgreSQLSpaceImpl instance
            
        Returns:
            PostgreSQLSpaceTransaction: New transaction object
        """
        try:
            # Get a connection - we need to manage it manually since the transaction will own it
            if self.shared_pool:
                # For shared pool (psycopg3 ConnectionPool), get connection synchronously
                conn = self.shared_pool.getconn()
            elif self.rdf_pool:
                # For RDF pool, get connection from psycopg3 pool
                conn = self.rdf_pool.getconn()
            else:
                # Fallback to direct connection
                conn = psycopg.connect(self.connection_string, row_factory=dict_row)
            
            # Create transaction object
            transaction = PostgreSQLSpaceTransaction(space_impl, conn)
            
            # Track the active transaction
            self.active_transactions[transaction.transaction_id] = transaction
            
            self.logger.debug(f"Created transaction {transaction.transaction_id}")
            return transaction
                
        except Exception as e:
            self.logger.error(f"Failed to create transaction: {e}")
            raise
    
    async def get_transaction(self, space_impl) -> PostgreSQLSpaceTransaction:
        """
        Get a new transaction object (alias for create_transaction).
        
        Args:
            space_impl: Reference to the PostgreSQLSpaceImpl instance
            
        Returns:
            PostgreSQLSpaceTransaction: New transaction object
        """
        return await self.create_transaction(space_impl)
    
    async def commit_transaction_object(self, transaction: PostgreSQLSpaceTransaction) -> bool:
        """
        Commit a specific transaction object.
        
        Args:
            transaction: The transaction object to commit
            
        Returns:
            bool: True if commit was successful, False otherwise
        """
        if not isinstance(transaction, PostgreSQLSpaceTransaction):
            self.logger.error("Invalid transaction object provided")
            return False
            
        return await transaction.commit()
    
    async def rollback_transaction_object(self, transaction: PostgreSQLSpaceTransaction) -> bool:
        """
        Rollback a specific transaction object.
        
        Args:
            transaction: The transaction object to rollback
            
        Returns:
            bool: True if rollback was successful, False otherwise
        """
        if not isinstance(transaction, PostgreSQLSpaceTransaction):
            self.logger.error("Invalid transaction object provided")
            return False
            
        return await transaction.rollback()
    
    def get_active_transaction_count(self) -> int:
        """
        Get the number of currently active transactions.
        
        Returns:
            int: Number of active transactions
        """
        active_count = sum(1 for tx in self.active_transactions.values() if tx.is_active)
        return active_count
    
    async def rollback_all_transactions(self) -> Dict[str, bool]:
        """
        Rollback all pending transactions.
        
        This is typically used during shutdown or error recovery.
        
        Returns:
            Dict[str, bool]: Dictionary mapping transaction IDs to rollback success status
        """
        results = {}
        
        # Get list of active transactions to avoid modification during iteration
        active_transactions = [(tx_id, tx) for tx_id, tx in self.active_transactions.items() if tx.is_active]
        
        self.logger.info(f"Rolling back {len(active_transactions)} active transactions")
        
        for tx_id, transaction in active_transactions:
            try:
                success = await transaction.rollback()
                results[tx_id] = success
                if success:
                    self.logger.debug(f"Successfully rolled back transaction {tx_id}")
                else:
                    self.logger.warning(f"Failed to rollback transaction {tx_id}")
            except Exception as e:
                self.logger.error(f"Error rolling back transaction {tx_id}: {e}")
                results[tx_id] = False
        
        return results
    
    async def _remove_active_transaction(self, transaction_id: str) -> None:
        """
        Remove a transaction from the active transactions list.
        
        This is called internally by PostgreSQLSpaceTransaction when it completes.
        
        Args:
            transaction_id: ID of the transaction to remove
        """
        if transaction_id in self.active_transactions:
            del self.active_transactions[transaction_id]
            self.logger.debug(f"Removed transaction {transaction_id} from active list")
    
    async def commit_transaction(self, connection=None) -> bool:
        """
        Manually commit the current transaction.
        
        This is useful when using auto_commit=False in batch operations
        to commit multiple batches in a single transaction.
        
        Args:
            connection: Optional connection to commit. If None, gets a new connection.
        
        Returns:
            True if commit was successful, False otherwise
        """
        try:
            if connection is not None:
                connection.commit()
                self.logger.debug("💾 Transaction committed successfully")
                return True
            else:
                with self.get_connection() as conn:
                    conn.commit()
                    self.logger.debug("💾 Transaction committed successfully")
                    return True
        except Exception as e:
            self.logger.error(f"Error committing transaction: {e}")
            return False

    def close_pool(self) -> None:
        """
        Close the connection pool and all connections.
        """
        if self.rdf_pool:
            try:
                self.rdf_pool.close()
                self.logger.info("Connection pool closed successfully")
            except Exception as e:
                self.logger.error(f"Error closing connection pool: {e}")
            finally:
                self.rdf_pool = None


