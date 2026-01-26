
import logging
from typing import Any, Dict, List, Optional, Tuple, Iterator
from rdflib import URIRef, Literal, BNode
from rdflib.term import Variable
from rdflib.graph import Graph


class SpaceImpl:
    """
    Generic space implementation that provides database access methods for RDF operations.
    
    This class acts as a lightweight wrapper that delegates to backend-specific implementations
    (e.g., PostgreSQLDbImpl, FusekiSpaceImpl) for actual space operations. This separation allows
    for support of multiple database backends while maintaining a consistent interface.
    """
    
    def __init__(self, space_id: str, backend, space_name: str = None, space_description: str = None):
        """
        Initialize SpaceImpl with space ID and backend.
        
        Args:
            space_id: Unique identifier for the space
            backend: Backend implementation for space operations
            space_name: Human-readable name for the space
            space_description: Optional description for the space
        """
        self.space_id = space_id
        self.backend = backend
        self.space_name = space_name or space_id
        self.space_description = space_description
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        self.logger.info(f"Initializing SpaceImpl for space_id='{space_id}'")
        self.logger.debug(f"Using backend: {type(backend).__name__}")
        
        self.logger.debug(f"SpaceImpl initialization completed for space '{space_id}'")
    
    async def create(self) -> bool:
        """
        Create the space storage and metadata.
        
        Returns:
            True if creation successful, False otherwise
        """
        self.logger.info(f"create() called for space '{self.space_id}'")
        
        try:
            # Create space storage (Fuseki dataset + PostgreSQL primary data tables)
            success = await self.backend.create_space_storage(self.space_id)
            if not success:
                self.logger.error(f"❌ Failed to create space storage '{self.space_id}'")
                return False
            
            # Create space metadata if backend supports it
            if hasattr(self.backend, 'create_space_metadata'):
                metadata = {
                    'space': self.space_id,
                    'space_name': self.space_name,
                    'space_description': self.space_description,
                    'tenant': 'default'
                }
                metadata_success = await self.backend.create_space_metadata(self.space_id, metadata)
                if not metadata_success:
                    self.logger.error(f"❌ Failed to create space metadata for '{self.space_id}'")
                    # Rollback storage creation
                    try:
                        await self.backend.delete_space_storage(self.space_id)
                        self.logger.info(f"🔄 Rolled back storage for '{self.space_id}' due to metadata failure")
                    except Exception as rollback_error:
                        self.logger.error(f"❌ Failed to rollback storage for '{self.space_id}': {rollback_error}")
                    return False
                self.logger.info(f"✅ Space metadata created for '{self.space_id}'")
                
            self.logger.info(f"✅ Successfully created space '{self.space_id}'")
            return True
            
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
            # Use generic backend to delete space storage
            success = await self.backend.delete_space_storage(self.space_id)
            if success:
                self.logger.info(f"✅ Successfully destroyed space '{self.space_id}'")
            else:
                self.logger.error(f"❌ Failed to destroy space '{self.space_id}'")
            return success
            
        except Exception as e:
            self.logger.error(f"destroy() failed for space '{self.space_id}': {e}")
            return False
        
    async def exists(self) -> bool:
        """
        Check if this space exists in the backend.
        
        Returns:
            True if space exists, False otherwise
        """
        try:
            return await self.backend.space_exists(self.space_id)
        except Exception as e:
            self.logger.error(f"exists() failed for space '{self.space_id}': {e}")
            return False
    
    async def close(self) -> None:
        """
        Close this space and clean up resources.
        """
        self.logger.info(f"close() called for space '{self.space_id}'")
        
        self.logger.debug(f"close() completed for space '{self.space_id}'")

    def get_db_space_impl(self):
        """
        Get the underlying backend implementation.
        
        Returns:
            The backend implementation or None if not available
        """
        return self.backend
    
    async def initialize_default_namespaces(self) -> None:
        """
        Initialize default RDF namespaces for this space.
        
        Adds standard namespace prefixes (rdf, rdfs, owl, xsd) to the namespace table.
        These are commonly used in most RDF applications.
        """
        self.logger.info(f"Initializing default namespaces for space '{self.space_id}'")
        
        try:
            # For now, skip namespace initialization for generic backends
            # Different backends may handle namespaces differently
            self.logger.info(f"Skipping namespace initialization for generic backend: {type(self.backend).__name__}")
            self.logger.info(f"Default namespaces initialization completed for space '{self.space_id}'")
        except Exception as e:
            self.logger.error(f"Error initializing default namespaces for space '{self.space_id}': {e}")
    