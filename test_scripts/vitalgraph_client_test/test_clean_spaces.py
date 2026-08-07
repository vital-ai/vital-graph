#!/usr/bin/env python3
"""
List all spaces in VitalGraph and show total count.
Useful for identifying old test spaces that need cleanup.
"""

import sys
import os
from pathlib import Path

# Add project root to Python path for imports
# `parent.parent` is test_scripts/, not the project root — `vitalgraph`
# lives one level further up, so this used to fail at `import vitalgraph`.
# test_scripts/ is appended (not inserted) so it cannot shadow packages in
# this directory: test_scripts/sparql/ vs vitalgraph_client_test/sparql/.
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.append(str(project_root / "test_scripts"))

import asyncio
from vitalgraph.client.vitalgraph_client import VitalGraphClient


async def list_all_spaces():
    """List all spaces and print details."""
    
    # Initialize client with config
    # Configuration loaded from environment variables
    client = VitalGraphClient()
    
    try:
        # Open connection
        await client.open()
        print("✅ Connected to VitalGraph")
        print("=" * 80)
        
        # List all spaces
        print("\n📋 Listing all spaces...\n")
        spaces_response = await client.spaces.list_spaces()
        
        if not spaces_response.is_success:
            print(f"❌ Failed to list spaces: {spaces_response.error_message}")
            return
        
        # Get space list (SpacesListResponse has spaces attribute directly)
        spaces = spaces_response.spaces
        total_count = spaces_response.count
        
        print(f"📊 Total Spaces: {total_count}")
        print("=" * 80)
        
        if total_count == 0:
            print("\nℹ️  No spaces found")
            return
        
        # Print each space
        for i, space in enumerate(spaces, 1):
            space_id = space.space
            space_name = space.space_name if hasattr(space, 'space_name') else 'N/A'
            update_time = space.update_time if hasattr(space, 'update_time') else 'N/A'
            description = space.space_description if hasattr(space, 'space_description') else None
            
            print(f"\n{i}. Space ID: {space_id}")
            print(f"   Name: {space_name}")
            print(f"   Last Updated: {update_time}")
            if description:
                print(f"   Description: {description}")
        
        print("\n" + "=" * 80)
        print(f"\n✅ Listed {total_count} space(s)")
        
        # Identify potential test spaces
        test_spaces = [s for s in spaces if 'test' in s.space.lower()]
        if test_spaces:
            print(f"\n⚠️  Found {len(test_spaces)} potential test space(s):")
            for space in test_spaces:
                print(f"   - {space.space}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Close client
        await client.close()
        print("\n✅ Client closed")


if __name__ == "__main__":
    asyncio.run(list_all_spaces())
