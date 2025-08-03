#!/usr/bin/env python3
"""
Find and analyze unused terms in VitalGraph PostgreSQL database.

This script identifies terms in the term table that are not referenced by any RDF quad
in subject, predicate, object, or context positions. It provides multiple analysis
approaches optimized for different dataset sizes.
"""

import asyncio
import logging
import sys
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

# Add the project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

from vitalgraph.config.config_loader import VitalGraphConfig
from vitalgraph.db.postgresql.postgresql_db_impl import PostgreSQLDbImpl
import psycopg

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class UnusedTermsFinder:
    """Find and analyze unused terms in VitalGraph spaces."""
    
    def __init__(self, config_path: str = None):
        """Initialize with VitalGraph configuration."""
        self.config_path = config_path or os.path.join(project_root, 'vitalgraphdb_config', 'vitalgraphdb-config.yaml')
        self.config = VitalGraphConfig(self.config_path)
        self.db_impl = None
        
    async def connect(self):
        """Connect to the database."""
        try:
            # Get database configuration
            db_config = self.config.get_database_config()
            tables_config = self.config.get_tables_config()
            
            # Initialize database implementation
            self.db_impl = PostgreSQLDbImpl(db_config, tables_config)
            await self.db_impl.connect()
            
            logger.info("Connected to VitalGraph database")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from the database."""
        if self.db_impl:
            await self.db_impl.disconnect()
            logger.info("Disconnected from database")
    
    async def list_spaces(self) -> List[Dict[str, Any]]:
        """List all available spaces."""
        if not self.db_impl:
            raise RuntimeError("Not connected to database")
        
        try:
            spaces = await self.db_impl.list_spaces()
            logger.info(f"Found {len(spaces)} spaces")
            return spaces
        except Exception as e:
            logger.error(f"Error listing spaces: {e}")
            return []
    
    async def get_space_table_names(self, space_id: str) -> Dict[str, str]:
        """Get table names for a specific space."""
        if not self.db_impl:
            raise RuntimeError("Not connected to database")
        
        # Get space implementation to access table names
        space_impl = self.db_impl.get_space_impl()
        if not space_impl:
            raise RuntimeError("Space implementation not available")
        
        # Create schema instance to get table names
        from vitalgraph.db.postgresql.space.postgresql_space_schema import PostgreSQLSpaceSchema
        schema = PostgreSQLSpaceSchema(space_impl.global_prefix, space_id, use_unlogged=True)
        return schema.get_table_names()
    
    async def analyze_space_statistics(self, space_id: str) -> Dict[str, Any]:
        """Get comprehensive statistics for a space."""
        table_names = await self.get_space_table_names(space_id)
        term_table = table_names['term']
        quad_table = table_names['rdf_quad']
        
        # Statistics query
        stats_sql = f"""
        SELECT 
            'Total Terms' as metric,
            COUNT(*) as count
        FROM {term_table}
        UNION ALL
        SELECT 
            'Total Quads' as metric,
            COUNT(*) as count  
        FROM {quad_table}
        UNION ALL
        SELECT 
            'Unique Referenced Terms' as metric,
            COUNT(DISTINCT uuid) as count
        FROM (
            SELECT subject_uuid AS uuid FROM {quad_table}
            UNION
            SELECT predicate_uuid FROM {quad_table}
            UNION
            SELECT object_uuid FROM {quad_table}
            UNION
            SELECT context_uuid FROM {quad_table}
        ) refs
        """
        
        # Term type breakdown query
        breakdown_sql = f"""
        SELECT 
            t.term_type,
            CASE 
                WHEN t.term_type = 'U' THEN 'URI'
                WHEN t.term_type = 'L' THEN 'Literal' 
                WHEN t.term_type = 'B' THEN 'Blank Node'
                WHEN t.term_type = 'G' THEN 'Graph'
                ELSE 'Unknown'
            END as term_type_name,
            COUNT(*) as total_terms,
            COUNT(r.uuid) as referenced_terms,
            COUNT(*) - COUNT(r.uuid) as unused_terms
        FROM {term_table} t
        LEFT JOIN (
            SELECT DISTINCT subject_uuid AS uuid FROM {quad_table}
            UNION
            SELECT DISTINCT predicate_uuid FROM {quad_table}
            UNION
            SELECT DISTINCT object_uuid FROM {quad_table}
            UNION
            SELECT DISTINCT context_uuid FROM {quad_table}
        ) r ON t.term_uuid = r.uuid
        GROUP BY t.term_type
        ORDER BY t.term_type
        """
        
        try:
            # Get space implementation for database access
            space_impl = self.db_impl.get_space_impl()
            
            # Execute statistics query
            async with space_impl.core.get_dict_connection() as conn:
                cursor = conn.cursor()
                # Get basic statistics
                cursor.execute(stats_sql)
                stats_rows = cursor.fetchall()
                
                # Get term type breakdown
                cursor.execute(breakdown_sql)
                breakdown_rows = cursor.fetchall()
            
            # Process results
            stats = {row['metric']: row['count'] for row in stats_rows}
            
            # Calculate unused terms
            total_terms = stats.get('Total Terms', 0)
            referenced_terms = stats.get('Unique Referenced Terms', 0)
            unused_terms = total_terms - referenced_terms
            
            return {
                'space_id': space_id,
                'total_terms': total_terms,
                'total_quads': stats.get('Total Quads', 0),
                'referenced_terms': referenced_terms,
                'unused_terms': unused_terms,
                'unused_percentage': (unused_terms / total_terms * 100) if total_terms > 0 else 0,
                'term_type_breakdown': breakdown_rows
            }
            
        except Exception as e:
            logger.error(f"Error analyzing space {space_id}: {e}")
            raise
    
    async def find_unused_terms(self, space_id: str, approach: str = 'left_join', limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Find unused terms using specified approach.
        
        Args:
            space_id: Space identifier
            approach: 'left_join', 'not_exists', or 'multi_pass'
            limit: Optional limit on results
        """
        table_names = await self.get_space_table_names(space_id)
        term_table = table_names['term']
        quad_table = table_names['rdf_quad']
        
        limit_clause = f"LIMIT {limit}" if limit else ""
        
        if approach == 'left_join':
            # Approach 1: LEFT JOIN (most efficient for small-medium datasets)
            sql = f"""
            SELECT 
                t.term_uuid,
                t.term_text,
                t.term_type,
                t.created_time
            FROM {term_table} t
            LEFT JOIN (
                SELECT subject_uuid AS referenced_uuid FROM {quad_table}
                UNION
                SELECT predicate_uuid FROM {quad_table}
                UNION
                SELECT object_uuid FROM {quad_table}
                UNION
                SELECT context_uuid FROM {quad_table}
            ) refs ON t.term_uuid = refs.referenced_uuid
            WHERE refs.referenced_uuid IS NULL
            ORDER BY t.created_time DESC
            {limit_clause}
            """
            
        elif approach == 'temp_table':
            # Approach 3: Multi-pass with temp table (best for very large datasets)
            return await self._find_unused_terms_temp_table(space_id, term_table, quad_table, limit)
            
        elif approach == 'not_exists':
            # Approach 2: NOT EXISTS (good for large datasets with many unused terms)
            sql = f"""
            SELECT 
                t.term_uuid,
                t.term_text,
                t.term_type,
                t.created_time
            FROM {term_table} t
            WHERE NOT EXISTS (
                SELECT 1 FROM {quad_table} q 
                WHERE q.subject_uuid = t.term_uuid
                   OR q.predicate_uuid = t.term_uuid
                   OR q.object_uuid = t.term_uuid
                   OR q.context_uuid = t.term_uuid
            )
            ORDER BY t.created_time DESC
            {limit_clause}
            """
            
        else:
            raise ValueError(f"Unknown approach: {approach}")
        
        try:
            # Get space implementation for database access
            space_impl = self.db_impl.get_space_impl()
            
            # Execute query
            async with space_impl.core.get_dict_connection() as conn:
                cursor = conn.cursor()
                start_time = datetime.now()
                cursor.execute(sql)
                results = cursor.fetchall()
                end_time = datetime.now()
                
                execution_time = (end_time - start_time).total_seconds()
                logger.info(f"Found {len(results)} unused terms in {execution_time:.2f}s using {approach} approach")
                
                return results
                    
        except Exception as e:
            logger.error(f"Error finding unused terms in space {space_id}: {e}")
            raise
    
    async def _find_unused_terms_temp_table(self, space_id: str, term_table: str, quad_table: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Find unused terms using temp table approach (best for very large datasets).
        
        This approach:
        1. Creates a temp table with all referenced UUIDs
        2. Creates an index on the temp table
        3. Does a LEFT JOIN against the indexed temp table
        4. Cleans up the temp table
        """
        try:
            # Get space implementation for database access
            space_impl = self.db_impl.get_space_impl()
            
            limit_clause = f"LIMIT {limit}" if limit else ""
            
            async with space_impl.core.get_dict_connection() as conn:
                cursor = conn.cursor()
                start_time = datetime.now()
                
                logger.info(f"Creating temp table with referenced UUIDs for space {space_id}...")
                
                # Step 1: Create temporary table with all referenced UUIDs
                create_temp_sql = f"""
                CREATE TEMP TABLE temp_referenced_uuids AS
                SELECT DISTINCT subject_uuid AS uuid FROM {quad_table}
                UNION
                SELECT DISTINCT predicate_uuid FROM {quad_table}
                UNION  
                SELECT DISTINCT object_uuid FROM {quad_table}
                UNION
                SELECT DISTINCT context_uuid FROM {quad_table}
                """
                
                cursor.execute(create_temp_sql)
                logger.info("Temp table created successfully")
                
                # Step 2: Create index on temp table for fast lookups
                index_sql = "CREATE INDEX idx_temp_referenced_uuids ON temp_referenced_uuids (uuid)"
                cursor.execute(index_sql)
                logger.info("Index created on temp table")
                
                # Step 3: Find unused terms by comparing against temp table
                find_unused_sql = f"""
                SELECT 
                    t.term_uuid,
                    t.term_text,
                    t.term_type,
                    t.created_time
                FROM {term_table} t
                LEFT JOIN temp_referenced_uuids r ON t.term_uuid = r.uuid
                WHERE r.uuid IS NULL
                ORDER BY t.created_time DESC
                {limit_clause}
                """
                
                cursor.execute(find_unused_sql)
                results = cursor.fetchall()
                
                # Step 4: Clean up temp table
                cursor.execute("DROP TABLE temp_referenced_uuids")
                logger.info("Temp table cleaned up")
                
                end_time = datetime.now()
                execution_time = (end_time - start_time).total_seconds()
                logger.info(f"Found {len(results)} unused terms in {execution_time:.2f}s using temp_table approach")
                
                return results
                
        except Exception as e:
            logger.error(f"Error finding unused terms with temp table in space {space_id}: {e}")
            raise
    
    async def delete_unused_terms(self, space_id: str, dry_run: bool = True) -> Dict[str, Any]:
        """
        Delete unused terms from a space.
        
        Args:
            space_id: Space identifier
            dry_run: If True, only count terms that would be deleted
            
        Returns:
            Dictionary with deletion results
        """
        table_names = await self.get_space_table_names(space_id)
        term_table = table_names['term']
        quad_table = table_names['rdf_quad']
        
        if dry_run:
            # Count unused terms
            sql = f"""
            SELECT COUNT(*) as unused_count
            FROM {term_table} t
            WHERE NOT EXISTS (
                SELECT 1 FROM {quad_table} q 
                WHERE q.subject_uuid = t.term_uuid
                   OR q.predicate_uuid = t.term_uuid
                   OR q.object_uuid = t.term_uuid
                   OR q.context_uuid = t.term_uuid
            )
            """
        else:
            # Delete unused terms
            sql = f"""
            DELETE FROM {term_table} t
            WHERE NOT EXISTS (
                SELECT 1 FROM {quad_table} q 
                WHERE q.subject_uuid = t.term_uuid
                   OR q.predicate_uuid = t.term_uuid
                   OR q.object_uuid = t.term_uuid
                   OR q.context_uuid = t.term_uuid
            )
            """
        
        try:
            # Get space implementation for database access
            space_impl = self.db_impl.get_space_impl()
            
            async with space_impl.core.get_dict_connection() as conn:
                async with conn.cursor() as cursor:
                    start_time = datetime.now()
                    
                    if dry_run:
                        await cursor.execute(sql)
                        result = await cursor.fetchone()
                        count = result['unused_count']
                        action = "would delete"
                    else:
                        await cursor.execute(sql)
                        count = cursor.rowcount
                        action = "deleted"
                    
                    end_time = datetime.now()
                    execution_time = (end_time - start_time).total_seconds()
                    
                    logger.info(f"{'Dry run: ' if dry_run else ''}{action.capitalize()} {count} unused terms in {execution_time:.2f}s")
                    
                    return {
                        'space_id': space_id,
                        'action': action,
                        'count': count,
                        'execution_time': execution_time,
                        'dry_run': dry_run
                    }
                    
        except Exception as e:
            logger.error(f"Error deleting unused terms in space {space_id}: {e}")
            raise

async def main():
    """Main function to demonstrate unused terms analysis."""
    finder = UnusedTermsFinder()
    
    try:
        # Connect to database
        if not await finder.connect():
            return 1
        
        # List available spaces
        print("\n=== Available Spaces ===")
        spaces = await finder.list_spaces()
        if not spaces:
            print("No spaces found")
            return 1
        
        for i, space in enumerate(spaces):
            # Space data structure: {'id': int, 'space': 'space_name', 'space_name': 'Display Name', 'space_description': 'desc'}
            if isinstance(space, dict):
                space_id = space.get('space', f"id_{space.get('id', 'unknown')}")
                display_name = space.get('space_name', 'No name')
                description = space.get('space_description', 'No description')
            else:
                space_id = str(space)
                display_name = 'Unknown'
                description = 'No description'
            print(f"{i+1}. {space_id} ({display_name}) - {description}")
        
        SPACE_TO_ANALYZE = "wordnet_space"  # Change this to analyze different spaces
        target_space = SPACE_TO_ANALYZE
        print(f"\n=== Analyzing Space: {target_space} ===")
        
        # Get comprehensive statistics
        stats = await finder.analyze_space_statistics(target_space)
        
        print(f"Total Terms: {stats['total_terms']:,}")
        print(f"Total Quads: {stats['total_quads']:,}")
        print(f"Referenced Terms: {stats['referenced_terms']:,}")
        print(f"Unused Terms: {stats['unused_terms']:,} ({stats['unused_percentage']:.1f}%)")
        
        print("\n=== Term Type Breakdown ===")
        for row in stats['term_type_breakdown']:
            print(f"{row['term_type_name']}: {row['total_terms']:,} total, "
                  f"{row['referenced_terms']:,} used, {row['unused_terms']:,} unused")
        
        # Find some unused terms (limited sample)
        if stats['unused_terms'] > 0:
            print(f"\n=== Sample Unused Terms (first 10) ===")
            unused_sample = await finder.find_unused_terms(target_space, approach='temp_table', limit=10)
            
            for term in unused_sample:
                term_type_name = {'U': 'URI', 'L': 'Literal', 'B': 'Blank', 'G': 'Graph'}.get(term['term_type'], 'Unknown')
                print(f"{term_type_name}: {term['term_text'][:100]}{'...' if len(term['term_text']) > 100 else ''}")
        
        print(f"\n=== Analysis Complete ===")
        print("This script only provides statistics and analysis.")
        print("No data will be modified or deleted.")
        
    except Exception as e:
        logger.error(f"Error in main: {e}")
        return 1
    
    finally:
        await finder.disconnect()
    
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
