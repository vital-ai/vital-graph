import logging
import asyncio
import re
import csv
import io
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any, Union, Tuple, AsyncGenerator, Set
from contextlib import asynccontextmanager
import psycopg
from psycopg import sql
from psycopg.rows import dict_row

# RDFLib imports for term handling
from rdflib import URIRef, Literal, BNode, Variable
from rdflib.term import Identifier

# Import PostgreSQL utilities
from .postgresql_log_utils import PostgreSQLLogUtils
from .space.postgresql_space_utils import PostgreSQLSpaceUtils
from .original.postgresql_utils import PostgreSQLUtils
from .postgresql_cache_term import PostgreSQLCacheTerm
from .postgresql_cache_graph import PostgreSQLCacheGraph
from .space.postgresql_space_core import PostgreSQLSpaceCore
from .space.postgresql_space_schema import PostgreSQLSpaceSchema
from .space.postgresql_space_db_mgmt import PostgreSQLSpaceDbMgmt
from .space.postgresql_space_namespaces import PostgreSQLSpaceNamespaces
from .space.postgresql_space_datatypes import PostgreSQLSpaceDatatypes
from .space.postgresql_space_terms import PostgreSQLSpaceTerms
from .space.postgresql_space_queries import PostgreSQLSpaceQueries
from .space.postgresql_space_db_ops import PostgreSQLSpaceDBOps
from .space.postgresql_space_graphs import PostgreSQLSpaceGraphs

class PostgreSQLSpaceImpl:
    """
    PostgreSQL implementation for RDF graph space management.
    
    Manages all RDF spaces and their associated tables:
    - namespace: RDF namespace prefix mappings per space
    - graph: Graph (context) URIs and metadata per space
    - rdf_quad: RDF quads with term references per space
    - term: Terms dictionary with types and metadata per space
    
    Table names are prefixed with global_prefix__space_id__ format.
    """
    
    def __init__(self, connection_string: str, global_prefix: str = "vitalgraph", use_unlogged: bool = True, pool_config: Optional[Dict[str, Any]] = None, shared_pool=None):
        """
        Initialize PostgreSQL space implementation with shared or dedicated psycopg3 ConnectionPool.
        
        Args:
            connection_string: PostgreSQL connection string
            global_prefix: Global prefix for table names
            use_unlogged: Whether to use unlogged tables for better performance
            pool_config: Optional connection pool configuration
            shared_pool: Optional shared psycopg3 ConnectionPool instance
        """
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Initialize core connection management
        self.core = PostgreSQLSpaceCore(
            connection_string=connection_string,
            global_prefix=global_prefix,
            pool_config=pool_config,
            shared_pool=shared_pool
        )
        
        # Keep these attributes for backward compatibility and space-specific functionality
        self.connection_string = connection_string
        self.global_prefix = global_prefix
        self.use_unlogged = use_unlogged
        
        # Initialize utils instance for timing operations and table name generation
        self.utils = PostgreSQLUtils()
        
        # Validate global prefix using utils
        PostgreSQLSpaceUtils.validate_global_prefix(global_prefix)
        
        # Initialize database management class
        self.db_mgmt = PostgreSQLSpaceDbMgmt(self)
        
        # Initialize namespace management class
        self.namespaces = PostgreSQLSpaceNamespaces(self)
        
        # Initialize datatype management class
        self.datatypes = PostgreSQLSpaceDatatypes(self)
        
        # Initialize term management class
        self.terms = PostgreSQLSpaceTerms(self)
        
        # Initialize query management class
        self.queries = PostgreSQLSpaceQueries(self)
        
        # Initialize database operations class
        self.db_ops = PostgreSQLSpaceDBOps(self)
        
        # Initialize graph management class
        self.graphs = PostgreSQLSpaceGraphs(self)
        
        # Cache of schema instances by space_id
        self._schema_cache = {}
        
        # Cache of SPARQL implementations by space_id to persist term caches across requests
        self._sparql_impl_cache = {}
        
        # Cache of datatype caches by space_id - each space has its own datatype cache
        self._datatype_caches = {}
        
        # Cache of graph caches by space_id - each space has its own graph cache
        self._graph_caches = {}
        
        # Global term cache for all spaces (shared for performance)
        self._term_cache = PostgreSQLCacheTerm()
        
        # Flag to track if datatype cache has been loaded
        self._datatype_cache_loaded = False
    
    def _get_schema(self, space_id: str) -> PostgreSQLSpaceSchema:
        """
        Get or create a schema instance for the specified space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            PostgreSQLSpaceSchema: Schema instance for the space
        """
        if space_id not in self._schema_cache:
            self._schema_cache[space_id] = PostgreSQLSpaceSchema(
                global_prefix=self.global_prefix,
                space_id=space_id,
                use_unlogged=self.use_unlogged
            )
        return self._schema_cache[space_id]
    
    def get_term_cache(self):
        """
        Get the term cache for this PostgreSQL space implementation.
        
        Returns:
            PostgreSQLCacheTerm: The term cache instance
        """
        return self._term_cache
    
    def get_manager_info(self) -> Dict[str, Any]:
        """
        Get general information about this space manager.
        
        Returns:
            dict: Manager information
        """
        return self.core.get_manager_info(self)

    def get_datatype_cache(self, space_id: str) -> 'PostgreSQLCacheDatatype':
        """
        Get the datatype cache for a specific space, creating it if necessary.
        Each space has its own datatype cache that is initialized when the space is created.
        
        Args:
            space_id: Space identifier
            
        Returns:
            PostgreSQLCacheDatatype: The datatype cache for the specified space
        """
        return self.datatypes.get_datatype_cache(space_id)
    
    def get_graph_cache(self, space_id: str) -> 'PostgreSQLCacheGraph':
        """
        Get the graph cache for a specific space, creating it if necessary.
        Each space has its own graph cache for tracking graph existence.
        The cache is automatically initialized with all existing graphs from the database.
        
        Args:
            space_id: Space identifier
            
        Returns:
            PostgreSQLCacheGraph: The graph cache for the specified space
        """
        if space_id not in self._graph_caches:
            # Create new cache (will be lazily initialized on first async access)
            cache = PostgreSQLCacheGraph()
            self.logger.info(f"Created graph cache for space '{space_id}' (will be initialized on first access)")
            
            self._graph_caches[space_id] = cache
            
        return self._graph_caches[space_id]
    
    def close(self):
        """
        Close the RDF connection pool and clean up resources.
        """
        self.core.close()
    
    def __del__(self):
        """
        Destructor to ensure pool is closed when object is garbage collected.
        """
        try:
            self.close()
        except Exception:
            pass  # Ignore errors during cleanup
    
    
    def get_connection(self):
        """
        Get a database connection. 
        
        WARNING: This method is deprecated for pooled connections.
        Use get_db_connection() context manager instead to ensure proper connection lifecycle.
        
        Returns:
            psycopg.Connection: Database connection (direct connection only)
        """
        return self.core.get_connection()
    
    def return_connection(self, conn) -> None:
        """
        Return a connection to the shared psycopg3 pool or close it if direct connection.
        
        Args:
            conn: Database connection to return
        """
        return self.core.return_connection(conn)
    
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
        async with self.core.get_db_connection() as conn:
            yield conn
    
    def _resolve_term_info(self, term: Identifier) -> Tuple[str, str, Optional[str], Optional[int]]:
        """
        Resolve an RDF term to its database representation.
        
        Args:
            term: RDFLib term (URIRef, Literal, BNode)
            
        Returns:
            tuple: (term_text, term_type, lang, datatype_id)
        """
        return self.terms._resolve_term_info(term)
    
    def _get_table_names(self, space_id: str) -> Dict[str, str]:
        """
        Get all RDF space table names for a specific space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            dict: Dictionary of table names keyed by base name
        """
        schema = self._get_schema(space_id)
        return schema.get_table_names()
    
    def get_sparql_impl(self, space_id: str):
        """
        Get or create a cached SPARQL implementation for the given space.
        
        This ensures that the SPARQL implementation and its term cache persist
        across multiple requests, providing significant performance benefits.
        
        Args:
            space_id: Space identifier
            
        Returns:
            PostgreSQLSparqlImpl: Cached SPARQL implementation instance
        """
        if space_id not in self._sparql_impl_cache:
            # Import here to avoid circular imports
            from .postgresql_sparql_impl import PostgreSQLSparqlImpl
            
            self.logger.info(f" Creating new cached SPARQL implementation for space: {space_id}")
            self._sparql_impl_cache[space_id] = PostgreSQLSparqlImpl(self)
        else:
            self.logger.debug(f" Reusing cached SPARQL implementation for space: {space_id}")
            
        return self._sparql_impl_cache[space_id]
    
    def _get_create_table_sql(self, space_id: str) -> Dict[str, str]:
        """
        Generate CREATE TABLE SQL statements for UUID-based RDF space tables.
        
        This creates tables optimized for UUID-based term identification:
        - Uses UUID primary keys instead of BIGSERIAL
        - Eliminates foreign key constraints for better performance
        - Optimized for deterministic UUID-based batch loading
        
        Args:
            space_id: Space identifier
            
        Returns:
            dict: Dictionary of CREATE TABLE SQL statements
        """
        schema = self._get_schema(space_id)
        return schema.get_create_table_sql()
    
    def _get_standard_datatypes(self) -> List[Tuple[str, str]]:
        """
        Get list of standard XSD and RDF datatype URIs to insert into datatype table.
        
        Returns:
            List of (datatype_uri, datatype_name) tuples
        """
        return self.datatypes.get_standard_datatypes()
    
    def _insert_standard_datatypes(self, space_id: str) -> bool:
        """
        Insert standard datatype URIs into the datatype table for a space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            bool: True if successful, False otherwise
        """
        return self.datatypes.insert_standard_datatypes(space_id)
    
    def _ensure_text_search_extensions(self) -> bool:
        """
        Ensure that required PostgreSQL extensions for text search are enabled.
        This includes pg_trgm for trigram-based regex matching.
        
        Returns:
            bool: True if extensions are available, False otherwise
        """
        return self.core._ensure_text_search_extensions()
    
    async def _ensure_datatype_cache_loaded(self, space_id: str) -> None:
        """
        Ensure datatype cache is loaded for a specific space.
        This method loads datatypes from the database into the shared cache if not already loaded.
        
        Args:
            space_id: Space identifier
        """
        return await self.datatypes.ensure_datatype_cache_loaded(space_id)
    
    async def _load_all_datatypes_into_cache(self) -> None:
        """
        Load all datatypes from all spaces into the shared datatype cache.
        This is more efficient than loading per-space since datatypes are shared.
        """
        return await self.datatypes.load_all_datatypes_into_cache()
    
    async def load_datatype_cache(self, space_id: str) -> 'PostgreSQLCacheDatatype':
        """
        Get the datatype cache for a specific space.
        This method ensures the cache is loaded and returns the shared instance.
        
        Args:
            space_id: Space identifier
            
        Returns:
            PostgreSQLCacheDatatype instance populated with datatypes
        """
        return await self.datatypes.load_datatype_cache(space_id)
    
    async def get_or_create_datatype_id(self, space_id: str, datatype_uri: str) -> int:
        """
        Get or create a datatype ID for the given URI.
        This method first checks the cache, then the database, and creates a new entry if needed.
        
        Args:
            space_id: Space identifier
            datatype_uri: The datatype URI to resolve
            
        Returns:
            The datatype ID (BIGINT)
        """
        return await self.datatypes.get_or_create_datatype_id(space_id, datatype_uri)
    
    async def _resolve_datatype_ids_batch(self, space_id: str, datatype_uris: set) -> Dict[str, int]:
        """
        Resolve datatype URIs to IDs, inserting unknown datatypes as needed.
        
        Args:
            space_id: Space identifier for the datatype table
            datatype_uris: Set of datatype URIs to resolve
            
        Returns:
            Dictionary mapping datatype URIs to their BIGINT IDs
        """
        return await self.datatypes.resolve_datatype_ids_batch(space_id, datatype_uris)
    
    async def _process_term_with_datatype(self, space_id: str, term_value: str, term_type: str, lang: Optional[str], datatype_uri: Optional[str]) -> Tuple[str, str, Optional[str], Optional[int]]:
        """
        Helper method to process a term and resolve its datatype ID using the space-specific cache.
        
        Args:
            space_id: Space identifier for the datatype cache
            term_value: The term value/text
            term_type: The term type ('uri', 'literal', 'blank')
            lang: Language tag for literals (optional)
            datatype_uri: Datatype URI for literals (optional)
            
        Returns:
            Tuple of (term_value, term_type, lang, datatype_id)
        """
        return await self.terms._process_term_with_datatype(space_id, term_value, term_type, lang, datatype_uri)

    def _initialize_space_datatype_cache_sync(self, space_id: str) -> None:
        """
        Initialize the datatype cache for a specific space by loading standard datatypes
        and any existing datatypes from the database (synchronous version).
        
        Args:
            space_id: Space identifier
        """
        return self.datatypes.initialize_space_datatype_cache_sync(space_id)

    async def add_rdf_quad(self, space_id: str, quad: Union[tuple, list]) -> bool:
        """
        Add an RDF quad to a specific space with proper datatype handling.
        
        This method uses the new datatype cache system to properly resolve and store
        datatype IDs for all literal terms in the quad.
        
        Args:
            space_id: Space identifier
            quad: Tuple of (subject, predicate, object, graph) RDF values
            
        Returns:
            bool: True if successful, False otherwise
        """
        return await self.db_ops.add_rdf_quad(space_id, quad)
    
    async def remove_rdf_quad(self, space_id: str, s: str, p: str, o: str, g: str) -> bool:
        """
        Remove an RDF quad from a specific space with proper datatype handling.
        
        This method uses the new datatype cache system to properly resolve datatypes
        when looking up terms for removal.
        
        Args:
            space_id: Space identifier
            s: Subject value (URI, literal, or blank node)
            p: Predicate value (typically URI)
            o: Object value (URI, literal, or blank node)
            g: Graph value (URI, literal, or blank node)
            
        Returns:
            bool: True if successful, False otherwise
        """
        return await self.db_ops.remove_rdf_quad(space_id, s, p, o, g)
    
    def create_space_tables(self, space_id: str) -> bool:
        """
        Create UUID-based RDF tables optimized for deterministic batch loading.
        
        Args:
            space_id: Space identifier
            
        Returns:
            bool: True if tables created successfully, False otherwise
        """
        PostgreSQLSpaceUtils.validate_space_id(space_id)
        
        # Delegate table creation to database management class
        success = self.db_mgmt.create_space_tables(space_id)
        
        if success:
            # Insert standard datatypes after table creation
            if not self._insert_standard_datatypes(space_id):
                self.logger.warning(f"⚠️ Failed to insert standard datatypes for '{space_id}', but tables were created")
            
            # Initialize datatype cache for this space (synchronous)
            self._initialize_space_datatype_cache_sync(space_id)
        
        return success
    
    def drop_indexes_for_bulk_load(self, space_id: str) -> bool:
        """
        Drop all indexes before bulk loading for maximum performance.
        Keeps only primary keys and constraints.
        
        Args:
            space_id: Space identifier
            
        Returns:
            bool: True if indexes dropped successfully, False otherwise
        """
        # Delegate to database management class
        return self.db_mgmt.drop_indexes_for_bulk_load(space_id)
    
    def recreate_indexes_after_bulk_load(self, space_id: str, concurrent: bool = True) -> bool:
        """
        Recreate all indexes after bulk loading is complete.
        
        Args:
            space_id: Space identifier
            concurrent: If True, use CONCURRENTLY to avoid blocking queries
            
        Returns:
            bool: True if indexes recreated successfully, False otherwise
        """
        # Delegate to database management class
        return self.db_mgmt.recreate_indexes_after_bulk_load(space_id, concurrent)
    
    def delete_space_tables(self, space_id: str) -> bool:
        """
        Delete all RDF tables for a specific space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            bool: True if tables deleted successfully, False otherwise
        """
        PostgreSQLSpaceUtils.validate_space_id(space_id)
        
        # Delegate to database management class
        return self.db_mgmt.delete_space_tables(space_id)
    
    def space_exists(self, space_id: str) -> bool:
        """
        Check if tables for a space exist in the database.
        
        Args:
            space_id: Space identifier
            
        Returns:
            bool: True if space tables exist, False otherwise
        """
        return self.core.space_exists(space_id, self)
    
    def list_spaces(self) -> List[str]:
        """
        List all spaces that have tables in the database.
        
        Returns:
            list: List of space IDs
        """
        return self.core.list_spaces()
    
    def get_space_info(self, space_id: str) -> Dict[str, Any]:
        """
        Get information about a specific space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            dict: Space information including table details
        """
        return self.core.get_space_info(space_id, self)
    
    async def add_term(self, space_id: str, term_text: str, term_type: str, 
                      lang: Optional[str] = None, datatype_id: Optional[int] = None) -> Optional[str]:
        """
        Add a term to the terms dictionary for a specific space using UUID-based approach.
        
        Args:
            space_id: Space identifier
            term_text: The term text (URI, literal value, etc.)
            term_type: Term type ('U'=URI, 'L'=Literal, 'B'=BlankNode, 'G'=Graph)
            lang: Language tag for literals
            datatype_id: Reference to datatype term ID
            
        Returns:
            str: Term UUID if successful, None otherwise
        """
        return await self.terms.add_term(space_id, term_text, term_type, lang, datatype_id)
    
    async def get_term_uuid(self, space_id: str, term_text: str, term_type: str, 
                           lang: Optional[str] = None, datatype_id: Optional[int] = None) -> Optional[str]:
        """
        Get term UUID for existing term in a specific space using datatype-aware approach.
        
        This method is maintained for backward compatibility but now uses the new
        datatype-aware infrastructure internally.
        
        Args:
            space_id: Space identifier
            term_text: The term text
            term_type: Term type
            lang: Language tag
            datatype_id: Datatype term ID (for backward compatibility)
            
        Returns:
            str: Term UUID if found, None otherwise
        """
        return await self.terms.get_term_uuid(space_id, term_text, term_type, lang, datatype_id)
    
    async def get_term_uuid_from_rdf_value(self, space_id: str, rdf_value) -> Optional[str]:
        """
        Get term UUID for existing term from an RDF value using datatype-aware approach.
        
        This method uses the new datatype cache system to properly resolve and match
        datatype IDs for literal terms.
        
        Args:
            space_id: Space identifier
            rdf_value: RDF value (URI, literal, or blank node)
            
        Returns:
            str: Term UUID if found, None otherwise
        """
        return await self.terms.get_term_uuid_from_rdf_value(space_id, rdf_value)
    
    async def delete_term(self, space_id: str, term_text: str, term_type: str, 
                         lang: Optional[str] = None, datatype_id: Optional[int] = None) -> bool:
        """
        Delete a term from a specific space using UUID-based approach.
        
        Note: This will only delete the term if it's not referenced by any quads.
        Use with caution as this could break referential integrity if not checked properly.
        
        Args:
            space_id: Space identifier
            term_text: The term text
            term_type: Term type
            lang: Language tag
            datatype_id: Datatype term ID
            
        Returns:
            bool: True if term was deleted, False otherwise
        """
        return await self.terms.delete_term(space_id, term_text, term_type, lang, datatype_id)
    
    # Quad management methods
    async def add_quad(self, space_id: str, subject_uuid: str, predicate_uuid: str, 
                      object_uuid: str, context_uuid: str) -> bool:
        """
        Add an RDF quad to a specific space using UUID-based approach.
        
        Args:
            space_id: Space identifier
            subject_uuid: Subject term UUID
            predicate_uuid: Predicate term UUID
            object_uuid: Object term UUID
            context_uuid: Context (graph) term UUID
            
        Returns:
            bool: True if successful, False otherwise
        """
        return await self.db_ops.add_quad(space_id, subject_uuid, predicate_uuid, object_uuid, context_uuid)
    
    async def get_quad_count(self, space_id: str, context_uuid: Optional[str] = None) -> int:
        """
        Get count of quads in a specific space using UUID-based approach, optionally filtered by context.
        
        Args:
            space_id: Space identifier
            context_uuid: Optional context UUID to filter by
            
        Returns:
            int: Number of quads
            
        Raises:
            Exception: If the space does not exist
        """
        return await self.queries.get_quad_count(space_id, context_uuid)
    
    async def get_rdf_quad_count(self, space_id: str, graph_uri: Optional[str] = None) -> int:
        """
        Get count of RDF quads in a specific space, optionally filtered by graph URI (context).
        
        This is a high-level RDF API that accepts graph URIs and converts them to UUIDs
        internally for compatibility with the UUID-based get_quad_count method.
        
        Args:
            space_id: Space identifier
            graph_uri: Optional graph URI to filter by (e.g., 'http://vital.ai/graph/test')
            
        Returns:
            int: Number of quads
            
        Raises:
            Exception: If the space does not exist
        """
        return await self.queries.get_rdf_quad_count(space_id, graph_uri)
    
    async def remove_quad(self, space_id: str, subject_uuid: str, predicate_uuid: str, object_uuid: str, context_uuid: str) -> bool:
        """
        Remove a single RDF quad from a specific space using UUID-based approach.
        
        Following RDFLib pattern: removes only one instance of the matching quad,
        not all instances. If multiple identical quads exist, only one is removed.
        
        Args:
            space_id: Space identifier
            subject_uuid: Subject term UUID
            predicate_uuid: Predicate term UUID
            object_uuid: Object term UUID
            context_uuid: Context (graph) term UUID
            
        Returns:
            bool: True if a quad was removed, False if no matching quad found
        """
        return await self.db_ops.remove_quad(space_id, subject_uuid, predicate_uuid, object_uuid, context_uuid)
    

    async def get_rdf_quad(self, space_id: str, s: str, p: str, o: str, g: str) -> bool:
        """
        Check if an RDF quad exists in a specific space using datatype-aware approach.
        
        This method uses the new datatype cache system to properly resolve and match
        datatype IDs for all literal terms in the quad.
        
        Args:
            space_id: Space identifier
            s: Subject value (URI, literal, or blank node)
            p: Predicate value (typically URI)
            o: Object value (URI, literal, or blank node)
            g: Graph/context value (typically URI)
            
        Returns:
            bool: True if the quad exists, False otherwise
        """
        return await self.queries.get_rdf_quad(space_id, s, p, o, g)
    
    async def add_rdf_quads_batch(self, space_id: str, quads: List[Tuple[Identifier, Identifier, Identifier, Identifier]], 
                                 auto_commit: bool = True, verify_count: bool = False, connection=None) -> int:
        """
        Datatype-aware batch RDF quad insertion with proper datatype handling.
        
        This method uses the new datatype cache system to properly resolve and store
        datatype IDs for all literal terms in the batch.
        
        Args:
            space_id: The space identifier
            quads: List of (subject, predicate, object, context) tuples
            auto_commit: Whether to commit the transaction automatically (default: True)
            verify_count: Whether to verify insertion with COUNT query (default: False, for performance)
            connection: Optional connection to use (for transaction management)
            
        Returns:
            Number of quads successfully inserted
        """
        return await self.db_ops.add_rdf_quads_batch(space_id, quads, auto_commit, verify_count, connection)
    
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
        return await self.core.commit_transaction(connection)
    
    async def remove_rdf_quads_batch(self, space_id: str, quads: List[tuple]) -> int:
        """
        Datatype-aware batch RDF quad removal with proper datatype handling.
        
        This method uses the new datatype cache system to properly resolve and match
        datatype IDs for all literal terms in the batch.
        
        Args:
            space_id: Space identifier
            quads: List of (s, p, o, g) tuples representing RDF quads to remove
            
        Returns:
            int: Number of quads successfully removed
        """
        return await self.db_ops.remove_rdf_quads_batch(space_id, quads)
    
    # Namespace management methods
    async def add_namespace(self, space_id: str, prefix: str, namespace_uri: str) -> Optional[int]:
        """
        Add a namespace prefix mapping to a specific space.
        
        Args:
            space_id: Space identifier
            prefix: Namespace prefix (e.g., 'foaf', 'rdf')
            namespace_uri: Full namespace URI (e.g., 'http://xmlns.com/foaf/0.1/')
            
        Returns:
            int: Namespace ID if successful, None otherwise
        """
        return await self.namespaces.add_namespace(space_id, prefix, namespace_uri)
    
    async def get_namespace_uri(self, space_id: str, prefix: str) -> Optional[str]:
        """
        Get namespace URI for a given prefix in a specific space.
        
        Args:
            space_id: Space identifier
            prefix: Namespace prefix to look up
            
        Returns:
            str: Namespace URI if found, None otherwise
        """
        return await self.namespaces.get_namespace_uri(space_id, prefix)
    
    async def list_namespaces(self, space_id: str) -> List[Dict[str, Any]]:
        """
        Get all namespace prefix mappings for a specific space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            list: List of namespace dictionaries with id, prefix, namespace_uri, created_time
        """
        return await self.namespaces.list_namespaces(space_id)
    
    async def quads(self, space_id: str, quad_pattern: tuple, context: Optional[Any] = None):
        """
        A generator over all the quads matching the pattern. Pattern can include any objects
        for comparing against nodes in the store, including URIRef, Literal, BNode, Variable, 
        and REGEXTerm for regex pattern matching.
        
        This follows the RDFLib triples() pattern but for quads (subject, predicate, object, context).
        Used by SPARQL query implementation for quad pattern matching.
        
        REGEXTerm Support:
        - REGEXTerm instances in any position enable PostgreSQL regex matching (~)
        - Uses PostgreSQL's built-in regex engine for efficient pattern matching
        - Leverages pg_trgm indexes for optimized regex query performance
        - Supports full POSIX regex syntax in pattern strings
        
        Args:
            space_id: Space identifier
            quad_pattern: 4-tuple of (subject, predicate, object, context) patterns
            context: Optional context (not used in current implementation)
            
        Yields:
            tuple: (quad, context_iterator) where quad is (s, p, o, c) and 
                   context_iterator is a function that yields the context
        """
        # Delegate to the queries class
        async for result in self.queries.quads(space_id, quad_pattern, context):
            yield result
    
    def get_pool_stats(self) -> dict:
        """
        Get connection pool statistics for shared or dedicated RDF psycopg3 ConnectionPool.
        
        Returns:
            dict: Pool statistics including size, available connections, etc.
        """
        return self.core.get_pool_stats()
    
    async def health_check(self) -> bool:
        """
        Perform a health check on the connection pool.
        
        Returns:
            bool: True if pool is healthy, False otherwise
        """
        return await self.core.health_check()

    def close_pool(self) -> None:
        """
        Close the connection pool and all connections.
        """
        self.core.close_pool()

    

