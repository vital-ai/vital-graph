#!/usr/bin/env python3
"""
Cleanup script for orphaned temporary tables in VitalGraph PostgreSQL database.

This script identifies and removes temporary tables that were created during import operations
but were never properly cleaned up. It preserves tables that are actively used as partitions.

Usage:
    python cleanup_temp_tables.py                    # Dry run (shows what would be deleted)
    python cleanup_temp_tables.py --execute          # Actually delete the orphaned temp tables
"""

import logging
import sys
import os
from typing import List, Dict, Any, Set

# Add the project root to Python path
project_root = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, project_root)

from vitalgraph.db.postgresql.postgresql_db_impl import PostgreSQLDbImpl
from vitalgraph.config.config_loader import VitalGraphConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class TempTableCleanup:
    """Handles cleanup of orphaned temporary tables."""
    
    def __init__(self, config_path: str = None):
        """
        Initialize the cleanup tool.
        
        Args:
            config_path: Path to VitalGraph config file (optional)
        """
        self.config_path = config_path or os.path.join(
            os.path.dirname(__file__), 'vitalgraphdb_config', 'vitalgraphdb-config.yaml'
        )
        self.db_impl = None
        
    async def initialize(self):
        """Initialize database connection."""
        try:
            # Load configuration using VitalGraphConfig
            config = VitalGraphConfig(self.config_path)
            
            # Get database and tables config
            db_config = config.get_database_config()
            tables_config = config.get_tables_config()
            
            logger.info(f"Using config from: {self.config_path}")
            logger.info(f"Database: {db_config.get('database', 'unknown')}")
            logger.info(f"Host: {db_config.get('host', 'unknown')}")
            logger.info(f"Username: {db_config.get('username', 'unknown')}")
            logger.info(f"Table prefix: {tables_config.get('prefix', 'unknown')}")
            
            self.db_impl = PostgreSQLDbImpl(db_config, tables_config)
            
            # Connect to database
            success = await self.db_impl.connect()
            if not success:
                raise Exception("Failed to connect to database")
                
            logger.info(f"✅ Connected to database successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize database connection: {e}")
            return False
    
    async def get_all_temp_tables(self) -> List[Dict[str, Any]]:
        """
        Get all temporary tables in the database.
        
        Returns:
            List of temp table information dictionaries
        """
        try:
            async with self.db_impl.get_space_impl().get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT 
                            schemaname,
                            tablename,
                            tableowner,
                            pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size,
                            pg_total_relation_size(schemaname||'.'||tablename) as size_bytes
                        FROM pg_tables 
                        WHERE tablename LIKE 'temp_%'
                          AND tablename NOT LIKE '%_pkey'
                          AND tablename NOT LIKE '%_idx%'
                        ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
                    """)
                    
                    results = []
                    for row in cursor.fetchall():
                        results.append({
                            'schema': row[0],
                            'table_name': row[1],
                            'owner': row[2],
                            'size': row[3],
                            'size_bytes': row[4]
                        })
                    
                    logger.info(f"Found {len(results)} temp tables")
                    return results
                    
        except Exception as e:
            logger.error(f"❌ Failed to get temp tables: {e}")
            return []
    
    async def get_active_partitions(self) -> Set[str]:
        """
        Get temp tables that are actively used as partitions.
        
        Returns:
            Set of table names that are active partitions
        """
        try:
            async with self.db_impl.get_space_impl().get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT 
                            c.relname as table_name,
                            p.relname as parent_table
                        FROM pg_class c
                        LEFT JOIN pg_inherits i ON c.oid = i.inhrelid
                        LEFT JOIN pg_class p ON i.inhparent = p.oid
                        WHERE c.relname LIKE 'temp_%' 
                          AND c.relkind = 'r' 
                          AND c.relispartition = true
                        ORDER BY c.relname
                    """)
                    
                    active_partitions = set()
                    for row in cursor.fetchall():
                        table_name = row[0]
                        parent_table = row[1]
                        active_partitions.add(table_name)
                        logger.info(f"🔗 Active partition: {table_name} → {parent_table}")
                    
                    logger.info(f"Found {len(active_partitions)} active temp table partitions")
                    return active_partitions
                    
        except Exception as e:
            logger.error(f"❌ Failed to get active partitions: {e}")
            return set()
    
    async def get_table_stats(self, table_name: str) -> Dict[str, Any]:
        """
        Get statistics for a specific table.
        
        Args:
            table_name: Name of the table
            
        Returns:
            Dictionary with table statistics
        """
        try:
            async with self.db_impl.get_space_impl().get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT 
                            n_tup_ins as inserts,
                            n_tup_upd as updates,
                            n_tup_del as deletes,
                            n_live_tup as live_rows,
                            n_dead_tup as dead_rows,
                            last_vacuum,
                            last_autovacuum,
                            last_analyze,
                            last_autoanalyze
                        FROM pg_stat_user_tables 
                        WHERE relname = %s
                    """, (table_name,))
                    
                    row = cursor.fetchone()
                    if row:
                        return {
                            'inserts': row[0] or 0,
                            'updates': row[1] or 0,
                            'deletes': row[2] or 0,
                            'live_rows': row[3] or 0,
                            'dead_rows': row[4] or 0,
                            'last_vacuum': row[5],
                            'last_autovacuum': row[6],
                            'last_analyze': row[7],
                            'last_autoanalyze': row[8]
                        }
                    else:
                        return {}
                        
        except Exception as e:
            logger.warning(f"Failed to get stats for table {table_name}: {e}")
            return {}
    
    async def drop_temp_table(self, table_name: str, dry_run: bool = True) -> bool:
        """
        Drop a temporary table.
        
        Args:
            table_name: Name of the table to drop
            dry_run: If True, only log what would be done
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if dry_run:
                logger.info(f"🔍 DRY RUN: Would drop temp table '{table_name}'")
                return True
            else:
                logger.info(f"🗑️ DROPPING: Temp table '{table_name}'")
                
                async with self.db_impl.get_space_impl().get_db_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
                        
                logger.info(f"✅ Successfully dropped temp table '{table_name}'")
                return True
                
        except Exception as e:
            logger.error(f"❌ Error dropping temp table '{table_name}': {e}")
            return False
    
    async def cleanup_orphaned_temp_tables(self, dry_run: bool = True) -> Dict[str, Any]:
        """
        Clean up all orphaned temporary tables.
        
        Args:
            dry_run: If True, only show what would be done (default: True)
            
        Returns:
            Dictionary with cleanup statistics
        """
        stats = {
            'total_found': 0,
            'active_partitions': 0,
            'orphaned_tables': 0,
            'successfully_cleaned': 0,
            'failed_cleanup': 0,
            'total_size_bytes': 0,
            'cleaned_size_bytes': 0
        }
        
        try:
            # Get all temp tables
            all_temp_tables = await self.get_all_temp_tables()
            stats['total_found'] = len(all_temp_tables)
            
            # Get active partitions (tables we should NOT delete)
            active_partitions = await self.get_active_partitions()
            stats['active_partitions'] = len(active_partitions)
            
            if not all_temp_tables:
                logger.info("🎉 No temp tables found - database is clean!")
                return stats
            
            # Calculate total size
            stats['total_size_bytes'] = sum(table['size_bytes'] for table in all_temp_tables)
            total_size_gb = stats['total_size_bytes'] / (1024**3)
            
            logger.info(f"📊 Found {len(all_temp_tables)} temp tables consuming {total_size_gb:.2f} GB")
            logger.info(f"🔗 {len(active_partitions)} tables are active partitions (will be preserved)")
            
            # Identify orphaned tables
            orphaned_tables = []
            for table in all_temp_tables:
                table_name = table['table_name']
                if table_name not in active_partitions:
                    orphaned_tables.append(table)
                    stats['cleaned_size_bytes'] += table['size_bytes']
                else:
                    logger.info(f"🔒 PRESERVING active partition: {table_name} ({table['size']})")
            
            stats['orphaned_tables'] = len(orphaned_tables)
            cleaned_size_gb = stats['cleaned_size_bytes'] / (1024**3)
            
            if not orphaned_tables:
                logger.info("🎉 No orphaned temp tables found - all temp tables are active partitions!")
                return stats
            
            logger.info(f"🧹 Found {len(orphaned_tables)} orphaned temp tables to clean up ({cleaned_size_gb:.2f} GB)")
            
            # Clean up orphaned tables
            for table in orphaned_tables:
                table_name = table['table_name']
                size = table['size']
                
                # Get additional stats for logging
                table_stats = await self.get_table_stats(table_name)
                live_rows = table_stats.get('live_rows', 0)
                
                if dry_run:
                    logger.info(f"🔍 DRY RUN: Would drop '{table_name}' ({size}, {live_rows:,} rows)")
                else:
                    logger.info(f"🗑️ DROPPING: '{table_name}' ({size}, {live_rows:,} rows)")
                
                success = await self.drop_temp_table(table_name, dry_run=dry_run)
                if success:
                    stats['successfully_cleaned'] += 1
                else:
                    stats['failed_cleanup'] += 1
            
            # Summary
            if dry_run:
                logger.info(f"🔍 DRY RUN COMPLETE: Found {stats['orphaned_tables']} orphaned temp tables ({cleaned_size_gb:.2f} GB) that would be cleaned up")
            else:
                logger.info(f"🧹 CLEANUP COMPLETE: {stats['successfully_cleaned']}/{stats['orphaned_tables']} orphaned temp tables cleaned up ({cleaned_size_gb:.2f} GB freed)")
                
                if stats['failed_cleanup'] > 0:
                    logger.warning(f"⚠️ {stats['failed_cleanup']} temp tables failed to clean up")
            
            return stats
            
        except Exception as e:
            logger.error(f"❌ Failed to cleanup temp tables: {e}")
            return stats
    
    async def close(self):
        """Close database connection."""
        if self.db_impl:
            await self.db_impl.disconnect()
            logger.info("Database connection closed")

async def main():
    """Main function to run the cleanup."""
    
    # Parse command line arguments
    dry_run = True
    if len(sys.argv) > 1 and sys.argv[1].lower() in ['--execute', '--real', '--no-dry-run']:
        dry_run = False
        logger.warning("🚨 REAL EXECUTION MODE - Changes will be made to the database!")
    else:
        logger.info("🔍 DRY RUN MODE - No changes will be made (use --execute to actually clean up)")
    
    cleanup = TempTableCleanup()
    
    try:
        # Initialize
        if not await cleanup.initialize():
            sys.exit(1)
        
        # Run cleanup
        stats = await cleanup.cleanup_orphaned_temp_tables(dry_run=dry_run)
        
        # Print final summary
        total_size_gb = stats['total_size_bytes'] / (1024**3)
        cleaned_size_gb = stats['cleaned_size_bytes'] / (1024**3)
        
        print("\n" + "="*60)
        print("TEMP TABLE CLEANUP SUMMARY")
        print("="*60)
        print(f"Total temp tables found: {stats['total_found']}")
        print(f"Active partitions (preserved): {stats['active_partitions']}")
        print(f"Orphaned tables found: {stats['orphaned_tables']}")
        print(f"Successfully cleaned: {stats['successfully_cleaned']}")
        print(f"Failed to clean: {stats['failed_cleanup']}")
        print(f"Total size: {total_size_gb:.2f} GB")
        print(f"Size cleaned/would be cleaned: {cleaned_size_gb:.2f} GB")
        
        if dry_run and stats['orphaned_tables'] > 0:
            print(f"\nTo actually perform the cleanup, run:")
            print(f"python cleanup_temp_tables.py --execute")
        print("="*60)
        
    except KeyboardInterrupt:
        logger.info("Cleanup interrupted by user")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)
    finally:
        await cleanup.close()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
