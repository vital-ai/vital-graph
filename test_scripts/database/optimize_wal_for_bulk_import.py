#!/usr/bin/env python3
"""
Script to optimize PostgreSQL WAL settings for bulk import operations.

This script temporarily adjusts WAL settings to maximize bulk import performance,
then provides commands to restore original settings after import completion.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.config.config_loader import get_config
from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl


async def optimize_wal_settings():
    """Optimize WAL settings for bulk import operations."""
    
    print("🔧 PostgreSQL WAL Optimization for Bulk Import")
    print("=" * 50)
    
    # Load configuration using the same pattern as test scripts
    config_path = project_root / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    config = get_config(str(config_path))
    
    # Initialize VitalGraph implementation
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    print(f"✅ Connected to database successfully")
    
    try:
        # Get current settings
        print("\n📊 Current WAL Settings:")
        current_settings = {}
        
        settings_to_check = [
            'max_wal_size',
            'checkpoint_timeout', 
            'wal_buffers',
            'maintenance_work_mem',
            'shared_buffers'
        ]
        
        # Use the database implementation's space_impl for connections
        db_impl = impl.db_impl
        
        # Get database connection using the space implementation
        async with db_impl.space_impl.get_db_connection() as conn:
            cursor = conn.cursor()
            for setting in settings_to_check:
                cursor.execute(f"SHOW {setting};")
                value = cursor.fetchone()[0]
                current_settings[setting] = value
                print(f"  {setting}: {value}")
        
        # Optimized settings for bulk import
        optimized_settings = {
            'max_wal_size': '4GB',           # Increase from 1GB
            'checkpoint_timeout': '30min',   # Increase from 5min
            'wal_buffers': '16MB',          # Increase from 4MB
            'maintenance_work_mem': '1GB'    # For index creation
        }
        
        print(f"\n🚀 Applying Optimized Settings:")
        
        async with db_impl.space_impl.get_db_connection() as conn:
            # Set autocommit mode to avoid transaction blocks
            conn.autocommit = True
            cursor = conn.cursor()
            
            for setting, value in optimized_settings.items():
                print(f"  Setting {setting} = {value}")
                cursor.execute(f"ALTER SYSTEM SET {setting} = '{value}';")
            
            # Reload configuration
            cursor.execute("SELECT pg_reload_conf();")
            print("  ✅ Configuration reloaded")
        
        # Verify new settings
        print(f"\n✅ Verified New Settings:")
        async with db_impl.space_impl.get_db_connection() as conn:
            cursor = conn.cursor()
            for setting in optimized_settings.keys():
                cursor.execute(f"SHOW {setting};")
                value = cursor.fetchone()[0]
                print(f"  {setting}: {value}")
        
        # Generate restore script
        restore_script = f"""#!/bin/bash
# Script to restore original WAL settings after bulk import

echo "🔄 Restoring Original WAL Settings..."
psql-17 -h host.docker.internal -U postgres -d vitalgraphdb << 'EOF'
"""
        
        for setting, original_value in current_settings.items():
            if setting in optimized_settings:
                restore_script += f"ALTER SYSTEM SET {setting} = '{original_value}';\n"
        
        restore_script += """SELECT pg_reload_conf();
\\q
EOF

echo "✅ Original settings restored"
"""
        
        restore_script_path = project_root / "test_scripts" / "database" / "restore_original_wal_settings.sh"
        with open(restore_script_path, 'w') as f:
            f.write(restore_script)
        
        restore_script_path.chmod(0o755)
        
        print(f"\n📝 Restore script created: {restore_script_path}")
        print(f"   Run after bulk import: ./test_scripts/database/restore_original_wal_settings.sh")
        
        print(f"\n🎯 WAL optimization complete!")
        print(f"   Expected performance improvement: 2-5x faster bulk operations")
        
    finally:
        await impl.db_impl.disconnect()


if __name__ == "__main__":
    asyncio.run(optimize_wal_settings())
