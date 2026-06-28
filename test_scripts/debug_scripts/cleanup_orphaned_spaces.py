#!/usr/bin/env python3
"""
Cleanup script for orphaned spaces in VitalGraph.

An orphaned space is one that has a database record in the space table
but no corresponding tables in the database. This can happen when:
1. Space creation fails partway through
2. Tables are manually dropped but space record remains
3. Import processes fail and leave incomplete spaces

This script will:
1. Identify orphaned spaces (database record but no tables)
2. Optionally remove the orphaned space records from the database
3. Provide detailed logging of what was cleaned up
"""

import asyncio
import logging
import sys
import os
from typing import List, Dict, Any

# Add the project root to Python path
project_root = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, project_root)

from vitalgraph.db.postgresql.postgresql_db_impl import PostgreSQLDbImpl
from vitalgraph.space.space_manager import SpaceManager
from vitalgraph.config.config_loader import VitalGraphConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class OrphanedSpaceCleanup:
    """Handles cleanup of orphaned spaces using SpaceManager."""
    
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
        self.space_manager = None
        
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
            
            # Initialize SpaceManager
            self.space_manager = SpaceManager(self.db_impl)
            await self.space_manager.initialize_from_database()
            
            logger.info(f"✅ SpaceManager initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize database connection: {e}")
            return False
    
    async def find_orphaned_spaces(self) -> List[str]:
        """
        Find all orphaned spaces using SpaceManager.
        
        Returns:
            List of orphaned space IDs
        """
        try:
            logger.info("Using SpaceManager to detect orphaned spaces...")
            
            # Use SpaceManager's built-in orphaned space detection
            orphaned_space_ids = await self.space_manager.detect_orphaned_spaces()
            
            logger.info(f"Found {len(orphaned_space_ids)} orphaned spaces: {orphaned_space_ids}")
            return orphaned_space_ids
            
        except Exception as e:
            logger.error(f"❌ Failed to find orphaned spaces: {e}")
            return []
    
    async def cleanup_orphaned_space(self, space_id: str, dry_run: bool = True) -> bool:
        """
        Clean up a single orphaned space using SpaceManager.
        
        Args:
            space_id: Space ID to clean up
            dry_run: If True, only log what would be done (default: True)
            
        Returns:
            True if cleanup successful, False otherwise
        """
        try:
            if dry_run:
                logger.info(f"🔍 DRY RUN: Would delete orphaned space '{space_id}' using SpaceManager.delete_space_with_tables()")
                return True
            else:
                logger.info(f"🗑️ DELETING: Orphaned space '{space_id}' using SpaceManager.delete_space_with_tables()")
                
                # Use SpaceManager's comprehensive deletion method
                success = await self.space_manager.delete_space_with_tables(space_id)
                
                if success:
                    logger.info(f"✅ Successfully deleted orphaned space '{space_id}'")
                    return True
                else:
                    logger.error(f"❌ Failed to delete orphaned space '{space_id}'")
                    return False
                    
        except Exception as e:
            logger.error(f"❌ Error cleaning up space '{space_id}': {e}")
            return False
    
    async def cleanup_all_orphaned_spaces(self, dry_run: bool = True) -> Dict[str, int]:
        """
        Clean up all orphaned spaces.
        
        Args:
            dry_run: If True, only log what would be done (default: True)
            
        Returns:
            Dictionary with cleanup statistics
        """
        stats = {
            'total_found': 0,
            'successfully_cleaned': 0,
            'failed_cleanup': 0
        }
        
        try:
            # Find all orphaned spaces
            orphaned_space_ids = await self.find_orphaned_spaces()
            stats['total_found'] = len(orphaned_space_ids)
            
            if not orphaned_space_ids:
                logger.info("🎉 No orphaned spaces found - database is clean!")
                return stats
            
            # Clean up each orphaned space
            for space_id in orphaned_space_ids:
                success = await self.cleanup_orphaned_space(space_id, dry_run=dry_run)
                if success:
                    stats['successfully_cleaned'] += 1
                else:
                    stats['failed_cleanup'] += 1
            
            # Summary
            if dry_run:
                logger.info(f"🔍 DRY RUN COMPLETE: Found {stats['total_found']} orphaned spaces that would be cleaned up")
            else:
                logger.info(f"🧹 CLEANUP COMPLETE: {stats['successfully_cleaned']}/{stats['total_found']} orphaned spaces cleaned up successfully")
                if stats['failed_cleanup'] > 0:
                    logger.warning(f"⚠️ {stats['failed_cleanup']} spaces failed to clean up")
            
            return stats
            
        except Exception as e:
            logger.error(f"❌ Failed to cleanup orphaned spaces: {e}")
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
    
    cleanup = OrphanedSpaceCleanup()
    
    try:
        # Initialize
        if not await cleanup.initialize():
            sys.exit(1)
        
        # Run cleanup
        stats = await cleanup.cleanup_all_orphaned_spaces(dry_run=dry_run)
        
        # Print final summary
        print("\n" + "="*60)
        print("ORPHANED SPACE CLEANUP SUMMARY")
        print("="*60)
        print(f"Total orphaned spaces found: {stats['total_found']}")
        print(f"Successfully cleaned: {stats['successfully_cleaned']}")
        print(f"Failed to clean: {stats['failed_cleanup']}")
        
        if dry_run and stats['total_found'] > 0:
            print("\nTo actually perform the cleanup, run:")
            print(f"python {sys.argv[0]} --execute")
        
        print("="*60)
        
    except KeyboardInterrupt:
        logger.info("Cleanup interrupted by user")
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        sys.exit(1)
    finally:
        await cleanup.close()

if __name__ == "__main__":
    asyncio.run(main())
