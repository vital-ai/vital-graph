#!/usr/bin/env python3
"""
Database Information Script for VitalGraph PostgreSQL Analysis

This script connects to the PostgreSQL database and provides detailed
information about table schemas, indexes, partitions, and other metadata
for VitalGraph space tables.
"""

import asyncio
import logging
import sys
import os
from pathlib import Path
from typing import Dict, List, Any, Optional
import psycopg
from psycopg.rows import dict_row

# Add the project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.config.config_loader import get_config


class DatabaseInfoAnalyzer:
    """Analyzes PostgreSQL database structure and metadata for VitalGraph spaces."""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.connection = None
        self.config = None
        
    async def initialize(self):
        """Initialize database connection using VitalGraph config."""
        try:
            # Load VitalGraph configuration
            config_path = project_root / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
            self.config = get_config(str(config_path))
            
            # Extract database connection parameters
            db_config = self.config.get_database_config()
            
            # Connect to PostgreSQL
            self.connection = await psycopg.AsyncConnection.connect(
                host=db_config.get('host', 'localhost'),
                port=db_config.get('port', 5432),
                dbname=db_config.get('database', 'vitalgraphdb'),
                user=db_config.get('user', 'postgres'),
                password=db_config.get('password', ''),
                row_factory=dict_row
            )
            
            self.logger.info(f"✅ Connected to PostgreSQL database: {db_config.get('database', 'vitalgraphdb')}")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize database connection: {e}")
            return False
    
    async def close(self):
        """Close database connection."""
        if self.connection:
            await self.connection.close()
            self.logger.info("✅ Disconnected from database")
    
    async def get_table_schema(self, table_name: str) -> List[Dict[str, Any]]:
        """Get detailed schema information for a table."""
        query = """
        SELECT 
            column_name,
            data_type,
            is_nullable,
            column_default,
            character_maximum_length,
            numeric_precision,
            numeric_scale,
            ordinal_position,
            udt_name
        FROM information_schema.columns 
        WHERE table_name = %s 
        ORDER BY ordinal_position;
        """
        
        async with self.connection.cursor() as cursor:
            await cursor.execute(query, (table_name,))
            return await cursor.fetchall()
    
    async def get_table_indexes(self, table_name: str) -> List[Dict[str, Any]]:
        """Get index information for a table."""
        query = """
        SELECT 
            i.indexname,
            i.indexdef,
            i.tablespace,
            pg_size_pretty(pg_relation_size(c.oid)) as index_size,
            s.idx_scan as times_used,
            s.idx_tup_read as tuples_read,
            s.idx_tup_fetch as tuples_fetched
        FROM pg_indexes i
        LEFT JOIN pg_class c ON c.relname = i.indexname
        LEFT JOIN pg_stat_user_indexes s ON s.indexrelname = i.indexname
        WHERE i.tablename = %s
        ORDER BY i.indexname;
        """
        
        async with self.connection.cursor() as cursor:
            await cursor.execute(query, (table_name,))
            return await cursor.fetchall()
    
    async def get_table_constraints(self, table_name: str) -> List[Dict[str, Any]]:
        """Get constraint information for a table."""
        query = """
        SELECT 
            tc.constraint_name,
            tc.constraint_type,
            tc.is_deferrable,
            tc.initially_deferred,
            kcu.column_name,
            ccu.table_name AS foreign_table_name,
            ccu.column_name AS foreign_column_name
        FROM information_schema.table_constraints tc
        LEFT JOIN information_schema.key_column_usage kcu 
            ON tc.constraint_name = kcu.constraint_name
        LEFT JOIN information_schema.constraint_column_usage ccu 
            ON ccu.constraint_name = tc.constraint_name
        WHERE tc.table_name = %s
        ORDER BY tc.constraint_type, tc.constraint_name;
        """
        
        async with self.connection.cursor() as cursor:
            await cursor.execute(query, (table_name,))
            return await cursor.fetchall()
    
    async def get_all_related_tables(self, base_table_name: str) -> List[Dict]:
        """Get all tables related to a base table, including partitions."""
        query = """
        WITH RECURSIVE partition_tree AS (
            -- Base case: find the root table (try both exact match and pattern match)
            SELECT 
                c.oid,
                c.relname,
                n.nspname as schema_name,
                c.relkind,
                0 as level,
                c.relname as root_table
            FROM pg_class c
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE c.relname = %s OR c.relname LIKE %s
            
            UNION ALL
            
            -- Recursive case: find child partitions
            SELECT 
                child.oid,
                child.relname,
                child_ns.nspname as schema_name,
                child.relkind,
                pt.level + 1,
                pt.root_table
            FROM partition_tree pt
            JOIN pg_inherits i ON pt.oid = i.inhparent
            JOIN pg_class child ON i.inhrelid = child.oid
            JOIN pg_namespace child_ns ON child.relnamespace = child_ns.oid
        )
        SELECT DISTINCT
            pt.relname,
            pt.schema_name,
            pt.relkind,
            pt.level,
            pg_size_pretty(pg_total_relation_size(pt.oid)) as size,
            CASE 
                WHEN pt.level > 0 THEN pg_get_expr(c.relpartbound, c.oid)
                ELSE NULL
            END as partition_bound
        FROM partition_tree pt
        JOIN pg_class c ON pt.oid = c.oid
        ORDER BY pt.level, pt.relname;
        """
        
        async with self.connection.cursor() as cursor:
            await cursor.execute(query, (base_table_name, f"{base_table_name}%"))
            return await cursor.fetchall()
    
    async def get_partition_info(self, table_name: str) -> Dict[str, Any]:
        """Get comprehensive partition information for a table."""
        # Get child tables (partitions) using inheritance
        child_query = """
        SELECT 
            c.relname as partition_name,
            n.nspname as schema_name,
            pg_get_expr(c.relpartbound, c.oid) as partition_bound,
            pg_size_pretty(pg_total_relation_size(c.oid)) as size
        FROM pg_inherits i
        JOIN pg_class c ON i.inhrelid = c.oid
        JOIN pg_namespace n ON c.relnamespace = n.oid
        JOIN pg_class p ON i.inhparent = p.oid
        WHERE p.relname = %s
        ORDER BY c.relname;
        """
        
        result = {
            'is_partitioned': False,
            'partition_info': None,
            'child_partitions': []
        }
        
        async with self.connection.cursor() as cursor:
            # Check basic partition info
            pg_class_query = """
            SELECT 
                c.relname,
                c.relkind,
                c.relpersistence,
                c.relispartition,
                c.relpartbound,
                pg_get_partition_def(c.oid) as partition_def,
                pg_get_expr(c.relpartbound, c.oid) as partition_bound,
                pg_size_pretty(pg_total_relation_size(c.oid)) as total_size
            FROM pg_class c
            WHERE c.relname = %s;
            """
            await cursor.execute(pg_class_query, (table_name,))
            pg_class_info = await cursor.fetchone()
            
            if pg_class_info:
                result['partition_info'] = pg_class_info
                if pg_class_info.get('partition_key'):
                    result['is_partitioned'] = True
            
            # Get child partitions
            await cursor.execute(child_partitions_query, (table_name,))
            result['child_partitions'] = await cursor.fetchall()
        
        return result
    
    async def get_table_stats(self, table_name: str) -> Dict[str, Any]:
        """Get table statistics and size information."""
        query = """
        SELECT 
            schemaname,
            tablename,
            attname,
            n_distinct,
            most_common_vals,
            most_common_freqs,
            histogram_bounds
        FROM pg_stats 
        WHERE tablename = %s
        ORDER BY attname;
        """
        
        size_query = """
        SELECT 
            pg_size_pretty(pg_total_relation_size(%s::regclass)) as total_size,
            pg_size_pretty(pg_relation_size(%s::regclass)) as table_size,
            pg_size_pretty(pg_total_relation_size(%s::regclass) - pg_relation_size(%s::regclass)) as indexes_size
        """
        
        async with self.connection.cursor() as cursor:
            # Get column statistics
            await cursor.execute(query, (table_name,))
            stats = await cursor.fetchall()
            
            # Get size information
            await cursor.execute(size_query, (table_name, table_name, table_name, table_name))
            size_info = await cursor.fetchone()
            
            return {
                'column_stats': stats,
                'size_info': size_info
            }
    
    async def analyze_all_partitions(self, base_table_name: str):
        """Analyze all partitions for a base table including csv_import_001."""
        print(f"\n🔍 Getting detailed partition information for: {base_table_name}")
        print(f"{'='*80}")
        
        # Get all related tables
        related_tables = await self.get_all_related_tables(base_table_name)
        
        print(f"Found {len(related_tables)} tables for {base_table_name}:")
        for table in related_tables:
            print(f"  • {table['relname']}")
            print(f"    Schema: {table['schema_name']}")
            print(f"    Size: {table['size']}")
            if table.get('partition_bound'):
                print(f"    Bound: {table['partition_bound']}")
            print()
        
        print(f"\n🔍 Index information for {base_table_name} partitions:")
        print(f"{'='*60}")
        
        # Get indexes for each related table
        for table in related_tables:
            table_name = table['relname']
            indexes = await self.get_table_indexes(table_name)
            
            print(f"\n📋 {table_name} ({len(indexes)} indexes):")
            for idx in indexes:
                size = idx.get('size', 'unknown')
                print(f"  • {idx['indexname']} - {size}")
                if idx.get('indexdef'):
                    print(f"    {idx['indexdef']}")
            print()
    
    async def analyze_space_tables(self, space_id: str) -> Dict[str, Any]:
        """Analyze all tables for a given space."""
        results = {}
        
        # Get table prefix from config
        tables_config = self.config.get_table_config()
        global_prefix = tables_config.get('prefix', 'vitalgraph1_').rstrip('_')
        
        # Define tables to analyze
        tables_to_analyze = [
            f"{global_prefix}__{space_id}__term", 
            f"{global_prefix}__{space_id}__rdf_quad"
        ]
        
        for table_name in tables_to_analyze:
            try:
                # Get comprehensive table information
                table_info = {
                    'schema': await self.get_table_schema(table_name),
                    'indexes': await self.get_table_indexes(table_name),
                    'constraints': await self.get_table_constraints(table_name),
                    'partitions': await self.get_partition_info(table_name),
                    'stats': await self.get_table_stats(table_name)
                }
                
                results[table_name] = table_info
                
            except Exception as e:
                self.logger.error(f"❌ Error analyzing table {table_name}: {e}")
                results[table_name] = {'error': str(e)}
        
        return results
    
    def print_table_analysis(self, table_name: str, table_info: Dict[str, Any]):
        """Print formatted analysis of a single table."""
        print(f"\n{'='*80}")
        print(f"📊 TABLE ANALYSIS: {table_name}")
        print(f"{'='*80}")
        
        if 'error' in table_info:
            print(f"❌ Error: {table_info['error']}")
            return
        
        # Schema information
        print(f"\n📋 SCHEMA:")
        print(f"{'Column':<25} {'Type':<20} {'Nullable':<10} {'Default':<30}")
        print(f"{'-'*85}")
        for col in table_info['schema']:
            nullable = "YES" if col['is_nullable'] == 'YES' else "NO"
            default = col['column_default'] or ""
            if len(default) > 28:
                default = default[:25] + "..."
            print(f"{col['column_name']:<25} {col['data_type']:<20} {nullable:<10} {default:<30}")
        
        # Index information
        print(f"\n🔍 INDEXES:")
        if table_info['indexes']:
            for idx in table_info['indexes']:
                print(f"  • {idx['indexname']}")
                print(f"    Definition: {idx['indexdef']}")
                if idx['index_size']:
                    print(f"    Size: {idx['index_size']}")
                if idx['times_used'] is not None:
                    print(f"    Usage: {idx['times_used']} scans, {idx['tuples_read']} tuples read")
                print()
        else:
            print("  No indexes found")
        
        # Constraint information
        print(f"\n🔒 CONSTRAINTS:")
        if table_info['constraints']:
            for constraint in table_info['constraints']:
                print(f"  • {constraint['constraint_name']} ({constraint['constraint_type']})")
                if constraint['column_name']:
                    print(f"    Column: {constraint['column_name']}")
                if constraint['foreign_table_name']:
                    print(f"    References: {constraint['foreign_table_name']}.{constraint['foreign_column_name']}")
                print()
        else:
            print("  No constraints found")
        
        # Partition information
        print(f"\n📂 PARTITIONING:")
        partition_info = table_info['partitions']
        if partition_info['is_partitioned']:
            print(f"  ✅ Table is partitioned")
            if partition_info['partition_info']:
                pinfo = partition_info['partition_info']
                if pinfo.get('partition_key'):
                    print(f"  Partition Key: {pinfo['partition_key']}")
                if pinfo.get('total_size'):
                    print(f"  Total Size: {pinfo['total_size']}")
            
            if partition_info['child_partitions']:
                print(f"  Child Partitions ({len(partition_info['child_partitions'])}):")
                for partition in partition_info['child_partitions']:
                    print(f"    • {partition['partition_name']} - {partition.get('partition_size', 'N/A')}")
        else:
            print("  ❌ Table is not partitioned")
        
        # Size and statistics
        print(f"\n📈 SIZE & STATISTICS:")
        stats = table_info['stats']
        if stats['size_info']:
            size_info = stats['size_info']
            print(f"  Total Size: {size_info.get('total_size', 'N/A')}")
            print(f"  Table Size: {size_info.get('table_size', 'N/A')}")
            print(f"  Indexes Size: {size_info.get('indexes_size', 'N/A')}")
        
        if stats['column_stats']:
            print(f"  Column Statistics:")
            for stat in stats['column_stats'][:5]:  # Show first 5 columns
                if stat['n_distinct'] is not None:
                    print(f"    • {stat['attname']}: {stat['n_distinct']} distinct values")


async def main():
    """Main function to analyze database tables."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
    )
    
    analyzer = DatabaseInfoAnalyzer()
    
    try:
        print("🔌 Initializing database connection...")
        if not await analyzer.initialize():
            print("❌ Failed to initialize database connection")
            return
        
        # Get table prefix from config
        tables_config = analyzer.config.get_table_config()
        global_prefix = tables_config.get('prefix', 'vitalgraph1_').rstrip('_')
        
        # Analyze import_001 space tables with comprehensive partition analysis
        space_id = "import_001"
        tables_to_analyze = [
            f"{global_prefix}__{space_id}__term", 
            f"{global_prefix}__{space_id}__rdf_quad"
        ]
        
        for table_name in tables_to_analyze:
            await analyzer.analyze_all_partitions(table_name)
        
        # Also check specifically for csv_import_001 partitions
        print(f"\n🔍 Checking specifically for csv_import_001 partitions:")
        print(f"{'='*60}")
        
        # Query for csv_import_001 partitions directly
        csv_query = """
        SELECT 
            c.relname,
            n.nspname as schema_name,
            c.relkind,
            c.relispartition,
            pg_get_expr(c.relpartbound, c.oid) as partition_bound,
            pg_size_pretty(pg_total_relation_size(c.oid)) as size
        FROM pg_class c
        JOIN pg_namespace n ON c.relnamespace = n.oid
        WHERE c.relname LIKE '%csv_import_001%' 
        AND c.relkind = 'r'
        AND c.relispartition = true
        ORDER BY c.relname;
        """
        
        async with analyzer.connection.cursor() as cursor:
            await cursor.execute(csv_query)
            csv_partitions = await cursor.fetchall()
        
        if csv_partitions:
            print(f"Found {len(csv_partitions)} csv_import_001 partitions:")
            for partition in csv_partitions:
                print(f"  • {partition['relname']}")
                print(f"    Schema: {partition['schema_name']}")
                print(f"    Size: {partition['size']}")
                if partition['partition_bound']:
                    print(f"    Bound: {partition['partition_bound']}")
                print(f"    Is Partition: {partition['relispartition']}")
                print()
        
        # Now specifically verify the partitions we expect to exist
        print(f"\n🔍 Verifying expected csv_import_001 partitions:")
        print(f"{'='*60}")
        
        expected_partitions = [
            f"{global_prefix}__{space_id}__term_csv_import_001",
            f"{global_prefix}__{space_id}__rdf_quad_csv_import_001"
        ]
        
        for partition_name in expected_partitions:
            print(f"\n🔍 Checking: {partition_name}")
            partition_found = False
            for partition in csv_partitions:
                if partition['relname'] == partition_name.split('.')[-1]:
                    print(f"  ✅ EXISTS as partition")
                    print(f"     Schema: {partition['schema_name']}")
                    print(f"     Size: {partition['size']}")
                    print(f"     Bound: {partition['partition_bound']}")
                    partition_found = True
                    break
            
            if not partition_found:
                print(f"  ❌ NOT FOUND")
        
        print(f"\n{'='*80}")
        print(f"✅ Partition analysis complete")
            
    except Exception as e:
        print(f"❌ Error in main process: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await analyzer.close()


if __name__ == "__main__":
    asyncio.run(main())