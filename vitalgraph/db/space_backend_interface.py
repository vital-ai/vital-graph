"""
Abstract interface for space backend implementations.

This module defines the SpaceBackendInterface that all backend implementations
(PostgreSQL, Fuseki, Oxigraph, Mock) must implement. This ensures consistent
API across different storage backends while allowing backend-specific optimizations.
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Union, Tuple, AsyncGenerator
from contextlib import asynccontextmanager

# RDFLib imports for term handling
from rdflib import URIRef, Literal, BNode, Variable
from rdflib.term import Identifier


class SpaceBackendInterface(ABC):
    """
    Abstract interface for space backend implementations.
    
    This interface defines all methods that space backend implementations
    must provide for RDF graph space management, including:
    - Space lifecycle management (create, delete, exists)
    - RDF quad operations (add, remove, query, count)
    - Term management (add, get, delete)
    - Namespace management (add, get, list)
    - Connection and resource management
    """
    
    # ========================================
    # Connection and Resource Management
    # ========================================
    
    @abstractmethod
    def close(self) -> None:
        """Close backend connections and clean up resources."""
        pass
    
    @abstractmethod
    @asynccontextmanager
    async def get_db_connection(self):
        """
        Async context manager for automatic connection management.
        
        Yields:
            Connection object appropriate for the backend
        """
        pass
    
    # ========================================
    # Space Lifecycle Management
    # ========================================
    
    @abstractmethod
    async def create_space_storage(self, space_id: str) -> bool:
        """
        Create storage structures for a new space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            bool: True if successful, False otherwise
        """
        pass
    
    @abstractmethod
    async def delete_space_storage(self, space_id: str) -> bool:
        """
        Delete all storage structures for a space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            bool: True if successful, False otherwise
        """
        pass
    
    @abstractmethod
    async def space_exists(self, space_id: str) -> bool:
        """
        Check if a space exists in the backend.
        
        Args:
            space_id: Space identifier
            
        Returns:
            bool: True if space exists, False otherwise
        """
        pass
    
    @abstractmethod
    async def list_spaces(self) -> List[str]:
        """
        List all spaces in the backend.
        
        Returns:
            List[str]: List of space identifiers
        """
        pass
    
    @abstractmethod
    async def get_space_info(self, space_id: str) -> Dict[str, Any]:
        """
        Get information about a specific space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            Dict[str, Any]: Space information
        """
        pass
    
    # ========================================
    # RDF Quad Operations
    # ========================================
    
    @abstractmethod
    async def add_rdf_quad(self, space_id: str, quad: Union[tuple, list]) -> bool:
        """
        Add an RDF quad to a space.
        
        Args:
            space_id: Space identifier
            quad: RDF quad as (subject, predicate, object, graph) tuple
            
        Returns:
            bool: True if successful, False otherwise
        """
        pass
    
    @abstractmethod
    async def remove_rdf_quad(self, space_id: str, s: str, p: str, o: str, g: str) -> bool:
        """
        Remove an RDF quad from a space.
        
        Args:
            space_id: Space identifier
            s: Subject value
            p: Predicate value
            o: Object value
            g: Graph/context value
            
        Returns:
            bool: True if successful, False otherwise
        """
        pass
    
    @abstractmethod
    async def get_rdf_quad(self, space_id: str, s: str, p: str, o: str, g: str) -> bool:
        """
        Check if an RDF quad exists in a space.
        
        Args:
            space_id: Space identifier
            s: Subject value
            p: Predicate value
            o: Object value
            g: Graph/context value
            
        Returns:
            bool: True if quad exists, False otherwise
        """
        pass
    
    @abstractmethod
    async def get_rdf_quad_count(self, space_id: str, graph_uri: Optional[str] = None) -> int:
        """
        Get count of RDF quads in a space.
        
        Args:
            space_id: Space identifier
            graph_uri: Optional graph URI to filter by
            
        Returns:
            int: Number of quads
        """
        pass
    
    @abstractmethod
    async def add_rdf_quads_batch(self, space_id: str, quads: List[Tuple[Identifier, Identifier, Identifier, Identifier]], 
                                 auto_commit: bool = True, verify_count: bool = False, connection=None) -> int:
        """
        Add multiple RDF quads to a space in a batch operation.
        
        Args:
            space_id: Space identifier
            quads: List of RDF quads as (subject, predicate, object, graph) tuples
            auto_commit: Whether to commit automatically
            verify_count: Whether to verify insertion count
            connection: Optional connection to use
            
        Returns:
            int: Number of quads successfully inserted
        """
        pass
    
    @abstractmethod
    async def remove_rdf_quads_batch(self, space_id: str, quads: List[tuple]) -> int:
        """
        Remove multiple RDF quads from a space in a batch operation.
        
        Args:
            space_id: Space identifier
            quads: List of RDF quads to remove
            
        Returns:
            int: Number of quads successfully removed
        """
        pass
    
    @abstractmethod
    async def quads(self, space_id: str, quad_pattern: tuple, context: Optional[Any] = None):
        """
        Generator over all quads matching the pattern.
        
        Args:
            space_id: Space identifier
            quad_pattern: 4-tuple pattern (subject, predicate, object, context)
            context: Optional context
            
        Yields:
            tuple: Matching quads
        """
        pass
    
    # ========================================
    # Term Management
    # ========================================
    
    @abstractmethod
    async def add_term(self, space_id: str, term_text: str, term_type: str, 
                      lang: Optional[str] = None, datatype_id: Optional[int] = None) -> Optional[str]:
        """
        Add a term to the space.
        
        Args:
            space_id: Space identifier
            term_text: Term text
            term_type: Term type ('U'=URI, 'L'=Literal, 'B'=BlankNode)
            lang: Language tag for literals
            datatype_id: Datatype identifier
            
        Returns:
            Optional[str]: Term identifier if successful
        """
        pass
    
    @abstractmethod
    async def get_term_uuid(self, space_id: str, term_text: str, term_type: str, 
                           lang: Optional[str] = None, datatype_id: Optional[int] = None) -> Optional[str]:
        """
        Get term identifier for existing term.
        
        Args:
            space_id: Space identifier
            term_text: Term text
            term_type: Term type
            lang: Language tag
            datatype_id: Datatype identifier
            
        Returns:
            Optional[str]: Term identifier if found
        """
        pass
    
    
    @abstractmethod
    async def delete_term(self, space_id: str, term_text: str, term_type: str, 
                         lang: Optional[str] = None, datatype_id: Optional[int] = None) -> bool:
        """
        Delete a term from the space.
        
        Args:
            space_id: Space identifier
            term_text: Term text
            term_type: Term type
            lang: Language tag
            datatype_id: Datatype identifier
            
        Returns:
            bool: True if successful, False otherwise
        """
        pass
    
    # ========================================
    # Namespace Management
    # ========================================
    
    @abstractmethod
    async def add_namespace(self, space_id: str, prefix: str, namespace_uri: str) -> Optional[int]:
        """
        Add a namespace prefix mapping to a space.
        
        Args:
            space_id: Space identifier
            prefix: Namespace prefix
            namespace_uri: Full namespace URI
            
        Returns:
            Optional[int]: Namespace ID if successful
        """
        pass
    
    @abstractmethod
    async def get_namespace_uri(self, space_id: str, prefix: str) -> Optional[str]:
        """
        Get namespace URI for a prefix.
        
        Args:
            space_id: Space identifier
            prefix: Namespace prefix
            
        Returns:
            Optional[str]: Namespace URI if found
        """
        pass
    
    @abstractmethod
    async def list_namespaces(self, space_id: str) -> List[Dict[str, Any]]:
        """
        List all namespace mappings for a space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            List[Dict[str, Any]]: List of namespace mappings
        """
        pass
    
    # ========================================
    # SPARQL Integration
    # ========================================
    
    @abstractmethod
    def get_sparql_impl(self, space_id: str):
        """
        Get SPARQL implementation for a space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            SPARQL implementation instance
        """
        pass
    
    # ========================================
    # Utility Methods
    # ========================================
    
    @abstractmethod
    def get_manager_info(self) -> Dict[str, Any]:
        """
        Get information about the backend manager.
        
        Returns:
            Dict[str, Any]: Manager information
        """
        pass
    
    # ========================================
    # Optional Performance Methods
    # ========================================
    
    async def drop_indexes_for_bulk_load(self, space_id: str) -> bool:
        """
        Drop indexes before bulk loading (optional optimization).
        
        Args:
            space_id: Space identifier
            
        Returns:
            bool: True if successful, False otherwise
        """
        return True  # Default no-op implementation
    
    async def recreate_indexes_after_bulk_load(self, space_id: str, concurrent: bool = True) -> bool:
        """
        Recreate indexes after bulk loading (optional optimization).
        
        Args:
            space_id: Space identifier
            concurrent: Use concurrent index creation
            
        Returns:
            bool: True if successful, False otherwise
        """
        return True  # Default no-op implementation


class SparqlBackendInterface(ABC):
    """
    Abstract interface for SPARQL backend implementations.
    
    This interface defines methods for SPARQL query execution
    that backends must implement.
    """
    
    @abstractmethod
    async def execute_sparql_query(self, space_id: str, query: str, **kwargs) -> Dict[str, Any]:
        """
        Execute a SPARQL query against a space.
        
        Args:
            space_id: Space identifier
            query: SPARQL query string
            **kwargs: Additional query parameters
            
        Returns:
            Dict[str, Any]: Query results
        """
        pass
    
    @abstractmethod
    async def execute_sparql_update(self, space_id: str, update: str, **kwargs) -> bool:
        """
        Execute a SPARQL update against a space.
        
        Args:
            space_id: Space identifier
            update: SPARQL update string
            **kwargs: Additional update parameters
            
        Returns:
            bool: True if successful, False otherwise
        """
        pass
