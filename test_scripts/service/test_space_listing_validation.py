#!/usr/bin/env python3
"""
Space Listing and Validation Test Script
========================================

This script provides comprehensive space listing and validation functionality:
- Lists spaces via REST API endpoints
- Lists spaces via internal Space Manager functions
- Validates table existence for each space
- Detects orphaned spaces (tables without database records)
- Detects incomplete spaces (database records without tables)
- Pretty prints all information in a structured format

Usage:
    python test_space_listing_validation.py
"""

import asyncio
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.api.vitalgraph_api import VitalGraphAPI
from vitalgraph.auth.vitalgraph_auth import VitalGraphAuth
from vitalgraph.config.config_loader import get_config


class SpaceListingValidator:
    """Comprehensive space listing and validation tool."""
    
    def __init__(self):
        self.vital_graph_impl = None
        self.api = None
        self.auth = None
        self.space_manager = None
        self.db_impl = None
        self.current_user = {
            "username": "admin",
            "full_name": "Administrator",
            "email": "admin@vitalgraph.com",
            "role": "admin"
        }
    
    async def setup(self) -> bool:
        """Initialize VitalGraph components and API."""
        try:
            print("🔧 Setting up Space Listing Validator...")
            
            # Initialize VitalGraph with configuration (exact pattern from working tests)
            print("   📋 Loading configuration...")
            config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
            config = get_config(str(config_path))
            
            print("   📋 Initializing VitalGraphImpl...")
            self.vital_graph_impl = VitalGraphImpl(config=config)
            
            # Connect database and automatically initialize SpaceManager
            print("   📋 Connecting database and initializing SpaceManager...")
            connected = await self.vital_graph_impl.connect_database()
            if not connected:
                print("   ❌ Failed to connect database")
                return False
            
            if not self.vital_graph_impl:
                print("   ❌ Failed to initialize VitalGraphImpl")
                return False
            
            # Get components from VitalGraphImpl
            self.db_impl = self.vital_graph_impl.get_db_impl()
            self.space_manager = self.vital_graph_impl.get_space_manager()
            
            if self.db_impl is None:
                print("   ❌ Database implementation not available")
                return False
                
            if self.space_manager is None:
                print("   ❌ Space Manager not available")
                return False
            
            # Database should already be connected from VitalGraphImpl initialization
            if not self.db_impl.is_connected():
                print("   ❌ Database not connected after VitalGraphImpl initialization")
                return False
            
            print("   ✅ Database already connected from VitalGraphImpl")
            
            # Initialize authentication
            print("   🔐 Initializing authentication...")
            self.auth = VitalGraphAuth()
            
            # Initialize VitalGraphAPI with all components
            print("   🌐 Initializing VitalGraphAPI...")
            self.api = VitalGraphAPI(
                auth_handler=self.auth,
                db_impl=self.db_impl,
                space_manager=self.space_manager
            )
            
            print("✅ Space Listing Validator setup complete")
            print(f"   📊 Database connected: {self.db_impl.is_connected()}")
            print(f"   📊 Space Manager available: {self.space_manager is not None}")
            print(f"   📊 API initialized: {self.api is not None}")
            
            return True
            
        except Exception as e:
            print(f"❌ Setup failed: {str(e)}")
            return False
    
    async def get_api_spaces(self) -> List[Dict[str, Any]]:
        """Get spaces via REST API."""
        try:
            print("📡 Fetching spaces via REST API...")
            spaces = await self.api.list_spaces(self.current_user)
            print(f"   ✅ Found {len(spaces)} spaces via API")
            return spaces
        except Exception as e:
            print(f"   ❌ API space listing failed: {str(e)}")
            return []
    
    async def get_database_spaces(self) -> List[Dict[str, Any]]:
        """Get spaces directly from database."""
        try:
            print("🗄️ Fetching spaces directly from database...")
            spaces = await self.db_impl.list_spaces()
            print(f"   ✅ Found {len(spaces)} spaces in database")
            return spaces
        except Exception as e:
            print(f"   ❌ Database space listing failed: {str(e)}")
            return []
    
    def get_space_manager_spaces(self) -> List[str]:
        """Get spaces from Space Manager registry."""
        try:
            print("📋 Fetching spaces from Space Manager registry...")
            spaces = self.space_manager.list_spaces()
            print(f"   ✅ Found {len(spaces)} spaces in Space Manager registry")
            return spaces
        except Exception as e:
            print(f"   ❌ Space Manager listing failed: {str(e)}")
            return []
    
    async def check_space_tables(self, space_id: str) -> Tuple[bool, Optional[str]]:
        """Check if tables exist for a given space."""
        try:
            # Get space from Space Manager registry
            space_record = self.space_manager.get_space(space_id)
            if space_record:
                # Use existing space record to check tables
                tables_exist = space_record.space_impl.exists()
                return tables_exist, None
            else:
                # Create temporary SpaceImpl to check tables
                from vitalgraph.space.space_impl import SpaceImpl
                temp_space_impl = SpaceImpl(space_id=space_id, db_impl=self.db_impl)
                tables_exist = temp_space_impl.exists()
                return tables_exist, None
        except Exception as e:
            return False, str(e)
    
    async def find_orphaned_tables(self) -> List[str]:
        """Find tables that exist but have no corresponding database records."""
        try:
            print("🔍 Scanning for orphaned tables...")
            
            # Get all database space records
            db_spaces = await self.get_database_spaces()
            db_space_ids = {space.get('space') for space in db_spaces}
            
            # Get global prefix for table scanning
            global_prefix = self.db_impl.global_prefix
            
            # Query PostgreSQL for tables matching our naming pattern
            orphaned_spaces = []
            
            with self.db_impl.shared_pool.connection() as conn:
                cursor = conn.cursor()
                
                # Find all tables with our prefix pattern
                cursor.execute("""
                    SELECT tablename FROM pg_tables 
                    WHERE tablename LIKE %s 
                    AND schemaname = 'public'
                """, (f"{global_prefix}__%",))
                
                tables = cursor.fetchall()
                
                # Extract space IDs from table names
                space_ids_with_tables = set()
                for (table_name,) in tables:
                    # Table format: {global_prefix}__{space_id}__{table_type}
                    if table_name.startswith(f"{global_prefix}__"):
                        parts = table_name.split("__")
                        if len(parts) >= 3:
                            space_id = parts[1]  # Extract space_id
                            space_ids_with_tables.add(space_id)
                
                # Find spaces with tables but no database records
                orphaned_spaces = list(space_ids_with_tables - db_space_ids)
            
            print(f"   🔍 Found {len(orphaned_spaces)} orphaned spaces with tables but no database records")
            return orphaned_spaces
            
        except Exception as e:
            print(f"   ❌ Orphaned table scan failed: {str(e)}")
            return []
    
    def format_space_info(self, space_data: Dict[str, Any], tables_exist: bool, 
                         table_check_error: Optional[str], source: str) -> str:
        """Format space information for pretty printing."""
        space_id = space_data.get('space', 'Unknown')
        space_name = space_data.get('space_name', 'N/A')
        space_desc = space_data.get('space_description', 'N/A')
        db_id = space_data.get('id', 'N/A')
        update_time = space_data.get('update_time', 'N/A')
        
        # Format update time if available
        if update_time != 'N/A':
            try:
                if isinstance(update_time, str):
                    dt = datetime.fromisoformat(update_time.replace('Z', '+00:00'))
                    update_time = dt.strftime('%Y-%m-%d %H:%M:%S')
            except:
                pass  # Keep original format if parsing fails
        
        # Status indicators
        tables_status = "✅ EXISTS" if tables_exist else "❌ MISSING"
        if table_check_error:
            tables_status = f"⚠️ ERROR: {table_check_error}"
        
        return f"""
    📁 Space: {space_id}
       🏷️  Name: {space_name}
       📝 Description: {space_desc}
       🆔 Database ID: {db_id}
       🕒 Updated: {update_time}
       🗂️  Tables: {tables_status}
       📍 Source: {source}"""
    
    def format_orphaned_space_info(self, space_id: str) -> str:
        """Format orphaned space information."""
        return f"""
    📁 Space: {space_id}
       ⚠️  Status: ORPHANED (Tables exist but no database record)
       🗂️  Tables: ✅ EXISTS
       📍 Source: Table scan"""
    
    async def run_comprehensive_listing(self) -> None:
        """Run comprehensive space listing and validation."""
        print("🚀 STARTING COMPREHENSIVE SPACE LISTING AND VALIDATION")
        print("=" * 70)
        
        # Get spaces from all sources
        api_spaces = await self.get_api_spaces()
        db_spaces = await self.get_database_spaces()
        sm_spaces = self.get_space_manager_spaces()
        orphaned_spaces = await self.find_orphaned_tables()
        
        print(f"\n📊 SUMMARY")
        print("-" * 30)
        print(f"   📡 API Spaces: {len(api_spaces)}")
        print(f"   🗄️ Database Spaces: {len(db_spaces)}")
        print(f"   📋 Space Manager Registry: {len(sm_spaces)}")
        print(f"   ⚠️ Orphaned Spaces: {len(orphaned_spaces)}")
        
        # Create comprehensive space inventory
        all_space_ids = set()
        space_info_map = {}
        
        # Process API spaces
        for space in api_spaces:
            space_id = space.get('space')
            if space_id:
                all_space_ids.add(space_id)
                space_info_map[space_id] = {
                    'data': space,
                    'source': 'API',
                    'in_api': True,
                    'in_db': False,
                    'in_sm': False,
                    'tables_exist': None,
                    'table_error': None
                }
        
        # Process database spaces
        for space in db_spaces:
            space_id = space.get('space')
            if space_id:
                all_space_ids.add(space_id)
                if space_id in space_info_map:
                    space_info_map[space_id]['in_db'] = True
                else:
                    space_info_map[space_id] = {
                        'data': space,
                        'source': 'Database',
                        'in_api': False,
                        'in_db': True,
                        'in_sm': False,
                        'tables_exist': None,
                        'table_error': None
                    }
        
        # Process Space Manager spaces
        for space_id in sm_spaces:
            all_space_ids.add(space_id)
            if space_id in space_info_map:
                space_info_map[space_id]['in_sm'] = True
            else:
                # This shouldn't happen normally, but handle it
                space_info_map[space_id] = {
                    'data': {'space': space_id, 'space_name': 'Unknown', 'space_description': 'Unknown'},
                    'source': 'Space Manager Only',
                    'in_api': False,
                    'in_db': False,
                    'in_sm': True,
                    'tables_exist': None,
                    'table_error': None
                }
        
        # Check table existence for all spaces
        print(f"\n🔍 VALIDATING TABLE EXISTENCE")
        print("-" * 40)
        
        for space_id in all_space_ids:
            print(f"   Checking tables for '{space_id}'...")
            tables_exist, error = await self.check_space_tables(space_id)
            space_info_map[space_id]['tables_exist'] = tables_exist
            space_info_map[space_id]['table_error'] = error
        
        # Display detailed results
        print(f"\n📋 DETAILED SPACE INVENTORY")
        print("=" * 50)
        
        if not all_space_ids and not orphaned_spaces:
            print("   📭 No spaces found in any source")
        else:
            # Group spaces by status
            complete_spaces = []
            incomplete_spaces = []
            registry_only_spaces = []
            
            for space_id, info in space_info_map.items():
                if info['in_db'] and info['tables_exist']:
                    complete_spaces.append((space_id, info))
                elif info['in_db'] and not info['tables_exist']:
                    incomplete_spaces.append((space_id, info))
                elif not info['in_db'] and info['tables_exist']:
                    registry_only_spaces.append((space_id, info))
                else:
                    incomplete_spaces.append((space_id, info))
            
            # Display complete spaces
            if complete_spaces:
                print(f"\n✅ COMPLETE SPACES ({len(complete_spaces)})")
                print("   (Database record + Tables exist)")
                print("-" * 40)
                for space_id, info in complete_spaces:
                    print(self.format_space_info(
                        info['data'], 
                        info['tables_exist'], 
                        info['table_error'], 
                        info['source']
                    ))
            
            # Display incomplete spaces
            if incomplete_spaces:
                print(f"\n⚠️ INCOMPLETE SPACES ({len(incomplete_spaces)})")
                print("   (Database record exists but tables missing or other issues)")
                print("-" * 60)
                for space_id, info in incomplete_spaces:
                    print(self.format_space_info(
                        info['data'], 
                        info['tables_exist'], 
                        info['table_error'], 
                        info['source']
                    ))
            
            # Display registry-only spaces
            if registry_only_spaces:
                print(f"\n📋 REGISTRY-ONLY SPACES ({len(registry_only_spaces)})")
                print("   (In Space Manager registry but no database record)")
                print("-" * 50)
                for space_id, info in registry_only_spaces:
                    print(self.format_space_info(
                        info['data'], 
                        info['tables_exist'], 
                        info['table_error'], 
                        info['source']
                    ))
            
            # Display orphaned spaces
            if orphaned_spaces:
                print(f"\n🚨 ORPHANED SPACES ({len(orphaned_spaces)})")
                print("   (Tables exist but no database record)")
                print("-" * 45)
                for space_id in orphaned_spaces:
                    print(self.format_orphaned_space_info(space_id))
        
        # Display consistency analysis
        print(f"\n🔍 CONSISTENCY ANALYSIS")
        print("=" * 30)
        
        api_count = len(api_spaces)
        db_count = len(db_spaces)
        sm_count = len(sm_spaces)
        orphaned_count = len(orphaned_spaces)
        
        if api_count == db_count == sm_count and orphaned_count == 0:
            print("   ✅ PERFECT CONSISTENCY: All sources match, no orphaned spaces")
        else:
            print("   ⚠️ INCONSISTENCIES DETECTED:")
            if api_count != db_count:
                print(f"      • API count ({api_count}) != Database count ({db_count})")
            if db_count != sm_count:
                print(f"      • Database count ({db_count}) != Space Manager count ({sm_count})")
            if orphaned_count > 0:
                print(f"      • {orphaned_count} orphaned spaces found")
        
        # Display recommendations
        print(f"\n💡 RECOMMENDATIONS")
        print("-" * 20)
        
        if orphaned_spaces:
            print("   🧹 Clean up orphaned spaces:")
            print("      • Use Space Manager cleanup functions")
            print("      • Or manually drop orphaned tables")
        
        if incomplete_spaces:
            print("   🔧 Fix incomplete spaces:")
            print("      • Recreate missing tables")
            print("      • Or remove incomplete database records")
        
        if not (complete_spaces or incomplete_spaces or orphaned_spaces):
            print("   🎉 System is clean - no issues detected!")
        
        print(f"\n✅ Space listing and validation completed successfully!")
    
    async def teardown(self) -> None:
        """Clean up test environment."""
        try:
            print("\n🧹 Tearing down validator environment...")
            
            if self.db_impl and self.db_impl.is_connected():
                await self.db_impl.disconnect()
                print("   ✅ Disconnected from database")
            
        except Exception as e:
            print(f"   ⚠️ Teardown warning: {str(e)}")


async def main():
    """Main execution function."""
    validator = SpaceListingValidator()
    
    try:
        # Setup
        if not await validator.setup():
            print("❌ Setup failed - aborting validation")
            return
        
        # Run comprehensive listing
        await validator.run_comprehensive_listing()
        
    except Exception as e:
        print(f"💥 Validation failed: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        # Teardown
        await validator.teardown()


if __name__ == "__main__":
    asyncio.run(main())
