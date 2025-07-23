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
    
    def __init__(self, connection_string: str, global_prefix: str = "vitalgraph"):
        """
        Initialize PostgreSQL space implementation.
        
        Args:
            connection_string: PostgreSQL connection string
            global_prefix: Global table prefix for all spaces (default: 'vitalgraph')
        """
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.connection_string = connection_string
        self.global_prefix = global_prefix
        
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
        Generate CREATE TABLE SQL statements for all RDF space tables.
        
        Args:
            space_id: Space identifier
            
        Returns:
            dict: Dictionary of CREATE TABLE SQL statements keyed by base name
        """
        PostgreSQLUtils.validate_space_id(space_id)
        
        table_names = self._get_table_names(space_id)
        table_prefix = PostgreSQLUtils.get_table_prefix(self.global_prefix, space_id)
        
        sql_statements = {}
        
        # Terms dictionary table - stores all RDF terms for this space
        sql_statements['term'] = f"""
            CREATE TABLE {table_names['term']} (
                term_id BIGSERIAL PRIMARY KEY,
                term_text TEXT NOT NULL,
                term_type CHAR(1) NOT NULL CHECK (term_type IN ('U', 'L', 'B', 'G')),
                lang VARCHAR(20),
                datatype_id BIGINT,
                created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (term_text, term_type, lang, datatype_id)
            );
            
            CREATE INDEX idx_{table_prefix}term_text ON {table_names['term']} (term_text);
            CREATE INDEX idx_{table_prefix}term_type ON {table_names['term']} (term_type);
            CREATE INDEX idx_{table_prefix}term_text_type ON {table_names['term']} (term_text, term_type);
            CREATE INDEX idx_{table_prefix}term_text_gin_trgm ON {table_names['term']} USING gin (term_text gin_trgm_ops);
            CREATE INDEX idx_{table_prefix}term_text_gist_trgm ON {table_names['term']} USING gist (term_text gist_trgm_ops);
        """
        
        # Namespace table - RDF namespace prefix mappings for this space
        sql_statements['namespace'] = f"""
            CREATE TABLE {table_names['namespace']} (
                namespace_id BIGSERIAL PRIMARY KEY,
                prefix VARCHAR(50) NOT NULL,
                namespace_uri TEXT NOT NULL,
                created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (prefix)
            );
        """
        
        # Graph table - Graph (context) URIs and metadata for this space
        sql_statements['graph'] = f"""
            CREATE TABLE {table_names['graph']} (
                graph_id BIGSERIAL PRIMARY KEY,
                graph_uri_id BIGINT NOT NULL REFERENCES {table_names['term']}(term_id),
                graph_name VARCHAR(255),
                created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                triple_count BIGINT DEFAULT 0,
                UNIQUE (graph_uri_id)
            );
        """
        
        # RDF Quad table - stores RDF quads with term references for this space
        sql_statements['rdf_quad'] = f"""
            CREATE TABLE {table_names['rdf_quad']} (
                quad_id BIGSERIAL PRIMARY KEY,
                subject_id BIGINT NOT NULL REFERENCES {table_names['term']}(term_id),
                predicate_id BIGINT NOT NULL REFERENCES {table_names['term']}(term_id),
                object_id BIGINT NOT NULL REFERENCES {table_names['term']}(term_id),
                context_id BIGINT NOT NULL REFERENCES {table_names['term']}(term_id),
                created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (subject_id, predicate_id, object_id, context_id)
            );
            
            CREATE INDEX idx_{table_prefix}quad_spoc ON {table_names['rdf_quad']} (subject_id, predicate_id, object_id, context_id);
            CREATE INDEX idx_{table_prefix}quad_subject ON {table_names['rdf_quad']} (subject_id);
            CREATE INDEX idx_{table_prefix}quad_predicate ON {table_names['rdf_quad']} (predicate_id);
            CREATE INDEX idx_{table_prefix}quad_object ON {table_names['rdf_quad']} (object_id);
            CREATE INDEX idx_{table_prefix}quad_context ON {table_names['rdf_quad']} (context_id);
        """
        
        return sql_statements
    
    def _get_create_table_sql_minimal(self, space_id: str) -> Dict[str, str]:
        """
        Generate CREATE TABLE SQL statements with minimal indexes for bulk loading.
        Only creates essential constraints (PRIMARY KEY, UNIQUE, FOREIGN KEY).
        
        Args:
            space_id: Space identifier
            
        Returns:
            dict: Dictionary of CREATE TABLE SQL statements with minimal indexes
        """
        PostgreSQLUtils.validate_space_id(space_id)
        
        table_names = self._get_table_names(space_id)
        table_prefix = PostgreSQLUtils.get_table_prefix(self.global_prefix, space_id)
        
        sql_statements = {}
        
        # Terms dictionary table - minimal indexes for bulk loading
        sql_statements['term'] = f"""
            CREATE TABLE {table_names['term']} (
                term_id BIGSERIAL PRIMARY KEY,
                term_text TEXT NOT NULL,
                term_type CHAR(1) NOT NULL CHECK (term_type IN ('U', 'L', 'B', 'G')),
                lang VARCHAR(20),
                datatype_id BIGINT,
                created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (term_text, term_type, lang, datatype_id)
            );
        """
        
        # Namespace table - no additional indexes needed
        sql_statements['namespace'] = f"""
            CREATE TABLE {table_names['namespace']} (
                namespace_id BIGSERIAL PRIMARY KEY,
                prefix VARCHAR(50) NOT NULL,
                namespace_uri TEXT NOT NULL,
                created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (prefix)
            );
        """
        
        # Graph table - minimal indexes
        sql_statements['graph'] = f"""
            CREATE TABLE {table_names['graph']} (
                graph_id BIGSERIAL PRIMARY KEY,
                graph_uri_id BIGINT NOT NULL REFERENCES {table_names['term']}(term_id),
                graph_name VARCHAR(255),
                created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                triple_count BIGINT DEFAULT 0,
                UNIQUE (graph_uri_id)
            );
        """
        
        # RDF Quad table - only essential constraints, no performance indexes
        sql_statements['rdf_quad'] = f"""
            CREATE TABLE {table_names['rdf_quad']} (
                quad_id BIGSERIAL PRIMARY KEY,
                subject_id BIGINT NOT NULL REFERENCES {table_names['term']}(term_id),
                predicate_id BIGINT NOT NULL REFERENCES {table_names['term']}(term_id),
                object_id BIGINT NOT NULL REFERENCES {table_names['term']}(term_id),
                context_id BIGINT NOT NULL REFERENCES {table_names['term']}(term_id),
                created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (subject_id, predicate_id, object_id, context_id)
            );
        """
        
        return sql_statements
    
    def _get_create_table_sql_unlogged(self, space_id: str) -> Dict[str, str]:
        """
        Generate CREATE UNLOGGED TABLE SQL statements for ultra-fast bulk loading.
        Unlogged tables have no WAL overhead but are not crash-safe.
        
        Args:
            space_id: Space identifier
            
        Returns:
            dict: Dictionary of CREATE UNLOGGED TABLE SQL statements
        """
        PostgreSQLUtils.validate_space_id(space_id)
        
        table_names = self._get_table_names(space_id)
        # Add _unlogged suffix to table names
        unlogged_table_names = {
            key: f"{value}_unlogged" for key, value in table_names.items()
        }
        
        sql_statements = {}
        
        # Unlogged terms table - no constraints for maximum speed
        sql_statements['term'] = f"""
            CREATE UNLOGGED TABLE {unlogged_table_names['term']} (
                term_id BIGSERIAL,
                term_text TEXT NOT NULL,
                term_type CHAR(1) NOT NULL,
                lang VARCHAR(20),
                datatype_id BIGINT,
                created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """
        
        # Unlogged quad table - no constraints for maximum speed
        sql_statements['rdf_quad'] = f"""
            CREATE UNLOGGED TABLE {unlogged_table_names['rdf_quad']} (
                quad_id BIGSERIAL,
                subject_id BIGINT NOT NULL,
                predicate_id BIGINT NOT NULL,
                object_id BIGINT NOT NULL,
                context_id BIGINT NOT NULL,
                created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """
        
        return sql_statements
    
    def _get_performance_indexes_sql(self, space_id: str, use_unlogged: bool = False) -> Dict[str, List[str]]:
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
        if use_unlogged:
            table_names = {key: f"{value}_unlogged" for key, value in table_names.items()}
        table_prefix = PostgreSQLUtils.get_table_prefix(self.global_prefix, space_id)
        
        indexes = {}
        
        # Term table performance indexes
        indexes['term'] = [
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}term_text ON {table_names['term']} (term_text);",
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}term_type ON {table_names['term']} (term_type);",
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}term_text_type ON {table_names['term']} (term_text, term_type);",
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}term_text_gin_trgm ON {table_names['term']} USING gin (term_text gin_trgm_ops);",
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}term_text_gist_trgm ON {table_names['term']} USING gist (term_text gist_trgm_ops);"
        ]
        
        # Quad table performance indexes - SPARQL optimized
        indexes['rdf_quad'] = [
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}quad_spoc ON {table_names['rdf_quad']} (subject_id, predicate_id, object_id, context_id);",
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}quad_subject ON {table_names['rdf_quad']} (subject_id);",
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}quad_predicate ON {table_names['rdf_quad']} (predicate_id);",
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}quad_object ON {table_names['rdf_quad']} (object_id);",
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}quad_context ON {table_names['rdf_quad']} (context_id);"
        ]
        
        return indexes
        
        # Terms dictionary table - stores all RDF terms for this space
        tables['term'] = Table(
            term_table_name,
            self.metadata,
            Column('term_id', BigInteger, primary_key=True, autoincrement=True),
            Column('term_text', Text, nullable=False),
            Column('term_type', CHAR(1), nullable=False),  # 'U'=URI, 'L'=Literal, 'B'=BlankNode, 'G'=Graph
            Column('lang', String(20), nullable=True),      # Language tag for literals
            Column('datatype_id', BigInteger, nullable=True), # Reference to datatype term
            Column('created_time', DateTime, default=datetime.utcnow),
            
            # Indexes for performance
            Index(f"idx_{table_prefix}term_text", 'term_text'),
            Index(f"idx_{table_prefix}term_type", 'term_type'),
            Index(f"idx_{table_prefix}term_text_type", 'term_text', 'term_type'),
            
            # Text search indexes for regex and full-text search optimization
            # GIN index with pg_trgm for trigram-based regex matching
            Index(f"idx_{table_prefix}term_text_gin_trgm", 'term_text', 
                  postgresql_using='gin', postgresql_ops={'term_text': 'gin_trgm_ops'}),
            
            # GiST index for additional text search capabilities
            Index(f"idx_{table_prefix}term_text_gist_trgm", 'term_text',
                  postgresql_using='gist', postgresql_ops={'term_text': 'gist_trgm_ops'}),
            
            # Constraints
            CheckConstraint("term_type IN ('U', 'L', 'B', 'G')", name=f"ck_{table_prefix}term_type"),
            UniqueConstraint('term_text', 'term_type', 'lang', 'datatype_id', 
                           name=f"uq_{table_prefix}term_unique")
        )
        
        # Namespace table - RDF namespace prefix mappings for this space
        tables['namespace'] = Table(
            namespace_table_name,
            self.metadata,
            Column('namespace_id', BigInteger, primary_key=True, autoincrement=True),
            Column('prefix', String(50), nullable=False),
            Column('namespace_uri', Text, nullable=False),
            Column('created_time', DateTime, default=datetime.utcnow),
            
            # Unique constraint on prefix within this space
            UniqueConstraint('prefix', name=f"uq_{table_prefix}namespace_prefix")
        )
        
        # Graph table - Graph (context) URIs and metadata for this space
        tables['graph'] = Table(
            graph_table_name,
            self.metadata,
            Column('graph_id', BigInteger, primary_key=True, autoincrement=True),
            Column('graph_uri_id', BigInteger, 
                   ForeignKey(f"{term_table_name}.term_id"), 
                   nullable=False),
            Column('graph_name', String(255), nullable=True),  # Optional human-readable name
            Column('created_time', DateTime, default=datetime.utcnow),
            Column('updated_time', DateTime, default=datetime.utcnow, onupdate=datetime.utcnow),
            Column('triple_count', BigInteger, default=0),     # Cached count for performance
            
            # Unique constraint on graph URI within this space
            UniqueConstraint('graph_uri_id', name=f"uq_{table_prefix}graph_uri")
        )
        
        # RDF Quad table - stores RDF quads with term references for this space
        tables['rdf_quad'] = Table(
            quad_table_name,
            self.metadata,
            Column('quad_id', BigInteger, primary_key=True, autoincrement=True),
            Column('subject_id', BigInteger, 
                   ForeignKey(f"{term_table_name}.term_id"), 
                   nullable=False),
            Column('predicate_id', BigInteger, 
                   ForeignKey(f"{term_table_name}.term_id"), 
                   nullable=False),
            Column('object_id', BigInteger, 
                   ForeignKey(f"{term_table_name}.term_id"), 
                   nullable=False),
            Column('context_id', BigInteger, 
                   ForeignKey(f"{term_table_name}.term_id"), 
                   nullable=False),
            Column('created_time', DateTime, default=datetime.utcnow),
            
            # Indexes for SPARQL query performance
            Index(f"idx_{table_prefix}quad_spoc", 'subject_id', 'predicate_id', 'object_id', 'context_id'),
            Index(f"idx_{table_prefix}quad_pocs", 'predicate_id', 'object_id', 'context_id', 'subject_id'),
            Index(f"idx_{table_prefix}quad_ocsp", 'object_id', 'context_id', 'subject_id', 'predicate_id'),
            Index(f"idx_{table_prefix}quad_cspo", 'context_id', 'subject_id', 'predicate_id', 'object_id'),
            Index(f"idx_{table_prefix}quad_context", 'context_id'),
            
            # Unique constraint to prevent duplicate quads within this space
            UniqueConstraint('subject_id', 'predicate_id', 'object_id', 'context_id',
                           name=f"uq_{table_prefix}quad_unique")
        )
        
        # Cache the tables for this space
        self._table_cache[space_id] = tables
        
        self.logger.debug(f"Defined {len(tables)} tables for space '{space_id}' with prefix '{table_prefix}'")
        return tables
    
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
    
    async def create_space_tables(self, space_id: str) -> bool:
        """
        Create all RDF tables for a specific space using pure psycopg3.
        
        This method creates the complete table structure for an RDF space including:
        - Term table with text search indexes for efficient regex matching
        - Namespace table for prefix mappings
        - Graph table for context/graph metadata
        - RDF quad table with optimized indexes for SPARQL queries
        
        Args:
            space_id: Space identifier
            
        Returns:
            bool: True if tables were created successfully, False otherwise
        """
        try:
            # Ensure text search extensions are available
            await self._ensure_text_search_extensions()
            
            # Get SQL DDL statements for this space
            sql_statements = self._get_create_table_sql(space_id)
            
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Create tables in dependency order: term -> namespace, graph, quad
                    creation_order = ['term', 'namespace', 'graph', 'rdf_quad']
                    
                    for table_name in creation_order:
                        if table_name in sql_statements:
                            self.logger.debug(f"Creating table: {table_name}")
                            # Execute the DDL statement (may contain multiple statements)
                            for statement in sql_statements[table_name].strip().split(';'):
                                statement = statement.strip()
                                if statement:  # Skip empty statements
                                    cursor.execute(statement)
                    
                    conn.commit()
            
            self.logger.info(f"Successfully created {len(sql_statements)} tables for space '{space_id}'")
            return True
            
        except Exception as e:
            self.logger.error(f"Error creating tables for space '{space_id}': {e}")
            return False
    
    def create_space_tables_for_bulk_loading(self, space_id: str, use_unlogged: bool = False) -> bool:
        """
        Create RDF tables optimized for bulk loading with minimal indexes.
        
        Args:
            space_id: Space identifier
            use_unlogged: If True, create unlogged tables for maximum speed (not crash-safe)
            
        Returns:
            bool: True if tables created successfully, False otherwise
        """
        try:
            PostgreSQLUtils.validate_space_id(space_id)
            
            self.logger.info(f"Creating bulk-loading optimized RDF tables for space '{space_id}' (unlogged={use_unlogged})")
            
            with self.utils.time_operation("create_bulk_tables", f"space '{space_id}'"):
                with self.get_connection() as conn:
                    with conn.cursor() as cursor:
                        # If using unlogged tables, drop any existing unlogged tables first
                        if use_unlogged:
                            self.logger.debug(f"Checking for existing unlogged tables to clean up...")
                            table_names = self._get_table_names(space_id)
                            unlogged_table_names = [f"{name}_unlogged" for name in table_names.values()]
                            
                            # Drop tables in reverse dependency order
                            for table_name in reversed(unlogged_table_names):
                                try:
                                    cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
                                    self.logger.debug(f"Dropped existing unlogged table: {table_name}")
                                except psycopg.Error as e:
                                    self.logger.debug(f"No existing table to drop: {table_name} ({e})")
                            
                            conn.commit()
                        
                        # Get appropriate SQL statements
                        if use_unlogged:
                            sql_statements = self._get_create_table_sql_unlogged(space_id)
                            self.logger.info(f"Using UNLOGGED tables for maximum bulk loading speed")
                        else:
                            sql_statements = self._get_create_table_sql_minimal(space_id)
                            self.logger.info(f"Using minimal indexes for optimized bulk loading")
                        
                        # Create tables in dependency order
                        table_order = ['term', 'namespace', 'graph', 'rdf_quad']
                        created_tables = []
                        
                        for table_name in table_order:
                            if table_name in sql_statements:
                                self.logger.debug(f"Creating {table_name} table...")
                                for statement in sql_statements[table_name].strip().split(';'):
                                    statement = statement.strip()
                                    if statement:  # Skip empty statements
                                        cursor.execute(statement)
                                created_tables.append(table_name)
                        
                        conn.commit()
                        self.logger.info(f"Successfully created {len(created_tables)} bulk-loading tables for space '{space_id}': {created_tables}")
            
            # Cache table definitions
            self._table_cache[space_id] = self._get_table_names(space_id)
            return True
            
        except psycopg.Error as e:
            self.logger.error(f"Database error creating bulk-loading tables for space '{space_id}': {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error creating bulk-loading tables for space '{space_id}': {e}")
            return False
    
    def build_performance_indexes(self, space_id: str, concurrent: bool = True, use_unlogged: bool = False) -> bool:
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
                        indexes_sql = self._get_performance_indexes_sql(space_id, use_unlogged=use_unlogged)
                        
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
        except Exception as e:
            self.logger.error(f"Unexpected error building indexes for space '{space_id}': {e}")
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
            base_names = ['rdf_quad', 'graph', 'namespace', 'term']  # Drop in reverse dependency order
            
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    dropped_tables = []
                    for base_name in base_names:
                        table_name = table_names[base_name]
                        try:
                            cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
                            dropped_tables.append(table_name)
                            self.logger.debug(f"Dropped table {table_name}")
                        except Exception as e:
                            self.logger.warning(f"Could not drop table {table_name}: {e}")
                    
                    conn.commit()
                    self.logger.info(f"Successfully deleted {len(dropped_tables)} tables for space '{space_id}': {dropped_tables}")
            
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
            
            # Check if at least the term table exists for this space
            term_table_name = PostgreSQLUtils.get_table_name(self.global_prefix, space_id, 'term')
            
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = %s)",
                        (term_table_name,)
                    )
                    exists = cursor.fetchone()[0]
            
            self.logger.debug(f"Space '{space_id}' exists: {exists}")
            return exists
            
        except Exception as e:
            self.logger.error(f"Error checking space existence: {e}")
            return False
    
    async def list_spaces(self) -> List[str]:
        """
        List all spaces that have tables in the database.
        
        Returns:
            list: List of space IDs
        """
        try:
            spaces = set()
            
            with self.engine.connect() as conn:
                # Query for tables matching our naming pattern
                result = conn.execute(text(
                    "SELECT table_name FROM information_schema.tables WHERE table_name LIKE :pattern"
                ), {"pattern": f"{self.global_prefix}__%__term"})
                
                for row in result:
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
            
            if info["exists"]:
                # Get table information
                base_names = ['term', 'namespace', 'graph', 'rdf_quad']
                
                for base_name in base_names:
                    table_name = PostgreSQLUtils.get_table_name(self.global_prefix, space_id, base_name)
                    
                    table_info = {
                        "full_name": table_name,
                        "exists": True,  # We know space exists
                        "row_count": 0
                    }
                    
                    # Get row count
                    try:
                        with self.engine.connect() as conn:
                            result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                            table_info["row_count"] = result.scalar()
                    except Exception as e:
                        self.logger.warning(f"Could not get row count for {table_name}: {e}")
                    
                    info["tables"][base_name] = table_info
            
            return info
            
        except Exception as e:
            self.logger.error(f"Error getting space info: {e}")
            return {"error": str(e)}
    
    # Term management methods
    async def add_term(self, space_id: str, term_text: str, term_type: str, 
                      lang: Optional[str] = None, datatype_id: Optional[int] = None) -> Optional[int]:
        """
        Add a term to the terms dictionary for a specific space.
        
        Args:
            space_id: Space identifier
            term_text: The term text (URI, literal value, etc.)
            term_type: Term type ('U'=URI, 'L'=Literal, 'B'=BlankNode, 'G'=Graph)
            lang: Language tag for literals
            datatype_id: Reference to datatype term ID
            
        Returns:
            int: Term ID if successful, None otherwise
        """
        try:
            PostgreSQLUtils.validate_space_id(space_id)
            
            tables = self._define_space_tables(space_id)
            term_table = tables['term']
            
            with self.engine.connect() as conn:
                # Check if term already exists
                select_stmt = term_table.select().where(
                    (term_table.c.term_text == term_text) &
                    (term_table.c.term_type == term_type) &
                    (term_table.c.lang == lang) &
                    (term_table.c.datatype_id == datatype_id)
                )
                result = conn.execute(select_stmt).fetchone()
                
                if result:
                    self.logger.debug(f"Term already exists in space '{space_id}' with ID: {result.term_id}")
                    return result.term_id
                
                # Insert new term
                insert_stmt = term_table.insert().values(
                    term_text=term_text,
                    term_type=term_type,
                    lang=lang,
                    datatype_id=datatype_id
                )
                result = conn.execute(insert_stmt)
                conn.commit()
                
                term_id = result.inserted_primary_key[0]
                self.logger.debug(f"Added term '{term_text}' to space '{space_id}' with ID: {term_id}")
                return term_id
                
        except Exception as e:
            self.logger.error(f"Error adding term to space '{space_id}': {e}")
            return None
    
    async def get_term_id(self, space_id: str, term_text: str, term_type: str, 
                         lang: Optional[str] = None, datatype_id: Optional[int] = None) -> Optional[int]:
        """
        Get term ID for existing term in a specific space.
        
        Args:
            space_id: Space identifier
            term_text: The term text
            term_type: Term type
            lang: Language tag
            datatype_id: Datatype term ID
            
        Returns:
            int: Term ID if found, None otherwise
        """
        try:
            PostgreSQLUtils.validate_space_id(space_id)
            
            tables = self._define_space_tables(space_id)
            term_table = tables['term']
            
            with self.engine.connect() as conn:
                select_stmt = term_table.select().where(
                    (term_table.c.term_text == term_text) &
                    (term_table.c.term_type == term_type) &
                    (term_table.c.lang == lang) &
                    (term_table.c.datatype_id == datatype_id)
                )
                result = conn.execute(select_stmt).fetchone()
                
                return result.term_id if result else None
                
        except Exception as e:
            self.logger.error(f"Error getting term ID from space '{space_id}': {e}")
            return None
    
    # Quad management methods
    async def add_quad(self, space_id: str, subject_id: int, predicate_id: int, 
                      object_id: int, context_id: int) -> bool:
        """
        Add an RDF quad to a specific space.
        
        Args:
            space_id: Space identifier
            subject_id: Subject term ID
            predicate_id: Predicate term ID
            object_id: Object term ID
            context_id: Context (graph) term ID
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            PostgreSQLUtils.validate_space_id(space_id)
            
            tables = self._define_space_tables(space_id)
            quad_table = tables['rdf_quad']
            
            with self.engine.connect() as conn:
                # Check if quad already exists
                select_stmt = quad_table.select().where(
                    (quad_table.c.subject_id == subject_id) &
                    (quad_table.c.predicate_id == predicate_id) &
                    (quad_table.c.object_id == object_id) &
                    (quad_table.c.context_id == context_id)
                )
                result = conn.execute(select_stmt).fetchone()
                
                if result:
                    self.logger.debug(f"Quad already exists in space '{space_id}' with ID: {result.quad_id}")
                    return True
                
                # Insert new quad
                insert_stmt = quad_table.insert().values(
                    subject_id=subject_id,
                    predicate_id=predicate_id,
                    object_id=object_id,
                    context_id=context_id
                )
                result = conn.execute(insert_stmt)
                conn.commit()
                
                quad_id = result.inserted_primary_key[0]
                self.logger.debug(f"Added quad to space '{space_id}' with ID: {quad_id}")
                return True
                
        except Exception as e:
            self.logger.error(f"Error adding quad to space '{space_id}': {e}")
            return False
    
    async def get_quad_count(self, space_id: str, context_id: Optional[int] = None) -> int:
        """
        Get count of quads in a specific space, optionally filtered by context.
        
        Args:
            space_id: Space identifier
            context_id: Optional context ID to filter by
            
        Returns:
            int: Number of quads
        """
        try:
            PostgreSQLUtils.validate_space_id(space_id)
            
            tables = self._define_space_tables(space_id)
            quad_table = tables['rdf_quad']
            
            with self.engine.connect() as conn:
                if context_id:
                    select_stmt = quad_table.select().where(quad_table.c.context_id == context_id)
                    result = conn.execute(select_stmt)
                    return len(result.fetchall())
                else:
                    result = conn.execute(text(f"SELECT COUNT(*) FROM {quad_table.name}"))
                    return result.scalar()
                    
        except Exception as e:
            self.logger.error(f"Error getting quad count from space '{space_id}': {e}")
            return 0
    
    async def remove_quad(self, space_id: str, subject_id: int, predicate_id: int, object_id: int, context_id: int) -> bool:
        """
        Remove a single RDF quad from a specific space.
        
        Following RDFLib pattern: removes only one instance of the matching quad,
        not all instances. If multiple identical quads exist, only one is removed.
        
        Args:
            space_id: Space identifier
            subject_id: Subject term ID
            predicate_id: Predicate term ID
            object_id: Object term ID
            context_id: Context (graph) term ID
            
        Returns:
            bool: True if a quad was removed, False if no matching quad found
        """
        try:
            PostgreSQLUtils.validate_space_id(space_id)
            
            tables = self._define_space_tables(space_id)
            quad_table = tables['rdf_quad']
            
            with self.engine.connect() as conn:
                # Find the first matching quad (LIMIT 1 for single instance removal)
                select_stmt = quad_table.select().where(
                    (quad_table.c.subject_id == subject_id) &
                    (quad_table.c.predicate_id == predicate_id) &
                    (quad_table.c.object_id == object_id) &
                    (quad_table.c.context_id == context_id)
                ).limit(1)
                
                result = conn.execute(select_stmt).fetchone()
                
                if not result:
                    self.logger.debug(f"No matching quad found to remove from space '{space_id}'")
                    return False
                
                # Delete the specific quad by its ID (ensures only one instance is removed)
                delete_stmt = quad_table.delete().where(
                    quad_table.c.quad_id == result.quad_id
                )
                conn.execute(delete_stmt)
                conn.commit()
                
                self.logger.debug(f"Removed quad with ID {result.quad_id} from space '{space_id}'")
                return True
                
        except Exception as e:
            self.logger.error(f"Error removing quad from space '{space_id}': {e}")
            return False
    

    
    async def add_rdf_quad(self, space_id: str, quad: Union[tuple, list], s=None, p=None, o=None, g=None) -> bool:
        """
        Add an RDF quad to a specific space by converting RDF values to terms first.
        
        This function automatically determines term types from the RDF values and handles
        term conversion internally. It converts the subject, predicate, object, and graph
        values to term IDs and then calls add_quad().
        
        Args:
            space_id: Space identifier
            s: Subject value (URI, literal, or blank node)
            p: Predicate value (typically URI)
            o: Object value (URI, literal, or blank node)
            g: Graph/context value (typically URI)
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
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
            
            # Convert subject to term ID
            subject_id = await self.add_term(space_id, s_value, s_type, s_lang, s_datatype_id)
            if subject_id is None:
                self.logger.error(f"Failed to add subject term '{s}' to space '{space_id}'")
                return False
            
            # Convert predicate to term ID
            predicate_id = await self.add_term(space_id, p_value, p_type, p_lang, p_datatype_id)
            if predicate_id is None:
                self.logger.error(f"Failed to add predicate term '{p}' to space '{space_id}'")
                return False
            
            # Convert object to term ID
            object_id = await self.add_term(space_id, o_value, o_type, o_lang, o_datatype_id)
            if object_id is None:
                self.logger.error(f"Failed to add object term '{o}' to space '{space_id}'")
                return False
            
            # Convert graph to term ID
            graph_id = await self.add_term(space_id, g_value, g_type, g_lang, g_datatype_id)
            if graph_id is None:
                self.logger.error(f"Failed to add graph term '{g}' to space '{space_id}'")
                return False
            
            # Add the quad using term IDs
            success = await self.add_quad(space_id, subject_id, predicate_id, object_id, graph_id)
            
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
        Remove an RDF quad from a specific space by converting RDF values to terms first.
        
        This function automatically determines term types from the RDF values and handles
        term lookup internally. It looks up the term IDs for the subject, predicate, object,
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
            
            # Look up subject term ID
            subject_id = await self.get_term_id(space_id, s_value, s_type, s_lang, s_datatype_id)
            if subject_id is None:
                self.logger.debug(f"Subject term '{s}' not found in space '{space_id}'")
                return False
            
            # Look up predicate term ID
            predicate_id = await self.get_term_id(space_id, p_value, p_type, p_lang, p_datatype_id)
            if predicate_id is None:
                self.logger.debug(f"Predicate term '{p}' not found in space '{space_id}'")
                return False
            
            # Look up object term ID
            object_id = await self.get_term_id(space_id, o_value, o_type, o_lang, o_datatype_id)
            if object_id is None:
                self.logger.debug(f"Object term '{o}' not found in space '{space_id}'")
                return False
            
            # Look up graph term ID
            graph_id = await self.get_term_id(space_id, g_value, g_type, g_lang, g_datatype_id)
            if graph_id is None:
                self.logger.debug(f"Graph term '{g}' not found in space '{space_id}'")
                return False
            
            # Remove the quad using term IDs
            success = await self.remove_quad(space_id, subject_id, predicate_id, object_id, graph_id)
            
            if success:
                self.logger.debug(f"Successfully removed RDF quad from space '{space_id}'")
            else:
                self.logger.debug(f"No matching RDF quad found to remove from space '{space_id}'")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Error removing RDF quad from space '{space_id}': {e}")
            return False
    
    async def add_rdf_quads_batch(self, space_id: str, quads: List[tuple]) -> int:
        """
        AllowMultiple RDF quads to a specific space efficiently using batch operations.
        
        This function processes large batches (50,000+) efficiently by:
        1. Resolving all term types in batch
        2. Looking up existing terms in batch
        3. Inserting new terms in batch
{{ ... }}
        4. Inserting quads in batch
        
        Args:
            space_id: Space identifier
            quads: List of (s, p, o, g) tuples representing RDF quads
            
        Returns:
            int: Number of quads successfully added
        """
        if not quads:
            return 0
            
        with self.utils.time_operation("add_rdf_quads_batch", f"{len(quads)} quads to space '{space_id}'"):
            try:
                # Step 1: Resolve all term types and extract values
                with self.utils.time_operation("term_type_resolution", f"{len(quads)} quads"):
                    term_info = {}  # {(value, type, lang, datatype_id): set of quad_indices}
                    quad_terms = []  # [(s_info, p_info, o_info, g_info), ...]
                    
                    for i, (s, p, o, g) in enumerate(quads):
                        # Log progress for large batches
                        if i > 0 and i % 10000 == 0:
                            self.logger.debug(f"Processed {i}/{len(quads)} quads for type resolution")
                        
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
                        
                        # Store term info
                        s_info = (s_value, s_type, s_lang, s_datatype_id)
                        p_info = (p_value, p_type, p_lang, p_datatype_id)
                        o_info = (o_value, o_type, o_lang, o_datatype_id)
                        g_info = (g_value, g_type, g_lang, g_datatype_id)
                        
                        quad_terms.append((s_info, p_info, o_info, g_info))
                        
                        # Track unique terms
                        for term_info_item in [s_info, p_info, o_info, g_info]:
                            if term_info_item not in term_info:
                                term_info[term_info_item] = set()
                            term_info[term_info_item].add(i)
                    
                    self.logger.debug(f"Resolved {len(term_info)} unique terms from {len(quads)} quads")
                
                # Step 2: Batch lookup existing terms
                with self.utils.time_operation("batch_term_lookup", f"{len(term_info)} unique terms"):
                    tables = self._define_space_tables(space_id)
                    term_table = tables['term']
                    
                    term_id_map = {}  # {(value, type, lang, datatype_id): term_id}
                    
                    # Use a single connection for all database operations
                    with self.engine.connect() as conn:
                        # Build batch lookup query
                        unique_terms = list(term_info.keys())
                        batch_size = 1000  # Process in chunks to avoid query size limits
                        
                        self.logger.debug(f"Looking up {len(unique_terms)} terms in batches of {batch_size}")
                        
                        for i in range(0, len(unique_terms), batch_size):
                            batch_terms = unique_terms[i:i + batch_size]
                            
                            with self.utils.time_operation("term_lookup_batch", f"batch {i//batch_size + 1}, {len(batch_terms)} terms"):
                                # Create OR conditions for batch lookup
                                conditions = []
                                for value, term_type, lang, datatype_id in batch_terms:
                                    condition = (
                                        (term_table.c.term_text == value) &
                                        (term_table.c.term_type == term_type)
                                    )
                                    if lang is not None:
                                        condition &= (term_table.c.lang == lang)
                                    else:
                                        condition &= (term_table.c.lang.is_(None))
                                    
                                    if datatype_id is not None:
                                        condition &= (term_table.c.datatype_id == datatype_id)
                                    else:
                                        condition &= (term_table.c.datatype_id.is_(None))
                                    
                                    conditions.append(condition)
                                
                                if conditions:
                                    from sqlalchemy import or_
                                    select_stmt = term_table.select().where(or_(*conditions))
                                    result = conn.execute(select_stmt)
                                    
                                    batch_found = 0
                                    for row in result:
                                        key = (row.term_text, row.term_type, row.lang, row.datatype_id)
                                        term_id_map[key] = row.term_id
                                        batch_found += 1
                                    
                                    self.logger.debug(f"Found {batch_found} existing terms in batch {i//batch_size + 1}")
                        
                        self.logger.debug(f"Found {len(term_id_map)} total existing terms")
                        
                        # Step 3: Batch insert new terms (inside same connection)
                        with self.utils.time_operation("batch_term_insert", f"new terms needed"):
                            new_terms = []
                            for term_key in unique_terms:
                                if term_key not in term_id_map:
                                    value, term_type, lang, datatype_id = term_key
                                    new_terms.append({
                                        'term_text': value,
                                        'term_type': term_type,
                                        'lang': lang,
                                        'datatype_id': datatype_id,
                                        'created_time': datetime.utcnow()
                                    })
                            
                            if new_terms:
                                self.logger.debug(f"Inserting {len(new_terms)} new terms in batches of {batch_size}")
                                
                                # Batch insert new terms
                                for i in range(0, len(new_terms), batch_size):
                                    batch_new_terms = new_terms[i:i + batch_size]
                                    with self.utils.time_operation("term_insert_batch", f"batch {i//batch_size + 1}, {len(batch_new_terms)} terms"):
                                        insert_stmt = term_table.insert().values(batch_new_terms)
                                        conn.execute(insert_stmt)
                    
                            # Re-lookup the newly inserted terms to get their IDs
                            new_term_keys = [term_key for term_key in unique_terms if term_key not in term_id_map]
                            
                            for i in range(0, len(new_term_keys), batch_size):
                                batch_keys = new_term_keys[i:i + batch_size]
                                conditions = []
                                
                                for value, term_type, lang, datatype_id in batch_keys:
                                    condition = (
                                        (term_table.c.term_text == value) &
                                        (term_table.c.term_type == term_type)
                                    )
                                    if lang is not None:
                                        condition &= (term_table.c.lang == lang)
                                    else:
                                        condition &= (term_table.c.lang.is_(None))
                                    
                                    if datatype_id is not None:
                                        condition &= (term_table.c.datatype_id == datatype_id)
                                    else:
                                        condition &= (term_table.c.datatype_id.is_(None))
                                    
                                    conditions.append(condition)
                                
                                if conditions:
                                    select_stmt = term_table.select().where(or_(*conditions))
                                    result = conn.execute(select_stmt)
                                    
                                    for row in result:
                                        key = (row.term_text, row.term_type, row.lang, row.datatype_id)
                                        term_id_map[key] = row.term_id
                            self.logger.debug(f"Total terms resolved: {len(term_id_map)}")
                        
                        # Step 4: Batch insert quads (inside same connection)
                        with self.utils.time_operation("batch_quad_insert", f"processing {len(quad_terms)} quads"):
                            quad_table = tables['rdf_quad']
                            new_quads = []
                            
                            # Build quad data structures
                            for s_info, p_info, o_info, g_info in quad_terms:
                                subject_id = term_id_map.get(s_info)
                                predicate_id = term_id_map.get(p_info)
                                object_id = term_id_map.get(o_info)
                                context_id = term_id_map.get(g_info)
                                
                                # Debug logging for missing term IDs
                                if subject_id is None:
                                    self.logger.error(f"Missing subject_id for term: {s_info}")
                                if predicate_id is None:
                                    self.logger.error(f"Missing predicate_id for term: {p_info}")
                                if object_id is None:
                                    self.logger.error(f"Missing object_id for term: {o_info}")
                                if context_id is None:
                                    self.logger.error(f"Missing context_id for term: {g_info}")
                                
                                if all(id is not None for id in [subject_id, predicate_id, object_id, context_id]):
                                    new_quads.append({
                                        'subject_id': subject_id,
                                        'predicate_id': predicate_id,
                                        'object_id': object_id,
                                        'context_id': context_id,
                                        'created_time': datetime.utcnow()
                                    })
                            
                            if new_quads:
                                self.logger.debug(f"Inserting {len(new_quads)} quads in batches of {batch_size}")
                                
                                # Batch insert quads (handle duplicates by checking first)
                                inserted_count = 0
                                for i in range(0, len(new_quads), batch_size):
                                    batch_quads = new_quads[i:i + batch_size]
                                    
                                    with self.utils.time_operation("quad_insert_batch", f"batch {i//batch_size + 1}, {len(batch_quads)} quads"):
                                        # Check for existing quads to avoid duplicates
                                        conditions = []
                                        for quad in batch_quads:
                                            condition = (
                                                (quad_table.c.subject_id == quad['subject_id']) &
                                                (quad_table.c.predicate_id == quad['predicate_id']) &
                                                (quad_table.c.object_id == quad['object_id']) &
                                                (quad_table.c.context_id == quad['context_id'])
                                            )
                                            conditions.append(condition)
                                        
                                        if conditions:
                                            existing_stmt = quad_table.select().where(or_(*conditions))
                                            existing_result = conn.execute(existing_stmt)
                                            existing_quads = set()
                                            
                                            for row in existing_result:
                                                existing_quads.add((row.subject_id, row.predicate_id, row.object_id, row.context_id))
                                            
                                            # Filter out existing quads
                                            unique_quads = []
                                            for quad in batch_quads:
                                                quad_key = (quad['subject_id'], quad['predicate_id'], quad['object_id'], quad['context_id'])
                                                if quad_key not in existing_quads:
                                                    unique_quads.append(quad)
                                            
                                            if unique_quads:
                                                insert_stmt = quad_table.insert().values(unique_quads)
                                                conn.execute(insert_stmt)
                                                inserted_count += len(unique_quads)
                                                self.logger.debug(f"Inserted {len(unique_quads)} new quads in batch {i//batch_size + 1}")
                                
                                conn.commit()
                                
                                self.logger.info(f"Successfully added {inserted_count} RDF quads to space '{space_id}'")
                                return inserted_count
                            else:
                                self.logger.warning(f"No valid quads to insert for space '{space_id}'")
                                return 0
                        
            except Exception as e:
                self.logger.error(f"Error adding RDF quads batch to space '{space_id}': {e}")
                return 0
    
    async def _get_or_create_term_simple(self, cursor, term_info: Tuple[str, str, Optional[str], Optional[int]], table_name: str) -> int:
        """
        Simple helper to get or create a term ID using raw SQL.
        
        Args:
            cursor: Database cursor
            term_info: Tuple of (term_text, term_type, lang, datatype_id)
            table_name: Name of the term table
            
        Returns:
            int: Term ID
        """
        term_text, term_type, lang, datatype_id = term_info
        
        # First try to get existing term
        select_sql = f"""
            SELECT term_id FROM {table_name} 
            WHERE term_text = %s AND term_type = %s 
            AND lang IS NOT DISTINCT FROM %s 
            AND datatype_id IS NOT DISTINCT FROM %s
        """
        cursor.execute(select_sql, (term_text, term_type, lang, datatype_id))
        result = cursor.fetchone()
        
        if result:
            return result['term_id']
        
        # If not found, create new term
        insert_sql = f"""
            INSERT INTO {table_name} (term_text, term_type, lang, datatype_id, created_time)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING term_id
        """
        cursor.execute(insert_sql, (term_text, term_type, lang, datatype_id, datetime.utcnow()))
        result = cursor.fetchone()
        return result['term_id']

    async def add_rdf_quads_batch_optimized_psycopg3(self, space_id: str, quads: List[Tuple[Identifier, Identifier, Identifier, Identifier]], use_unlogged: bool = False) -> int:
        """
        Ultra-fast RDF quad batch insert using direct PostgreSQL COPY operations.
        
        This eliminates all individual term lookups and uses pure COPY FROM STDIN
        for maximum performance, similar to the Tier 3 WordNet loader that achieved
        25,322 quads/sec.
        
        Args:
            space_id: Space identifier
            quads: List of (s, p, o, g) tuples representing RDF quads
            use_unlogged: If True, target unlogged tables (table_name_unlogged)
            
        Returns:
            int: Number of quads successfully added
        """
        if not quads:
            return 0
            
        try:
            # Get table names (with unlogged suffix if needed)
            table_names = self._get_table_names(space_id)
            if use_unlogged:
                table_names = {key: f"{value}_unlogged" for key, value in table_names.items()}
                self.logger.debug(f"Using unlogged tables: {table_names}")
            
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Fast batch INSERT approach: Check existing terms first to avoid duplicates
                    self.logger.info(f"🚀 BATCH INSERT: Starting processing of {len(quads)} quads...")
                    
                    # Step 1: Collect all unique terms from this batch
                    self.logger.info("📋 STEP 1: Collecting unique terms from batch...")
                    unique_terms = set()
                    quad_term_info = []  # Store term info for each quad
                    
                    for s, p, o, g in quads:
                        try:
                            s_info = self._resolve_term_info(s)
                            p_info = self._resolve_term_info(p)
                            o_info = self._resolve_term_info(o)
                            g_info = self._resolve_term_info(g)
                            
                            quad_term_info.append((s_info, p_info, o_info, g_info))
                            unique_terms.update([s_info, p_info, o_info, g_info])
                        except Exception as e:
                            self.logger.error(f"❌ Error resolving term info: {e}")
                            continue
                    
                    self.logger.info(f"📊 Found {len(unique_terms)} unique terms in batch of {len(quads)} quads")
                    
                    # Step 2: Use high-performance COPY + ON CONFLICT approach for deduplication
                    self.logger.info("🚀 STEP 2: Preparing terms with ultra-fast COPY deduplication...")
                    
                    # Get next available term ID for new terms
                    cursor.execute(f"SELECT COALESCE(MAX(term_id), 0) + 1 as next_id FROM {table_names['term']}")
                    next_temp_id = cursor.fetchone()['next_id']
                    
                    # Assign temporary IDs to all unique terms (will dedupe via ON CONFLICT)
                    term_to_temp_id = {}
                    all_terms_data = []
                    
                    for term_info in unique_terms:
                        term_to_temp_id[term_info] = next_temp_id
                        all_terms_data.append((next_temp_id, *term_info, datetime.utcnow()))
                        next_temp_id += 1
                    
                    self.logger.info(f"📊 Prepared {len(all_terms_data)} unique terms for ultra-fast COPY insert")
                    
                    # Step 3: Prepare quad data using temporary term IDs
                    self.logger.info("📋 STEP 3: Preparing quad data with temporary term IDs...")
                    quad_rows = []
                    for s_info, p_info, o_info, g_info in quad_term_info:
                        quad_rows.append((
                            term_to_temp_id[s_info],
                            term_to_temp_id[p_info], 
                            term_to_temp_id[o_info],
                            term_to_temp_id[g_info],
                            datetime.utcnow()
                        ))
                    
                    self.logger.info(f"✅ STEP 3 COMPLETE: Prepared {len(all_terms_data)} terms and {len(quad_rows)} quads")
                    
                    # Log sample data for debugging
                    if all_terms_data:
                        sample_term = all_terms_data[0]
                        self.logger.info(f"📝 Sample term data: {sample_term}")
                    if quad_rows:
                        sample_quad = quad_rows[0]
                        self.logger.info(f"📝 Sample quad data: {sample_quad}")
                    
                    # Step 4: Ultra-fast term insert with automatic deduplication via ON CONFLICT
                    if all_terms_data:
                        self.logger.info(f"🚀 STEP 4: Ultra-fast term insert with ON CONFLICT deduplication ({len(all_terms_data)} terms)...")
                        try:
                            # Use ON CONFLICT to automatically handle duplicates at database level
                            if use_unlogged:
                                # Unlogged tables have no constraints, so use simple insert
                                insert_sql = f"""
                                    INSERT INTO {table_names['term']} (term_id, term_text, term_type, lang, datatype_id, created_time)
                                    VALUES (%s, %s, %s, %s, %s, %s)
                                """
                            else:
                                # Regular tables can use ON CONFLICT for deduplication
                                insert_sql = f"""
                                    INSERT INTO {table_names['term']} (term_id, term_text, term_type, lang, datatype_id, created_time)
                                    VALUES (%s, %s, %s, %s, %s, %s)
                                    ON CONFLICT (term_text, term_type, COALESCE(lang, ''), COALESCE(datatype_id, 0)) DO NOTHING
                                """
                            
                            self.logger.info(f"📝 Term insert SQL: {insert_sql}")
                            self.logger.info(f"🚀 Executing ultra-fast batch insert for {len(all_terms_data)} terms...")
                            
                            cursor.executemany(insert_sql, all_terms_data)
                            self.logger.info("✅ Ultra-fast term executemany completed successfully")
                            
                            # Verify the insert worked by counting total terms
                            self.logger.info("🔍 Verifying term insert results...")
                            cursor.execute(f"SELECT COUNT(*) as count FROM {table_names['term']}")
                            total_term_count = cursor.fetchone()['count']
                            self.logger.info(f"✅ STEP 4 COMPLETE: Ultra-fast term insert completed, total {total_term_count} terms in table")
                                
                        except Exception as e:
                            self.logger.error(f"❌ CRITICAL ERROR in term batch insert: {e}")
                            import traceback
                            self.logger.error(f"📋 Full traceback: {traceback.format_exc()}")
                            return 0
                    else:
                        self.logger.info("⚠️  STEP 4 SKIPPED: No terms to insert")
                    
                    # Step 5: Bulk insert all quads using executemany
                    if quad_rows:
                        self.logger.info(f"🔧 STEP 5: Starting quad batch insert of {len(quad_rows)} quads...")
                        try:
                            insert_sql = f"""
                                INSERT INTO {table_names['rdf_quad']} (subject_id, predicate_id, object_id, context_id, created_time)
                                VALUES (%s, %s, %s, %s, %s)
                            """
                            self.logger.info(f"📝 Quad insert SQL: {insert_sql}")
                            self.logger.info(f"📊 Executing batch insert for {len(quad_rows)} quads...")
                            
                            cursor.executemany(insert_sql, quad_rows)
                            self.logger.info("✅ Quad executemany completed successfully")
                            
                            # Verify the quad insert worked
                            self.logger.info("🔍 Verifying quad insert results...")
                            cursor.execute(f"SELECT COUNT(*) as count FROM {table_names['rdf_quad']}")
                            quad_count = cursor.fetchone()['count']
                            self.logger.info(f"✅ STEP 5 COMPLETE: Batch inserted {len(quad_rows)} quads, verified {quad_count} quads in table")
                            
                            if quad_count == 0:
                                self.logger.error("❌ CRITICAL: Batch insert completed but no quads were inserted!")
                                return 0
                            
                            # Commit the transaction
                            self.logger.info("💾 Committing transaction...")
                            conn.commit()
                            self.logger.info("✅ Transaction committed successfully")
                            
                            self.logger.info(f"🎉 SUCCESS: Fast batch insert completed - {len(quads)} quads added to space '{space_id}'")
                            return len(quads)
                            
                        except Exception as e:
                            self.logger.error(f"❌ CRITICAL ERROR in quad batch insert: {e}")
                            import traceback
                            self.logger.error(f"📋 Full traceback: {traceback.format_exc()}")
                            return 0
                    else:
                        self.logger.info("⚠️  STEP 3 SKIPPED: No quads to insert")
                        return 0
                    
        except Exception as e:
            self.logger.error(f"Error in psycopg3 batch insert to space '{space_id}': {e}")
            return 0
    
    async def add_rdf_quads_batch_uuid(self, space_id: str, quads: List[Tuple[Identifier, Identifier, Identifier, Identifier]], use_unlogged: bool = False) -> int:
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
            if use_unlogged:
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
    
    async def add_rdf_quads_batch_original(self, space_id: str, quads: List[Tuple[Identifier, Identifier, Identifier, Identifier]]) -> int:
        """
        Original slower batch insert method (kept for reference).
        """
        with self.utils.time_operation("add_rdf_quads_batch_optimized", f"{len(quads)} quads to space '{space_id}'"):
            try:
                # Step 1: Resolve all term types and extract values
                with self.utils.time_operation("term_type_resolution", f"{len(quads)} quads"):
                    term_info = {}  # {(value, type, lang, datatype_id): set of quad_indices}
                    quad_terms = []  # [(s_info, p_info, o_info, g_info), ...]
                    
                    for i, (s, p, o, g) in enumerate(quads):
                        # Log progress for large batches
                        if i > 0 and i % 25000 == 0:
                            self.logger.debug(f"Processed {i}/{len(quads)} quads for type resolution")
                        
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
                        
                        # Store term info
                        s_info = (s_value, s_type, s_lang, s_datatype_id)
                        p_info = (p_value, p_type, p_lang, p_datatype_id)
                        o_info = (o_value, o_type, o_lang, o_datatype_id)
                        g_info = (g_value, g_type, g_lang, g_datatype_id)
                        
                        quad_terms.append((s_info, p_info, o_info, g_info))
                        
                        # Track unique terms
                        for term_info_item in [s_info, p_info, o_info, g_info]:
                            if term_info_item not in term_info:
                                term_info[term_info_item] = set()
                            term_info[term_info_item].add(i)
                    
                    self.logger.debug(f"Resolved {len(term_info)} unique terms from {len(quads)} quads")
                
                # Step 2: Use term cache to minimize database lookups
                with self.utils.time_operation("term_cache_lookup", f"{len(term_info)} unique terms"):
                    term_id_map = {}  # {(value, type, lang, datatype_id): term_id}
                    cache_hits = 0
                    
                    # First pass: check cache for all terms
                    for term_key in term_info.keys():
                        cached_id = self.term_cache.get_term_id(term_key)
                        if cached_id is not None:
                            term_id_map[term_key] = cached_id
                            cache_hits += 1
                    
                    self.logger.debug(f"Cache hits: {cache_hits}/{len(term_info)} ({cache_hits/len(term_info)*100:.1f}%)")
                    
                    # Get terms that need database lookup
                    missing_terms = set(term_info.keys()) - set(term_id_map.keys())
                    missing_terms = self.term_cache.get_missing_terms(missing_terms)
                    
                    self.logger.debug(f"Need DB lookup for {len(missing_terms)} terms after Bloom filter")
                
                # Step 3: Batch lookup missing terms from database
                if missing_terms:
                    with self.utils.time_operation("batch_db_term_lookup", f"{len(missing_terms)} missing terms"):
                        tables = self._define_space_tables(space_id)
                        term_table = tables['term']
                        
                        with self.engine.connect() as conn:
                            # Process in chunks to avoid query size limits
                            batch_size = 1000
                            missing_terms_list = list(missing_terms)
                            
                            for i in range(0, len(missing_terms_list), batch_size):
                                batch_terms = missing_terms_list[i:i + batch_size]
                                
                                # Create OR conditions for batch lookup
                                conditions = []
                                for value, term_type, lang, datatype_id in batch_terms:
                                    condition = (
                                        (term_table.c.term_text == value) &
                                        (term_table.c.term_type == term_type)
                                    )
                                    if lang is not None:
                                        condition &= (term_table.c.lang == lang)
                                    else:
                                        condition &= (term_table.c.lang.is_(None))
                                    
                                    if datatype_id is not None:
                                        condition &= (term_table.c.datatype_id == datatype_id)
                                    else:
                                        condition &= (term_table.c.datatype_id.is_(None))
                                    
                                    conditions.append(condition)
                                
                                if conditions:
                                    query = select(
                                        term_table.c.term_id,
                                        term_table.c.term_text,
                                        term_table.c.term_type,
                                        term_table.c.lang,
                                        term_table.c.datatype_id
                                    ).where(or_(*conditions))
                                    
                                    result = conn.execute(query)
                                    for row in result:
                                        term_key = (row.term_text, row.term_type, row.lang, row.datatype_id)
                                        term_id_map[term_key] = row.term_id
                            
                            # Update cache with found terms
                            found_terms = {k: v for k, v in term_id_map.items() if k in missing_terms}
                            if found_terms:
                                self.term_cache.batch_update(found_terms)
                                self.logger.debug(f"Updated cache with {len(found_terms)} terms from DB")
                
                # Step 4: Identify and bulk insert new terms using psycopg3 COPY
                new_terms = [term_key for term_key in term_info.keys() if term_key not in term_id_map]
                
                if new_terms:
                    with self.utils.time_operation("bulk_insert_new_terms", f"{len(new_terms)} new terms"):
                        tables = self._define_space_tables(space_id)
                        term_table = tables['term']
                        
                        # Use SQLAlchemy connection with psycopg3 COPY
                        with self.engine.connect() as conn:
                            # Get the underlying psycopg3 connection
                            raw_conn = conn.connection.driver_connection
                            
                            # Prepare data for COPY
                            term_data = []
                            current_time = datetime.utcnow()
                            
                            for term_text, term_type, lang, datatype_id in new_terms:
                                term_data.append((
                                    term_text,
                                    term_type,
                                    lang,
                                    datatype_id,
                                    current_time
                                ))
                            
                            # Create temporary table for bulk insert
                            temp_table_name = f"temp_terms_{space_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}"
                            
                            raw_conn.execute(f"""
                                CREATE TEMPORARY TABLE {temp_table_name} (
                                    term_text TEXT,
                                    term_type CHAR(1),
                                    lang VARCHAR(20),
                                    datatype_id BIGINT,
                                    created_time TIMESTAMP
                                )
                            """)
                            
                            # Use psycopg3 COPY for bulk loading
                            with raw_conn.cursor() as cursor:
                                with cursor.copy(f"COPY {temp_table_name} (term_text, term_type, lang, datatype_id, created_time) FROM STDIN") as copy:
                                    for term_text, term_type, lang, datatype_id, created_time in term_data:
                                        copy.write_row([
                                            term_text,
                                            term_type,
                                            lang,
                                            datatype_id,
                                            created_time
                                        ])
                            
                            # Insert from temp table to actual table with conflict resolution
                            table_name = PostgreSQLUtils.get_table_name(self.global_prefix, space_id, 'term')
                            
                            # First, insert new terms
                            raw_conn.execute(f"""
                                INSERT INTO {table_name} (term_text, term_type, lang, datatype_id, created_time)
                                SELECT term_text, term_type, lang, datatype_id, created_time
                                FROM {temp_table_name}
                                ON CONFLICT (term_text, term_type, lang, datatype_id) 
                                DO NOTHING
                            """)
                            
                            # Commit the transaction to ensure terms are visible
                            raw_conn.commit()
                            
                            # Now retrieve all term IDs for the terms we tried to insert
                            # Use a simpler approach: query each term individually to avoid SQL injection
                            with raw_conn.cursor() as cursor:
                                for term_text, term_type, lang, datatype_id in new_terms:
                                    cursor.execute(f"""
                                        SELECT term_id, term_text, term_type, lang, datatype_id
                                        FROM {table_name}
                                        WHERE term_text = %s AND term_type = %s 
                                        AND lang IS NOT DISTINCT FROM %s 
                                        AND datatype_id IS NOT DISTINCT FROM %s
                                    """, (term_text, term_type, lang, datatype_id))
                                    
                                    row = cursor.fetchone()
                                    if row:
                                        term_key = (row[1], row[2], row[3], row[4])
                                        term_id_map[term_key] = row[0]
                        
                        # Update cache with new terms
                        new_term_mappings = {k: v for k, v in term_id_map.items() if k in new_terms}
                        if new_term_mappings:
                            self.term_cache.batch_update(new_term_mappings)
                            self.logger.debug(f"Added {len(new_term_mappings)} new terms to cache")
                
                # Step 5: Bulk insert quads using psycopg3 COPY
                with self.utils.time_operation("bulk_insert_quads", f"{len(quads)} quads"):
                    tables = self._define_space_tables(space_id)
                    quad_table = tables['rdf_quad']
                    
                    # Prepare quad data for COPY
                    valid_quads = []
                    for i, (s_info, p_info, o_info, g_info) in enumerate(quad_terms):
                        subject_id = term_id_map.get(s_info)
                        predicate_id = term_id_map.get(p_info)
                        object_id = term_id_map.get(o_info)
                        context_id = term_id_map.get(g_info)
                        
                        if all(id is not None for id in [subject_id, predicate_id, object_id, context_id]):
                            valid_quads.append((subject_id, predicate_id, object_id, context_id))
                        else:
                            missing_terms = []
                            if subject_id is None: missing_terms.append(f"subject: {s_info}")
                            if predicate_id is None: missing_terms.append(f"predicate: {p_info}")
                            if object_id is None: missing_terms.append(f"object: {o_info}")
                            if context_id is None: missing_terms.append(f"context: {g_info}")
                            self.logger.warning(f"Skipping quad {i}: missing term IDs for {', '.join(missing_terms)}")
                    
                    if valid_quads:
                        # Use SQLAlchemy connection with psycopg3 COPY
                        with self.engine.connect() as conn:
                            # Get the underlying psycopg3 connection
                            raw_conn = conn.connection.driver_connection
                            
                            # Prepare data for COPY
                            quad_data = []
                            current_time = datetime.utcnow()
                            
                            for subject_id, predicate_id, object_id, context_id in valid_quads:
                                quad_data.append((
                                    subject_id,
                                    predicate_id,
                                    object_id,
                                    context_id,
                                    current_time
                                ))
                            
                            # Create temporary table for bulk insert
                            temp_table_name = f"temp_quads_{space_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}"
                            
                            raw_conn.execute(f"""
                                CREATE TEMPORARY TABLE {temp_table_name} (
                                    subject_id BIGINT,
                                    predicate_id BIGINT,
                                    object_id BIGINT,
                                    context_id BIGINT,
                                    created_time TIMESTAMP
                                )
                            """)
                            
                            # Use psycopg3 COPY for bulk loading
                            with raw_conn.cursor() as cursor:
                                with cursor.copy(f"COPY {temp_table_name} (subject_id, predicate_id, object_id, context_id, created_time) FROM STDIN") as copy:
                                    for subject_id, predicate_id, object_id, context_id, created_time in quad_data:
                                        copy.write_row([
                                            subject_id,
                                            predicate_id,
                                            object_id,
                                            context_id,
                                            created_time
                                        ])
                            
                            # Insert from temp table to actual table with conflict resolution
                            table_name = PostgreSQLUtils.get_table_name(self.global_prefix, space_id, 'rdf_quad')
                            result = raw_conn.execute(f"""
                                INSERT INTO {table_name} (subject_id, predicate_id, object_id, context_id, created_time)
                                SELECT subject_id, predicate_id, object_id, context_id, created_time
                                FROM {temp_table_name}
                                ON CONFLICT (subject_id, predicate_id, object_id, context_id) 
                                DO NOTHING
                            """)
                            
                            inserted_count = result.rowcount
                            # Commit the transaction to ensure quads are visible
                            raw_conn.commit()
                        
                        # Log cache statistics
                        self.term_cache.log_statistics()
                        
                        self.logger.info(f"Successfully added {inserted_count} RDF quads to space '{space_id}' using optimized batch insert")
                        return inserted_count
                    else:
                        self.logger.warning(f"No valid quads to insert for space '{space_id}'")
                        return 0
                        
            except Exception as e:
                self.logger.error(f"Error in optimized RDF quads batch insert to space '{space_id}': {e}")
                return 0
    
    async def remove_rdf_quads_batch(self, space_id: str, quads: List[tuple]) -> int:
        """
        Remove multiple RDF quads from a specific space efficiently using batch operations.
        
        This function processes large batches (50,000+) efficiently by:
        1. Resolving all term types in batch
        2. Looking up existing terms in batch
        3. Removing matching quads in batch
        
        Args:
            space_id: Space identifier
            quads: List of (s, p, o, g) tuples representing RDF quads to remove
            
        Returns:
            int: Number of quads successfully removed
        """
        if not quads:
            return 0
            
        with self.utils.time_operation("remove_rdf_quads_batch", f"removing {len(quads)} quads from space '{space_id}'"):
            try:
                # Step 1: Resolve all term types and extract values
                with self.utils.time_operation("batch_term_resolution", f"resolving types for {len(quads)} quads"):
                    term_info = {}  # {(value, type, lang, datatype_id): set of quad_indices}
                    quad_terms = []  # [(s_info, p_info, o_info, g_info), ...]
                    
                    for i, (s, p, o, g) in enumerate(quads):
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
                        
                        # Store term info
                        s_info = (s_value, s_type, s_lang, s_datatype_id)
                        p_info = (p_value, p_type, p_lang, p_datatype_id)
                        o_info = (o_value, o_type, o_lang, o_datatype_id)
                        g_info = (g_value, g_type, g_lang, g_datatype_id)
                        
                        quad_terms.append((s_info, p_info, o_info, g_info))
                        
                        # Track unique terms
                        for term_info_item in [s_info, p_info, o_info, g_info]:
                            if term_info_item not in term_info:
                                term_info[term_info_item] = set()
                            term_info[term_info_item].add(i)
                    
                    self.logger.debug(f"Resolved {len(term_info)} unique terms from {len(quads)} quads")
                
                # Step 2: Batch lookup existing terms
                tables = self._define_space_tables(space_id)
                term_table = tables['term']
                quad_table = tables['rdf_quad']
                
                term_id_map = {}  # {(value, type, lang, datatype_id): term_id}
                
                with self.engine.connect() as conn:
                    with self.utils.time_operation("batch_term_lookup", f"looking up {len(term_info)} unique terms"):
                        # Build batch lookup query
                        unique_terms = list(term_info.keys())
                        batch_size = 1000
                        
                        for i in range(0, len(unique_terms), batch_size):
                            batch_terms = unique_terms[i:i + batch_size]
                            
                            with self.utils.time_operation("term_lookup_batch", f"batch {i//batch_size + 1}, {len(batch_terms)} terms"):
                                conditions = []
                                
                                for value, term_type, lang, datatype_id in batch_terms:
                                    condition = (
                                        (term_table.c.term_text == value) &
                                        (term_table.c.term_type == term_type)
                                    )
                                    if lang is not None:
                                        condition &= (term_table.c.lang == lang)
                                    else:
                                        condition &= (term_table.c.lang.is_(None))
                                    
                                    if datatype_id is not None:
                                        condition &= (term_table.c.datatype_id == datatype_id)
                                    else:
                                        condition &= (term_table.c.datatype_id.is_(None))
                                    
                                    conditions.append(condition)
                                
                                if conditions:
                                    from sqlalchemy import or_
                                    select_stmt = term_table.select().where(or_(*conditions))
                                    result = conn.execute(select_stmt)
                                    
                                    for row in result:
                                        key = (row.term_text, row.term_type, row.lang, row.datatype_id)
                                        term_id_map[key] = row.term_id
                        
                        self.logger.debug(f"Found {len(term_id_map)} existing terms")
                    
                    # Step 3: Batch remove quads
                    with self.utils.time_operation("batch_quad_removal", f"removing quads from {len(quad_terms)} candidates"):
                        quad_ids_to_remove = []
                        
                        # Find matching quads
                        for s_info, p_info, o_info, g_info in quad_terms:
                            subject_id = term_id_map.get(s_info)
                            predicate_id = term_id_map.get(p_info)
                            object_id = term_id_map.get(o_info)
                            graph_id = term_id_map.get(g_info)
                            
                            # Only look for quads where all terms exist
                            if all(id is not None for id in [subject_id, predicate_id, object_id, graph_id]):
                                # Find matching quad(s)
                                select_stmt = quad_table.select().where(
                                    (quad_table.c.subject_id == subject_id) &
                                    (quad_table.c.predicate_id == predicate_id) &
                                    (quad_table.c.object_id == object_id) &
                                    (quad_table.c.graph_id == graph_id)
                                ).limit(1)  # Following RDFLib pattern: remove only one instance
                                
                                result = conn.execute(select_stmt).fetchone()
                                if result:
                                    quad_ids_to_remove.append(result.quad_id)
                        
                        if quad_ids_to_remove:
                            self.logger.debug(f"Removing {len(quad_ids_to_remove)} quads in batches of {batch_size}")
                            
                            # Batch remove quads
                            removed_count = 0
                            for i in range(0, len(quad_ids_to_remove), batch_size):
                                batch_ids = quad_ids_to_remove[i:i + batch_size]
                                
                                with self.utils.time_operation("quad_remove_batch", f"batch {i//batch_size + 1}, {len(batch_ids)} quads"):
                                    delete_stmt = quad_table.delete().where(
                                        quad_table.c.quad_id.in_(batch_ids)
                                    )
                                    result = conn.execute(delete_stmt)
                                    removed_count += result.rowcount
                                    self.logger.debug(f"Removed {result.rowcount} quads in batch {i//batch_size + 1}")
                            
                            conn.commit()
                            
                            self.logger.info(f"Successfully removed {removed_count} RDF quads from space '{space_id}'")
                            return removed_count
                        else:
                            self.logger.debug(f"No matching quads found to remove from space '{space_id}'")
                            return 0
                            
            except Exception as e:
                self.logger.error(f"Error removing RDF quads batch from space '{space_id}': {e}")
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
            
            tables = self._define_space_tables(space_id)
            namespace_table = tables['namespace']
            
            with self.engine.connect() as conn:
                # Check if prefix already exists
                select_stmt = namespace_table.select().where(
                    namespace_table.c.prefix == prefix
                )
                result = conn.execute(select_stmt).fetchone()
                
                if result:
                    # Update existing namespace URI if different
                    if result.namespace_uri != namespace_uri:
                        update_stmt = namespace_table.update().where(
                            namespace_table.c.namespace_id == result.namespace_id
                        ).values(namespace_uri=namespace_uri)
                        conn.execute(update_stmt)
                        conn.commit()
                        self.logger.info(f"Updated namespace '{prefix}' in space '{space_id}' to URI: {namespace_uri}")
                    else:
                        self.logger.debug(f"Namespace '{prefix}' already exists in space '{space_id}' with same URI")
                    return result.namespace_id
                
                # Insert new namespace
                insert_stmt = namespace_table.insert().values(
                    prefix=prefix,
                    namespace_uri=namespace_uri
                )
                result = conn.execute(insert_stmt)
                conn.commit()
                
                namespace_id = result.inserted_primary_key[0]
                self.logger.info(f"Added namespace '{prefix}' -> '{namespace_uri}' to space '{space_id}' with ID: {namespace_id}")
                return namespace_id
                
        except Exception as e:
            self.logger.error(f"Error adding namespace to space '{space_id}': {e}")
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
            
            tables = self._define_space_tables(space_id)
            namespace_table = tables['namespace']
            
            with self.engine.connect() as conn:
                select_stmt = namespace_table.select().where(
                    namespace_table.c.prefix == prefix
                )
                result = conn.execute(select_stmt).fetchone()
                
                if result:
                    self.logger.debug(f"Found namespace URI for '{prefix}' in space '{space_id}': {result.namespace_uri}")
                    return result.namespace_uri
                else:
                    self.logger.debug(f"No namespace found for prefix '{prefix}' in space '{space_id}'")
                    return None
                    
        except Exception as e:
            self.logger.error(f"Error getting namespace URI from space '{space_id}': {e}")
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
            
            tables = self._define_space_tables(space_id)
            namespace_table = tables['namespace']
            
            with self.engine.connect() as conn:
                select_stmt = namespace_table.select().order_by(namespace_table.c.prefix)
                results = conn.execute(select_stmt).fetchall()
                
                namespaces = []
                for row in results:
                    namespaces.append({
                        'namespace_id': row.namespace_id,
                        'prefix': row.prefix,
                        'namespace_uri': row.namespace_uri,
                        'created_time': row.created_time.isoformat() if row.created_time else None
                    })
                
                self.logger.debug(f"Retrieved {len(namespaces)} namespaces from space '{space_id}'")
                return namespaces
                
        except Exception as e:
            self.logger.error(f"Error listing namespaces from space '{space_id}': {e}")
            return []
    
    async def quads(self, space_id: str, quad_pattern: tuple, context: Optional[Any] = None, use_unlogged: bool = False):
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
        # Initialize results collection
        all_results = []
        
        try:
            self.logger.debug(f"🔍 DEBUG: Starting quads() method for space_id='{space_id}', pattern={quad_pattern}")
            
            PostgreSQLUtils.validate_space_id(space_id)
            self.logger.debug(f"🔍 DEBUG: Space ID validation passed")
            
            # Extract pattern components
            subject, predicate, obj, graph = quad_pattern
            self.logger.debug(f"🔍 DEBUG: Pattern components - s:{subject}, p:{predicate}, o:{obj}, g:{graph}")
            
            # Get table names (with unlogged suffix if needed)
            table_names = self._get_table_names(space_id)
            if use_unlogged:
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
                        # Build the SQL query with joins
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
                        JOIN {term_table} s_term ON quad.subject_id = s_term.term_id
                        JOIN {term_table} p_term ON quad.predicate_id = p_term.term_id
                        JOIN {term_table} o_term ON quad.object_id = o_term.term_id
                        JOIN {term_table} c_term ON quad.context_id = c_term.term_id
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
                        
                        # Execute query with timeout protection
                        self.logger.info(f"⏰ Starting query execution...")
                        import time
                        start_time = time.time()
                        
                        try:
                            cursor.execute(query, params)
                            execution_time = time.time() - start_time
                            self.logger.info(f"✅ Query executed successfully in {execution_time:.3f}s")
                        except Exception as e:
                            execution_time = time.time() - start_time
                            self.logger.error(f"❌ Query failed after {execution_time:.3f}s: {e}")
                            raise
                        
                        self.logger.debug(f"🔍 DEBUG: Calling cursor.fetchall()...")
                        results = cursor.fetchall()
                        self.logger.debug(f"🔍 DEBUG: cursor.fetchall() completed successfully")
                    
                        self.logger.debug(f"🔍 DEBUG: Found {len(results)} matching quads for pattern {quad_pattern}")
                        
                        # Convert results back to RDFLib terms and yield
                        self.logger.debug(f"🔍 DEBUG: Starting result processing loop...")
                        for i, row in enumerate(results):
                            self.logger.debug(f"🔍 DEBUG: Processing row {i}: {row}")
                            
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
                            
                            # Build the quad (psycopg3 returns named results, access by column name)
                            self.logger.debug(f"🔍 DEBUG: Converting row to RDFLib terms...")
                            s = db_to_rdflib_term(row['subject_text'], row['subject_type'], row['subject_lang'], row['subject_datatype_id'])  # subject
                            p = db_to_rdflib_term(row['predicate_text'], row['predicate_type'])  # predicate
                            o = db_to_rdflib_term(row['object_text'], row['object_type'], row['object_lang'], row['object_datatype_id'])  # object
                            c = db_to_rdflib_term(row['context_text'], row['context_type'])  # context
                            
                            quad = (s, p, o, c)
                            self.logger.debug(f"🔍 DEBUG: Created quad: {quad}")
                            
                            # Create a simple context iterator (just yields the context)
                            def context_iterator():
                                yield c
                            
                            # Collect results instead of yielding inside connection context
                            all_results.append((quad, context_iterator))
                            self.logger.debug(f"🔍 DEBUG: Collected quad {i}")
                        
        except Exception as e:
            self.logger.error(f"Error in quads query for space '{space_id}': {e}")
            self.logger.error(f"Exception type: {type(e)}")
            self.logger.error(f"Exception args: {e.args}")
            import traceback
            self.logger.error(f"Full traceback: {traceback.format_exc()}")
            # Return empty results for error case
            return
            
        # Now yield all results outside the connection context to avoid lifecycle issues
        self.logger.info(f"✅ QUADS: Collected {len(all_results)} results, now yielding outside connection context")
        for i, (quad, context_iter_func) in enumerate(all_results):
            self.logger.debug(f"🔍 DEBUG: Yielding quad {i+1}/{len(all_results)}")
            yield quad, context_iter_func()
    
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

