"""
PostgreSQL Space Transaction Management

This module provides transaction management for PostgreSQL space operations,
encapsulating database connections and providing transaction control.
"""

import logging
import uuid
from typing import Optional, Any
from contextlib import asynccontextmanager


class PostgreSQLSpaceTransaction:
    """
    Encapsulates a database connection and transaction state for PostgreSQL space operations.
    
    This class provides an opaque transaction object that can be passed to batch operations
    while hiding the underlying connection details from the caller.
    """
    
    def __init__(self, space_impl: Any, connection: Any, transaction_id: Optional[str] = None):
        """
        Initialize a new transaction object.
        
        Args:
            space_impl: Reference to the PostgreSQLSpaceImpl instance
            connection: The database connection object
            transaction_id: Optional transaction ID (auto-generated if not provided)
        """
        self.space_impl = space_impl
        self.connection = connection
        self.transaction_id = transaction_id or str(uuid.uuid4())
        self.is_active = True
        self.is_committed = False
        self.is_rolled_back = False
        
        # Transaction statistics
        self.quads_added = 0
        self.quads_updated = 0
        self.quads_removed = 0
        self.terms_added = 0
        
        # Set up logging
        self.logger = logging.getLogger(__name__)
        
        self.logger.debug(f"Created transaction {self.transaction_id}")
    
    def increment_quads_added(self, count: int = 1):
        """Increment the count of quads added in this transaction."""
        self.quads_added += count
    
    def increment_quads_updated(self, count: int = 1):
        """Increment the count of quads updated in this transaction."""
        self.quads_updated += count
    
    def increment_quads_removed(self, count: int = 1):
        """Increment the count of quads removed in this transaction."""
        self.quads_removed += count
    
    def increment_terms_added(self, count: int = 1):
        """Increment the count of terms added in this transaction."""
        self.terms_added += count
    
    def get_transaction_stats(self) -> dict:
        """Get current transaction statistics."""
        return {
            'transaction_id': self.transaction_id,
            'quads_added': self.quads_added,
            'quads_updated': self.quads_updated,
            'quads_removed': self.quads_removed,
            'terms_added': self.terms_added,
            'total_operations': self.quads_added + self.quads_updated + self.quads_removed,
            'is_active': self.is_active,
            'is_committed': self.is_committed,
            'is_rolled_back': self.is_rolled_back
        }
    
    @property
    def core(self):
        """Get reference to the space core."""
        return self.space_impl.core if self.space_impl else None
    
    async def commit(self) -> bool:
        """
        Commit the transaction.
        
        Returns:
            bool: True if commit was successful, False otherwise
        """
        if not self.is_active:
            self.logger.warning(f"Transaction {self.transaction_id} is not active, cannot commit")
            return False
            
        if self.is_committed:
            self.logger.warning(f"Transaction {self.transaction_id} already committed")
            return True
            
        if self.is_rolled_back:
            self.logger.warning(f"Transaction {self.transaction_id} was rolled back, cannot commit")
            return False
        
        try:
            self.connection.commit()
            self.is_committed = True
            self.is_active = False
            
            # Log transaction statistics
            stats = self.get_transaction_stats()
            self.logger.info(f"✅ Transaction {self.transaction_id} committed successfully - "
                           f"Operations: {stats['total_operations']} "
                           f"(Added: {stats['quads_added']}, Updated: {stats['quads_updated']}, "
                           f"Removed: {stats['quads_removed']}, Terms: {stats['terms_added']})")
            
            # Clean up connection
            await self._cleanup_connection()
            
            # Notify core that transaction is complete
            if self.core:
                await self.core._remove_active_transaction(self.transaction_id)
            
            self.logger.debug(f"Successfully committed transaction {self.transaction_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to commit transaction {self.transaction_id}: {e}")
            # Try to clean up connection even on failure
            try:
                await self._cleanup_connection()
            except Exception:
                pass
            return False
    
    async def rollback(self) -> bool:
        """
        Rollback the transaction.
        
        Returns:
            bool: True if rollback was successful, False otherwise
        """
        if not self.is_active:
            self.logger.warning(f"Transaction {self.transaction_id} is not active, cannot rollback")
            return False
            
        if self.is_rolled_back:
            self.logger.warning(f"Transaction {self.transaction_id} already rolled back")
            return True
            
        if self.is_committed:
            self.logger.warning(f"Transaction {self.transaction_id} was committed, cannot rollback")
            return False
        
        try:
            self.connection.rollback()
            self.is_rolled_back = True
            self.is_active = False
            
            # Log transaction statistics for rollback
            stats = self.get_transaction_stats()
            self.logger.info(f"🔄 Transaction {self.transaction_id} rolled back - "
                           f"Lost operations: {stats['total_operations']} "
                           f"(Added: {stats['quads_added']}, Updated: {stats['quads_updated']}, "
                           f"Removed: {stats['quads_removed']}, Terms: {stats['terms_added']})")
            
            # Clean up connection
            await self._cleanup_connection()
            
            # Notify core that transaction is complete
            if self.core:
                await self.core._remove_active_transaction(self.transaction_id)
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to rollback transaction {self.transaction_id}: {e}")
            # Try to clean up connection even on failure
            try:
                await self._cleanup_connection()
            except Exception:
                pass
            return False
    
    async def _cleanup_connection(self):
        """
        Clean up the database connection.
        
        Returns the connection to the pool or closes it if using direct connections.
        """
        if self.connection is None:
            return
            
        try:
            # Check if we have access to the core's shared pool
            if self.core and hasattr(self.core, 'shared_pool') and self.core.shared_pool:
                # Return connection to shared pool (synchronous)
                self.core.shared_pool.putconn(self.connection)
                self.logger.debug(f"Returned connection to shared pool for transaction {self.transaction_id}")
            elif self.core and hasattr(self.core, 'rdf_pool') and self.core.rdf_pool:
                # Return connection to RDF pool
                self.core.rdf_pool.putconn(self.connection)
                self.logger.debug(f"Returned connection to RDF pool for transaction {self.transaction_id}")
            else:
                # Close direct connection
                await self.connection.close()
                self.logger.debug(f"Closed direct connection for transaction {self.transaction_id}")
        except Exception as e:
            self.logger.warning(f"Error cleaning up connection for transaction {self.transaction_id}: {e}")
        finally:
            self.connection = None
    
    def get_connection(self):
        """
        Get the underlying database connection.
        
        Returns:
            The database connection object
        """
        if not self.is_active:
            self.logger.warning(f"Transaction {self.transaction_id} is not active")
            return None
        
        return self.connection
    
    def __str__(self) -> str:
        """String representation of the transaction."""
        status = "active"
        if self.is_committed:
            status = "committed"
        elif self.is_rolled_back:
            status = "rolled_back"
        elif not self.is_active:
            status = "inactive"
        
        return f"PostgreSQLSpaceTransaction(id={self.transaction_id}, status={status})"
    
    def __repr__(self) -> str:
        """Detailed representation of the transaction."""
        return (f"PostgreSQLSpaceTransaction(transaction_id='{self.transaction_id}', "
                f"is_active={self.is_active}, is_committed={self.is_committed}, "
                f"is_rolled_back={self.is_rolled_back})")
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit with automatic rollback on exception."""
        if exc_type is not None:
            # Exception occurred, rollback
            await self.rollback()
        elif self.is_active:
            # No exception, commit if still active
            await self.commit()
