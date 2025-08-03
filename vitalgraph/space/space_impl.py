
import logging
from typing import Any, Dict, List, Optional, Tuple, Iterator
from rdflib import URIRef, Literal, BNode
from rdflib.term import Variable
from rdflib.graph import Graph


class SpaceImpl:
    """
    Space implementation that provides database access methods for RDF operations.
    
    This class acts as a lightweight wrapper that delegates to database-specific implementations
    (e.g., PostgreSQLSpaceImpl) for actual per-space table management. This separation allows
    for future support of other database backends while maintaining a consistent interface.
    """
    
    def __init__(self, *, space_id: str, db_impl):
        """
        Initialize SpaceImpl with space identifier and database implementation.
        
        Args:
            space_id: Unique string identifier for this space (e.g., "store123")
            db_impl: Instance of PostgreSQLDbImpl for database operations
        """
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.space_id = space_id
        self.db_impl = db_impl
        
        self.logger.info(f"Initializing SpaceImpl for space_id='{space_id}'")
        self.logger.debug(f"Database implementation: {type(db_impl).__name__}")
        
        # Get the database-specific space implementation (currently PostgreSQL only)
        self._space_impl = None
        if hasattr(db_impl, 'get_space_impl'):
            self._space_impl = db_impl.get_space_impl()
            self.logger.debug(f"Using database-specific space implementation: {type(self._space_impl).__name__}")
        else:
            self.logger.warning(f"Database implementation does not provide space_impl - operations will be limited")
        
        self.logger.debug(f"SpaceImpl initialization completed for space '{space_id}'")
    
    async def create(self) -> bool:
        """
        Create the database schema and tables for this space.
        
        Returns:
            True if creation successful, False otherwise
        """
        self.logger.info(f"create() called for space '{self.space_id}'")
        
        try:
            if self._space_impl:
                # Delegate to PostgreSQL implementation
                success = await self._space_impl.create_space_tables(self.space_id)
                if success:
                    self.logger.info(f"✅ Successfully created tables for space '{self.space_id}'")
                else:
                    self.logger.error(f"❌ Failed to create tables for space '{self.space_id}'")
                return success
            else:
                self.logger.warning("No database-specific space implementation available - schema creation skipped")
                return False
            
        except Exception as e:
            self.logger.error(f"create() failed for space '{self.space_id}': {e}")
            return False
    
    def open(self) -> bool:
        """
        Open this space and prepare it for operations.
        
        Returns:
            True if opening successful, False otherwise
        """
        self.logger.info(f"open() called for space '{self.space_id}'")
        
        try:
            if self._space_impl:
                # Check if space tables exist
                exists = self._space_impl.space_exists(self.space_id)
                if exists:
                    self.logger.info(f"✅ Space '{self.space_id}' opened successfully - tables exist")
                    return True
                else:
                    self.logger.error(f"❌ Space '{self.space_id}' cannot be opened - tables do not exist")
                    return False
            else:
                self.logger.warning("No database-specific space implementation available - space opening skipped")
                return False
            
        except Exception as e:
            self.logger.error(f"open() failed for space '{self.space_id}': {e}")
            return False
    
    async def destroy(self) -> bool:
        """
        Destroy this space and all its data permanently.
        
        Returns:
            True if destruction successful, False otherwise
        """
        self.logger.info(f"destroy() called for space '{self.space_id}'")
        
        try:
            if self._space_impl:
                # Delegate to PostgreSQL implementation to delete all tables
                success = await self._space_impl.delete_space_tables(self.space_id)
                if success:
                    self.logger.info(f"✅ Successfully destroyed tables for space '{self.space_id}'")
                else:
                    self.logger.error(f"❌ Failed to destroy tables for space '{self.space_id}'")
                return success
            else:
                self.logger.warning("No database-specific space implementation available - space destruction skipped")
                return False
            
        except Exception as e:
            self.logger.error(f"destroy() failed for space '{self.space_id}': {e}")
            return False
        
    async def exists(self) -> bool:
        """
        Check if this space's tables exist in the database.
        
        Returns:
            True if space tables exist, False otherwise
        """
        try:
            if self._space_impl:
                return await self._space_impl.space_exists(self.space_id)
            else:
                self.logger.warning("No database-specific space implementation available - cannot check existence")
                return False
        except Exception as e:
            self.logger.error(f"exists() failed for space '{self.space_id}': {e}")
            return False
    
    def close(self) -> None:
        """
        Close this space and clean up resources.
        """
        self.logger.info(f"close() called for space '{self.space_id}'")
        
        try:
            # For now, just log the close operation
            # Future implementations might need to:
            # 1. Flush any pending operations
            # 2. Close space-specific database connections
            # 3. Clean up temporary resources
            
            self.logger.debug(f"close() completed for space '{self.space_id}'")
            
        except Exception as e:
            self.logger.error(f"close() failed for space '{self.space_id}': {e}")
    
    def get_db_space_impl(self):
        """
        Get the underlying database-specific space implementation.
        
        Returns:
            The database-specific space implementation (e.g., PostgreSQLSpaceImpl)
            or None if not available
        """
        return self._space_impl
    
    async def initialize_default_namespaces(self) -> None:
        """
        Initialize default RDF namespaces for this space.
        
        Adds standard namespace prefixes (rdf, rdfs, owl, xsd) to the namespace table.
        These are commonly used in most RDF applications.
        """
        self.logger.info(f"Initializing default namespaces for space '{self.space_id}'")
        
        try:
            if self._space_impl and hasattr(self._space_impl, 'namespaces'):
                # Define standard RDF namespaces
                default_namespaces = {
                    'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
                    'rdfs': 'http://www.w3.org/2000/01/rdf-schema#',
                    'owl': 'http://www.w3.org/2002/07/owl#',
                    'xsd': 'http://www.w3.org/2001/XMLSchema#'
                }
                
                # Add each namespace
                for prefix, uri in default_namespaces.items():
                    namespace_id = await self._space_impl.add_namespace(self.space_id, prefix, uri)
                    if namespace_id:
                        self.logger.debug(f"Added default namespace '{prefix}' -> '{uri}' with ID: {namespace_id}")
                    else:
                        self.logger.warning(f"Failed to add default namespace '{prefix}' -> '{uri}'")
                
                self.logger.info(f"Default namespaces initialized for space '{self.space_id}'")
            else:
                self.logger.warning("Cannot initialize default namespaces - no namespace support available")
        except Exception as e:
            self.logger.error(f"Error initializing default namespaces for space '{self.space_id}': {e}")
    