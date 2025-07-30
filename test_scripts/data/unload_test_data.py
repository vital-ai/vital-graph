#!/usr/bin/env python3
"""
Unload Test Data Script
=======================

This script deletes the database tables associated with test spaces used by
the reload data scripts. It provides a clean way to remove test data and
free up database resources.

Spaces handled:
- space_test (from reload_test_data.py)
- wordnet_space (from reload_wordnet.py)

Usage:
    python test_scripts/data/unload_test_data.py
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add the project root directory to the path to import vitalgraph modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.db.postgresql.postgresql_utils import PostgreSQLUtils

# Set up logging for clean output
logging.basicConfig(
    level=logging.INFO,
    format='%(name)s - %(levelname)s - %(message)s'
)

# Default spaces to unload (matches the reload scripts)
DEFAULT_SPACES = [
    "space_test",      # From reload_test_data.py
    "wordnet_space"    # From reload_wordnet.py
]

async def unload_space_data(space_impl, space_id):
    """Unload data for a specific space using high-level API methods."""
    print(f"\n🗑️  Unloading space: {space_id}")
    print("-" * 40)
    
    try:
        # Check if space exists first using the proper API method
        space_existed = await space_impl.space_exists(space_id)
        
        if not space_existed:
            print(f"   ℹ️  Space '{space_id}' does not exist - already clean")
            return True  # Consider this a success since the goal (no tables) is achieved
        
        # Space exists, so get quad count for reporting
        quad_count = 0
        try:
            quad_count = await space_impl.get_quad_count(space_id)
            print(f"   📊 Found space with {quad_count:,} quads")
        except Exception as e:
            print(f"   ⚠️  Could not get quad count: {e}")
        
        # Space exists, so attempt to delete the tables
        print(f"   🗑️  Deleting tables for space '{space_id}'...")
        success = space_impl.delete_space_tables(space_id)
        
        if success:
            print(f"   ✅ Successfully deleted tables for space '{space_id}'")
            if quad_count > 0:
                print(f"   📈 Freed: {quad_count:,} quads")
            return True
        else:
            print(f"   ❌ Failed to delete tables for space '{space_id}'")
            return False
            
    except Exception as e:
        print(f"   ❌ Error unloading space '{space_id}': {e}")
        import traceback
        traceback.print_exc()
        return False

async def verify_cleanup(space_impl, space_id):
    """Verify that space tables have been completely removed using proper API methods."""
    try:
        # Use the proper API method to check if space still exists
        space_still_exists = await space_impl.space_exists(space_id)
        
        if space_still_exists:
            print(f"   ⚠️  Warning: Space '{space_id}' still exists after deletion")
            return False
        else:
            print(f"   ✅ Verification passed - no tables remain for space '{space_id}'")
            return True
            
    except Exception as e:
        print(f"   ❌ Error verifying cleanup for space '{space_id}': {e}")
        return False



async def unload_test_data(spaces_to_unload=None):
    """Main function to unload test data."""
    
    # Reduce logging chatter from verbose modules
    logging.getLogger('vitalgraph.db.postgresql.postgresql_space_impl').setLevel(logging.WARNING)
    logging.getLogger('vitalgraph.rdf.rdf_utils').setLevel(logging.WARNING)
    logging.getLogger('vitalgraph.db.postgresql.postgresql_cache_term').setLevel(logging.WARNING)
    
    spaces = spaces_to_unload or DEFAULT_SPACES
    
    print("🧹 Test Data Unload Script")
    print("=" * 50)
    print(f"Spaces to unload: {', '.join(spaces)}")
    
    # Step 1: Initialize VitalGraphImpl with config
    print("\n1. Initializing VitalGraphImpl with config file...")
    try:
        project_root = Path(__file__).parent.parent.parent  # Go up to project root from test_scripts/data
        config_path = project_root / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
        print(f"   Using config file: {config_path}")
        
        from vitalgraph.config.config_loader import get_config
        config = get_config(str(config_path))
        
        # Initialize VitalGraphImpl
        vitalgraph_impl = VitalGraphImpl(config=config)
        db_impl = vitalgraph_impl.get_db_impl()
        
        if not config:
            print("❌ Failed to load configuration")
            return False
            
        if not db_impl:
            print("❌ Failed to initialize database implementation")
            return False
            
        print("✅ VitalGraphImpl initialized successfully")
        print(f"   Config loaded: {config is not None}")
        print(f"   DB implementation: {type(db_impl).__name__}")
        
    except Exception as e:
        print(f"❌ Error initializing VitalGraph: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Step 2: Connect to database
    print("\n2. Connecting to database...")
    try:
        await db_impl.connect()
        space_impl = db_impl.get_space_impl()
        print("✅ Connected to database successfully")
        print(f"   Space implementation: {type(space_impl).__name__}")
    except Exception as e:
        print(f"❌ Error connecting to database: {e}")
        return False

    # Step 3: Unload each space
    print("\n3. Unloading spaces...")
    successful_unloads = 0
    failed_unloads = 0
    
    for space_id in spaces:
        success = await unload_space_data(space_impl, space_id)
        if success:
            successful_unloads += 1
            # Verify cleanup
            await verify_cleanup(space_impl, space_id)
        else:
            failed_unloads += 1

    # Step 4: Disconnect
    print("\n4. Disconnecting from database...")
    try:
        await db_impl.disconnect()
        print("✅ Database disconnected successfully")
    except Exception as e:
        print(f"❌ Error disconnecting: {e}")

    # Summary
    print("\n" + "=" * 60)
    if failed_unloads == 0:
        print("🎉 Test Data Unload Completed Successfully!")
        print(f"✅ Successfully unloaded {successful_unloads} spaces")
    else:
        print("⚠️  Test Data Unload Completed with Issues")
        print(f"✅ Successfully unloaded: {successful_unloads} spaces")
        print(f"❌ Failed to unload: {failed_unloads} spaces")
    
    print(f"Spaces processed: {', '.join(spaces)}")
    print("=" * 60)
    
    return failed_unloads == 0

if __name__ == "__main__":
    asyncio.run(unload_test_data())
