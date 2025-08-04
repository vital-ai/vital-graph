#!/opt/homebrew/anaconda3/envs/vital-graph/bin/python
"""
Reindex VitalGraph PostgreSQL space with optimized indexes for performance.

This script drops existing indexes and recreates them with performance optimizations
based on SPARQL query patterns and PostgreSQL best practices.
"""

import asyncio
import logging
import sys
import os
import time
import yaml
from typing import List, Dict, Any, Optional
from datetime import datetime

import psycopg

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SpaceReindexer:
    """Reindex VitalGraph space with optimized indexes."""
    
    def __init__(self, config_path: str = None):
        """Initialize with direct database configuration."""
        # Default config path
        if config_path is None:
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
            config_path = os.path.join(project_root, 'vitalgraphdb_config', 'vitalgraphdb-config.yaml')
        
        self.config_path = config_path
        self.db_config = self._load_config()
        self.connection = None
        
    def _load_config(self):
        """Load database configuration from YAML file."""
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
            
            # Extract database configuration
            db_config = config.get('database', {})
            return {
                'host': db_config.get('host', 'localhost'),
                'port': db_config.get('port', 5432),
                'database': db_config.get('database', 'vitalgraph'),
                'user': db_config.get('user', 'postgres'),
                'password': db_config.get('password', ''),
                'global_prefix': config.get('tables', {}).get('global_prefix', 'vitalgraph1')
            }
        except Exception as e:
            logger.error(f"Failed to load config from {self.config_path}: {e}")
            # Fallback to default configuration
            return {
                'host': 'localhost',
                'port': 5432,
                'database': 'vitalgraph',
                'user': 'postgres',
                'password': '',
                'global_prefix': 'vitalgraph1'
            }
        
    async def connect(self):
        """Connect to the database."""
        try:
            # Build connection string
            conninfo = (
                f"host={self.db_config['host']} "
                f"port={self.db_config['port']} "
                f"dbname={self.db_config['database']} "
                f"user={self.db_config['user']} "
                f"password={self.db_config['password']}"
            )
            
            # Create async connection
            self.connection = await psycopg.AsyncConnection.connect(conninfo)
            
            # Set autocommit mode for CREATE INDEX CONCURRENTLY
            await self.connection.set_autocommit(True)
            
            logger.info(f"Connected to PostgreSQL database: {self.db_config['database']}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from the database."""
        if self.connection:
            await self.connection.close()
            self.connection = None
            logger.info("Disconnected from database")
    
    def get_table_names(self, space_id: str):
        """Get table names for the space."""
        global_prefix = self.db_config['global_prefix']
        table_prefix = f"{global_prefix}__{space_id}__"
        
        return {
            'term': f"{table_prefix}term_unlogged",
            'rdf_quad': f"{table_prefix}rdf_quad_unlogged",
            'namespace': f"{table_prefix}namespace_unlogged",
            'graph': f"{table_prefix}graph_unlogged",
            'datatype': f"{table_prefix}datatype_unlogged"
        }
    
    def get_table_prefix(self, space_id: str):
        """Get table prefix for the space."""
        global_prefix = self.db_config['global_prefix']
        return f"{global_prefix}__{space_id}__"
    
    async def check_space_exists(self, space_id: str):
        """Check if space tables exist."""
        if not self.connection:
            raise RuntimeError("Not connected to database")
        
        table_names = self.get_table_names(space_id)
        
        async with self.connection.cursor() as cursor:
            await cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = %s
            """, (table_names['term'],))
            
            result = await cursor.fetchone()
            return result is not None
    
    async def get_existing_indexes(self, space_id: str):
        """Get list of existing indexes for the space."""
        if not self.connection:
            raise RuntimeError("Not connected to database")
        
        table_names = self.get_table_names(space_id)
        table_list = list(table_names.values())
        
        # Build the IN clause with proper placeholders
        placeholders = ','.join(['%s'] * len(table_list))
        
        async with self.connection.cursor() as cursor:
            await cursor.execute(f"""
                SELECT 
                    i.indexname,
                    i.tablename,
                    i.indexdef
                FROM pg_indexes i
                WHERE i.tablename IN ({placeholders})
                ORDER BY i.tablename, i.indexname
            """, table_list)
            
            indexes = await cursor.fetchall()
            return indexes
    
    def get_drop_indexes_sql(self, space_id: str) -> List[str]:
        """Get SQL statements to drop existing indexes."""
        table_prefix = self.get_table_prefix(space_id)
        
        # Standard schema indexes
        drop_statements = [
            # Term table indexes from schema
            f"DROP INDEX IF EXISTS idx_{table_prefix}term_text;",
            f"DROP INDEX IF EXISTS idx_{table_prefix}term_type;", 
            f"DROP INDEX IF EXISTS idx_{table_prefix}term_text_type;",
            f"DROP INDEX IF EXISTS idx_{table_prefix}term_text_gin_trgm;",
            f"DROP INDEX IF EXISTS idx_{table_prefix}term_text_gist_trgm;",
            
            # Quad table indexes from schema
            f"DROP INDEX IF EXISTS idx_{table_prefix}quad_subject;",
            f"DROP INDEX IF EXISTS idx_{table_prefix}quad_predicate;",
            f"DROP INDEX IF EXISTS idx_{table_prefix}quad_object;",
            f"DROP INDEX IF EXISTS idx_{table_prefix}quad_context;",
            f"DROP INDEX IF EXISTS idx_{table_prefix}quad_uuid;",
            f"DROP INDEX IF EXISTS idx_{table_prefix}quad_spoc;",
            
            # Custom performance indexes
            f"DROP INDEX IF EXISTS idx_{table_prefix}quad_poc;",
            f"DROP INDEX IF EXISTS idx_{table_prefix}quad_opc;",
            f"DROP INDEX IF EXISTS idx_{table_prefix}quad_cpso;",
            f"DROP INDEX IF EXISTS idx_{table_prefix}quad_pco;",
            f"DROP INDEX IF EXISTS idx_{table_prefix}term_text_lower;",
            f"DROP INDEX IF EXISTS idx_{table_prefix}term_text_literals_gin;",
            f"DROP INDEX IF EXISTS idx_{table_prefix}term_text_fts;",
            f"DROP INDEX IF EXISTS idx_{table_prefix}quad_spco;",
            f"DROP INDEX IF EXISTS idx_{table_prefix}quad_opcs;",
            f"DROP INDEX IF EXISTS idx_quad_predicate_object_context_subject;",
            f"DROP INDEX IF EXISTS idx_quad_subject_predicate_context_object;",
            
            # Datatype table indexes from schema
            f"DROP INDEX IF EXISTS idx_{table_prefix}datatype_uri;",
            f"DROP INDEX IF EXISTS idx_{table_prefix}datatype_name;"
        ]
        
        return drop_statements
    
    def get_create_indexes_sql(self, space_id: str) -> List[str]:
        """Get SQL statements to create optimized indexes."""
        table_names = self.get_table_names(space_id)
        table_prefix = self.get_table_prefix(space_id)
        
        create_statements = []
        
        # === TERM TABLE INDEXES ===
        
        # Basic indexes from schema
        create_statements.extend([
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}term_text ON {table_names['term']} (term_text);",
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}term_type ON {table_names['term']} (term_type);",
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}term_text_type ON {table_names['term']} (term_text, term_type);",
        ])
        
        # Trigram indexes for text search from schema
        create_statements.extend([
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}term_text_gin_trgm ON {table_names['term']} USING gin (term_text gin_trgm_ops);",
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}term_text_gist_trgm ON {table_names['term']} USING gist (term_text gist_trgm_ops);",
        ])
        
        # Custom performance indexes for term table
        create_statements.extend([
            # Functional index for case-insensitive searches
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}term_text_lower ON {table_names['term']} (lower(term_text));",
            
            # Partial index for literal values (most text searches)
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}term_text_literals_gin ON {table_names['term']} USING gin (term_text gin_trgm_ops) WHERE term_type = 'L';",
        ])
        
        # === QUAD TABLE INDEXES ===
        
        # Individual column indexes from schema
        create_statements.extend([
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}quad_subject ON {table_names['rdf_quad']} (subject_uuid);",
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}quad_predicate ON {table_names['rdf_quad']} (predicate_uuid);",
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}quad_object ON {table_names['rdf_quad']} (object_uuid);",
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}quad_context ON {table_names['rdf_quad']} (context_uuid);",
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}quad_uuid ON {table_names['rdf_quad']} (quad_uuid);",
        ])
        
        # SPARQL-optimized composite index from schema
        create_statements.append(
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}quad_spoc ON {table_names['rdf_quad']} (subject_uuid, predicate_uuid, object_uuid, context_uuid);"
        )
        
        # Custom performance indexes for quad table
        create_statements.extend([
            # MOST IMPORTANT: Composite index for predicate-based lookups
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}quad_poc ON {table_names['rdf_quad']} (predicate_uuid, object_uuid, context_uuid, subject_uuid);",
            
            # For reverse lookups (finding subjects by object)
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}quad_opc ON {table_names['rdf_quad']} (object_uuid, predicate_uuid, context_uuid, subject_uuid);",
            
            # For context-first queries (since you filter by graph)
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}quad_cpso ON {table_names['rdf_quad']} (context_uuid, predicate_uuid, subject_uuid, object_uuid);",
            
            # For finding edges by source/destination
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}quad_pco ON {table_names['rdf_quad']} (predicate_uuid, context_uuid, object_uuid);",
            
            # Additional quad indexes
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}quad_spco ON {table_names['rdf_quad']} (subject_uuid, predicate_uuid, context_uuid, object_uuid);",
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}quad_opcs ON {table_names['rdf_quad']} (object_uuid, predicate_uuid, context_uuid, subject_uuid);",
            f"CREATE INDEX CONCURRENTLY idx_quad_predicate_object_context_subject ON {table_names['rdf_quad']} (predicate_uuid, object_uuid, context_uuid, subject_uuid);",
            f"CREATE INDEX CONCURRENTLY idx_quad_subject_predicate_context_object ON {table_names['rdf_quad']} (subject_uuid, predicate_uuid, context_uuid, object_uuid);",
        ])
        
        # === DATATYPE TABLE INDEXES ===
        create_statements.extend([
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}datatype_uri ON {table_names['datatype']} (datatype_uri);",
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}datatype_name ON {table_names['datatype']} (datatype_name);",
        ])
        
        return create_statements
    
    def get_alter_table_sql(self, space_id: str) -> List[str]:
        """Get SQL statements to add full-text search column."""
        table_names = self.get_table_names(space_id)
        table_prefix = self.get_table_prefix(space_id)
        
        return [
            # Add full-text search column and index
            f"""ALTER TABLE {table_names['term']} 
                ADD COLUMN IF NOT EXISTS term_text_fts tsvector 
                GENERATED ALWAYS AS (
                    CASE 
                        WHEN term_type = 'L' THEN to_tsvector('english', term_text)
                        ELSE NULL
                    END
                ) STORED;""",
            
            f"CREATE INDEX CONCURRENTLY idx_{table_prefix}term_text_fts ON {table_names['term']} USING gin (term_text_fts);"
        ]
    
    def get_analyze_sql(self, space_id: str) -> List[str]:
        """Get SQL statements to update table statistics."""
        table_names = self.get_table_names(space_id)
        
        return [
            f"ANALYZE {table_names['term']};",
            f"ANALYZE {table_names['rdf_quad']};",
            f"ANALYZE {table_names['datatype']};",
        ]
    
    async def execute_sql_statements(self, statements: List[str], description: str):
        """Execute a list of SQL statements."""
        if not self.connection:
            raise RuntimeError("Not connected to database")
        
        logger.info(f"\n{description}")
        logger.info("=" * 60)
        
        success_count = 0
        error_count = 0
        
        for i, statement in enumerate(statements, 1):
            try:
                logger.info(f"[{i:2d}/{len(statements)}] Executing: {statement[:80]}{'...' if len(statement) > 80 else ''}")
                start_time = time.time()
                
                async with self.connection.cursor() as cursor:
                    await cursor.execute(statement)
                
                execution_time = time.time() - start_time
                logger.info(f"         ✅ Success ({execution_time:.3f}s)")
                success_count += 1
                
            except Exception as e:
                logger.error(f"         ❌ Error: {e}")
                error_count += 1
                # Continue with other statements
        
        logger.info(f"\n{description} Summary:")
        logger.info(f"  ✅ Success: {success_count}")
        logger.info(f"  ❌ Errors:  {error_count}")
        logger.info(f"  📊 Total:   {len(statements)}")
        
        return success_count, error_count
    
    async def reindex_space(self, space_id: str):
        """Reindex the specified space with optimized indexes."""
        if not self.connection:
            raise RuntimeError("Not connected to database")
        
        logger.info(f"\n🔄 REINDEXING SPACE: {space_id}")
        logger.info("=" * 80)
        
        # Check if space exists
        if not await self.check_space_exists(space_id):
            logger.error(f"❌ Space '{space_id}' does not exist!")
            return False
        
        logger.info(f"✅ Space '{space_id}' exists")
        
        # Show existing indexes
        logger.info("\n📋 Existing indexes:")
        existing_indexes = await self.get_existing_indexes(space_id)
        for index in existing_indexes:
            logger.info(f"  - {index[0]} on {index[1]}")
        
        total_start_time = time.time()
        
        try:
            # Step 1: Drop existing indexes
            drop_statements = self.get_drop_indexes_sql(space_id)
            await self.execute_sql_statements(drop_statements, "🗑️  DROPPING EXISTING INDEXES")
            
            # Step 2: Add full-text search column
            alter_statements = self.get_alter_table_sql(space_id)
            await self.execute_sql_statements(alter_statements, "🔧 ADDING FULL-TEXT SEARCH COLUMN")
            
            # Step 3: Create optimized indexes
            create_statements = self.get_create_indexes_sql(space_id)
            await self.execute_sql_statements(create_statements, "🏗️  CREATING OPTIMIZED INDEXES")
            
            # Step 4: Update table statistics
            analyze_statements = self.get_analyze_sql(space_id)
            await self.execute_sql_statements(analyze_statements, "📊 UPDATING TABLE STATISTICS")
            
            total_time = time.time() - total_start_time
            
            logger.info(f"\n🎉 REINDEXING COMPLETE!")
            logger.info(f"   Total time: {total_time:.1f} seconds")
            logger.info(f"   Space: {space_id}")
            
            # Show final indexes
            logger.info("\n📋 Final indexes:")
            final_indexes = await self.get_existing_indexes(space_id)
            for index in final_indexes:
                logger.info(f"  - {index[0]} on {index[1]}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Reindexing failed: {e}")
            return False

async def main():
    """Main function to run the space reindexer."""
    logger = logging.getLogger(__name__)
    
    # Get space_id from command line or use default
    space_id = "wordnet_frames"
    if len(sys.argv) > 1:
        space_id = sys.argv[1]
    
    reindexer = SpaceReindexer()
    
    try:
        # Connect to database
        if not await reindexer.connect():
            logger.error("Failed to connect to database")
            return 1
        
        logger.info("Connected to database")
        
        # Run reindexing
        logger.info(f"\n🚀 Starting reindex for space: {space_id}")
        
        success = await reindexer.reindex_space(space_id)
        
        if success:
            logger.info(f"\n✅ Successfully reindexed space: {space_id}")
            return 0
        else:
            logger.error(f"\n❌ Failed to reindex space: {space_id}")
            return 1
        
    except Exception as e:
        logger.error(f"Error during reindexing: {e}")
        return 1
    finally:
        await reindexer.disconnect()

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
