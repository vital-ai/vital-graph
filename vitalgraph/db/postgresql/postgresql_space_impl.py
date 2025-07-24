import logging
import asyncio
import re
import csv
import io
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any, Union, Tuple, AsyncGenerator, Set
import psycopg
from psycopg import sql
from psycopg.rows import dict_row

# RDFLib imports for term handling
from rdflib import URIRef, Literal, BNode, Variable
from rdflib.term import Identifier

# Import PostgreSQL utilities
from .postgresql_utils import PostgreSQLUtils
from .postgresql_term_cache import PostgreSQLTermCache


class REGEXTerm(str):
    """
    REGEXTerm can be used in any term slot and is interpreted as a request to
    perform a REGEX match (not a string comparison) using the value
    (pre-compiled) for checking matches against database terms.
    
    Inspired by RDFLib's REGEXMatching store plugin.
    """
    
    def __init__(self, expr):
        self.compiledExpr = re.compile(expr)
        self.pattern = expr
    
    def __reduce__(self):
        return (REGEXTerm, (self.pattern,))
    
    def match(self, text):
        """Check if the given text matches this regex pattern."""
        return self.compiledExpr.match(str(text)) is not None
    
    def __str__(self):
        return f"REGEXTerm({self.pattern})"


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
    
    def __init__(self, connection_string: str, global_prefix: str = "vitalgraph", use_unlogged: bool = True):
        """
        Initialize PostgreSQL space implementation.
        
        Args:
            connection_string: PostgreSQL connection string
            global_prefix: Global table prefix for all spaces (default: 'vitalgraph')
            use_unlogged: Whether to use unlogged tables for better performance (default: True)
        """
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.connection_string = connection_string
        self.global_prefix = global_prefix
        self.use_unlogged = use_unlogged
        
        # Initialize PostgreSQL utilities
        self.utils = PostgreSQLUtils(logger=self.logger)
        
        # Initialize term cache for performance optimization
        self.term_cache = PostgreSQLTermCache(
            cache_size=100000,  # Cache up to 100K terms
            bloom_capacity=1000000,  # Expect up to 1M unique terms
            bloom_error_rate=0.1  # 10% false positive rate
        )
        
        # Validate global prefix using utils
        PostgreSQLUtils.validate_global_prefix(global_prefix)
        
        # Cache of table definitions by space_id
        self._table_cache = {}
        
        self.logger.info(f"Initializing PostgreSQLSpaceImpl with global prefix '{global_prefix}'")
    
    def get_connection(self):
        """
        Get a new psycopg3 database connection.
        
        Returns:
            psycopg.Connection: Database connection with dict row factory
        """
        conn = psycopg.connect(self.connection_string, row_factory=dict_row)
        return conn
    
    def _resolve_term_info(self, term: Identifier) -> Tuple[str, str, Optional[str], Optional[int]]:
        """
        Resolve an RDF term to its database representation.
        
        Args:
            term: RDFLib term (URIRef, Literal, BNode)
            
        Returns:
            tuple: (term_text, term_type, lang, datatype_id)
        """
        if isinstance(term, URIRef):
            return (str(term), 'U', None, None)
        elif isinstance(term, Literal):
            lang = term.language if term.language else None
            # For now, we'll set datatype_id to None and handle datatypes later
            datatype_id = None
            

            
            return (str(term), 'L', lang, datatype_id)
        elif isinstance(term, BNode):
            return (str(term), 'B', None, None)
        else:
            # Fallback for any other term type
            return (str(term), 'U', None, None)
    

    
    def _get_table_names(self, space_id: str) -> Dict[str, str]:
        """
        Get all RDF space table names for a specific space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            dict: Dictionary of table names keyed by base name
        """
        PostgreSQLUtils.validate_space_id(space_id)
        
        return {
            'term': PostgreSQLUtils.get_table_name(self.global_prefix, space_id, 'term'),
            'namespace': PostgreSQLUtils.get_table_name(self.global_prefix, space_id, 'namespace'),
            'graph': PostgreSQLUtils.get_table_name(self.global_prefix, space_id, 'graph'),
            'rdf_quad': PostgreSQLUtils.get_table_name(self.global_prefix, space_id, 'rdf_quad')
        }
    

    

    
    def _get_create_table_sql(self, space_id: str) -> Dict[str, str]:
        """
        Generate CREATE TABLE SQL statements for UUID-based RDF space tables.
        
        This creates tables optimized for UUID-based term identification:
        - Uses UUID primary keys instead of BIGSERIAL
        - Eliminates foreign key constraints for better performance
        - Optimized for deterministic UUID-based batch loading
        
        Args:
            space_id: Space identifier
            use_unlogged: If True, create unlogged tables for maximum speed
            
        Returns:
            dict: Dictionary of CREATE TABLE SQL statements
        """
        PostgreSQLUtils.validate_space_id(space_id)
        
        table_names = self._get_table_names(space_id)
        if self.use_unlogged:
            table_names = {key: f"{value}_unlogged" for key, value in table_names.items()}
        
        table_prefix = PostgreSQLUtils.get_table_prefix(self.global_prefix, space_id)
        if self.use_unlogged:
            table_prefix += "_unlogged"
        
        sql_statements = {}
        
        # UUID-based term table
        table_type = "UNLOGGED TABLE" if self.use_unlogged else "TABLE"
        sql_statements['term'] = f"""
            CREATE {table_type} {table_names['term']} (
                term_uuid UUID PRIMARY KEY,
                term_text TEXT NOT NULL,
                term_type CHAR(1) NOT NULL CHECK (term_type IN ('U', 'L', 'B', 'G')),
                lang VARCHAR(20),
                datatype_id BIGINT,
                created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE INDEX idx_{table_prefix}_term_text ON {table_names['term']} (term_text);
            CREATE INDEX idx_{table_prefix}_term_type ON {table_names['term']} (term_type);
        """
        
        # UUID-based quad table
        sql_statements['rdf_quad'] = f"""
            CREATE {table_type} {table_names['rdf_quad']} (
                subject_uuid UUID NOT NULL,
                predicate_uuid UUID NOT NULL,
                object_uuid UUID NOT NULL,
                context_uuid UUID NOT NULL,
                quad_uuid UUID NOT NULL DEFAULT gen_random_uuid(),
                created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (subject_uuid, predicate_uuid, object_uuid, context_uuid, quad_uuid)
            );
            
            CREATE INDEX idx_{table_prefix}_quad_predicate ON {table_names['rdf_quad']} (predicate_uuid);
            CREATE INDEX idx_{table_prefix}_quad_object ON {table_names['rdf_quad']} (object_uuid);
            CREATE INDEX idx_{table_prefix}_quad_context ON {table_names['rdf_quad']} (context_uuid);
            CREATE INDEX idx_{table_prefix}_quad_uuid ON {table_names['rdf_quad']} (quad_uuid);
        """
        
        # Namespace table (unchanged)
        sql_statements['namespace'] = f"""
            CREATE {table_type} {table_names['namespace']} (
                namespace_id BIGSERIAL PRIMARY KEY,
                prefix VARCHAR(50) NOT NULL UNIQUE,
                namespace_uri TEXT NOT NULL UNIQUE,
                created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """
        
        # Graph table (unchanged)
        sql_statements['graph'] = f"""
            CREATE {table_type} {table_names['graph']} (
                graph_id BIGSERIAL PRIMARY KEY,
                graph_uri TEXT NOT NULL UNIQUE,
                graph_name VARCHAR(255),
                created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                triple_count BIGINT DEFAULT 0
            );
        """
        
        return sql_statements
    
    def _get_performance_indexes_sql(self, space_id: str) -> Dict[str, List[str]]:
        """
        Generate SQL statements for performance indexes to be created after bulk loading.
        
        Args:
            space_id: Space identifier
            use_unlogged: If True, create indexes on unlogged tables
            
        Returns:
            dict: Dictionary of index creation SQL statements by table
        """
        PostgreSQLUtils.validate_space_id(space_id)
        
        table_names = self._get_table_names(space_id)
        if self.use_unlogged:
            table_names = {key: f"{value}_unlogged" for key, value in table_names.items()}
        table_prefix = PostgreSQLUtils.get_table_prefix(self.global_prefix, space_id)
        
        # Detect table schema (UUID vs ID based) by checking column names
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(f"""
                        SELECT COUNT(*) 
                        FROM information_schema.columns 
                        WHERE table_name = '{table_names['rdf_quad'].split('.')[-1]}' 
                        AND column_name = 'subject_uuid'
                    """)
                    result = cursor.fetchone()
                    # Handle both dict-like and tuple-like cursor results
                    if result:
                        count = result[0] if isinstance(result, (tuple, list)) else result.get('count', 0)
                        is_uuid_schema = count > 0
                    else:
                        is_uuid_schema = False
        except Exception as e:
            self.logger.warning(f"Could not detect table schema, assuming ID-based: {e}")
            is_uuid_schema = False
        
        # Use appropriate column names based on schema
        if is_uuid_schema:
            subject_col, predicate_col, object_col, context_col = 'subject_uuid', 'predicate_uuid', 'object_uuid', 'context_uuid'
        else:
            subject_col, predicate_col, object_col, context_col = 'subject_id', 'predicate_id', 'object_id', 'context_id'
        
        indexes = {}
        
        # Term table performance indexes
        indexes['term'] = [
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}term_text ON {table_names['term']} (term_text);",
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}term_type ON {table_names['term']} (term_type);",
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}term_text_type ON {table_names['term']} (term_text, term_type);",
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}term_text_gin_trgm ON {table_names['term']} USING gin (term_text gin_trgm_ops);",
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}term_text_gist_trgm ON {table_names['term']} USING gist (term_text gist_trgm_ops);"
        ]
        
        # Add table clustering for UUID-based tables to physically order rows by UUID
        if is_uuid_schema:
            # Cluster term table by UUID for better JOIN performance
            # This physically reorders table rows by UUID, improving cache locality and reducing I/O
            indexes['term'].append(f"CLUSTER {table_names['term']} USING {table_names['term']}_pkey;")
        
        # Quad table performance indexes - SPARQL optimized with appropriate column names
        indexes['rdf_quad'] = [
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}quad_spoc ON {table_names['rdf_quad']} ({subject_col}, {predicate_col}, {object_col}, {context_col});",
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}quad_subject ON {table_names['rdf_quad']} ({subject_col});",
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}quad_predicate ON {table_names['rdf_quad']} ({predicate_col});",
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}quad_object ON {table_names['rdf_quad']} ({object_col});",
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}quad_context ON {table_names['rdf_quad']} ({context_col});"
        ]
        
        # Add clustering for quad table if UUID-based (optional optimization)
        if is_uuid_schema:
            # Cluster quad table by subject_uuid for subject-focused queries
            # This can improve performance for queries that filter by subject
            indexes['rdf_quad'].append(f"CLUSTER {table_names['rdf_quad']} USING idx_{table_prefix}quad_subject;")
        
        return indexes
        
    # Space lifecycle management
    async def _ensure_text_search_extensions(self) -> bool:
        """
        Ensure that required PostgreSQL extensions for text search are enabled.
        This includes pg_trgm for trigram-based regex matching.
        
        Returns:
            bool: True if extensions are available, False otherwise
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Check if pg_trgm extension is available
                    cursor.execute(
                        "SELECT 1 FROM pg_available_extensions WHERE name = 'pg_trgm'"
                    )
                    result = cursor.fetchone()
                    
                    if not result:
                        self.logger.warning("pg_trgm extension is not available - regex performance may be limited")
                        return False
                    
                    # Enable pg_trgm extension if not already enabled
                    cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
                    conn.commit()
                    
                    self.logger.debug("pg_trgm extension is enabled for text search optimization")
                    return True
                
        except Exception as e:
            self.logger.warning(f"Could not enable text search extensions: {e}")
            return False
    

    

    
    def create_space_tables(self, space_id: str) -> bool:
        """
        Create UUID-based RDF tables optimized for deterministic batch loading.
        
        This creates tables that use UUIDs as primary keys 
        
        Args:
            space_id: Space identifier
            use_unlogged: If True, create unlogged tables for maximum speed (not crash-safe)
            
        Returns:
            bool: True if tables created successfully, False otherwise
        """
        try:
            PostgreSQLUtils.validate_space_id(space_id)
            
            self.logger.info(f"Creating UUID-based RDF tables for space '{space_id}' (unlogged={self.use_unlogged})")
            
            # Get UUID-based table creation SQL
            sql_statements = self._get_create_table_sql(space_id)
            
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    created_tables = []
                    
                    # Create tables in dependency order
                    table_order = ['term', 'rdf_quad', 'namespace', 'graph']
                    
                    for table_name in table_order:
                        if table_name in sql_statements:
                            try:
                                self.logger.debug(f"Creating UUID-based table: {table_name}")
                                
                                # Execute each statement in the SQL block
                                for statement in sql_statements[table_name].strip().split(';'):
                                    statement = statement.strip()
                                    if statement:  # Skip empty statements
                                        cursor.execute(statement)
                                
                                created_tables.append(table_name)
                                self.logger.debug(f"Successfully created UUID-based table: {table_name}")
                                
                            except Exception as e:
                                self.logger.error(f"Error creating UUID-based table {table_name}: {e}")
                                raise
                    
                    conn.commit()
                    self.logger.info(f"Successfully created {len(created_tables)} UUID-based tables for space '{space_id}': {created_tables}")
            
            # Cache table definitions
            self._table_cache[space_id] = self._get_table_names(space_id)
            return True
            
        except psycopg.Error as e:
            self.logger.error(f"Database error creating UUID-based tables for space '{space_id}': {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error creating UUID-based tables for space '{space_id}': {e}")
            return False
    
    def build_performance_indexes(self, space_id: str, concurrent: bool = True) -> bool:
        """
        Build performance indexes after bulk loading is complete.
        
        Args:
            space_id: Space identifier
            concurrent: If True, use CONCURRENTLY to avoid blocking queries
            use_unlogged: If True, build indexes on unlogged tables
            
        Returns:
            bool: True if indexes built successfully, False otherwise
        """
        try:
            PostgreSQLUtils.validate_space_id(space_id)
            
            self.logger.info(f"Building performance indexes for space '{space_id}' (concurrent={concurrent})")
            
            with self.utils.time_operation("build_indexes", f"space '{space_id}'"):
                with self.get_connection() as conn:
                    with conn.cursor() as cursor:
                        # Get index creation SQL (for unlogged tables if needed)
                        indexes_sql = self._get_performance_indexes_sql(space_id)
                        
                        total_indexes = sum(len(table_indexes) for table_indexes in indexes_sql.values())
                        created_indexes = 0
                        
                        for table_name, table_indexes in indexes_sql.items():
                            self.logger.info(f"Building {len(table_indexes)} indexes for {table_name} table...")
                            
                            for index_sql in table_indexes:
                                try:
                                    # Remove CONCURRENTLY if not requested
                                    if not concurrent:
                                        index_sql = index_sql.replace(' CONCURRENTLY', '')
                                    
                                    self.logger.debug(f"Executing: {index_sql}")
                                    cursor.execute(index_sql)
                                    created_indexes += 1
                                    
                                    # Commit each index if using CONCURRENTLY
                                    if concurrent:
                                        conn.commit()
                                        
                                except psycopg.Error as e:
                                    self.logger.warning(f"Failed to create index: {e}")
                                    if concurrent:
                                        conn.rollback()
                        
                        # Final commit if not using CONCURRENTLY
                        if not concurrent:
                            conn.commit()
                        
                        self.logger.info(f"Successfully created {created_indexes}/{total_indexes} performance indexes for space '{space_id}'")
            
            return created_indexes > 0
            
        except psycopg.Error as e:
            self.logger.error(f"Database error building indexes for space '{space_id}': {e}")
            return False
    
    def delete_space_tables(self, space_id: str) -> bool:
        """
        Delete all RDF tables for a specific space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            bool: True if tables deleted successfully, False otherwise
        """
        try:
            PostgreSQLUtils.validate_space_id(space_id)
            
            self.logger.info(f"Deleting RDF tables for space '{space_id}'")
            
            # Get table names for this space
            table_names = self._get_table_names(space_id)
            if self.use_unlogged:
                table_names = {key: f"{value}_unlogged" for key, value in table_names.items()}
            
            base_names = ['rdf_quad', 'graph', 'namespace', 'term']  # Drop in reverse dependency order
            
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    dropped_tables = []
                    
                    # Drop the expected tables for this space
                    for base_name in base_names:
                        table_name = table_names[base_name]
                        try:
                            cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
                            dropped_tables.append(table_name)
                            self.logger.debug(f"Dropped table {table_name}")
                        except Exception as e:
                            self.logger.warning(f"Could not drop table {table_name}: {e}")
                    
                    conn.commit()
                    self.logger.info(f"Successfully deleted {len(dropped_tables)} tables for space '{space_id}'")
                    self.logger.debug(f"Dropped tables: {dropped_tables}")
            
            return True
            
        except psycopg.Error as e:
            self.logger.error(f"Database error deleting tables for space '{space_id}': {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error deleting tables for space '{space_id}': {e}")
            return False
    
    async def space_exists(self, space_id: str) -> bool:
        """
        Check if tables for a space exist in the database.
        
        Args:
            space_id: Space identifier
            
        Returns:
            bool: True if space tables exist, False otherwise
        """
        try:
            PostgreSQLUtils.validate_space_id(space_id)
            
            # Check if at least the term table exists for this space by trying to query it
            term_table_name = PostgreSQLUtils.get_table_name(self.global_prefix, space_id, 'term')
            
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Try to query the table directly - if it doesn't exist, this will raise an exception
                    cursor.execute(f"SELECT 1 FROM {term_table_name} LIMIT 1")
                    # If we get here, the table exists
                    exists = True
            
            self.logger.debug(f"Space '{space_id}' exists: {exists}")
            return exists
            
        except Exception as e:
            # If we get an exception (likely "relation does not exist"), the space doesn't exist
            self.logger.debug(f"Space '{space_id}' does not exist: {e}")
            return False
    
    async def list_spaces(self) -> List[str]:
        """
        List all spaces that have tables in the database.
        
        Returns:
            list: List of space IDs
        """
        try:
            spaces = set()
            
            self.logger.debug(f"Listing spaces with global prefix: {self.global_prefix}")
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Query for tables matching our naming pattern
                cursor.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_name LIKE %s",
                    (f"{self.global_prefix}__%__term",)
                )
                results = cursor.fetchall()
                
                for row in results:
                    table_name = row[0]
                    # Extract space_id from table name: global_prefix__space_id__term
                    parts = table_name.split('__')
                    if len(parts) >= 3 and parts[0] == self.global_prefix and parts[-1] == 'term':
                        space_id = '__'.join(parts[1:-1])  # Handle space_ids with underscores
                        spaces.add(space_id)
            
            space_list = sorted(list(spaces))
            self.logger.debug(f"Found {len(space_list)} spaces: {space_list}")
            return space_list
            
        except Exception as e:
            self.logger.error(f"Error listing spaces: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return []
    
    async def get_space_info(self, space_id: str) -> Dict[str, Any]:
        """
        Get information about a specific space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            dict: Space information including table details
        """
        try:
            PostgreSQLUtils.validate_space_id(space_id)
            
            info = {
                "space_id": space_id,
                "table_prefix": PostgreSQLUtils.get_table_prefix(self.global_prefix, space_id),
                "exists": await self.space_exists(space_id),
                "tables": {}
            }
            
            self.logger.debug(f"Getting space info for space '{space_id}'")
            
            if info["exists"]:
                # Get table information
                base_names = ['term', 'namespace', 'graph', 'rdf_quad']
                
                with self.get_connection() as conn:
                    cursor = conn.cursor()
                    
                    for base_name in base_names:
                        table_name = PostgreSQLUtils.get_table_name(self.global_prefix, space_id, base_name)
                        
                        table_info = {
                            "full_name": table_name,
                            "exists": True,  # We know space exists
                            "row_count": 0
                        }
                        
                        # Get row count
                        try:
                            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                            result = cursor.fetchone()
                            table_info["row_count"] = result[0] if result else 0
                        except Exception as e:
                            self.logger.warning(f"Could not get row count for {table_name}: {e}")
                        
                        info["tables"][base_name] = table_info
            
            return info
            
        except Exception as e:
            self.logger.error(f"Error getting space info: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": str(e)}
    
    # Term management methods
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
        try:
            PostgreSQLUtils.validate_space_id(space_id)
            
            # Generate deterministic UUID for the term
            term_key = (term_text, term_type, lang, datatype_id)
            # Generate deterministic UUID
            RDF_NAMESPACE = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
            composite_key = f"{term_text}|{term_type}|{lang or ''}|{datatype_id or 0}"
            term_uuid = uuid.uuid5(RDF_NAMESPACE, composite_key)
            
            # Get table names
            table_prefix = PostgreSQLUtils.get_table_prefix(self.global_prefix, space_id)
            term_table_name = PostgreSQLUtils.get_table_name(self.global_prefix, space_id, "term")
            
            # Use raw psycopg3 connection for UUID-based operations
            with self.get_connection() as conn:
                conn.row_factory = psycopg.rows.dict_row
                cursor = conn.cursor()
                
                # Check if term already exists
                cursor.execute(
                    f"SELECT term_uuid FROM {term_table_name} WHERE term_uuid = %s",
                    (term_uuid,)
                )
                result = cursor.fetchone()
                
                if result:
                    self.logger.debug(f"Term already exists in space '{space_id}' with UUID: {term_uuid}")
                    return str(term_uuid)
                
                # Insert new term
                cursor.execute(
                    f"""
                    INSERT INTO {term_table_name} 
                    (term_uuid, term_text, term_type, lang, datatype_id, created_time) 
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (term_uuid, term_text, term_type, lang, datatype_id, datetime.utcnow())
                )
                conn.commit()
                
                self.logger.debug(f"Added term '{term_text}' to space '{space_id}' with UUID: {term_uuid}")
                return str(term_uuid)
                
        except Exception as e:
            self.logger.error(f"Error adding term to space '{space_id}': {e}")
            return None
    
    async def get_term_uuid(self, space_id: str, term_text: str, term_type: str, 
                           lang: Optional[str] = None, datatype_id: Optional[int] = None) -> Optional[str]:
        """
        Get term UUID for existing term in a specific space using UUID-based approach.
        
        Args:
            space_id: Space identifier
            term_text: The term text
            term_type: Term type
            lang: Language tag
            datatype_id: Datatype term ID
            
        Returns:
            str: Term UUID if found, None otherwise
        """
        try:
            PostgreSQLUtils.validate_space_id(space_id)
            
            # Generate deterministic UUID for the term
            term_key = (term_text, term_type, lang, datatype_id)
            # Generate deterministic UUID
            RDF_NAMESPACE = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
            composite_key = f"{term_text}|{term_type}|{lang or ''}|{datatype_id or 0}"
            term_uuid = uuid.uuid5(RDF_NAMESPACE, composite_key)
            
            # Get table names
            table_prefix = PostgreSQLUtils.get_table_prefix(self.global_prefix, space_id)
            term_table_name = PostgreSQLUtils.get_table_name(self.global_prefix, space_id, "term")
            
            # Use raw psycopg3 connection for UUID-based operations
            with self.get_connection() as conn:
                conn.row_factory = psycopg.rows.dict_row
                cursor = conn.cursor()
                
                # Check if term exists
                cursor.execute(
                    f"SELECT term_uuid FROM {term_table_name} WHERE term_uuid = %s",
                    (term_uuid,)
                )
                result = cursor.fetchone()
                
                return str(term_uuid) if result else None
                
        except Exception as e:
            self.logger.error(f"Error getting term UUID from space '{space_id}': {e}")
            return None
    
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
        try:
            PostgreSQLUtils.validate_space_id(space_id)
            
            # Generate deterministic UUID for the term
            term_key = (term_text, term_type, lang, datatype_id)
            # Generate deterministic UUID
            RDF_NAMESPACE = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
            composite_key = f"{term_text}|{term_type}|{lang or ''}|{datatype_id or 0}"
            term_uuid = uuid.uuid5(RDF_NAMESPACE, composite_key)
            
            # Get table names
            table_prefix = PostgreSQLUtils.get_table_prefix(self.global_prefix, space_id)
            term_table_name = PostgreSQLUtils.get_table_name(self.global_prefix, space_id, "term")
            quad_table_name = PostgreSQLUtils.get_table_name(self.global_prefix, space_id, "rdf_quad")
            
            # Use raw psycopg3 connection for UUID-based operations
            with self.get_connection() as conn:
                conn.row_factory = psycopg.rows.dict_row
                cursor = conn.cursor()
                
                # First check if term exists
                cursor.execute(
                    f"SELECT term_uuid FROM {term_table_name} WHERE term_uuid = %s",
                    (term_uuid,)
                )
                result = cursor.fetchone()
                
                if not result:
                    self.logger.debug(f"Term does not exist in space '{space_id}' with UUID: {term_uuid}")
                    return False
                
                # Check if term is referenced by any quads
                cursor.execute(
                    f"""
                    SELECT COUNT(*) as count FROM {quad_table_name} 
                    WHERE subject_uuid = %s OR predicate_uuid = %s OR object_uuid = %s OR context_uuid = %s
                    """,
                    (term_uuid, term_uuid, term_uuid, term_uuid)
                )
                quad_count = cursor.fetchone()['count']
                
                if quad_count > 0:
                    self.logger.warning(f"Cannot delete term '{term_text}' from space '{space_id}': referenced by {quad_count} quads")
                    return False
                
                # Delete the term
                cursor.execute(
                    f"DELETE FROM {term_table_name} WHERE term_uuid = %s",
                    (term_uuid,)
                )
                
                deleted_count = cursor.rowcount
                conn.commit()
                
                if deleted_count > 0:
                    self.logger.debug(f"Deleted term '{term_text}' from space '{space_id}' with UUID: {term_uuid}")
                    return True
                else:
                    self.logger.debug(f"No term deleted from space '{space_id}' with UUID: {term_uuid}")
                    return False
                
        except Exception as e:
            self.logger.error(f"Error deleting term from space '{space_id}': {e}")
            return False
    
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
        try:
            PostgreSQLUtils.validate_space_id(space_id)
            
            # Get table names using UUID-based approach
            table_prefix = PostgreSQLUtils.get_table_prefix(self.global_prefix, space_id)
            quad_table_name = PostgreSQLUtils.get_table_name(self.global_prefix, space_id, "rdf_quad")
            
            # Use raw psycopg3 connection for UUID-based operations
            with self.get_connection() as conn:
                conn.row_factory = psycopg.rows.dict_row
                cursor = conn.cursor()
                
                # Insert quad (duplicates allowed, quad_uuid auto-generated)
                cursor.execute(
                    f"""
                    INSERT INTO {quad_table_name} 
                    (subject_uuid, predicate_uuid, object_uuid, context_uuid, created_time) 
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING quad_uuid
                    """,
                    (subject_uuid, predicate_uuid, object_uuid, context_uuid, datetime.utcnow())
                )
                result = cursor.fetchone()
                quad_uuid = result['quad_uuid']
                conn.commit()
                
                self.logger.debug(f"Added quad to space '{space_id}' with UUID: {quad_uuid}")
                return True
                
        except Exception as e:
            self.logger.error(f"Error adding quad to space '{space_id}': {e}")
            return False
    
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
        PostgreSQLUtils.validate_space_id(space_id)
        
        # Check if space exists first - this will throw if it doesn't
        space_exists = await self.space_exists(space_id)
        if not space_exists:
            raise ValueError(f"Space '{space_id}' does not exist")
        
        # Get table names using UUID-based approach
        quad_table_name = PostgreSQLUtils.get_table_name(self.global_prefix, space_id, "rdf_quad")
        
        try:
            # Use raw psycopg3 connection for UUID-based operations
            with self.get_connection() as conn:
                conn.row_factory = psycopg.rows.dict_row
                cursor = conn.cursor()
                
                if context_uuid:
                    cursor.execute(
                        f"SELECT COUNT(*) as count FROM {quad_table_name} WHERE context_uuid = %s", 
                        (context_uuid,)
                    )
                else:
                    cursor.execute(f"SELECT COUNT(*) as count FROM {quad_table_name}")
                
                result = cursor.fetchone()
                return result['count'] if result else 0
                    
        except Exception as e:
            self.logger.error(f"Error getting quad count from space '{space_id}': {e}")
            raise  # Re-raise the exception instead of returning 0
    
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
        try:
            self.logger.debug(f"Getting RDF quad count from space '{space_id}' with graph URI: {graph_uri}")
            
            # If no graph URI specified, get total count
            if graph_uri is None:
                return await self.get_quad_count(space_id)
            
            # Convert graph URI to UUID
            from rdflib import URIRef
            graph_ref = URIRef(graph_uri)
            
            # Determine term type and generate UUID
            g_type, g_lang, g_datatype_id = PostgreSQLUtils.determine_term_type(graph_ref)
            g_value = PostgreSQLUtils.extract_literal_value(graph_ref) if g_type == 'L' else graph_ref
            
            # Look up the graph UUID in the term table
            graph_uuid = await self.get_term_uuid(space_id, str(g_value), g_type, g_lang, g_datatype_id)
            
            if graph_uuid is None:
                # Graph URI doesn't exist in this space, so count is 0
                self.logger.debug(f"Graph URI '{graph_uri}' not found in space '{space_id}', returning count 0")
                return 0
            
            # Use the UUID-based method
            return await self.get_quad_count(space_id, graph_uuid)
            
        except Exception as e:
            self.logger.error(f"Error getting RDF quad count from space '{space_id}' with graph '{graph_uri}': {e}")
            raise
    
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
        try:
            PostgreSQLUtils.validate_space_id(space_id)
            
            # Get table names using UUID-based approach
            table_prefix = PostgreSQLUtils.get_table_prefix(self.global_prefix, space_id)
            quad_table_name = PostgreSQLUtils.get_table_name(self.global_prefix, space_id, "rdf_quad")
            
            # Use raw psycopg3 connection for UUID-based operations
            with self.get_connection() as conn:
                conn.row_factory = psycopg.rows.dict_row
                cursor = conn.cursor()
                
                # Delete exactly one instance using ctid (handles duplicates properly)
                cursor.execute(
                    f"""
                    DELETE FROM {quad_table_name} 
                    WHERE ctid IN (
                        SELECT ctid FROM {quad_table_name}
                        WHERE subject_uuid = %s AND predicate_uuid = %s 
                              AND object_uuid = %s AND context_uuid = %s
                        LIMIT 1
                    )
                    """,
                    (subject_uuid, predicate_uuid, object_uuid, context_uuid)
                )
                
                removed_count = cursor.rowcount
                conn.commit()
                
                if removed_count > 0:
                    self.logger.debug(f"Removed one quad instance from space '{space_id}'")
                    return True
                else:
                    self.logger.debug(f"No quad was actually removed from space '{space_id}'")
                    return False
                
        except Exception as e:
            self.logger.error(f"Error removing quad from space '{space_id}': {e}")
            return False
    

    
    async def add_rdf_quad(self, space_id: str, quad: Union[tuple, list]) -> bool:
        """
        Add an RDF quad to a specific space by converting RDF values to terms first using UUID-based approach.
        
        This function automatically determines term types from the RDF values and handles
        term conversion internally. It converts the subject, predicate, object, and graph
        values to term UUIDs and then calls add_quad().
        
        Args:
            space_id: Space identifier
            quad: Tuple of (subject, predicate, object, graph) RDF values
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Unpack the quad tuple
            s, p, o, g = quad
            self.logger.debug(f"Adding RDF quad to space '{space_id}': <{s}> <{p}> <{o}> <{g}>")
            
            # Determine term types automatically
            s_type, s_lang, s_datatype_id = PostgreSQLUtils.determine_term_type(s)
            p_type, p_lang, p_datatype_id = PostgreSQLUtils.determine_term_type(p)
            o_type, o_lang, o_datatype_id = PostgreSQLUtils.determine_term_type(o)
            g_type, g_lang, g_datatype_id = PostgreSQLUtils.determine_term_type(g)
            
            # Extract literal values if needed
            s_value = PostgreSQLUtils.extract_literal_value(s) if s_type == 'L' else s
            p_value = PostgreSQLUtils.extract_literal_value(p) if p_type == 'L' else p
            o_value = PostgreSQLUtils.extract_literal_value(o) if o_type == 'L' else o
            g_value = PostgreSQLUtils.extract_literal_value(g) if g_type == 'L' else g
            
            self.logger.debug(f"Detected types: s={s_type}, p={p_type}, o={o_type}, g={g_type}")
            
            # Convert subject to term UUID
            subject_uuid = await self.add_term(space_id, s_value, s_type, s_lang, s_datatype_id)
            if subject_uuid is None:
                self.logger.error(f"Failed to add subject term '{s}' to space '{space_id}'")
                return False
            
            # Convert predicate to term UUID
            predicate_uuid = await self.add_term(space_id, p_value, p_type, p_lang, p_datatype_id)
            if predicate_uuid is None:
                self.logger.error(f"Failed to add predicate term '{p}' to space '{space_id}'")
                return False
            
            # Convert object to term UUID
            object_uuid = await self.add_term(space_id, o_value, o_type, o_lang, o_datatype_id)
            if object_uuid is None:
                self.logger.error(f"Failed to add object term '{o}' to space '{space_id}'")
                return False
            
            # Convert graph to term UUID
            graph_uuid = await self.add_term(space_id, g_value, g_type, g_lang, g_datatype_id)
            if graph_uuid is None:
                self.logger.error(f"Failed to add graph term '{g}' to space '{space_id}'")
                return False
            
            # Add the quad using term UUIDs
            success = await self.add_quad(space_id, subject_uuid, predicate_uuid, object_uuid, graph_uuid)
            
            if success:
                self.logger.debug(f"Successfully added RDF quad to space '{space_id}'")
            else:
                self.logger.error(f"Failed to add RDF quad to space '{space_id}'")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Error adding RDF quad to space '{space_id}': {e}")
            return False
    
    async def remove_rdf_quad(self, space_id: str, s: str, p: str, o: str, g: str) -> bool:
        """
        Remove an RDF quad from a specific space by converting RDF values to terms first using UUID-based approach.
        
        This function automatically determines term types from the RDF values and handles
        term lookup internally. It looks up the term UUIDs for the subject, predicate, object,
        and graph values and then calls remove_quad().
        
        Following RDFLib pattern: removes only one instance of the matching quad.
        
        Args:
            space_id: Space identifier
            s: Subject value (URI, literal, or blank node)
            p: Predicate value (typically URI)
            o: Object value (URI, literal, or blank node)
            g: Graph/context value (typically URI)
            
        Returns:
            bool: True if a quad was removed, False if no matching quad found
        """
        try:
            self.logger.debug(f"Removing RDF quad from space '{space_id}': <{s}> <{p}> <{o}> <{g}>")
            
            # Determine term types automatically
            s_type, s_lang, s_datatype_id = PostgreSQLUtils.determine_term_type(s)
            p_type, p_lang, p_datatype_id = PostgreSQLUtils.determine_term_type(p)
            o_type, o_lang, o_datatype_id = PostgreSQLUtils.determine_term_type(o)
            g_type, g_lang, g_datatype_id = PostgreSQLUtils.determine_term_type(g)
            
            # Extract literal values if needed
            s_value = PostgreSQLUtils.extract_literal_value(s) if s_type == 'L' else s
            p_value = PostgreSQLUtils.extract_literal_value(p) if p_type == 'L' else p
            o_value = PostgreSQLUtils.extract_literal_value(o) if o_type == 'L' else o
            g_value = PostgreSQLUtils.extract_literal_value(g) if g_type == 'L' else g
            
            self.logger.debug(f"Detected types: s={s_type}, p={p_type}, o={o_type}, g={g_type}")
            
            # Generate deterministic UUIDs for the terms
            RDF_NAMESPACE = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
            s_composite = f"{s_value}|{s_type}|{s_lang or ''}|{s_datatype_id or 0}"
            p_composite = f"{p_value}|{p_type}|{p_lang or ''}|{p_datatype_id or 0}"
            o_composite = f"{o_value}|{o_type}|{o_lang or ''}|{o_datatype_id or 0}"
            g_composite = f"{g_value}|{g_type}|{g_lang or ''}|{g_datatype_id or 0}"
            
            subject_uuid = uuid.uuid5(RDF_NAMESPACE, s_composite)
            predicate_uuid = uuid.uuid5(RDF_NAMESPACE, p_composite)
            object_uuid = uuid.uuid5(RDF_NAMESPACE, o_composite)
            graph_uuid = uuid.uuid5(RDF_NAMESPACE, g_composite)
            
            # Remove the quad using term UUIDs
            success = await self.remove_quad(space_id, subject_uuid, predicate_uuid, object_uuid, graph_uuid)
            
            if success:
                self.logger.debug(f"Successfully removed RDF quad from space '{space_id}'")
            else:
                self.logger.debug(f"No matching RDF quad found to remove from space '{space_id}'")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Error removing RDF quad from space '{space_id}': {e}")
            return False
    
    async def get_rdf_quad(self, space_id: str, s: str, p: str, o: str, g: str) -> bool:
        """
        Check if an RDF quad exists in a specific space using UUID-based approach.
        
        This function automatically determines term types from the RDF values and handles
        term lookup internally. It looks up the term UUIDs for the subject, predicate, object,
        and graph values and then checks if the quad exists.
        
        Args:
            space_id: Space identifier
            s: Subject value (URI, literal, or blank node)
            p: Predicate value (typically URI)
            o: Object value (URI, literal, or blank node)
            g: Graph/context value (typically URI)
            
        Returns:
            bool: True if the quad exists, False otherwise
        """
        try:
            self.logger.debug(f"Checking RDF quad in space '{space_id}': <{s}> <{p}> <{o}> <{g}>")
            
            # Determine term types automatically
            s_type, s_lang, s_datatype_id = PostgreSQLUtils.determine_term_type(s)
            p_type, p_lang, p_datatype_id = PostgreSQLUtils.determine_term_type(p)
            o_type, o_lang, o_datatype_id = PostgreSQLUtils.determine_term_type(o)
            g_type, g_lang, g_datatype_id = PostgreSQLUtils.determine_term_type(g)
            
            # Extract literal values if needed
            s_value = PostgreSQLUtils.extract_literal_value(s) if s_type == 'L' else s
            p_value = PostgreSQLUtils.extract_literal_value(p) if p_type == 'L' else p
            o_value = PostgreSQLUtils.extract_literal_value(o) if o_type == 'L' else o
            g_value = PostgreSQLUtils.extract_literal_value(g) if g_type == 'L' else g
            
            self.logger.debug(f"Detected types: s={s_type}, p={p_type}, o={o_type}, g={g_type}")
            
            # Generate UUIDs for the terms (deterministic)
            s_key = (s_value, s_type, s_lang, s_datatype_id)
            p_key = (p_value, p_type, p_lang, p_datatype_id)
            o_key = (o_value, o_type, o_lang, o_datatype_id)
            g_key = (g_value, g_type, g_lang, g_datatype_id)
            
            # Generate deterministic UUIDs
            RDF_NAMESPACE = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
            s_composite = f"{s_value}|{s_type}|{s_lang or ''}|{s_datatype_id or 0}"
            p_composite = f"{p_value}|{p_type}|{p_lang or ''}|{p_datatype_id or 0}"
            o_composite = f"{o_value}|{o_type}|{o_lang or ''}|{o_datatype_id or 0}"
            g_composite = f"{g_value}|{g_type}|{g_lang or ''}|{g_datatype_id or 0}"
            
            subject_uuid = uuid.uuid5(RDF_NAMESPACE, s_composite)
            predicate_uuid = uuid.uuid5(RDF_NAMESPACE, p_composite)
            object_uuid = uuid.uuid5(RDF_NAMESPACE, o_composite)
            graph_uuid = uuid.uuid5(RDF_NAMESPACE, g_composite)
            
            # Get table names using UUID-based approach
            table_prefix = PostgreSQLUtils.get_table_prefix(self.global_prefix, space_id)
            quad_table_name = PostgreSQLUtils.get_table_name(self.global_prefix, space_id, "rdf_quad")
            
            # Use raw psycopg3 connection for UUID-based operations
            with self.get_connection() as conn:
                conn.row_factory = psycopg.rows.dict_row
                cursor = conn.cursor()
                
                # Check if quad exists
                cursor.execute(
                    f"""
                    SELECT quad_uuid FROM {quad_table_name} 
                    WHERE subject_uuid = %s AND predicate_uuid = %s AND object_uuid = %s AND context_uuid = %s
                    LIMIT 1
                    """,
                    (subject_uuid, predicate_uuid, object_uuid, graph_uuid)
                )
                result = cursor.fetchone()
                
                exists = result is not None
                
                if exists:
                    self.logger.debug(f"RDF quad exists in space '{space_id}' with UUID: {result['quad_uuid']}")
                else:
                    self.logger.debug(f"RDF quad does not exist in space '{space_id}'")
                
                return exists
                
        except Exception as e:
            self.logger.error(f"Error checking RDF quad in space '{space_id}': {e}")
            return False
    
    async def add_rdf_quads_batch(self, space_id: str, quads: List[Tuple[Identifier, Identifier, Identifier, Identifier]]) -> int:
        """
        Ultra-clean UUID-based RDF quad batch insert.
        
        This approach eliminates all ID management complexity by using deterministic UUIDs:
        1. Generate UUIDs for all terms in batch
        2. Query which UUIDs already exist in database
        3. Insert only missing terms
        4. Insert quads using UUIDs (no ID mapping needed)
        
        Args:
            space_id: Space identifier
            quads: List of (s, p, o, g) tuples representing RDF quads
            use_unlogged: If True, target unlogged tables
            
        Returns:
            int: Number of quads successfully added
        """
        if not quads:
            return 0
            
        try:
            # Fixed namespace for deterministic UUID generation
            RDF_NAMESPACE = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
            
            def generate_term_uuid(term_text: str, term_type: str, lang: str = None, datatype_id: int = None) -> uuid.UUID:
                """Generate deterministic UUID for any term."""
                composite_key = f"{term_text}|{term_type}|{lang or ''}|{datatype_id or 0}"
                return uuid.uuid5(RDF_NAMESPACE, composite_key)
            
            # Get table names (with unlogged suffix if needed)
            table_names = self._get_table_names(space_id)
            if self.use_unlogged:
                table_names = {key: f"{value}_unlogged" for key, value in table_names.items()}
                self.logger.debug(f"Using unlogged tables: {table_names}")
            
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    self.logger.info(f"🚀 UUID BATCH INSERT: Starting processing of {len(quads)} quads...")
                    
                    # Step 1: Collect all unique terms and generate UUIDs
                    self.logger.info("📋 STEP 1: Collecting unique terms and generating UUIDs...")
                    unique_terms = set()
                    quad_term_data = []
                    
                    for s, p, o, g in quads:
                        try:
                            s_info = self._resolve_term_info(s)
                            p_info = self._resolve_term_info(p)
                            o_info = self._resolve_term_info(o)
                            
                            # Assign global graph if no graph is specified (g is None)
                            if g is None:
                                from vitalgraph.db.postgresql.postgresql_sparql_impl import GraphConstants
                                from rdflib import URIRef
                                global_graph = URIRef(GraphConstants.GLOBAL_GRAPH_URI)
                                g_info = self._resolve_term_info(global_graph)
                            else:
                                g_info = self._resolve_term_info(g)
                            
                            quad_term_data.append((s_info, p_info, o_info, g_info))
                            unique_terms.update([s_info, p_info, o_info, g_info])
                        except Exception as e:
                            self.logger.error(f"❌ Error resolving term info: {e}")
                            continue
                    
                    self.logger.info(f"📊 Generated {len(unique_terms)} unique terms from {len(quads)} quads")
                    
                    # Step 2: Generate UUIDs for all unique terms
                    self.logger.info("🔑 STEP 2: Generating UUIDs for all terms...")
                    term_to_uuid = {}
                    uuid_to_term = {}
                    
                    for term_info in unique_terms:
                        term_text, term_type, lang, datatype_id = term_info
                        term_uuid = generate_term_uuid(term_text, term_type, lang, datatype_id)
                        term_to_uuid[term_info] = term_uuid
                        uuid_to_term[term_uuid] = term_info
                    
                    self.logger.info(f"🔑 Generated UUIDs for all {len(unique_terms)} terms")
                    
                    # Step 3: Check which UUIDs already exist in database
                    self.logger.info("🔍 STEP 3: Checking which UUIDs already exist...")
                    all_uuids = list(term_to_uuid.values())
                    cursor.execute(
                        f"SELECT term_uuid FROM {table_names['term']} WHERE term_uuid = ANY(%s)",
                        (all_uuids,)
                    )
                    
                    existing_uuids = {row['term_uuid'] for row in cursor.fetchall()}
                    missing_uuids = set(all_uuids) - existing_uuids
                    
                    self.logger.info(f"✅ Found {len(existing_uuids)} existing terms, {len(missing_uuids)} new terms to insert")
                    
                    # Step 4: Insert only missing terms
                    if missing_uuids:
                        self.logger.info(f"🚀 STEP 4: Inserting {len(missing_uuids)} new terms...")
                        new_terms_data = []
                        for missing_uuid in missing_uuids:
                            term_info = uuid_to_term[missing_uuid]
                            term_text, term_type, lang, datatype_id = term_info
                            new_terms_data.append((missing_uuid, term_text, term_type, lang, datatype_id, datetime.utcnow()))
                        
                        cursor.executemany(
                            f"""INSERT INTO {table_names['term']} 
                               (term_uuid, term_text, term_type, lang, datatype_id, created_time) 
                               VALUES (%s, %s, %s, %s, %s, %s)""",
                            new_terms_data
                        )
                        self.logger.info(f"✅ Inserted {len(new_terms_data)} new terms")
                    else:
                        self.logger.info("⚠️  STEP 4 SKIPPED: All terms already exist")
                    
                    # Step 5: Insert quads using UUIDs (no ID mapping needed!)
                    if quad_term_data:
                        self.logger.info(f"🔧 STEP 5: Inserting {len(quad_term_data)} quads using UUIDs...")
                        quad_data = []
                        for s_info, p_info, o_info, g_info in quad_term_data:
                            quad_data.append((
                                term_to_uuid[s_info],    # Subject UUID
                                term_to_uuid[p_info],     # Predicate UUID  
                                term_to_uuid[o_info],     # Object UUID
                                term_to_uuid[g_info],     # Context UUID
                                datetime.utcnow()
                            ))
                        
                        cursor.executemany(
                            f"""INSERT INTO {table_names['rdf_quad']} 
                               (subject_uuid, predicate_uuid, object_uuid, context_uuid, created_time) 
                               VALUES (%s, %s, %s, %s, %s)""",
                            quad_data
                        )
                        
                        # Verify the quad insert worked
                        cursor.execute(f"SELECT COUNT(*) as count FROM {table_names['rdf_quad']}")
                        quad_count = cursor.fetchone()['count']
                        self.logger.info(f"✅ STEP 5 COMPLETE: Inserted {len(quad_data)} quads, verified {quad_count} total quads in table")
                        
                        if quad_count == 0:
                            self.logger.error("❌ CRITICAL: Batch insert completed but no quads were inserted!")
                            return 0
                        
                        # Commit the transaction
                        self.logger.info("💾 Committing transaction...")
                        conn.commit()
                        self.logger.info("✅ Transaction committed successfully")
                        
                        self.logger.info(f"🎉 SUCCESS: UUID batch insert completed - {len(quads)} quads added to space '{space_id}'")
                        return len(quads)
                        
                    else:
                        self.logger.info("⚠️  STEP 5 SKIPPED: No quads to insert")
                        return 0
                    
        except Exception as e:
            self.logger.error(f"Error in UUID batch insert to space '{space_id}': {e}")
            import traceback
            self.logger.error(f"📋 Full traceback: {traceback.format_exc()}")
            return 0
    
    async def remove_rdf_quads_batch(self, space_id: str, quads: List[tuple]) -> int:
        """
        Remove multiple RDF quads from a specific space efficiently using UUID-based batch operations.
        
        This function processes large batches (50,000+) efficiently by:
        1. Resolving all term types and generating UUIDs in batch
        2. Looking up existing terms by UUID in batch
        3. Removing matching quads in batch using UUIDs
        
        Args:
            space_id: Space identifier
            quads: List of (s, p, o, g) tuples representing RDF quads to remove
            
        Returns:
            int: Number of quads successfully removed
        """
        if not quads:
            return 0
            
        with self.utils.time_operation("remove_rdf_quads_batch_uuid", f"removing {len(quads)} quads from space '{space_id}'"):
            try:
                # Step 1: Resolve all term types and generate UUIDs
                with self.utils.time_operation("batch_term_resolution", f"resolving types for {len(quads)} quads"):
                    unique_terms = set()  # Set of (value, type, lang, datatype_id) tuples
                    quad_uuids = []  # [(s_uuid, p_uuid, o_uuid, g_uuid), ...]
                    
                    for s, p, o, g in quads:
                        # Determine term types
                        s_type, s_lang, s_datatype_id = PostgreSQLUtils.determine_term_type(s)
                        p_type, p_lang, p_datatype_id = PostgreSQLUtils.determine_term_type(p)
                        o_type, o_lang, o_datatype_id = PostgreSQLUtils.determine_term_type(o)
                        g_type, g_lang, g_datatype_id = PostgreSQLUtils.determine_term_type(g)
                        
                        # Extract values
                        s_value = PostgreSQLUtils.extract_literal_value(s) if s_type == 'L' else str(s)
                        p_value = PostgreSQLUtils.extract_literal_value(p) if p_type == 'L' else str(p)
                        o_value = PostgreSQLUtils.extract_literal_value(o) if o_type == 'L' else str(o)
                        g_value = PostgreSQLUtils.extract_literal_value(g) if g_type == 'L' else str(g)
                        
                        # Store unique terms
                        s_info = (s_value, s_type, s_lang, s_datatype_id)
                        p_info = (p_value, p_type, p_lang, p_datatype_id)
                        o_info = (o_value, o_type, o_lang, o_datatype_id)
                        g_info = (g_value, g_type, g_lang, g_datatype_id)
                        
                        unique_terms.update([s_info, p_info, o_info, g_info])
                        
                        # Generate UUIDs for this quad
                        s_key = (s_value, s_type, s_lang, s_datatype_id)
                        p_key = (p_value, p_type, p_lang, p_datatype_id)
                        o_key = (o_value, o_type, o_lang, o_datatype_id)
                        g_key = (g_value, g_type, g_lang, g_datatype_id)
                        
                        # Generate deterministic UUIDs
                        RDF_NAMESPACE = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
                        s_composite = f"{s_value}|{s_type}|{s_lang or ''}|{s_datatype_id or 0}"
                        p_composite = f"{p_value}|{p_type}|{p_lang or ''}|{p_datatype_id or 0}"
                        o_composite = f"{o_value}|{o_type}|{o_lang or ''}|{o_datatype_id or 0}"
                        g_composite = f"{g_value}|{g_type}|{g_lang or ''}|{g_datatype_id or 0}"
                        
                        s_uuid = uuid.uuid5(RDF_NAMESPACE, s_composite)
                        p_uuid = uuid.uuid5(RDF_NAMESPACE, p_composite)
                        o_uuid = uuid.uuid5(RDF_NAMESPACE, o_composite)
                        g_uuid = uuid.uuid5(RDF_NAMESPACE, g_composite)
                        
                        quad_uuids.append((s_uuid, p_uuid, o_uuid, g_uuid))
                    
                    self.logger.debug(f"Resolved {len(unique_terms)} unique terms from {len(quads)} quads")
                
                # Step 2: Get table names
                table_prefix = PostgreSQLUtils.get_table_prefix(self.global_prefix, space_id)
                term_table_name = PostgreSQLUtils.get_table_name(self.global_prefix, space_id, "term")
                quad_table_name = PostgreSQLUtils.get_table_name(self.global_prefix, space_id, "rdf_quad")
                
                # Step 3: Use raw psycopg3 connection for UUID-based operations
                with self.get_connection() as conn:
                    conn.row_factory = psycopg.rows.dict_row
                    
                    # Step 4: Batch remove quads using UUIDs
                    with self.utils.time_operation("batch_quad_removal", f"removing quads from {len(quad_uuids)} candidates"):
                        removed_count = 0
                        batch_size = 1000
                        
                        for i in range(0, len(quad_uuids), batch_size):
                            batch_uuids = quad_uuids[i:i + batch_size]
                            
                            with self.utils.time_operation("quad_remove_batch", f"batch {i//batch_size + 1}, {len(batch_uuids)} quads"):
                                # Handle duplicate quads by counting instances and deleting exact number
                                from collections import Counter
                                quad_counts = Counter(batch_uuids)
                                
                                cursor = conn.cursor()
                                batch_removed = 0
                                
                                for (s_uuid, p_uuid, o_uuid, g_uuid), count in quad_counts.items():
                                    # Delete exactly 'count' instances of this quad using ctid
                                    delete_sql = f"""
                                        DELETE FROM {quad_table_name} 
                                        WHERE ctid IN (
                                            SELECT ctid FROM {quad_table_name}
                                            WHERE subject_uuid = %s AND predicate_uuid = %s 
                                                  AND object_uuid = %s AND context_uuid = %s
                                            LIMIT %s
                                        )
                                    """
                                    
                                    cursor.execute(delete_sql, [s_uuid, p_uuid, o_uuid, g_uuid, count])
                                    quad_removed = cursor.rowcount
                                    batch_removed += quad_removed
                                
                                removed_count += batch_removed
                                
                                self.logger.debug(f"Removed {batch_removed} quads in batch {i//batch_size + 1}")
                        
                        conn.commit()
                        
                        if removed_count > 0:
                            self.logger.info(f"🎉 SUCCESS: UUID batch removal completed - {removed_count} quads removed from space '{space_id}'")
                        else:
                            self.logger.debug(f"No matching quads found to remove from space '{space_id}'")
                        
                        return removed_count
                            
            except Exception as e:
                self.logger.error(f"Error removing RDF quads batch from space '{space_id}': {e}")
                import traceback
                self.logger.error(f"📋 Full traceback: {traceback.format_exc()}")
                return 0
    
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
        try:
            PostgreSQLUtils.validate_space_id(space_id)
            
            # Get table names using current structure
            table_names = self._get_table_names(space_id)
            namespace_table_name = table_names['namespace']
            
            self.logger.debug(f"Adding namespace '{prefix}' -> '{namespace_uri}' to space '{space_id}'")
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Check if prefix already exists
                cursor.execute(
                    f"SELECT namespace_id, namespace_uri FROM {namespace_table_name} WHERE prefix = %s",
                    (prefix,)
                )
                result = cursor.fetchone()
                
                if result:
                    namespace_id, existing_uri = result
                    # Update existing namespace URI if different
                    if existing_uri != namespace_uri:
                        cursor.execute(
                            f"UPDATE {namespace_table_name} SET namespace_uri = %s WHERE namespace_id = %s",
                            (namespace_uri, namespace_id)
                        )
                        conn.commit()
                        self.logger.info(f"Updated namespace '{prefix}' in space '{space_id}' to URI: {namespace_uri}")
                    else:
                        self.logger.debug(f"Namespace '{prefix}' already exists in space '{space_id}' with same URI")
                    return namespace_id
                
                # Insert new namespace
                cursor.execute(
                    f"INSERT INTO {namespace_table_name} (prefix, namespace_uri) VALUES (%s, %s) RETURNING namespace_id",
                    (prefix, namespace_uri)
                )
                result = cursor.fetchone()
                namespace_id = result[0] if result else None
                
                conn.commit()
                
                self.logger.info(f"Added namespace '{prefix}' -> '{namespace_uri}' to space '{space_id}' with ID: {namespace_id}")
                return namespace_id
                
        except Exception as e:
            self.logger.error(f"Error adding namespace to space '{space_id}': {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return None
    
    async def get_namespace_uri(self, space_id: str, prefix: str) -> Optional[str]:
        """
        Get namespace URI for a given prefix in a specific space.
        
        Args:
            space_id: Space identifier
            prefix: Namespace prefix to look up
            
        Returns:
            str: Namespace URI if found, None otherwise
        """
        try:
            PostgreSQLUtils.validate_space_id(space_id)
            
            # Get table names using current structure
            table_names = self._get_table_names(space_id)
            namespace_table_name = table_names['namespace']
            
            self.logger.debug(f"Looking up namespace URI for prefix '{prefix}' in space '{space_id}'")
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute(
                    f"SELECT namespace_uri FROM {namespace_table_name} WHERE prefix = %s",
                    (prefix,)
                )
                result = cursor.fetchone()
                
                if result:
                    namespace_uri = result[0]
                    self.logger.debug(f"Found namespace URI for '{prefix}' in space '{space_id}': {namespace_uri}")
                    return namespace_uri
                else:
                    self.logger.debug(f"No namespace found for prefix '{prefix}' in space '{space_id}'")
                    return None
                    
        except Exception as e:
            self.logger.error(f"Error getting namespace URI from space '{space_id}': {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return None
    
    async def list_namespaces(self, space_id: str) -> List[Dict[str, Any]]:
        """
        Get all namespace prefix mappings for a specific space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            list: List of namespace dictionaries with id, prefix, namespace_uri, created_time
        """
        try:
            PostgreSQLUtils.validate_space_id(space_id)
            
            # Get table names using current structure
            table_names = self._get_table_names(space_id)
            namespace_table_name = table_names['namespace']
            
            self.logger.debug(f"Listing all namespaces for space '{space_id}'")
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute(
                    f"SELECT namespace_id, prefix, namespace_uri, created_time FROM {namespace_table_name} ORDER BY prefix"
                )
                results = cursor.fetchall()
                
                namespaces = []
                for row in results:
                    namespace_id, prefix, namespace_uri, created_time = row
                    namespaces.append({
                        'namespace_id': namespace_id,
                        'prefix': prefix,
                        'namespace_uri': namespace_uri,
                        'created_time': created_time.isoformat() if created_time else None
                    })
                
                self.logger.debug(f"Retrieved {len(namespaces)} namespaces from space '{space_id}'")
                return namespaces
                
        except Exception as e:
            self.logger.error(f"Error listing namespaces from space '{space_id}': {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return []
    
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
        try:
            self.logger.debug(f"🔍 DEBUG: Starting quads() method for space_id='{space_id}', pattern={quad_pattern}")
            
            PostgreSQLUtils.validate_space_id(space_id)
            self.logger.debug(f"🔍 DEBUG: Space ID validation passed")
            
            # Extract pattern components
            subject, predicate, obj, graph = quad_pattern
            self.logger.debug(f"🔍 DEBUG: Pattern components - s:{subject}, p:{predicate}, o:{obj}, g:{graph}")
            
            # Get table names (with unlogged suffix if needed)
            table_names = self._get_table_names(space_id)
            if self.use_unlogged:
                table_names = {key: f"{value}_unlogged" for key, value in table_names.items()}
            term_table = table_names['term']
            quad_table = table_names['rdf_quad']
            self.logger.debug(f"🔍 DEBUG: Table names - term:{term_table}, quad:{quad_table}")
            
            with self.utils.time_operation("quads_query", f"pattern {quad_pattern} in space '{space_id}'"):
                self.logger.debug(f"🔍 DEBUG: Starting time operation and connection")
                with self.get_connection() as conn:
                    self.logger.debug(f"🔍 DEBUG: Got connection: {type(conn)}")
                    with conn.cursor() as cursor:
                        self.logger.debug(f"🔍 DEBUG: Got cursor: {type(cursor)}")
                        # Use UUID-based schema column names
                        join_columns = {
                            'subject': ('quad.subject_uuid', 's_term.term_uuid'),
                            'predicate': ('quad.predicate_uuid', 'p_term.term_uuid'),
                            'object': ('quad.object_uuid', 'o_term.term_uuid'),
                            'context': ('quad.context_uuid', 'c_term.term_uuid')
                        }
                        
                        # Build the SQL query with appropriate joins
                        base_query = f"""
                        SELECT 
                            s_term.term_text as subject_text,
                            s_term.term_type as subject_type,
                            s_term.lang as subject_lang,
                            s_term.datatype_id as subject_datatype_id,
                            
                            p_term.term_text as predicate_text,
                            p_term.term_type as predicate_type,
                            
                            o_term.term_text as object_text,
                            o_term.term_type as object_type,
                            o_term.lang as object_lang,
                            o_term.datatype_id as object_datatype_id,
                            
                            c_term.term_text as context_text,
                            c_term.term_type as context_type
                        FROM {quad_table} quad
                        JOIN {term_table} s_term ON {join_columns['subject'][0]} = {join_columns['subject'][1]}
                        JOIN {term_table} p_term ON {join_columns['predicate'][0]} = {join_columns['predicate'][1]}
                        JOIN {term_table} o_term ON {join_columns['object'][0]} = {join_columns['object'][1]}
                        JOIN {term_table} c_term ON {join_columns['context'][0]} = {join_columns['context'][1]}
                        """
                    
                        # Build WHERE conditions and parameters
                        where_conditions = []
                        params = []
                        
                        # Helper function to check if a pattern element is a variable/unbound
                        def is_unbound(element):
                            return element is None or (hasattr(element, '__class__') and 
                                                     element.__class__.__name__ == 'Variable')
                        
                        # Helper function to check if a pattern element is a REGEXTerm
                        def is_regex_term(element):
                            return isinstance(element, REGEXTerm)
                        
                        # Helper function to convert RDFLib term to database term info
                        def term_to_db_info(term):
                            if isinstance(term, URIRef):
                                return str(term), 'U', None, None
                            elif isinstance(term, Literal):
                                # Safely access language attribute
                                lang = term.language if hasattr(term, 'language') else None
                                return str(term), 'L', lang, None  # TODO: handle datatype
                            elif isinstance(term, BNode):
                                return str(term), 'B', None, None
                            else:
                                # Assume it's a string representation
                                return str(term), 'U', None, None  # Default to URI
                        
                        # Add subject condition
                        if not is_unbound(subject):
                            if is_regex_term(subject):
                                # Use PostgreSQL regex matching for REGEXTerm
                                where_conditions.append("s_term.term_text ~ %s")
                                params.append(subject.pattern)
                                self.logger.debug(f"Added regex condition for subject: {subject.pattern}")
                            else:
                                s_text, s_type, s_lang, s_datatype = term_to_db_info(subject)
                                where_conditions.append("s_term.term_text = %s AND s_term.term_type = %s")
                                params.extend([s_text, s_type])
                                if s_lang:
                                    where_conditions.append("s_term.lang = %s")
                                    params.append(s_lang)
                        
                        # Add predicate condition
                        if not is_unbound(predicate):
                            if is_regex_term(predicate):
                                # Use PostgreSQL regex matching for REGEXTerm
                                where_conditions.append("p_term.term_text ~ %s")
                                params.append(predicate.pattern)
                                self.logger.debug(f"Added regex condition for predicate: {predicate.pattern}")
                            else:
                                p_text, p_type, p_lang, p_datatype = term_to_db_info(predicate)
                                where_conditions.append("p_term.term_text = %s AND p_term.term_type = %s")
                                params.extend([p_text, p_type])
                        
                        # Add object condition
                        if not is_unbound(obj):
                            if is_regex_term(obj):
                                # Use PostgreSQL regex matching for REGEXTerm
                                where_conditions.append("o_term.term_text ~ %s")
                                params.append(obj.pattern)
                                self.logger.debug(f"Added regex condition for object: {obj.pattern}")
                            else:
                                o_text, o_type, o_lang, o_datatype = term_to_db_info(obj)
                                where_conditions.append("o_term.term_text = %s AND o_term.term_type = %s")
                                params.extend([o_text, o_type])
                                if o_lang:
                                    where_conditions.append("o_term.lang = %s")
                                    params.append(o_lang)
                        
                        # Add context condition
                        if not is_unbound(graph):
                            if is_regex_term(graph):
                                # Use PostgreSQL regex matching for REGEXTerm
                                where_conditions.append("c_term.term_text ~ %s")
                                params.append(graph.pattern)
                                self.logger.debug(f"Added regex condition for context: {graph.pattern}")
                            else:
                                c_text, c_type, c_lang, c_datatype = term_to_db_info(graph)
                                where_conditions.append("c_term.term_text = %s AND c_term.term_type = %s")
                                params.extend([c_text, c_type])
                        
                        # Build final query
                        if where_conditions:
                            query = base_query + " WHERE " + " AND ".join([f"({cond})" for cond in where_conditions])
                        else:
                            query = base_query
                        
                        # Debug logging with more detail
                        self.logger.info(f"🔍 QUADS QUERY: About to execute query on {len(table_names)} tables")
                        self.logger.info(f"📝 Full query: {query}")
                        self.logger.info(f"📊 Parameters: {params}")
                        self.logger.info(f"🎯 Pattern: {quad_pattern}")
                        
                        # Use server-side cursor for true streaming performance
                        self.logger.info(f"⏰ Starting server-side cursor setup...")
                        import time
                        start_time = time.time()
                        
                        # Generate unique cursor name
                        import uuid
                        cursor_name = f"quads_cursor_{uuid.uuid4().hex[:8]}"
                        
                        try:
                            # Declare server-side cursor
                            declare_sql = f"DECLARE {cursor_name} CURSOR FOR {query}"
                            self.logger.debug(f"🔍 DEBUG: Declaring cursor: {declare_sql}")
                            cursor.execute(declare_sql, params)
                            
                            setup_time = time.time() - start_time
                            self.logger.info(f"✅ Server-side cursor declared in {setup_time:.3f}s")
                            
                            # Convert database terms back to RDFLib terms
                            def db_to_rdflib_term(text, term_type, lang=None, datatype_id=None):
                                if term_type == 'U':
                                    return URIRef(text)
                                elif term_type == 'L':
                                    if lang:
                                        return Literal(text, lang=lang)
                                    else:
                                        return Literal(text)  # TODO: handle datatype
                                elif term_type == 'B':
                                    return BNode(text)
                                else:
                                    return URIRef(text)  # Default fallback
                            
                            # Use server-side cursor paging for immediate streaming
                            self.logger.debug(f"🔍 DEBUG: Starting server-side cursor paging...")
                            page_size = 1000  # Fetch pages of 1000 rows
                            total_yielded = 0
                            
                            while True:
                                # Fetch next page from server-side cursor
                                fetch_sql = f"FETCH FORWARD {page_size} FROM {cursor_name}"
                                cursor.execute(fetch_sql)
                                page_results = cursor.fetchall()
                                
                                if not page_results:
                                    break  # No more results
                                
                                self.logger.debug(f"🔍 DEBUG: Fetched page of {len(page_results)} rows from cursor")
                                
                                # Process and yield each row immediately
                                for row in page_results:
                                    total_yielded += 1
                                    
                                    # Build the quad (psycopg3 returns named results, access by column name)
                                    s = db_to_rdflib_term(row['subject_text'], row['subject_type'], row['subject_lang'], row['subject_datatype_id'])
                                    p = db_to_rdflib_term(row['predicate_text'], row['predicate_type'])
                                    o = db_to_rdflib_term(row['object_text'], row['object_type'], row['object_lang'], row['object_datatype_id'])
                                    c = db_to_rdflib_term(row['context_text'], row['context_type'])
                                    
                                    quad = (s, p, o, c)
                                    
                                    # Create context iterator
                                    def context_iter():
                                        yield c
                                    
                                    # Yield immediately for true streaming
                                    yield quad, context_iter
                                    
                                    # Log progress for large result sets
                                    if total_yielded % 50000 == 0:
                                        self.logger.info(f"🔍 DEBUG: Streamed {total_yielded:,} quads so far...")
                            
                            self.logger.info(f"✅ Completed server-side cursor streaming - yielded {total_yielded:,} total quads")
                            
                        except Exception as e:
                            execution_time = time.time() - start_time
                            self.logger.error(f"❌ Server-side cursor failed after {execution_time:.3f}s: {e}")
                            raise
                        finally:
                            # Always close the cursor
                            try:
                                cursor.execute(f"CLOSE {cursor_name}")
                                self.logger.debug(f"🔍 DEBUG: Closed server-side cursor {cursor_name}")
                            except Exception as e:
                                self.logger.warning(f"⚠️ Failed to close cursor {cursor_name}: {e}")
                        
        except Exception as e:
            self.logger.error(f"Error in quads query for space '{space_id}': {e}")
            self.logger.error(f"Exception type: {type(e)}")
            self.logger.error(f"Exception args: {e.args}")
            import traceback
            self.logger.error(f"Full traceback: {traceback.format_exc()}")
            # Return empty results for error case
            return
    
    def get_manager_info(self) -> Dict[str, Any]:
        """
        Get general information about this space manager.
        
        Returns:
            dict: Manager information
        """
        return {
            "global_prefix": self.global_prefix,
            "connected": self.connection_string is not None,
            "cached_spaces": list(self._table_cache.keys()),
            "cache_size": len(self._table_cache)
        }

