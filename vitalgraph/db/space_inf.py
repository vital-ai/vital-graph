"""
Abstract interface for VitalGraph space backend implementations.

This module defines the abstract base classes and factory patterns needed to support
multiple backend implementations for VitalGraph spaces, including PostgreSQL, Oxigraph,
Fuseki, and mock implementations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Any, AsyncGenerator, Tuple, Union
from contextlib import asynccontextmanager
import logging

# RDFLib imports for type hints
from rdflib import URIRef, Literal, BNode, Variable
from rdflib.term import Identifier

# Import SPARQL interface from separate module
from .sparql_inf import SparqlBackendInterface


class SpaceBackendInterface(ABC):
    """
    Abstract interface for VitalGraph space backend implementations.
    
    This interface defines the contract that all space backends must implement
    to provide RDF storage and retrieval capabilities. It covers:
    
    - Space lifecycle management (create, delete, exists)
    - RDF quad storage and retrieval
    - Term management and caching
    - Namespace management
    - SPARQL query support
    - Batch operations for performance
    - Connection and resource management
    
    Each backend implementation (PostgreSQL, Oxigraph, Fuseki, Mock) must
    provide concrete implementations of all these methods.
    """
    
    # ========================================
    # Core Lifecycle Methods
    # ========================================
    
    @abstractmethod
    async def init_space_storage(self, space_id: str) -> bool:
        """
        Initialize storage for a space (tables, collections, etc.).
        
        Args:
            space_id: Unique identifier for the space
            
        Returns:
            True if initialization successful, False otherwise
        """
        pass
    
    @abstractmethod
    async def delete_space_storage(self, space_id: str) -> bool:
        """
        Delete all data and storage for a space.
        
        Args:
            space_id: Unique identifier for the space
            
        Returns:
            True if deletion successful, False otherwise
        """
        pass
    
    @abstractmethod
    async def space_storage_exists(self, space_id: str) -> bool:
        """
        Check if storage for a space exists in the backend.
        
        Args:
            space_id: Unique identifier for the space
            
        Returns:
            True if space storage exists, False otherwise
        """
        pass
    
    @abstractmethod
    async def list_spaces(self) -> List[str]:
        """
        List all spaces that exist in this backend.
        
        Returns:
            List of space identifiers
        """
        pass
    
    @abstractmethod
    async def get_space_info(self, space_id: str) -> Dict[str, Any]:
        """
        Get information about a specific space.
        
        Args:
            space_id: Unique identifier for the space
            
        Returns:
            Dictionary containing space metadata and statistics
        """
        pass
    
    # ========================================
    # Connection Management
    # ========================================
    
    @abstractmethod
    @asynccontextmanager
    async def get_backend_connection(self):
        """
        Async context manager for backend-specific connections.
        
        For testing and backend-specific operations that need direct access.
        
        Yields:
            Backend connection object (database, HTTP client, etc.)
        """
        pass
    
    @abstractmethod
    def close(self) -> None:
        """
        Close all connections and clean up resources.
        """
        pass
    
    # ========================================
    # Term Management
    # ========================================
    
    @abstractmethod
    async def add_term(self, space_id: str, term_text: str, term_type: str, 
                      lang: Optional[str] = None, datatype_id: Optional[int] = None) -> Optional[str]:
        """
        Add a term to the terms dictionary for a specific space.
        
        Args:
            space_id: Space identifier
            term_text: The term text (URI, literal value, etc.)
            term_type: Term type ('U'=URI, 'L'=Literal, 'B'=BlankNode, 'G'=Graph)
            lang: Language tag for literals
            datatype_id: Reference to datatype term ID
            
        Returns:
            Term identifier if successful, None otherwise
        """
        pass
    
    @abstractmethod
    async def get_term_uuid(self, space_id: str, term_text: str, term_type: str, 
                           lang: Optional[str] = None, datatype_id: Optional[int] = None) -> Optional[str]:
        """
        Get term identifier for existing term in a specific space.
        
        Args:
            space_id: Space identifier
            term_text: The term text
            term_type: Term type
            lang: Language tag
            datatype_id: Datatype term ID
            
        Returns:
            Term identifier if found, None otherwise
        """
        pass
    
    @abstractmethod
    async def get_term_uuid_from_rdf_value(self, space_id: str, rdf_value) -> Optional[str]:
        """
        Get term identifier for existing term from an RDF value.
        
        Args:
            space_id: Space identifier
            rdf_value: RDF value (URI, literal, or blank node)
            
        Returns:
            Term identifier if found, None otherwise
        """
        pass
    
    @abstractmethod
    async def delete_term(self, space_id: str, term_text: str, term_type: str, 
                         lang: Optional[str] = None, datatype_id: Optional[int] = None) -> bool:
        """
        Delete a term from a specific space.
        
        Args:
            space_id: Space identifier
            term_text: The term text
            term_type: Term type
            lang: Language tag
            datatype_id: Datatype term ID
            
        Returns:
            True if term was deleted, False otherwise
        """
        pass
    
    # ========================================
    # Quad Operations (Low-level)
    # ========================================
    
    @abstractmethod
    async def add_quad(self, space_id: str, subject_uuid: str, predicate_uuid: str, 
                      object_uuid: str, context_uuid: str) -> bool:
        """
        Add an RDF quad using term identifiers.
        
        Args:
            space_id: Space identifier
            subject_uuid: Subject term identifier
            predicate_uuid: Predicate term identifier
            object_uuid: Object term identifier
            context_uuid: Context (graph) term identifier
            
        Returns:
            True if successful, False otherwise
        """
        pass
    
    @abstractmethod
    async def remove_quad(self, space_id: str, subject_uuid: str, predicate_uuid: str, 
                         object_uuid: str, context_uuid: str) -> bool:
        """
        Remove an RDF quad using term identifiers.
        
        Args:
            space_id: Space identifier
            subject_uuid: Subject term identifier
            predicate_uuid: Predicate term identifier
            object_uuid: Object term identifier
            context_uuid: Context (graph) term identifier
            
        Returns:
            True if a quad was removed, False if no matching quad found
        """
        pass
    
    @abstractmethod
    async def get_quad_count(self, space_id: str, context_uuid: Optional[str] = None) -> int:
        """
        Get count of quads in a specific space, optionally filtered by context.
        
        Args:
            space_id: Space identifier
            context_uuid: Optional context identifier to filter by
            
        Returns:
            Number of quads
        """
        pass
    
    # ========================================
    # RDF Operations (High-level)
    # ========================================
    
    @abstractmethod
    async def add_rdf_quad(self, space_id: str, quad: Union[tuple, list]) -> bool:
        """
        Add an RDF quad using RDF values.
        
        Args:
            space_id: Space identifier
            quad: Tuple/list of (subject, predicate, object, context) RDF values
            
        Returns:
            True if successful, False otherwise
        """
        pass
    
    @abstractmethod
    async def remove_rdf_quad(self, space_id: str, s: str, p: str, o: str, g: str) -> bool:
        """
        Remove an RDF quad using RDF values.
        
        Args:
            space_id: Space identifier
            s: Subject value
            p: Predicate value
            o: Object value
            g: Graph/context value
            
        Returns:
            True if successful, False otherwise
        """
        pass
    
    @abstractmethod
    async def get_rdf_quad(self, space_id: str, s: str, p: str, o: str, g: str) -> bool:
        """
        Check if an RDF quad exists using RDF values.
        
        Args:
            space_id: Space identifier
            s: Subject value
            p: Predicate value
            o: Object value
            g: Graph/context value
            
        Returns:
            True if the quad exists, False otherwise
        """
        pass
    
    @abstractmethod
    async def get_rdf_quad_count(self, space_id: str, graph_uri: Optional[str] = None) -> int:
        """
        Get count of RDF quads, optionally filtered by graph URI.
        
        Args:
            space_id: Space identifier
            graph_uri: Optional graph URI to filter by
            
        Returns:
            Number of quads
        """
        pass
    
    @abstractmethod
    async def add_rdf_quads_batch(self, space_id: str, quads: List[Tuple[Identifier, Identifier, Identifier, Identifier]], 
                                 auto_commit: bool = True, verify_count: bool = False, connection=None) -> int:
        """
        Batch RDF quad insertion for performance.
        
        Args:
            space_id: Space identifier
            quads: List of (subject, predicate, object, context) tuples
            auto_commit: Whether to commit the transaction automatically
            verify_count: Whether to verify insertion with COUNT query
            connection: Optional connection to use
            
        Returns:
            Number of quads successfully inserted
        """
        pass
    
    @abstractmethod
    async def remove_rdf_quads_batch(self, space_id: str, quads: List[tuple]) -> int:
        """
        Batch RDF quad removal for performance.
        
        Args:
            space_id: Space identifier
            quads: List of (s, p, o, g) tuples representing RDF quads to remove
            
        Returns:
            Number of quads successfully removed
        """
        pass
    
    # ========================================
    # Quad Pattern Matching (SPARQL Support)
    # ========================================
    
    @abstractmethod
    async def quads(self, space_id: str, quad_pattern: tuple, context: Optional[Any] = None):
        """
        Generator over all quads matching the pattern.
        
        Pattern can include any objects for comparing against nodes in the store,
        including URIRef, Literal, BNode, Variable, and REGEXTerm for regex matching.
        
        Args:
            space_id: Space identifier
            quad_pattern: 4-tuple of (subject, predicate, object, context) patterns
            context: Optional context (not used in current implementation)
            
        Yields:
            tuple: (quad, context_iterator) where quad is (s, p, o, c)
        """
        pass
    
    # ========================================
    # Namespace Management
    # ========================================
    
    @abstractmethod
    async def add_namespace(self, space_id: str, prefix: str, namespace_uri: str) -> Optional[int]:
        """
        Add a namespace prefix mapping to a specific space.
        
        Args:
            space_id: Space identifier
            prefix: Namespace prefix (e.g., 'foaf', 'rdf')
            namespace_uri: Full namespace URI
            
        Returns:
            Namespace ID if successful, None otherwise
        """
        pass
    
    @abstractmethod
    async def get_namespace_uri(self, space_id: str, prefix: str) -> Optional[str]:
        """
        Get namespace URI for a given prefix in a specific space.
        
        Args:
            space_id: Space identifier
            prefix: Namespace prefix to look up
            
        Returns:
            Namespace URI if found, None otherwise
        """
        pass
    
    @abstractmethod
    async def list_namespaces(self, space_id: str) -> List[Dict[str, Any]]:
        """
        Get all namespace prefix mappings for a specific space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            List of namespace dictionaries
        """
        pass
    
    # ========================================
    # Datatype Management
    # ========================================
    
    @abstractmethod
    async def get_or_create_datatype_id(self, space_id: str, datatype_uri: str) -> int:
        """
        Get or create a datatype ID for the given URI.
        
        Args:
            space_id: Space identifier
            datatype_uri: Datatype URI (e.g., xsd:string)
            
        Returns:
            Datatype ID
        """
        pass
    
    # ========================================
    # SPARQL Support
    # ========================================
    
    @abstractmethod
    def get_sparql_impl(self, space_id: str) -> SparqlBackendInterface:
        """
        Get backend-specific SPARQL implementation for the given space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            SparqlBackendInterface implementation instance
        """
        pass
    
    # ========================================
    # Utility Methods
    # ========================================
    
    @abstractmethod
    def get_manager_info(self) -> Dict[str, Any]:
        """
        Get general information about this space manager.
        
        Returns:
            Dictionary containing manager metadata
        """
        pass
    
    @abstractmethod
    def get_pool_stats(self) -> Dict[str, Any]:
        """
        Get connection pool statistics.
        
        Returns:
            Dictionary containing pool statistics
        """
        pass
    
    # ========================================
    # Bulk Operations Support
    # ========================================
    
    @abstractmethod
    async def drop_indexes_for_bulk_load(self, space_id: str) -> bool:
        """
        Drop indexes before bulk loading for maximum performance.
        
        Args:
            space_id: Space identifier
            
        Returns:
            True if indexes dropped successfully, False otherwise
        """
        pass
    
    @abstractmethod
    async def recreate_indexes_after_bulk_load(self, space_id: str, concurrent: bool = True) -> bool:
        """
        Recreate indexes after bulk loading is complete.
        
        Args:
            space_id: Space identifier
            concurrent: If True, use non-blocking index creation
            
        Returns:
            True if indexes recreated successfully, False otherwise
        """
        pass


class SignalManagerInterface(ABC):
    """
    Abstract interface for backend-specific signal management.
    
    This interface abstracts the existing SignalManager in /vitalgraph/signal/
    to support different backend notification mechanisms:
    - PostgreSQL: NOTIFY/LISTEN (existing implementation)
    - Oxigraph: In-memory events (non-operational initially)
    - Fuseki: HTTP webhooks or polling
    - Mock: In-memory event simulation
    
    Different backends may have different mechanisms for notifying
    about space events and data changes.
    """
    
    @abstractmethod
    async def notify_space_created(self, space_id: str) -> None:
        """
        Notify that a space was created.
        
        Args:
            space_id: Space identifier
        """
        pass
    
    @abstractmethod
    async def notify_space_deleted(self, space_id: str) -> None:
        """
        Notify that a space was deleted.
        
        Args:
            space_id: Space identifier
        """
        pass
    
    @abstractmethod
    async def notify_space_updated(self, space_id: str, update_type: str, metadata: Dict[str, Any] = None) -> None:
        """
        Notify that a space was updated.
        
        Args:
            space_id: Space identifier
            update_type: Type of update (e.g., 'quad_added', 'namespace_added')
            metadata: Optional metadata about the update
        """
        pass
    
    @abstractmethod
    async def subscribe_to_space_events(self, callback, space_id: Optional[str] = None) -> None:
        """
        Subscribe to space events.
        
        Args:
            callback: Function to call when events occur
            space_id: Optional space ID to filter events, None for all spaces
        """
        pass
    
    @abstractmethod
    async def unsubscribe_from_space_events(self, callback) -> None:
        """
        Unsubscribe from space events.
        
        Args:
            callback: Function to remove from event notifications
        """
        pass
    
    @abstractmethod
    def close(self) -> None:
        """
        Close signal manager and clean up resources.
        """
        pass


# ========================================
# Backend Configuration Support
# ========================================

from enum import Enum
from dataclasses import dataclass


class BackendType(Enum):
    """Supported backend types."""
    POSTGRESQL = "postgresql"
    OXIGRAPH = "oxigraph" 
    FUSEKI = "fuseki"
    MOCK = "mock"


@dataclass
class BackendConfig:
    """Configuration for a space backend."""
    backend_type: BackendType
    connection_params: Dict[str, Any]
    pool_config: Optional[Dict[str, Any]] = None
    signal_manager_config: Optional[Dict[str, Any]] = None


class BackendFactory:
    """Factory for creating space backend implementations."""
    
    @staticmethod
    def create_backend(config: BackendConfig) -> SpaceBackendInterface:
        """
        Create a space backend implementation based on configuration.
        
        Args:
            config: Backend configuration
            
        Returns:
            Space backend implementation instance
            
        Raises:
            ValueError: If backend type is not supported
            ImportError: If required backend dependencies are not available
        """
        if config.backend_type == BackendType.POSTGRESQL:
            try:
                from .postgresql.postgresql_space_impl import PostgreSQLSpaceImpl
                return PostgreSQLSpaceImpl(**config.connection_params)
            except ImportError as e:
                raise ImportError(f"PostgreSQL backend dependencies not available: {e}")
                
        elif config.backend_type == BackendType.OXIGRAPH:
            try:
                from .oxigraph.oxigraph_space_impl import OxigraphSpaceImpl
                return OxigraphSpaceImpl(**config.connection_params)
            except ImportError as e:
                raise ImportError(f"Oxigraph backend dependencies not available: {e}")
                
        elif config.backend_type == BackendType.FUSEKI:
            try:
                from .fuseki.fuseki_space_impl import FusekiSpaceImpl
                return FusekiSpaceImpl(**config.connection_params)
            except ImportError as e:
                raise ImportError(f"Fuseki backend dependencies not available: {e}")
                
        elif config.backend_type == BackendType.MOCK:
            try:
                from ..mock.client.space.mock_space_impl import MockSpaceImpl
                return MockSpaceImpl(**config.connection_params)
            except ImportError as e:
                raise ImportError(f"Mock backend dependencies not available: {e}")
                
        else:
            raise ValueError(f"Unsupported backend type: {config.backend_type}")
    
    @staticmethod
    def create_signal_manager(config: BackendConfig) -> SignalManagerInterface:
        """
        Create a signal manager implementation based on configuration.
        
        Args:
            config: Backend configuration
            
        Returns:
            Signal manager implementation instance
            
        Raises:
            ValueError: If backend type is not supported
            ImportError: If required backend dependencies are not available
        """
        signal_config = config.signal_manager_config or {}
        
        if config.backend_type == BackendType.POSTGRESQL:
            try:
                from .postgresql.postgresql_signal_manager import PostgreSQLSignalManager
                return PostgreSQLSignalManager(**signal_config)
            except ImportError as e:
                raise ImportError(f"PostgreSQL signal manager dependencies not available: {e}")
                
        elif config.backend_type == BackendType.OXIGRAPH:
            try:
                from .oxigraph.oxigraph_signal_manager import OxigraphSignalManager
                return OxigraphSignalManager(**signal_config)
            except ImportError as e:
                raise ImportError(f"Oxigraph signal manager dependencies not available: {e}")
                
        elif config.backend_type == BackendType.FUSEKI:
            try:
                from .fuseki.fuseki_signal_manager import FusekiSignalManager
                return FusekiSignalManager(**signal_config)
            except ImportError as e:
                raise ImportError(f"Fuseki signal manager dependencies not available: {e}")
                
        elif config.backend_type == BackendType.MOCK:
            try:
                from ..mock.client.signal.mock_signal_manager import MockSignalManager
                return MockSignalManager(**signal_config)
            except ImportError as e:
                raise ImportError(f"Mock signal manager dependencies not available: {e}")
                
        else:
            raise ValueError(f"Unsupported backend type: {config.backend_type}")
