#!/usr/bin/env python3
"""
Cleanup script to manually delete test space tables.
This is a temporary utility to clean up orphaned tables from test runs.
"""

import asyncio
import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl

TEST_SPACE_ID = "test_space_manager_001"

async def cleanup_test_space():
    """Clean up test space tables manually."""
    print(f"🧹 Cleaning up test space: {TEST_SPACE_ID}")
    
    impl = None
    try:
        # Initialize VitalGraph
        impl = VitalGraphImpl()
        await impl.connect()
        
        # Get the PostgreSQL space implementation
        space_impl_pg = impl.db_impl.space_impl
        
        # Check if space tables exist
        if space_impl_pg.space_exists(TEST_SPACE_ID):
            print(f"📋 Space tables exist for '{TEST_SPACE_ID}', deleting...")
            
            # Delete the space tables
            if space_impl_pg.delete_space_tables(TEST_SPACE_ID):
                print(f"✅ Successfully deleted tables for space '{TEST_SPACE_ID}'")
            else:
                print(f"❌ Failed to delete tables for space '{TEST_SPACE_ID}'")
        else:
            print(f"📋 No tables found for space '{TEST_SPACE_ID}'")
            
        # Also check database records
        db_spaces = await impl.db_impl.list_spaces()
        existing_space = next((s for s in db_spaces if s.get('space') == TEST_SPACE_ID), None)
        
        if existing_space:
            print(f"📋 Database record exists for '{TEST_SPACE_ID}', deleting...")
            space_db_id = existing_space.get('id')
            if await impl.db_impl.remove_space(str(space_db_id)):
                print(f"✅ Successfully deleted database record for space '{TEST_SPACE_ID}'")
            else:
                print(f"❌ Failed to delete database record for space '{TEST_SPACE_ID}'")
        else:
            print(f"📋 No database record found for space '{TEST_SPACE_ID}'")
            
        print(f"🎯 Cleanup complete for space '{TEST_SPACE_ID}'")
        
    except Exception as e:
        print(f"❌ Cleanup failed: {e}")
        return False
        
    finally:
        if impl:
            await impl.disconnect()
            
    return True

if __name__ == "__main__":
    success = asyncio.run(cleanup_test_space())
    sys.exit(0 if success else 1)
