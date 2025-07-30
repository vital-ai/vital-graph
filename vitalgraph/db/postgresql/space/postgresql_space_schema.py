from typing import Dict, List, Tuple
from ..postgresql_log_utils import PostgreSQLLogUtils
from .postgresql_space_utils import PostgreSQLSpaceUtils


class PostgreSQLSpaceSchema:
    """
    PostgreSQL schema definitions for RDF graph spaces.
    
    This class contains all schema-related definitions including:
    - Table names and naming conventions
    - CREATE TABLE SQL statements
    - Index definitions and naming patterns
    - Standard datatype definitions
    
    This class is stateless and focused purely on schema definitions,
    not database operations or queries.
    """
    
    def __init__(self, global_prefix: str, space_id: str, use_unlogged: bool = True):
        """
        Initialize schema with configuration parameters.
        
        Args:
            global_prefix: Global prefix for table names
            space_id: Space identifier
            use_unlogged: Whether to use unlogged tables for better performance
        """
        self.global_prefix = global_prefix
        self.space_id = space_id
        self.use_unlogged = use_unlogged
        
        # Validate parameters
        PostgreSQLSpaceUtils.validate_global_prefix(global_prefix)
        PostgreSQLSpaceUtils.validate_space_id(space_id)
    
    def get_table_names(self) -> Dict[str, str]:
        """
        Get all RDF space table names for the configured space.
        
        Returns:
            dict: Dictionary of table names keyed by base name
        """
        base_names = {
            'term': PostgreSQLSpaceUtils.get_table_name(self.global_prefix, self.space_id, 'term'),
            'namespace': PostgreSQLSpaceUtils.get_table_name(self.global_prefix, self.space_id, 'namespace'),
            'graph': PostgreSQLSpaceUtils.get_table_name(self.global_prefix, self.space_id, 'graph'),
            'rdf_quad': PostgreSQLSpaceUtils.get_table_name(self.global_prefix, self.space_id, 'rdf_quad'),
            'datatype': PostgreSQLSpaceUtils.get_table_name(self.global_prefix, self.space_id, 'datatype')
        }
        
        # Add unlogged suffix if configured
        if self.use_unlogged:
            return {key: f"{value}_unlogged" for key, value in base_names.items()}
        
        return base_names
    
    def get_table_prefix(self) -> str:
        """
        Get the table prefix for index naming.
        
        Returns:
            str: Table prefix for index names
        """
        table_prefix = PostgreSQLSpaceUtils.get_table_prefix(self.global_prefix, self.space_id)
        if self.use_unlogged:
            table_prefix += "_unlogged"
        return table_prefix
    
    def get_create_table_sql(self) -> Dict[str, str]:
        """
        Generate CREATE TABLE SQL statements for UUID-based RDF space tables.
        
        This creates tables optimized for UUID-based term identification:
        - Uses UUID primary keys instead of BIGSERIAL
        - Eliminates foreign key constraints for better performance
        - Optimized for deterministic UUID-based batch loading
        
        Returns:
            dict: Dictionary of CREATE TABLE SQL statements
        """
        table_names = self.get_table_names()
        table_prefix = self.get_table_prefix()
        
        sql_statements = {}
        
        # UUID-based term table with ALL performance indexes
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
            
            -- Basic indexes
            CREATE INDEX idx_{table_prefix}_term_text ON {table_names['term']} (term_text);
            CREATE INDEX idx_{table_prefix}_term_type ON {table_names['term']} (term_type);
            
            -- Composite index for optimized batch lookups
            CREATE INDEX idx_{table_prefix}_term_text_type ON {table_names['term']} (term_text, term_type);
            
            -- Trigram indexes for text search
            CREATE INDEX idx_{table_prefix}_term_text_gin_trgm ON {table_names['term']} USING gin (term_text gin_trgm_ops);
            CREATE INDEX idx_{table_prefix}_term_text_gist_trgm ON {table_names['term']} USING gist (term_text gist_trgm_ops);
            
            -- Cluster term table by UUID for better JOIN performance
            CLUSTER {table_names['term']} USING {table_names['term']}_pkey;
        """
        
        # UUID-based quad table with ALL performance indexes
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
            
            -- Individual column indexes
            CREATE INDEX idx_{table_prefix}_quad_subject ON {table_names['rdf_quad']} (subject_uuid);
            CREATE INDEX idx_{table_prefix}_quad_predicate ON {table_names['rdf_quad']} (predicate_uuid);
            CREATE INDEX idx_{table_prefix}_quad_object ON {table_names['rdf_quad']} (object_uuid);
            CREATE INDEX idx_{table_prefix}_quad_context ON {table_names['rdf_quad']} (context_uuid);
            CREATE INDEX idx_{table_prefix}_quad_uuid ON {table_names['rdf_quad']} (quad_uuid);
            
            -- SPARQL-optimized composite index (subject, predicate, object, context)
            CREATE INDEX idx_{table_prefix}_quad_spoc ON {table_names['rdf_quad']} (subject_uuid, predicate_uuid, object_uuid, context_uuid);
            
            -- Cluster quad table by subject_uuid for subject-focused queries
            CLUSTER {table_names['rdf_quad']} USING idx_{table_prefix}_quad_subject;
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
        
        # Datatype table for efficient datatype URI storage and lookup
        sql_statements['datatype'] = f"""
            CREATE {table_type} {table_names['datatype']} (
                datatype_id BIGSERIAL PRIMARY KEY,
                datatype_uri VARCHAR(255) NOT NULL UNIQUE,
                datatype_name VARCHAR(100),
                created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Index on datatype URI for fast lookups
            CREATE INDEX idx_{table_prefix}_datatype_uri ON {table_names['datatype']} (datatype_uri);
            
            -- Index on datatype name for queries
            CREATE INDEX idx_{table_prefix}_datatype_name ON {table_names['datatype']} (datatype_name);
        """
        
        return sql_statements
    

    
    def get_drop_indexes_sql(self) -> List[str]:
        """
        Get SQL statements to drop indexes for bulk loading performance.
        
        Returns:
            List of DROP INDEX SQL statements
        """
        table_prefix = self.get_table_prefix()
        
        return [
            # Term table indexes
            f"DROP INDEX IF EXISTS idx_{table_prefix}_term_text;",
            f"DROP INDEX IF EXISTS idx_{table_prefix}_term_type;", 
            f"DROP INDEX IF EXISTS idx_{table_prefix}_term_text_type;",
            f"DROP INDEX IF EXISTS idx_{table_prefix}_term_text_gin_trgm;",
            f"DROP INDEX IF EXISTS idx_{table_prefix}_term_text_gist_trgm;",
            
            # Quad table indexes
            f"DROP INDEX IF EXISTS idx_{table_prefix}_quad_subject;",
            f"DROP INDEX IF EXISTS idx_{table_prefix}_quad_predicate;",
            f"DROP INDEX IF EXISTS idx_{table_prefix}_quad_object;",
            f"DROP INDEX IF EXISTS idx_{table_prefix}_quad_context;",
            f"DROP INDEX IF EXISTS idx_{table_prefix}_quad_uuid;",
            f"DROP INDEX IF EXISTS idx_{table_prefix}_quad_spoc;"
        ]
    
    def get_recreate_indexes_sql(self, concurrent: bool = True) -> List[str]:
        """
        Get SQL statements to recreate indexes after bulk loading.
        
        Args:
            concurrent: Whether to create indexes concurrently
            
        Returns:
            List of CREATE INDEX SQL statements
        """
        table_names = self.get_table_names()
        table_prefix = self.get_table_prefix()
        concurrent_keyword = "CONCURRENTLY" if concurrent else ""
        
        return [
            # Term table indexes
            f"CREATE INDEX {concurrent_keyword} idx_{table_prefix}_term_text ON {table_names['term']} (term_text);",
            f"CREATE INDEX {concurrent_keyword} idx_{table_prefix}_term_type ON {table_names['term']} (term_type);",
            f"CREATE INDEX {concurrent_keyword} idx_{table_prefix}_term_text_type ON {table_names['term']} (term_text, term_type);",
            f"CREATE INDEX {concurrent_keyword} idx_{table_prefix}_term_text_gin_trgm ON {table_names['term']} USING gin (term_text gin_trgm_ops);",
            f"CREATE INDEX {concurrent_keyword} idx_{table_prefix}_term_text_gist_trgm ON {table_names['term']} USING gist (term_text gist_trgm_ops);",
            
            # Quad table indexes
            f"CREATE INDEX {concurrent_keyword} idx_{table_prefix}_quad_subject ON {table_names['rdf_quad']} (subject_uuid);",
            f"CREATE INDEX {concurrent_keyword} idx_{table_prefix}_quad_predicate ON {table_names['rdf_quad']} (predicate_uuid);",
            f"CREATE INDEX {concurrent_keyword} idx_{table_prefix}_quad_object ON {table_names['rdf_quad']} (object_uuid);",
            f"CREATE INDEX {concurrent_keyword} idx_{table_prefix}_quad_context ON {table_names['rdf_quad']} (context_uuid);",
            f"CREATE INDEX {concurrent_keyword} idx_{table_prefix}_quad_uuid ON {table_names['rdf_quad']} (quad_uuid);",
            f"CREATE INDEX {concurrent_keyword} idx_{table_prefix}_quad_spoc ON {table_names['rdf_quad']} (subject_uuid, predicate_uuid, object_uuid, context_uuid);"
        ]
    
    def get_cluster_sql(self) -> List[str]:
        """
        Get SQL statements to cluster tables for performance.
        
        Returns:
            List of CLUSTER SQL statements
        """
        table_names = self.get_table_names()
        table_prefix = self.get_table_prefix()
        
        return [
            f"CLUSTER {table_names['rdf_quad']} USING idx_{table_prefix}_quad_subject;"
        ]


# functions for defining the db schema
