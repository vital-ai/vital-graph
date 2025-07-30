#!/usr/bin/env python3
"""
Simple test script to verify the quads() generator is working correctly.
"""

import asyncio
import sys
import os

# Add the project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl

async def test_quads_generator():
    """Test the quads() async generator to ensure it doesn't hang."""
    print("🚀 Testing quads() generator")
    print("=" * 50)
    
    try:
        # Initialize VitalGraphImpl
        config_path = os.path.join(project_root, "vitalgraphdb_config", "vitalgraphdb-config.yaml")
        print(f"Loading config from: {config_path}")
        
        vitalgraph_impl = VitalGraphImpl(config_path)
        print("✅ VitalGraphImpl initialized")
        
        # Connect to database
        await vitalgraph_impl.connect()
        print("✅ Database connected")
        
        # Get space implementation
        db_impl = vitalgraph_impl.get_db_impl()
        space_impl = db_impl.get_space_impl()
        print("✅ Space implementation obtained")
        
        # Test the quads() generator with a simple pattern
        print("\n🔍 Testing quads() generator...")
        quad_pattern = (None, None, None, None)  # Get all quads
        
        print("   Creating async generator...")
        quad_generator = space_impl.quads("space_one", quad_pattern)
        print("   ✅ Generator created successfully")
        
        print("   Testing first few results...")
        count = 0
        async for quad, contexts in quad_generator:
            count += 1
            if count == 1:
                print(f"   ✅ First quad retrieved: {quad}")
            if count >= 5:  # Just test first 5 to verify it works
                print(f"   ⏹️  Stopping after {count} quads (test successful)")
                break
        
        if count > 0:
            print(f"🎉 SUCCESS: quads() generator is working correctly!")
            print(f"   Retrieved {count} quads without hanging")
        else:
            print("⚠️  No quads found (empty result set)")
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        try:
            await vitalgraph_impl.disconnect()
            print("✅ Database disconnected")
        except:
            pass
    
    return True

if __name__ == "__main__":
    success = asyncio.run(test_quads_generator())
    if success:
        print("\n🎉 Test completed successfully!")
        sys.exit(0)
    else:
        print("\n💥 Test failed!")
        sys.exit(1)
